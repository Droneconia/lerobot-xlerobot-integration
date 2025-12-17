# Remote Inference Latency Testing

This document explains how to run latency tests for SmolVLA remote inference between a mock robot host (laptop) and a policy client (RunPod).

## Overview

The latency test measures round-trip time for:
1. Mock host generates observation (state + 3 camera images)
2. Observation sent to RunPod via ZMQ
3. SmolVLA policy runs inference on RunPod
4. Action sent back to mock host via ZMQ
5. Mock host calculates latency metrics

## Prerequisites

### On Laptop
```bash
# Install required packages (should already be installed)
pip install opencv-python numpy pyzmq
```

### On RunPod
```bash
# Ensure lerobot environment is activated
# All dependencies should be installed via lerobot installation
```

## Quick Start

### Step 1: Get RunPod Public IP

On your RunPod instance:
```bash
curl ifconfig.me
# Example output: 23.45.67.89
```

### Step 2: Start Client on RunPod (First!)

The client must start first because it binds to ports and waits for the host.

```bash
# On RunPod terminal
cd /workspace/lerobot-xlerobot-integration

# Start latency test client
python test_remote_inference_latency.py \
    --robot.type=grievous_client \
    --robot.reverse_connection=true \
    --robot.port_zmq_cmd=5555 \
    --robot.port_zmq_observations=5556 \
    --policy.path=Grievous-Robot/smolvla_finetuned_5k \
    --duration=30

# Expected output:
# INFO - Loading policy from Grievous-Robot/smolvla_finetuned_5k...
# INFO - Initializing GrievousClient...
# INFO - Binding to ports 5555/5556...
# INFO - Waiting for observations from host...
```

### Step 3: Start Mock Host on Laptop (Second!)

Once the client is waiting, start the mock host:

```bash
# On laptop terminal
cd ~/Code/lerobot-xlerobot-integration

# Start mock host (replace with your RunPod IP)
python src/lerobot/robots/grievous/grievous_mock_inference_host.py \
    --remote-ip 23.45.67.89 \
    --port-cmd 5555 \
    --port-obs 5556 \
    --duration 30

# Expected output:
# INFO - Connecting to remote policy at 23.45.67.89...
# INFO - Starting 30-second latency test...
# [10 samples] Round-trip: 185.2ms | Inference: 156.3ms | Network: 28.9ms
# [20 samples] Round-trip: 182.7ms | Inference: 155.1ms | Network: 27.6ms
# ...
```

### Step 4: Wait for Test to Complete

Both scripts will run for 30 seconds. The mock host will print:
- Real-time progress every 10 samples
- Final statistics at the end (mean, median, P95, P99)

Example final output:
```
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

Inference Time (from client):
  Mean:   156.3 ms
  Median: 155.8 ms
  P95:    165.2 ms
  P99:    172.1 ms

Network Overhead:
  Mean:   29.1 ms
  Median: 26.2 ms

Dropped Observations: 0
Sequence Gaps: []
============================================================
```

## Configuration Options

### Mock Host Options

```bash
python src/lerobot/robots/grievous/grievous_mock_inference_host.py --help

Options:
  --remote-ip IP       RunPod IP address (required)
  --port-cmd PORT      Command port (default: 5555)
  --port-obs PORT      Observation port (default: 5556)
  --duration SECONDS   Test duration (default: 30)
  --freq HZ            Loop frequency (default: 50)
```

### Client Options

```bash
python test_remote_inference_latency.py --help

Options:
  --robot.type TYPE                 Robot type (use: grievous_client)
  --robot.reverse_connection BOOL   Bind mode (use: true)
  --robot.port_zmq_cmd PORT         Command port (default: 5555)
  --robot.port_zmq_observations PORT Observation port (default: 5556)
  --policy.path PATH                Policy checkpoint path
  --duration SECONDS                Test duration (default: 30)
```

## Troubleshooting

### Client Never Receives Observations

**Symptom**: Client waits forever, no "First observation received" message

**Possible causes**:
1. Firewall blocking ports 5555/5556 on RunPod
2. Wrong IP address
3. Mock host not started

