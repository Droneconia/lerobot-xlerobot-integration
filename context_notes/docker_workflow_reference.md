# Docker Build, Tag, Push, Deploy - Complete Workflow Reference

## Prerequisites

### 1. Docker Installation (Ubuntu)
```bash
# Install Docker
sudo apt update
sudo apt install -y docker.io docker-compose

# Add your user to docker group (avoid sudo)
sudo usermod -aG docker $USER

# Log out and back in, then verify
docker ps
```

### 2. Docker Hub Authentication
```bash
# Login to Docker Hub (one-time)
docker login
# Enter username: alexkoven
# Enter password: (your Docker Hub password/token)
```

### 3. Environment Variables (for RunPod)
Prepare these values - you'll need them when deploying:
- `HF_TOKEN` - HuggingFace token (from huggingface.co/settings/tokens)
- `WANDB_API_KEY` - Weights & Biases API key (from wandb.ai/authorize)
- `SSH_PUBLIC_KEY` - Your SSH public key for direct pod access (optional, for faster SSH)

---

## Step 1: Build the Docker Image

### Basic Build (uses cache)
```bash
cd /home/falcon/Code/lerobot-xlerobot-integration

docker build \
  -f docker/Dockerfile.internal \
  -t alexkoven/lerobot-grievous-training:latest \
  .
```

**Parameters:**
- `-f docker/Dockerfile.internal` - Path to Dockerfile
- `-t alexkoven/lerobot-grievous-training:latest` - Tag with FULL name (username/repo:tag)
- `.` - Build context (current directory)

**Time**: ~3-5 minutes (with cache), ~8-12 minutes (first time)

---

### Clean Rebuild (force fresh build)
Use when:
- Changes to `entrypoint.sh` or similar files aren't being picked up
- Debugging build issues
- Want to ensure everything is fresh

```bash
docker build --no-cache \
  -f docker/Dockerfile.internal \
  -t alexkoven/lerobot-grievous-training:latest \
  .
```

**Time**: ~8-12 minutes (rebuilds everything)

---

### Verify Build Succeeded
```bash
# Check image exists
docker images alexkoven/lerobot-grievous-training

# Expected output:
# REPOSITORY                              TAG       IMAGE ID       CREATED         SIZE
# alexkoven/lerobot-grievous-training    latest    abc123def456   2 minutes ago   7.8GB

# Test run the container (verify entrypoint works)
docker run --rm alexkoven/lerobot-grievous-training:latest echo "Testing" 2>&1 | head -30

# Should see:
# ==========================================
# Starting LeRobot Container
# ==========================================
# Starting SSH daemon...
# ✓ SSH daemon started
# ... (authentication output)
```

---

## Step 2: Tag the Image (if needed)

### When to Tag
- **Already tagged during build** (recommended): Skip this step
- **Built without full name**: Need to add username prefix

### Tagging Commands
```bash
# Add Docker Hub username prefix
docker tag lerobot-grievous-training:latest alexkoven/lerobot-grievous-training:latest

# Create version tags (optional but recommended)
docker tag alexkoven/lerobot-grievous-training:latest alexkoven/lerobot-grievous-training:v1.2
```

### Version Tag Naming
- `latest` - Most recent stable build (always exists)
- `v1.0`, `v1.1`, `v1.2` - Semantic versions for specific releases
- `dev` - Development/testing builds

---

## Step 3: Push to Docker Hub

### Push Latest Tag
```bash
docker push alexkoven/lerobot-grievous-training:latest
```

**Time**: 
- First push: ~10-15 minutes (~8GB upload)
- Subsequent pushes: ~30 seconds - 3 minutes (only changed layers)

### Push Multiple Tags
```bash
# Push specific version
docker push alexkoven/lerobot-grievous-training:v1.2

# Push all tags
docker push alexkoven/lerobot-grievous-training --all-tags
```

