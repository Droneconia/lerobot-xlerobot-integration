# Remote Inference Latency Test Plan

## Objective
Measure round-trip latency for SmolVLA inference running on RunPod (4090/5090) communicating with local laptop acting as robot surrogate (no actual hardware). Test duration: 30 seconds.

---

## Architecture Overview

```
LAPTOP (Host - Mock Robot)              RUNPOD (Client - SmolVLA Inference)
─────────────────────────────           ───────────────────────────────────

┌─────────────────────────┐             ┌──────────────────────────┐
│ grievous_inference_host │             │ test_inference_latency   │
│   (MODIFIED)            │             │   (NEW SCRIPT)           │
└─────────────────────────┘             └──────────────────────────┘
         │                                         │
         │ [t0] Capture mock observation          │
         │      Tag: seq_num, timestamp_sent      │
         │                                         │
         ├────── ZMQ PUSH (port 5556) ────────────>│ [t1] Receive observation
         │       Observation + Metadata            │      Extract seq_num, ts
         │                                         │
         │                                         │ [t2] Preprocess
         │                                         │ [t3] SmolVLA.forward()
         │                                         │ [t4] Postprocess
         │                                         │
         │<────── ZMQ PUSH (port 5555) ────────────┤ [t5] Send action + metadata
         │        Action + Metadata                │      (seq_num, inference_time)
         │                                         │
[t6] Receive action                                │
     Extract seq_num                               │
     Calculate: round_trip = t6 - t0              │
     Log metrics                                   │
```

**Key Measurement**: Round-trip latency = Time from observation capture to action receipt (same machine clock, no sync issues)

---

## Timestamp Tagging Strategy

### Sequence Number Matching
- **Host**: Maintains `pending_observations = {seq_num: timestamp_sent}`
- **Action echoes back**: `seq_num` for matching
- **Round-trip calculation**: `time.perf_counter() - pending_observations[seq_num]`
- **No clock sync needed**: All timing done on host machine clock

### Message Format

**Observation (Host → Client)**
```json
{
  "seq_num": 123,
  "timestamp_sent": 1234567890.123,
  "left_arm_shoulder_pan.pos": 0.5,
  "...": "other state keys",
  "left_wrist": "base64_jpeg_data",
  "right_wrist": "base64_jpeg_data",
  "head": "base64_jpeg_data"
}
```

**Action (Client → Host)**
```json
{
  "seq_num": 123,
  "inference_time_ms": 145.2,
  "timestamp_received": 1234567890.234,
  "timestamp_sent": 1234567890.379,
  "left_arm_shoulder_pan.pos": 0.6,
  "...": "other action keys"
}
```

---

## Implementation Components

### 1. Modified `grievous_inference_host.py`

**File**: `src/lerobot/robots/grievous/grievous_inference_host.py`

**Changes**:

#### A. Add Dummy Robot Mode
```python
class DummyGrievous:
    """Mock Grievous robot for latency testing without hardware."""
    
    def __init__(self, config: GrievousConfig):
        self.config = config
        # Create dummy cameras that return synthetic images
        self.cameras = {
            "left_wrist": DummyCamera(width=640, height=480),
            "right_wrist": DummyCamera(width=640, height=480),
            "head": DummyCamera(width=640, height=480),
        }
        # Dummy state (random values)
        self.state = self._generate_dummy_state()
    
    def connect(self, calibrate=False):
        logging.info("DummyGrievous: Mock connection (no hardware)")
    
    def disconnect(self):
        logging.info("DummyGrievous: Mock disconnection")
    
    def get_observation(self):
        """Return synthetic observation with images."""
        obs = dict(self.state)
        for cam_name, cam in self.cameras.items():
            obs[cam_name] = cam.get_frame()  # Generate synthetic image
        obs["observation.state"] = np.array(list(self.state.values()), dtype=np.float32)
        return obs
    
    def send_action(self, action):
        """Mock action execution (no-op)."""
        pass
    
    def _generate_dummy_state(self):
        """Generate realistic joint positions."""
        return {
            "left_arm_shoulder_pan.pos": 0.0,
            "left_arm_shoulder_lift.pos": -0.5,
            # ... (all 15 state keys with realistic values)
        }

class DummyCamera:
    """Generates synthetic camera images."""
    
    def __init__(self, width=640, height=480):
        self.width = width
        self.height = height
        self.frame_count = 0
    
    def get_frame(self):
        """Generate synthetic image (colored noise + frame counter)."""
        img = np.random.randint(0, 255, (self.height, self.width, 3), dtype=np.uint8)
        # Add frame counter text for visual verification
        cv2.putText(img, f"Frame: {self.frame_count}", (10, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        self.frame_count += 1
        return img
```

