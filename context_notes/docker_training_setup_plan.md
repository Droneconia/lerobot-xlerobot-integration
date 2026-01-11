# Docker Setup - Action Plan (Ubuntu)

**Goal:** Build Docker image locally → Push to Docker Hub → Deploy on RunPod  
**Time Savings:** 2-3 min pod startup (vs. 20-30 min with setup script)  
**System:** Ubuntu

## Progress Tracker
**Status:** Step 1-6 ✓ Complete, Ready for Step 7 (RunPod Setup)  
**Current Task:** USER needs to set up RunPod credentials and template  
**Last Updated:** Dec 17, 2025  

**Credentials (fill in as you get them):**
- Docker version: 28.2.2 ✓
- Image built: ce5ad1c70459 ✓
- Image pushed to Docker Hub: ✓
- Docker Hub username: _____ (your image path)
- HF token: _____ (get from https://huggingface.co/settings/tokens)
- WandB key: _____ (get from https://wandb.ai/authorize)

---

## Legend
- **USER**: You do this on your local machine
- **AI**: I do this in Cursor
- **BOTH**: Requires coordination

---

## Step 1: Install Docker on Ubuntu (USER)

- [ ] **USER**: Install Docker:
```bash
sudo apt update
sudo apt install -y docker.io
```

- [ ] **USER**: Add your user to docker group (avoids needing sudo):
```bash
sudo usermod -aG docker $USER
```

- [ ] **USER**: Activate group changes (choose one):
```bash
# Option A: Use newgrp (works immediately in current terminal)
newgrp docker

# Option B: Log out and log back in (applies system-wide)
```

- [ ] **USER**: Verify Docker works:
```bash
docker --version
docker ps
```

**Expected output**: Docker version info and empty container list (or running containers)

**Docker Installed:** Yes / No | **Date:** _____ | **Version:** _____

---

## Step 2: Prepare Image Files (AI - DONE ✓)

- [x] **AI**: Updated Dockerfile to Python 3.11
- [x] **AI**: Created `docker/entrypoint.sh` for auto-authentication
- [x] **AI**: Integrated entrypoint into Dockerfile

**Status:** Complete

---

## Step 3: Build Docker Image (USER)

- [ ] **USER**: Open terminal and navigate to repository:
```bash
cd /home/falcon/Code/lerobot-xlerobot-integration
```

- [ ] **USER**: Build the image (~20-30 minutes):
```bash
docker build -f docker/Dockerfile.internal -t lerobot-grievous-training:test .
```

- [ ] **USER**: Wait for build to complete (watch for any errors)

- [ ] **USER**: Check image was created:
```bash
docker images | grep lerobot-grievous
```

**Image Built:** Yes / No  
**Image Size:** _____ GB  
**Build Time:** _____ minutes  
**Date:** _____  
**Issues:** _____

---

## Step 4: Test Image Locally (USER)

- [ ] **USER**: Run image interactively:
```bash
docker run --rm -it lerobot-grievous-training:test
```

- [ ] **USER**: Inside container, verify:
```bash
python --version          # Should show Python 3.11.x
python -c "import torch; print(torch.__version__)"
python -c "import lerobot; print(lerobot.__version__)"
exit
```

**Tests Passed:** Yes / No  
**Python Version:** _____  
**PyTorch Version:** _____  
**Issues:** _____

---

## Step 5: Create Docker Hub Account (USER)

- [ ] **USER**: Go to https://hub.docker.com
- [ ] **USER**: Sign up (free account) or log in
- [ ] **USER**: Note your username: _____________________

**Account Created:** Yes / No | **Date:** _____

---

## Step 6: Push Image to Docker Hub (USER)

- [ ] **USER**: Login to Docker Hub from terminal:
```bash
docker login
# Enter username and password when prompted
```

- [ ] **USER**: Tag image with your username:
```bash
docker tag lerobot-grievous-training:test <YOUR-USERNAME>/lerobot-grievous-training:latest
docker tag lerobot-grievous-training:test <YOUR-USERNAME>/lerobot-grievous-training:v1.0
```

- [ ] **USER**: Push to Docker Hub (~10-20 minutes):
```bash
docker push <YOUR-USERNAME>/lerobot-grievous-training:latest
docker push <YOUR-USERNAME>/lerobot-grievous-training:v1.0
```

- [ ] **USER**: Verify on Docker Hub website: Check repository exists and tags are visible

**Image Path:** _____________________  
**Push Complete:** Yes / No  
**Push Time:** _____ minutes  
**Date:** _____  
**Issues:** _____

---

## Step 7: Get Authentication Credentials (USER)

- [ ] **USER**: Get HuggingFace token:
  - Go to https://huggingface.co/settings/tokens
  - Create new token with read/write permissions
  - Copy and store securely: _____

- [ ] **USER**: Get WandB API key:
  - Go to https://wandb.ai/authorize
  - Copy API key and store securely: _____

**⚠️ Important**: Never commit these tokens to git!

**Credentials Obtained:** Yes / No | **Date:** _____

---

## Step 8: Configure RunPod (USER)

### 8.1 Create Network Volume (Optional but Recommended)
- [ ] **USER**: Go to https://www.runpod.io → Storage → Network Volumes
- [ ] **USER**: Click "New Network Volume"
- [ ] **USER**: Configure:
  - Name: `lerobot-grievous-storage`
  - Size: `50 GB`
  - Region: Choose your preferred region
- [ ] **USER**: Create and note Volume ID: _____

**Volume Created:** Yes / No | **Date:** _____

### 8.2 Create Pod Template
- [ ] **USER**: RunPod → Templates → New Template
- [ ] **USER**: Fill in:
  - **Template Name**: `LeRobot Grievous Training`
  - **Container Image**: `<YOUR-USERNAME>/lerobot-grievous-training:latest`
  - **Container Disk**: `50 GB`
  - **Volume Mount Path**: `/workspace` (if using volume)
  
- [ ] **USER**: Add Environment Variables:
  - `HF_TOKEN` = `<paste-your-hf-token>`
  - `WANDB_API_KEY` = `<paste-your-wandb-key>`
  - `HF_HOME` = `/workspace/.cache/huggingface`
  - `CUDA_VISIBLE_DEVICES` = `0`

- [ ] **USER**: Expose TCP Ports (for inference - allows RPi5 to connect):
  - Click "Add Port" or similar button
  - **Port 5555**: TCP (for commands/actions from policy to robot)
  - **Port 5556**: TCP (for observations from robot to policy)
  - Note: These are used when running inference, not needed for training only

- [ ] **USER**: Save template

**Template Created:** Yes / No | **Template Name:** _____ | **Date:** _____

---

## Step 9: Deploy Your First Pod (USER)

- [ ] **USER**: RunPod → Pods → Deploy
- [ ] **USER**: Select your template: "LeRobot Grievous Training"
- [ ] **USER**: Choose GPU type (RTX 4090 / A100, need 24GB+ VRAM)
- [ ] **USER**: Choose region with availability
- [ ] **USER**: Attach volume (if created in Step 8.1)
- [ ] **USER**: Click Deploy
- [ ] **USER**: Wait for status: Pending → Pulling → Running (~5-10 min first time)

**Pod Deployed:** Yes / No  
**Pod ID:** _____  
**GPU Type:** _____  
**Region:** _____  
**Startup Time:** _____ minutes  
**Date:** _____

---

## Step 10: Verify Pod Environment (USER)

- [ ] **USER**: In RunPod dashboard, click "Connect" on your pod
- [ ] **USER**: Choose Web Terminal or SSH
- [ ] **USER**: Verify entrypoint ran (should see "Environment Ready" message)
- [ ] **USER**: Run verification commands:

```bash
# Check GPU
nvidia-smi

# Check Python and packages
python --version                                                    # Expect 3.11.x
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
python -c "import lerobot; print(lerobot.__version__)"

# Check authentication
huggingface-cli whoami          # Should show your HF username
wandb status                     # Should show "Logged in as..."

# Check training script
ls -la train_grievous.sh
chmod +x train_grievous.sh
```

**Verification Results:**
- GPU detected: Yes / No | GPU model: _____
- Python 3.11: Yes / No
- PyTorch CUDA: Yes / No
- Auth working: Yes / No
- **All systems ready:** Yes / No
- **Issues:** _____

---

## Step 11: Run Training (USER)

### First Time - Test Run
- [ ] **USER**: In pod terminal, run quick test:
```bash
cd /lerobot
./train_grievous.sh
# Select verification/test option
```

### Full Training
- [ ] **USER**: Run full training:
```bash
cd /lerobot
./train_grievous.sh
# Select full training option
```

- [ ] **USER**: Monitor:
  - WandB dashboard (link in training output)
  - GPU usage: `watch -n 1 nvidia-smi` (in separate terminal)

- [ ] **USER**: After training completes, stop pod to avoid charges

**Training Status:**
- Test run: Success / Failed
- Full training: Success / Failed / In Progress
- **Date:** _____
- **Issues:** _____

---

## Step 12: Running Inference (Optional - USER + RPi5)

**When you want to run inference from RunPod with your robot:**

### 12.1 On RunPod Pod
1. [ ] Connect to your running pod
2. [ ] Note the pod's public IP address (shown in RunPod dashboard)
3. [ ] Verify ports 5555 and 5556 are exposed
4. [ ] Start policy inference server (waiting for robot to connect)
```bash
cd /lerobot
# Run your inference script that listens on ports 5555/5556
# The script should wait for the RPi5 to connect
```

### 12.2 On RPi5 (Robot Side)
1. [ ] SSH into your RPi5
2. [ ] Run the Grievous inference host with RunPod IP:
```bash
python -m lerobot.robots.grievous.grievous_inference_host \
    --remote-ip <RUNPOD-POD-IP> \
    --port-cmd 5555 \
    --port-obs 5556 \
    --duration 300
```

**What happens:**
- RPi5 connects to RunPod pod's exposed ports
- RPi5 sends robot observations (camera frames + state) → RunPod
- RunPod policy processes observations and sends actions → RPi5
- RPi5 executes actions on Grievous robot
- Loop continues until duration expires or interrupted

**Architecture:**
```
[RPi5 - Grievous Robot]  <--TCP 5555/5556-->  [RunPod Pod - Policy Server]
    (Host)                                         (Client/Policy)
  - Controls robot                               - Runs inference
  - Sends observations                           - Sends actions
  - Receives actions                             - Receives observations
```

**Key Points:**
- Ports 5555/5556 must be exposed in RunPod template
- RPi5 initiates connection to RunPod (reverse of typical client-server)
- Use `--dry-run` on RPi5 for safe testing without moving robot

---

## For Future Training Runs (USER)

**Quick Start (~2-3 minutes):**
1. [ ] RunPod → Deploy from template
2. [ ] Select GPU and region
3. [ ] Wait for "Running" status
4. [ ] Connect → Run `./train_grievous.sh`
5. [ ] Monitor via WandB
6. [ ] Stop pod when done

---

## Updating Code/Dependencies (USER + AI)

**When you need to update code:**
1. [ ] **AI**: Make code changes in Cursor
2. [ ] **USER**: Pull changes to local machine
3. [ ] **USER**: Rebuild image:
```bash
docker build -f docker/Dockerfile.internal -t lerobot-grievous-training:latest .
```
4. [ ] **USER**: Tag and push:
```bash
docker tag lerobot-grievous-training:latest <username>/lerobot-grievous-training:v1.1
docker push <username>/lerobot-grievous-training:v1.1
docker push <username>/lerobot-grievous-training:latest
```
5. [ ] **USER**: Deploy new pod (pulls latest image)

**Update Log:**
- v1.0: _____ | Initial release
- v1.1: _____ | _____

---

## Quick Troubleshooting

| Problem | Solution (USER) |
|---------|-----------------|
| GPU not detected | Run `nvidia-smi` in pod, check RunPod dashboard shows GPU attached |
| Auth failed | Check env vars in template, verify tokens are valid |
| Out of disk space | `df -h`, clear cache: `rm -rf /workspace/.cache/huggingface/*` |
| OOM error | Reduce batch size in training config, or use larger GPU |
| Can't pull image | Verify image path, check Docker Hub repository is public |

---

## Quick Reference Commands

**Local build/push:**
```bash
docker build -f docker/Dockerfile.internal -t lerobot-grievous-training:latest .
docker tag lerobot-grievous-training:latest <username>/lerobot-grievous-training:latest
docker login && docker push <username>/lerobot-grievous-training:latest
```

**In-pod verification:**
```bash
nvidia-smi                                          # GPU check
python --version                                    # Python 3.11
python -c "import torch, lerobot; print(torch.__version__, lerobot.__version__)"
huggingface-cli whoami && wandb status             # Auth check
```

---

## Summary

**Timeline:**
- Initial setup: 2-3 hours (one time)
- Per pod startup: 2-3 minutes (vs. 20-30 min with script)
- Break-even: After 3-4 pod deployments

**Key Files:**
- `docker/Dockerfile.internal` (Python 3.11, entrypoint integrated)
- `docker/entrypoint.sh` (auto-authentication)
- Image path: `<YOUR-USERNAME>/lerobot-grievous-training:latest`

**Resources:**
- Docker Hub: https://hub.docker.com
- RunPod: https://www.runpod.io
- HF Tokens: https://huggingface.co/settings/tokens
- WandB: https://wandb.ai/authorize

---

**SETUP COMPLETE - READY TO BUILD**

**Next Action:** USER completes Step 1 (Install Docker)

