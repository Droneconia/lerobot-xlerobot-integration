#!/bin/bash

# Grievous Robot Visualization Script
# Organization: Grievous-Robot (https://huggingface.co/Grievous-Robot)
# 
# ============================================================================
# USAGE:
# ============================================================================
#   ./visualize_grievous.sh                                    # Use defaults
#   DATASET_NAME="pick-place" VERSION=1 EPISODE=0 ./visualize_grievous.sh
#
# Environment Variables:
#   DATASET_NAME - Base dataset name (default: min-dataset)
#   VERSION      - Dataset version number (default: 1)
#   EPISODE      - Episode index to visualize (default: 0)
#   MODE         - Visualization mode: 'local' or 'distant' (default: local)
#   SAVE         - Save .rrd file instead of opening viewer: 0 or 1 (default: 0)
#   OUTPUT_DIR   - Directory to save .rrd file when SAVE=1 (default: ./visualizations)
#   BATCH_SIZE   - Batch size for DataLoader (default: 32)
#   NUM_WORKERS  - Number of DataLoader workers (default: 4)
#   VIDEO_BACKEND - Video decoder: 'pyav', 'torchcodec', or 'video_reader' (default: pyav)
#
# Note: If a dataset with the specified VERSION doesn't exist locally, it will be
#       downloaded from Hugging Face Hub.
#
# Example:
#   DATASET_NAME="pick-place" \
#   VERSION=1 \
#   EPISODE=5 \
#   ./visualize_grievous.sh
#
#   This visualizes: Grievous-Robot/pick-place-v1, episode 5
#
# Example (save .rrd file):
#   DATASET_NAME="pick-place" \
#   VERSION=1 \
#   EPISODE=0 \
#   SAVE=1 \
#   OUTPUT_DIR="./saved_viz" \
#   ./visualize_grievous.sh
#
#   This saves: ./saved_viz/lerobot_Grievous-Robot_pick-place-v1_episode_0.rrd
# ============================================================================

# Configuration
DATASET_NAME="${DATASET_NAME:-min-dataset}"
VERSION="${VERSION:-2}"
EPISODE="${EPISODE:-0}"
MODE="${MODE:-local}"
SAVE="${SAVE:-0}"
OUTPUT_DIR="${OUTPUT_DIR:-./visualizations}"
BATCH_SIZE="${BATCH_SIZE:-32}"
NUM_WORKERS="${NUM_WORKERS:-4}"
VIDEO_BACKEND="${VIDEO_BACKEND:-pyav}"

# Build full dataset repo ID
REPO_ID="Grievous-Robot/${DATASET_NAME}-v${VERSION}"

# Display visualization configuration
echo "============================================================================"
echo "GRIEVOUS ROBOT DATASET VISUALIZATION"
echo "============================================================================"
echo "Dataset:     ${REPO_ID}"
echo "Episode:     ${EPISODE}"
echo "Mode:        ${MODE}"
echo "Save .rrd:   ${SAVE}"
if [ "${SAVE}" = "1" ]; then
    echo "Output Dir:  ${OUTPUT_DIR}"
fi
echo "Batch Size:  ${BATCH_SIZE}"
echo "Workers:     ${NUM_WORKERS}"
echo "Video Backend: ${VIDEO_BACKEND}"
echo "============================================================================"
echo ""

# Create output directory if saving
if [ "${SAVE}" = "1" ]; then
    mkdir -p "${OUTPUT_DIR}"
    echo "Output directory: ${OUTPUT_DIR}"
    echo ""
fi

# Build command arguments
CMD_ARGS=(
    --repo-id "${REPO_ID}"
    --episode-index "${EPISODE}"
    --batch-size "${BATCH_SIZE}"
    --num-workers "${NUM_WORKERS}"
    --mode "${MODE}"
    --video-backend "${VIDEO_BACKEND}"
    --static 1
)

# Add save-specific arguments
if [ "${SAVE}" = "1" ]; then
    CMD_ARGS+=(
        --save 1
        --output-dir "${OUTPUT_DIR}"
    )
fi

# Run visualization
echo "Starting visualization..."
echo "============================================================================"
lerobot-dataset-viz "${CMD_ARGS[@]}"