#### B. Add Latency Tracking to Control Loop
```python
# In main() function, before control loop:
observation_counter = 0
pending_observations = {}  # {seq_num: timestamp_sent}
latency_samples = []  # Store all latency measurements

# In control loop (after getting observation):
seq_num = observation_counter
observation_counter += 1
timestamp_sent = time.perf_counter()
pending_observations[seq_num] = timestamp_sent

# Add metadata to observation
last_observation['seq_num'] = seq_num
last_observation['timestamp_sent'] = timestamp_sent

# After receiving action:
timestamp_received = time.perf_counter()
seq_num = data.get('seq_num', -1)

if seq_num in pending_observations:
    round_trip_ms = (timestamp_received - pending_observations[seq_num]) * 1000
    inference_time_ms = data.get('inference_time_ms', 0.0)
    network_time_ms = round_trip_ms - inference_time_ms
    
    latency_samples.append({
        'seq_num': seq_num,
        'round_trip_ms': round_trip_ms,
        'inference_ms': inference_time_ms,
        'network_ms': network_time_ms
    })
    
    logger.info(f"[Seq {seq_num:04d}] Round-trip: {round_trip_ms:.1f}ms | "
                f"Inference: {inference_time_ms:.1f}ms | "
                f"Network: {network_time_ms:.1f}ms")
    
    # Clean up old entries
    del pending_observations[seq_num]

# At end of test, print summary statistics:
if latency_samples:
    print_latency_summary(latency_samples)
```

#### C. Add Statistics Summary Function
```python
def print_latency_summary(samples: list[dict]) -> None:
    """Print statistical summary of latency measurements."""
    import numpy as np
    
    round_trips = [s['round_trip_ms'] for s in samples]
    inferences = [s['inference_ms'] for s in samples]
    networks = [s['network_ms'] for s in samples]
    
    print("\n" + "="*60)
    print("LATENCY TEST SUMMARY")
    print("="*60)
    print(f"Total Samples: {len(samples)}")
    print(f"Duration: {samples[-1]['seq_num'] - samples[0]['seq_num']} iterations")
    print()
    
    print("ROUND-TRIP LATENCY (Observation Sent → Action Received):")
    print(f"  Mean:   {np.mean(round_trips):.1f} ms")
    print(f"  Median: {np.median(round_trips):.1f} ms")
    print(f"  Std:    {np.std(round_trips):.1f} ms")
    print(f"  Min:    {np.min(round_trips):.1f} ms")
    print(f"  Max:    {np.max(round_trips):.1f} ms")
    print(f"  P95:    {np.percentile(round_trips, 95):.1f} ms")
    print(f"  P99:    {np.percentile(round_trips, 99):.1f} ms")
    print()
    
    print("INFERENCE TIME (SmolVLA Forward Pass):")
    print(f"  Mean:   {np.mean(inferences):.1f} ms")
    print(f"  Median: {np.median(inferences):.1f} ms")
    print(f"  Std:    {np.std(inferences):.1f} ms")
    print(f"  Min:    {np.min(inferences):.1f} ms")
    print(f"  Max:    {np.max(inferences):.1f} ms")
    print()
    
    print("NETWORK LATENCY (Round-trip - Inference):")
    print(f"  Mean:   {np.mean(networks):.1f} ms")
    print(f"  Median: {np.median(networks):.1f} ms")
    print(f"  Std:    {np.std(networks):.1f} ms")
    print()
    
    # Dropped frames detection
    seq_nums = [s['seq_num'] for s in samples]
    expected_count = seq_nums[-1] - seq_nums[0] + 1
    actual_count = len(seq_nums)
    dropped = expected_count - actual_count
    
    if dropped > 0:
        print(f"⚠️  DROPPED FRAMES: {dropped} / {expected_count} ({dropped/expected_count*100:.1f}%)")
    else:
        print("✓ NO DROPPED FRAMES")
    
    print("="*60 + "\n")
```

