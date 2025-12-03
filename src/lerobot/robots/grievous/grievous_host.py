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
from typing import Optional

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
        freq_hz: int = 120,
        motor_bus_lock: Optional[threading.Lock] = None,
    ):
        """Initialize teleop control thread.
        
        Args:
            robot: Grievous robot instance
            teleop_action_processor: Processor for teleop actions
            robot_action_processor: Processor for robot actions
            freq_hz: Refresh rate for teleop control loop
            motor_bus_lock: Shared lock for serializing motor bus access
        """
        self.robot = robot
        self.freq_hz = freq_hz
        self.motor_bus_lock = motor_bus_lock
        
        # Thread-safe storage for last action and observation
        self._lock = threading.Lock()
        self._last_robot_action: dict = {}
        self._running = False
        self._thread: threading.Thread | None = None
        
        # Timing collection for periodic reporting
        self._timing_lock = threading.Lock()
        self._timing_data: dict[str, list[float]] = {}
        self._last_print_time = time.perf_counter()
        self._timing_data_start_time: float | None = None
    
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
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("Teleop control thread did not stop gracefully")
            else:
                logger.info("Teleop control thread stopped")
    
    def _control_loop(self) -> None:
        """Main control loop running in separate thread."""
        while self._running:
            loop_start = time.perf_counter()
            
            # Time the control operations
            control_start = time.perf_counter()
            try:
                # Get action from leader arms (doesn't use motor bus)
                robot_action = self.robot.get_action()

                action_valid = True
                if robot_action is None:
                    logger.warning("Received None action, skipping send")
                    action_valid = False
                elif not isinstance(robot_action, dict):
                    logger.error(f"Invalid action type: {type(robot_action)}, expected dict. Skipping send.")
                    action_valid = False
                elif not robot_action:
                    logger.warning("Received empty action dict, skipping send")
                    action_valid = False
                
                # Send action to follower (uses motor bus - must be serialized)
                if action_valid:
                    if self.motor_bus_lock:
                        with self.motor_bus_lock:
                            self.robot.send_action(robot_action)
                    else:    
                        self.robot.send_action(robot_action)

                    # Update thread-safe storage
                    with self._lock:
                        self._last_robot_action = robot_action
                else:
                    logger.warning("Invalid action, skipping send")
                
                
                    
            except Exception as e:
                logger.error(f"Error in teleop control loop: {e}", exc_info=True)
            control_time = (time.perf_counter() - control_start) * 1000  # ms
            
            # Rate limiting
            elapsed = time.perf_counter() - loop_start
            sleep_time = max(1 / self.freq_hz - elapsed, 0)
            sleep_start = time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)
            actual_sleep_time = (time.perf_counter() - sleep_start) * 1000  # ms
            
            # Collect timing data
            total_loop_time = (time.perf_counter() - loop_start) * 1000  # ms
            with self._timing_lock:
                current_time = time.perf_counter()
                
                # Track when timing data collection started
                if self._timing_data_start_time is None:
                    self._timing_data_start_time = current_time
                
                # Store timing data for each category
                if "control" not in self._timing_data:
                    self._timing_data["control"] = []
                self._timing_data["control"].append(control_time)
                
                if "sleep" not in self._timing_data:
                    self._timing_data["sleep"] = []
                self._timing_data["sleep"].append(actual_sleep_time)
                
                if "total_loop_time" not in self._timing_data:
                    self._timing_data["total_loop_time"] = []
                self._timing_data["total_loop_time"].append(total_loop_time)
                
                # Print averages every second
                if current_time - self._last_print_time >= 1.0:
                    if self._timing_data and self._timing_data_start_time is not None:
                        timing_parts = []
                        for key in sorted(self._timing_data.keys()):
                            if self._timing_data[key]:
                                avg_time = sum(self._timing_data[key]) / len(self._timing_data[key])
                                min_time = min(self._timing_data[key])
                                max_time = max(self._timing_data[key])
                                timing_parts.append(f"{key}: avg={avg_time:.2f}ms min={min_time:.2f}ms max={max_time:.2f}ms")
                        
                        # Calculate actual frequency using the actual time span of collected data
                        loop_count = len(self._timing_data.get("total_loop_time", []))
                        actual_time_span = current_time - self._timing_data_start_time
                        actual_freq = loop_count / actual_time_span if actual_time_span > 0 else 0
                        
                        timing_str = " | ".join(timing_parts)
                        print(f"TeleopControlThread timing - Freq: {actual_freq:.1f}Hz | Loops: {loop_count} | {timing_str}")
                    
                    # Reset timing data
                    self._timing_data.clear()
                    self._timing_data_start_time = None
                    self._last_print_time = current_time
    
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
    
    # Create shared lock for motor bus access (prevents concurrent access conflicts)
    motor_bus_lock = threading.Lock()
    
    # Start teleop control thread (runs at higher refresh rate)
    teleop_thread = TeleopControlThread(
        robot=robot,
        freq_hz=host.teleop_freq_hz,
        motor_bus_lock=motor_bus_lock,
    )
    teleop_thread.start()
    
    last_cmd_time = time.time()
    watchdog_active = False
    logger.info("Waiting for commands from remote client...")
    
    # Timing collection for periodic reporting
    timing_data: dict[str, list[float]] = {}
    last_print_time = time.perf_counter()
    timing_data_start_time: float | None = None
    
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
                
            # Reset watchdog timer
            last_cmd_time = time.time()
            watchdog_active = False
                
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
            # Uses motor bus - must be serialized with teleop thread
            step_start = time.perf_counter()
            with motor_bus_lock:
                last_observation = robot.get_observation()
            step_times["get_observation"] = (time.perf_counter() - step_start) * 1000  # ms
            
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

            # 5. Get last action from teleop thread
            step_start = time.perf_counter()
            robot_action = teleop_thread.get_last_action()
            step_times["get_action_from_thread"] = (time.perf_counter() - step_start) * 1000  # ms

            if robot_action:
                robot_action["head_motor_1.pos"] = last_observation.get("head_motor_1.pos", 0.0)
                robot_action["head_motor_2.pos"] = last_observation.get("head_motor_2.pos", 0.0)
            
            # 6. Send processed robot_action to remote client via command socket
            step_start = time.perf_counter()
            try:
                # Send processed action for client feedback
                host.zmq_cmd_socket.send_string(json.dumps(robot_action), flags=zmq.NOBLOCK)
            except zmq.Again:
                logger.debug("Dropping action feedback, no client connected")
            except Exception as e:
                logger.error(f"Failed to send action feedback: {e}")
            step_times["send_action_feedback"] = (time.perf_counter() - step_start) * 1000  # ms
            
            # 7. Send observation to remote client
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
            
            # 8. Rate limiting
            step_start = time.perf_counter()
            elapsed = time.perf_counter() - loop_start_time
            sleep_time = max(1 / host.max_loop_freq_hz - elapsed, 0)
            time.sleep(sleep_time)
            step_times["sleep"] = (time.perf_counter() - step_start) * 1000  # ms
            
            # Collect timing data
            total_loop_time = (time.perf_counter() - loop_start_time) * 1000  # ms
            current_time = time.perf_counter()
            
            # Track when timing data collection started
            if timing_data_start_time is None:
                timing_data_start_time = current_time
            
            for key, value in step_times.items():
                if key != "encode_per_camera":
                    if key not in timing_data:
                        timing_data[key] = []
                    timing_data[key].append(value)
            
            # Handle per-camera encoding times separately
            if "encode_per_camera" in step_times:
                for cam_key, cam_time in step_times["encode_per_camera"].items():
                    cam_timing_key = f"encode_{cam_key}"
                    if cam_timing_key not in timing_data:
                        timing_data[cam_timing_key] = []
                    timing_data[cam_timing_key].append(cam_time)
            
            if "total_loop_time" not in timing_data:
                timing_data["total_loop_time"] = []
            timing_data["total_loop_time"].append(total_loop_time)
            
            # Print averages every second
            if current_time - last_print_time >= 1.0:
                if timing_data and timing_data_start_time is not None:
                    timing_parts = []
                    for key in sorted(timing_data.keys()):
                        if timing_data[key]:
                            avg_time = sum(timing_data[key]) / len(timing_data[key])
                            min_time = min(timing_data[key])
                            max_time = max(timing_data[key])
                            timing_parts.append(f"{key}: avg={avg_time:.2f}ms min={min_time:.2f}ms max={max_time:.2f}ms")
                    
                    # Calculate actual frequency using the actual time span of collected data
                    loop_count = len(timing_data.get("total_loop_time", []))
                    actual_time_span = current_time - timing_data_start_time
                    actual_freq = loop_count / actual_time_span if actual_time_span > 0 else 0
                    
                    timing_str = " | ".join(timing_parts)
                    print(f"Main loop timing - Freq: {actual_freq:.1f}Hz | Loops: {loop_count} | {timing_str}")
                
                # Reset timing data
                timing_data.clear()
                timing_data_start_time = None
                last_print_time = current_time
            
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

