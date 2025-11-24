#!/bin/bash

# Grievous Robot Recording Script
# Organization: Grievous-Robot (https://huggingface.co/Grievous-Robot)
# 
# ============================================================================
# KEYBOARD CONTROLS (Primary Method):
# ============================================================================
#   →  (Right Arrow)  - End current episode and save
#   ←  (Left Arrow)   - Discard current episode and re-record
#   Esc               - Stop all recording and exit
#
# Recording Flow:
#   1. Episode starts automatically
#   2. Perform the task
#   3. Press → when done (or wait for timeout)
#   4. Reset environment during reset period
#   5. Press → to skip reset early (or wait for timeout)
#   6. Repeat for next episode
#
# ============================================================================
# USAGE:
# ============================================================================
#   ./test_record.sh                                    # Use defaults
#   TASK="pick cube" VERSION=2 ./test_record.sh        # Specify task & version
#
# Environment Variables:
#   TASK         - Task description (default: "Test record")
#   VERSION      - Dataset version number (default: 1, auto-increments if exists)
#   EPISODES     - Max number of episodes (default: 50)
#   EPISODE_TIME - Max recording time per episode in seconds (default: 120)
#   RESET_TIME   - Max reset time between episodes in seconds (default: 60)
#   DATASET_NAME - Base dataset name (default: test-record)
#
# Note: If a dataset with the specified VERSION already exists locally, the script
#       will automatically increment to the next available version number.
#
# Example:
#   TASK="Pick red cube and place in blue box" \
#   VERSION=1 \
#   DATASET_NAME="pick-place" \
#   EPISODES=25 \
#   ./test_record.sh
#
#   This creates: Grievous-Robot/pick-place-v1
# ============================================================================

# Configuration
TASK="${TASK:-Test record}"
REQUESTED_VERSION="${VERSION:-1}"
EPISODES="${EPISODES:-10}"
EPISODE_TIME="${EPISODE_TIME:-120}"  # 2 min safety timeout (use → to end early)
RESET_TIME="${RESET_TIME:-60}"       # 1 min reset window (use → to skip early)
DATASET_NAME="${DATASET_NAME:-test-record}"

# Auto-increment version if dataset already exists
CACHE_DIR="$HOME/.cache/huggingface/lerobot/Grievous-Robot"
VERSION=$REQUESTED_VERSION

while [ -d "$CACHE_DIR/${DATASET_NAME}-v${VERSION}" ]; do
    echo "⚠️  Dataset ${DATASET_NAME}-v${VERSION} already exists locally"
    VERSION=$((VERSION + 1))
done

if [ $VERSION -ne $REQUESTED_VERSION ]; then
    echo "✓ Auto-incremented to version ${VERSION} (next available)"
    echo ""
fi

# Display recording configuration
echo "============================================================================"
echo "GRIEVOUS ROBOT RECORDING SESSION"
echo "============================================================================"
echo "Dataset:     Grievous-Robot/${DATASET_NAME}-v${VERSION}"
echo "Task:        ${TASK}"
echo "Episodes:    ${EPISODES} (max)"
echo "Episode Max: ${EPISODE_TIME}s (press → to end early)"
echo "Reset Max:   ${RESET_TIME}s (press → to skip early)"
echo "============================================================================"
echo ""
echo "KEYBOARD CONTROLS:"
echo "  →  (Right Arrow)  - End episode and save / Skip reset"
echo "  ←  (Left Arrow)   - Discard episode and re-record"
echo "  Esc               - Stop recording and exit"
echo ""
echo "============================================================================"
echo "Starting in 3 seconds..."
echo "============================================================================"
sleep 3

# Run recording
lerobot-record \
    --robot.type=grievous_client \
    --robot.remote_ip=192.168.50.47 \
    --robot.cameras='{
        left_wrist: {type: opencv, index_or_path: /dev/video6, width: 640, height: 480, fps: 30},
        right_wrist: {type: opencv, index_or_path: /dev/video8, width: 640, height: 480, fps: 30},
        head: {type: intelrealsense, serial_number_or_name: 032622074046, width: 640, height: 480, fps: 30}
    }' \
    --teleop.type=grievous_leader \
    --teleop.left_arm_port=/dev/ttyACM3 \
    --teleop.right_arm_port=/dev/ttyACM2 \
    --teleop.remote_ip=192.168.50.47 \
    --teleop.port_zmq_cmd=5555 \
    --teleop.id=grievous_leader \
    --dataset.repo_id="Grievous-Robot/${DATASET_NAME}-v${VERSION}" \
    --dataset.num_episodes=${EPISODES} \
    --dataset.single_task="${TASK}" \
    --dataset.episode_time_s=${EPISODE_TIME} \
    --dataset.reset_time_s=${RESET_TIME} \
    --dataset.push_to_hub=true \
    --dataset.num_image_writer_threads_per_camera=4 \
    --display_data=true