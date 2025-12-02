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

"""Grievous Host Daemon - Runs on RPi5 to manage physical robot hardware.

This daemon:
- Instantiates the Grievous robot (follower arms + base + head + leader arms)
- Opens ZMQ sockets to send processed actions and observations
- Runs a control loop that:
  * Gets actions from leader arms
  * Processes actions through processor pipelines
  * Sends actions to follower (XLerobot)
  * Reads observations from both follower and leader
  * Encodes camera images to base64
  * Sends processed actions and observations back to client
  * Implements watchdog timer for safety (stops base if no commands)
"""

import base64
import json
import logging
import threading
import time

import cv2
import numpy as np
import zmq

from lerobot.processor import (
    RobotAction,
    RobotObservation,
    RobotProcessorPipeline,
    make_default_processors,
)

from .grievous import Grievous
from .config_grievous import GrievousConfig, GrievousHostConfig

logger = logging.getLogger(__name__)


class GrievousHost:
    """ZMQ-based host daemon for Grievous robot running on RPi5.
    
    Manages bidirectional communication with remote client:
    - Receives actions via ZMQ PULL socket
    - Sends observations via ZMQ PUSH socket
    """

    def __init__(self, config: GrievousHostConfig):
        """Initialize ZMQ sockets for command and observation streaming.
        
        Args:
            config: Host configuration (ports, timeouts, loop frequency)
        """
        self.zmq_context = zmq.Context()
        
        # Command socket: send processed actions to client
        self.zmq_cmd_socket = self.zmq_context.socket(zmq.PUSH)
        self.zmq_cmd_socket.setsockopt(zmq.CONFLATE, 1)  # Keep only latest message
        self.zmq_cmd_socket.bind(f"tcp://*:{config.port_zmq_cmd}")
        logger.info(f"Command socket bound to tcp://*:{config.port_zmq_cmd}")
        
        # Observation socket: send observations to client
        self.zmq_observation_socket = self.zmq_context.socket(zmq.PUSH)
        self.zmq_observation_socket.setsockopt(zmq.CONFLATE, 1)  # Keep only latest message
        self.zmq_observation_socket.bind(f"tcp://*:{config.port_zmq_observations}")
        logger.info(f"Observation socket bound to tcp://*:{config.port_zmq_observations}")
        
        # Configuration
        self.connection_time_s = config.connection_time_s
        self.watchdog_timeout_ms = config.watchdog_timeout_ms
        self.max_loop_freq_hz = config.max_loop_freq_hz
        self.teleop_freq_hz = config.teleop_freq_hz
        
        logger.info(f"GrievousHost initialized: watchdog={config.watchdog_timeout_ms}ms, main_freq={config.max_loop_freq_hz}Hz, teleop_freq={config.teleop_freq_hz}Hz")

    def disconnect(self) -> None:
        """Close ZMQ sockets and terminate context."""
        logger.info("Closing GrievousHost ZMQ sockets...")
        self.zmq_observation_socket.close()
        self.zmq_cmd_socket.close()
        self.zmq_context.term()
        logger.info("GrievousHost disconnected")


