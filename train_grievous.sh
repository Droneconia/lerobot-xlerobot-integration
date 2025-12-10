#!/bin/bash
# Training script for Grievous Robot SmolVLA finetuning
# Organization: Grievous-Robot
# Dataset: min-dataset-v10

set -e  # Exit on error

# ============================================================================
# Environment Variables (only what libraries actually use)
# ============================================================================
export HF_HOME=/workspace/.cache/huggingface
export CUDA_VISIBLE_DEVICES=0

# ============================================================================
# Configuration Variables
# ============================================================================
ORG_NAME="Grievous-Robot"
DATASET_NAME="min-dataset-v10"
DATASET_REPO_ID="${ORG_NAME}/${DATASET_NAME}"

# Training parameters
BATCH_SIZE=64
STEPS=20000
LEARNING_RATE=1e-4
OUTPUT_DIR="/workspace/outputs/smolvla_finetuned"
JOB_NAME="smolvla_grievous_20k"

# Checkpoint management (to save space on 20GB volume)
# With 20GB volume, we save less frequently and keep only recent checkpoints
SAVE_FREQ=5000  # Save every 5000 steps (4 checkpoints total instead of 10)
KEEP_CHECKPOINTS=2  # Keep only last 2 checkpoints locally (delete older ones)

# WandB configuration
WANDB_PROJECT="smolvla-finetuning"
WANDB_ENABLE=true

# Model configuration
POLICY_PATH="lerobot/smolvla_base"
POLICY_REPO_ID="${ORG_NAME}/smolvla_finetuned"
PUSH_TO_HUB=true

# ============================================================================
# Functions
# ============================================================================

# Quick verification run (10 steps, ~1 minute)
verify_setup() {
    echo "=========================================="
    echo "Running verification (10 steps)..."
    echo "=========================================="
    
    python src/lerobot/scripts/lerobot_train.py \
        --policy.path=${POLICY_PATH} \
        --dataset.repo_id=${DATASET_REPO_ID} \
        --batch_size=8 \
        --steps=10 \
        --output_dir=/workspace/outputs/verify \
        --job_name=verify_setup \
        --policy.device=cuda \
        --optimizer.lr=${LEARNING_RATE} \
        --num_workers=2 \
        --log_freq=5 \
        --save_checkpoint=false \
        --eval_freq=0 \
        --wandb.enable=false \
        --policy.push_to_hub=false \
        --rename_map='{"observation.images.left_wrist":"observation.images.camera1","observation.images.right_wrist":"observation.images.camera2","observation.images.head":"observation.images.camera3"}' \
        --seed=1000
    
    echo "✓ Verification complete!"
}

# Test training run (500 steps, ~15-30 minutes)
test_training() {
    echo "=========================================="
    echo "Running test training (500 steps)..."
    echo "=========================================="
    
    python src/lerobot/scripts/lerobot_train.py \
        --policy.path=${POLICY_PATH} \
        --dataset.repo_id=${DATASET_REPO_ID} \
        --batch_size=32 \
        --steps=500 \
        --output_dir=/workspace/outputs/test_run \
        --job_name=smolvla_test_500 \
        --policy.device=cuda \
        --optimizer.lr=${LEARNING_RATE} \
        --optimizer.grad_clip_norm=1.0 \
        --num_workers=4 \
        --save_freq=500 \
        --log_freq=50 \
        --eval_freq=0 \
        --wandb.enable=${WANDB_ENABLE} \
        --wandb.project=${WANDB_PROJECT} \
        --policy.push_to_hub=false \
        --rename_map='{"observation.images.left_wrist":"observation.images.camera1","observation.images.right_wrist":"observation.images.camera2","observation.images.head":"observation.images.camera3"}' \
        --seed=1000
    
    echo "✓ Test training complete!"
}

