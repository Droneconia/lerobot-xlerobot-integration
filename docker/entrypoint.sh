#!/bin/bash
# Auto-authentication entrypoint for RunPod
# This script automatically logs in to HuggingFace and WandB when tokens are provided as environment variables
set -e

echo "=========================================="
echo "Starting LeRobot Container"
echo "=========================================="

# Start SSH daemon for direct SSH access (port 22)
echo "Starting SSH daemon..."
sudo /usr/sbin/sshd
echo "✓ SSH daemon started"

# Auto-authenticate HuggingFace if token provided
if [ -n "$HF_TOKEN" ]; then
    echo "Authenticating with HuggingFace..."
    huggingface-cli login --token "$HF_TOKEN" --add-to-git-credential
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
echo "=========================================="

# Execute the main command
exec "$@"