class TeleopControlThread:
    """Separate thread for teleop control that runs at higher refresh rate.
    
    This thread continuously:
    1. Gets actions from leader arms
    2. Processes actions through processor pipelines
    3. Sends actions to follower (XLerobot)
    
    The main loop can access the last processed action via get_last_action().
    """
    
    def __init__(
        self,
        robot: "Grievous",
        teleop_action_processor,
        robot_action_processor,
        freq_hz: int = 120,
    ):
        """Initialize teleop control thread.
        
        Args:
            robot: Grievous robot instance
            teleop_action_processor: Processor for teleop actions
            robot_action_processor: Processor for robot actions
            freq_hz: Refresh rate for teleop control loop
        """
        self.robot = robot
        self.teleop_action_processor = teleop_action_processor
        self.robot_action_processor = robot_action_processor
        self.freq_hz = freq_hz
        
        # Thread-safe storage for last action and observation
        self._lock = threading.Lock()
        self._last_robot_action: dict = {}
        self._last_observation: dict = {}
        self._running = False
        self._thread: threading.Thread | None = None
    
    def start(self) -> None:
        """Start the teleop control thread."""
        if self._running:
            logger.warning("Teleop control thread is already running")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._control_loop, daemon=True)
        self._thread.start()
        logger.info(f"Teleop control thread started at {self.freq_hz}Hz")
    
    def stop(self) -> None:
        """Stop the teleop control thread."""
        if not self._running:
            return
        
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                logger.warning("Teleop control thread did not stop gracefully")
            else:
                logger.info("Teleop control thread stopped")
    
    def _control_loop(self) -> None:
        """Main control loop running in separate thread."""
        while self._running:
            loop_start = time.perf_counter()
            
            try:
                
                # Get action from leader arms
                robot_action = self.robot.get_action()
                
                # Send action to follower
                self.robot.send_action(robot_action)
                
                # Update thread-safe storage
                with self._lock:
                    self._last_robot_action = robot_action
                    
            except Exception as e:
                logger.error(f"Error in teleop control loop: {e}", exc_info=True)
            
            # Rate limiting
            elapsed = time.perf_counter() - loop_start
            sleep_time = max(1 / self.freq_hz - elapsed, 0)
            if sleep_time > 0:
                time.sleep(sleep_time)
    
    def get_last_action(self) -> dict:
        """Get the last processed robot action (thread-safe).
        
        Returns:
            Dictionary containing the last robot action
        """
        with self._lock:
            return self._last_robot_action.copy()
    