#### D. Add CLI Arguments
```python
parser.add_argument("--dummy-robot", action="store_true",
                    help="Use dummy robot (no hardware) for latency testing")
parser.add_argument("--duration", type=int, default=30,
                    help="Test duration in seconds (default: 30)")

# In main():
if args.dummy_robot:
    logger.warning("🤖 Using DUMMY ROBOT (no hardware)")
    robot_config = GrievousConfig(id="dummy_grievous")
    robot = DummyGrievous(robot_config)
else:
    robot_config = GrievousConfig(id="grievous_robot")
    robot = Grievous(robot_config)
```

---

### 2. New Script: `test_inference_latency.py`

**File**: `test_inference_latency.py` (root directory)

**Purpose**: Lightweight script that connects to laptop host, runs SmolVLA inference, measures latency.

**Structure**:
```python
#!/usr/bin/env python
"""
Latency test for remote SmolVLA inference.

Connects to grievous_inference_host running on laptop,
receives observations, runs inference, sends actions with timing metadata.
"""

import argparse
import json
import logging
import time
from pathlib import Path

import torch
import zmq

from lerobot.cameras.configs import CameraConfig
from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
from lerobot.configs.policies import PreTrainedConfig
from lerobot.policies.factory import make_policy, make_pre_post_processors
from lerobot.processor.rename_processor import rename_stats
from lerobot.utils.utils import get_safe_torch_device

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def dummy_dataset_meta():
    """Create minimal dataset metadata for policy initialization."""
    from types import SimpleNamespace
    
    # SmolVLA expects specific camera and state keys
    stats = {
        # Camera stats (dummy values)
        "observation.images.camera1": {
            "mean": [0.485, 0.456, 0.406],
            "std": [0.229, 0.224, 0.225]
        },
        "observation.images.camera2": {
            "mean": [0.485, 0.456, 0.406],
            "std": [0.229, 0.224, 0.225]
        },
        "observation.images.camera3": {
            "mean": [0.485, 0.456, 0.406],
            "std": [0.229, 0.224, 0.225]
        },
        # State stats (15 values: 2 arms × 6 joints + 2 head + 3 base)
        "observation.state": {
            "mean": [0.0] * 15,
            "std": [1.0] * 15
        },
        # Action stats (15 values)
        "action": {
            "mean": [0.0] * 15,
            "std": [1.0] * 15
        }
    }
    
    # Create minimal meta with only what policy needs
    meta = SimpleNamespace(
        stats=stats,
        robot_type="grievous_client",
        fps=30
    )
    
    return meta


def main():
    parser = argparse.ArgumentParser(description="Remote inference latency test")
    parser.add_argument("--policy-path", type=str, 
                        default="Grievous-Robot/smolvla_finetuned_5k",
                        help="HuggingFace policy path")
    parser.add_argument("--host-ip", type=str, required=True,
                        help="Laptop host IP address")
    parser.add_argument("--port-cmd", type=int, default=5555,
                        help="Command port (send actions)")
    parser.add_argument("--port-obs", type=int, default=5556,
                        help="Observation port (receive observations)")
    parser.add_argument("--duration", type=int, default=30,
                        help="Test duration in seconds")
    parser.add_argument("--device", type=str, default="cuda",
                        help="Device for inference (cuda/cpu)")
    args = parser.parse_args()
    
    logger.info("="*60)
    logger.info("REMOTE INFERENCE LATENCY TEST")
    logger.info("="*60)
    logger.info(f"Policy: {args.policy_path}")
    logger.info(f"Host: {args.host_ip}:{args.port_obs}/{args.port_cmd}")
    logger.info(f"Duration: {args.duration}s")
    logger.info(f"Device: {args.device}")
    logger.info("="*60)
    
    # 1. Initialize ZMQ sockets
    logger.info("Initializing ZMQ sockets...")
    context = zmq.Context()
    
    # Observation socket (PULL): receive from host
    obs_socket = context.socket(zmq.PULL)
    obs_socket.connect(f"tcp://{args.host_ip}:{args.port_obs}")
    obs_socket.setsockopt(zmq.CONFLATE, 1)
    logger.info(f"Observation socket connected to tcp://{args.host_ip}:{args.port_obs}")
    
    # Command socket (PUSH): send to host
    cmd_socket = context.socket(zmq.PUSH)
    cmd_socket.connect(f"tcp://{args.host_ip}:{args.port_cmd}")
    cmd_socket.setsockopt(zmq.CONFLATE, 1)
    logger.info(f"Command socket connected to tcp://{args.host_ip}:{args.port_cmd}")
    
    # 2. Load policy
    logger.info(f"Loading policy from {args.policy_path}...")
    policy_cfg = PreTrainedConfig.from_pretrained(args.policy_path)
    policy_cfg.device = args.device
    
    ds_meta = dummy_dataset_meta()
    policy = make_policy(policy_cfg, ds_meta=ds_meta)
    policy.eval()
    logger.info("Policy loaded successfully")
    
    # 3. Load preprocessor/postprocessor
    logger.info("Loading preprocessor/postprocessor...")
    rename_map = {
        "observation.images.left_wrist": "observation.images.camera1",
        "observation.images.right_wrist": "observation.images.camera2",
        "observation.images.head": "observation.images.camera3"
    }
    
    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg=policy_cfg,
        pretrained_path=args.policy_path,
        dataset_stats=rename_stats(ds_meta.stats, rename_map),
        preprocessor_overrides={
            "device_processor": {"device": args.device},
            "rename_observations_processor": {"rename_map": rename_map}
        }
    )
    preprocessor.reset()
    postprocessor.reset()
    logger.info("Processors loaded successfully")
    
    # 4. Run inference loop
    logger.info("Starting inference loop...")
    device = get_safe_torch_device(args.device)
    start_time = time.time()
    iteration = 0
    
    try:
        while time.time() - start_time < args.duration:
            loop_start = time.perf_counter()
            
            # A. Receive observation
            obs_string = obs_socket.recv_string()
            timestamp_received = time.perf_counter()
            
            observation = json.loads(obs_string)
            seq_num = observation.get('seq_num', -1)
            
            # B. Preprocess observation
            # Convert base64 images back to numpy arrays
            import base64
            import cv2
            import numpy as np
            
            for cam_key in ['left_wrist', 'right_wrist', 'head']:
                if cam_key in observation and isinstance(observation[cam_key], str):
                    jpg_data = base64.b64decode(observation[cam_key])
                    np_arr = np.frombuffer(jpg_data, dtype=np.uint8)
                    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                    observation[cam_key] = frame
            
            # Build observation dict for policy
            obs_dict = {}
            for key, value in observation.items():
                if key not in ['seq_num', 'timestamp_sent']:
                    obs_dict[key] = value
            
            # C. Run inference
            inference_start = time.perf_counter()
            
            with torch.no_grad():
                # Preprocess
                processed_obs = preprocessor(obs_dict)
                
                # Move to device
                for key, val in processed_obs.items():
                    if torch.is_tensor(val):
                        processed_obs[key] = val.to(device)
                
                # Forward pass
                action_tensor = policy.select_action(processed_obs)
                
                # Postprocess
                action_processed = postprocessor({"action": action_tensor})
            
            inference_end = time.perf_counter()
            inference_time_ms = (inference_end - inference_start) * 1000
            
            # D. Convert action tensor to dict
            action_dict = {}
            action_values = action_tensor.cpu().numpy()
            
            # Map action values to keys (15 values: arms + head + base)
            action_keys = [
                "left_arm_shoulder_pan.pos", "left_arm_shoulder_lift.pos",
                "left_arm_elbow_flex.pos", "left_arm_wrist_flex.pos",
                "left_arm_wrist_roll.pos", "left_arm_gripper.pos",
                "right_arm_shoulder_pan.pos", "right_arm_shoulder_lift.pos",
                "right_arm_elbow_flex.pos", "right_arm_wrist_flex.pos",
                "right_arm_wrist_roll.pos", "right_arm_gripper.pos",
                "head_motor_1.pos", "head_motor_2.pos",
                "x.vel", "y.vel", "theta.vel"
            ]
            
            for i, key in enumerate(action_keys[:len(action_values)]):
                action_dict[key] = float(action_values[i])
            
            # E. Add timing metadata
            timestamp_sent = time.perf_counter()
            action_dict['seq_num'] = seq_num
            action_dict['inference_time_ms'] = inference_time_ms
            action_dict['timestamp_received'] = timestamp_received
            action_dict['timestamp_sent'] = timestamp_sent
            
            # F. Send action
            cmd_socket.send_string(json.dumps(action_dict), flags=zmq.NOBLOCK)
            
            iteration += 1
            
            # Log every 10 iterations
            if iteration % 10 == 0:
                logger.info(f"[Iter {iteration:04d}] Inference: {inference_time_ms:.1f}ms | "
                           f"Seq: {seq_num}")
    
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    
    finally:
        logger.info(f"Test completed: {iteration} iterations in {time.time() - start_time:.1f}s")
        obs_socket.close()
        cmd_socket.close()
        context.term()


if __name__ == "__main__":
    main()
```

