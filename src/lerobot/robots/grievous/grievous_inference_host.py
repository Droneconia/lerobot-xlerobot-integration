#!/usr/bin/env python

# Copyright 2025 Alexander Nettekoven, The University of Texas at Austin
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Grievous Inference Host - Runs on RPi5 to receive remote policy commands.

This daemon:
- Instantiates the Grievous robot (follower arms + base + head + leader arms)
- Opens ZMQ sockets to receive actions and send observations
- Runs a control loop that:
  * Receives actions from remote policy (via ZMQ PULL socket)
  * Executes actions on follower robot
  * Reads observations from follower (cameras + state)
  * Encodes camera images to base64
  * Sends observations to remote client (via ZMQ PUSH socket)
  * Implements watchdog timer for safety (stops base if no commands)
  
Note: Leader arms are instantiated but not actively used in this mode.
They are available for future overwrite functionality.
"""

import argparse
import base64
import json
import logging
import time

import cv2
import numpy as np
import zmq

from .grievous import Grievous
from .config_grievous import GrievousConfig, GrievousHostConfig

logger = logging.getLogger(__name__)


class GrievousInferenceHost:
    """ZMQ-based host daemon for Grievous robot running on RPi5.
    
    Manages bidirectional communication with remote client:
    - Receives actions via ZMQ PULL socket
    - Sends observations via ZMQ PUSH socket
    """

    def __init__(self, config: GrievousHostConfig):
        """Initialize ZMQ sockets for command and observation streaming.
        
        Supports two modes:
        - Normal mode (remote_ip=None): Bind locally and wait for client (server mode)
        - Reverse mode (remote_ip set): Connect to remote client (client mode)
        
        Args:
            config: Host configuration (ports, timeouts, loop frequency, remote_ip)
        """
        self.zmq_context = zmq.Context()
        
        if config.remote_ip is not None:
            # Reverse connection mode: CONNECT to remote client (client mode)
            # Used when host is behind NAT and needs to reach out to remote server
            logger.info(f"Connecting to remote client at {config.remote_ip}:{config.port_zmq_cmd}/{config.port_zmq_observations}...")
            
            # Command socket: RECEIVE actions from client (PULL)
            self.zmq_cmd_socket = self.zmq_context.socket(zmq.PULL)
            # Set socket options for better reliability
            self.zmq_cmd_socket.setsockopt(zmq.RCVHWM, 1)  # Receive High Water Mark = 1 (keep only latest)
            self.zmq_cmd_socket.setsockopt(zmq.LINGER, 0)  # Don't wait on close
            cmd_address = f"tcp://{config.remote_ip}:{config.port_zmq_cmd}"
            self.zmq_cmd_socket.connect(cmd_address)
            logger.info(f"✓ Command socket (PULL) connected to {cmd_address} (RCVHWM=1)")
            
            # Observation socket: send observations to client (PUSH)
            self.zmq_observation_socket = self.zmq_context.socket(zmq.PUSH)
            self.zmq_observation_socket.setsockopt(zmq.CONFLATE, 1)  # Keep only latest message
            obs_address = f"tcp://{config.remote_ip}:{config.port_zmq_observations}"
            self.zmq_observation_socket.connect(obs_address)
            logger.info(f"✓ Observation socket (PUSH) connected to {obs_address}")
            
            # Test connectivity by sending a dummy observation
            logger.info("Testing observation socket connectivity...")
            try:
                test_msg = json.dumps({"test": "connectivity_check"})
                self.zmq_observation_socket.send_string(test_msg, flags=zmq.NOBLOCK)
                logger.info("✓ Test observation sent successfully")
            except Exception as e:
                logger.error(f"✗ Failed to send test observation: {e}")
            
            # ZMQ slow joiner fix: Allow time for bidirectional connection to fully establish
            # This ensures the command socket is ready to receive before the remote starts sending
            # 2s delay accounts for network latency and script startup timing differences
            logger.info("Waiting for ZMQ bidirectional connection to stabilize (2s)...")
            import time
            time.sleep(2.0)
            logger.info("✓ Connection stabilized, ready to send/receive")
            
        else:
            # Normal mode: BIND locally (server mode)
            logger.info(f"Binding GrievousInferenceHost on ports {config.port_zmq_cmd}/{config.port_zmq_observations}...")
            
            # Command socket: RECEIVE actions from client (PULL)
            self.zmq_cmd_socket = self.zmq_context.socket(zmq.PULL)
            # Note: CONFLATE doesn't work with PULL sockets - removed for proper message delivery
            self.zmq_cmd_socket.bind(f"tcp://*:{config.port_zmq_cmd}")
            logger.info(f"Command socket (PULL) bound to tcp://*:{config.port_zmq_cmd}")
            
            # Observation socket: send observations to client
            self.zmq_observation_socket = self.zmq_context.socket(zmq.PUSH)
            self.zmq_observation_socket.setsockopt(zmq.CONFLATE, 1)  # Keep only latest message
            self.zmq_observation_socket.bind(f"tcp://*:{config.port_zmq_observations}")
            logger.info(f"Observation socket (PUSH) bound to tcp://*:{config.port_zmq_observations}")
        
        # Configuration
        self.connection_time_s = config.connection_time_s
        self.watchdog_timeout_ms = config.watchdog_timeout_ms
        self.max_loop_freq_hz = config.max_loop_freq_hz
        self.dry_run = config.dry_run
        
        logger.info(
            f"GrievousInferenceHost initialized: watchdog={config.watchdog_timeout_ms}ms, "
            f"freq={config.max_loop_freq_hz}Hz, dry_run={config.dry_run}"
        )

    def disconnect(self) -> None:
        """Close ZMQ sockets and terminate context."""
        logger.info("Closing GrievousInferenceHost ZMQ sockets...")
        self.zmq_observation_socket.close()
        self.zmq_cmd_socket.close()
        self.zmq_context.term()
        logger.info("GrievousInferenceHost disconnected")


def main():
    """Main entry point for Grievous inference host daemon.
    
    Runs control loop that:
    1. Receives actions from remote policy (via ZMQ)
    2. Executes actions on Grievous follower
    3. Reads observations from Grievous (follower + cameras)
    4. Encodes camera images to base64
    5. Sends observations to remote client (via ZMQ)
    6. Implements watchdog safety timer
    """
    # Print startup banner BEFORE logging setup to confirm script is running
    print("=" * 80)
    print("GRIEVOUS INFERENCE HOST STARTING")
    print("=" * 80)
    
    parser = argparse.ArgumentParser(description="Grievous inference host daemon")
    parser.add_argument("--remote-ip", type=str, default=None,
                        help="Remote client IP for reverse connection (e.g., Runpod IP)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log actions but don't execute on robot (safe testing)")
    parser.add_argument("--duration", type=int, default=300,
                        help="Connection duration in seconds (default: 300)")
    parser.add_argument("--port-cmd", type=int, default=5555,
                        help="Command port (default: 5555, use external port if port-mapped)")
    parser.add_argument("--port-obs", type=int, default=5556,
                        help="Observation port (default: 5556, use external port if port-mapped)")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable DEBUG level logging")
    args = parser.parse_args()
    
    # Configure logging - force reconfiguration to override any previous setup
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        force=True  # Force reconfiguration even if logging was already initialized
    )
    
    # Also set the root logger explicitly
    logging.getLogger().setLevel(log_level)
    
    # Suppress noisy third-party library logs unless in verbose mode
    if not args.verbose:
        logging.getLogger('draccus').setLevel(logging.WARNING)
        logging.getLogger('lerobot.cameras').setLevel(logging.INFO)
        logging.getLogger('lerobot.motors').setLevel(logging.INFO)
        logging.getLogger('lerobot.teleoperators').setLevel(logging.INFO)
    
    # Print configuration immediately
    print(f"\n🤖 Configuration:")
    print(f"   Remote IP:    {args.remote_ip if args.remote_ip else 'None (local mode)'}")
    print(f"   Command port: {args.port_cmd}")
    print(f"   Obs port:     {args.port_obs}")
    print(f"   Duration:     {args.duration}s")
    print(f"   Dry run:      {args.dry_run}")
    print(f"   Verbose:      {args.verbose}")
    print("=" * 80 + "\n")
    
    if args.dry_run:
        logger.warning("⚠️  DRY RUN MODE: Actions will be logged but NOT executed on robot")
    
    logger.info("Configuring Grievous robot...")
    # Use proper ID for calibration management (avoids None collisions)
    robot_config = GrievousConfig(id="grievous_robot")
    robot = Grievous(robot_config)
    
    logger.info("Connecting Grievous robot (using existing calibration)...")
    robot.connect(calibrate=False)  # Use existing calibration from cache
    logger.info("Grievous connected successfully")
    # Note: Leader arms are connected but not actively used in inference mode
    # They are available for future overwrite functionality
    
    logger.info("Starting GrievousInferenceHost daemon...")
    logger.info(f"Configuration: remote_ip={args.remote_ip}, cmd_port={args.port_cmd}, obs_port={args.port_obs}")
    host_config = GrievousHostConfig(
        connection_time_s=args.duration,
        remote_ip=args.remote_ip,
        dry_run=args.dry_run,
        port_zmq_cmd=args.port_cmd,
        port_zmq_observations=args.port_obs
    )
    host = GrievousInferenceHost(host_config)
    
    last_cmd_time = time.time()
    watchdog_active = False
    logger.info("Waiting for commands from remote policy...")
    
    try:
        # Main control loop
        start = time.perf_counter()
        duration = 0
        
        iteration_count = 0
        while duration < host.connection_time_s:
            loop_start_time = time.perf_counter()
            iteration_count += 1
            
            # Log only every 30th iteration (once per second at 30Hz) to avoid spam
            if iteration_count % 30 == 1:
                logger.info(f"Loop iteration #{iteration_count}, duration={duration:.1f}s")
            
            # 1. Try to receive action commands from remote policy
            try:
                msg = host.zmq_cmd_socket.recv_string(zmq.NOBLOCK)
                logger.debug(f"recv_string returned: {len(msg) if msg else 0} bytes")
                data = dict(json.loads(msg))
                
                # DEBUG: Log first action to see keys/values
                if not hasattr(host, '_logged_first_action'):
                    logger.info(f"✓✓✓ FIRST ACTION RECEIVED! ✓✓✓")
                    logger.info(f"  Keys: {list(data.keys())}")
                    logger.info(f"  First 3 values: {dict(list(data.items())[:3])}")
                    host._logged_first_action = True
                
                if host.dry_run:
                    # Dry run mode: Log action but don't execute
                    if not hasattr(host, '_action_recv_count'):
                        host._action_recv_count = 0
                    host._action_recv_count += 1
                    if host._action_recv_count % 30 == 1:  # Log every 30th action
                        logger.info(f"[DRY RUN] Action #{host._action_recv_count} received: {len(data)} keys")
                else:
                    # Execute action on follower (XLerobot component)
                    robot.send_action(data)
                    logger.info(f"Action received and executed: {len(data)} keys")
                
                # Reset watchdog timer
                last_cmd_time = time.time()
                watchdog_active = False
                
            except zmq.Again as e:
                # No command available (non-blocking)
                if not hasattr(host, '_no_cmd_logged'):
                    logger.warning(f"✗ No command received yet (zmq.Again exception: {e})")
                    host._no_cmd_logged = True
                logger.debug("zmq.Again - no message available")
            except json.JSONDecodeError as e:
                logger.error(f"✗ JSON decode error: {e}, msg length: {len(msg) if 'msg' in locals() else 'N/A'}")
            except Exception as e:
                logger.error(f"✗ Message fetching/execution failed: {type(e).__name__}: {e}", exc_info=True)
            
            # 2. Check watchdog timer
            now = time.time()
            if (now - last_cmd_time > host.watchdog_timeout_ms / 1000) and not watchdog_active:
                logger.warning(
                    f"Command not received for {host.watchdog_timeout_ms}ms. Stopping base for safety."
                )
                watchdog_active = True
                # Stop the mobile base (safety feature)
                robot.xlerobot.stop_base()
            
            # 3. Get observation from Grievous (follower + cameras)
            # Note: Leader arms are not read in inference mode
            if iteration_count % 30 == 1:
                logger.info("Getting observation from robot...")
            last_observation = robot.get_observation()
            if iteration_count % 30 == 1:
                logger.info(f"Got observation with {len(last_observation)} keys")
            
            # 4. Encode camera images to base64 for network transmission
            logger.debug("Encoding camera images...")
            for cam_key in robot.xlerobot.cameras.keys():
                if cam_key in last_observation:
                    # Check if image is valid (not None and not empty)
                    try:
                        img = last_observation[cam_key]
                        if img is None or not isinstance(img, np.ndarray) or img.size == 0:
                            logger.debug(f"Camera {cam_key} returned empty/invalid image, skipping encode")
                            last_observation[cam_key] = ""
                            continue
                        
                        ret, buffer = cv2.imencode(
                            ".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 90]
                        )
                        if ret:
                            last_observation[cam_key] = base64.b64encode(buffer).decode("utf-8")
                        else:
                            logger.warning(f"Failed to encode camera {cam_key}")
                            last_observation[cam_key] = ""
                    except Exception as e:
                        logger.error(f"Failed to encode camera {cam_key}: {e}")
                        last_observation[cam_key] = ""
            
            # 5. Send observation to remote client
            try:
                obs_json = json.dumps(last_observation)
                host.zmq_observation_socket.send_string(obs_json, flags=zmq.NOBLOCK)
                if iteration_count % 30 == 1:
                    logger.info(f"Sent observation #{iteration_count}: {len(obs_json)} bytes")
            except zmq.Again:
                logger.warning("Dropping observation, no client connected (zmq.Again)")
            except Exception as e:
                logger.error(f"Failed to send observation: {e}")
            
            # 6. Rate limiting
            elapsed = time.perf_counter() - loop_start_time
            sleep_time = max(1 / host.max_loop_freq_hz - elapsed, 0)
            time.sleep(sleep_time)
            
            duration = time.perf_counter() - start
        
        logger.info(f"Connection time limit reached ({host.connection_time_s}s). Shutting down.")
    
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down...")
    
    finally:
        logger.info("Cleaning up Grievous inference host...")
        robot.disconnect()
        host.disconnect()
        logger.info("Grievous inference host shutdown complete")


if __name__ == "__main__":
    main()

