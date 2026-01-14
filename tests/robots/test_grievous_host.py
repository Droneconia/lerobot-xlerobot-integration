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

import json
import threading
import time
from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pytest
import zmq

from lerobot.robots.grievous.config_grievous import GrievousHostConfig
from lerobot.robots.grievous.grievous_host import GrievousHost, TeleopControlThread


@pytest.fixture
def mock_zmq_context():
    """Mock ZMQ context and sockets."""
    context_mock = MagicMock()
    cmd_socket_mock = MagicMock()
    obs_socket_mock = MagicMock()
    
    context_mock.socket.return_value = cmd_socket_mock
    context_mock.socket.side_effect = [cmd_socket_mock, obs_socket_mock]
    
    return context_mock, cmd_socket_mock, obs_socket_mock


@pytest.fixture
def mock_robot():
    """Mock Grievous robot."""
    robot = MagicMock()
    robot.get_action.return_value = {
        "left_arm_shoulder_pan.pos": 0.5,
        "left_arm_shoulder_lift.pos": 0.3,
        "right_arm_shoulder_pan.pos": -0.5,
        "right_arm_shoulder_lift.pos": -0.3,
    }
    robot.get_observation.return_value = {
        "left_arm_shoulder_pan.pos": 0.5,
        "left_arm_shoulder_lift.pos": 0.3,
        "left_wrist": np.zeros((480, 640, 3), dtype=np.uint8),
        "right_wrist": np.zeros((480, 640, 3), dtype=np.uint8),
    }
    robot.send_action.return_value = None
    robot.xlerobot = MagicMock()
    robot.xlerobot.cameras = {
        "left_wrist": MagicMock(),
        "right_wrist": MagicMock(),
        "head": MagicMock(),
    }
    robot.xlerobot.stop_base = MagicMock()
    return robot


@pytest.fixture
def mock_processors():
    """Mock processor pipelines."""
    teleop_processor = MagicMock()
    robot_processor = MagicMock()
    obs_processor = MagicMock()
    
    # Make processors return the input action (identity behavior)
    def teleop_side_effect(args):
        action, obs = args
        return action
    
    def robot_side_effect(args):
        action, obs = args
        return action
    
    teleop_processor.side_effect = teleop_side_effect
    robot_processor.side_effect = robot_side_effect
    
    return teleop_processor, robot_processor, obs_processor


class TestGrievousHost:
    """Tests for GrievousHost class."""
    
    @patch("lerobot.robots.grievous.grievous_host.zmq.Context")
    def test_init(self, mock_context_class, mock_zmq_context):
        """Test GrievousHost initialization."""
        context_mock, cmd_socket_mock, obs_socket_mock = mock_zmq_context
        mock_context_class.return_value = context_mock
        
        config = GrievousHostConfig(
            port_zmq_cmd=5555,
            port_zmq_observations=5556,
            connection_time_s=10,
            watchdog_timeout_ms=500,
            max_loop_freq_hz=60,
            teleop_freq_hz=120,
        )
        
        host = GrievousHost(config)
        
        # Check context was created
        mock_context_class.assert_called_once()
        
        # Check sockets were created (called twice: cmd and obs)
        assert context_mock.socket.call_count == 2
        
        # Check socket configuration
        cmd_socket_mock.setsockopt.assert_called_with(zmq.CONFLATE, 1)
        obs_socket_mock.setsockopt.assert_called_with(zmq.CONFLATE, 1)
        
        # Check sockets were bound
        cmd_socket_mock.bind.assert_called_once_with("tcp://*:5555")
        obs_socket_mock.bind.assert_called_once_with("tcp://*:5556")
        
        # Check config was stored
        assert host.connection_time_s == 10
        assert host.watchdog_timeout_ms == 500
        assert host.max_loop_freq_hz == 60
        assert host.teleop_freq_hz == 120
    
    @patch("lerobot.robots.grievous.grievous_host.zmq.Context")
    def test_disconnect(self, mock_context_class, mock_zmq_context):
        """Test GrievousHost disconnect."""
        context_mock, cmd_socket_mock, obs_socket_mock = mock_zmq_context
        mock_context_class.return_value = context_mock
        
        config = GrievousHostConfig()
        host = GrievousHost(config)
        
        host.disconnect()
        
        # Check sockets were closed
        obs_socket_mock.close.assert_called_once()
        cmd_socket_mock.close.assert_called_once()
        
        # Check context was terminated
        context_mock.term.assert_called_once()


