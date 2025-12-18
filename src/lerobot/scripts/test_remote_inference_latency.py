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

"""Remote Inference Latency Test Client

This script runs on RunPod and receives observations from a mock host,
runs SmolVLA policy inference, and sends actions back with timing metadata.

Usage:
    python test_remote_inference_latency.py \
        --robot.type=grievous_client \
        --robot.reverse_connection=true \
        --policy.path=Grievous-Robot/smolvla_finetuned_5k \
        --duration=30
"""

import logging
import time
from dataclasses import dataclass
from pprint import pformat
from typing import Any

from lerobot.configs import parser
from lerobot.configs.policies import PreTrainedConfig
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.datasets.pipeline_features import aggregate_pipeline_dataset_features, create_initial_features
from lerobot.datasets.utils import build_dataset_frame, combine_feature_dicts
from lerobot.policies.factory import make_policy, make_pre_post_processors
from lerobot.policies.utils import make_robot_action
from lerobot.processor import (
    PolicyProcessorPipeline,
    RobotProcessorPipeline,
    make_default_processors,
)
from lerobot.robots import (  # noqa: F401
    Robot,
    RobotConfig,
    grievous,  # Import grievous module for registration
    make_robot_from_config,
)
from lerobot.utils.constants import ACTION, OBS_STR
from lerobot.utils.control_utils import predict_action
from lerobot.utils.import_utils import register_third_party_devices
from lerobot.utils.utils import get_safe_torch_device, init_logging

logger = logging.getLogger(__name__)


@dataclass
class LatencyTestConfig:
    """Configuration for latency test client."""

    robot: RobotConfig
    policy: PreTrainedConfig | None = None
    duration: int = 30  # Test duration in seconds
    max_iterations: int = 10000  # Safety limit

    def __post_init__(self):
        # Parse policy path if provided
        policy_path = parser.get_path_arg("policy")
        if policy_path:
            cli_overrides = parser.get_cli_overrides("policy")
            self.policy = PreTrainedConfig.from_pretrained(policy_path, cli_overrides=cli_overrides)
            self.policy.pretrained_path = policy_path

        if self.policy is None:
            raise ValueError("Policy is required for latency testing. Use --policy.path=<model>")

    @classmethod
    def __get_path_fields__(cls) -> list[str]:
        """Enable parser to load policy config from path."""
        return ["policy"]


