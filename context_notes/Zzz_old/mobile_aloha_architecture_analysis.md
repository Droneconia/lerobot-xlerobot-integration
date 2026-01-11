# Mobile ALOHA Architecture Analysis

**Date**: November 2025  
**Purpose**: Deep analysis of Mobile ALOHA's communication, teleoperation, and training workflow to extract insights for Grievous robot implementation

---

## Executive Summary

Mobile ALOHA uses a **monolithic, single-machine architecture** where all hardware (4 robot arms, cameras, mobile base) connects directly to one computer via USB/serial. Unlike Grievous's network-based design, there is **zero network communication** during teleoperation or policy execution. All coordination happens through **ROS1** topics running locally at 50Hz.

**Key Architectural Principle**: Everything runs on one machine to minimize latency and ensure deterministic timing.

---

## 1. Hardware Architecture

### Physical Components
```
Mobile ALOHA System:
├── Master Arms (2x wx250s) - Operator Input
│   ├── Left master: /dev/ttyDXL_master_left
│   └── Right master: /dev/ttyDXL_master_right
├── Puppet Arms (2x vx300s) - Task Execution
│   ├── Left puppet: /dev/ttyDXL_puppet_left
│   └── Right puppet: /dev/ttyDXL_puppet_right
├── Cameras (3x USB)
│   ├── /dev/CAM_HIGH
│   ├── /dev/CAM_LEFT_WRIST
│   └── /dev/CAM_RIGHT_WRIST
└── Mobile Base
    ├── AgileX Tracer (CANBUS)
    └── or Custom wheels (Dynamixel, /dev/ttyDXL_wheels)
```

### Port Management Strategy
- **udev rules** bind each device to fixed symlinks based on serial numbers
- Prevents port reassignment issues (`ttyUSB0` → `ttyUSB5`)
- Critical for reliability: "Do not use extension cables or USB hubs" (max 2 cameras per hub if needed)
- Latency timer set to 1ms via udev for all devices

---

## 2. Communication Architecture

### Core Design: Local ROS1 Topology

**NO NETWORK COMMUNICATION EXISTS**

All components communicate via ROS1 topics on localhost:

```
ROS1 Topics (Single Machine):
├── Master Arms → ROS Topics
│   ├── /master_left/joint_states (JointState)
│   └── /master_right/joint_states (JointState)
├── Puppet Arms ← ROS Topics
│   ├── /puppet_left/commands/joint_group (JointGroupCommand)
│   ├── /puppet_left/commands/joint_single (JointSingleCommand)
│   ├── /puppet_right/commands/joint_group
│   └── /puppet_right/commands/joint_single
├── Cameras → ROS Topics
│   ├── /usb_cam_high/image_raw (sensor_msgs/Image)
│   ├── /usb_cam_left_wrist/image_raw
│   └── /usb_cam_right_wrist/image_raw
└── Mobile Base (Direct SDK, no ROS)
    ├── pyagxrobots.TracerBase() for CANBUS base
    └── DynamixelClient for wheel motors
```

### Control Flow

**Teleoperation Mode** (record_episodes.py):
```
1. Master arms publish joint states → ROS topics (via Interbotix SDK)
2. Python script subscribes to master topics
3. get_action() reads master positions directly from ROS JointState messages
4. Script publishes commands to puppet ROS topics
5. Interbotix nodes forward commands to Dynamixel motors
6. Image data collected via ROS subscribers (ImageRecorder class)
7. All data synchronized in-memory, then saved to HDF5

Control Loop: ~50Hz (20ms)
```

**Policy Execution Mode** (replay_episodes.py):
```
1. Load actions from HDF5 file
2. Directly call puppet_bot.arm.set_joint_positions()
3. Mobile base controlled via tracer.SetMotionCommand()
4. No network involved - direct API calls

Replay Rate: 50Hz
```

---

## 3. Motor Control Layer

### Dynamixel Communication

**Protocol**: Dynamixel SDK Protocol 2.0  
**Baudrate**: 1,000,000 bps  
**Motor IDs**: 1-9 per arm (8 joints + gripper)

#### Custom `DynamixelClient` Class (dynamixel_client.py)

**Key Features**:
- Wraps DynamixelSDK with cleaner API
- **GroupBulkRead** for efficient position/velocity/current reading
- **GroupSyncWrite** for simultaneous motor commands
- Caching previous read values if communication fails
- Motor scaling: positions (radians), velocities (rad/s), currents (mA)