### Verify Push
```bash
# Check local image digest
docker images --digests alexkoven/lerobot-grievous-training

# OR: Check on Docker Hub
# Go to: https://hub.docker.com/r/alexkoven/lerobot-grievous-training/tags
# Verify "Last pushed" timestamp is recent
```

**Output should show**:
```
The push refers to repository [docker.io/alexkoven/lerobot-grievous-training]
abc123: Pushed   # New/changed layers
def456: Layer already exists   # Unchanged layers
latest: digest: sha256:xyz789... size: 3460
```

---

## Step 4: Deploy on RunPod

### A. Create/Update Template (One-time setup)

1. **Go to**: [RunPod Dashboard](https://runpod.io) → Templates → "+ New Template"

2. **Template Configuration**:
   ```
   Template Name: LeRobot Grievous Training
   
   Container Image: alexkoven/lerobot-grievous-training:latest
   
   Container Disk: 40 GB (REQUIRED - do not use less!)
   
   Expose HTTP Ports: (leave empty unless needed)
   
   Expose TCP Ports: 22, 5555, 5556
   
   Docker Command: (leave empty - uses Dockerfile CMD)
   
   Environment Variables:
     HF_TOKEN: hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
     WANDB_API_KEY: xxxxxxxxxxxxxxxxxxxxxxxxxxxx
     SSH_PUBLIC_KEY: ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA... podrun-access
   ```

3. **Click**: "Save Template"

---

### B. Deploy New Pod

1. **Terminate old pod** (if exists):
   - Pods → Select pod → Terminate
   - Wait for confirmation

2. **Deploy new pod**:
   - Pods → "+ Deploy"
   - Select GPU (e.g., RTX 4090, A6000)
   - Select template: "LeRobot Grievous Training"
   - Select Network Volume (optional but recommended):
     - Name: `grievous-workspace`
     - Mount path: `/workspace`
     - Size: 50GB+
   - Click: "Deploy On-Demand" or "Deploy Spot"

3. **Wait for "Running" status** (~2-3 minutes)
   - Pod pulls image from Docker Hub
   - Runs entrypoint script (auth to HF & WandB)
   - Starts SSH daemon
   - Enters `sleep infinity` (container stays alive)

---

### C. Connect to Pod

#### Option 1: Web Terminal (Quick Access)
- Pods → Your pod → "Connect" → "Start Web Terminal"
- Opens browser-based terminal

#### Option 2: SSH via RunPod Gateway
```bash
# From RunPod "Connect" section, copy SSH command:
ssh -t POD-ID-USER@ssh.runpod.io -i ~/.ssh/id_podrun
```

#### Option 3: Direct SSH (Port 22 exposed)
```bash
# Get pod IP and mapped port from "Connect" section
ssh root@<POD-IP> -p <MAPPED-PORT-22> -i ~/.ssh/id_podrun
```

#### Option 4: SSH Config (Recommended)
Add to `~/.ssh/config`:
```
Host runpod-grievous
    HostName ssh.runpod.io
    User <POD-ID-USER>
    IdentityFile ~/.ssh/id_podrun
    ServerAliveInterval 60
```

Then simply: `ssh runpod-grievous`

---

## Step 5: Verify Deployment

### Inside the Pod (via SSH or Web Terminal)

```bash
# 1. Check Python version
python --version
# Expected: Python 3.11.14

# 2. Check PyTorch + CUDA
python -c "import torch; print(f'PyTorch: {torch.__version__}'); print(f'CUDA Available: {torch.cuda.is_available()}')"
# Expected: PyTorch: 2.7.1+cu126, CUDA Available: True

# 3. Check HuggingFace auth
huggingface-cli whoami
# Expected: Logged in as: <your-username>

# 4. Check WandB auth
wandb status
# Expected: Logged in as: <your-username>

# 5. Check workspace
ls -la /workspace
# Should see network volume contents (if mounted)

# 6. Test LeRobot import
python -c "from lerobot.common.policies.smolvla.modeling_smolvla import SmolVLAPolicy; print('✓ SmolVLA import successful')"
```

---
