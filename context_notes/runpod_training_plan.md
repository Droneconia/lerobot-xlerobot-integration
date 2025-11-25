# RunPod Training Plan for Grievous SmolVLA

## Overview
Train SmolVLA policy on RunPod RTX 4090, then deploy inference locally. Total cost: ~$3.50 one-time.

---

## Phase 1: Pre-Flight Preparation (Local, 30 minutes)

### 1.1 Dataset Preparation
**Critical**: Dataset must be on HuggingFace Hub before starting RunPod.

- Verify local dataset completeness in `~/.cache/huggingface/lerobot/Grievous-Robot/<dataset-name>/`
- Check required files exist: `meta/info.json`, `meta/stats.json`, `meta/tasks.parquet`, `videos/`
- Push to HuggingFace Hub using `huggingface-cli upload <repo-id> . --repo-type=dataset`
- Test download access: `huggingface-cli download <repo-id> --repo-type=dataset`

**Attention**: Dataset size ~3-5GB, upload takes 10-30 minutes depending on bandwidth.

### 1.2 Authentication Tokens
Collect and save securely:
- HuggingFace token (read/write): From https://huggingface.co/settings/tokens
- WandB API key (optional but recommended): From https://wandb.ai/authorize

### 1.3 Configuration Validation (Optional)
Test training config locally before RunPod to catch errors early:
- Run `lerobot-train --help` to verify installation
- Validate dataset features match SmolVLA expectations
- Check camera naming conventions (left_wrist, right_wrist, head)

---

## Phase 2: RunPod Instance Setup (15 minutes)

### 2.1 Instance Selection
**Recommended**: RTX 4090 (24GB VRAM)
- Provider: RunPod
- GPU: RTX 4090 (24GB)
- Template: PyTorch 2.1+ with CUDA 11.8+
- Storage: Container disk (50GB) + Network Volume (50GB, optional but recommended)
- Instance type: On-Demand (NOT Spot - avoid interruptions)
- Region: Choose closest to your location for lower latency

**Cost**: $0.44/hour × 8 hours = ~$3.50 total

### 2.2 Storage Strategy
Two options:

**Option A: Network Volume** (Recommended)
- Attach 50GB network volume to `/workspace`
- Survives pod termination
- Cost: $10/month (reusable across multiple training runs)
- Use for: `output_dir`, checkpoints

**Option B: Container Disk + Hub Push**
- Use ephemeral container storage
- Push final model to HuggingFace Hub immediately after training
- Risk: Lose intermediate checkpoints if pod crashes
- Use for: One-off training with good internet

### 2.3 Pod Configuration
Enable features:
- Expose HTTP Ports: Yes (for future inference server)
- Start Jupyter: Optional (for debugging)
- Persistent Storage: Network volume path `/workspace`

**Attention**: Pods automatically terminate after idle time - set appropriate timeout or disable auto-stop.

---

## Phase 3: Environment Setup (10-15 minutes, one-time)

### 3.1 Install LeRobot
On pod terminal:
- Clone LeRobot repository
- Install with all dependencies using pip
- Installation takes ~10-15 minutes

**Attention**: Use editable install to allow modifications if needed.

### 3.2 Authentication
Configure access tokens:
- Login to HuggingFace CLI with token
- Login to WandB (optional)
- Verify authentication works (test whoami commands)

### 3.3 Directory Structure
Create organized workspace:
- Output directory for checkpoints
- Logs directory for training logs
- Optional: Dataset cache directory (auto-created on first download)

**Attention**: If using network volume, ensure output_dir points to `/workspace` for persistence.

### 3.4 Test GPU
Verify CUDA availability:
- Check nvidia-smi shows RTX 4090
- Verify PyTorch sees GPU
- Note available VRAM (~24GB)

---

## Phase 4: Training Execution (7-8 hours)

