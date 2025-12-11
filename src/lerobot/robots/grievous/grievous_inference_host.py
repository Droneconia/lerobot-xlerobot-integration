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
            self.zmq_cmd_socket.connect(f"tcp://{config.remote_ip}:{config.port_zmq_cmd}")
            logger.info(f"Command socket (PULL) connected to tcp://{config.remote_ip}:{config.port_zmq_cmd}")
            
            # Observation socket: send observations to client (PUSH)
            self.zmq_observation_socket = self.zmq_context.socket(zmq.PUSH)
            self.zmq_observation_socket.setsockopt(zmq.CONFLATE, 1)  # Keep only latest message
            self.zmq_observation_socket.connect(f"tcp://{config.remote_ip}:{config.port_zmq_observations}")
            logger.info(f"Observation socket (PUSH) connected to tcp://{config.remote_ip}:{config.port_zmq_observations}")
            
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
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
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
        
        while duration < host.connection_time_s:
            loop_start_time = time.perf_counter()
            
            # 1. Try to receive action commands from remote policy
            try:
                msg = host.zmq_cmd_socket.recv_string(zmq.NOBLOCK)
                data = dict(json.loads(msg))
                
                # DEBUG: Log first action to see keys/values
                if not hasattr(host, '_logged_first_action'):
                    logger.info(f"FIRST ACTION KEYS: {list(data.keys())}")
                    logger.info(f"FIRST ACTION VALUES (first 3): {dict(list(data.items())[:3])}")
                    host._logged_first_action = True
                
                if host.dry_run:
                    # Dry run mode: Log action but don't execute
                    logger.info(f"[DRY RUN] Action received (not executed): {len(data)} keys")
                    logger.info(f"[DRY RUN] Action values: {data}")
                else:
                    # Execute action on follower (XLerobot component)
                    robot.send_action(data)
                    logger.info(f"Action received and executed: {len(data)} keys")
                
                # Reset watchdog timer
                last_cmd_time = time.time()
                watchdog_active = False
                
            except zmq.Again:
                # No command available (non-blocking)
                if not watchdog_active:
                    logger.debug("No command available")
            except Exception as e:
                logger.error(f"Message fetching/execution failed: {e}")
            
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
            last_observation = robot.get_observation()
            
            # 4. Encode camera images to base64 for network transmission
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
                host.zmq_observation_socket.send_string(
                    json.dumps(last_observation), flags=zmq.NOBLOCK
                )
            except zmq.Again:
                logger.debug("Dropping observation, no client connected")
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

