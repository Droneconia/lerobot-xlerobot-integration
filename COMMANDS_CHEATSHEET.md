# Grievous Robot Commands Cheatsheet

Quick reference for running Grievous in different modes.

---

## 1. Recording Mode (with Teleoperation)

### On RPi5:
```bash
cd ~/Code/lerobot-xlerobot-integration
conda activate grievous
python -m lerobot.robots.grievous.grievous_host
```

### On Laptop:
```bash
cd /path/to/lerobot-xlerobot-integration
conda activate grievous

# Set your parameters:
export TASK="Pick and place cube"
export DATASET_NAME="pick-place"
export VERSION=1
export EPISODES=10

lerobot-record \
    --robot.type=grievous_client \
    --robot.remote_ip=192.168.50.148 \
    --robot.cameras='{
        left_wrist: {type: opencv, index_or_path: /dev/video6, width: 640, height: 480, fps: 30},
        right_wrist: {type: opencv, index_or_path: /dev/video8, width: 640, height: 480, fps: 30},
        head: {type: intelrealsense, serial_number_or_name: 032622074046, width: 640, height: 480, fps: 30}
    }' \
    --teleop.type=grievous_leader \
    --teleop.left_arm_port=/dev/ttyACM3 \
    --teleop.right_arm_port=/dev/ttyACM2 \
    --teleop.remote_ip=192.168.50.148 \
    --teleop.port_zmq_cmd=5555 \
    --teleop.id=grievous_leader \
    --dataset.repo_id="Grievous-Robot/${DATASET_NAME}-v${VERSION}" \
    --dataset.num_episodes=${EPISODES} \
    --dataset.single_task="${TASK}" \
    --dataset.episode_time_s=120 \
    --dataset.reset_time_s=60 \
    --dataset.push_to_hub=true \
    --dataset.num_image_writer_threads_per_camera=4 \
    --display_data=true
```

---

## 2. Inference Mode - Normal Connection (Not Behind NAT)

**Use when:** RPi5 has public IP or port forwarding works

### On RPi5 (binds and waits):
```bash
cd ~/Code/lerobot-xlerobot-integration
conda activate grievous

# For dry-run (safe testing - logs actions, doesn't execute):
python -m lerobot.robots.grievous.grievous_inference_host --dry-run --duration 300

# For real execution:
python -m lerobot.robots.grievous.grievous_inference_host --duration 300
```

### On Runpod (connects to RPi5):
```bash
cd /workspace/lerobot-xlerobot-integration

# Set your parameters:
export RPI5_IP="192.168.50.148"  # RPi5's IP
export POLICY_PATH="/workspace/outputs/smolvla_finetuned_20251210_022454/checkpoints/last/pretrained_model"
export EPISODES=1

lerobot-record \
    --robot.type=grievous_client \
    --robot.remote_ip=${RPI5_IP} \
    --policy.path="${POLICY_PATH}" \
    --dataset.repo_id="Grievous-Robot/eval_remote" \
    --dataset.num_episodes=${EPISODES} \
    --dataset.single_task="Remote inference test" \
    --dataset.push_to_hub=false \
    --display_data=false
```

---

## 3. Inference Mode - Reverse Connection (Behind NAT/Firewall)

**Use when:** RPi5 is behind university NAT (your situation)

### STEP 1 - On Runpod (binds and waits for RPi5):
```bash
cd /workspace/lerobot-xlerobot-integration

# First get Runpod's public IP:
curl ifconfig.me
# Example output: 209.170.80.156

# Set your parameters:
export POLICY_PATH="/workspace/outputs/smolvla_finetuned_20251210_022454/checkpoints/last/pretrained_model"
export EPISODES=1

# Start Runpod in server mode (waits for RPi5 to connect):
lerobot-record \
    --robot.type=grievous_client \
    --robot.reverse_connection=true \
    --robot.connect_timeout_s=120 \
    --policy.path="${POLICY_PATH}" \
    --dataset.repo_id="Grievous-Robot/eval_remote" \
    --dataset.num_episodes=${EPISODES} \
    --dataset.single_task="Remote inference test" \
    --dataset.push_to_hub=false \
    --display_data=false \
    --play_sounds=false \
    --dataset.rename_map='{"observation.images.left_wrist": "observation.images.camera1", "observation.images.right_wrist": "observation.images.camera2", "observation.images.head": "observation.images.camera3"}'
```