### 4.1 Launch Training
Use `lerobot-train` command (no modifications needed) with configuration:
- Policy: lerobot/smolvla_base (pretrained)
- Dataset: Your HuggingFace dataset repo
- Batch size: 32 (optimal for RTX 4090)
- Steps: 20,000 (standard for SmolVLA fine-tuning)
- Output directory: Network volume path or container path
- Save frequency: 2,000-5,000 steps (for resume capability)
- Log frequency: 200 steps (for monitoring)
- Workers: 4 (data loading parallelism)
- WandB: Enable for remote monitoring
- Hub push: Enable automatic push of final model

**Attention**: Training takes 7-8 hours. Start before leaving for the day.

### 4.2 Memory Management
Monitor VRAM usage:
- Expected: ~12-14GB with batch_size=32
- Safe range: 50-80% VRAM utilization
- If OOM occurs: Reduce batch_size to 24 or 16

**Attention**: First few steps may spike memory during initialization - this is normal.

### 4.3 Monitoring Strategy
Track training progress remotely:
- WandB dashboard: Loss curves, GPU utilization, step timing
- RunPod web terminal: Check process is running
- Checkpoint directory: Verify saves every N steps

**Key metrics to watch**:
- Loss should steadily decrease (expect 0.1-0.3 range)
- Grad norm should stabilize (not explode to >100)
- Steps/second should be consistent (~0.3-0.5 steps/sec)
- GPU utilization should be >80%

### 4.4 Common Issues During Training

**Issue**: Dataset download fails
- Solution: Re-authenticate HuggingFace, manually download dataset first

**Issue**: CUDA Out of Memory
- Solution: Reduce batch_size incrementally (32→24→16)

**Issue**: Training hangs at data loading
- Solution: Reduce num_workers (4→2→0)

**Issue**: Loss not decreasing
- Solution: Check learning rate, verify dataset quality, ensure normalization stats exist

**Attention**: Save pod logs before investigating issues - they contain stack traces.

---

## Phase 5: Training Completion (30 minutes)

### 5.1 Verify Training Success
Check indicators:
- Final checkpoint exists in output directory
- Model pushed to HuggingFace Hub (if enabled)
- WandB run marked as "finished"
- Final loss value is reasonable (<0.3)

### 5.2 Checkpoint Management
Three copies for safety:
1. Network volume (if used) - keep for resume capability
2. HuggingFace Hub - primary storage, accessible anywhere
3. Local download - backup on your laptop

Download checkpoint to local:
- Use `huggingface-cli download` or SCP from pod
- Checkpoint size: ~1-2GB

**Attention**: Don't terminate pod until checkpoint is safely backed up in 2+ locations.

### 5.3 Upload to HuggingFace Hub
If not auto-pushed during training:
- Upload final checkpoint directory
- Include preprocessor and postprocessor configs
- Add model card with training details (dataset, hyperparameters, performance)

---

## Phase 6: Pod Cleanup

### 6.1 Termination Decision
Two options:

**Option A: Terminate Immediately** (Recommended)
- Download all checkpoints
- Verify Hub upload complete
- Terminate pod to stop charges
- Keep network volume for future runs

**Option B: Keep for Inference Testing**
- Test model inference on pod first
- Run evaluation script with dummy data
- Then terminate after validation

**Cost consideration**: Keeping pod running costs $0.44/hour = $10.56/day

### 6.2 Network Volume Management
If using network volume:
- Keep volume active ($10/month) for future training runs
- Contains: Checkpoints, logs, cached dependencies
- Reusable: Attach to new pods instantly, skip installation steps

---

## Phase 7: Inference Deployment (Post-Training)

### 7.1 Local Inference (Recommended)
Deploy trained model on laptop/lab cluster:
- Download model from HuggingFace Hub
- Load policy locally: `make_policy("Grievous-Robot/smolvla_v1")`
- Run `lerobot-record` with trained policy for evaluation
- Expected latency: 40-55ms (excellent for manipulation)
- Cost: $0 ongoing

**Attention**: This gives best latency and zero ongoing costs.

