#!/usr/bin/env python
"""Voice-controlled state machine for Grievous robot teleoperation.

Listens to voice commands from USB microphone using Vosk, filters for activation phrases,
and processes commands when activated. Manages control and recording states independently.
"""

import json
import logging
import queue
import sys
import threading
import time
from enum import Enum
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from lerobot.processor import make_default_processors
from lerobot.robots.grievous import Grievous
from lerobot.robots.grievous.config_grievous import GrievousConfig

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    import pyaudio
    PYAudio_AVAILABLE = True
except ImportError:
    PYAudio_AVAILABLE = False
    logging.warning("pyaudio not available")

try:
    from vosk import Model, KaldiRecognizer
    VOSK_AVAILABLE = True
except ImportError:
    VOSK_AVAILABLE = False
    logging.warning("vosk not available")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ControlMode(Enum):
    IDLE = "idle"
    ARM_TELEOP = "arm_teleop"
    BASE_TELEOP = "base_teleop"
    CALIBRATING = "calibrating"
    SHUTDOWN = "shutdown"


class RecordingMode(Enum):
    NOT_RECORDING = "not_recording"
    RECORDING = "recording"


class TeleopControlThread:
    """Separate thread for teleop control that runs at higher refresh rate.
    
    This thread continuously:
    1. Gets actions from leader arms
    2. Processes actions through processor pipelines
    3. Sends actions to follower (XLerobot) only when in ARM_TELEOP mode
    
    The thread runs all processing steps regardless of mode, but only sends
    actions when control_mode is ARM_TELEOP.
    """
    
    def __init__(
        self,
        robot: "Grievous",
        teleop_action_processor,
        action_processor,
        control_mode_getter,  # Function to get current control mode
        freq_hz: int = 120,
        motor_bus_lock: threading.Lock | None = None,
    ):
        """Initialize teleop control thread.
        
        Args:
            robot: Grievous robot instance
            teleop_action_processor: Processor for teleop actions
            action_processor: Processor for robot actions
            control_mode_getter: Function that returns current ControlMode
            freq_hz: Refresh rate for teleop control loop
            motor_bus_lock: Shared lock for serializing motor bus access
        """
        self.robot = robot
        self.teleop_action_processor = teleop_action_processor
        self.action_processor = action_processor
        self.control_mode_getter = control_mode_getter
        self.freq_hz = freq_hz
        self.motor_bus_lock = motor_bus_lock
        
        # Thread-safe storage for last action
        self._lock = threading.Lock()
        self._last_action: dict = {}
        self._running = False
        self._thread: threading.Thread | None = None
        
        # Timing collection for periodic reporting
        self._timing_lock = threading.Lock()
        self._loop_times: list[float] = []  # Store loop times to calculate frequencies
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
                action = self.robot.get_action()
                
                # Validate action
                action_valid = True
                if action is None:
                    logger.warning("Received None action, skipping send")
                    action_valid = False
                elif not isinstance(action, dict):
                    logger.error(f"Invalid action type: {type(action)}, expected dict. Skipping send.")
                    action_valid = False
                elif not action:
                    logger.warning("Received empty action dict, skipping send")
                    action_valid = False
                
                # Only send action to follower if in ARM_TELEOP mode
                # Thread runs all processing regardless of mode, but skips sending in other modes
                current_control_mode = self.control_mode_getter()
                if action_valid and current_control_mode == ControlMode.ARM_TELEOP:
                    # Send action to follower (uses motor bus - must be serialized)
                    if self.motor_bus_lock:
                        with self.motor_bus_lock:
                            self.robot.send_action(action)
                    else:
                        self.robot.send_action(action)
                    
                    # Update thread-safe storage
                    with self._lock:
                        self._last_action = action
                elif action_valid:
                    # Action is valid but not in ARM_TELEOP mode - still update storage but don't send
                    with self._lock:
                        self._last_action = action
                else:
                    logger.warning("Invalid action, skipping send")
                
            except Exception as e:
                logger.error(f"Error in teleop control loop: {e}", exc_info=True)
            
            # Rate limiting - sleep at the end to reach desired frequency
            elapsed = time.perf_counter() - loop_start
            sleep_time = max(1 / self.freq_hz - elapsed, 0)
            if sleep_time > 0:
                time.sleep(sleep_time)
            
            # Collect timing data
            total_loop_time = (time.perf_counter() - loop_start) * 1000  # ms
            loop_frequency = 1000.0 / total_loop_time if total_loop_time > 0 else 0  # Hz
            
            with self._timing_lock:
                current_time = time.perf_counter()
                
                # Track when timing data collection started
                if self._timing_data_start_time is None:
                    self._timing_data_start_time = current_time
                
                # Store loop frequency
                self._loop_times.append(loop_frequency)
                
                # Print frequency stats every second
                if current_time - self._last_print_time >= 1.0:
                    if self._loop_times:
                        loop_count = len(self._loop_times)
                        actual_time_span = current_time - self._timing_data_start_time
                        min_freq = min(self._loop_times)
                        max_freq = max(self._loop_times)
                        overall_freq = loop_count / actual_time_span if actual_time_span > 0 else 0
                        
                        print(f"TeleopControlThread - Loops: {loop_count} | Overall Freq: {overall_freq:.1f}Hz | Min: {min_freq:.1f}Hz | Max: {max_freq:.1f}Hz")
                    
                    # Reset timing data
                    self._loop_times.clear()
                    self._timing_data_start_time = None
                    self._last_print_time = current_time
    
    def get_last_action(self) -> dict:
        """Get the last processed robot action (thread-safe).
        
        Returns:
            Dictionary containing the last robot action
        """
        with self._lock:
            return self._last_action.copy()