def run_latency_test(cfg: LatencyTestConfig) -> None:
    """Main latency testing loop.
    
    Args:
        cfg: Configuration for latency test
    """
    init_logging()
    logger.info("Latency Test Configuration:")
    logger.info(pformat(cfg))

    # Initialize robot client
    logger.info("Initializing GrievousClient...")
    robot = make_robot_from_config(cfg.robot)
    logger.info(f"Robot type: {robot.name}")
    logger.info(f"Action features: {list(robot.action_features.keys())}")
    logger.info(f"Observation features: {list(robot.observation_features.keys())}")

    # Create processor pipelines
    teleop_action_processor, robot_action_processor, robot_observation_processor = make_default_processors()

    # Create dataset features (needed for policy inference)
    logger.info("Creating dataset features...")
    dataset_features = combine_feature_dicts(
        aggregate_pipeline_dataset_features(
            pipeline=teleop_action_processor,
            initial_features=create_initial_features(action=robot.action_features),
            use_videos=False,  # No video encoding for latency test
        ),
        aggregate_pipeline_dataset_features(
            pipeline=robot_observation_processor,
            initial_features=create_initial_features(observation=robot.observation_features),
            use_videos=False,
        ),
    )

    # Create temporary in-memory dataset for feature information
    logger.info("Creating temporary dataset for policy...")
    # We need a minimal dataset structure just for the policy to understand features
    # Create a simple namespace object to hold the metadata
    from types import SimpleNamespace
    dataset_meta = SimpleNamespace(
        robot_type=robot.name,
        fps=30,
        features=dataset_features,
        stats={},  # Empty stats - policy will handle missing stats gracefully
    )

    # Load policy
    logger.info(f"Loading policy from {cfg.policy.pretrained_path}...")
    policy = make_policy(cfg.policy, ds_meta=dataset_meta)
    logger.info(f"Policy device: {policy.config.device}")
    logger.info(f"Policy loaded successfully")

    # Create preprocessor and postprocessor
    logger.info("Creating preprocessor and postprocessor...")
    try:
        preprocessor, postprocessor = make_pre_post_processors(
            policy_cfg=cfg.policy,
            pretrained_path=cfg.policy.pretrained_path,
            dataset_stats={},  # Empty stats - will use defaults
            preprocessor_overrides={
                "device_processor": {"device": cfg.policy.device},
            },
        )
    except Exception as e:
        logger.warning(f"Error creating pre/post processors with stats: {e}")
        logger.info("Attempting to create processors without stats...")
        preprocessor, postprocessor = make_pre_post_processors(
            policy_cfg=cfg.policy,
            pretrained_path=None,  # Don't try to load stats
            dataset_stats={},
            preprocessor_overrides={
                "device_processor": {"device": cfg.policy.device},
            },
        )

    # Connect robot
    logger.info("Connecting to robot client (will wait for host connection)...")
    robot.connect()
    logger.info("Robot connected successfully!")

    # Reset policy and processors
    policy.reset()
    preprocessor.reset()
    postprocessor.reset()

    # Get device
    device = get_safe_torch_device(cfg.policy.device)
    logger.info(f"Using device: {device}")

    # Main inference loop
    logger.info(f"\nStarting {cfg.duration}-second latency test...")
    logger.info("Waiting for observations from host...\n")

    iteration = 0
    start_time = time.perf_counter()
    last_seq_num = -1
    received_count = 0

    try:
        while iteration < cfg.max_iterations:
            loop_start = time.perf_counter()

            # Check duration
            elapsed = time.perf_counter() - start_time
            if elapsed >= cfg.duration:
                logger.info(f"Test duration reached ({cfg.duration}s). Stopping.")
                break

            # 1. Get observation from robot client
            try:
                obs_dict = robot.get_observation()
            except Exception as e:
                logger.error(f"Error getting observation: {e}")
                time.sleep(0.01)
                continue

            # 2. Extract metadata from observation
            seq_num = obs_dict.pop("seq_num", -1)
            timestamp_sent = obs_dict.pop("timestamp_sent", 0.0)
            timestamp_received = time.perf_counter()

            # Track if we're receiving observations
            if seq_num >= 0:
                received_count += 1
                if received_count == 1:
                    logger.info(f"First observation received (seq_num={seq_num})")

                # Check for gaps
                if last_seq_num >= 0 and seq_num != last_seq_num + 1:
                    gap = seq_num - last_seq_num - 1
                    logger.warning(f"Sequence gap: skipped {gap} observations")
                last_seq_num = seq_num

            # 3. Build observation frame for policy
            # Remove observation.state if present (will be reconstructed)
            obs_dict.pop("observation.state", None)
            
            # Rename camera keys to match policy expectations
            # Robot sends: left_wrist, right_wrist, head
            # Policy expects: camera1, camera2, camera3
            camera_rename_map = {
                "left_wrist": "camera1",
                "right_wrist": "camera2",
                "head": "camera3",
            }
            
            for old_name, new_name in camera_rename_map.items():
                if old_name in obs_dict:
                    obs_dict[new_name] = obs_dict.pop(old_name)
            
            try:
                observation_frame = build_dataset_frame(
                    dataset_features, obs_dict, prefix=OBS_STR
                )
            except Exception as e:
                logger.error(f"Error building observation frame: {e}")
                logger.error(f"Observation keys: {obs_dict.keys()}")
                time.sleep(0.01)
                continue

            # 4. Run inference with timing
            inference_start = time.perf_counter()
            try:
                action_values = predict_action(
                    observation=observation_frame,
                    policy=policy,
                    device=device,
                    preprocessor=preprocessor,
                    postprocessor=postprocessor,
                    use_amp=cfg.policy.use_amp,
                    task="latency test",  # Single task for test
                    robot_type=robot.robot_type,
                )
            except Exception as e:
                logger.error(f"Error during inference: {e}")
                time.sleep(0.01)
                continue

            inference_end = time.perf_counter()
            inference_time_ms = (inference_end - inference_start) * 1000

            # Log first inference
            if iteration == 0:
                logger.info(f"First inference complete: {inference_time_ms:.1f}ms")
                logger.info(f"Action keys: {list(action_values.keys())}")

            # 5. Convert action to robot action format
            try:
                robot_action = make_robot_action(action_values, dataset_features)
            except Exception as e:
                logger.error(f"Error making robot action: {e}")
                time.sleep(0.01)
                continue

            # 6. Add timing metadata to action
            # Convert robot_action dict to regular dict and add metadata
            action_dict = {key: float(robot_action[key]) for key in robot.action_features.keys()}
            action_dict["seq_num"] = seq_num
            action_dict["timestamp_received"] = timestamp_received
            action_dict["inference_start"] = inference_start
            action_dict["inference_end"] = inference_end
            action_dict["timestamp_sent"] = time.perf_counter()

            # 7. Send action back to host
            try:
                robot.send_action(action_dict)
            except Exception as e:
                logger.error(f"Error sending action: {e}")
                time.sleep(0.01)
                continue

            # Print periodic progress
            if iteration % 10 == 0 and iteration > 0:
                elapsed_total = time.perf_counter() - start_time
                rate = iteration / elapsed_total if elapsed_total > 0 else 0
                print(
                    f"[{iteration:4d} iterations] "
                    f"Rate: {rate:.1f} Hz | "
                    f"Last inference: {inference_time_ms:.1f}ms | "
                    f"Elapsed: {elapsed_total:.1f}s"
                )

            iteration += 1

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Stopping test.")
    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        logger.info("\nCleaning up...")
        robot.disconnect()
        logger.info(f"Test complete. Processed {iteration} iterations.")


@parser.wrap()
def main(cfg: LatencyTestConfig):
    """Entry point for latency test."""
    run_latency_test(cfg)


if __name__ == "__main__":
    register_third_party_devices()
    main()