#!/usr/bin/env python

# Copyright 2025 The HuggingFace Inc. team. All rights reserved.
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

import logging
from functools import cached_property
import numpy as np

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus
from lerobot.processor import RobotAction, RobotObservation
from lerobot.robots.so_follower import SOFollower, SOFollowerRobotConfig
from lerobot.utils.decorators import check_if_already_connected, check_if_not_connected

from ..robot import Robot
from .config_advanced_grievous import AdvancedGrievousConfig

logger = logging.getLogger(__name__)


class AdvancedGrievous(Robot):
    """
    [Bimanual SO Follower Arms](https://github.com/TheRobotStudio/SO-ARM100) designed by TheRobotStudio
    (Advanced Grievous variant).
    """

    config_class = AdvancedGrievousConfig
    name = "advanced_grievous"

    def __init__(self, config: AdvancedGrievousConfig):
        super().__init__(config)
        self.config = config

        left_arm_config = SOFollowerRobotConfig(
            id=f"{config.id}_left" if config.id else None,
            calibration_dir=config.calibration_dir,
            port=config.left_arm_config.port,
            disable_torque_on_disconnect=config.left_arm_config.disable_torque_on_disconnect,
            max_relative_target=config.left_arm_config.max_relative_target,
            use_degrees=config.left_arm_config.use_degrees,
            cameras=config.left_arm_config.cameras,
        )

        right_arm_config = SOFollowerRobotConfig(
            id=f"{config.id}_right" if config.id else None,
            calibration_dir=config.calibration_dir,
            port=config.right_arm_config.port,
            disable_torque_on_disconnect=config.right_arm_config.disable_torque_on_disconnect,
            max_relative_target=config.right_arm_config.max_relative_target,
            use_degrees=config.right_arm_config.use_degrees,
            cameras=config.right_arm_config.cameras,
        )

        self.left_arm = SOFollower(left_arm_config)
        self.right_arm = SOFollower(right_arm_config)

        # Base: 3 omniwheel motors on an independent port (single board, no other motors)
        self.base_bus = FeetechMotorsBus(
            port=config.base_config.port,
            motors={
                "base_left_wheel": Motor(1, "sts3215", MotorNormMode.RANGE_M100_100),
                "base_back_wheel": Motor(2, "sts3215", MotorNormMode.RANGE_M100_100),
                "base_right_wheel": Motor(3, "sts3215", MotorNormMode.RANGE_M100_100),
            },
            calibration={},
        )
        self.base_motors = [m for m in self.base_bus.motors if m.startswith("base")]

        # Only for compatibility with other parts of the codebase that expect a `robot.cameras` attribute
        self.cameras = {**self.left_arm.cameras, **self.right_arm.cameras}

    # --- Base kinematics (same omniwheel layout as LeKiwi) ---

    @staticmethod
    def _degps_to_raw(degps: float) -> int:
        steps_per_deg = 4096.0 / 360.0
        speed_in_steps = degps * steps_per_deg
        speed_int = int(round(speed_in_steps))
        if speed_int > 0x7FFF:
            speed_int = 0x7FFF
        elif speed_int < -0x8000:
            speed_int = -0x8000
        return speed_int

    @staticmethod
    def _raw_to_degps(raw_speed: int) -> float:
        steps_per_deg = 4096.0 / 360.0
        return raw_speed / steps_per_deg

    def _body_to_wheel_raw(
        self,
        x: float,
        y: float,
        theta: float,
        wheel_radius: float = 0.05,
        base_radius: float = 0.125,
        max_raw: int = 3000,
    ) -> dict[str, int]:
        """
        Convert desired body-frame velocities into wheel raw commands.

        Parameters:
          x: Linear velocity in x (m/s).
          y: Linear velocity in y (m/s).
          theta: Rotational velocity (deg/s).
          wheel_radius: Radius of each wheel (meters).
          base_radius: Distance from the center of rotation to each wheel (meters).
          max_raw: Maximum allowed raw command (ticks) per wheel.

        Returns:
          A dictionary with wheel raw commands for base_left_wheel, base_back_wheel, base_right_wheel.
        """
        theta_rad = theta * (np.pi / 180.0)
        velocity_vector = np.array([x, y, theta_rad])
        angles = np.radians(np.array([240, 0, 120]) - 90)
        m = np.array([[np.cos(a), np.sin(a), base_radius] for a in angles])
        wheel_linear_speeds = m.dot(velocity_vector)
        wheel_angular_speeds = wheel_linear_speeds / wheel_radius
        wheel_degps = wheel_angular_speeds * (180.0 / np.pi)
        steps_per_deg = 4096.0 / 360.0
        raw_floats = [abs(degps) * steps_per_deg for degps in wheel_degps]
        max_raw_computed = max(raw_floats)
        if max_raw_computed > max_raw:
            scale = max_raw / max_raw_computed
            wheel_degps = wheel_degps * scale
        wheel_raw = [self._degps_to_raw(float(deg)) for deg in wheel_degps]
        return {
            "base_left_wheel": wheel_raw[0],
            "base_back_wheel": wheel_raw[1],
            "base_right_wheel": wheel_raw[2],
        }

    def _wheel_raw_to_body(
        self,
        left_wheel_speed: int,
        back_wheel_speed: int,
        right_wheel_speed: int,
        wheel_radius: float = 0.05,
        base_radius: float = 0.125,
    ) -> dict[str, float]:
        """
        Convert wheel raw velocity feedback into body-frame velocities.

        Parameters:
          left_wheel_speed, back_wheel_speed, right_wheel_speed: Raw wheel velocities.
          wheel_radius: Radius of each wheel (meters).
          base_radius: Distance from the robot center to each wheel (meters).

        Returns:
          Dict with "x.vel" (m/s), "y.vel" (m/s), "theta.vel" (deg/s).
        """
        wheel_degps = np.array(
            [
                self._raw_to_degps(left_wheel_speed),
                self._raw_to_degps(back_wheel_speed),
                self._raw_to_degps(right_wheel_speed),
            ]
        )
        wheel_radps = wheel_degps * (np.pi / 180.0)
        wheel_linear_speeds = wheel_radps * wheel_radius
        angles = np.radians(np.array([240, 0, 120]) - 90)
        m = np.array([[np.cos(a), np.sin(a), base_radius] for a in angles])
        m_inv = np.linalg.inv(m)
        velocity_vector = m_inv.dot(wheel_linear_speeds)
        x, y, theta_rad = velocity_vector
        theta = float(theta_rad * (180.0 / np.pi))
        return {"x.vel": float(x), "y.vel": float(y), "theta.vel": theta}

    @property
    def _motors_ft(self) -> dict[str, type]:
        left_arm_motors_ft = self.left_arm._motors_ft
        right_arm_motors_ft = self.right_arm._motors_ft
        # Base: body-frame velocities (recorded and commanded as x, y, theta)
        base_ft = {"x.vel": float, "y.vel": float, "theta.vel": float}

        return {
            **{f"left_{k}": v for k, v in left_arm_motors_ft.items()},
            **{f"right_{k}": v for k, v in right_arm_motors_ft.items()},
            **base_ft,
        }

    @property
    def _cameras_ft(self) -> dict[str, tuple]:
        left_arm_cameras_ft = self.left_arm._cameras_ft
        right_arm_cameras_ft = self.right_arm._cameras_ft

        return {
            **{f"left_{k}": v for k, v in left_arm_cameras_ft.items()},
            **{f"right_{k}": v for k, v in right_arm_cameras_ft.items()},
        }

    @cached_property
    def observation_features(self) -> dict[str, type | tuple]:
        return {**self._motors_ft, **self._cameras_ft}

    @cached_property
    def action_features(self) -> dict[str, type]:
        return self._motors_ft

    @property
    def is_connected(self) -> bool:
        return (
            self.left_arm.is_connected
            and self.right_arm.is_connected
            and self.base_bus.is_connected
        )

    @check_if_already_connected
    def connect(self, calibrate: bool = True) -> None:
        self.left_arm.connect(calibrate)
        self.right_arm.connect(calibrate)
        self.base_bus.connect()

    @property
    def is_calibrated(self) -> bool:
        return self.left_arm.is_calibrated and self.right_arm.is_calibrated

    def calibrate(self) -> None:
        self.left_arm.calibrate()
        self.right_arm.calibrate()

    def configure(self) -> None:
        self.left_arm.configure()
        self.right_arm.configure()
        self.base_bus.enable_torque()

    def setup_motors(self) -> None:
        self.left_arm.setup_motors()
        self.right_arm.setup_motors()

    @check_if_not_connected
    def get_observation(self) -> RobotObservation:
        obs_dict = {}

        # Add "left_" prefix
        left_obs = self.left_arm.get_observation()
        obs_dict.update({f"left_{key}": value for key, value in left_obs.items()})

        # Add "right_" prefix
        right_obs = self.right_arm.get_observation()
        obs_dict.update({f"right_{key}": value for key, value in right_obs.items()})

        # Read base wheel raw velocities and convert to body-frame (x, y, theta)
        base_wheel_vel = self.base_bus.sync_read("Present_Velocity", self.base_motors)
        base_vel = self._wheel_raw_to_body(
            base_wheel_vel["base_left_wheel"],
            base_wheel_vel["base_back_wheel"],
            base_wheel_vel["base_right_wheel"],
        )
        obs_dict.update(base_vel)

        return obs_dict

    @check_if_not_connected
    def send_action(self, action: RobotAction) -> RobotAction:
        # Remove "left_" prefix
        left_action = {
            key.removeprefix("left_"): value for key, value in action.items() if key.startswith("left_")
        }
        # Remove "right_" prefix
        right_action = {
            key.removeprefix("right_"): value for key, value in action.items() if key.startswith("right_")
        }
        # Extract base body-frame velocities (x.vel, y.vel, theta.vel) and convert to wheel raw
        x_vel = action.get("x.vel", 0.0)
        y_vel = action.get("y.vel", 0.0)
        theta_vel = action.get("theta.vel", 0.0)
        wheel_raw = self._body_to_wheel_raw(x_vel, y_vel, theta_vel)
        self.base_bus.sync_write("Goal_Velocity", wheel_raw)
        base_action = {"x.vel": x_vel, "y.vel": y_vel, "theta.vel": theta_vel}

        sent_action_left = self.left_arm.send_action(left_action)
        sent_action_right = self.right_arm.send_action(right_action)

        # Add prefixes back
        prefixed_sent_action_left = {f"left_{key}": value for key, value in sent_action_left.items()}
        prefixed_sent_action_right = {f"right_{key}": value for key, value in sent_action_right.items()}

        return {**prefixed_sent_action_left, **prefixed_sent_action_right, **base_action}

    @check_if_not_connected
    def disconnect(self):
        self.base_bus.sync_write("Goal_Velocity", dict.fromkeys(self.base_motors, 0), num_retry=5)
        self.base_bus.disconnect(disable_torque=self.config.base_config.disable_torque_on_disconnect)
        self.left_arm.disconnect()
        self.right_arm.disconnect()