### STEP 2 - On RPi5 (connects to Runpod):
```bash
cd ~/Grievous
conda activate lerobot

# Set Runpod's IP and ports (check Runpod dashboard for current values):
export RUNPOD_IP="209.170.80.132"  # From: curl ifconfig.me on Runpod
# Port mapping from Runpod dashboard "Direct TCP ports":
# External 10526 -> Internal 5555 (commands)
# External 10527 -> Internal 5556 (observations)

# For dry-run (safe testing - logs actions, doesn't execute):
python -m lerobot.robots.grievous.grievous_inference_host \
    --remote-ip ${RUNPOD_IP} \
    --port-cmd 10526 \
    --port-obs 10527 \
    --dry-run \
    --duration 300

# For real execution (after dry-run looks good):
python -m lerobot.robots.grievous.grievous_inference_host \
    --remote-ip ${RUNPOD_IP} \
    --port-cmd 10526 \
    --port-obs 10527 \
    --duration 300
```

---

## 4. Latency Testing Mode (Mock Robot + Remote Policy)

**Use when:** Testing round-trip latency without physical robot hardware

**Purpose:** Measure inference latency from observation to action with SmolVLA policy on RunPod

### STEP 1 - On Runpod (binds and waits for laptop):
```bash
cd /workspace/lerobot-xlerobot-integration

# Pull latest changes (IMPORTANT - camera key fix):
git pull origin dummy_inference_laptop

# Activate conda environment:
conda activate lerobot

# Verify GPU is available:
nvidia-smi


# Start latency test client (binds to INTERNAL ports and waits 120s for host):
python -m lerobot.scripts.test_remote_inference_latency \
    --robot.type=grievous_client \
    --robot.reverse_connection=true \
    --robot.port_zmq_cmd=5555 \
    --robot.port_zmq_observations=5556 \
    --robot.connect_timeout_s=120 \
    --policy.path=lerobot/smolvla_base \
    --duration=30
```

**Expected output:**
- Policy will load (~10 seconds)
- "Connecting to robot client..."
- "Waiting for observations from host..."
- Then waits for your laptop to connect (up to 120 seconds)

### STEP 2 - On Laptop (connects to Runpod):
```bash
cd ~/Code/lerobot-xlerobot-integration

# Activate conda environment:
conda activate lerobot

# Get Runpod external ports from dashboard "Direct TCP ports":
# Example: 213.173.102.85:10305 -> :5555 (commands)
#          213.173.102.85:10306 -> :5556 (observations)

export RUNPOD_IP="213.173.102.85"      # From Runpod dashboard
export RUNPOD_CMD_PORT="10305"         # External port for commands (maps to 5555)
export RUNPOD_OBS_PORT="10306"         # External port for observations (maps to 5556)

# Start mock host (connects to EXTERNAL ports):
python -m lerobot.robots.grievous.grievous_mock_inference_host \
    --remote-ip ${RUNPOD_IP} \
    --port-cmd ${RUNPOD_CMD_PORT} \
    --port-obs ${RUNPOD_OBS_PORT} \
    --duration 30 \
    --resolution 480x640  # Default: 480x640. Try 240x320 for 4x less data (faster test)
```

**Resolution options:**
- `--resolution 480x640`: Full resolution (~2.9 MB, 640ms with 36 Mbps upload)
- `--resolution 240x320`: Quarter resolution (~0.7 MB, 160ms with 36 Mbps upload) ← **Recommended for testing**
- `--resolution 120x160`: 1/16th resolution (~0.2 MB, 40ms with 36 Mbps upload)


