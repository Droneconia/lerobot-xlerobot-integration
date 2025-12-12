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

"""Grievous Client - Network-transparent Robot interface for remote Grievous.

This client runs on the laptop and communicates with the Grievous host daemon on RPi5.
It implements the Robot interface, making the remote Grievous appear as if it's local.
"""

import base64
import json
import logging
from functools import cached_property
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np
import zmq

from lerobot.utils.errors import DeviceAlreadyConnectedError, DeviceNotConnectedError

from ..robot import Robot
from .config_grievous import GrievousClientConfig

logger = logging.getLogger(__name__)


class GrievousClient(Robot):
    """Network client for Grievous robot.
    
    Provides transparent network access to remote Grievous on RPi5.
    Observations include follower state, leader state (with _leader suffix), and cameras.
    Actions control only the follower (leader is input-only).
    """

    config_class = GrievousClientConfig
    name = "grievous_client"

    def __init__(self, config: GrievousClientConfig):
        super().__init__(config)
        self.config = config
        self.id = config.id
        self.robot_type = config.type

        # Network configuration
        self.remote_ip = config.remote_ip
        self.port_zmq_cmd = config.port_zmq_cmd
        self.port_zmq_observations = config.port_zmq_observations
        self.reverse_connection = config.reverse_connection  # Bind mode (server) vs connect mode (client)

        # Teleop configuration
        self.teleop_keys = config.teleop_keys

        # Polling configuration
        self.polling_timeout_ms = config.polling_timeout_ms
        self.connect_timeout_s = config.connect_timeout_s

        # ZMQ sockets (initialized in connect())
        self.zmq_context = None
        self.zmq_cmd_socket = None
        self.zmq_observation_socket = None

        # Cached data
        self.last_frames = {}
        self.last_remote_state = {}

        # Speed control for base teleoperation
        self.speed_levels = [
            {"xy": 0.1, "theta": 30},  # slow
            {"xy": 0.2, "theta": 60},  # medium
            {"xy": 0.3, "theta": 90},  # fast
        ]
        self.speed_index = 0  # Start at slow

        self._is_connected = False
        self.logs = {}

        logger.info(f"GrievousClient initialized for {self.remote_ip}")

    @cached_property
    def _follower_state_ft(self) -> dict[str, type]:
        """Follower state features (XLerobot: arms + base + head)."""
        return dict.fromkeys(
            (
                # Left follower arm
                "left_arm_shoulder_pan.pos",
                "left_arm_shoulder_lift.pos",
                "left_arm_elbow_flex.pos",
                "left_arm_wrist_flex.pos",
                "left_arm_wrist_roll.pos",
                "left_arm_gripper.pos",
                # Right follower arm
                "right_arm_shoulder_pan.pos",
                "right_arm_shoulder_lift.pos",
                "right_arm_elbow_flex.pos",
                "right_arm_wrist_flex.pos",
                "right_arm_wrist_roll.pos",
                "right_arm_gripper.pos",
                # Head
                "head_motor_1.pos",
                "head_motor_2.pos",
                # Base (velocity control)
                "x.vel",
                "y.vel",
                "theta.vel",
            ),
            float,
        )

    @cached_property
    def _leader_state_ft(self) -> dict[str, type]:
        """Leader state features (BiSO100Leader: 2 leader arms with _leader suffix)."""
        return dict.fromkeys(
            (
                # Left leader arm
                "left_shoulder_pan.pos_leader",
                "left_shoulder_lift.pos_leader",
                "left_elbow_flex.pos_leader",
                "left_wrist_flex.pos_leader",
                "left_wrist_roll.pos_leader",
                "left_gripper.pos_leader",
                # Right leader arm
                "right_shoulder_pan.pos_leader",
                "right_shoulder_lift.pos_leader",
                "right_elbow_flex.pos_leader",
                "right_wrist_flex.pos_leader",
                "right_wrist_roll.pos_leader",
                "right_gripper.pos_leader",
            ),
            float,
        )

    @cached_property
    def _state_ft(self) -> dict[str, type]:
        """All state features: follower only (leader excluded from observations)."""
        return {**self._follower_state_ft}

    @cached_property
    def _state_order(self) -> tuple[str, ...]:
        """Ordered tuple of follower state keys only (leader excluded)."""
        return tuple(self._state_ft.keys())

    @cached_property
    def _cameras_ft(self) -> dict[str, tuple[int, int, int]]:
        """Camera features (height, width, channels)."""
        return {name: (cfg.height, cfg.width, 3) for name, cfg in self.config.cameras.items()}

    @cached_property
    def observation_features(self) -> dict[str, type | tuple]:
        """Observation features: follower state + cameras (leader excluded)."""
        return {**self._state_ft, **self._cameras_ft}

    @cached_property
    def action_features(self) -> dict[str, type]:
        """Action features: follower only (leader is input-only)."""
        return self._follower_state_ft

    @property
    def cameras(self) -> dict:
        """Camera dict for compatibility with recording."""
        return {name: None for name in self.config.cameras}

    @property
    def is_connected(self) -> bool:
        """Check if connected to remote Grievous host."""
        return self._is_connected

    @property
    def is_calibrated(self) -> bool:
        """Calibration is handled on the host side."""
        return True

    def connect(self) -> None:
        """Establish ZMQ connection to remote Grievous host on RPi5.
        
        Supports two modes:
        - Normal mode (reverse_connection=False): Connect to remote host (client mode)
        - Reverse mode (reverse_connection=True): Bind locally and wait for host (server mode)
        """
        if self._is_connected:
            raise DeviceAlreadyConnectedError(
                "GrievousClient is already connected. Do not run `robot.connect()` twice."
            )

        # Create ZMQ context and sockets
        self.zmq_context = zmq.Context()

        if self.reverse_connection:
            # Reverse connection mode: BIND locally (server mode)
            # Used when client is behind NAT and needs to accept connections
            logger.info(f"Binding GrievousClient in server mode on ports {self.port_zmq_cmd}/{self.port_zmq_observations}...")

            # Command socket (PUSH): send actions to host
            self.zmq_cmd_socket = self.zmq_context.socket(zmq.PUSH)
            self.zmq_cmd_socket.bind(f"tcp://*:{self.port_zmq_cmd}")
            self.zmq_cmd_socket.setsockopt(zmq.CONFLATE, 1)  # Keep only latest message
            logger.info(f"Command socket bound to tcp://*:{self.port_zmq_cmd}")

            # Observation socket (PULL): receive observations from host
            self.zmq_observation_socket = self.zmq_context.socket(zmq.PULL)
            self.zmq_observation_socket.bind(f"tcp://*:{self.port_zmq_observations}")
            self.zmq_observation_socket.setsockopt(zmq.CONFLATE, 1)  # Keep only latest message
            logger.info(f"Observation socket bound to tcp://*:{self.port_zmq_observations}")

            # Wait for first observation to confirm host connected
            logger.info("Waiting for host to connect and send first observation...")
            poller = zmq.Poller()
            poller.register(self.zmq_observation_socket, zmq.POLLIN)
            socks = dict(poller.poll(self.connect_timeout_s * 1000))

            if self.zmq_observation_socket not in socks or socks[self.zmq_observation_socket] != zmq.POLLIN:
                raise DeviceNotConnectedError(
                    f"Timeout waiting for host to connect. "
                    "Is grievous_inference_host.py running on RPi5?"
                )

            logger.info("GrievousClient connected successfully (reverse connection mode)")

        else:
            # Normal mode: CONNECT to remote host (client mode)
            logger.info(f"Connecting to Grievous host at {self.remote_ip}...")

            # Command socket (PUSH): send actions to host
            self.zmq_cmd_socket = self.zmq_context.socket(zmq.PUSH)
            zmq_cmd_locator = f"tcp://{self.remote_ip}:{self.port_zmq_cmd}"
            self.zmq_cmd_socket.connect(zmq_cmd_locator)
            self.zmq_cmd_socket.setsockopt(zmq.CONFLATE, 1)  # Keep only latest message
            logger.info(f"Command socket connected to {zmq_cmd_locator}")

            # Observation socket (PULL): receive observations from host
            self.zmq_observation_socket = self.zmq_context.socket(zmq.PULL)
            zmq_observations_locator = f"tcp://{self.remote_ip}:{self.port_zmq_observations}"
            self.zmq_observation_socket.connect(zmq_observations_locator)
            self.zmq_observation_socket.setsockopt(zmq.CONFLATE, 1)  # Keep only latest message
            logger.info(f"Observation socket connected to {zmq_observations_locator}")

            # Wait for first observation to confirm connection
            poller = zmq.Poller()
            poller.register(self.zmq_observation_socket, zmq.POLLIN)
            socks = dict(poller.poll(self.connect_timeout_s * 1000))

            if self.zmq_observation_socket not in socks or socks[self.zmq_observation_socket] != zmq.POLLIN:
                raise DeviceNotConnectedError(
                    f"Timeout waiting for Grievous host at {self.remote_ip}. "
                    "Is the host daemon running?"
                )

            logger.info("GrievousClient connected successfully")

        self._is_connected = True

    def disconnect(self) -> None:
        """Close ZMQ sockets and disconnect from host."""
        if self.zmq_cmd_socket:
            self.zmq_cmd_socket.close()
        if self.zmq_observation_socket:
            self.zmq_observation_socket.close()
        if self.zmq_context:
            self.zmq_context.term()

        self._is_connected = False
        logger.info("GrievousClient disconnected")

    def calibrate(self) -> None:
        """Calibration is handled on the host side."""
        pass

    def configure(self) -> None:
        """Configuration is handled on the host side."""
        pass

    def _poll_and_get_latest_message(self) -> Optional[str]:
        """Poll ZMQ socket and return latest observation message.
        
        Returns:
            Latest message string or None if timeout
        """
        poller = zmq.Poller()
        poller.register(self.zmq_observation_socket, zmq.POLLIN)

        try:
            socks = dict(poller.poll(self.polling_timeout_ms))
        except zmq.ZMQError as e:
            logger.error(f"ZMQ polling error: {e}")
            return None

        if self.zmq_observation_socket not in socks:
            logger.debug("No new observation available within timeout")
            return None

        # Drain queue and keep only the latest message
        last_msg = None
        while True:
            try:
                msg = self.zmq_observation_socket.recv_string(zmq.NOBLOCK)
                last_msg = msg
            except zmq.Again:
                break

        if last_msg is None:
            logger.warning("Poller indicated data, but failed to retrieve message")

        return last_msg

    def _parse_observation_json(self, obs_string: str) -> Optional[Dict[str, Any]]:
        """Parse JSON observation string.
        
        Args:
            obs_string: JSON string from host
            
        Returns:
            Parsed dictionary or None if parsing fails
        """
        try:
            return json.loads(obs_string)
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON observation: {e}")
            return None

    def _decode_image_from_b64(self, image_b64: str) -> Optional[np.ndarray]:
        """Decode base64-encoded image to OpenCV format.
        
        Args:
            image_b64: Base64-encoded JPEG image string
            
        Returns:
            Decoded image as numpy array or None if decoding fails
        """
        if not image_b64:
            return None
        try:
            jpg_data = base64.b64decode(image_b64)
            np_arr = np.frombuffer(jpg_data, dtype=np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None:
                logger.warning("cv2.imdecode returned None for an image")
            return frame
        except (TypeError, ValueError) as e:
            logger.error(f"Error decoding base64 image: {e}")
            return None

    def _remote_state_from_obs(
        self, observation: Dict[str, Any]
    ) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
        """Extract camera frames and state from observation.
        
        Args:
            observation: Raw observation dictionary from host
            
        Returns:
            Tuple of (frames_dict, state_dict)
        """
        # Extract only follower state values (default to 0.0 if missing)
        # Leader values are explicitly excluded from observations
        flat_state = {key: observation.get(key, 0.0) for key in self._state_order}

        # Create state vector with only follower state (no leader values)
        state_vec = np.array([flat_state[key] for key in self._state_order], dtype=np.float32)

        # Only include follower state keys in obs_dict (filter out any leader keys from host)
        obs_dict: Dict[str, Any] = {**flat_state, "observation.state": state_vec}

        # Decode camera images
        current_frames: Dict[str, np.ndarray] = {}
        for cam_name, image_b64 in observation.items():
            if cam_name not in self._cameras_ft:
                continue
            frame = self._decode_image_from_b64(image_b64)
            if frame is not None:
                current_frames[cam_name] = frame

        return current_frames, obs_dict

    def _get_data(self) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
        """Poll for latest observation from host.
        
        If no new data available, returns cached data.
        
        Returns:
            Tuple of (frames_dict, state_dict)
        """
        # 1. Get latest message from ZMQ socket
        latest_message_str = self._poll_and_get_latest_message()

        # 2. If no message, return cached data
        if latest_message_str is None:
            return self.last_frames, self.last_remote_state

        # 3. Parse JSON message
        observation = self._parse_observation_json(latest_message_str)

        # 4. If parsing failed, return cached data
        if observation is None:
            return self.last_frames, self.last_remote_state

        # 5. Process observation
        try:
            new_frames, new_state = self._remote_state_from_obs(observation)
        except Exception as e:
            logger.error(f"Error processing observation, serving cached data: {e}")
            return self.last_frames, self.last_remote_state

        # Update cache
        self.last_frames = new_frames
        self.last_remote_state = new_state

        return new_frames, new_state

    def get_observation(self) -> dict[str, Any]:
        """Get observation from remote Grievous.
        
        Observation includes:
        - Follower state (XLerobot: arms, base, head)
        - Leader state (BiSO100Leader: arms with _leader suffix)
        - Camera frames
        
        Returns:
            Dictionary with all observation data
            
        Raises:
            DeviceNotConnectedError: If not connected to host
        """
        if not self._is_connected:
            raise DeviceNotConnectedError(
                "GrievousClient is not connected. Run `robot.connect()` first."
            )

        frames, obs_dict = self._get_data()

        # Add camera frames to observation
        for cam_name, frame in frames.items():
            if frame is None:
                logger.warning(f"Frame {cam_name} is None, using black image")
                # Use camera config dimensions for fallback
                cam_cfg = self.config.cameras[cam_name]
                frame = np.zeros((cam_cfg.height, cam_cfg.width, 3), dtype=np.uint8)
            obs_dict[cam_name] = frame
            
        return obs_dict

    def _from_keyboard_to_base_action(self, pressed_keys: np.ndarray) -> dict[str, float]:
        """Convert keyboard inputs to base velocity commands.
        
        Args:
            pressed_keys: Array of currently pressed key characters
            
        Returns:
            Dictionary with x.vel, y.vel, theta.vel commands
        """
        # Speed control
        if self.teleop_keys["speed_up"] in pressed_keys:
            self.speed_index = min(self.speed_index + 1, 2)
        if self.teleop_keys["speed_down"] in pressed_keys:
            self.speed_index = max(self.speed_index - 1, 0)

        speed_setting = self.speed_levels[self.speed_index]
        xy_speed = speed_setting["xy"]  # m/s
        theta_speed = speed_setting["theta"]  # deg/s

        x_cmd = 0.0  # forward/backward
        y_cmd = 0.0  # lateral
        theta_cmd = 0.0  # rotation

        if self.teleop_keys["forward"] in pressed_keys:
            x_cmd += xy_speed
        if self.teleop_keys["backward"] in pressed_keys:
            x_cmd -= xy_speed
        if self.teleop_keys["left"] in pressed_keys:
            y_cmd += xy_speed
        if self.teleop_keys["right"] in pressed_keys:
            y_cmd -= xy_speed
        if self.teleop_keys["rotate_left"] in pressed_keys:
            theta_cmd += theta_speed
        if self.teleop_keys["rotate_right"] in pressed_keys:
            theta_cmd -= theta_speed

        return {
            "x.vel": x_cmd,
            "y.vel": y_cmd,
            "theta.vel": theta_cmd,
        }

    def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """Send action to remote Grievous follower.
        
        Actions are sent only to the follower (XLerobot).
        Leader arms are input-only and not controlled by actions.
        
        Args:
            action: Dictionary of action values for follower
            
        Returns:
            The action that was sent
            
        Raises:
            DeviceNotConnectedError: If not connected to host
        """
        if not self._is_connected:
            raise DeviceNotConnectedError(
                "GrievousClient is not connected. Run `robot.connect()` first."
            )

        # Send action via ZMQ
        try:
            action_json = json.dumps(action)
            self.zmq_cmd_socket.send_string(action_json, flags=zmq.NOBLOCK)
            # Log every 30th action to avoid spam (at 30Hz = once per second)
            if not hasattr(self, '_action_send_count'):
                self._action_send_count = 0
            self._action_send_count += 1
            if self._action_send_count % 30 == 1:
                logger.info(f"Action #{self._action_send_count} sent successfully ({len(action_json)} bytes)")
        except zmq.Again:
            logger.warning("Command socket busy, dropping action")
        except Exception as e:
            logger.error(f"Error sending action: {e}")
        return action
