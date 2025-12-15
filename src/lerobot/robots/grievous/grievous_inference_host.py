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


def generate_mock_observation():
    """Generate synthetic observation for latency testing without hardware.
    
    Returns:
        dict: Mock observation matching Grievous robot's observation structure
    """
    # Generate synthetic camera images (640x480 RGB)
    # Use colored noise to simulate realistic image data size
    # NOTE: Use ORIGINAL camera names (left_wrist, right_wrist, head) so rename_map can work
    mock_images = {}
    for cam_name in ["left_wrist", "right_wrist", "head"]:
        # Create colored noise image
        img = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
        # Add a simple pattern to make it look more like a real image
        img[:, :, 0] = (img[:, :, 0] * 0.6 + 100).astype(np.uint8)  # Red channel bias
        img[:, :, 1] = (img[:, :, 1] * 0.8 + 80).astype(np.uint8)   # Green channel bias
        img[:, :, 2] = (img[:, :, 2] * 0.7 + 90).astype(np.uint8)   # Blue channel bias
        mock_images[cam_name] = img
    
    # Generate synthetic state (17-dimensional action space)
    # Match the structure from Grievous robot
    # NOTE: Convert to Python float for JSON serialization compatibility
    mock_state = {
        # Mobile base (3 DOF: x, y, yaw)
        "observation.state.base.x": float(np.random.uniform(-0.1, 0.1)),
        "observation.state.base.y": float(np.random.uniform(-0.1, 0.1)),
        "observation.state.base.yaw": float(np.random.uniform(-0.2, 0.2)),
        # Follower arms (assumed 7 DOF each for typical mobile manipulator)
        "observation.state.follower.left_arm.joint_0": float(np.random.uniform(-np.pi, np.pi)),
        "observation.state.follower.left_arm.joint_1": float(np.random.uniform(-np.pi/2, np.pi/2)),
        "observation.state.follower.left_arm.joint_2": float(np.random.uniform(-np.pi, np.pi)),
        "observation.state.follower.left_arm.joint_3": float(np.random.uniform(-np.pi/2, np.pi/2)),
        "observation.state.follower.left_arm.joint_4": float(np.random.uniform(-np.pi, np.pi)),
        "observation.state.follower.left_arm.joint_5": float(np.random.uniform(-np.pi/2, np.pi/2)),
        "observation.state.follower.left_arm.joint_6": float(np.random.uniform(-np.pi, np.pi)),
        "observation.state.follower.right_arm.joint_0": float(np.random.uniform(-np.pi, np.pi)),
        "observation.state.follower.right_arm.joint_1": float(np.random.uniform(-np.pi/2, np.pi/2)),
        "observation.state.follower.right_arm.joint_2": float(np.random.uniform(-np.pi, np.pi)),
        "observation.state.follower.right_arm.joint_3": float(np.random.uniform(-np.pi/2, np.pi/2)),
        "observation.state.follower.right_arm.joint_4": float(np.random.uniform(-np.pi, np.pi)),
        "observation.state.follower.right_arm.joint_5": float(np.random.uniform(-np.pi/2, np.pi/2)),
        "observation.state.follower.right_arm.joint_6": float(np.random.uniform(-np.pi, np.pi)),
    }
    
    # Combine images and state
    observation = {**mock_images, **mock_state}
    return observation


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
    parser.add_argument("--mock-hardware", action="store_true",
                        help="Use synthetic observations (no physical robot needed)")
    parser.add_argument("--latency-benchmark", action="store_true",
                        help="Synchronous latency measurement mode (send one obs, wait for response)")
    parser.add_argument("--num-measurements", type=int, default=50,
                        help="Number of latency measurements to collect (default: 50)")
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
    print(f"   Mock HW:      {args.mock_hardware}")
    print(f"   Latency mode: {args.latency_benchmark}")
    if args.latency_benchmark:
        print(f"   Measurements: {args.num_measurements}")
    print(f"   Verbose:      {args.verbose}")
    print("=" * 80 + "\n")
    
    if args.dry_run:
        logger.warning("⚠️  DRY RUN MODE: Actions will be logged but NOT executed on robot")
    
    if args.mock_hardware:
        logger.warning("🤖 MOCK HARDWARE MODE: Using synthetic observations for latency testing")
        robot = None  # No physical robot in mock mode
    else:
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
    
    # Latency benchmark mode: Send one observation, wait for response, measure time
    if args.latency_benchmark:
        if not args.mock_hardware:
            logger.error("Latency benchmark mode requires --mock-hardware flag")
            return
        
        logger.info("=" * 80)
        logger.info("LATENCY BENCHMARK MODE")
        logger.info("=" * 80)
        logger.info(f"Will send {args.num_measurements} observations synchronously and measure round-trip time")
        logger.info("=" * 80)
        
        latencies = []
        timeout_ms = 30000  # 30 second timeout per request
        
        for i in range(args.num_measurements):
            # Generate observation
            observation = generate_mock_observation()
            
            # Encode images
            for cam_key in ["left_wrist", "right_wrist", "head"]:
                if cam_key in observation:
                    img = observation[cam_key]
                    ret, buffer = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                    if ret:
                        observation[cam_key] = base64.b64encode(buffer).decode("utf-8")
                    else:
                        logger.error(f"Failed to encode {cam_key}")
            
            # Send observation and record time
            try:
                obs_json = json.dumps(observation)
                logger.debug(f"  Observation has {len(observation)} keys: {list(observation.keys())[:5]}")
                logger.debug(f"  JSON length: {len(obs_json)} bytes")
            except (TypeError, ValueError) as e:
                logger.error(f"[{i+1}/{args.num_measurements}] Failed to serialize observation to JSON: {e}")
                logger.error(f"  Observation keys: {list(observation.keys())}")
                logger.error(f"  Sample values: {[(k, type(v).__name__) for k, v in list(observation.items())[:5]]}")
                continue
            
            send_time = time.perf_counter()
            
            try:
                host.zmq_observation_socket.send_string(obs_json, flags=zmq.NOBLOCK)
                logger.info(f"[{i+1}/{args.num_measurements}] Sent observation ({len(obs_json)} bytes, {len(observation)} keys), waiting for action...")
            except zmq.Again:
                logger.error(f"[{i+1}/{args.num_measurements}] Failed to send observation (socket busy)")
                continue
            
            # Wait for action response (blocking with timeout)
            poller = zmq.Poller()
            poller.register(host.zmq_cmd_socket, zmq.POLLIN)
            
            socks = dict(poller.poll(timeout_ms))
            
            if host.zmq_cmd_socket in socks and socks[host.zmq_cmd_socket] == zmq.POLLIN:
                # Receive action
                msg = host.zmq_cmd_socket.recv_string(zmq.NOBLOCK)
                receive_time = time.perf_counter()
                
                # Calculate latency
                latency_ms = (receive_time - send_time) * 1000
                latencies.append(latency_ms)
                
                logger.info(f"[{i+1}/{args.num_measurements}] ✓ Received action in {latency_ms:.2f} ms")
                
                # Parse to verify it's valid
                try:
                    action_data = json.loads(msg)
                    logger.debug(f"  Action keys: {len(action_data)}")
                except json.JSONDecodeError as e:
                    logger.warning(f"  Invalid JSON in action: {e}")
            else:
                logger.error(f"[{i+1}/{args.num_measurements}] ✗ Timeout waiting for action (>{timeout_ms}ms)")
        
        # Print final statistics
        if len(latencies) > 0:
            logger.info("")
            logger.info("=" * 80)
            logger.info("📊 LATENCY BENCHMARK RESULTS")
            logger.info("=" * 80)
            logger.info(f"Successful measurements: {len(latencies)}/{args.num_measurements}")
            logger.info(f"Mean latency:            {np.mean(latencies):.2f} ms")
            logger.info(f"Std deviation:           {np.std(latencies):.2f} ms")
            logger.info(f"Min latency:             {np.min(latencies):.2f} ms")
            logger.info(f"Max latency:             {np.max(latencies):.2f} ms")
            logger.info(f"Median latency:          {np.median(latencies):.2f} ms")
            logger.info(f"95th percentile:         {np.percentile(latencies, 95):.2f} ms")
            logger.info(f"99th percentile:         {np.percentile(latencies, 99):.2f} ms")
            logger.info("=" * 80)
        else:
            logger.error("No successful measurements collected!")
        
        # Clean up and exit
        host.disconnect()
        logger.info("Latency benchmark complete")
        return
    
    last_cmd_time = time.time()
    watchdog_active = False
    logger.info("Waiting for commands from remote policy...")
    
    # Latency tracking for mock mode
    latencies = []  # Store round-trip times (observation sent → action received)
    last_observation_sent_time = None
    
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
                action_received_time = time.perf_counter()  # Timestamp for latency measurement
                logger.debug(f"recv_string returned: {len(msg) if msg else 0} bytes")
                data = dict(json.loads(msg))
                
                # Calculate latency if in mock mode and we sent an observation
                if args.mock_hardware and last_observation_sent_time is not None:
                    latency_ms = (action_received_time - last_observation_sent_time) * 1000
                    latencies.append(latency_ms)
                    if len(latencies) % 30 == 1:  # Log stats every 30 actions
                        mean_lat = np.mean(latencies)
                        std_lat = np.std(latencies)
                        min_lat = np.min(latencies)
                        max_lat = np.max(latencies)
                        logger.info(f"📊 LATENCY [{len(latencies)} samples]: "
                                  f"mean={mean_lat:.1f}ms, std={std_lat:.1f}ms, "
                                  f"min={min_lat:.1f}ms, max={max_lat:.1f}ms")
                
                # DEBUG: Log first action to see keys/values
                if not hasattr(host, '_logged_first_action'):
                    logger.info(f"✓✓✓ FIRST ACTION RECEIVED! ✓✓✓")
                    logger.info(f"  Keys: {list(data.keys())}")
                    logger.info(f"  First 3 values: {dict(list(data.items())[:3])}")
                    host._logged_first_action = True
                
                if host.dry_run or args.mock_hardware:
                    # Dry run or mock mode: Log action but don't execute
                    if not hasattr(host, '_action_recv_count'):
                        host._action_recv_count = 0
                    host._action_recv_count += 1
                    if host._action_recv_count % 30 == 1:  # Log every 30th action
                        mode_str = "MOCK" if args.mock_hardware else "DRY RUN"
                        logger.info(f"[{mode_str}] Action #{host._action_recv_count} received: {len(data)} keys")
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
                    f"Command not received for {host.watchdog_timeout_ms}ms. "
                    f"{'Would stop base' if args.mock_hardware else 'Stopping base'} for safety."
                )
                watchdog_active = True
                # Stop the mobile base (safety feature)
                if not args.mock_hardware:
                    robot.xlerobot.stop_base()
            
            # 3. Get observation from Grievous (follower + cameras) or generate mock
            if args.mock_hardware:
                # Generate synthetic observation for latency testing
                if iteration_count % 30 == 1:
                    logger.info("Generating mock observation...")
                last_observation = generate_mock_observation()
                if iteration_count % 30 == 1:
                    logger.info(f"Generated mock observation with {len(last_observation)} keys")
            else:
                # Note: Leader arms are not read in inference mode
                if iteration_count % 30 == 1:
                    logger.info("Getting observation from robot...")
                last_observation = robot.get_observation()
                if iteration_count % 30 == 1:
                    logger.info(f"Got observation with {len(last_observation)} keys")
            
            # 4. Encode camera images to base64 for network transmission
            if not args.mock_hardware:
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
            else:
                # Mock mode: Encode synthetic images
                logger.debug("Encoding mock camera images...")
                for cam_key in ["left_wrist", "right_wrist", "head"]:
                    if cam_key in last_observation:
                        try:
                            img = last_observation[cam_key]
                            ret, buffer = cv2.imencode(
                                ".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 90]
                            )
                            if ret:
                                last_observation[cam_key] = base64.b64encode(buffer).decode("utf-8")
                            else:
                                logger.warning(f"Failed to encode mock camera {cam_key}")
                                last_observation[cam_key] = ""
                        except Exception as e:
                            logger.error(f"Failed to encode mock camera {cam_key}: {e}")
                            last_observation[cam_key] = ""
            
            # 5. Send observation to remote client
            try:
                obs_json = json.dumps(last_observation)
                host.zmq_observation_socket.send_string(obs_json, flags=zmq.NOBLOCK)
                last_observation_sent_time = time.perf_counter()  # Track timestamp for latency
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
        # Print final latency statistics in mock mode
        if args.mock_hardware and len(latencies) > 0:
            logger.info("=" * 80)
            logger.info("📊 FINAL LATENCY STATISTICS")
            logger.info("=" * 80)
            logger.info(f"Total samples:     {len(latencies)}")
            logger.info(f"Mean latency:      {np.mean(latencies):.2f} ms")
            logger.info(f"Std deviation:     {np.std(latencies):.2f} ms")
            logger.info(f"Min latency:       {np.min(latencies):.2f} ms")
            logger.info(f"Max latency:       {np.max(latencies):.2f} ms")
            logger.info(f"Median latency:    {np.median(latencies):.2f} ms")
            logger.info(f"95th percentile:   {np.percentile(latencies, 95):.2f} ms")
            logger.info(f"99th percentile:   {np.percentile(latencies, 99):.2f} ms")
            logger.info("=" * 80)
        
        logger.info("Cleaning up Grievous inference host...")
        if robot is not None:
            robot.disconnect()
        host.disconnect()
        logger.info("Grievous inference host shutdown complete")


if __name__ == "__main__":
    main()

