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

"""Configuration classes for Grievous robot (XLerobot)."""

from dataclasses import dataclass, field

from lerobot.cameras.configs import CameraConfig, Cv2Rotation, ColorMode
from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
from lerobot.cameras.realsense import RealSenseCameraConfig

from ..config import RobotConfig


def grievous_cameras_config() -> dict[str, CameraConfig]:
    """Default camera configuration for Grievous (same as XLerobot).
    
    Camera paths (RPi5):
    - Left wrist: /dev/video0 (Innomaker at usb 1.2)
    - Right wrist: /dev/video8 (Innomaker at usb 1.3)
    - Head: RealSense D435 with serial 032622074046 (uses video2-7)
    """
    return {
        "left_wrist": OpenCVCameraConfig(
            index_or_path="/dev/video0", fps=30, width=640, height=480, rotation=Cv2Rotation.NO_ROTATION
        ),
        "right_wrist": OpenCVCameraConfig(
            index_or_path="/dev/video8", fps=30, width=640, height=480, rotation=Cv2Rotation.NO_ROTATION
        ),
        "head": RealSenseCameraConfig(
            serial_number_or_name="032622074046",
            fps=30,
            width=640,
            height=480,
            color_mode=ColorMode.RGB,
            rotation=Cv2Rotation.NO_ROTATION,
            use_depth=False  # Disabled - conflicts with other video devices
        ),
    }


@RobotConfig.register_subclass("grievous")
@dataclass
class GrievousConfig(RobotConfig):
    """Configuration for Grievous robot hardware on laptop.
    
    Grievous = XLerobot (follower arms + base + head + cameras) + BiSO100Leader (leader arms)
    
    Port configuration (from laptop_host_setup.md):
    - Follower left arm: /dev/follower_left
    - Follower right arm: /dev/follower_right
    - Leader left arm: /dev/leader_left
    - Leader right arm: /dev/leader_right
    """
    
    # Follower arms ports (XLerobot pattern)
    port1: str = "/dev/follower_left"  # Follower left arm
    port2: str = "/dev/follower_right"  # Follower right arm
    
    # Leader arms ports
    leader_left_arm_port: str = "/dev/leader_left"  # Leader left arm
    leader_right_arm_port: str = "/dev/leader_right"  # Leader right arm
    
    # Motor settings
    disable_torque_on_disconnect: bool = True
    max_relative_target: int | None = None
    use_degrees: bool = False
    
    # Cameras (shared with follower)
    cameras: dict[str, CameraConfig] = field(default_factory=grievous_cameras_config)
    
    # Teleop keys for base control
    teleop_keys: dict[str, str] = field(
        default_factory=lambda: {
            # Movement
            "forward": "i",
            "backward": "k",
            "left": "j",
            "right": "l",
            "rotate_left": "u",
            "rotate_right": "o",
            # Speed control
            "speed_up": "n",
            "speed_down": "m",
            # Quit teleop
            "quit": "b",
        }
    )


@dataclass
class GrievousHostConfig:
    """Configuration for Grievous host daemon running on RPi5.
    
    This is not a RobotConfig - it's for the host process configuration.
    """
    
    # Network Configuration
    port_zmq_cmd: int = 5555
    port_zmq_observations: int = 5556
    remote_ip: str | None = None  # Runpod IP for reverse connection mode (None = bind locally)
    
    # Runtime configuration
    connection_time_s: int = 3600  # Max runtime before auto-shutdown
    watchdog_timeout_ms: int = 500  # Stop robot if no commands received
    max_loop_freq_hz: int = 30  # Control loop frequency
    teleop_freq_hz: int = 120  # Teleop control thread frequency (higher rate for smoother control)
    dry_run: bool = False  # If True, log actions but don't send to robot (safe testing)


@RobotConfig.register_subclass("grievous_client")
@dataclass
class GrievousClientConfig(RobotConfig):
    """Configuration for Grievous network client on laptop.
    
    Provides network-transparent Robot interface to remote Grievous.
    """
    
    # REQUIRED FIELDS FIRST (no defaults)
    remote_ip: str = "192.168.50.47" # IP address of RPi5 - REQUIRED (ignored in reverse_connection mode)
    
    # OPTIONAL FIELDS (with defaults)
    # ZMQ ports (must match host)
    port_zmq_cmd: int = 5555
    port_zmq_observations: int = 5556
    reverse_connection: bool = False  # True = bind locally (server mode), False = connect to remote_ip (client mode)
    
    # Polling configuration
    polling_timeout_ms: int = 15
    connect_timeout_s: int = 5
    
    # Camera metadata (for dataset features - not actual devices)
    cameras: dict[str, CameraConfig] = field(default_factory=grievous_cameras_config)
    
    # Teleop keys (for base control via keyboard)
    teleop_keys: dict[str, str] = field(
        default_factory=lambda: {
            # Movement
            "forward": "i",
            "backward": "k",
            "left": "j",
            "right": "l",
            "rotate_left": "u",
            "rotate_right": "o",
            # Speed control
            "speed_up": "n",
            "speed_down": "m",
            # Quit teleop
            "quit": "b",
        }
    )

