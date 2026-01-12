#!/usr/bin/env python
"""Voice-controlled state machine for Grievous robot teleoperation.

This module implements a state machine that listens to voice commands from a microphone
and interprets them to determine what code should run at any given time.

The state machine has two independent dimensions:
1. Control Mode: IDLE / ARM_TELEOP / BASE_TELEOP / CALIBRATING / SHUTDOWN
2. Recording Mode: NOT_RECORDING / RECORDING

Control modes and recording mode operate independently. You can have any control mode
active while recording or not recording.

On startup, the state machine enters IDLE with NOT_RECORDING.
"""

import json
import logging
import os
import queue
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Any

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    logging.warning("numpy not available. Peak calculation will not work.")

try:
    import pyaudio
    PYAudio_AVAILABLE = True
except ImportError as e:
    PYAudio_AVAILABLE = False
    logging.warning(f"pyaudio not available. Voice commands will not work. Error: {e}")

try:
    from vosk import Model, KaldiRecognizer
    VOSK_AVAILABLE = True
except ImportError:
    VOSK_AVAILABLE = False
    logging.warning("vosk not available. Voice commands will not work.")


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ControlMode(Enum):
    """Control mode states."""
    IDLE = "idle"
    ARM_TELEOP = "arm_teleop"
    BASE_TELEOP = "base_teleop"
    CALIBRATING = "calibrating"
    SHUTDOWN = "shutdown"


class RecordingMode(Enum):
    """Recording mode states."""
    NOT_RECORDING = "not_recording"
    RECORDING = "recording"


