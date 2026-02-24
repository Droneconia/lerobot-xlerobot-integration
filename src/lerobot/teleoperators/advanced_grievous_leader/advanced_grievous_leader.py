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
import logging
import queue
import threading
import time
from enum import Enum
from functools import cached_property
from pathlib import Path
from typing import Optional

from lerobot.teleoperators.so_leader import SOLeaderTeleopConfig
from lerobot.utils.decorators import check_if_already_connected, check_if_not_connected
from lerobot.utils.utils import log_say

from ..so_leader import SOLeader
from ..teleoperator import Teleoperator
from .config_advanced_grievous_leader import AdvancedGrievousLeaderConfig

logger = logging.getLogger(__name__)

# Default Vosk model (repo root / voice-model / vosk-model-small-en-us-0.15)
_DEFAULT_VOICE_MODEL_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "voice-model" / "vosk-model-small-en-us-0.15"
)

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False

try:
    from vosk import Model, KaldiRecognizer
    VOSK_AVAILABLE = True
except ImportError:
    VOSK_AVAILABLE = False


class TeleopMode(Enum):
    """Which part of the robot is being teleoperated."""
    ARM_TELEOP = "arm_teleop"   # arms from leader, base zero
    BASE_TELEOP = "base_teleop"  # arms held (cached), base from left leader arm mapping


# Voice phrases that switch mode (lowercase, one word or short phrase)
VOICE_TO_MODE = {
    "arm": TeleopMode.ARM_TELEOP,
    "arms": TeleopMode.ARM_TELEOP,
    "base": TeleopMode.BASE_TELEOP,
    "bass": TeleopMode.BASE_TELEOP,
    "move": TeleopMode.BASE_TELEOP,
}


def _apply_deadzone(value: float, deadzone: float) -> float:
    if abs(value) < deadzone:
        return 0.0
    if value > 0:
        return (value - deadzone) / (100.0 - deadzone)
    return (value + deadzone) / (100.0 - deadzone)