---

## Running the Test

### Step 1: Start Host on Laptop

```bash
# Terminal 1 (Laptop)
cd /home/falcon/Code/lerobot-xlerobot-integration

python src/lerobot/robots/grievous/grievous_inference_host.py \
    --dummy-robot \
    --remote-ip <RUNPOD_IP> \
    --port-cmd 5555 \
    --port-obs 5556 \
    --duration 60
```

**Expected Output**:
```
2025-12-16 10:00:00 - INFO - 🤖 Using DUMMY ROBOT (no hardware)
2025-12-16 10:00:00 - INFO - Connecting to remote client at <RUNPOD_IP>:5555/5556...
2025-12-16 10:00:00 - INFO - Command socket (PULL) connected to tcp://<RUNPOD_IP>:5555
2025-12-16 10:00:00 - INFO - Observation socket (PUSH) connected to tcp://<RUNPOD_IP>:5556
2025-12-16 10:00:00 - INFO - GrievousInferenceHost initialized
2025-12-16 10:00:00 - INFO - Waiting for commands from remote policy...
```

### Step 2: Start Client on RunPod

```bash
# Terminal 2 (RunPod)
cd /workspace/lerobot-xlerobot-integration

python test_inference_latency.py \
    --policy-path Grievous-Robot/smolvla_finetuned_5k \
    --host-ip <LAPTOP_PUBLIC_IP> \
    --port-cmd 5555 \
    --port-obs 5556 \
    --duration 30 \
    --device cuda
```

