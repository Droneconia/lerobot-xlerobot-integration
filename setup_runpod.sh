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
# Step 6: Find and Link System PyTorch
# ============================================================================
echo ""
echo "Step 6: Finding system PyTorch installation..."

# Try to find PyTorch in various Python installations
TORCH_PATH=""
PYTHON_WITH_TORCH=""

# Check system python3
if python3 -c "import torch" 2>/dev/null; then
    PYTHON_WITH_TORCH="python3"
    TORCH_PATH=$(python3 -c "import torch; import os; print(os.path.dirname(os.path.dirname(torch.__file__)))" 2>/dev/null)
    echo "Found PyTorch in system python3: $TORCH_PATH"
# Check /usr/bin/python3
elif /usr/bin/python3 -c "import torch" 2>/dev/null; then
    PYTHON_WITH_TORCH="/usr/bin/python3"
    TORCH_PATH=$(/usr/bin/python3 -c "import torch; import os; print(os.path.dirname(os.path.dirname(torch.__file__)))" 2>/dev/null)
    echo "Found PyTorch in /usr/bin/python3: $TORCH_PATH"
# Check if there's a site-packages directory with torch
elif [ -d "/usr/local/lib/python3" ]; then
    for py_dir in /usr/local/lib/python3.*/site-packages; do
        if [ -d "$py_dir/torch" ]; then
            TORCH_PATH="$py_dir"
            echo "Found PyTorch in: $TORCH_PATH"
            break
        fi
    done
fi

# If we found PyTorch, add it to PYTHONPATH
if [ -n "$TORCH_PATH" ] && [ -d "$TORCH_PATH" ]; then
    echo "Adding PyTorch path to PYTHONPATH: $TORCH_PATH"
    export PYTHONPATH="$TORCH_PATH:$PYTHONPATH"
    
    # Verify it works
    if python -c "import torch; print(f'PyTorch version: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')" 2>/dev/null; then
        echo "✓ PyTorch is now accessible from conda environment"
    else
        echo "WARNING: PyTorch path added but still not accessible. May need to check dependencies."
    fi
else
    echo "ERROR: Could not find PyTorch installation."
    echo "Checking if PyTorch exists in any Python installation..."
    python3 -c "import torch; print('PyTorch found in python3')" 2>/dev/null || echo "  - Not in python3"
    /usr/bin/python3 -c "import torch; print('PyTorch found in /usr/bin/python3')" 2>/dev/null || echo "  - Not in /usr/bin/python3"
    echo ""
    echo "You may need to install PyTorch manually or check the container image documentation."
fi

# ============================================================================
# Step 7: Install LeRobot with SmolVLA Dependencies
# ============================================================================
echo ""
echo "Step 7: Installing LeRobot with SmolVLA dependencies..."
echo "This may take 15-30 minutes depending on network speed..."

# Ensure we're in the repository directory
if [ ! -f "pyproject.toml" ]; then
    echo "ERROR: pyproject.toml not found. Make sure you're running this script from the repository root."
    exit 1
fi

pip install --no-cache-dir -e ".[smolvla]"

echo ""
echo "LeRobot installation completed."

# ============================================================================
# Step 8: Verify Installation
# ============================================================================
echo ""
echo "Step 8: Verifying installation..."

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
# Step 9: Update Activation Script
# ============================================================================
echo ""
echo "Step 9: Updating activation script with detected paths..."

# Get the repository directory (where this script is located)
REPO_DIR=$(cd "$(dirname "$0")" && pwd)

# Find PyTorch path for activation script
ACTIVATION_TORCH_PATH=""
if python3 -c "import torch" 2>/dev/null; then
    ACTIVATION_TORCH_PATH=$(python3 -c "import torch; import os; print(os.path.dirname(os.path.dirname(torch.__file__)))" 2>/dev/null)
elif /usr/bin/python3 -c "import torch" 2>/dev/null; then
    ACTIVATION_TORCH_PATH=$(/usr/bin/python3 -c "import torch; import os; print(os.path.dirname(os.path.dirname(torch.__file__)))" 2>/dev/null)
fi

# Update activate_env.sh in the repository
ACTIVATE_SCRIPT="$REPO_DIR/activate_env.sh"
if [ -f "$ACTIVATE_SCRIPT" ]; then
    echo "Updating existing activate_env.sh with detected paths..."
    
    # Update the script with detected paths
    cat > "$ACTIVATE_SCRIPT" << EOF
#!/bin/bash
# Activation script for RunPod LeRobot environment
# Run this script after pod restart: source activate_env.sh

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

# Add system PyTorch to PYTHONPATH if found
if [ -n "${ACTIVATION_TORCH_PATH}" ] && [ -d "${ACTIVATION_TORCH_PATH}" ]; then
    export PYTHONPATH="${ACTIVATION_TORCH_PATH}:\$PYTHONPATH"
fi

# Navigate to project directory
cd "${REPO_DIR}"

echo "=========================================="
echo "Environment activated successfully!"
echo "=========================================="
echo "  Conda env: grievous"
echo "  Python: \$(python --version)"
echo "  PyTorch: \$(python -c 'import torch; print(torch.__version__)' 2>/dev/null || echo 'Not found')"
echo "  CUDA available: \$(python -c 'import torch; print(torch.cuda.is_available())' 2>/dev/null || echo 'N/A')"
echo "  Working directory: \$(pwd)"
echo "=========================================="
EOF
    
    chmod +x "$ACTIVATE_SCRIPT"
    echo "Activation script updated at $ACTIVATE_SCRIPT"
else
    echo "WARNING: activate_env.sh not found in repository at $ACTIVATE_SCRIPT"
    echo "You may need to create it manually or it will be created on first setup."
fi

# ============================================================================
# Step 10: Make Training Script Executable
# ============================================================================
echo ""
echo "Step 10: Making training script executable..."

# Get the repository directory (where this script is located)
REPO_DIR=$(cd "$(dirname "$0")" && pwd)

if [ -f "$REPO_DIR/train_grievous.sh" ]; then
    chmod +x "$REPO_DIR/train_grievous.sh"
    echo "Training script is now executable."
else
    echo "WARNING: train_grievous.sh not found at $REPO_DIR/train_grievous.sh"
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
echo "   cd $REPO_DIR"
echo "   ./train_grievous.sh"
echo ""
echo "=========================================="