**Expected output:**
```
Connecting to remote policy at 213.173.102.85...
Test duration: 30 seconds
Expected samples: ~1500

[10 samples] Round-trip: 185.2ms | Inference: 156.3ms | Network: 28.9ms
[20 samples] Round-trip: 182.7ms | Inference: 155.1ms | Network: 27.6ms
...

============================================================
Latency Test Complete (150 samples)
============================================================

Round-trip Latency:
  Mean:   185.4 ms
  Median: 182.0 ms
  P95:    220.5 ms
  P99:    245.8 ms
  Min:    145.2 ms
  Max:    312.7 ms
============================================================
```


### Interpreting Results:
The test uses a **synchronous request-response** pattern:
- Host sends ONE observation → waits for action → measures latency → repeats

**Metrics Explained:**
- **Round-Trip Latency**: Total time from observation sent to action received (host's perspective)
  - `< 200ms`: Excellent - suitable for responsive robot control
  - `200-300ms`: Good - acceptable with action chunking
  - `> 300ms`: Poor - consider local inference or optimization
- **Inference Time**: Time spent on RunPod GPU processing the observation (measured on RunPod)
  - First inference ~400ms (model warmup) is normal
  - Subsequent inferences should be ~4-5ms (5090) or ~5-10ms (4090)
- **Test Time**: Total elapsed time since test started (for reference)

### Important Notes:
- **Test mode**: Synchronous (one request at a time) - no dropped observations or sequence gaps
- **Port mapping**: RunPod maps internal ports (5555, 5556) to external ports (check dashboard)
- **Order matters**: Start RunPod client FIRST, then laptop mock host SECOND (within 120 seconds)
- **First inference spike**: ~400ms is normal due to model compilation/warmup
- **No physical robot needed**: Uses dummy observations (zeros + random camera frames)

### Troubleshooting:
**Issue: `All image features are missing from the batch`**
- **Fix**: Pull latest changes on RunPod: `git pull origin dummy_inference_laptop`
- **Cause**: Camera keys need to be renamed from `left_wrist`/`right_wrist`/`head` to `camera1`/`camera2`/`camera3`

**Issue: `No module named 'zmq'`**
- **Fix**: Install pyzmq: `pip install pyzmq`

**Issue: Connection timeout / "Timeout waiting for host"**
- **Fix**: Check RunPod IP and ports are correct from dashboard
- **Fix**: Increase timeout: `--robot.connect_timeout_s=120` (default is 5 seconds)
- **Fix**: Start RunPod first, then laptop within timeout window

---

## Quick Tips

### Keyboard Controls (during recording):
- `→` (Right Arrow) - End episode and save / Skip reset
- `←` (Left Arrow) - Discard episode and re-record
- `Esc` - Stop recording and exit

### Common Variables:
```bash
# Recording:
TASK="Pick and place cube"
DATASET_NAME="pick-place"
VERSION=1
EPISODES=10

# Inference:
POLICY_PATH="/workspace/outputs/smolvla_finetuned_20251210_022454/checkpoints/last/pretrained_model"
RUNPOD_IP="209.170.80.156"  # From: curl ifconfig.me (on Runpod)
RPI5_IP="192.168.50.148"
```

### Checking Connection:
```bash
# On RPi5, check if you can reach Runpod:
ping -c 3 209.170.80.156

# Test port connectivity:
python3 -c "import socket; s=socket.socket(); s.settimeout(5); result = s.connect_ex(('209.170.80.156', 5555)); print('Reachable' if result == 0 else 'Not reachable'); s.close()"
```

### Get Runpod IP:
```bash
# On Runpod:
curl ifconfig.me
```

### Get RPi5 IP:
```bash
# On RPi5:
hostname -I
```

### Latency Test Tips:
```bash
# Activate conda environment first:
conda activate lerobot

# Check if zmq is installed (needed for latency test):
python -c "import zmq; print('ZMQ installed')"

# If not installed (should be in lerobot environment):
pip install pyzmq opencv-python numpy

# Test mock host help:
python -m lerobot.robots.grievous.grievous_mock_inference_host --help

# Test client help:
python -m lerobot.scripts.test_remote_inference_latency --help
```

