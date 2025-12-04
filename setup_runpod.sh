#!/bin/bash
# RunPod Setup Script for LeRobot Training
# This script sets up the environment for training SmolVLA models on RunPod

set -e  # Exit on error

echo "=========================================="
echo "RunPod LeRobot Training Setup"
echo "=========================================="

# ============================================================================
# Step 1: Navigate to Workspace
# ============================================================================
echo ""
echo "Step 1: Navigating to /workspace..."
cd /workspace
echo "Current directory: $(pwd)"

# ============================================================================
# Step 2: Install Miniconda
# ============================================================================
echo ""
echo "Step 2: Installing Miniconda to /workspace..."
if [ -d "/workspace/miniconda3" ]; then
    echo "Miniconda already exists at /workspace/miniconda3, skipping installation."
else
    wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
    bash Miniconda3-latest-Linux-x86_64.sh -b -p /workspace/miniconda3
    rm Miniconda3-latest-Linux-x86_64.sh
    echo "Miniconda installed successfully."
fi

# ============================================================================
# Step 3: Create Conda Environment
# ============================================================================
echo ""
echo "Step 3: Creating conda environment 'grievous' with Python 3.10..."

# Source conda to use it in this script
source /workspace/miniconda3/etc/profile.d/conda.sh

# Accept conda Terms of Service (required for default channels)
echo "Accepting conda Terms of Service..."
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main || true
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r || true

# Create environment if it doesn't exist
# Use --system-site-packages to access system-installed PyTorch
if conda env list | grep -q "grievous"; then
    echo "Conda environment 'grievous' already exists, skipping creation."
    echo "Note: If environment was created without --system-site-packages, you may need to recreate it."
else
    conda create -y -n grievous python=3.10 --system-site-packages
    echo "Conda environment 'grievous' created successfully with system site-packages access."
fi

# Activate environment
conda activate grievous
echo "Conda environment activated."

# ============================================================================
# Step 4: Install ffmpeg
# ============================================================================
echo ""
echo "Step 4: Installing ffmpeg in conda environment..."
conda install -y ffmpeg -c conda-forge
echo "ffmpeg installed successfully."

# Verify Python version
echo ""
echo "Python version: $(python --version)"

# ============================================================================
# Step 5: Configure Environment Variables
# ============================================================================
echo ""
echo "Step 5: Configuring environment variables for space management..."

# Create temporary directory on network volume
mkdir -p /workspace/tmp
mkdir -p /workspace/.cache/pip
mkdir -p /workspace/.cache/huggingface
mkdir -p /workspace/.cache/torch

# Set environment variables for this session
export TMPDIR=/workspace/tmp
export PIP_TEMP_DIR=/workspace/tmp
export PIP_CACHE_DIR=/workspace/.cache/pip
export HF_HOME=/workspace/.cache/huggingface
export HF_LEROBOT_HOME=/workspace/.cache/huggingface/lerobot
export TORCH_HOME=/workspace/.cache/torch
export TRITON_CACHE_DIR=/workspace/.cache/triton
export CUDA_VISIBLE_DEVICES=0

echo "Environment variables set:"
echo "  TMPDIR=$TMPDIR"
echo "  PIP_CACHE_DIR=$PIP_CACHE_DIR"
echo "  HF_HOME=$HF_HOME"

# ============================================================================
# Step 6: Verify System PyTorch Access
# ============================================================================
echo ""
echo "Step 6: Verifying system PyTorch access..."

# Check if PyTorch is accessible from conda environment
if python -c "import torch; print(f'PyTorch version: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')" 2>/dev/null; then
    echo "✓ System PyTorch is accessible from conda environment"
else
    echo "WARNING: PyTorch not found in conda environment."
    echo "This may happen if the environment was created without --system-site-packages."
    echo "Checking system Python for PyTorch..."
    
    # Check system Python
    if python3 -c "import torch; print(torch.__version__)" 2>/dev/null; then
        SYSTEM_TORCH_VERSION=$(python3 -c "import torch; print(torch.__version__)" 2>/dev/null)
        echo "System Python has PyTorch: $SYSTEM_TORCH_VERSION"
        echo "To use system PyTorch, you may need to recreate the conda environment with --system-site-packages"
        echo "Or add system site-packages to PYTHONPATH manually"
    else
        echo "ERROR: PyTorch not found in system Python either."
        echo "You may need to install PyTorch manually."
    fi
fi

# ============================================================================
# Step 7: Clone Repository
# ============================================================================
echo ""
echo "Step 7: Cloning Grievous repository..."

if [ -d "/workspace/Grievous" ]; then
    echo "Repository already exists at /workspace/Grievous, skipping clone."
    echo "To update, run: cd /workspace/Grievous && git pull"
else
    git clone https://github.com/alexkoven/Grievous.git /workspace/Grievous
    echo "Repository cloned successfully."
fi

cd /workspace/Grievous
echo "Current directory: $(pwd)"

# ============================================================================
# Step 8: Install LeRobot with SmolVLA Dependencies
# ============================================================================
echo ""
echo "Step 8: Installing LeRobot with SmolVLA dependencies..."
echo "This may take 15-30 minutes depending on network speed..."

pip install --no-cache-dir -e ".[smolvla]"

echo ""
echo "LeRobot installation completed."

# ============================================================================
# Step 9: Verify Installation
# ============================================================================
echo ""
echo "Step 9: Verifying installation..."

echo "Checking LeRobot..."
python -c "import lerobot; print(f'LeRobot version: {lerobot.__version__}')" || echo "WARNING: LeRobot import failed"

echo ""
echo "Checking SmolVLA dependencies..."
python -c "import transformers; print(f'Transformers: {transformers.__version__}')" || echo "WARNING: Transformers import failed"
python -c "import accelerate; print(f'Accelerate: {accelerate.__version__}')" || echo "WARNING: Accelerate import failed"
python -c "import wandb; print(f'WandB: {wandb.__version__}')" || echo "WARNING: WandB import failed"
python -c "import safetensors; print('Safetensors: OK')" || echo "WARNING: Safetensors import failed"
python -c "import num2words; print('Num2words: OK')" || echo "WARNING: Num2words import failed"

echo ""
echo "Checking training script..."
lerobot-train --help | head -5 || echo "WARNING: lerobot-train command not found"

echo ""
echo "Checking GPU access..."
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU count: {torch.cuda.device_count()}'); print(f'GPU name: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')"

# ============================================================================
# Step 10: Create Activation Script
# ============================================================================
echo ""
echo "Step 10: Creating activation script..."

cat > /workspace/activate_env.sh << 'EOF'
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
EOF

chmod +x /workspace/activate_env.sh
echo "Activation script created at /workspace/activate_env.sh"

# ============================================================================
# Step 11: Make Training Script Executable
# ============================================================================
echo ""
echo "Step 11: Making training script executable..."

if [ -f "/workspace/Grievous/train_grievous.sh" ]; then
    chmod +x /workspace/Grievous/train_grievous.sh
    echo "Training script is now executable."
else
    echo "WARNING: train_grievous.sh not found at /workspace/Grievous/train_grievous.sh"
fi

# ============================================================================
# Summary
# ============================================================================
echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Authenticate with HuggingFace:"
echo "   huggingface-cli login"
echo ""
echo "2. Authenticate with WandB:"
echo "   wandb login"
echo ""
echo "3. After pod restart, activate environment:"
echo "   source /workspace/activate_env.sh"
echo ""
echo "4. Run training:"
echo "   cd /workspace/Grievous"
echo "   ./train_grievous.sh"
echo ""
echo "=========================================="