**Expected Output**:
```
============================================================
REMOTE INFERENCE LATENCY TEST
============================================================
Policy: Grievous-Robot/smolvla_finetuned_5k
Host: <LAPTOP_IP>:5556/5555
Duration: 30s
Device: cuda
============================================================
INFO - Initializing ZMQ sockets...
INFO - Observation socket connected to tcp://<LAPTOP_IP>:5556
INFO - Command socket connected to tcp://<LAPTOP_IP>:5555
INFO - Loading policy from Grievous-Robot/smolvla_finetuned_5k...
INFO - Policy loaded successfully
INFO - Starting inference loop...
[Iter 0010] Inference: 145.2ms | Seq: 10
[Iter 0020] Inference: 143.8ms | Seq: 20
...
```

### Step 3: View Results on Laptop

After 30 seconds, the host will print summary statistics:

```
============================================================
LATENCY TEST SUMMARY
============================================================
Total Samples: 185
Duration: 185 iterations

ROUND-TRIP LATENCY (Observation Sent → Action Received):
  Mean:   187.3 ms
  Median: 185.2 ms
  Std:    12.4 ms
  Min:    165.7 ms
  Max:    215.8 ms
  P95:    205.1 ms
  P99:    212.3 ms

INFERENCE TIME (SmolVLA Forward Pass):
  Mean:   145.6 ms
  Median: 144.8 ms
  Std:    5.2 ms
  Min:    138.2 ms
  Max:    162.3 ms

NETWORK LATENCY (Round-trip - Inference):
  Mean:   41.7 ms
  Median: 40.4 ms
  Std:    8.7 ms

✓ NO DROPPED FRAMES
============================================================
```

---

## Expected Latency Breakdown