# Full training run (20k steps, ~4 hours)
full_training() {
    local run_in_background=$1
    
    # Check if output directory exists
    local final_output_dir="${OUTPUT_DIR}"
    local final_job_name="${JOB_NAME}"
    local resume_flag=""
    
    if [ -d "${OUTPUT_DIR}" ]; then
        echo "=========================================="
        echo "Output directory already exists: ${OUTPUT_DIR}"
        echo "=========================================="
        echo ""
        echo "What would you like to do?"
        echo "  1) Resume existing training (continue from checkpoint)"
        echo "  2) Create new directory with timestamp (start fresh)"
        echo "  3) Cancel"
        echo ""
        read -p "Enter option [1-3]: " dir_choice
        
        case "${dir_choice}" in
            1)
                echo "Resuming existing training..."
                resume_flag="--resume"
                # Check if there's a checkpoint to resume from
                if [ ! -d "${OUTPUT_DIR}/checkpoints" ] || [ -z "$(ls -A ${OUTPUT_DIR}/checkpoints 2>/dev/null)" ]; then
                    echo "WARNING: No checkpoints found in ${OUTPUT_DIR}/checkpoints"
                    echo "Cannot resume. Please choose option 2 to start fresh."
                    exit 1
                fi
                ;;
            2)
                # Create new directory with timestamp
                local timestamp=$(date +%Y%m%d_%H%M%S)
                final_output_dir="${OUTPUT_DIR}_${timestamp}"
                final_job_name="${JOB_NAME}_${timestamp}"
                echo "Creating new directory: ${final_output_dir}"
                ;;
            3)
                echo "Cancelled."
                exit 0
                ;;
            *)
                echo "Invalid option. Cancelled."
                exit 1
                ;;
        esac
    fi
    
    echo "=========================================="
    echo "Running full training (${STEPS} steps)..."
    echo "=========================================="
    echo "Dataset: ${DATASET_REPO_ID}"
    echo "Output: ${final_output_dir}"
    echo "WandB Project: ${WANDB_PROJECT}"
    if [ -n "${resume_flag}" ]; then
        echo "Mode: RESUME (continuing from checkpoint)"
    else
        echo "Mode: NEW RUN"
    fi
    echo "=========================================="
    
    # Build the training command
    local train_cmd="python src/lerobot/scripts/lerobot_train.py \
        --policy.path=${POLICY_PATH} \
        --dataset.repo_id=${DATASET_REPO_ID} \
        --batch_size=${BATCH_SIZE} \
        --steps=${STEPS} \
        --output_dir=${final_output_dir} \
        --job_name=${final_job_name} \
        ${resume_flag} \
        --policy.device=cuda \
        --optimizer.lr=${LEARNING_RATE} \
        --optimizer.weight_decay=0.0 \
        --optimizer.grad_clip_norm=1.0 \
        --num_workers=4 \
        --save_freq=${SAVE_FREQ} \
        --log_freq=100 \
        --eval_freq=0 \
        --wandb.enable=${WANDB_ENABLE} \
        --wandb.project=${WANDB_PROJECT} \
        --policy.repo_id=${POLICY_REPO_ID} \
        --policy.push_to_hub=${PUSH_TO_HUB} \
        --rename_map='{\"observation.images.left_wrist\":\"observation.images.camera1\",\"observation.images.right_wrist\":\"observation.images.camera2\",\"observation.images.head\":\"observation.images.camera3\"}' \
        --seed=1000"
    
    if [ "$run_in_background" = "true" ]; then
        # Create log directory
        local log_dir="${final_output_dir}/../training_logs"
        mkdir -p "$log_dir"
        local log_file="${log_dir}/training_$(date +%Y%m%d_%H%M%S).log"
        
        echo ""
        echo "Running training in background..."
        echo "Log file: ${log_file}"
        echo ""
        
        # Try to use screen if available (best option)
        if command -v screen &> /dev/null; then
            echo "Using 'screen' for background execution."
            echo "To attach later: screen -r training_smolvla"
            echo "To detach: Press Ctrl+A then D"
            echo ""
            screen -dmS training_smolvla bash -c "$train_cmd 2>&1 | tee ${log_file}"
            echo "Training started in screen session 'training_smolvla'"
            echo "View logs: tail -f ${log_file}"
        # Fallback to nohup if screen not available
        elif command -v nohup &> /dev/null; then
            echo "Using 'nohup' for background execution."
            echo "View logs: tail -f ${log_file}"
            echo ""
            nohup bash -c "$train_cmd" > "${log_file}" 2>&1 &
            local pid=$!
            echo "Training started in background (PID: $pid)"
            echo "Check status: ps aux | grep lerobot_train"
        else
            echo "WARNING: Neither 'screen' nor 'nohup' found. Running in background with &"
            echo "WARNING: Process may stop if you disconnect. Consider installing 'screen' or 'tmux'"
            bash -c "$train_cmd" > "${log_file}" 2>&1 &
            local pid=$!
            echo "Training started in background (PID: $pid)"
        fi
        
        echo ""
        echo "=========================================="
        echo "Background Training Started"
        echo "=========================================="
        echo "Monitor progress:"
        echo "  - Log file: tail -f ${log_file}"
        echo "  - WandB: https://wandb.ai (project: ${WANDB_PROJECT})"
        echo "  - GPU: watch -n 1 nvidia-smi"
        echo "  - Process: ps aux | grep lerobot_train"
        if command -v screen &> /dev/null; then
            echo ""
            echo "To attach to training session:"
            echo "  screen -r training_smolvla"
            echo "  (Press Ctrl+A then D to detach)"
        fi
        echo "=========================================="
    else
        # Run in foreground
        eval "$train_cmd"
        echo "✓ Full training complete!"
        
        # Clean up old checkpoints to save space (keep only last N)
        # Since push_to_hub only pushes final checkpoint, we keep recent ones for safety
        if [ -d "${final_output_dir}/checkpoints" ]; then
            echo ""
            echo "Cleaning up old checkpoints (keeping last ${KEEP_CHECKPOINTS})..."
            cd "${final_output_dir}/checkpoints"
            
            total=$(ls -1d */ 2>/dev/null | wc -l)
            if [ "${total}" -gt "${KEEP_CHECKPOINTS}" ]; then
                to_delete=$((total - KEEP_CHECKPOINTS))
                echo "Found ${total} checkpoints, deleting ${to_delete} oldest..."
                ls -1d */ | sort -V | head -n -${KEEP_CHECKPOINTS} | xargs rm -rf
                echo "✓ Cleanup complete: kept last ${KEEP_CHECKPOINTS} checkpoints"
            else
                echo "Only ${total} checkpoint(s), no cleanup needed"
            fi
            cd - > /dev/null
        fi
        
        echo ""
        echo "Model saved to: ${final_output_dir}"
        if [ "${PUSH_TO_HUB}" = "true" ]; then
            echo "Model pushed to Hub: ${POLICY_REPO_ID}"
        fi
    fi
}