def main():
    """Main entry point for Grievous host daemon.
    
    Runs control loop that:
    1. Gets actions from leader arms
    2. Processes actions through processor pipelines
    3. Sends actions to Grievous follower
    4. Reads observations from Grievous (follower + leader)
    5. Encodes camera images to base64
    6. Sends processed actions to remote client via command socket
    7. Sends observations to remote client via observation socket
    8. Implements watchdog safety timer
    """
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    logger.info("Configuring Grievous robot...")
    # Use proper ID for calibration management (avoids None collisions)
    robot_config = GrievousConfig(id="grievous_robot")
    robot = Grievous(robot_config)
    
    logger.info("Connecting Grievous robot (using existing calibration)...")
    robot.connect(calibrate=False)  # Use existing calibration from cache
    logger.info("Grievous connected successfully")
    
    logger.info("Starting GrievousHost daemon...")
    host_config = GrievousHostConfig()
    host = GrievousHost(host_config)

    teleop_action_processor, robot_action_processor, robot_observation_processor = make_default_processors()
    
    # Start teleop control thread (runs at higher refresh rate)
    teleop_thread = TeleopControlThread(
        robot=robot,
        teleop_action_processor=teleop_action_processor,
        robot_action_processor=robot_action_processor,
        freq_hz=host.teleop_freq_hz,
    )
    teleop_thread.start()
    
    last_cmd_time = time.time()
    watchdog_active = False
    logger.info("Waiting for commands from remote client...")
    
    try:
        # Main control loop
        start = time.perf_counter()
        duration = 0
        
        while duration < host.connection_time_s:
            loop_start_time = time.perf_counter()
            step_times = {}
            
            # Adapt when base and head controls are implemented
            # # 1. Receive action commands from client
            # step_start = time.perf_counter()
            # try:
            #     msg = host.zmq_cmd_socket.recv_string(zmq.NOBLOCK)
            #     data = dict(json.loads(msg))
                
            #     # Send action to follower (XLerobot component)
            #     robot.send_action(data)
            #     print(f"Sent action to follower: {data}")
                
            #     # Reset watchdog timer
            #     last_cmd_time = time.time()
            #     watchdog_active = False
                
            # except zmq.Again:
            #     # No command available (non-blocking)
            #     if not watchdog_active:
            #         logger.debug("No command available")
            # except Exception as e:
            #     logger.debug(f"Message fetching failed: {e}")
            # step_times["receive_action"] = (time.perf_counter() - step_start) * 1000  # ms
            
            # 2. Check watchdog timer
            step_start = time.perf_counter()
            now = time.time()
            if (now - last_cmd_time > host.watchdog_timeout_ms / 1000) and not watchdog_active:
                logger.warning(
                    f"Command not received for {host.watchdog_timeout_ms}ms. Stopping base for safety."
                )
                watchdog_active = True
                # Stop the mobile base (safety feature)
                robot.xlerobot.stop_base()
            step_times["watchdog_check"] = (time.perf_counter() - step_start) * 1000  # ms
            
            # 3. Get observation from Grievous (follower + leader + cameras)
            step_start = time.perf_counter()
            last_observation = robot.get_observation()
            step_times["get_observation"] = (time.perf_counter() - step_start) * 1000  # ms
            
            # 4. Get last action from teleop thread
            step_start = time.perf_counter()
            robot_action = teleop_thread.get_last_action()
            step_times["get_action_from_thread"] = (time.perf_counter() - step_start) * 1000  # ms

            if robot_action:
                robot_action["head_motor_1.pos"] = last_observation.get("head_motor_1.pos", 0.0)
                robot_action["head_motor_2.pos"] = last_observation.get("head_motor_2.pos", 0.0)
            
            # 4. Encode camera images to base64 for network transmission
            step_start = time.perf_counter()
            encode_times = {}
            for cam_key in robot.xlerobot.cameras.keys():
                cam_start = time.perf_counter()
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
                encode_times[cam_key] = (time.perf_counter() - cam_start) * 1000  # ms
            step_times["encode_cameras"] = (time.perf_counter() - step_start) * 1000  # ms
            step_times["encode_per_camera"] = encode_times
            
            # 5. Send processed robot_action to remote client via command socket
            step_start = time.perf_counter()
            try:
                # Send processed action for client feedback
                host.zmq_cmd_socket.send_string(json.dumps(robot_action), flags=zmq.NOBLOCK)
            except zmq.Again:
                logger.debug("Dropping action feedback, no client connected")
            except Exception as e:
                logger.error(f"Failed to send action feedback: {e}")
            step_times["send_action_feedback"] = (time.perf_counter() - step_start) * 1000  # ms
            
            # 6. Send observation to remote client
            step_start = time.perf_counter()
            try:
                host.zmq_observation_socket.send_string(
                    json.dumps(last_observation), flags=zmq.NOBLOCK
                )
            except zmq.Again:
                logger.debug("Dropping observation, no client connected")
            except Exception as e:
                logger.error(f"Failed to send observation: {e}")
            step_times["send_observation"] = (time.perf_counter() - step_start) * 1000  # ms
            
            # 7. Rate limiting
            step_start = time.perf_counter()
            elapsed = time.perf_counter() - loop_start_time
            sleep_time = max(1 / host.max_loop_freq_hz - elapsed, 0)
            time.sleep(sleep_time)
            step_times["sleep"] = (time.perf_counter() - step_start) * 1000  # ms
            
            # Display timing information
            total_loop_time = (time.perf_counter() - loop_start_time) * 1000  # ms
            timing_parts = [f"{k}: {v:.2f}ms" for k, v in step_times.items() if k != "encode_per_camera"]
            if "encode_per_camera" in step_times:
                cam_timings = " | ".join([f"{cam}: {t:.2f}ms" for cam, t in step_times["encode_per_camera"].items()])
                timing_parts.append(f"encode_cameras_detail: [{cam_timings}]")
            timing_str = " | ".join(timing_parts)
            print(f"Loop timing - Total: {total_loop_time:.2f}ms | {timing_str}")
            
            duration = time.perf_counter() - start
        
        logger.info(f"Connection time limit reached ({host.connection_time_s}s). Shutting down.")
    
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down...")
    
    finally:
        logger.info("Cleaning up Grievous host...")
        teleop_thread.stop()
        robot.disconnect()
        host.disconnect()
        logger.info("Grievous host shutdown complete")


if __name__ == "__main__":
    main()

