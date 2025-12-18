 # Remote Inference Latency Testing Plan

## Objective
Measure round-trip latency for SmolVLA inference running on RunPod (4090/5090) communicating with a mock local robot. Test duration: 30 seconds to get reliable latency statistics.

## Architecture

```
LAPTOP (Mock Robot Host)                    RUNPOD (Policy Client)
────────────────────────                    ──────────────────────

[t0] Generate dummy observation              
[t0] Tag: seq_num, timestamp_sent            
[t0] Send via ZMQ (port 5556)                
                            ────────────>    
                                             [t1] Receive observation
                                             [t1] Extract metadata
                                             [t2] Start policy inference
                                             [t3] End policy inference  
                                             [t4] Add metadata to action
                                             [t4] Send via ZMQ (port 5555)
                            <────────────    
[t5] Receive action                          
[t5] Calculate: round_trip = t5 - t0        
[t5] Log all metrics                         

METRICS:
├─ Round-trip latency: t5 - t0 (CRITICAL)
├─ Inference time: t3 - t2 (from action metadata)
└─ Network overhead: (t5 - t0) - (t3 - t2)
```

## Message Protocol

### Observation Message (Host → Client)
```python
{
    # Metadata (NEW)
    "seq_num": int,              # Sequence counter for matching
    "timestamp_sent": float,     # time.perf_counter() when sent
    
    # Robot state (17 floats - dummy data)
    "left_arm_shoulder_pan.pos": float,
    "left_arm_shoulder_lift.pos": float,
    "left_arm_elbow_flex.pos": float,
    "left_arm_wrist_flex.pos": float,
    "left_arm_wrist_roll.pos": float,
    "left_arm_gripper.pos": float,
    "right_arm_shoulder_pan.pos": float,
    "right_arm_shoulder_lift.pos": float,
    "right_arm_elbow_flex.pos": float,
    "right_arm_wrist_flex.pos": float,
    "right_arm_wrist_roll.pos": float,
    "right_arm_gripper.pos": float,
    "head_motor_1.pos": float,
    "head_motor_2.pos": float,
    "x.vel": float,
    "y.vel": float,
    "theta.vel": float,
    
    # Camera images (base64 JPEG - dummy 640x480 frames)
    "left_wrist": str,   # base64 encoded
    "right_wrist": str,  # base64 encoded
    "head": str,         # base64 encoded
}
```

### Action Message (Client → Host)
```python
{
    # Metadata (NEW - echoed + timing)
    "seq_num": int,                  # Echo from observation
    "timestamp_received": float,     # When client received obs
    "inference_start": float,        # Before policy.__call__()
    "inference_end": float,          # After policy.__call__()
    "timestamp_sent": float,         # Before sending action
    
    # Action values (17 floats - same keys as state)
    "left_arm_shoulder_pan.pos": float,
    # ... (same structure as observation state)
}
```

## Implementation Components

### Component 1: Mock Grievous Inference Host
**File**: `src/lerobot/robots/grievous/grievous_mock_inference_host.py`

**Purpose**: Lightweight daemon that sends dummy observations and receives actions with timing

**Key Features**:
- Generate synthetic robot state (random walk or fixed values)
- Generate dummy camera frames (colored noise or test patterns)
- Encode images to base64 JPEG (same as real host)
- Add sequence number and timestamp metadata
- Receive actions and extract timing metadata
- Calculate and log latency statistics in real-time

