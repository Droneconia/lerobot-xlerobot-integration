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

from dataclasses import dataclass

from lerobot.robots.so_follower import SOFollowerConfig

from ..config import RobotConfig


@dataclass
class BaseConfig:
    """Base configuration class for mobile base with 3 omniwheels."""

    # Port to connect to the base motors bus
    port: str

    # Disable torque on all base motors when disconnecting
    disable_torque_on_disconnect: bool = True


@RobotConfig.register_subclass("advanced_grievous")
@dataclass
class AdvancedGrievousConfig(RobotConfig):
    """Configuration class for Advanced Grievous robots."""

    left_arm_config: SOFollowerConfig
    right_arm_config: SOFollowerConfig
    base_config: BaseConfig
