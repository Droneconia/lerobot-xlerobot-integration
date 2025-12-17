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

"""Mock Grievous Inference Host - Lightweight latency testing daemon.

This script generates dummy observations and sends them to a remote policy client,
then receives actions and measures round-trip latency.

Usage:
    python grievous_mock_inference_host.py --remote-ip <RUNPOD_IP> --duration 30
"""

import argparse
import base64
import json
import logging
import time
from collections import defaultdict
from typing import Dict, List

import cv2
import numpy as np
import zmq

logger = logging.getLogger(__name__)


class MockGrievousInferenceHost:
    """Mock host that generates dummy observations for latency testing.
    
    This class simulates the behavior of grievous_inference_host.py but with
    synthetic data instead of real robot hardware.
    """

    def __init__(
        self,
        remote_ip: str,
        port_cmd: int = 5555,
        port_obs: int = 5556,
        loop_freq_hz: int = 50,
        duration_s: int = 30,
    ):
        """Initialize mock host with ZMQ sockets.
        
        Args:
            remote_ip: IP address of remote client (RunPod)
            port_cmd: Port for receiving actions from client
            port_obs: Port for sending observations to client
            loop_freq_hz: Control loop frequency (Hz)
            duration_s: Test duration in seconds
        """
        self.remote_ip = remote_ip
        self.port_cmd = port_cmd
        self.port_obs = port_obs
        self.loop_freq_hz = loop_freq_hz
        self.duration_s = duration_s

        # ZMQ context and sockets
        self.zmq_context = zmq.Context()
        
        # Command socket: RECEIVE actions from client (PULL)
        self.zmq_cmd_socket = self.zmq_context.socket(zmq.PULL)
        self.zmq_cmd_socket.connect(f"tcp://{remote_ip}:{port_cmd}")
        logger.info(f"Command socket (PULL) connected to tcp://{remote_ip}:{port_cmd}")
        
        # Observation socket: SEND observations to client (PUSH)
        self.zmq_observation_socket = self.zmq_context.socket(zmq.PUSH)
        self.zmq_observation_socket.setsockopt(zmq.CONFLATE, 1)  # Keep only latest
        self.zmq_observation_socket.connect(f"tcp://{remote_ip}:{port_obs}")
        logger.info(f"Observation socket (PUSH) connected to tcp://{remote_ip}:{port_obs}")

        # Tracking state
        self.observation_counter = 0
        self.pending_observations: Dict[int, float] = {}  # {seq_num: timestamp_sent}
        
        # Statistics
        self.latencies: List[float] = []
        self.inference_times: List[float] = []
        self.network_overheads: List[float] = []
        self.sequence_gaps: List[int] = []
        self.last_received_seq = -1

        logger.info(
            f"MockGrievousInferenceHost initialized: freq={loop_freq_hz}Hz, duration={duration_s}s"
        )

    def disconnect(self) -> None:
        """Close ZMQ sockets and terminate context."""
        logger.info("Closing MockGrievousInferenceHost ZMQ sockets...")
        self.zmq_observation_socket.close()
        self.zmq_cmd_socket.close()
        self.zmq_context.term()
        logger.info("MockGrievousInferenceHost disconnected")

    def generate_dummy_observation(self) -> Dict:
        """Generate synthetic observation with robot state and camera images.
        
        Returns:
            Dictionary with robot state (17 floats) and 3 base64-encoded camera images
        """
        observation = {}

        # Generate dummy robot state (17 DoF)
        # Left arm (6 DoF)
        observation["left_arm_shoulder_pan.pos"] = 0.0
        observation["left_arm_shoulder_lift.pos"] = 0.0
        observation["left_arm_elbow_flex.pos"] = 0.0
        observation["left_arm_wrist_flex.pos"] = 0.0
        observation["left_arm_wrist_roll.pos"] = 0.0
        observation["left_arm_gripper.pos"] = 0.0
        
        # Right arm (6 DoF)
        observation["right_arm_shoulder_pan.pos"] = 0.0
        observation["right_arm_shoulder_lift.pos"] = 0.0
        observation["right_arm_elbow_flex.pos"] = 0.0
        observation["right_arm_wrist_flex.pos"] = 0.0
        observation["right_arm_wrist_roll.pos"] = 0.0
        observation["right_arm_gripper.pos"] = 0.0
        
        # Head (2 DoF)
        observation["head_motor_1.pos"] = 0.0
        observation["head_motor_2.pos"] = 0.0
        
        # Base (3 DoF - velocities)
        observation["x.vel"] = 0.0
        observation["y.vel"] = 0.0
        observation["theta.vel"] = 0.0

        # Generate dummy camera frames (640x480 colored noise)
        # This simulates the real camera image size and compression
        for cam_name in ["left_wrist", "right_wrist", "head"]:
            # Create random noise image
            frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
            
            # Encode to JPEG with quality 90 (same as real host)
            ret, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            if ret:
                observation[cam_name] = base64.b64encode(buffer).decode("utf-8")
            else:
                logger.warning(f"Failed to encode camera {cam_name}, using empty string")
                observation[cam_name] = ""

        return observation

    def calculate_statistics(self) -> Dict:
        """Calculate statistical summary of latency measurements.
        
        Returns:
            Dictionary with mean, median, P95, P99, min, max for each metric
        """
        stats = {}

        if self.latencies:
            latencies_sorted = sorted(self.latencies)
            n = len(latencies_sorted)
            stats["round_trip"] = {
                "mean": np.mean(latencies_sorted),
                "median": np.median(latencies_sorted),
                "p95": latencies_sorted[int(n * 0.95)] if n > 0 else 0,
                "p99": latencies_sorted[int(n * 0.99)] if n > 0 else 0,
                "min": min(latencies_sorted),
                "max": max(latencies_sorted),
            }

        if self.inference_times:
            inference_sorted = sorted(self.inference_times)
            n = len(inference_sorted)
            stats["inference"] = {
                "mean": np.mean(inference_sorted),
                "median": np.median(inference_sorted),
                "p95": inference_sorted[int(n * 0.95)] if n > 0 else 0,
                "p99": inference_sorted[int(n * 0.99)] if n > 0 else 0,
            }

        if self.network_overheads:
            network_sorted = sorted(self.network_overheads)
            stats["network"] = {
                "mean": np.mean(network_sorted),
                "median": np.median(network_sorted),
            }

        return stats

    def print_final_statistics(self) -> None:
        """Print comprehensive statistics summary at end of test."""
        print("\n" + "=" * 60)
        print(f"Latency Test Complete ({len(self.latencies)} samples)")
        print("=" * 60)

        stats = self.calculate_statistics()

        if "round_trip" in stats:
            rt = stats["round_trip"]
            print("\nRound-trip Latency:")
            print(f"  Mean:   {rt['mean']:.1f} ms")
            print(f"  Median: {rt['median']:.1f} ms")
            print(f"  P95:    {rt['p95']:.1f} ms")
            print(f"  P99:    {rt['p99']:.1f} ms")
            print(f"  Min:    {rt['min']:.1f} ms")
            print(f"  Max:    {rt['max']:.1f} ms")

        if "inference" in stats:
            inf = stats["inference"]
            print("\nInference Time (from client):")
            print(f"  Mean:   {inf['mean']:.1f} ms")
            print(f"  Median: {inf['median']:.1f} ms")
            print(f"  P95:    {inf['p95']:.1f} ms")
            print(f"  P99:    {inf['p99']:.1f} ms")

        if "network" in stats:
            net = stats["network"]
            print("\nNetwork Overhead:")
            print(f"  Mean:   {net['mean']:.1f} ms")
            print(f"  Median: {net['median']:.1f} ms")

        dropped = self.observation_counter - len(self.latencies)
        print(f"\nDropped Observations: {dropped}")
        
        if self.sequence_gaps:
            print(f"Sequence Gaps: {self.sequence_gaps[:10]}")  # Show first 10 gaps
        else:
            print("Sequence Gaps: []")

        print("=" * 60 + "\n")

    def run(self) -> None:
        """Main control loop: send observations and receive actions."""
        logger.info(f"Starting {self.duration_s}-second latency test...")
        print(f"\nConnecting to remote policy at {self.remote_ip}...")
        print(f"Test duration: {self.duration_s} seconds")
        print(f"Loop frequency: {self.loop_freq_hz} Hz")
        print(f"Expected samples: ~{self.duration_s * self.loop_freq_hz // 10 * 10}\n")

        start_time = time.perf_counter()
        duration = 0

        try:
            while duration < self.duration_s:
                loop_start = time.perf_counter()

                # 1. Generate dummy observation
                observation = self.generate_dummy_observation()

                # 2. Add metadata (sequence number and timestamp)
                seq_num = self.observation_counter
                self.observation_counter += 1
                timestamp_sent = time.perf_counter()
                self.pending_observations[seq_num] = timestamp_sent

                observation["seq_num"] = seq_num
                observation["timestamp_sent"] = timestamp_sent

                # 3. Send observation to client
                try:
                    obs_json = json.dumps(observation)
                    self.zmq_observation_socket.send_string(obs_json, flags=zmq.NOBLOCK)
                except zmq.Again:
                    logger.debug("Observation socket busy, dropping observation")
                except Exception as e:
                    logger.error(f"Failed to send observation: {e}")

                # 4. Try to receive action (non-blocking)
                try:
                    action_msg = self.zmq_cmd_socket.recv_string(zmq.NOBLOCK)
                    timestamp_received = time.perf_counter()
                    action = json.loads(action_msg)

                    # 5. Extract metadata
                    action_seq = action.get("seq_num", -1)
                    timestamp_action_received = action.get("timestamp_received", 0)
                    inference_start = action.get("inference_start", 0)
                    inference_end = action.get("inference_end", 0)
                    timestamp_action_sent = action.get("timestamp_sent", 0)

                    # 6. Calculate latencies
                    if action_seq in self.pending_observations:
                        # Round-trip latency (critical metric)
                        round_trip_ms = (timestamp_received - self.pending_observations[action_seq]) * 1000

                        # Inference time (from client's timing)
                        inference_ms = (inference_end - inference_start) * 1000

                        # Network overhead (round-trip - inference)
                        network_ms = round_trip_ms - inference_ms

                        # Store statistics
                        self.latencies.append(round_trip_ms)
                        self.inference_times.append(inference_ms)
                        self.network_overheads.append(network_ms)

                        # Check for sequence gaps
                        if self.last_received_seq >= 0 and action_seq != self.last_received_seq + 1:
                            gap = action_seq - self.last_received_seq - 1
                            self.sequence_gaps.append(gap)
                            logger.warning(f"Sequence gap detected: {gap} observations skipped")

                        self.last_received_seq = action_seq

                        # Print progress every 10 samples
                        if len(self.latencies) % 10 == 0:
                            print(
                                f"[{len(self.latencies):3d} samples] "
                                f"Round-trip: {round_trip_ms:6.1f}ms | "
                                f"Inference: {inference_ms:6.1f}ms | "
                                f"Network: {network_ms:5.1f}ms"
                            )

                        # Clean up pending observations
                        del self.pending_observations[action_seq]
                    else:
                        logger.warning(f"Received action for unknown seq_num: {action_seq}")

                except zmq.Again:
                    # No action available yet (normal during startup)
                    pass
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode action JSON: {e}")
                except Exception as e:
                    logger.error(f"Error processing action: {e}")

                # 7. Rate limiting
                elapsed = time.perf_counter() - loop_start
                sleep_time = max(1 / self.loop_freq_hz - elapsed, 0)
                time.sleep(sleep_time)

                duration = time.perf_counter() - start_time

            logger.info(f"Test duration reached ({self.duration_s}s). Shutting down.")

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received. Shutting down...")

        finally:
            # Print final statistics
            self.print_final_statistics()
            
            # Cleanup
            self.disconnect()


def main():
    """Main entry point for mock inference host."""
    parser = argparse.ArgumentParser(
        description="Mock Grievous inference host for latency testing"
    )
    parser.add_argument(
        "--remote-ip",
        type=str,
        required=True,
        help="Remote client IP address (RunPod instance)",
    )
    parser.add_argument(
        "--port-cmd", type=int, default=5555, help="Command port (default: 5555)"
    )
    parser.add_argument(
        "--port-obs", type=int, default=5556, help="Observation port (default: 5556)"
    )
    parser.add_argument(
        "--duration", type=int, default=30, help="Test duration in seconds (default: 30)"
    )
    parser.add_argument(
        "--freq", type=int, default=50, help="Loop frequency in Hz (default: 50)"
    )
    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger.info("Starting Mock Grievous Inference Host")
    logger.info(f"Connecting to remote policy at {args.remote_ip}")

    # Create and run mock host
    host = MockGrievousInferenceHost(
        remote_ip=args.remote_ip,
        port_cmd=args.port_cmd,
        port_obs=args.port_obs,
        loop_freq_hz=args.freq,
        duration_s=args.duration,
    )

    host.run()


if __name__ == "__main__":
    main()