class VoiceCommandStateMachine:
    """State machine that processes voice commands to control robot operations.
    
    The state machine listens to microphone input, recognizes voice commands using Vosk,
    and transitions between states based on the recognized commands.
    
    State structure:
    - control_mode: ControlMode (IDLE, ARM_TELEOP, BASE_TELEOP, CALIBRATING, SHUTDOWN)
    - recording_mode: RecordingMode (NOT_RECORDING, RECORDING)
    
    Control modes operate independently from recording mode.
    
    The system requires an activation phrase before accepting commands. After hearing
    an activation phrase, the system listens for commands for 10 seconds.
    """
    
    # Activation phrases that enable command listening
    ACTIVATION_PHRASES = [
        "hey grievous",
        "grievous on",
        "grievous start",
        "listen grievous",
        "grievous listen",
        "activate grievous",
        "grievous activate",
        "wake up grievous",
        "grievous wake up",
    ]
    
    # Voice command mappings for control mode
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
    
    # Voice command mappings for recording mode
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
    
    def __init__(
        self,
        model_path: str | Path | None = None,
        sample_rate: int = 16000,
        chunk_size: int = 4000,
    ):
        """Initialize the voice command state machine.
        
        Args:
            model_path: Path to Vosk model directory. If None, uses default model.
            sample_rate: Audio sample rate in Hz (default: 16000 for Vosk)
            chunk_size: Audio chunk size for processing (default: 4000)
        """
        # State dimensions
        self.control_mode = ControlMode.IDLE
        self.previous_control_mode = ControlMode.IDLE
        self.recording_mode = RecordingMode.NOT_RECORDING
        self.previous_recording_mode = RecordingMode.NOT_RECORDING
        
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        
        # Voice recognition setup
        self.model = None
        self.recognizer = None
        self.audio_stream = None
        self.audio = None
        self.command_queue = queue.Queue()
        self.recognition_thread = None
        self.is_listening = False
        
        # Audio monitoring for periodic output
        self.peak_levels = []
        self.recognized_texts = []
        self.last_output_time = time.time()
        self.output_interval = 1.0  # Output every second
        
        # Activation phrase system
        self.is_activated = False  # Whether system is listening for commands
        self.activation_expiry = 0.0  # Timestamp when activation expires
        self.activation_window = 20.0  # Seconds to listen after activation
        
        # State-specific data
        self.state_data: dict[str, Any] = {}
        
        # Initialize Vosk model
        if VOSK_AVAILABLE and PYAudio_AVAILABLE:
            self._init_voice_recognition(model_path)
        else:
            logger.warning("Voice recognition not available. Install vosk and pyaudio.")
    
    def _find_usb_microphone(self, pyaudio_instance, device_name_keyword="usb"):
        """Find USB microphone device index.
        
        Args:
            pyaudio_instance: PyAudio instance
            device_name_keyword: Keyword to search for in device name (default: "usb")
            
        Returns:
            Device index if found, None otherwise
        """
        device_count = pyaudio_instance.get_device_count()
        logger.info(f"Found {device_count} audio devices")
        
        for i in range(device_count):
            device_info = pyaudio_instance.get_device_info_by_index(i)
            device_name = device_info.get("name", "").lower()
            max_input_channels = device_info.get("maxInputChannels", 0)
            
            if device_name_keyword in device_name and max_input_channels > 0:
                logger.info(f"Found USB microphone: Device {i} - {device_info.get('name')}")
                return i
        
        logger.warning(f"No USB microphone found with keyword '{device_name_keyword}'. Using default input device.")
        return None
    
    def _get_compatible_sample_rate(self, pyaudio_instance, device_index, preferred_rate=16000):
        """Find a compatible sample rate for the audio device.
        
        Args:
            pyaudio_instance: PyAudio instance
            device_index: Device index (None for default)
            preferred_rate: Preferred sample rate (default: 16000)
            
        Returns:
            Compatible sample rate, or None if none found
        """
        # Common sample rates to try (prefer 16000 for Vosk, but try others)
        sample_rates = [preferred_rate, 44100, 48000, 22050, 24000, 8000, 11025, 12000]
        
        for rate in sample_rates:
            try:
                # Test if the sample rate is supported by trying to open a stream
                test_stream = pyaudio_instance.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=rate,
                    input=True,
                    input_device_index=device_index,
                    frames_per_buffer=self.chunk_size,
                )
                test_stream.stop_stream()
                test_stream.close()
                logger.info(f"Device supports sample rate: {rate} Hz")
                return rate
            except Exception as e:
                logger.debug(f"Sample rate {rate} Hz not supported: {e}")
                continue
        
        logger.error("No compatible sample rate found for the audio device")
        return None
    
    def _calculate_peak_level(self, audio_data, sample_width=2):
        """Calculate peak audio level from raw audio data.
        
        Args:
            audio_data: Raw audio bytes
            sample_width: Sample width in bytes (2 for 16-bit)
            
        Returns:
            Peak level as a float (0.0 to 1.0)
        """
        if not NUMPY_AVAILABLE:
            return 0.0
        
        # Convert bytes to numpy array
        if sample_width == 2:
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
        else:
            audio_array = np.frombuffer(audio_data, dtype=np.int8)
        
        # Calculate peak (normalized to 0-1)
        if len(audio_array) > 0:
            peak = np.abs(audio_array).max()
            max_value = 32767.0 if sample_width == 2 else 127.0
            return peak / max_value
        
        return 0.0
    
    def _init_voice_recognition(self, model_path: str | Path | None):
        """Initialize Vosk model and audio stream."""
        try:
            # Use default model path if not provided
            if model_path is None:
                model_path = Path(__file__).parent / "vosk-models" / "vosk-model-small-en-us-0.15"
            
            model_path = Path(model_path)
            if not model_path.exists():
                raise FileNotFoundError(f"Vosk model not found at {model_path}")
            
            # Initialize PyAudio first to check device capabilities
            self.audio = pyaudio.PyAudio()
            
            # Find USB microphone
            device_index = self._find_usb_microphone(self.audio)
            
            # Find a compatible sample rate for the device
            compatible_rate = self._get_compatible_sample_rate(self.audio, device_index, self.sample_rate)
            if compatible_rate is None:
                raise RuntimeError("Could not find a compatible sample rate for the audio device")
            
            # Update sample rate if it changed
            if compatible_rate != self.sample_rate:
                logger.info(f"Using sample rate {compatible_rate} Hz instead of {self.sample_rate} Hz (device compatibility)")
                self.sample_rate = compatible_rate
            
            # Load Vosk model with the actual sample rate
            logger.info(f"Loading Vosk model from {model_path}")
            self.model = Model(str(model_path))
            self.recognizer = KaldiRecognizer(self.model, self.sample_rate)
            self.recognizer.SetWords(True)
            
            # Open audio stream with the compatible sample rate
            self.audio_stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.sample_rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=self.chunk_size,
            )
            
            logger.info(f"Voice recognition initialized successfully with sample rate {self.sample_rate} Hz")
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
            logger.warning("Audio stream or recognizer not initialized")
            return
        
        logger.info("Starting voice command listener...")
        self.is_listening = True
        
        while self.is_listening:
            try:
                data = self.audio_stream.read(self.chunk_size, exception_on_overflow=False)
                
                # Calculate peak level for monitoring
                peak = self._calculate_peak_level(data)
                self.peak_levels.append(peak)
                
                # Process with Vosk
                if self.recognizer.AcceptWaveform(data):
                    result = json.loads(self.recognizer.Result())
                    text = result.get("text", "").strip().lower()
                    
                    if text:
                        logger.info(f"Recognized command: '{text}'")
                        self.command_queue.put(text)
                        # Store recognized text for periodic output
                        self.recognized_texts.append(text)
                else:
                    # Partial result (not stored, only final results are used)
                    partial = json.loads(self.recognizer.PartialResult())
                    partial_text = partial.get("partial", "").strip().lower()
                    if partial_text:
                        logger.debug(f"Partial recognition: '{partial_text}'")
            
            except queue.Full:
                logger.warning("Command queue full, dropping command")
            except Exception as e:
                logger.error(f"Error in voice recognition: {e}")
                time.sleep(0.1)
    
    def start_listening(self):
        """Start the voice command listener in a background thread."""
        if not self.is_listening and self.audio_stream and self.recognizer:
            self.recognition_thread = threading.Thread(target=self._listen_for_commands, daemon=True)
            self.recognition_thread.start()
            logger.info("Voice command listener started")
        else:
            logger.warning("Cannot start listener: audio not initialized")
    
    def stop_listening(self):
        """Stop the voice command listener."""
        self.is_listening = False
        if self.recognition_thread and self.recognition_thread.is_alive():
            self.recognition_thread.join(timeout=2.0)
        logger.info("Voice command listener stopped")
    
    def _is_activation_phrase(self, command: str) -> bool:
        """Check if a command is an activation phrase.
        
        Args:
            command: Recognized voice command text
            
        Returns:
            True if the command matches an activation phrase
        """
        command = command.lower().strip()
        
        # Direct match
        if command in self.ACTIVATION_PHRASES:
            return True
        
        # Fuzzy matching for partial phrases
        for phrase in self.ACTIVATION_PHRASES:
            if phrase in command or command in phrase:
                return True
        
        return False
    
    def _activate_listening(self):
        """Activate the system to listen for commands for the next 10 seconds."""
        self.is_activated = True
        self.activation_expiry = time.time() + self.activation_window
        logger.info(f"Activation phrase detected! Listening for commands for {self.activation_window} seconds.")
    
    def _check_activation_status(self) -> bool:
        """Check if the system is currently activated and within the listening window.
        
        Returns:
            True if activated and within the time window, False otherwise
        """
        if not self.is_activated:
            return False
        
        # Check if activation window has expired
        if time.time() > self.activation_expiry:
            self.is_activated = False
            logger.info("Activation window expired. Say an activation phrase to enable commands.")
            return False
        
        return True
    
    def _interpret_command(self, command: str) -> tuple[ControlMode | None, RecordingMode | None]:
        """Interpret a voice command and return target states for each dimension.
        
        Args:
            command: Recognized voice command text
            
        Returns:
            Tuple of (control_mode, recording_mode) - any can be None if unchanged
        """
        command = command.lower().strip()
        
        control_mode = None
        recording_mode = None
        
        # Check control commands
        if command in self.CONTROL_COMMANDS:
            control_mode = self.CONTROL_COMMANDS[command]
        else:
            # Fuzzy matching for partial commands
            for cmd_key, target_mode in self.CONTROL_COMMANDS.items():
                if cmd_key in command:
                    control_mode = target_mode
                    break
        
        # Check recording commands
        if command in self.RECORDING_COMMANDS:
            recording_mode = self.RECORDING_COMMANDS[command]
        else:
            # Fuzzy matching for partial commands
            for cmd_key, target_mode in self.RECORDING_COMMANDS.items():
                if cmd_key in command:
                    recording_mode = target_mode
                    break
        
        return control_mode, recording_mode
    
    def _transition_control_mode(self, new_mode: ControlMode):
        """Handle control mode transition with entry/exit actions.
        
        Args:
            new_mode: Target control mode
        """
        if new_mode == self.control_mode:
            return
        
        logger.info(f"Control mode transition: {self.control_mode.value} -> {new_mode.value}")
        
        # Exit actions for current control mode
        self._exit_control_mode(self.control_mode)
        
        # Update state
        self.previous_control_mode = self.control_mode
        self.control_mode = new_mode
        
        # Entry actions for new control mode
        self._enter_control_mode(new_mode)
    
    def _transition_recording_mode(self, new_mode: RecordingMode):
        """Handle recording mode transition with entry/exit actions.
        
        Args:
            new_mode: Target recording mode
        """
        if new_mode == self.recording_mode:
            return
        
        logger.info(f"Recording mode transition: {self.recording_mode.value} -> {new_mode.value}")
        
        # Exit actions for current recording mode
        self._exit_recording_mode(self.recording_mode)
        
        # Update state
        self.previous_recording_mode = self.recording_mode
        self.recording_mode = new_mode
        
        # Entry actions for new recording mode
        self._enter_recording_mode(new_mode)
    
    def _enter_control_mode(self, mode: ControlMode):
        """Perform entry actions when entering a control mode.
        
        Args:
            mode: Control mode being entered
        """
        logger.info(f"Entering control mode: {mode.value}")
        
        if mode == ControlMode.IDLE:
            self._enter_idle_control()
        elif mode == ControlMode.ARM_TELEOP:
            self._start_arm_teleop()
        elif mode == ControlMode.BASE_TELEOP:
            self._start_base_teleop()
        elif mode == ControlMode.CALIBRATING:
            self._start_calibration()
        elif mode == ControlMode.SHUTDOWN:
            self._shutdown()
    
    def _exit_control_mode(self, mode: ControlMode):
        """Perform exit actions when leaving a control mode.
        
        Args:
            mode: Control mode being exited
        """
        logger.info(f"Exiting control mode: {mode.value}")
        
        if mode == ControlMode.ARM_TELEOP:
            self._stop_arm_teleop()
        elif mode == ControlMode.BASE_TELEOP:
            self._stop_base_teleop()
        elif mode == ControlMode.CALIBRATING:
            self._stop_calibration()
    
    def _enter_recording_mode(self, mode: RecordingMode):
        """Perform entry actions when entering a recording mode.
        
        Args:
            mode: Recording mode being entered
        """
        logger.info(f"Entering recording mode: {mode.value}")
        
        if mode == RecordingMode.RECORDING:
            self._start_recording()
        elif mode == RecordingMode.NOT_RECORDING:
            self._stop_recording()
    
    def _exit_recording_mode(self, mode: RecordingMode):
        """Perform exit actions when leaving a recording mode.
        
        Args:
            mode: Recording mode being exited
        """
        logger.info(f"Exiting recording mode: {mode.value}")
        
        if mode == RecordingMode.RECORDING:
            self._stop_recording()
    
    def _enter_idle_control(self):
        """Enter idle control mode - stop all teleop operations."""
        logger.info("Entering IDLE control mode")
        # Ensure all teleop operations are stopped
        self._stop_arm_teleop()
        self._stop_base_teleop()
    
    def _start_arm_teleop(self):
        """Start arm teleoperation mode - PLACEHOLDER."""
        logger.info("=== STARTING ARM TELEOP MODE ===")
        logger.info("PLACEHOLDER: Implement arm teleop logic here")
        # TODO: Implement arm teleop logic
        # Example:
        # - Connect to robot
        # - Start teleop loop for arms only
        # - Get actions from leader arms
        # - Send actions to follower arms
        # - Keep base stationary
        self.state_data["arm_teleop_start_time"] = time.time()
    
    def _stop_arm_teleop(self):
        """Stop arm teleoperation mode - PLACEHOLDER."""
        logger.info("=== STOPPING ARM TELEOP MODE ===")
        logger.info("PLACEHOLDER: Implement arm teleop cleanup here")
        # TODO: Implement arm teleop cleanup
        # Example:
        # - Stop arm teleop loop
        # - Disconnect from robot (optional)
        if "arm_teleop_start_time" in self.state_data:
            duration = time.time() - self.state_data["arm_teleop_start_time"]
            logger.info(f"Arm teleop ran for {duration:.2f} seconds")
            del self.state_data["arm_teleop_start_time"]
    
    def _start_base_teleop(self):
        """Start base teleoperation mode - PLACEHOLDER."""
        logger.info("=== STARTING BASE TELEOP MODE ===")
        logger.info("PLACEHOLDER: Implement base teleop logic here")
        # TODO: Implement base teleop logic
        # Example:
        # - Connect to robot
        # - Start teleop loop for base only
        # - Get base commands from input (keyboard/voice/etc)
        # - Send base velocities to robot
        # - Keep arms stationary
        self.state_data["base_teleop_start_time"] = time.time()
    
    def _stop_base_teleop(self):
        """Stop base teleoperation mode - PLACEHOLDER."""
        logger.info("=== STOPPING BASE TELEOP MODE ===")
        logger.info("PLACEHOLDER: Implement base teleop cleanup here")
        # TODO: Implement base teleop cleanup
        # Example:
        # - Stop base teleop loop
        # - Set base velocities to zero
        # - Disconnect from robot (optional)
        if "base_teleop_start_time" in self.state_data:
            duration = time.time() - self.state_data["base_teleop_start_time"]
            logger.info(f"Base teleop ran for {duration:.2f} seconds")
            del self.state_data["base_teleop_start_time"]
    
    def _start_recording(self):
        """Start recording mode - PLACEHOLDER."""
        logger.info("=== STARTING RECORDING MODE ===")
        logger.info("PLACEHOLDER: Implement recording logic here")
        # TODO: Implement recording logic
        # Example:
        # - Connect to robot
        # - Initialize dataset writer
        # - Set up cloud upload connection
        # - Start recording loop
        # - Save observations and actions
        # - Upload data to cloud in real-time or batches
        self.state_data["recording_start_time"] = time.time()
        self.state_data["recording_episode"] = 0
    
    def _stop_recording(self):
        """Stop recording mode - PLACEHOLDER."""
        logger.info("=== STOPPING RECORDING MODE ===")
        logger.info("PLACEHOLDER: Implement recording cleanup here")
        # TODO: Implement recording cleanup
        # Example:
        # - Stop recording loop
        # - Finalize dataset
        # - Upload final data to cloud
        # - Save metadata
        if "recording_start_time" in self.state_data:
            duration = time.time() - self.state_data["recording_start_time"]
            logger.info(f"Recording ran for {duration:.2f} seconds")
            del self.state_data["recording_start_time"]
    
    def _start_calibration(self):
        """Start calibration mode - PLACEHOLDER."""
        logger.info("=== STARTING CALIBRATION ===")
        logger.info("PLACEHOLDER: Implement calibration logic here")
        # TODO: Implement calibration logic
        # Example:
        # - Connect to robot
        # - Run calibration sequence
        # - Save calibration data
        self.state_data["calibration_start_time"] = time.time()
    
    def _stop_calibration(self):
        """Stop calibration mode - PLACEHOLDER."""
        logger.info("=== STOPPING CALIBRATION ===")
        logger.info("PLACEHOLDER: Implement calibration cleanup here")
        # TODO: Implement calibration cleanup
        if "calibration_start_time" in self.state_data:
            duration = time.time() - self.state_data["calibration_start_time"]
            logger.info(f"Calibration ran for {duration:.2f} seconds")
            del self.state_data["calibration_start_time"]
    
    def _shutdown(self):
        """Shutdown the state machine - PLACEHOLDER."""
        logger.info("=== SHUTDOWN REQUESTED ===")
        logger.info("PLACEHOLDER: Implement shutdown logic here")
        # TODO: Implement shutdown logic
        # Example:
        # - Stop all active operations
        # - Disconnect from robot
        # - Save any pending data
        # - Close all connections
        # - Stop voice listener
        # - Clean up resources
        # Note: This is called when entering SHUTDOWN control mode
        self._enter_idle_control()
        if self.recording_mode == RecordingMode.RECORDING:
            self._stop_recording()
        self.stop_listening()
        if self.audio_stream:
            self.audio_stream.stop_stream()
            self.audio_stream.close()
        if self.audio:
            self.audio.terminate()
    
    def process_commands(self):
        """Process pending voice commands from the queue.
        
        This should be called regularly in the main loop.
        Commands are only processed if the system is activated (within 10-second window).
        """
        # Check if activation window has expired
        self._check_activation_status()
        
        try:
            while True:
                command = self.command_queue.get_nowait()
                
                # Check if this is an activation phrase
                if self._is_activation_phrase(command):
                    self._activate_listening()
                    continue  # Activation phrases don't change state, just enable listening
                
                # Only process commands if system is activated
                if not self._check_activation_status():
                    logger.debug(f"Ignoring command '{command}' - system not activated. Say an activation phrase first.")
                    continue
                
                # Interpret and process the command
                control_mode, recording_mode = self._interpret_command(command)
                
                # Process control mode changes
                if control_mode is not None:
                    self._transition_control_mode(control_mode)
                
                # Process recording mode changes (independent of control mode)
                if recording_mode is not None:
                    self._transition_recording_mode(recording_mode)
                
                # If no changes detected, log warning
                if control_mode is None and recording_mode is None:
                    logger.warning(f"Unrecognized command: '{command}'")
        
        except queue.Empty:
            pass  # No commands to process
    
    def _output_status(self):
        """Output current state, peak level, and recognized text every second."""
        current_time = time.time()
        
        # Check if it's time to output
        if current_time - self.last_output_time >= self.output_interval:
            # Calculate peak statistics
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
            
            # Get recognized text from this interval
            text_output = " ".join(self.recognized_texts) if self.recognized_texts else "(no speech detected)"
            
            # Format state information
            state_str = f"Control: {self.control_mode.value}, Recording: {self.recording_mode.value}"
            
            # Add activation status
            if self.is_activated:
                remaining_time = max(0, self.activation_expiry - time.time())
                activation_status = f"LISTENING ({remaining_time:.1f}s)"
            else:
                activation_status = "WAITING (say activation phrase)"
            
            # Output to console
            print(f"[{time.strftime('%H:%M:%S')}] {activation_status} | State: {state_str} | Peak: {max_peak:.3f} (avg: {avg_peak:.3f}) | Text: {text_output}")
            
            # Reset for next interval
            self.peak_levels = []
            self.recognized_texts = []
            self.last_output_time = current_time
    
    def run_state_action(self):
        """Execute the action for the current state.
        
        This should be called regularly in the main loop to execute
        state-specific behavior (e.g., teleop loop, recording loop).
        """
        # Handle control mode actions
        if self.control_mode == ControlMode.ARM_TELEOP:
            self._run_arm_teleop_loop()
        elif self.control_mode == ControlMode.BASE_TELEOP:
            self._run_base_teleop_loop()
        elif self.control_mode == ControlMode.CALIBRATING:
            self._run_calibration_loop()
        elif self.control_mode == ControlMode.SHUTDOWN:
            # Shutdown state - do nothing, will exit loop
            pass
        elif self.control_mode == ControlMode.IDLE:
            # Idle state - just wait
            time.sleep(0.1)
        
        # Recording mode runs independently
        if self.recording_mode == RecordingMode.RECORDING:
            self._run_recording_loop()
    
    def _run_arm_teleop_loop(self):
        """Run one iteration of arm teleop loop - PLACEHOLDER."""
        # TODO: Implement arm teleop loop iteration
        # Example:
        # - Get observation from robot
        # - Get action from leader arms
        # - Process action for arms only
        # - Send action to robot (arms only, base stays stationary)
        # - Visualize (optional)
        pass
    
    def _run_base_teleop_loop(self):
        """Run one iteration of base teleop loop - PLACEHOLDER."""
        # TODO: Implement base teleop loop iteration
        # Example:
        # - Get observation from robot
        # - Get base commands from input (keyboard/voice/etc)
        # - Process base velocities
        # - Send action to robot (base only, arms stay stationary)
        # - Visualize (optional)
        pass
    
    def _run_recording_loop(self):
        """Run one iteration of recording loop - PLACEHOLDER."""
        # TODO: Implement recording loop iteration
        # Example:
        # - Get observation from robot
        # - Get current action (from teleop or other source)
        # - Save observation and action to dataset
        # - Upload data to cloud (in batches or real-time)
        # - Send action to robot (if in teleop mode)
        pass
    
    def _run_calibration_loop(self):
        """Run one iteration of calibration loop - PLACEHOLDER."""
        # TODO: Implement calibration loop iteration
        # Example:
        # - Move robot through calibration sequence
        # - Record joint positions
        # - Check if calibration complete
        # - If complete, transition special_state to NONE
        pass
    
    def run(self, fps: int = 10):
        """Run the main state machine loop.
        
        Args:
            fps: Target frames per second for the main loop
        """
        logger.info("Starting voice-controlled state machine...")
        logger.info(f"Initial state - Control: {self.control_mode.value}, Recording: {self.recording_mode.value}")
        logger.info("System is waiting for activation phrase. Say 'hey grievous', 'grievous on', etc. to enable commands.")
        
        if self.model and self.recognizer:
            self.start_listening()
        else:
            logger.warning("Voice recognition not available. State machine will run but won't respond to voice commands.")
        
        try:
            loop_time = 1.0 / fps
            while self.control_mode != ControlMode.SHUTDOWN:
                loop_start = time.perf_counter()
                
                # Process voice commands
                self.process_commands()
                
                # Execute state-specific actions
                self.run_state_action()
                
                # Output status (state, peak, text) every second
                self._output_status()
                
                # Maintain loop timing
                elapsed = time.perf_counter() - loop_start
                sleep_time = max(0, loop_time - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)
        
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            self._transition_control_mode(ControlMode.SHUTDOWN)
        finally:
            if self.control_mode != ControlMode.SHUTDOWN:
                self._transition_control_mode(ControlMode.SHUTDOWN)
            logger.info("State machine stopped")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Voice-controlled state machine for Grievous robot")
    parser.add_argument(
        "--model-path",
        type=str,
        default=None,
        help="Path to Vosk model directory (default: vosk-models/vosk-model-small-en-us-0.15)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=10,
        help="Main loop frames per second (default: 10)",
    )
    
    args = parser.parse_args()
    
    # Create and run state machine
    state_machine = VoiceCommandStateMachine(model_path=args.model_path)
    state_machine.run(fps=args.fps)


if __name__ == "__main__":
    main()