class AdvancedGrievousLeader(Teleoperator):
    """
    [Bimanual SO Leader Arms](https://github.com/TheRobotStudio/SO-ARM100) designed by TheRobotStudio
    (Advanced Grievous Leader variant).
    Voice commands switch between arm teleop and base teleop (left leader arm → base velocities).
    """

    config_class = AdvancedGrievousLeaderConfig
    name = "advanced_grievous_leader"

    def __init__(self, config: AdvancedGrievousLeaderConfig):
        super().__init__(config)
        self.config = config

        left_arm_config = SOLeaderTeleopConfig(
            id=f"{config.id}_left" if config.id else None,
            calibration_dir=config.calibration_dir,
            port=config.left_arm_config.port,
        )

        right_arm_config = SOLeaderTeleopConfig(
            id=f"{config.id}_right" if config.id else None,
            calibration_dir=config.calibration_dir,
            port=config.right_arm_config.port,
        )

        self.left_arm = SOLeader(left_arm_config)
        self.right_arm = SOLeader(right_arm_config)

        # State: arm vs base teleop; voice updates this
        self._mode = TeleopMode.ARM_TELEOP
        self._cached_arm_action: Optional[dict[str, float]] = None

        # Optional voice: queue filled by listener thread, drained in get_action()
        self._voice_queue: queue.Queue[str] = queue.Queue()
        self._voice_listening = False
        self._voice_thread: Optional[threading.Thread] = None
        self._voice_audio_stream = None
        self._voice_recognizer = None
        self._voice_pyaudio = None

    @property
    def teleop_mode(self) -> TeleopMode:
        return self._mode

    def _start_voice_listener(self) -> None:
        if not VOSK_AVAILABLE or not PYAUDIO_AVAILABLE:
            return
        raw_path = self.config.voice_model_path or str(_DEFAULT_VOICE_MODEL_PATH)
        path = Path(raw_path)
        if not path.exists():
            logger.warning("Voice model path %s not found, voice mode switching disabled.", path)
            return
        try:
            model = Model(str(path))
            self._voice_pyaudio = pyaudio.PyAudio()
            stream = self._voice_pyaudio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=4000,
            )
            self._voice_audio_stream = stream
            self._voice_recognizer = KaldiRecognizer(model, 16000)
            self._voice_listening = True
            self._voice_thread = threading.Thread(target=self._voice_loop, daemon=True)
            self._voice_thread.start()
            logger.info("Voice listener started; say 'arm'/'arms' or 'base'/'move' to switch mode.")
        except Exception as e:
            logger.warning("Could not start voice listener: %s", e)

    def _voice_loop(self) -> None:
        while self._voice_listening and self._voice_audio_stream and self._voice_recognizer:
            try:
                data = self._voice_audio_stream.read(4000, exception_on_overflow=False)
                if self._voice_recognizer.AcceptWaveform(data):
                    result = json.loads(self._voice_recognizer.Result())
                    text = (result.get("text") or "").strip().lower()
                    if text:
                        self._voice_queue.put(text)
            except Exception as e:
                if self._voice_listening:
                    logger.debug("Voice loop error: %s", e)
                time.sleep(0.05)

    def _stop_voice_listener(self) -> None:
        self._voice_listening = False
        if self._voice_thread and self._voice_thread.is_alive():
            self._voice_thread.join(timeout=2.0)
        if self._voice_audio_stream:
            try:
                self._voice_audio_stream.stop_stream()
                self._voice_audio_stream.close()
            except Exception as e:
                logger.debug("Error closing voice audio stream: %s", e)
            self._voice_audio_stream = None
        if self._voice_pyaudio:
            try:
                self._voice_pyaudio.terminate()
            except Exception as e:
                logger.debug("Error terminating PyAudio: %s", e)
            self._voice_pyaudio = None
        self._voice_recognizer = None

    def _process_voice_queue(self) -> None:
        while True:
            try:
                text = self._voice_queue.get_nowait()
            except queue.Empty:
                break
            text = text.strip().lower()
            for phrase, mode in VOICE_TO_MODE.items():
                if phrase in text or text == phrase:
                    old_mode = self._mode
                    self._mode = mode
                    if old_mode != mode:
                        logger.info("Teleop mode: %s", mode.value)
                        log_say("arms" if mode == TeleopMode.ARM_TELEOP else "base", blocking=False)
                    break

    @cached_property
    def action_features(self) -> dict[str, type]:
        left_arm_features = self.left_arm.action_features
        right_arm_features = self.right_arm.action_features
        base_ft = {"x.vel": float, "y.vel": float, "theta.vel": float}
        return {
            **{f"left_{k}": v for k, v in left_arm_features.items()},
            **{f"right_{k}": v for k, v in right_arm_features.items()},
            **base_ft,
        }

    @cached_property
    def feedback_features(self) -> dict[str, type]:
        return {}

    @property
    def is_connected(self) -> bool:
        return self.left_arm.is_connected and self.right_arm.is_connected

    @check_if_already_connected
    def connect(self, calibrate: bool = True) -> None:
        self.left_arm.connect(calibrate)
        self.right_arm.connect(calibrate)
        self._start_voice_listener()

    @property
    def is_calibrated(self) -> bool:
        return self.left_arm.is_calibrated and self.right_arm.is_calibrated

    def calibrate(self) -> None:
        self.left_arm.calibrate()
        self.right_arm.calibrate()

    def configure(self) -> None:
        self.left_arm.configure()
        self.right_arm.configure()

    def setup_motors(self) -> None:
        self.left_arm.setup_motors()
        self.right_arm.setup_motors()

    @check_if_not_connected
    def get_action(self) -> dict[str, float]:
        self._process_voice_queue()

        left_action = self.left_arm.get_action()
        right_action = self.right_arm.get_action()
        prefixed_left = {f"left_{k}": v for k, v in left_action.items()}
        prefixed_right = {f"right_{k}": v for k, v in right_action.items()}
        full_arm = {**prefixed_left, **prefixed_right}

        if self._mode == TeleopMode.ARM_TELEOP:
            self._cached_arm_action = full_arm.copy()
            return {
                **full_arm,
                "x.vel": 0.0,
                "y.vel": 0.0,
                "theta.vel": 0.0,
            }

        # BASE_TELEOP: hold arms (use cache or current if no cache), drive base from left leader arm
        if self._cached_arm_action is None:
            self._cached_arm_action = full_arm.copy()
        arm_part = self._cached_arm_action

        deadzone = 20.0
        base_scale = 0.4
        theta_scale = 60.0
        # Scaled down to test
        x_vel = -_apply_deadzone(prefixed_left.get("left_wrist_flex.pos", 0.0), deadzone) * base_scale * 0.5
        y_vel = -_apply_deadzone(prefixed_left.get("left_shoulder_pan.pos", 0.0), deadzone) * base_scale * 0.5
        theta_vel = -_apply_deadzone(prefixed_left.get("left_wrist_roll.pos", 0.0), deadzone) * theta_scale * 0.5

        return {
            **arm_part,
            "x.vel": x_vel,
            "y.vel": y_vel,
            "theta.vel": theta_vel,
        }

    def send_feedback(self, feedback: dict[str, float]) -> None:
        raise NotImplementedError

    @check_if_not_connected
    def disconnect(self) -> None:
        self._stop_voice_listener()
        self.left_arm.disconnect()
        self.right_arm.disconnect()