**Main Loop** (50Hz to simulate real robot):
```python
while duration < 30:  # 30 second test
    loop_start = time.perf_counter()
    
    # 1. Generate dummy observation
    observation = generate_dummy_observation()
    
    # 2. Add metadata
    seq_num = observation_counter
    observation_counter += 1
    timestamp_sent = time.perf_counter()
    pending_observations[seq_num] = timestamp_sent
    
    observation['seq_num'] = seq_num
    observation['timestamp_sent'] = timestamp_sent
    
    # 3. Send observation
    zmq_obs_socket.send_string(json.dumps(observation), zmq.NOBLOCK)
    
    # 4. Try to receive action (non-blocking)
    try:
        action_msg = zmq_cmd_socket.recv_string(zmq.NOBLOCK)
        action = json.loads(action_msg)
        timestamp_received = time.perf_counter()
        
        # 5. Calculate latencies
        action_seq = action['seq_num']
        if action_seq in pending_observations:
            round_trip_ms = (timestamp_received - pending_observations[action_seq]) * 1000
            inference_ms = (action['inference_end'] - action['inference_start']) * 1000
            network_ms = round_trip_ms - inference_ms
            
            # 6. Log statistics
            latencies.append(round_trip_ms)
            inference_times.append(inference_ms)
            
            # Print every 10 samples
            if len(latencies) % 10 == 0:
                print(f"[{len(latencies)} samples] "
                      f"Round-trip: {round_trip_ms:.1f}ms | "
                      f"Inference: {inference_ms:.1f}ms | "
                      f"Network: {network_ms:.1f}ms")
            
            del pending_observations[action_seq]
    except zmq.Again:
        pass  # No action yet
    
    # 7. Rate limit to 50Hz
    elapsed = time.perf_counter() - loop_start
    sleep_time = max(1/50 - elapsed, 0)
    time.sleep(sleep_time)
```

**Dummy Data Generation**:
```python
def generate_dummy_observation():
    # State: random walk or zeros
    state = {f"joint_{i}.pos": random.uniform(-1, 1) for i in range(17)}
    
    # Camera frames: 640x480 colored noise or test pattern
    for cam_name in ["left_wrist", "right_wrist", "head"]:
        frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        state[cam_name] = base64.b64encode(buffer).decode("utf-8")
    
    return state
```

### Component 2: Latency Test Client
**File**: `test_remote_inference_latency.py`

**Purpose**: RunPod script that receives observations, runs inference, sends actions with timing

**Key Features**:
- Initialize `GrievousClient` in reverse connection mode (bind locally)
- Load SmolVLA policy from `Grievous-Robot/smolvla_finetuned_5k`
- Load preprocessor/postprocessor with proper dataset stats
- Run inference loop with timing instrumentation
- Extract metadata from observations, add metadata to actions

**Main Loop**:
```python
policy.reset()
preprocessor.reset()
postprocessor.reset()

iteration = 0
max_iterations = 1000  # Safety limit

while iteration < max_iterations:
    # 1. Get observation from client (polls ZMQ)
    obs_dict = robot.get_observation()
    
    # 2. Extract metadata
    seq_num = obs_dict.pop('seq_num', -1)
    timestamp_sent = obs_dict.pop('timestamp_sent', 0)
    timestamp_received = time.perf_counter()
    
    # 3. Build dataset frame for policy
    observation_frame = build_dataset_frame(dataset.features, obs_dict, prefix="observation")
    
    # 4. Run inference with timing
    inference_start = time.perf_counter()
    action_values = predict_action(
        observation=observation_frame,
        policy=policy,
        device=device,
        preprocessor=preprocessor,
        postprocessor=postprocessor,
        use_amp=policy.config.use_amp,
        task="latency test",
        robot_type="grievous_client",
    )
    inference_end = time.perf_counter()
    
    # 5. Convert action to dict
    action_dict = {key: float(action_values[key]) for key in action_features}
    
    # 6. Add metadata
    action_dict['seq_num'] = seq_num
    action_dict['timestamp_received'] = timestamp_received
    action_dict['inference_start'] = inference_start
    action_dict['inference_end'] = inference_end
    action_dict['timestamp_sent'] = time.perf_counter()
    
    # 7. Send action
    robot.send_action(action_dict)
    
    iteration += 1
```

## Execution Workflow