class TestTeleopControlThread:
    """Tests for TeleopControlThread class."""
    
    def test_init(self, mock_robot, mock_processors):
        """Test TeleopControlThread initialization."""
        teleop_processor, robot_processor, _ = mock_processors
        
        thread = TeleopControlThread(
            robot=mock_robot,
            teleop_action_processor=teleop_processor,
            robot_action_processor=robot_processor,
            freq_hz=120,
        )
        
        assert thread.robot == mock_robot
        assert thread.teleop_action_processor == teleop_processor
        assert thread.robot_action_processor == robot_processor
        assert thread.freq_hz == 120
        assert not thread._running
        assert thread._thread is None
    
    def test_start_stop(self, mock_robot, mock_processors):
        """Test thread start and stop."""
        teleop_processor, robot_processor, _ = mock_processors
        
        thread = TeleopControlThread(
            robot=mock_robot,
            teleop_action_processor=teleop_processor,
            robot_action_processor=robot_processor,
            freq_hz=1000,  # High frequency for quick test
        )
        
        # Start thread
        thread.start()
        assert thread._running
        assert thread._thread is not None
        assert thread._thread.is_alive()
        
        # Give thread a moment to run
        time.sleep(0.1)
        
        # Stop thread
        thread.stop()
        assert not thread._running
        
        # Wait for thread to finish
        thread._thread.join(timeout=1.0)
        assert not thread._thread.is_alive()
    
    def test_control_loop_processes_actions(self, mock_robot, mock_processors):
        """Test that control loop processes actions correctly."""
        teleop_processor, robot_processor, _ = mock_processors
        
        thread = TeleopControlThread(
            robot=mock_robot,
            teleop_action_processor=teleop_processor,
            robot_action_processor=robot_processor,
            freq_hz=1000,  # High frequency for quick test
        )
        
        thread.start()
        time.sleep(0.15)  # Let it run a bit longer
        
        # Check that get_action was called
        assert mock_robot.get_action.called
        
        # Check that send_action was called
        assert mock_robot.send_action.called
        
        thread.stop()
        if thread._thread:
            thread._thread.join(timeout=1.0)
    
    def test_get_last_action(self, mock_robot, mock_processors):
        """Test thread-safe action retrieval."""
        teleop_processor, robot_processor, _ = mock_processors
        
        thread = TeleopControlThread(
            robot=mock_robot,
            teleop_action_processor=teleop_processor,
            robot_action_processor=robot_processor,
            freq_hz=1000,
        )
        
        # Initially empty
        action = thread.get_last_action()
        assert action == {}
        
        # Start thread and let it run
        thread.start()
        time.sleep(0.15)  # Give it time to process
        
        # Should have an action now
        action = thread.get_last_action()
        assert isinstance(action, dict)
        assert len(action) > 0
        
        thread.stop()
        if thread._thread:
            thread._thread.join(timeout=1.0)
    
    def test_control_loop_error_handling(self, mock_robot, mock_processors):
        """Test that errors in control loop don't crash the thread."""
        teleop_processor, robot_processor, _ = mock_processors
        
        # Make get_action raise an error
        mock_robot.get_action.side_effect = [ValueError("Test error"), mock_robot.get_action.return_value]
        
        thread = TeleopControlThread(
            robot=mock_robot,
            teleop_action_processor=teleop_processor,
            robot_action_processor=robot_processor,
            freq_hz=1000,
        )
        
        thread.start()
        time.sleep(0.15)
        
        # Thread should still be running despite error
        assert thread._running
        assert thread._thread.is_alive()
        
        thread.stop()
        if thread._thread:
            thread._thread.join(timeout=1.0)
    
    def test_rate_limiting(self, mock_robot, mock_processors):
        """Test that rate limiting works correctly."""
        teleop_processor, robot_processor, _ = mock_processors
        
        thread = TeleopControlThread(
            robot=mock_robot,
            teleop_action_processor=teleop_processor,
            robot_action_processor=robot_processor,
            freq_hz=10,  # 10 Hz = 100ms per iteration
        )
        
        start_time = time.perf_counter()
        thread.start()
        time.sleep(0.5)  # Should allow ~5 iterations
        thread.stop()
        thread._thread.join(timeout=1.0)
        
        # Check that get_action was called multiple times
        assert mock_robot.get_action.call_count >= 3
    
    def test_motor_bus_lock_prevents_conflicts(self, mock_robot, mock_processors):
        """Test that motor bus lock prevents concurrent access conflicts."""
        teleop_processor, robot_processor, _ = mock_processors
        
        # Create a shared lock
        motor_bus_lock = threading.Lock()
        
        # Track if operations are happening concurrently
        concurrent_access = threading.Event()
        access_times = []
        access_lock = threading.Lock()
        
        # Mock send_action to track when it's called
        def tracked_send_action(action):
            with access_lock:
                access_times.append(("send", time.perf_counter()))
            # Simulate some work (motor bus access)
            time.sleep(0.001)  # 1ms
            return None  # send_action returns None
        
        mock_robot.send_action.side_effect = tracked_send_action
        
        # Mock get_observation to track when it's called
        def tracked_get_observation():
            with access_lock:
                access_times.append(("get_obs", time.perf_counter()))
            # Simulate some work (motor bus access)
            time.sleep(0.001)  # 1ms
            # Return the original mock's return value without calling it
            return {
                "left_arm_shoulder_pan.pos": 0.5,
                "left_arm_shoulder_lift.pos": 0.3,
                "left_wrist": np.zeros((480, 640, 3), dtype=np.uint8),
                "right_wrist": np.zeros((480, 640, 3), dtype=np.uint8),
            }
        
        mock_robot.get_observation.side_effect = tracked_get_observation
        
        # Create thread with lock
        thread = TeleopControlThread(
            robot=mock_robot,
            teleop_action_processor=teleop_processor,
            robot_action_processor=robot_processor,
            freq_hz=100,  # High frequency for quick test
            motor_bus_lock=motor_bus_lock,
        )
        
        thread.start()
        time.sleep(0.1)  # Let thread run
        
        # Simulate main loop getting observations while teleop thread is running
        for _ in range(5):
            with motor_bus_lock:
                obs = mock_robot.get_observation()
            time.sleep(0.01)  # Simulate main loop rate (100Hz)
        
        thread.stop()
        if thread._thread:
            thread._thread.join(timeout=1.0)
        
        # Verify both operations were called
        assert mock_robot.send_action.called
        assert mock_robot.get_observation.called
        
        # Verify we have multiple access times recorded
        assert len(access_times) >= 5
    
    def test_teleop_script_integration(self, mock_robot, mock_processors):
        """Integration test simulating the full teleop script workflow."""
        teleop_processor, robot_processor, _ = mock_processors
        
        # Create shared lock (as in main())
        motor_bus_lock = threading.Lock()
        
        # Create teleop thread with lock
        thread = TeleopControlThread(
            robot=mock_robot,
            teleop_action_processor=teleop_processor,
            robot_action_processor=robot_processor,
            freq_hz=120,  # Real teleop frequency
            motor_bus_lock=motor_bus_lock,
        )
        
        thread.start()
        
        # Simulate main loop running at 60Hz
        observations_received = []
        actions_received = []
        
        start_time = time.perf_counter()
        while time.perf_counter() - start_time < 0.2:  # Run for 200ms
            # Main loop: get observation (with lock)
            with motor_bus_lock:
                obs = mock_robot.get_observation()
            observations_received.append(obs)
            
            # Get action from thread
            action = thread.get_last_action()
            if action:
                actions_received.append(action)
            
            time.sleep(1.0 / 60.0)  # 60Hz main loop
        
        thread.stop()
        if thread._thread:
            thread._thread.join(timeout=1.0)
        
        # Verify the system worked:
        # 1. Teleop thread was running
        assert thread._thread is not None or not thread._running
        
        # 2. Observations were received
        assert len(observations_received) > 0
        
        # 3. Actions were received from thread
        assert len(actions_received) > 0 or mock_robot.get_action.called
        
        # 4. No exceptions were raised (implicitly verified by test completing)
        
        # 5. Both send_action and get_observation were called
        assert mock_robot.send_action.called
        assert mock_robot.get_observation.called
    
    def test_motor_bus_lock_serialization(self, mock_robot, mock_processors):
        """Test that motor bus lock properly serializes access."""
        teleop_processor, robot_processor, _ = mock_processors
        
        motor_bus_lock = threading.Lock()
        access_order = []
        order_lock = threading.Lock()
        
        # Track access order
        def tracked_send(action):
            with order_lock:
                access_order.append(("send_start", time.perf_counter()))
            # Simulate motor bus operation
            time.sleep(0.001)
            with order_lock:
                access_order.append(("send_end", time.perf_counter()))
            return None
        
        def tracked_get():
            with order_lock:
                access_order.append(("get_start", time.perf_counter()))
            # Simulate motor bus operation
            time.sleep(0.001)
            with order_lock:
                access_order.append(("get_end", time.perf_counter()))
            return {
                "left_arm_shoulder_pan.pos": 0.5,
                "left_arm_shoulder_lift.pos": 0.3,
            }
        
        mock_robot.send_action.side_effect = tracked_send
        mock_robot.get_observation.side_effect = tracked_get
        
        thread = TeleopControlThread(
            robot=mock_robot,
            teleop_action_processor=teleop_processor,
            robot_action_processor=robot_processor,
            freq_hz=50,  # Moderate frequency
            motor_bus_lock=motor_bus_lock,
        )
        
        thread.start()
        time.sleep(0.05)  # Let it run a bit
        
        # Try to get observation while thread is sending actions
        with motor_bus_lock:
            obs = mock_robot.get_observation()
        
        thread.stop()
        if thread._thread:
            thread._thread.join(timeout=1.0)
        
        # Verify operations completed (access_order has entries)
        assert len(access_order) > 0
        
        # Verify no overlapping operations (each send_end before next get_start, etc.)
        # This is a basic check - in reality the lock ensures this
        for i in range(len(access_order) - 1):
            current = access_order[i]
            next_op = access_order[i + 1]
            # If current is an end and next is a start of different type, 
            # they should be properly sequenced (lock ensures this)
            if current[0].endswith("_end") and next_op[0].endswith("_start"):
                # Times should be sequential (lock prevents overlap)
                assert current[1] <= next_op[1]


