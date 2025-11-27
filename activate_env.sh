#!/bin/bash
# Activation script for RunPod LeRobot environment
# Run this script after pod restart: source /workspace/activate_env.sh

# Activate conda
source /workspace/miniconda3/etc/profile.d/conda.sh
conda activate grievous

# Set environment variables
export TMPDIR=/workspace/tmp
export PIP_TEMP_DIR=/workspace/tmp
export PIP_CACHE_DIR=/workspace/.cache/pip
export HF_HOME=/workspace/.cache/huggingface
export HF_LEROBOT_HOME=/workspace/.cache/huggingface/lerobot
export TORCH_HOME=/workspace/.cache/torch
export TRITON_CACHE_DIR=/workspace/.cache/triton
export CUDA_VISIBLE_DEVICES=0

# Navigate to project directory
cd /workspace/Grievous

echo "=========================================="
echo "Environment activated successfully!"
echo "=========================================="
echo "  Conda env: grievous"
echo "  Python: $(python --version)"
echo "  PyTorch: $(python -c 'import torch; print(torch.__version__)')"
echo "  CUDA available: $(python -c 'import torch; print(torch.cuda.is_available())')"
echo "  Working directory: $(pwd)"
echo "=========================================="

