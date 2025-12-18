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
        print("\n" + "=" * 70)
        print(f"RESULTS: Collected {len(self.latencies)} valid samples")
        print("=" * 70)

        if not self.latencies:
            print("\nNo samples collected. Test failed.")
            print("=" * 70 + "\n")
            return

        stats = self.calculate_statistics()

        if "round_trip" in stats:
            rt = stats["round_trip"]
            print("\n📊 ROUND-TRIP LATENCY (observation sent → action received):")
            print(f"  Mean:      {rt['mean']:7.1f} ms")
            print(f"  Median:    {rt['median']:7.1f} ms")
            print(f"  P95:       {rt['p95']:7.1f} ms")
            print(f"  P99:       {rt['p99']:7.1f} ms")
            print(f"  Min:       {rt['min']:7.1f} ms")
            print(f"  Max:       {rt['max']:7.1f} ms")

        if "inference" in stats:
            inf = stats["inference"]
            print("\n⚡ INFERENCE TIME (measured on RunPod GPU):")
            print(f"  Mean:      {inf['mean']:7.1f} ms")
            print(f"  Median:    {inf['median']:7.1f} ms")
            print(f"  P95:       {inf['p95']:7.1f} ms")
            print(f"  P99:       {inf['p99']:7.1f} ms")
            print("\n  Note: Inference spikes may indicate model compilation or caching.")

        print("\n" + "=" * 70 + "\n")

    def run(self) -> None:
        """Main control loop: synchronous request-response for latency testing.
        
        Sends ONE observation, waits for the action response, calculates latency, repeats.
        """
        logger.info(f"Starting {self.duration_s}-second latency test...")
        print(f"\n{'='*70}")
        print(f"LATENCY TEST: Synchronous Request-Response Mode")
        print(f"{'='*70}")
        print(f"Remote policy: {self.remote_ip}")
        print(f"Test duration: {self.duration_s} seconds")
        print(f"Timeout per request: 5 seconds")
        print(f"{'='*70}\n")

        start_time = time.perf_counter()
        sample_count = 0
        timeout_count = 0
        
        try:
            while (time.perf_counter() - start_time) < self.duration_s:
                iteration_start = time.perf_counter()
                
                # 1. Generate and send observation
                observation = self.generate_dummy_observation()
                seq_num = self.observation_counter
                self.observation_counter += 1
                
                observation["seq_num"] = seq_num
                observation["timestamp_sent"] = iteration_start
                
                try:
                    obs_json = json.dumps(observation)
                    self.zmq_observation_socket.send_string(obs_json)
                    
                    if sample_count == 0:
                        print(f"✓ First observation sent (seq_num={seq_num})")
                    
                except Exception as e:
                    logger.error(f"Failed to send observation: {e}")
                    continue
                
                # 2. WAIT for action response (blocking, with timeout)
                poller = zmq.Poller()
                poller.register(self.zmq_cmd_socket, zmq.POLLIN)
                
                try:
                    socks = dict(poller.poll(timeout=5000))  # 5 second timeout
                    
                    if self.zmq_cmd_socket in socks:
                        action_msg = self.zmq_cmd_socket.recv_string()
                        timestamp_received = time.perf_counter()
                        action = json.loads(action_msg)
                        
                        # 3. Extract timing metadata from action
                        action_seq = action.get("seq_num", -1)
                        inference_start = action.get("inference_start", 0)
                        inference_end = action.get("inference_end", 0)
                        
                        # 4. Verify this is the action for our observation
                        if action_seq != seq_num:
                            logger.warning(
                                f"Sequence mismatch: sent {seq_num}, received {action_seq}"
                            )
                            continue
                        
                        # 5. Calculate latencies (all times are from host's clock except inference)
                        round_trip_ms = (timestamp_received - iteration_start) * 1000
                        inference_ms = (inference_end - inference_start) * 1000
                        
                        # Note: We can't accurately separate network vs inference time
                        # since inference timestamps are from a different machine's clock
                        
                        # Store statistics
                        self.latencies.append(round_trip_ms)
                        self.inference_times.append(inference_ms)
                        sample_count += 1
                        
                        # Print progress
                        if sample_count == 1:
                            print(f"✓ First action received (round-trip: {round_trip_ms:.1f}ms)\n")
                            print(f"{'Sample':<8} {'Round-Trip (ms)':<18} {'Inference (ms)':<18} {'Test Time (s)':<15}")
                            print(f"{'-'*70}")
                        
                        if sample_count % 10 == 0 or sample_count <= 3:
                            elapsed_s = time.perf_counter() - start_time
                            print(
                                f"{sample_count:<8} {round_trip_ms:<18.1f} "
                                f"{inference_ms:<18.1f} {elapsed_s:<15.1f}"
                            )
                    
                    else:
                        # Timeout waiting for action
                        timeout_count += 1
                        logger.warning(f"Timeout waiting for action (seq_num={seq_num})")
                        
                except zmq.ZMQError as e:
                    logger.error(f"ZMQ error: {e}")
                    continue
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode action JSON: {e}")
                    continue
            
            print(f"\n{'='*70}")
            print(f"Test duration reached ({self.duration_s}s). Completing...")
            print(f"{'='*70}")

        except KeyboardInterrupt:
            print(f"\n{'='*70}")
            print(f"Test interrupted by user")
            print(f"{'='*70}")

        finally:
            # Print final statistics
            print(f"\nCollected {sample_count} samples ({timeout_count} timeouts)")
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