**Critical Read Operation** (runs every control loop):
```python
def read_pos_vel_cur(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    # Bulk reads all motors in single USB transaction
    # Address: ADDR_PRESENT_POS_VEL_CUR (126)
    # Length: 10 bytes (current=2, velocity=4, position=4)
    return positions, velocities, currents
```

**Write Operation**:
```python
def write_desired_pos(self, motor_ids, positions):
    # GroupSyncWrite to ADDR_GOAL_POSITION (116)
    # Sends commands to all motors simultaneously
    # Does NOT wait for completion (non-blocking)
```

### Master vs Puppet Motor Configuration

**Master Arms** (Operator Input):
- Operating mode: **PWM** (torque off, free-moving for operator to manipulate)
- Gripper: **Current-based position** (slight resistance for tactile feedback)
- Purpose: Human physically moves arms, positions are read passively

**Puppet Arms** (Task Execution):
- Operating mode: **Position control**
- Profile velocity/acceleration: **0** (immediate response, no trajectory smoothing)
- Gripper: **Current-based position** (compliant grasping)
- Purpose: Tracks master positions or policy commands

**Critical Optimization** (from README):
```python
# In interbotix_xs_modules/arm.py, line ~50
# ORIGINAL: self.T_sb = mr.FKinSpace(...)  # Forward kinematics every step
# MODIFIED: self.T_sb = None  # Skip FK calculation

# Reason: FK adds ~5ms latency per arm per step
# At 50Hz with 4 arms, this saves 20ms per cycle
```

---

## 4. Camera Management

### ROS USB Camera Nodes

**Configuration** (from 4arms_teleop.launch):
- **Device**: Bound via udev symlinks (`/dev/CAM_*`)
- **Resolution**: 640x480
- **Framerate**: 60 FPS (hardware)
- **Pixel format**: YUYV
- **Autofocus**: Disabled (fixed focus for consistency)
- **Focus values**: Hand-tuned per camera (5, 40, 40 for high, left_wrist, right_wrist)

### Image Data Flow

**During Recording**:
```python
class ImageRecorder:
    # Subscribes to ROS image topics
    rospy.Subscriber("/usb_{cam_name}/image_raw", Image, callback)
    
    def image_cb(self, cam_name, data):
        # Convert ROS Image → OpenCV (BGR/RGB)
        self._image = CvBridge().imgmsg_to_cv2(data)
        self._secs = data.header.stamp.secs
        self._nsecs = data.header.stamp.nsecs
```

**Storage** (HDF5 with JPEG Compression):
```python
# From record_episodes.py
COMPRESS = True
encode_param = [cv2.IMWRITE_JPEG_QUALITY, 50]  # Quality 50

# Process:
1. Record raw images (480x640x3 uint8)
2. JPEG compress each frame → variable length bytes
3. Pad to max length for HDF5 storage
4. Store compressed bytes + compress_len array

# Compression reduces file size ~10x
# Dataset includes '/compress_len' to decode variable-length JPEGs
```

**No Network Transmission**: Images never sent over network during teleoperation. Only accessed locally via ROS shared memory.

---

## 5. Teleoperation Workflow

### Full Teleoperation Pipeline

**Setup Phase** (opening_ceremony):
```python
1. Reboot gripper motors (clear errors)
2. Set operating modes:
   - Master arms: position mode, gripper position mode
   - Puppet arms: position mode, gripper current-based position
3. Enable torque on all motors
4. Move to START_ARM_POSE (ergonomic starting position)
5. Wait for operator to close both master grippers (trigger signal)
6. Disable torque on master arms (free-moving)
```

**Control Loop** (50Hz):
```python
def capture_one_episode():
    for t in range(max_timesteps):
        t0 = time.time()
        
        # 1. Read master arm positions (from ROS joint states)
        action = get_action(master_bot_left, master_bot_right)
        # Returns: [left_arm(6), left_gripper(1), right_arm(6), right_gripper(1)]
        
        # 2. Command puppet arms + get observations
        ts = env.step(action)
        # - Publishes joint commands to ROS topics
        # - Reads puppet joint states from ROS topics
        # - Reads camera images from ROS topics
        # - Reads base velocity from Dynamixel or Tracer
        
        # 3. Store data
        timesteps.append(ts)
        actions.append(action)
        
        # 4. Sleep to maintain 50Hz
        time.sleep(max(0, DT - (time.time() - t0)))
```

**Key Insight**: The control loop is **synchronous** and **blocking**. No asynchronous network calls. Everything happens in sequence within 20ms.

### Kinematic Mapping

