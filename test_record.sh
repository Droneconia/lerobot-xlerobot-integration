#!/bin/bash

# Grievous Robot Recording Script (Advanced - Command-Based)
# Organization: Grievous-Robot (https://huggingface.co/Grievous-Robot)
# 
# ============================================================================
# RECORDING COMMANDS (ZMQ-Based):
# ============================================================================
# This script uses advanced_record which receives commands via ZMQ socket.
# Recording is controlled by sending commands to the robot host:
#
#   "start_recording" - Begin recording data to dataset
#   "stop_recording"  - Stop recording and save current episode
#
# To send commands, use a ZMQ PUSH socket to port 5557 (default):
#   python -c "import zmq; ctx=zmq.Context(); s=ctx.socket(zmq.PUSH); s.connect('tcp://192.168.50.148:5557'); s.send_string('start_recording')"
#
# Recording Flow:
#   1. Script starts and waits for "start_recording" command
#   2. Send "start_recording" to begin recording
#   3. Perform the task
#   4. Send "stop_recording" when done (saves episode automatically)
#   5. Repeat steps 2-4 for additional episodes
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
#   DATASET_NAME - Base dataset name (default: test-record)
#   PORT_CMD     - ZMQ port for recording commands (default: 5557)
#
# Note: If a dataset with the specified VERSION already exists locally, the script
#       will automatically increment to the next available version number.
#
# Example:
#   TASK="Pick red cube and place in blue box" \
#   VERSION=1 \
#   DATASET_NAME="pick-place" \
#   ./test_record.sh
#
#   This creates: Grievous-Robot/pick-place-v1
# ============================================================================

# Configuration
TASK="${TASK:-Test record}"
REQUESTED_VERSION="${VERSION:-1}"
DATASET_NAME="${DATASET_NAME:-test-record}"
PORT_CMD="${PORT_CMD:-5557}"  # ZMQ port for recording commands

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
echo "GRIEVOUS ROBOT RECORDING SESSION (Advanced - Command-Based)"
echo "============================================================================"
echo "Dataset:     Grievous-Robot/${DATASET_NAME}-v${VERSION}"
echo "Task:        ${TASK}"
echo "Command Port: ${PORT_CMD}"
echo "============================================================================"
echo ""
echo "RECORDING COMMANDS (send via ZMQ to port ${PORT_CMD}):"
echo "  start_recording - Begin recording data to dataset"
echo "  stop_recording  - Stop recording and save current episode"
echo ""
echo "Example command to start recording:"
echo "  python -c \"import zmq; ctx=zmq.Context(); s=ctx.socket(zmq.PUSH); s.connect('tcp://192.168.50.148:${PORT_CMD}'); s.send_string('start_recording')\""
echo ""
echo "============================================================================"
echo "Starting in 3 seconds..."
echo "============================================================================"
sleep 3

# Run recording
python -m lerobot.scripts.advanced_record \
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
    --dataset.single_task="${TASK}" \
    --dataset.push_to_hub=true \
    --dataset.num_image_writer_threads_per_camera=4 \
    --port_recording_cmd=${PORT_CMD} \
    --display_data=true