### 4090 GPU (Estimated)
- **Inference Time**: 140-160 ms (SmolVLA forward pass)
- **Network Latency**: 30-50 ms (laptop ↔ RunPod round-trip)
- **Processing Overhead**: 10-20 ms (JSON encode/decode, base64)
- **Total Round-Trip**: **180-230 ms**

### 5090 GPU (Estimated)
- **Inference Time**: 100-120 ms (faster GPU)
- **Network Latency**: 30-50 ms (same network)
- **Processing Overhead**: 10-20 ms (same)
- **Total Round-Trip**: **140-190 ms**

### Target for Real-Time Control
- **50Hz control** requires < 20ms latency ❌ (not achievable with cloud inference)
- **10Hz control** requires < 100ms latency ❌ (marginal with 5090)
- **5Hz control** requires < 200ms latency ✓ (achievable with both GPUs)

---

## Success Criteria

- [ ] Host successfully creates dummy robot and sends synthetic observations
- [ ] Client successfully loads `Grievous-Robot/smolvla_finetuned_5k` policy
- [ ] Test runs for 30 seconds without errors
- [ ] All sequence numbers matched (no dropped frames)
- [ ] Round-trip latency measured and logged
- [ ] Inference time isolated from network latency
- [ ] Summary statistics printed at end

---

## Troubleshooting

### Issue: "Cannot connect to host"
- **Cause**: Firewall blocking ports or incorrect IP
- **Fix**: 
  - Check RunPod can reach laptop: `ping <LAPTOP_IP>`
  - Open ports on laptop: `sudo ufw allow 5555:5556/tcp`
  - Verify laptop public IP: `curl ifconfig.me`

### Issue: "Policy fails to load"
- **Cause**: Model not found or auth issue
- **Fix**:
  - Verify checkpoint exists: https://huggingface.co/Grievous-Robot/smolvla_finetuned_5k
  - Login to HuggingFace: `huggingface-cli login`
  - Check token has read permissions

### Issue: "Watchdog timeout triggered"
- **Cause**: Inference too slow (> 500ms)
- **Fix**: Increase timeout in host script: `--watchdog-timeout 2000`

### Issue: "Dropped frames detected"
- **Cause**: Inference slower than observation rate
- **Fix**: Normal for this test - latency stats still valid from completed iterations

---

## Implementation Checklist

### Phase 1: Host Modifications (60 min)
- [ ] Add `DummyGrievous` class with synthetic image generation
- [ ] Add `DummyCamera` class
- [ ] Add sequence number tracking (`observation_counter`, `pending_observations`)
- [ ] Add metadata to observation JSON (`seq_num`, `timestamp_sent`)
- [ ] Parse metadata from action JSON
- [ ] Calculate and log latency per iteration
- [ ] Store latency samples in list
- [ ] Implement `print_latency_summary()` function
- [ ] Add CLI arguments: `--dummy-robot`, `--duration`

### Phase 2: Client Script (90 min)
- [ ] Create `test_inference_latency.py` script
- [ ] Initialize ZMQ sockets (PULL for obs, PUSH for actions)
- [ ] Implement `dummy_dataset_meta()` function
- [ ] Load policy from HuggingFace
- [ ] Load preprocessor/postprocessor with rename_map
- [ ] Implement inference loop:
  - [ ] Receive observation, extract metadata
  - [ ] Decode base64 images
  - [ ] Preprocess observation
  - [ ] Run policy.select_action()
  - [ ] Postprocess action
  - [ ] Add timing metadata to action
  - [ ] Send action to host
- [ ] Add periodic logging (every 10 iterations)
- [ ] Add CLI arguments

### Phase 3: Testing (30 min)
- [ ] Test host in isolation (dummy robot mode)
- [ ] Test client can load policy
- [ ] Run full 30-second test
- [ ] Verify latency summary prints correctly
- [ ] Document results

---

## Files to Create/Modify

### Modified Files
1. `src/lerobot/robots/grievous/grievous_inference_host.py`
   - Add dummy robot classes
   - Add latency tracking
   - Add statistics summary

### New Files
1. `test_inference_latency.py` (root directory)
   - Standalone latency test client

2. `context_notes/remote_inference_latency_test_plan.md` (this file)
   - Complete test plan and documentation