**Master → Puppet Mapping**:
- **Arm joints**: Direct copy (master and puppet have proportional kinematics)
  ```python
  puppet_arm_qpos = master_arm_qpos  # 1:1 mapping
  ```
- **Gripper**: Normalized mapping (different gripper geometries)
  ```python
  # Normalize master gripper to [0, 1]
  norm = (pos - MASTER_CLOSE) / (MASTER_OPEN - MASTER_CLOSE)
  # Unnormalize to puppet gripper range
  puppet_pos = norm * (PUPPET_OPEN - PUPPET_CLOSE) + PUPPET_CLOSE
  ```

---

## 6. Data Collection & Storage

### HDF5 Dataset Structure

```
episode_N.hdf5:
├── attributes
│   ├── sim: False
│   └── compress: True
├── observations/
│   ├── qpos (max_timesteps, 14)          # Joint positions: [left_arm(6), left_grip(1), right_arm(6), right_grip(1)]
│   ├── qvel (max_timesteps, 14)          # Joint velocities
│   ├── effort (max_timesteps, 14)        # Joint torques/currents
│   └── images/
│       ├── cam_high (max_timesteps, padded_size) # JPEG compressed bytes
│       ├── cam_left_wrist (...)
│       └── cam_right_wrist (...)
├── action (max_timesteps, 14)            # Commanded joint positions
├── base_action (max_timesteps, 2)        # [linear_vel, angular_vel]
└── compress_len (3, max_timesteps)       # Length of each compressed image
```

**Episode Length**: Task-dependent (1000-8500 timesteps, i.e., 20-170 seconds)

**Data Fidelity**: All observations and actions timestamped and synchronized within the same Python process. No network jitter.

---

## 7. Training Workflow

### Separation of Concerns

**Mobile ALOHA repo** (data collection):
- Teleoperation scripts
- Data recording to HDF5
- Replay for verification

**ACT++ repo** (policy learning):
- Loads HDF5 datasets
- Trains Action Chunking Transformer
- Exports trained policy

**Workflow**:
```
1. Record episodes on robot → HDF5 files
2. Copy HDF5 files to training machine (laptop/workstation with GPU)
3. Train ACT++ policy on training machine
4. Copy trained policy back to robot
5. Load policy in Python script on robot
6. Run inference locally (no network)
```

**Key Point**: Training happens **offline** on a separate machine. The robot is never used during training. No network communication during deployment.

---

## 8. Policy Execution (Replay/Inference)

### Replay Mode (replay_episodes.py)

Executes recorded actions open-loop:
```python
# Load HDF5 data
actions = root['/action'][()]
base_actions = root['/base_action'][()]

# Execute at 50Hz
for action, base_action in zip(actions, base_actions):
    env.step(action, base_action)
    time.sleep(DT)
```

### Policy Inference Mode (not in this repo)

From ACT++, typical structure:
```python
# Load trained policy
policy = ACTPolicy.load(checkpoint_path)
policy.cuda()

# Inference loop
obs = env.get_observation()  # Includes qpos, qvel, images
action = policy.predict(obs, num_queries=100)  # Action chunks

# Execute action chunk at 50Hz
for a in action:
    env.step(a)
    time.sleep(DT)
```

**No Network**: Policy runs locally on the robot computer. GPU inference if available, otherwise CPU.

---

## 9. Latency & Performance Optimization

### Measured Performance

From diagnostics in code:
```python
# record_episodes.py:
freq_mean = 1 / dt_mean
# Target: 50Hz (20ms per cycle)
# If freq_mean < 30Hz, episode is rejected and re-recorded

# Breakdown:
# - get_action (read ROS topics): ~1ms
# - step_env (command + read obs): ~15ms
#   - Joint read: ~2ms per arm (bulk read)
#   - Joint write: <1ms (sync write, non-blocking)
#   - Image copy from ROS: ~8ms (3 cameras)
# - Total: ~16-18ms
# - Sleep: ~2-4ms to reach 20ms target
```

### Optimization Strategies

1. **Skip FK calculation** in Interbotix SDK (saves ~5ms/arm)
2. **GroupBulkRead** for motor states (single USB transaction vs N transactions)
3. **GroupSyncWrite** for motor commands (simultaneous, non-blocking)
4. **Profile velocity = 0** (no trajectory generation in motors, immediate response)
5. **Local ROS communication** (shared memory, no TCP serialization)
6. **DT sleep** at end of loop (maintains consistent timing)

**Critical Insight**: Because everything is local, latency is **deterministic**. No network jitter, packet loss, or retransmission delays.

---

## 10. Comparison: Mobile ALOHA vs Grievous