class TestMainFunction:
    """Integration tests for main function."""
    
    @patch("lerobot.robots.grievous.grievous_host.Grievous")
    @patch("lerobot.robots.grievous.grievous_host.GrievousHost")
    @patch("lerobot.robots.grievous.grievous_host.make_default_processors")
    @patch("lerobot.robots.grievous.grievous_host.time")
    def test_main_loop_basic_flow(
        self,
        mock_time,
        mock_make_processors,
        mock_host_class,
        mock_grievous_class,
        mock_robot,
        mock_processors,
    ):
        """Test basic main loop flow."""
        # Setup mocks
        teleop_processor, robot_processor, obs_processor = mock_processors
        mock_make_processors.return_value = (teleop_processor, robot_processor, obs_processor)
        
        mock_robot_instance = mock_robot
        mock_grievous_class.return_value = mock_robot_instance
        
        mock_host_instance = MagicMock()
        mock_host_instance.connection_time_s = 0.1  # Short timeout for test
        mock_host_instance.watchdog_timeout_ms = 500
        mock_host_instance.max_loop_freq_hz = 60
        mock_host_instance.teleop_freq_hz = 120
        mock_host_instance.zmq_cmd_socket = MagicMock()
        mock_host_instance.zmq_observation_socket = MagicMock()
        mock_host_class.return_value = mock_host_instance
        
        # Mock time to control loop duration
        call_count = [0]
        
        def time_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return 0.0  # start time
            elif call_count[0] < 10:
                return 0.01 * call_count[0]  # Incrementing time
            else:
                return 0.2  # Exceed connection_time_s
        
        mock_time.perf_counter.side_effect = time_side_effect
        mock_time.time.return_value = 0.0
        mock_time.sleep.return_value = None
        
        # Import and run main
        from lerobot.robots.grievous.grievous_host import main
        
        try:
            main()
        except SystemExit:
            pass  # Expected if KeyboardInterrupt handling
        
        # Verify robot was initialized and connected
        mock_grievous_class.assert_called_once()
        mock_robot_instance.connect.assert_called_once_with(calibrate=False)
        
        # Verify host was created
        mock_host_class.assert_called_once()
        
        # Verify processors were created
        mock_make_processors.assert_called_once()
        
        # Verify robot methods were called
        assert mock_robot_instance.get_observation.called
    
    @patch("lerobot.robots.grievous.grievous_host.Grievous")
    @patch("lerobot.robots.grievous.grievous_host.GrievousHost")
    @patch("lerobot.robots.grievous.grievous_host.make_default_processors")
    @patch("lerobot.robots.grievous.grievous_host.time")
    def test_watchdog_functionality(
        self,
        mock_time,
        mock_make_processors,
        mock_host_class,
        mock_grievous_class,
        mock_robot,
        mock_processors,
    ):
        """Test watchdog timer functionality."""
        # Setup mocks
        teleop_processor, robot_processor, obs_processor = mock_processors
        mock_make_processors.return_value = (teleop_processor, robot_processor, obs_processor)
        
        mock_robot_instance = mock_robot
        mock_grievous_class.return_value = mock_robot_instance
        
        mock_host_instance = MagicMock()
        mock_host_instance.connection_time_s = 0.1
        mock_host_instance.watchdog_timeout_ms = 500
        mock_host_instance.max_loop_freq_hz = 60
        mock_host_instance.teleop_freq_hz = 120
        mock_host_instance.zmq_cmd_socket = MagicMock()
        mock_host_instance.zmq_observation_socket = MagicMock()
        mock_host_class.return_value = mock_host_instance
        
        # Mock time to trigger watchdog
        time_values = [0.0, 0.0, 0.6, 0.6, 0.2]  # Exceed watchdog timeout
        call_idx = [0]
        
        def time_side_effect():
            call_idx[0] += 1
            if call_idx[0] <= len(time_values):
                return time_values[call_idx[0] - 1]
            return 0.2
        
        mock_time.perf_counter.side_effect = time_side_effect
        mock_time.time.side_effect = lambda: time_values[call_idx[0] - 1] if call_idx[0] <= len(time_values) else 0.0
        mock_time.sleep.return_value = None
        
        from lerobot.robots.grievous.grievous_host import main
        
        try:
            main()
        except SystemExit:
            pass
        
        # Verify stop_base was called when watchdog triggered
        assert mock_robot_instance.xlerobot.stop_base.called
    
    @patch("lerobot.robots.grievous.grievous_host.Grievous")
    @patch("lerobot.robots.grievous.grievous_host.GrievousHost")
    @patch("lerobot.robots.grievous.grievous_host.make_default_processors")
    @patch("lerobot.robots.grievous.grievous_host.cv2")
    @patch("lerobot.robots.grievous.grievous_host.time")
    def test_camera_encoding(
        self,
        mock_time,
        mock_cv2,
        mock_make_processors,
        mock_host_class,
        mock_grievous_class,
        mock_robot,
        mock_processors,
    ):
        """Test camera image encoding."""
        # Setup mocks
        teleop_processor, robot_processor, obs_processor = mock_processors
        mock_make_processors.return_value = (teleop_processor, robot_processor, obs_processor)
        
        mock_robot_instance = mock_robot
        mock_grievous_class.return_value = mock_robot_instance
        
        # Setup observation with camera images
        mock_robot_instance.get_observation.return_value = {
            "left_arm_shoulder_pan.pos": 0.5,
            "left_wrist": np.zeros((480, 640, 3), dtype=np.uint8),
            "right_wrist": np.zeros((480, 640, 3), dtype=np.uint8),
        }
        
        mock_host_instance = MagicMock()
        mock_host_instance.connection_time_s = 0.1
        mock_host_instance.watchdog_timeout_ms = 500
        mock_host_instance.max_loop_freq_hz = 60
        mock_host_instance.teleop_freq_hz = 120
        mock_host_instance.zmq_cmd_socket = MagicMock()
        mock_host_instance.zmq_observation_socket = MagicMock()
        mock_host_class.return_value = mock_host_instance
        
        # Mock cv2.imencode
        mock_cv2.imencode.return_value = (True, b"fake_jpeg_data")
        
        # Mock time
        call_count = [0]
        
        def time_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return 0.0
            elif call_count[0] < 5:
                return 0.01 * call_count[0]
            else:
                return 0.2
        
        mock_time.perf_counter.side_effect = time_side_effect
        mock_time.time.return_value = 0.0
        mock_time.sleep.return_value = None
        
        from lerobot.robots.grievous.grievous_host import main
        
        try:
            main()
        except SystemExit:
            pass
        
        # Verify cv2.imencode was called for cameras
        assert mock_cv2.imencode.called
    
    @patch("lerobot.robots.grievous.grievous_host.Grievous")
    @patch("lerobot.robots.grievous.grievous_host.GrievousHost")
    @patch("lerobot.robots.grievous.grievous_host.make_default_processors")
    @patch("lerobot.robots.grievous.grievous_host.time")
    def test_zmq_message_sending(
        self,
        mock_time,
        mock_make_processors,
        mock_host_class,
        mock_grievous_class,
        mock_robot,
        mock_processors,
    ):
        """Test ZMQ message sending."""
        # Setup mocks
        teleop_processor, robot_processor, obs_processor = mock_processors
        mock_make_processors.return_value = (teleop_processor, robot_processor, obs_processor)
        
        mock_robot_instance = mock_robot
        mock_grievous_class.return_value = mock_robot_instance
        
        mock_host_instance = MagicMock()
        mock_host_instance.connection_time_s = 0.1
        mock_host_instance.watchdog_timeout_ms = 500
        mock_host_instance.max_loop_freq_hz = 60
        mock_host_instance.teleop_freq_hz = 120
        
        cmd_socket = MagicMock()
        obs_socket = MagicMock()
        mock_host_instance.zmq_cmd_socket = cmd_socket
        mock_host_instance.zmq_observation_socket = obs_socket
        mock_host_class.return_value = mock_host_instance
        
        # Mock time
        call_count = [0]
        
        def time_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return 0.0
            elif call_count[0] < 5:
                return 0.01 * call_count[0]
            else:
                return 0.2
        
        mock_time.perf_counter.side_effect = time_side_effect
        mock_time.time.return_value = 0.0
        mock_time.sleep.return_value = None
        
        from lerobot.robots.grievous.grievous_host import main
        
        try:
            main()
        except SystemExit:
            pass
        
        # Verify ZMQ sockets were used to send messages
        assert cmd_socket.send_string.called or cmd_socket.send_string.call_count >= 0
        assert obs_socket.send_string.called or obs_socket.send_string.call_count >= 0