# ============================================================================
# Main Execution
# ============================================================================

# Check if we're in the right directory
if [ ! -f "src/lerobot/scripts/lerobot_train.py" ]; then
    echo "Error: Must run from LeRobot repository root"
    echo "Current directory: $(pwd)"
    exit 1
fi

# Interactive menu
echo "=========================================="
echo "  Grievous Robot SmolVLA Training"
echo "=========================================="
echo ""
echo "Configuration:"
echo "  Organization: ${ORG_NAME}"
echo "  Dataset: ${DATASET_REPO_ID}"
echo "  WandB Project: ${WANDB_PROJECT}"
echo ""
echo "Select training option:"
echo "  1) Verify setup (10 steps, ~1 minute)"
echo "  2) Test training (500 steps, ~15-30 minutes)"
echo "  3) Full training (${STEPS} steps, ~4 hours)"
echo ""
read -p "Enter option [1-3]: " choice

# Ask about background execution for full training
RUN_IN_BACKGROUND="false"
if [ "${choice}" = "3" ]; then
    echo ""
    echo "Run training in background? (allows you to disconnect SSH)"
    echo "  y) Yes - run in background (recommended for long training)"
    echo "  n) No - run in foreground (see output in real-time)"
    echo ""
    read -p "Run in background? [y/N]: " bg_choice
    if [[ "$bg_choice" =~ ^[Yy]$ ]]; then
        RUN_IN_BACKGROUND="true"
    fi
fi

case "${choice}" in
    1)
        verify_setup
        ;;
    2)
        test_training
        ;;
    3)
        full_training "$RUN_IN_BACKGROUND"
        ;;
    *)
        echo ""
        echo "Invalid option. Please run the script again and choose 1, 2, or 3."
        exit 1
        ;;
esac

