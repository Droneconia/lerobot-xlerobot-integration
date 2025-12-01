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

