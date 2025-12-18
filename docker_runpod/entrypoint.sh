#!/bin/bash
# Entrypoint for self-contained LeRobot training environment
# Features:
# - Direct SSH access (fast, no gateway lag)
# - HuggingFace & WandB auto-authentication
# - Conda environment auto-activation
# - Workspace-based workflow

set -e

echo "=========================================="
echo "LeRobot Training Environment"
echo "Self-Contained | /workspace Workflow"
echo "=========================================="

# Setup SSH authorized keys from environment variable (injected at runtime)
if [ -n "$SSH_PUBLIC_KEY" ]; then
    echo "Setting up SSH authorized keys..."
    echo "$SSH_PUBLIC_KEY" > /root/.ssh/authorized_keys
    chmod 600 /root/.ssh/authorized_keys
    echo "✓ SSH public key configured"
else
    echo "⚠ SSH_PUBLIC_KEY not set - direct SSH will not work"
    echo "  Set SSH_PUBLIC_KEY environment variable in RunPod template"
fi

# Start SSH daemon for direct access (port 22)
echo "Starting SSH daemon..."
/usr/sbin/sshd
echo "✓ SSH daemon started (port 22 for direct access)"

# Initialize conda for this shell session
source /opt/conda/etc/profile.d/conda.sh

# Activate the grievous conda environment
echo "Activating conda environment: grievous"
conda activate grievous
echo "✓ Conda environment activated"

# Auto-authenticate HuggingFace if token provided
if [ -n "$HF_TOKEN" ]; then
    echo "Authenticating with HuggingFace..."
    huggingface-cli login --token "$HF_TOKEN" --add-to-git-credential 2>/dev/null || \
    hf auth login --token "$HF_TOKEN" --add-to-git-credential
    
    # Also copy token to ~/.cache for CLI compatibility
    mkdir -p ~/.cache/huggingface
    cp /workspace/.cache/huggingface/token ~/.cache/huggingface/token 2>/dev/null || true
    
    echo "✓ HuggingFace authentication complete"
else
    echo "⚠ HF_TOKEN not set - skipping HuggingFace authentication"
fi

# Auto-authenticate WandB if API key provided
if [ -n "$WANDB_API_KEY" ]; then
    echo "Authenticating with WandB..."
    wandb login "$WANDB_API_KEY"
    echo "✓ WandB authentication complete"
else
    echo "⚠ WANDB_API_KEY not set - skipping WandB authentication"
fi

echo "=========================================="
echo "Environment Ready"
echo "Python: $(python --version)"
echo "PyTorch: $(python -c 'import torch; print(torch.__version__)' 2>/dev/null || echo 'Not found')"
echo "CUDA: $(python -c 'import torch; print(torch.cuda.is_available())' 2>/dev/null || echo 'N/A')"
echo "GPU: $(python -c 'import torch; print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\")' 2>/dev/null || echo 'N/A')"
echo "Conda env: $CONDA_DEFAULT_ENV"
echo "Working directory: $(pwd)"
echo "=========================================="
echo ""
echo "📁 Setup Instructions:"
echo ""
echo "1. Clone Grievous repo (first time only):"
echo "   cd /workspace"
echo "   git clone https://github.com/alexkoven/Grievous.git"
echo ""
echo "2. Install LeRobot from Grievous source:"
echo "   cd /workspace/Grievous"
echo "   pip install -e '.[smolvla]'"
echo ""
echo "3. Verify installation:"
echo "   python -c 'from lerobot.common.policies.smolvla.modeling_smolvla import SmolVLAPolicy; print(\"✓ SmolVLA ready!\")'"
echo ""
echo "4. Start training:"
echo "   cd /workspace/Grievous"
echo "   ./train_grievous.sh"
echo ""
echo "📡 SSH Access:"
echo "   Direct: ssh root@<POD-IP> -p <MAPPED-PORT-22>"
echo ""
echo "📝 Note: All dependencies pre-installed, only clone + install needed!"
echo "=========================================="

# Execute the main command (defaults to "sleep infinity")
exec "$@"
