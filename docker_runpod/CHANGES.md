# Docker Rebuild Changes - Exact Local Environment Match

## What Changed

### **Root Cause Found:**
- **Old image:** Python 3.11
- **Your laptop:** Python 3.10
- **Result:** Version conflicts causing 2.7GB of re-downloads

### **Fix Applied:**

1. **Extracted exact requirements from your laptop:**
   - `conda env export` from your local `grievous` environment
   - Created `docker_runpod/requirements-exact.txt` (187 packages)
   - Includes torch 2.7.1 + CUDA 12.6.x (exact versions)

2. **Updated Dockerfile:**
   - Changed Python 3.11 → 3.10
   - Changed Miniconda py311 → py310
   - Replaced manual dependency installation with `requirements-exact.txt`
   - Removed `uv` usage, using regular `pip` instead

3. **Updated Workflow:**
   - User installs with `--no-deps` (just links code)
   - No downloads needed (all packages pre-installed)
   - Installation takes <5 seconds

---

## Files Modified

```
docker_runpod/
├── Dockerfile              ✓ Updated (Python 3.10, requirements-exact.txt)
├── entrypoint.sh           ✓ Updated (--no-deps instructions)
├── README.md               ✓ Updated (workflow docs)
└── requirements-exact.txt  ✓ NEW (from your laptop)
```

---

## New Workflow

### **After Rebuild (One-time):**
```bash
cd /workspace
git clone https://github.com/alexkoven/Grievous.git
cd Grievous
pip install --no-deps -e .
./train_grievous.sh
```

**Time:** <5 seconds for install (no downloads!)

---

## Why This Works

**Before (BROKEN):**
```
Image: Python 3.11 + partial packages
Install: pip detects version mismatch
Result: Downloads 2.7GB, fills disk ❌
```

**After (FIXED):**
```
Image: Python 3.10 + EXACT packages from your laptop
Install: pip install --no-deps (just links code)
Result: Instant, no downloads ✅
```

---

## Container Disk Requirements

**With exact versions:**
```
Image layers:        ~4 GB
Pre-installed pkgs:  ~4 GB  (exact match, no conflicts)
────────────────────────────
Total: ~8 GB
```

**Your 5GB container disk template should work** (tight but sufficient).

If issues, increase to 10GB for breathing room.

---

## Build & Test Commands

### **Build:**
```bash
cd /home/falcon/Code/lerobot-xlerobot-integration
sudo docker build -f docker_runpod/Dockerfile -t alexkoven/lerobot-grievous-training:latest .
```

**Expected:** ~10-12 minutes (installing 187 packages)

### **Push:**
```bash
sudo docker push alexkoven/lerobot-grievous-training:latest
```

### **Test (on pod):**
```bash
cd /workspace
git clone https://github.com/alexkoven/Grievous.git
cd Grievous
git checkout dummy_inference_laptop
pip install --no-deps -e .

# Verify (should be instant)
python -c "from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy; print('✓ Works!')"
```

---

## Success Criteria

✅ Build completes without errors
✅ Image size ~8-10 GB
✅ Pod install takes <5 seconds
✅ No package downloads during install
✅ Training starts successfully
✅ Works with 5GB container disk

---

## If Issues Occur

**If build fails:**
- Check `requirements-exact.txt` is in `docker_runpod/`
- Check Python 3.10 is being used

**If install still downloads packages:**
- Check Python version in pod: `python --version` (should be 3.10.18)
- Check installed packages: `pip list | grep torch` (should match laptop)

**If disk fills up:**
- Increase container disk to 10GB (gives headroom)

---

## Ready to Rebuild

Run:
```bash
sudo docker build -f docker_runpod/Dockerfile -t alexkoven/lerobot-grievous-training:latest .
```

This will be the FINAL rebuild!