class VoiceCommandStateMachine:
    """Voice-controlled state machine for robot teleoperation."""
    
    ACTIVATION_PHRASES = [
        "hey grievous", "grievous on", "grievous start",
        "listen grievous", "grievous listen",
        "activate grievous", "grievous activate",
        "wake up grievous", "grievous wake up",
    ]
    
    CONTROL_COMMANDS = {
        "idle": ControlMode.IDLE,
        "stop": ControlMode.IDLE,
        "stop teleop": ControlMode.IDLE,
        "stop arm teleop": ControlMode.IDLE,
        "stop base teleop": ControlMode.IDLE,
        "pause": ControlMode.IDLE,
        "arm": ControlMode.ARM_TELEOP,
        "arms": ControlMode.ARM_TELEOP,
        "arm teleop": ControlMode.ARM_TELEOP,
        "start arm teleop": ControlMode.ARM_TELEOP,
        "begin arm teleop": ControlMode.ARM_TELEOP,
        "arm control": ControlMode.ARM_TELEOP,
        "base": ControlMode.BASE_TELEOP,
        "base teleop": ControlMode.BASE_TELEOP,
        "start base teleop": ControlMode.BASE_TELEOP,
        "begin base teleop": ControlMode.BASE_TELEOP,
        "base control": ControlMode.BASE_TELEOP,
        "calibrate": ControlMode.CALIBRATING,
        "calibration": ControlMode.CALIBRATING,
        "start calibration": ControlMode.CALIBRATING,
        "shutdown": ControlMode.SHUTDOWN,
        "shut down": ControlMode.SHUTDOWN,
        "exit": ControlMode.SHUTDOWN,
        "quit": ControlMode.SHUTDOWN,
    }
    
    RECORDING_COMMANDS = {
        "start recording": RecordingMode.RECORDING,
        "begin recording": RecordingMode.RECORDING,
        "record": RecordingMode.RECORDING,
        "start record": RecordingMode.RECORDING,
        "end recording": RecordingMode.NOT_RECORDING,
        "end record": RecordingMode.NOT_RECORDING,
        "end": RecordingMode.NOT_RECORDING,
        "finish": RecordingMode.NOT_RECORDING,
    }
    
    def __init__(self, model_path: str | Path | None = None, sample_rate: int = 16000, chunk_size: int = 4000):
        self.control_mode = ControlMode.IDLE
        self.recording_mode = RecordingMode.NOT_RECORDING
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        
        self.model = None
        self.recognizer = None
        self.audio_stream = None
        self.audio = None
        self.command_queue = queue.Queue()
        self.recognition_thread = None
        self.is_listening = False
        
        self.peak_levels = []
        self.recognized_texts = []
        self.last_output_time = time.time()
        self.output_interval = 1.0
        
        self.is_activated = False
        self.activation_expiry = 0.0
        self.activation_window = 20.0
        
        # Robot control
        self.robot = None
        self.robot_initialized = False
        self.teleop_action_processor = None
        self.action_processor = None
        self.control_loop_fps = 120  # Control loop frequency (Hz)
        self.control_thread: TeleopControlThread | None = None
        
        if VOSK_AVAILABLE and PYAudio_AVAILABLE:
            self._init_voice_recognition(model_path)
    
    def _find_usb_microphone(self, pyaudio_instance, device_name_keyword="usb"):
        """Find USB microphone device index."""
        device_count = pyaudio_instance.get_device_count()
        for i in range(device_count):
            device_info = pyaudio_instance.get_device_info_by_index(i)
            device_name = device_info.get("name", "").lower()
            max_input_channels = device_info.get("maxInputChannels", 0)
            if device_name_keyword in device_name and max_input_channels > 0:
                logger.info(f"Found USB microphone: Device {i} - {device_info.get('name')}")
                return i
        logger.warning(f"No USB microphone found with keyword '{device_name_keyword}'. Using default.")
        return None
    
    def _get_compatible_sample_rate(self, pyaudio_instance, device_index, preferred_rate=16000):
        """Find a compatible sample rate for the audio device."""
        sample_rates = [preferred_rate, 44100, 48000, 22050, 24000, 8000, 11025, 12000]
        for rate in sample_rates:
            try:
                test_stream = pyaudio_instance.open(
                    format=pyaudio.paInt16, channels=1, rate=rate,
                    input=True, input_device_index=device_index, frames_per_buffer=self.chunk_size
                )
                test_stream.stop_stream()
                test_stream.close()
                logger.info(f"Device supports sample rate: {rate} Hz")
                return rate
            except Exception:
                continue
        logger.error("No compatible sample rate found")
        return None
    
    def _calculate_peak_level(self, audio_data, sample_width=2):
        """Calculate peak audio level from raw audio data."""
        if not NUMPY_AVAILABLE:
            return 0.0
        if sample_width == 2:
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
        else:
            audio_array = np.frombuffer(audio_data, dtype=np.int8)
        if len(audio_array) > 0:
            peak = np.abs(audio_array).max()
            max_value = 32767.0 if sample_width == 2 else 127.0
            return peak / max_value
        return 0.0
    
    def _init_voice_recognition(self, model_path: str | Path | None):
        """Initialize Vosk model and audio stream."""
        try:
            if model_path is None:
                model_path = Path(__file__).parent / "vosk-models" / "vosk-model-small-en-us-0.15"
            model_path = Path(model_path)
            if not model_path.exists():
                raise FileNotFoundError(f"Vosk model not found at {model_path}")
            
            self.audio = pyaudio.PyAudio()
            device_index = self._find_usb_microphone(self.audio)
            compatible_rate = self._get_compatible_sample_rate(self.audio, device_index, self.sample_rate)
            if compatible_rate is None:
                raise RuntimeError("Could not find a compatible sample rate")
            
            if compatible_rate != self.sample_rate:
                logger.info(f"Using sample rate {compatible_rate} Hz instead of {self.sample_rate} Hz")
                self.sample_rate = compatible_rate
            
            self.model = Model(str(model_path))
            self.recognizer = KaldiRecognizer(self.model, self.sample_rate)
            self.recognizer.SetWords(True)
            
            self.audio_stream = self.audio.open(
                format=pyaudio.paInt16, channels=1, rate=self.sample_rate,
                input=True, input_device_index=device_index, frames_per_buffer=self.chunk_size
            )
            logger.info(f"Voice recognition initialized with sample rate {self.sample_rate} Hz")
        except Exception as e:
            logger.error(f"Failed to initialize voice recognition: {e}")
            self.model = None
            self.recognizer = None
            if hasattr(self, 'audio') and self.audio:
                try:
                    self.audio.terminate()
                except:
                    pass
    
    def _listen_for_commands(self):
        """Background thread that continuously listens for voice commands."""
        if not self.audio_stream or not self.recognizer:
            return
        
        logger.info("Starting voice command listener...")
        self.is_listening = True
        
        while self.is_listening:
            try:
                data = self.audio_stream.read(self.chunk_size, exception_on_overflow=False)
                peak = self._calculate_peak_level(data)
                self.peak_levels.append(peak)
                
                if self.recognizer.AcceptWaveform(data):
                    result = json.loads(self.recognizer.Result())
                    text = result.get("text", "").strip().lower()
                    if text:
                        logger.info(f"Recognized: '{text}'")
                        self.command_queue.put(text)
                        self.recognized_texts.append(text)
            except queue.Full:
                pass
            except Exception as e:
                logger.error(f"Error in voice recognition: {e}")
                time.sleep(0.1)
    
    def start_listening(self):
        """Start the voice command listener in a background thread."""
        if not self.is_listening and self.audio_stream and self.recognizer:
            self.recognition_thread = threading.Thread(target=self._listen_for_commands, daemon=True)
            self.recognition_thread.start()
            logger.info("Voice command listener started")
    
    def stop_listening(self):
        """Stop the voice command listener."""
        self.is_listening = False
        if self.recognition_thread and self.recognition_thread.is_alive():
            self.recognition_thread.join(timeout=2.0)
    
    def _is_activation_phrase(self, command: str) -> bool:
        """Check if a command is an activation phrase."""
        command = command.lower().strip()
        if command in self.ACTIVATION_PHRASES:
            return True
        for phrase in self.ACTIVATION_PHRASES:
            if phrase in command or command in phrase:
                return True
        return False
    
    def _activate_listening(self):
        """Activate the system to listen for commands."""
        self.is_activated = True
        self.activation_expiry = time.time() + self.activation_window
        logger.info(f"Activated! Listening for {self.activation_window} seconds.")
    
    def _check_activation_status(self) -> bool:
        """Check if the system is currently activated."""
        if not self.is_activated:
            return False
        if time.time() > self.activation_expiry:
            self.is_activated = False
            logger.info("Activation window expired.")
            return False
        return True
    
    def _interpret_command(self, command: str) -> tuple[ControlMode | None, RecordingMode | None]:
        """Interpret a voice command and return target states."""
        command = command.lower().strip()
        control_mode = None
        recording_mode = None
        
        if command in self.CONTROL_COMMANDS:
            control_mode = self.CONTROL_COMMANDS[command]
        else:
            for cmd_key, target_mode in self.CONTROL_COMMANDS.items():
                if cmd_key in command:
                    control_mode = target_mode
                    break
        
        if command in self.RECORDING_COMMANDS:
            recording_mode = self.RECORDING_COMMANDS[command]
        else:
            for cmd_key, target_mode in self.RECORDING_COMMANDS.items():
                if cmd_key in command:
                    recording_mode = target_mode
                    break
        
        return control_mode, recording_mode
    
    def _init_robot(self):
        """Initialize and connect the Grievous robot (blocks until complete)."""
        try:
            logger.info("Configuring Grievous robot...")
            robot_config = GrievousConfig(id="grievous_robot")
            self.robot = Grievous(robot_config)
            
            logger.info("Connecting Grievous robot (using existing calibration)...")
            self.robot.connect(calibrate=False)
            logger.info("Grievous connected successfully")
            
            logger.info("Initializing processors...")
            self.teleop_action_processor, self.action_processor, _ = make_default_processors()
            logger.info("Processors initialized")
            
            # Create and start control thread
            self.control_thread = TeleopControlThread(
                robot=self.robot,
                teleop_action_processor=self.teleop_action_processor,
                action_processor=self.action_processor,
                control_mode_getter=lambda: self.control_mode,
                freq_hz=self.control_loop_fps,
                motor_bus_lock=None,  # Can add motor bus lock if needed
            )
            self.control_thread.start()
            
            self.robot_initialized = True
            logger.info("Robot initialization complete - ready to accept commands")
        except Exception as e:
            logger.error(f"Failed to initialize robot: {e}")
            self.robot = None
            self.robot_initialized = False
            raise
    
    def process_commands(self):
        """Process pending voice commands from the queue."""
        # Block commands until robot is initialized
        if not self.robot_initialized:
            return
        
        self._check_activation_status()
        
        try:
            while True:
                command = self.command_queue.get_nowait()
                
                if self._is_activation_phrase(command):
                    self._activate_listening()
                    continue
                
                if not self._check_activation_status():
                    continue
                
                control_mode, recording_mode = self._interpret_command(command)
                
                if control_mode is not None:
                    logger.info(f"Control mode: {self.control_mode.value} -> {control_mode.value}")
                    self.control_mode = control_mode
                    if control_mode == ControlMode.SHUTDOWN:
                        self._shutdown()
                
                if recording_mode is not None:
                    logger.info(f"Recording mode: {self.recording_mode.value} -> {recording_mode.value}")
                    self.recording_mode = recording_mode
        except queue.Empty:
            pass
    
    def _shutdown(self):
        """Shutdown the state machine."""
        logger.info("Shutting down...")
        self.stop_listening()
        
        # Stop control thread
        if self.control_thread:
            self.control_thread.stop()
        
        if self.audio_stream:
            self.audio_stream.stop_stream()
            self.audio_stream.close()
        if self.audio:
            self.audio.terminate()
        if self.robot:
            logger.info("Disconnecting robot...")
            self.robot.disconnect()
            logger.info("Robot disconnected")
    
    def _output_status(self):
        """Output current state, peak level, and recognized text every second."""
        current_time = time.time()
        if current_time - self.last_output_time >= self.output_interval:
            if self.peak_levels:
                if NUMPY_AVAILABLE:
                    avg_peak = float(np.mean(self.peak_levels))
                    max_peak = float(np.max(self.peak_levels))
                else:
                    avg_peak = sum(self.peak_levels) / len(self.peak_levels)
                    max_peak = max(self.peak_levels)
            else:
                avg_peak = 0.0
                max_peak = 0.0
            
            text_output = " ".join(self.recognized_texts) if self.recognized_texts else "(no speech detected)"
            state_str = f"Control: {self.control_mode.value}, Recording: {self.recording_mode.value}"
            
            if self.is_activated:
                remaining_time = max(0, self.activation_expiry - time.time())
                activation_status = f"LISTENING ({remaining_time:.1f}s)"
            else:
                activation_status = "WAITING (say activation phrase)"
            
            print(f"[{time.strftime('%H:%M:%S')}] {activation_status} | State: {state_str} | Peak: {max_peak:.3f} (avg: {avg_peak:.3f}) | Text: {text_output}")
            
            self.peak_levels = []
            self.recognized_texts = []
            self.last_output_time = current_time
    
    def run(self, fps: int = 10):
        """Run the main state machine loop."""
        logger.info("Starting voice-controlled state machine...")
        logger.info(f"Initial state - Control: {self.control_mode.value}, Recording: {self.recording_mode.value}")
        
        # Initialize robot at startup (blocks until complete)
        logger.info("Initializing robot (this may take a moment)...")
        try:
            self._init_robot()
        except Exception as e:
            logger.error(f"Robot initialization failed: {e}")
            logger.error("Cannot continue without robot. Exiting.")
            return
        
        logger.info("Say an activation phrase to enable commands.")
        
        if self.model and self.recognizer:
            self.start_listening()
        else:
            logger.warning("Voice recognition not available.")
        
        try:
            loop_time = 1.0 / fps
            while self.control_mode != ControlMode.SHUTDOWN:
                loop_start = time.perf_counter()
                
                # Process voice commands (blocked until robot initialized)
                self.process_commands()
                
                # Control loop runs in separate thread, no need to call it here
                
                # Output status (at lower frequency)
                self._output_status()
                
                elapsed = time.perf_counter() - loop_start
                sleep_time = max(0, loop_time - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            self.control_mode = ControlMode.SHUTDOWN
        finally:
            if self.control_mode != ControlMode.SHUTDOWN:
                self.control_mode = ControlMode.SHUTDOWN
            self._shutdown()
            logger.info("State machine stopped")


def main():
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Voice-controlled state machine for Grievous robot")
    parser.add_argument("--model-path", type=str, default=None, help="Path to Vosk model directory")
    parser.add_argument("--fps", type=int, default=10, help="Main loop frames per second (default: 10)")
    args = parser.parse_args()
    
    state_machine = VoiceCommandStateMachine(model_path=args.model_path)
    state_machine.run(fps=args.fps)


if __name__ == "__main__":
    main()