### 7.2 RunPod Inference Server (Alternative)
If no local GPU available:

**Setup**:
- Keep pod alive or create new pod with trained model
- Run FastAPI inference server
- Expose HTTP endpoint via RunPod URL
- Client sends observations, receives actions over HTTPS

**Cost**: $0.44/hour = $10.56/day for continuous operation

**Attention**: Network latency adds 50-100ms. Only use if local inference impossible.

### 7.3 Hybrid Approach
Development/testing cycle:
- Train on RunPod ($3.50 per run)
- Download model to local
- Evaluate locally (free, low latency)
- Iterate: Record more data, retrain on RunPod
- Deploy final model locally

---

## Cost Breakdown

### Minimal Setup (Recommended)
- Training: RTX 4090 × 8 hours = $3.52
- Network egress (checkpoint download): ~$0.30
- **Total one-time: $3.82**
- Inference: Local (free)

### With Network Volume
- Training: $3.52
- Network volume (1 month): $10.00
- **Total: $13.52** (but volume reusable for future runs)
- Amortized over 5 runs: ~$5.50 per training

### With RunPod Inference
- Training: $3.52
- Inference server (7 days × 8hr/day): $24.64
- **Total per week: $28.16**

**Attention**: Local inference changes total cost from $28/week to $4 one-time.

---

## Critical Attention Points

### Before Starting
- [ ] Dataset on HuggingFace Hub and downloadable
- [ ] HuggingFace token has read/write permissions
- [ ] Budget confirmed (~$4 for training)
- [ ] Time allocated (8 hours training + 1 hour setup/cleanup)

### During Training
- [ ] WandB shows loss decreasing
- [ ] GPU utilization >80%
- [ ] Checkpoints saving every N steps
- [ ] No OOM errors in logs

### After Training
- [ ] Final checkpoint downloaded locally
- [ ] Model on HuggingFace Hub
- [ ] Training metrics logged to WandB
- [ ] Pod terminated (unless keeping for inference)

### Red Flags
- Loss not decreasing after 5000 steps → Investigate dataset/config
- GPU utilization <50% → Data loading bottleneck
- Frequent OOM → Reduce batch size
- Training slower than expected → Check GPU isn't throttling

---

## Timeline Summary

| Phase | Duration | Cost | Can Run Unattended? |
|-------|----------|------|---------------------|
| Pre-flight prep | 30 min | $0 | No (manual work) |
| Pod setup | 15 min | $0.11 | No (configuration) |
| Environment setup | 15 min | $0.11 | Partially (installs) |
| Training | 7-8 hours | $3.08-3.52 | Yes (monitor via WandB) |
| Cleanup | 30 min | $0.22 | No (verify success) |
| **Total** | **9 hours** | **~$4** | Mostly |

**Best practice**: Start training before end of work day, monitor via WandB, return next morning to download checkpoints.

---

## Comparison: RunPod vs Alternatives

| Option | Training Cost | Setup Time | Inference Cost | Total (1 month) |
|--------|---------------|------------|----------------|-----------------|
| **RunPod + Local** | $3.50/run | 30 min | Free | **$3.50** ✓✓✓ |
| All RunPod | $3.50/run | 30 min | $252/mo | $255.50 |
| TACC + Local | Free | 2 hours | Free | $0 (if access) |
| Google Colab Pro+ | $50/mo | 5 min | N/A | $50/mo |
| Local only | Free | 0 min | Free | $0 (if GPU) |

**Recommendation**: RunPod for training, local for inference = best cost/benefit ratio.

---

## Next Steps

1. Push dataset to HuggingFace Hub (today)
2. Collect authentication tokens (5 minutes)
3. Create RunPod account if needed (10 minutes)
4. Review this plan, note questions (15 minutes)
5. Start training session (tomorrow, 9 hours total)
6. Evaluate trained policy locally (day after, 2 hours)

**Estimated calendar time**: 2-3 days from start to trained model evaluation.