**Solutions**:
```bash
# On RunPod: Check if ports are listening
netstat -tuln | grep 555

# On RunPod: Test firewall (if using UFW)
sudo ufw status
sudo ufw allow 5555
sudo ufw allow 5556

# On laptop: Test connectivity
nc -zv <RUNPOD_IP> 5555
nc -zv <RUNPOD_IP> 5556
```

### Policy Loading Fails

**Symptom**: `Error loading policy` or `Model not found`

**Solutions**:
```bash
# On RunPod: Verify HuggingFace authentication
huggingface-cli whoami

# On RunPod: Manually download model first
python -c "from huggingface_hub import snapshot_download; snapshot_download('Grievous-Robot/smolvla_finetuned_5k')"
```

### High Latency (>500ms)

**Symptom**: Round-trip latency consistently above 500ms

**Possible causes**:
1. Slow network connection
2. GPU not being used (CPU inference)
3. Model too large for GPU

**Solutions**:
```bash
# On RunPod: Check GPU is being used
nvidia-smi  # Should show python process using GPU

# On RunPod: Check GPU memory
nvidia-smi --query-gpu=memory.used,memory.total --format=csv

# If GPU OOM, try with lower precision
# Edit test_remote_inference_latency.py:
# Set use_amp=True in policy config
```

### Sequence Gaps

**Symptom**: "Sequence gap detected" warnings

**Causes**: Inference is slower than observation rate (50Hz)

**Solutions**:
1. Reduce mock host frequency: `--freq 10` (10Hz instead of 50Hz)
2. Check if GPU is actually being used
3. This is normal during initial warm-up (first few iterations)

## Interpreting Results

### Round-trip Latency

This is the **most important metric** - time from observation capture to action execution.

- **< 200ms**: Excellent - suitable for responsive robot control with action chunking
- **200-300ms**: Good - acceptable with larger action chunks (predict 50-100 steps ahead)
- **300-500ms**: Marginal - may cause sluggish robot behavior
- **> 500ms**: Poor - consider local inference or optimization

### Inference Time

Time spent in `policy.__call__()` on RunPod GPU.

- SmolVLA on 4090/5090: Expected ~150-200ms
- If much higher (>300ms), GPU may not be used or model is too large

### Network Overhead

Difference between round-trip and inference: `round_trip - inference`

- **< 50ms**: Excellent network connection
- **50-100ms**: Good - typical for cloud instances
- **> 100ms**: Poor - check network, consider different RunPod region

## Comparing GPU Performance

To compare 4090 vs 5090:

```bash
# Test on 4090 RunPod instance
python test_remote_inference_latency.py --policy.path=Grievous-Robot/smolvla_finetuned_5k --duration=60

# Test on 5090 RunPod instance  
python test_remote_inference_latency.py --policy.path=Grievous-Robot/smolvla_finetuned_5k --duration=60

# Compare inference time mean/median
```

Expected difference: 5090 should be ~20-30% faster than 4090 for transformer models.

## Technical Details

### Message Protocol

**Observation** (host → client):
```python
{
    "seq_num": 123,                    # Sequence number for matching
    "timestamp_sent": 1234567890.123,  # Monotonic timestamp
    # Robot state (17 floats)
    "left_arm_shoulder_pan.pos": 0.0,
    # ... (12 more joint positions)
    # Camera images (base64 JPEG, ~50-100KB each)
    "left_wrist": "base64_encoded...",
    "right_wrist": "base64_encoded...",
    "head": "base64_encoded...",
}
```

**Action** (client → host):
```python
{
    "seq_num": 123,                        # Echoed back
    "timestamp_received": 1234567890.234,  # Client clock
    "inference_start": 1234567890.235,     # Before inference
    "inference_end": 1234567890.456,       # After inference
    "timestamp_sent": 1234567890.457,      # Before sending
    # Action values (17 floats)
    "left_arm_shoulder_pan.pos": 0.1,
    # ... (16 more action values)
}
```

### Latency Calculation

```python
# Round-trip latency (host-side, no clock sync needed)
round_trip_ms = (timestamp_received - pending_observations[seq_num]) * 1000

# Inference time (client-side)
inference_ms = (inference_end - inference_start) * 1000

# Network overhead (calculated)
network_ms = round_trip_ms - inference_ms
```

No clock synchronization required between machines - we only compare timestamps from the same clock.

