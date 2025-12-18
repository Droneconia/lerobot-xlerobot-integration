# RunPod Docker Setup

This directory contains our custom Docker configuration optimized for RunPod training workflows.

## Directory Structure

```
docker_runpod/
├── Dockerfile                      # Main Dockerfile (self-contained, /workspace workflow)
├── entrypoint.sh                   # Entrypoint script for the main Dockerfile
├── Dockerfile.runpod-base          # Alternative: Uses RunPod's PyTorch base image
├── entrypoint.runpod-base.sh       # Entrypoint for runpod-base Dockerfile
└── README.md                       # This file
```

## Main Dockerfile (Recommended)

**File:** `Dockerfile`

**Features:**
- ✅ Self-contained (installs PyTorch from scratch)
- ✅ Portable (works on any platform, not just RunPod)
- ✅ Workspace-based (code in `/workspace` persists with network volume)
- ✅ Conda environment (`grievous`)
- ✅ Direct SSH access (fast, no gateway lag)
- ✅ Auto-activates environment on login

**Build:**
```bash
docker build -f docker_runpod/Dockerfile -t alexkoven/lerobot-grievous-training:latest .
```

**Use case:** Production training, development, fully reproducible

---

## Alternative Dockerfile (runpod-base)

**File:** `Dockerfile.runpod-base`

**Features:**
- Uses RunPod's PyTorch base image (faster build)
- Conda environment in `/opt/miniconda3`
- Still uses `/workspace` for code

**Build:**
```bash
docker build -f docker_runpod/Dockerfile.runpod-base -t alexkoven/lerobot-grievous-training:runpod-base .
```

**Use case:** Faster builds, RunPod-specific optimization

---

## SSH Access Configuration

SSH keys are **injected at runtime** (not baked into the image) for security.

**Setup:**
1. Add `SSH_PUBLIC_KEY` environment variable in RunPod template:
   ```
   SSH_PUBLIC_KEY=ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOBQtgy/VGmvbgQUHJdNVo5ywbQBP9mumDk9aZ7MIn5c podrun-access
   ```

2. The entrypoint script writes this to `/root/.ssh/authorized_keys` at container startup

3. SSH directly to the pod:
   ```bash
   ssh root@<POD-IP> -p <MAPPED-PORT-22>
   ```

**Security:** Keys never stored in image layers, only injected at runtime.

---

## Comparison with HuggingFace's Docker

| Aspect | HuggingFace (`docker/`) | Our Setup (`docker_runpod/`) |
|--------|------------------------|------------------------------|
| **Code location** | `/lerobot` (in image) | `/workspace` (persistent) |
| **Environment** | venv | conda |
| **PyTorch** | Installed via pip | Installed via pip (self-contained) |
| **SSH** | Via entrypoint | Direct with authorized keys |
| **Persistence** | Only `/workspace` caches | Code + data in `/workspace` |
| **Development** | Rebuild for code changes | Git pull in `/workspace` |
| **Use case** | CI/CD, testing | Training, development |

---

## Workflow

### 1. Build Image
```bash
docker build -f docker_runpod/Dockerfile -t alexkoven/lerobot-grievous-training:latest .
```

### 2. Push to Docker Hub
```bash
docker push alexkoven/lerobot-grievous-training:latest
```

### 3. Deploy on RunPod
- Use template with image: `alexkoven/lerobot-grievous-training:latest`
- Expose ports: 22, 5555, 5556
- Mount network volume at `/workspace`
- Set environment variables:
  - `HF_TOKEN` - HuggingFace token
  - `WANDB_API_KEY` - Weights & Biases API key
  - `SSH_PUBLIC_KEY` - Your SSH public key (for direct SSH access)

### 4. Connect via SSH
```bash
# Direct SSH (from RunPod Connect section)
ssh root@<POD-IP> -p <MAPPED-PORT-22>
```

### 5. Setup Code in Pod
```bash
# First time: Clone Grievous repo
cd /workspace
git clone https://github.com/alexkoven/Grievous.git
cd Grievous

# Install LeRobot from Grievous source (all dependencies pre-installed in image)
pip install -e ".[smolvla]"

# Verify
python -c "from lerobot.common.policies.smolvla.modeling_smolvla import SmolVLAPolicy; print('✓ Ready!')"
```

### 6. Run Training
```bash
cd /workspace/Grievous
./train_grievous.sh
```

**Note:** On subsequent pod starts (same network volume), just:
```bash
cd /workspace/Grievous
git pull  # Update code if needed
./train_grievous.sh
```

---

## Files Kept in Original `docker/` Directory

HuggingFace's original Docker files remain in `docker/` for reference:
- `docker/Dockerfile.internal` - HuggingFace's CI Dockerfile
- `docker/entrypoint.sh` - HuggingFace's entrypoint
- `docker/Dockerfile.user` - User-facing Dockerfile

These are kept separate to preserve upstream compatibility.
