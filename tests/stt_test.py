#!/usr/bin/env python
"""Simple test script for speech-to-text using Vosk.

This script captures audio from a USB microphone, converts it to text using Vosk,
and outputs the audio peak level and recognized text every second.
"""

import json
import logging
import time
from pathlib import Path

try:
    import pyaudio
    import numpy as np
    PYAudio_AVAILABLE = True
except ImportError:
    PYAudio_AVAILABLE = False
    print("ERROR: pyaudio and numpy are required. Install with: pip install pyaudio numpy")

try:
    from vosk import Model, KaldiRecognizer
    VOSK_AVAILABLE = True
except ImportError:
    VOSK_AVAILABLE = False
    print("ERROR: vosk is required. Install with: pip install vosk")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def find_microphone_device(pyaudio_instance, device_name_keyword="usb"):
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


def calculate_peak_level(audio_data, sample_width=2):
    """Calculate peak audio level from raw audio data.
    
    Args:
        audio_data: Raw audio bytes
        sample_width: Sample width in bytes (2 for 16-bit)
        
    Returns:
        Peak level as a float (0.0 to 1.0)
    """
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


def main():
    """Main function to run the speech-to-text test."""
    if not PYAudio_AVAILABLE:
        logger.error("pyaudio not available. Exiting.")
        return
    
    if not VOSK_AVAILABLE:
        logger.error("vosk not available. Exiting.")
        return
    
    # Configuration
    sample_rate = 16000
    chunk_size = 4000
    output_interval = 1.0  # Output every second
    
    # Find Vosk model
    model_path = Path(__file__).parent / "vosk-models" / "vosk-model-small-en-us-0.15"
    
    if not model_path.exists():
        logger.error(f"Vosk model not found at {model_path}")
        logger.error("Please ensure the Vosk model is installed in the vosk-models directory.")
        return
    
    logger.info(f"Loading Vosk model from {model_path}")
    try:
        model = Model(str(model_path))
        recognizer = KaldiRecognizer(model, sample_rate)
        recognizer.SetWords(True)
        logger.info("Vosk model loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load Vosk model: {e}")
        return
    
    # Initialize PyAudio
    try:
        audio = pyaudio.PyAudio()
        
        # Find USB microphone
        device_index = find_microphone_device(audio)
        
        # Open audio stream
        stream = audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=sample_rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=chunk_size,
        )
        logger.info("Audio stream opened successfully")
    except Exception as e:
        logger.error(f"Failed to initialize audio: {e}")
        return
    
    logger.info("Starting speech-to-text test. Press Ctrl+C to stop.")
    logger.info("=" * 60)
    
    try:
        last_output_time = time.time()
        accumulated_text = []
        peak_levels = []
        
        while True:
            # Read audio data
            try:
                data = stream.read(chunk_size, exception_on_overflow=False)
            except Exception as e:
                logger.error(f"Error reading audio: {e}")
                break
            
            # Calculate peak level
            peak = calculate_peak_level(data)
            peak_levels.append(peak)
            
            # Process with Vosk
            if recognizer.AcceptWaveform(data):
                result = json.loads(recognizer.Result())
                text = result.get("text", "").strip()
                if text:
                    accumulated_text.append(text)
            else:
                # Partial result
                partial = json.loads(recognizer.PartialResult())
                partial_text = partial.get("partial", "").strip()
                if partial_text:
                    # Store partial text (will be replaced by final result)
                    pass
            
            # Output every second
            current_time = time.time()
            if current_time - last_output_time >= output_interval:
                # Calculate average peak over the interval
                avg_peak = np.mean(peak_levels) if peak_levels else 0.0
                max_peak = np.max(peak_levels) if peak_levels else 0.0
                
                # Get accumulated text
                text_output = " ".join(accumulated_text) if accumulated_text else ""
                
                # Output results
                print(f"[{time.strftime('%H:%M:%S')}] Peak: {max_peak:.3f} (avg: {avg_peak:.3f}) | Text: {text_output if text_output else '(no speech detected)'}")
                
                # Reset for next interval
                accumulated_text = []
                peak_levels = []
                last_output_time = current_time
    
    except KeyboardInterrupt:
        logger.info("\nStopping...")
    finally:
        # Cleanup
        stream.stop_stream()
        stream.close()
        audio.terminate()
        logger.info("Audio stream closed")


if __name__ == "__main__":
    main()
