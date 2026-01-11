# Permanent Docker Solution Summary

## ✅ Problems Fixed

### **1. Version Upgrade Cascade**
**Problem:** Image had torch 2.4.1, but pip would upgrade to 2.7.1 during `pip install -e`, downloading 3GB of CUDA libraries and filling container disk.

**Solution:** Install EXACT versions (torch 2.7.1) from tested working pod in `requirements-exact.txt`. No version ranges = no upgrades.

---

### **2. Missing Utilities**
**Problem:** `screen` not installed (needed for background training sessions).

**Solution:** Added `screen`, `vim`, `nano` to system dependencies.

---

### **3. Container Disk Too Small**
**Problem:** 20GB not enough for:
- Image layers (~7-8GB)
- Pre-installed packages (~3-4GB)
- Additional packages during pip install (~2-3GB)
- Temporary space during install (~2GB)

**Solution:** **REQUIRE 40GB container disk in template.**

---

## 📋 Key Changes

### **Dockerfile (`docker_runpod/Dockerfile`)**

1. **Added utilities:**
   ```dockerfile
   screen vim nano
   ```

2. **Install exact versions:**
   ```dockerfile
   COPY docker_runpod/requirements-exact.txt /tmp/requirements-exact.txt
   RUN uv pip install --system -r /tmp/requirements-exact.txt
   ```

3. **No version ranges:** All packages pinned to exact tested versions

---

### **New File: `requirements-exact.txt`**

Contains EXACT versions from your working pod:
```
torch==2.7.1  (not >=2.4.0,<2.5.0)
torchvision==0.22.1
# ... all other packages with == not >=
```

This prevents pip from "being smart" and upgrading packages.

---

## 🎯 How It Works Now

### **Image Build:**
```
1. Install system dependencies (screen, vim, git, etc.)
2. Install miniconda
3. Create 'grievous' environment
4. Install EXACT package versions from requirements-exact.txt
   ↳ torch 2.7.1 + all CUDA libs
   ↳ transformers 4.57.3
   ↳ All other exact versions
5. Configure bashrc, entrypoint
```

**Result:** ~12-15GB image with ALL dependencies baked in

---

### **Pod Startup:**
```
1. Entrypoint runs:
   ├─ Start SSH daemon
   ├─ Activate conda environment
   ├─ Authenticate HF & WandB (from env vars)
   ├─ Export TMPDIR=/workspace/tmp
   ├─ Clone Grievous repo (if not exists)
   ├─ Checkout dev branch
   └─ pip install --no-deps -e . (instant - just links!)

2. User SSH in:
   └─ cd /workspace/Grievous && ./train_grievous.sh
```

**Key:** Everything is automated! Pod is ready to train on startup!

---

## 📊 Disk Space Breakdown (40GB Container)

```
Image layers:              ~8 GB
Pre-installed packages:    ~12 GB
Temp space during install: ~2 GB
OS + conda overhead:       ~3 GB
Free space:                ~15 GB
────────────────────────────────
Total:                     40 GB ✓
```

---

## 🔧 Build Commands

```bash
cd /home/falcon/Code/lerobot-xlerobot-integration

# Build with new configuration
sudo docker build -f docker_runpod/Dockerfile -t alexkoven/lerobot-grievous-training:latest .

# Push to Docker Hub
sudo docker push alexkoven/lerobot-grievous-training:latest
```

---

## 🚀 Deployment Workflow

### **Template Settings:**
```
Container Disk: 40 GB (MANDATORY)
Ports: 22, 5555, 5556
Env Vars: HF_TOKEN, WANDB_API_KEY, SSH_PUBLIC_KEY
```

### **First Time Setup:**
```bash
# Just SSH in - entrypoint handles everything!
ssh root@<POD-IP> -p <PORT>

# Check logs to see automatic setup progress:
# ✓ Grievous cloned
# ✓ Checked out dev branch
# ✓ LeRobot installed

# Start training immediately:
cd /workspace/Grievous
./train_grievous.sh
```

### **Subsequent Pods (same network volume):**
```bash
ssh root@<POD-IP> -p <PORT>

# Entrypoint sees Grievous exists → skips cloning
# Just reinstalls package link (instant)

# Optional: Update code
cd /workspace/Grievous
git pull

# Start training:
./train_grievous.sh
```

---

## ✅ Why This Is Permanent

1. **No version conflicts:** Exact versions prevent upgrades
2. **Pre-installed:** All heavy packages (torch, CUDA) in image
3. **Fast setup:** `pip install -e` is instant (just links)
4. **Enough space:** 40GB accommodates everything
5. **Utilities included:** screen, vim, nano baked in
6. **Tested versions:** Uses exact packages from working pod

---

## 🔄 Maintenance

### **When to Rebuild:**

1. **Update packages:** Edit `requirements-exact.txt`, rebuild
2. **Add utilities:** Edit Dockerfile, rebuild
3. **Change Python version:** Edit Dockerfile, rebuild

### **When NOT to Rebuild:**

1. **Code changes:** Just `git pull` in `/workspace/Grievous`
2. **Training config changes:** Edit in `/workspace`, persists
3. **New env vars:** Update template only

---

## 📝 Files Changed

```
docker_runpod/
├── Dockerfile (updated: system deps, exact versions)
├── entrypoint.sh (updated: TMPDIR exports, instructions)
├── requirements-exact.txt (NEW: pinned versions)
└── PERMANENT_SOLUTION.md (this file)

context_notes/
└── docker_workflow_reference.md (updated: 40GB requirement)
```

---

## 🎓 Lessons Learned

1. **pip is too smart:** Version ranges cause upgrades. Use `==` not `>=`.
2. **Container disk matters:** TMPDIR doesn't help with installed packages.
3. **Exact is better:** Tested versions > "latest compatible".
4. **Pre-install everything:** Makes user workflow instant.
5. **40GB is the magic number:** 20GB too small, 60GB wasteful.

---

## ⚠️ Critical Requirements

- ✅ **Container Disk: 40 GB** (DO NOT use 20GB!)
- ✅ **Use requirements-exact.txt** (not pyproject.toml ranges)
- ✅ **Network Volume:** For /workspace persistence
- ✅ **Env Vars:** HF_TOKEN, WANDB_API_KEY must be set