### Step 1: Prepare RunPod Instance
```bash
# SSH into RunPod pod
# Navigate to lerobot directory
cd /workspace/lerobot-xlerobot-integration

# Verify GPU
nvidia-smi

# Get RunPod public IP (for laptop to connect)
curl ifconfig.me
# Example output: 23.45.67.89
```

### Step 2: Start Latency Test Client on RunPod
```bash
# Start client (binds to ports 5555/5556, waits for laptop)
python test_remote_inference_latency.py \
    --robot.type=grievous_client \
    --robot.reverse_connection=true \
    --robot.port_zmq_cmd=5555 \
    --robot.port_zmq_observations=5556 \
    --policy.path=Grievous-Robot/smolvla_finetuned_5k \
    --duration=30

# Expected output:
# > Loading policy from Grievous-Robot/smolvla_finetuned_5k...
# > Initializing GrievousClient in reverse connection mode...
# > Binding to ports 5555/5556...
# > Waiting for host to connect...
```

### Step 3: Start Mock Host on Laptop
```bash
# On laptop terminal
cd ~/Code/lerobot-xlerobot-integration

# Start mock host (connects to RunPod IP)
python src/lerobot/robots/grievous/grievous_mock_inference_host.py \
    --remote-ip 23.45.67.89 \
    --port-cmd 5555 \
    --port-obs 5556 \
    --duration 30

# Expected output:
# > Connecting to RunPod at 23.45.67.89...
# > Connected successfully
# > Starting 30-second latency test...
# [10 samples] Round-trip: 185.2ms | Inference: 156.3ms | Network: 28.9ms
# [20 samples] Round-trip: 182.7ms | Inference: 155.1ms | Network: 27.6ms
# ...
```

### Step 4: Analyze Results
After 30 seconds, both scripts print final statistics:

**Mock Host Output**:
```
========================================
Latency Test Complete (150 samples)
========================================
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

Network Overhead:
  Mean:   29.1 ms
  Median: 26.2 ms

Dropped Observations: 0
Sequence Gaps: []
========================================
```

## Development Checklist

### Phase 1: Mock Host Implementation (45 min) ✅ COMPLETE
- [x] Create `grievous_mock_inference_host.py`
- [x] Implement dummy observation generation (state + images)
- [x] Add sequence number and timestamp tagging
- [x] Implement ZMQ sockets (reverse connection mode)
- [x] Add latency calculation and logging
- [x] Add final statistics summary (mean, median, P95, P99)
- [ ] Test locally with netcat or simple receiver

### Phase 2: Client Script Implementation (45 min) ✅ COMPLETE
- [x] Create `test_remote_inference_latency.py`
- [x] Setup `GrievousClient` with reverse connection
- [x] Load policy `Grievous-Robot/smolvla_finetuned_5k`
- [x] Setup preprocessor/postprocessor (handle missing dataset stats gracefully)
- [x] Extract metadata from observations
- [x] Run inference loop with timing
- [x] Add metadata to actions
- [x] Handle connection timeout gracefully

### Phase 3: Integration Testing (30 min) ⏳ IN PROGRESS
- [x] Create comprehensive usage documentation (LATENCY_TEST_README.md)
- [ ] Test with both scripts on same machine (localhost)
- [ ] Verify sequence numbers match
- [ ] Verify no dropped observations
- [ ] Check latency calculations are reasonable
- [ ] Test with RunPod instance
- [ ] Verify 30-second duration works correctly

## Expected Results

**Target Latency Budget** (for 50Hz robot control = 20ms cycle time):
- **Inference**: ~150-200ms (SmolVLA on 4090/5090)
- **Network**: ~20-50ms (depends on connection quality)
- **Total Round-trip**: ~170-250ms

**Interpretation**:
- If round-trip < 200ms: Excellent, could support action chunking
- If round-trip 200-300ms: Acceptable with large action chunks
- If round-trip > 300ms: May need optimization or local inference
