# Grievous Robot Commands Cheatsheet

Quick reference for running Grievous in different modes.

---

## 1. Recording Mode (with Teleoperation)

### On RPi5:
```bash
cd ~/Code/lerobot-xlerobot-integration
conda activate grievous
python src/lerobot/robots/grievous/grievous_host.py
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
    --policy.path="${POLICY_PATH}" \
    --dataset.repo_id="Grievous-Robot/eval_remote" \
    --dataset.num_episodes=${EPISODES} \
    --dataset.single_task="Remote inference test" \
    --dataset.push_to_hub=false \
    --display_data=false
```

### STEP 2 - On RPi5 (connects to Runpod):
```bash
cd ~/Code/lerobot-xlerobot-integration
conda activate grievous

# Set Runpod's IP (from curl ifconfig.me above):
export RUNPOD_IP="209.170.80.156"  # Replace with actual Runpod IP

# For dry-run (safe testing - logs actions, doesn't execute):
python -m lerobot.robots.grievous.grievous_inference_host \
    --remote-ip ${RUNPOD_IP} \
    --dry-run \
    --duration 300

# For real execution (after dry-run looks good):
python -m lerobot.robots.grievous.grievous_inference_host \
    --remote-ip ${RUNPOD_IP} \
    --duration 300
```

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

---

## Your Current Setup

Based on our troubleshooting:
- **RPi5 is behind university NAT** → Use **Reverse Connection** (Section 3)
- **Runpod IP**: Get with `curl ifconfig.me` on Runpod
- **RPi5 IP**: `192.168.50.148` (local, won't work from outside)

**For first-time testing:**
1. Use **Section 3** (Reverse Connection)
2. Start with `--dry-run` flag on RPi5
3. Watch the logs to verify actions look reasonable
4. Remove `--dry-run` for real execution

