# Laptop Hardware Specifications (Nov 19, 2025)

## System
- **CPU**: Intel i7-9750H @ 2.60GHz (6 cores, 12 threads)
- **RAM**: 32GB (28GB available)
- **GPU**: NVIDIA GTX 1650 Mobile (4GB VRAM, CUDA 12.4)
- **OS**: Ubuntu 22.04.5 LTS, Kernel 6.8.0-83-generic
- **Storage**: 228GB total, **17GB free (93% full)** ⚠️

## USB Infrastructure
- **Bus 1**: USB 2.0 (16 ports, 480 Mbps) - Black ports
- **Bus 2**: USB 3.0 (8 ports, 10 Gbps) - Blue ports, ~20x faster than USB 2.0

### USB Speed Comparison
- **USB 2.0**: 480 Mbps - Sufficient for motor controllers, adequate for compressed video
- **USB 3.0**: 10 Gbps (10,000 Mbps) - Required for high-bandwidth devices (depth cameras, multiple HD cameras)
- **Note**: Device speed is determined by the device itself and the slowest hub in the chain, not just the port color

## Connected Devices ✅

### Physical Setup
- **Thunderbolt port** → Genesys Logic USB 3.0 hub → 4x Motor controllers + 2x Wrist cameras
- **Blue USB 3.0 port #1** → RealSense D435 (direct connection)
- **Blue USB 3.0 port #2** → Terminus USB 2.0 hub → (available for expansion)

### USB Bus Assignment
**Bus 002 (USB 3.0 - 10 Gbps):**
- RealSense D435 head camera (8086:0b07)

**Bus 001 (USB 2.0 - 480 Mbps):**
- 4x QinHeng CH340 motor controllers (1a86:55d3) - Follower + Leader arms
- 2x Microdia Vitade AF wrist cameras (0c45:6366)
- Built-in Chicony webcam (04f2:b685)

### Device Paths

**Motor Controllers (Identified):**
- `/dev/leader_left` → Leader left arm
- `/dev/follower_left` → Follower left arm
- `/dev/follower_right` → Follower right arm
- `/dev/leader_right` → Leader right arm

**Cameras (Identified):**
- `/dev/cam_left` → Left wrist
- `/dev/cam_right`  → Right wrist
- `032622074046` → Intellsense serial number

## Next Steps
1. ✅ ~~Run `lerobot_find_port.py` to map motor controllers to ports~~ - DONE
2. Run `lerobot_find_cameras.py` to identify camera indices
3. Update `config_grievous.py` with identified port paths
4. Free up disk space (only 17GB available)

## Udev Motor Rules
SUBSYSTEM=="tty", ATTRS{serial}=="5A7A054921", SYMLINK+="follower_left"
SUBSYSTEM=="tty", ATTRS{serial}=="5A68013127", SYMLINK+="leader_left"
SUBSYSTEM=="tty", ATTRS{serial}=="5A7A054790", SYMLINK+="follower_right"
SUBSYSTEM=="tty", ATTRS{serial}=="5A7A059375", SYMLINK+="leader_right"

## Udev Camera rules 
# Wrist Camera Left
SUBSYSTEM=="video4linux", KERNEL=="video*", KERNELS=="1-3.1", ATTR{index}=="0", SYMLINK+="cam_left"

# Wrist Camera Right
SUBSYSTEM=="video4linux", KERNEL=="video*", KERNELS=="1-6", ATTR{index}=="0", SYMLINK+="cam_right"

^ Had to correct the above versions by adding {index}=="0"

## Add Grievous to Dialout
`sudo usermod -a -G dialout grievous`

## Recording Controls
- Right arrow -> finish current step
- Left arrow -> redo episode
- ESC -> end recording early, includes the episode where the recording was ended

