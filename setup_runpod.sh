#!/bin/bash
# RunPod Setup Script for LeRobot Training
# This script sets up the environment for training SmolVLA models on RunPod

set -e  # Exit on error

echo "=========================================="
echo "RunPod LeRobot Training Setup"
echo "=========================================="

# ============================================================================
# Cleanup Function
# ============================================================================
cleanup_storage() {
    echo ""
    echo "Performing storage cleanup..."
    
    # Show disk usage before cleanup
    echo "Disk usage before cleanup:"
    df -h /workspace 2>/dev/null || df -h /
    
    # Clean pip cache
    echo "Cleaning pip cache..."
    pip cache purge 2>/dev/null || true
    rm -rf /root/.cache/pip 2>/dev/null || true
    rm -rf /workspace/.cache/pip/* 2>/dev/null || true
    
    # Clean conda cache
    echo "Cleaning conda cache..."
    if command -v conda &> /dev/null; then
        conda clean -a -y 2>/dev/null || true
    fi
    if [ -d "/workspace/miniconda3/pkgs" ]; then
        rm -rf /workspace/miniconda3/pkgs/cache/* 2>/dev/null || true
    fi
    
    # Clean apt cache
    echo "Cleaning apt cache..."
    apt-get clean 2>/dev/null || true
    rm -rf /var/lib/apt/lists/* 2>/dev/null || true
    
    # Clean temporary files
    echo "Cleaning temporary files..."
    rm -rf /tmp/* 2>/dev/null || true
    rm -rf /workspace/tmp/* 2>/dev/null || true
    
    # Clean Python bytecode caches
    echo "Cleaning Python bytecode caches..."
    find /workspace -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find /workspace -type f -name "*.pyc" -delete 2>/dev/null || true
    find /workspace -type f -name "*.pyo" -delete 2>/dev/null || true
    
    # Clean system logs (if accessible)
    echo "Cleaning system logs..."
    journalctl --vacuum-time=1d 2>/dev/null || true
    
    # Clean old Miniconda installer if present
    echo "Cleaning old installers..."
    rm -f /workspace/Miniconda3-*.sh 2>/dev/null || true
    
    # Show disk usage after cleanup
    echo ""
    echo "Disk usage after cleanup:"
    df -h /workspace 2>/dev/null || df -h /
    
    echo "Cleanup completed."
}

# ============================================================================
# Step 1: Navigate to Workspace and Cleanup
# ============================================================================
echo ""
echo "Step 1: Navigating to /workspace and performing initial cleanup..."
cd /workspace
echo "Current directory: $(pwd)"

# Perform initial cleanup to free up space
cleanup_storage

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
# Step 7: Find Repository Directory
# ============================================================================
echo ""
echo "Step 7: Finding repository directory..."

# Try to find the repository directory
REPO_DIR=""

# First, check if we're already in the repo (script might be run from repo root)
if [ -f "pyproject.toml" ]; then
    REPO_DIR=$(pwd)
    echo "Found repository at current directory: $REPO_DIR"
# Check common locations
elif [ -f "/workspace/Grievous/pyproject.toml" ]; then
    REPO_DIR="/workspace/Grievous"
    echo "Found repository at: $REPO_DIR"
elif [ -f "/workspace/lerobot-xlerobot-integration/pyproject.toml" ]; then
    REPO_DIR="/workspace/lerobot-xlerobot-integration"
    echo "Found repository at: $REPO_DIR"
# Search in /workspace for any directory with pyproject.toml
else
    echo "Searching for repository in /workspace..."
    for dir in /workspace/*/; do
        if [ -f "${dir}pyproject.toml" ]; then
            REPO_DIR="$dir"
            echo "Found repository at: $REPO_DIR"
            break
        fi
    done
fi

# If still not found, check if script is in a repo directory
if [ -z "$REPO_DIR" ]; then
    SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
    if [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
        REPO_DIR="$SCRIPT_DIR"
        echo "Found repository at script location: $REPO_DIR"
    fi
fi

# Final check
if [ -z "$REPO_DIR" ] || [ ! -f "$REPO_DIR/pyproject.toml" ]; then
    echo "ERROR: Could not find repository directory with pyproject.toml"
    echo "Searched in:"
    echo "  - Current directory: $(pwd)"
    echo "  - /workspace/Grievous"
    echo "  - /workspace/lerobot-xlerobot-integration"
    echo "  - All subdirectories in /workspace"
    echo ""
    echo "Please either:"
    echo "  1. Clone the repository to /workspace/Grievous, or"
    echo "  2. Run this script from within the repository directory"
    exit 1
fi

# Navigate to repository directory
cd "$REPO_DIR"
echo "Changed to repository directory: $(pwd)"

# ============================================================================
# Step 8: Install Pillow in Conda Environment
# ============================================================================
echo ""
echo "Step 8: Installing Pillow in conda environment (Python 3.10 compatible)..."
echo "This ensures PIL is compiled for Python 3.10, avoiding conflicts with system Python 3.11 PIL..."

pip install --no-cache-dir Pillow

# Verify Pillow installation works correctly
echo "Verifying Pillow installation..."
if python -c "from PIL import Image; print(f'Pillow version: {Image.__version__}'); print('Pillow import successful')" 2>/dev/null; then
    echo "✓ Pillow is correctly installed and importable"
else
    echo "WARNING: Pillow installation verification failed. This may cause issues later."
    echo "Attempting to diagnose..."
    python -c "import sys; print('Python path:'); [print(f'  {p}') for p in sys.path]" 2>/dev/null || true
    python -c "import PIL; print(f'PIL location: {PIL.__file__}')" 2>/dev/null || true
fi

echo ""
echo "Pillow installation step completed."

# ============================================================================
# Step 9: Install LeRobot with SmolVLA Dependencies
# ============================================================================
echo ""
echo "Step 9: Installing LeRobot with SmolVLA dependencies..."
echo "This may take 15-30 minutes depending on network speed..."

pip install --no-cache-dir -e ".[smolvla]"

echo ""
echo "LeRobot installation completed."

# ============================================================================
# Step 10: Verify Installation
# ============================================================================
echo ""
echo "Step 10: Verifying installation..."

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
# Step 11: Update Activation Script
# ============================================================================
echo ""
echo "Step 11: Updating activation script with detected paths..."

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
# Step 12: Make Training Script Executable
# ============================================================================
echo ""
echo "Step 12: Making training script executable..."

# Get the repository directory (where this script is located)
REPO_DIR=$(cd "$(dirname "$0")" && pwd)

if [ -f "$REPO_DIR/train_grievous.sh" ]; then
    chmod +x "$REPO_DIR/train_grievous.sh"
    echo "Training script is now executable."
else
    echo "WARNING: train_grievous.sh not found at $REPO_DIR/train_grievous.sh"
fi

# ============================================================================
# Step 13: Final Cleanup
# ============================================================================
echo ""
echo "Step 13: Performing final cleanup to free up space..."
cleanup_storage

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
echo "   source activate_env.sh"
echo ""
echo "4. Run training:"
echo "   cd $REPO_DIR"
echo "   ./train_grievous.sh"
echo ""
echo "=========================================="

