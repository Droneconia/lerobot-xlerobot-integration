# Manual RunPod Setup Plan for LeRobot Training

## Overview
This document provides step-by-step instructions for manually setting up a fresh RunPod pod for training SmolVLA models with LeRobot. The pod comes with PyTorch 2.8, but LeRobot requires PyTorch <2.8.0, so we'll need to downgrade.

---

## Prerequisites
- Fresh RunPod pod with GPU access
- Network volume attached at `/workspace`
- SSH access to the pod
- HuggingFace token (from https://huggingface.co/settings/tokens)
- WandB token (from https://wandb.ai/settings)

---

## Step 1: Initial System Setup

### 1.1: Navigate to Workspace
```bash
cd /workspace
```

### 1.2: Install System Dependencies
Install all required system packages (based on Dockerfile.internal):

```bash
apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    build-essential \
    git \
    curl \
    libglib2.0-0 \
    libgl1-mesa-glx \
    libegl1-mesa \
    ffmpeg \
    libusb-1.0-0-dev \
    speech-dispatcher \
    libgeos-dev \
    portaudio19-dev \
    cmake \
    pkg-config \
    ninja-build \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
```

**Note**: If you get permission errors, you may need to use `sudo` or run as root.

### 1.3: Install Miniconda (if not already installed)
```bash
# Check if conda exists
which conda

# If not found, install Miniconda to /workspace (persistent location)
cd /workspace
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p /workspace/miniconda3
rm Miniconda3-latest-Linux-x86_64.sh

# Initialize conda for bash
/workspace/miniconda3/bin/conda init bash
source ~/.bashrc
```

---

## Step 2: Python Environment Setup

### 2.1: Create Conda Environment with Python 3.10
```bash
conda create -y -n grievous python=3.10
conda activate grievous
```

**Important**: LeRobot requires Python >=3.10,<3.11. The pod may come with Python 3.11 or 3.12, so we create a fresh 3.10 environment.

### 2.2: Install ffmpeg in Conda Environment
```bash
conda install -y ffmpeg -c conda-forge
```

**Why**: LeRobot uses ffmpeg for video processing. Installing via conda ensures compatibility and proper codec support.

### 2.3: Verify Python Version
```bash
python --version
# Should output: Python 3.10.x
```

---

## Step 3: Configure Environment Variables for Space Management

### 3.1: Set Temporary Directory to Network Volume
RunPod pods have limited container disk (5GB) but ample network volume space. Redirect all temporary files to the network volume:

```bash
# Create temporary directory on network volume
mkdir -p /workspace/tmp

# Set environment variables (add to ~/.bashrc for persistence)
export TMPDIR=/workspace/tmp
export PIP_TEMP_DIR=/workspace/tmp
export PIP_CACHE_DIR=/workspace/.cache/pip

# Also set HuggingFace cache location
export HF_HOME=/workspace/.cache/huggingface
export HF_LEROBOT_HOME=/workspace/.cache/huggingface/lerobot
export TORCH_HOME=/workspace/.cache/torch
export TRITON_CACHE_DIR=/workspace/.cache/triton

# Make these persistent
cat >> ~/.bashrc << 'EOF'
export TMPDIR=/workspace/tmp
export PIP_TEMP_DIR=/workspace/tmp
export PIP_CACHE_DIR=/workspace/.cache/pip
export HF_HOME=/workspace/.cache/huggingface
export HF_LEROBOT_HOME=/workspace/.cache/huggingface/lerobot
export TORCH_HOME=/workspace/.cache/torch
export TRITON_CACHE_DIR=/workspace/.cache/triton
EOF

# Reload bashrc
source ~/.bashrc
```

**Why**: Prevents "No space left on device" errors during package installation by using the persistent network volume instead of ephemeral container disk.

---

## Step 4: Downgrade PyTorch (Critical)

### 4.1: Check Current PyTorch Version
```bash
python -c "import torch; print(f'PyTorch version: {torch.__version__}')"
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
```

**Expected**: PyTorch 2.8.x (too new for LeRobot)

### 4.2: Uninstall Current PyTorch
```bash
pip uninstall -y torch torchvision torchaudio
```

### 4.3: Install Compatible PyTorch Version
LeRobot requires `torch>=2.2.1,<2.8.0`. Install PyTorch 2.4.0 with CUDA 12.1 support:

```bash
# Install PyTorch 2.4.0 with CUDA 12.1
pip install --no-cache-dir torch==2.4.0 torchvision==0.19.0 --index-url https://download.pytorch.org/whl/cu121
```

**Alternative**: If your pod has CUDA 12.4, you can try:
```bash
pip install --no-cache-dir torch==2.4.0 torchvision==0.19.0 --index-url https://download.pytorch.org/whl/cu124
```

**Note**: The `--no-cache-dir` flag prevents pip from using the default cache location on the ephemeral disk.

### 4.4: Verify PyTorch Installation
```bash
python -c "import torch; print(f'PyTorch version: {torch.__version__}')"
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
python -c "import torch; print(f'CUDA device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"No GPU\"}')"
```

**Expected Output**:
- PyTorch version: 2.4.0+cu121 (or similar)
- CUDA available: True
- CUDA device: NVIDIA GeForce RTX 4090 (or your GPU name)

---

## Step 5: Clone and Install LeRobot Repository

### 5.1: Navigate to Workspace
```bash
cd /workspace
```

### 5.2: Clone Your Fork (Grievous Repository)
```bash
# If using SSH
git clone git@github.com:alexkoven/lerobot-xlerobot-integration.git Grievous

# OR if using HTTPS
git clone https://github.com/alexkoven/lerobot-xlerobot-integration.git Grievous

cd Grievous
```

**Note**: Replace `alexkoven/lerobot-xlerobot-integration` with your actual repository path.

### 5.3: Install LeRobot with SmolVLA Dependencies
Install in editable mode with `[smolvla]` extras:

```bash
# Ensure we're in the grievous conda environment
conda activate grievous

# Install with smolvla extras (includes transformers, accelerate, safetensors, num2words)
pip install --no-cache-dir -e ".[smolvla]"
```

**What this installs**:
- Core LeRobot dependencies (datasets, diffusers, huggingface-hub, accelerate, etc.)
- PyTorch (already installed, but pip will verify compatibility)
- WandB (for experiment tracking)
- SmolVLA-specific dependencies:
  - `transformers>=4.53.0,<5.0.0`
  - `num2words>=0.5.14,<0.6.0`
  - `accelerate>=1.7.0,<2.0.0`
  - `safetensors>=0.4.3,<1.0.0`

**Installation Time**: 15-30 minutes depending on network speed.

**Troubleshooting**: If you encounter "No space left on device":
1. Verify `TMPDIR` is set: `echo $TMPDIR` (should be `/workspace/tmp`)
2. Check disk space: `df -h /workspace` and `df -h /tmp`
3. Clean pip cache: `pip cache purge`
4. Try installing in smaller batches (see Step 5.4)

### 5.4: Alternative Installation (If Space Issues Persist)
If you still hit space issues, install dependencies in batches:

```bash
# First, install core dependencies
pip install --no-cache-dir setuptools wheel packaging

# Then install PyTorch (if not already done)
pip install --no-cache-dir torch==2.4.0 torchvision==0.19.0 --index-url https://download.pytorch.org/whl/cu121

# Install HuggingFace ecosystem
pip install --no-cache-dir "datasets>=4.0.0,<4.2.0" "huggingface-hub[hf-transfer,cli]>=0.34.2,<0.36.0" "accelerate>=1.10.0,<2.0.0"

# Install transformers (required for smolvla)
pip install --no-cache-dir "transformers>=4.53.0,<5.0.0"

# Install other core dependencies
pip install --no-cache-dir "diffusers>=0.27.2,<0.36.0" "einops>=0.8.0,<0.9.0" "opencv-python-headless>=4.9.0,<4.13.0"

# Install smolvla-specific extras
pip install --no-cache-dir "num2words>=0.5.14,<0.6.0" "safetensors>=0.4.3,<1.0.0"

# Install WandB
pip install --no-cache-dir "wandb>=0.20.0,<0.22.0"

# Finally, install the rest of LeRobot in editable mode
pip install --no-cache-dir -e .
```

---

## Step 6: Verify Installation

### 6.1: Check LeRobot Installation
```bash
python -c "import lerobot; print(f'LeRobot version: {lerobot.__version__}')"
```

### 6.2: Check SmolVLA Dependencies
```bash
python -c "import transformers; print(f'Transformers version: {transformers.__version__}')"
python -c "import accelerate; print(f'Accelerate version: {accelerate.__version__}')"
python -c "import wandb; print(f'WandB version: {wandb.__version__}')"
python -c "import safetensors; print('Safetensors installed')"
python -c "import num2words; print('Num2words installed')"
```

### 6.3: Verify Training Script is Available
```bash
lerobot-train --help
```

Should show the training script help menu.

### 6.4: Check GPU Access
```bash
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU count: {torch.cuda.device_count()}'); print(f'GPU name: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')"
```

---

## Step 7: Set Up HuggingFace Authentication

### 7.1: Login to HuggingFace
```bash
huggingface-cli login
```

**What to do**:
1. When prompted, paste your HuggingFace token
2. Token can be found at: https://huggingface.co/settings/tokens
3. Create a token with "read" and "write" permissions if you don't have one

### 7.2: Verify HuggingFace Login
```bash
huggingface-cli whoami
```

Should display your HuggingFace username.

### 7.3: Test Dataset Access (Optional)
```bash
# Test accessing your dataset
python -c "from datasets import load_dataset; ds = load_dataset('Grievous-Robot/test-record-v14', split='train', streaming=True); print('Dataset accessible:', next(iter(ds)) is not None)"
```

Replace `Grievous-Robot/test-record-v14` with your actual dataset repository ID.

---

## Step 8: Set Up WandB Authentication

### 8.1: Login to WandB
```bash
wandb login
```

**What to do**:
1. When prompted, paste your WandB API key
2. API key can be found at: https://wandb.ai/settings
3. Copy the API key from the "API keys" section

### 8.2: Verify WandB Login
```bash
wandb whoami
```

Should display your WandB username and entity.

### 8.3: Test WandB (Optional)
```bash
python -c "import wandb; wandb.init(mode='disabled'); print('WandB initialized successfully')"
```

---

## Step 9: Set Up Training Script

### 9.1: Navigate to Repository
```bash
cd /workspace/Grievous
```

### 9.2: Make Training Script Executable
```bash
chmod +x train_grievous.sh
```

### 9.3: Verify Script is Ready
```bash
ls -la train_grievous.sh
cat train_grievous.sh | head -20
```

---

## Step 10: Create Persistent Startup Script

Since RunPod pods reset their environment on restart, create a startup script to quickly restore your environment:

### 10.1: Create Setup Script
```bash
cat > /workspace/setup_env.sh << 'EOF'
#!/bin/bash
# Persistent environment setup script for RunPod

# Activate conda environment
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

echo "Environment activated:"
echo "  - Conda env: grievous"
echo "  - Python: $(python --version)"
echo "  - PyTorch: $(python -c 'import torch; print(torch.__version__)')"
echo "  - CUDA available: $(python -c 'import torch; print(torch.cuda.is_available())')"
echo "  - Working directory: $(pwd)"
EOF

chmod +x /workspace/setup_env.sh
```

### 10.2: Usage After Pod Restart
After restarting the pod, simply run:
```bash
source /workspace/setup_env.sh
```

This will:
- Activate the conda environment
- Set all necessary environment variables
- Navigate to the project directory
- Display environment status

---

## Step 11: Final Verification

### 11.1: Complete Environment Check
Run a comprehensive check:

```bash
# Activate environment
source /workspace/setup_env.sh

# Check Python
python --version
# Expected: Python 3.10.x

# Check PyTorch
python -c "import torch; print(f'PyTorch: {torch.__version__}'); print(f'CUDA: {torch.cuda.is_available()}'); print(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')"
# Expected: PyTorch 2.4.0+cu121, CUDA: True, GPU: [Your GPU name]

# Check LeRobot
python -c "import lerobot; print(f'LeRobot: {lerobot.__version__}')"

# Check SmolVLA dependencies
python -c "import transformers, accelerate, wandb, safetensors, num2words; print('All SmolVLA dependencies installed')"

# Check HuggingFace
huggingface-cli whoami

# Check WandB
wandb whoami

# Check training script
lerobot-train --help | head -5
```

### 11.2: Quick Training Test (Optional)
Run a minimal verification training run:

```bash
cd /workspace/Grievous
./train_grievous.sh
# Select option 1 (verify_setup)
```

This will run 10 steps to verify everything works.

---

## Step 12: Clean Up (Optional)

### 12.1: Remove Installation Artifacts
After successful installation, you can clean up:

```bash
# Remove pip cache (if you want to free space)
pip cache purge

# Remove conda package cache
conda clean --all -y

# Remove temporary installation files
rm -rf /workspace/tmp/*  # Be careful - only if installation is complete
```

**Note**: Keep `/workspace/tmp` directory itself, as it's used for runtime temporary files.

---

## Troubleshooting

### Issue: "No space left on device" during pip install
**Solution**:
1. Verify `TMPDIR` is set: `echo $TMPDIR` (should be `/workspace/tmp`)
2. Check space: `df -h /workspace` and `df -h /tmp`
3. Clean caches: `pip cache purge && conda clean --all -y`
4. Install with `--no-cache-dir` flag
5. Install dependencies in smaller batches (see Step 5.4)

### Issue: PyTorch CUDA not available
**Solution**:
1. Check GPU is attached: `nvidia-smi`
2. Verify CUDA version: `nvcc --version`
3. Reinstall PyTorch with matching CUDA version
4. Check CUDA_VISIBLE_DEVICES: `echo $CUDA_VISIBLE_DEVICES`

### Issue: Conda environment not found after restart
**Solution**:
1. Use the persistent startup script: `source /workspace/setup_env.sh`
2. Or manually activate: `source /workspace/miniconda3/etc/profile.d/conda.sh && conda activate grievous`

### Issue: HuggingFace/WandB authentication lost
**Solution**:
1. Re-run `huggingface-cli login`
2. Re-run `wandb login`
3. Tokens are stored in `~/.cache/huggingface/` and `~/.netrc` (should persist on network volume)

### Issue: Import errors for LeRobot modules
**Solution**:
1. Verify installation: `pip list | grep lerobot`
2. Reinstall in editable mode: `pip install -e ".[smolvla]"`
3. Check you're in the correct directory: `pwd` should show `/workspace/Grievous`
4. Verify Python path: `python -c "import sys; print(sys.path)"`

---

## Summary Checklist

- [ ] System dependencies installed
- [ ] Miniconda installed to `/workspace`
- [ ] Conda environment `grievous` created with Python 3.10
- [ ] ffmpeg installed in conda environment
- [ ] Environment variables set (TMPDIR, HF_HOME, etc.)
- [ ] PyTorch downgraded to 2.4.0 with CUDA support
- [ ] LeRobot repository cloned to `/workspace/Grievous`
- [ ] LeRobot installed with `[smolvla]` extras
- [ ] HuggingFace authenticated
- [ ] WandB authenticated
- [ ] Training script (`train_grievous.sh`) is executable
- [ ] Persistent startup script created (`/workspace/setup_env.sh`)
- [ ] All verifications passed
- [ ] Quick test run successful (optional)

---

## Next Steps

After completing this setup:

1. **Run Training**: Use `./train_grievous.sh` to start training
2. **Monitor**: Check WandB dashboard for training progress
3. **Checkpoints**: Checkpoints saved to `/workspace/outputs/smolvla_finetuned/checkpoints/`
4. **Model Push**: Final model automatically pushed to HuggingFace Hub (if `PUSH_TO_HUB=true`)

---

## Notes

- **Persistence**: Everything in `/workspace` persists across pod restarts
- **Container Disk**: Limited to 5GB, use `/workspace` for all data
- **Environment**: Always run `source /workspace/setup_env.sh` after pod restart
- **GPU**: Verify GPU access with `nvidia-smi` and `torch.cuda.is_available()`
- **Space Management**: Keep an eye on `/workspace` disk usage, clean old checkpoints if needed