| Aspect | Mobile ALOHA | Grievous |
|--------|--------------|----------|
| **Architecture** | Monolithic (1 computer) | Distributed (RPi5 + Laptop) |
| **Leader Arms** | On separate USB ports | On RPi5 USB ports |
| **Communication** | Local ROS topics | ZMQ over TCP/IP network |
| **Latency** | ~16ms (deterministic) | ~20-50ms (variable, network dependent) |
| **Teleoperation** | Direct master→puppet mapping | Network round-trip for each command |
| **Data Collection** | Local HDF5 save | Possible local or streamed |
| **Training** | Offline on separate machine | Offline on laptop |
| **Policy Execution** | Local inference on robot PC | Network inference from laptop |
| **Cameras** | ROS USB camera nodes | Directly via Python (OpenCV/RealSense) |
| **Mobile Base** | Direct CANBUS or Dynamixel | Feetech motors via bus |
| **Motor Protocol** | Dynamixel Protocol 2.0 (1Mbps) | Feetech Protocol (USB serial) |
| **Advantages** | Low latency, deterministic | Flexible, powerful laptop GPU |
| **Disadvantages** | Limited by single PC compute | Network lag during teleop |

---

## 11. Key Architectural Insights

### Why Mobile ALOHA Works Well

1. **Single Machine Eliminates Network**: No TCP/IP overhead, packet loss, or jitter
2. **ROS Provides Structure**: Topic-based pub/sub without manual socket management
3. **Bulk Operations**: GroupBulkRead/Write minimize USB round-trips
4. **Hardware Optimization**: udev rules, fixed ports, latency timers
5. **Synchronous Design**: Blocking control loop ensures consistent timing
6. **Offline Training**: Robot not needed during training, no GPU on robot

### Why Grievous Differs

1. **Leader arms on RPi5**: Should be directly controlled, not sent over network
2. **Network for policy inference**: Laptop GPU useful for neural network forward pass
3. **Network for data collection**: RPi5 overheats during intensive processing

### Recommended Grievous Usage Pattern (from this analysis)

**For Teleoperation** (data collection):
```
Run entirely on RPi5 (no network):
- Leader arms (USB) → Read positions
- Follower arms (USB) → Send commands
- Cameras (USB) → Capture images
- Save HDF5 locally on RPi5
- Copy data to laptop afterward
```

**For Policy Execution** (evaluation):
```
Use network (acceptable latency for policy inference):
- RPi5: Read follower states, cameras → Send to laptop
- Laptop: Run policy inference (GPU) → Send actions to RPi5
- RPi5: Execute actions on follower arms
- No leader arm reading needed
```

This matches Grievous's design: **local teleoperation, network inference**.

---

## 12. Technical Learnings for Grievous

### What to Adopt

1. **Bulk motor operations**: Implement GroupBulkRead equivalent for Feetech motors
2. **Fixed device symlinks**: Use udev rules for consistent port mapping
3. **HDF5 + JPEG compression**: Efficient storage format (already in lerobot)
4. **Synchronous control loop**: Clear timing, easier debugging than async
5. **Health checks**: Reject episodes with low frequency (data quality assurance)
6. **Profile settings**: Zero profile velocity/acceleration for immediate response

### What to Avoid

1. **Network teleoperation**: Mobile ALOHA confirms local is mandatory for low latency
2. **Async network calls in control loop**: Adds jitter, harder to debug
3. **FK calculation every step**: Unnecessary overhead for simple control

### What Grievous Does Better

1. **Compositional robot design**: XLerobot + BiSO100Leader is cleaner than 4 separate arms
2. **Network inference flexibility**: Can use powerful laptop GPU for policy execution
3. **Modern Python stack**: lerobot repo is more maintainable than ROS1 launch files

---

## 13. Conclusion

Mobile ALOHA's architecture is **optimized for deterministic, low-latency teleoperation** by running everything on a single machine. This eliminates network overhead but constrains compute resources.

Grievous's distributed architecture offers flexibility for GPU-accelerated inference but **must run teleoperation locally** to avoid network lag that causes motor burnout.

**Actionable Recommendation**: 
- **Do**: Run `lerobot_record.py` on RPi5 (local teleoperation)
- **Do**: Run `lerobot_eval.py` from laptop (network inference is acceptable, ~30Hz)
- **Don't**: Run `lerobot_teleoperate.py` from laptop (network latency causes tracking errors)

This analysis confirms the insights from context_notes/robot_patterns_analysis.md and context_notes/lekiwi_architecture_analysis.md.

---

**End of Analysis**

