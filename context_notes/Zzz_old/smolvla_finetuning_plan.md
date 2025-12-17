# SmolVLA Finetuning Training Plan

## Overview

This document outlines the complete plan for finetuning SmolVLA on the Grievous robot dataset using `lerobot_train.py` on RunPod cloud infrastructure.

**Model**: `lerobot/smolvla_base` (pretrained 450M model)  
**Dataset**: `Grievous-Robot/test-record-v14`  
**Target Output**: `Grievous-Robot/smolvla_finetuned`  
**Estimated Training Time**: ~4 hours on RTX 4090 / A100 GPU

---

## Pre-Training Setup Checklist

### 1. Environment Verification
- [ ] Activate conda environment: `source activate_env.sh`
- [ ] Verify GPU access: `nvidia-smi` (should show RTX 4090 or similar)
- [ ] Check PyTorch CUDA: `python -c "import torch; print(torch.cuda.is_available())"`
- [ ] Verify working directory: Should be in repository root with `train_grievous.sh`

### 2. Authentication
- [ ] **HuggingFace**: Run `huggingface-cli login` and enter token
  - Token needed to download pretrained model and upload finetuned model
  - Token should have write access to `Grievous-Robot` organization
  
- [ ] **WandB**: Run `wandb login` and enter API key
  - Needed for training metrics logging
  - Project: `smolvla-finetuning`

### 3. Dataset Verification
- [ ] Confirm dataset `Grievous-Robot/test-record-v14` is accessible
- [ ] Verify dataset has correct format (images, state, actions)
- [ ] Check dataset size (recommended: >50 episodes for good results)

---

## Training Workflow

### Phase 1: Verification (10 steps, ~1 minute)
**Purpose**: Verify setup works before committing to long training

```bash
./train_grievous.sh
# Select option 1: Verify setup
```

**What to check**:
- No import errors
- GPU is being used (check `nvidia-smi` during run)
- Dataset loads correctly
- Model loads from `lerobot/smolvla_base`

### Phase 2: Test Training (500 steps, ~15-30 minutes)
**Purpose**: Test full training pipeline and monitor metrics

```bash
./train_grievous.sh
# Select option 2: Test training
```

**What to monitor**:
- **Loss**: Should decrease steadily (not spike or plateau immediately)
- **Learning rate**: Should start at 1e-4 and follow warmup schedule
- **Gradient norm**: Should be stable (not exploding)
- **GPU utilization**: Should be high (>80%)
- **Memory usage**: Should be reasonable for your GPU

**Red flags**:
- Loss not decreasing → May need lower learning rate
- Loss spiking → Training unstable, lower LR or increase gradient clipping
- GPU memory errors → Reduce batch size
- Dataset loading errors → Check dataset format

### Phase 3: Full Training (20,000 steps, ~4 hours)
**Purpose**: Complete finetuning run

```bash
./train_grievous.sh
# Select option 3: Full training
```

**Training details**:
- **Steps**: 20,000 (recommended by HuggingFace documentation)
- **Batch size**: 64 (recommended by HuggingFace documentation)
- **Checkpoints**: Saved every 5,000 steps (4 checkpoints total)
- **Logging**: Every 100 steps to WandB
- **Final model**: Automatically pushed to HuggingFace Hub

**Monitoring during training**:
1. **WandB Dashboard**: 
   - Watch loss curve (should decrease smoothly)
   - Monitor learning rate schedule
   - Check gradient norms (should be stable)
   
2. **Disk Space**:
   - Checkpoints saved to `/workspace/outputs/smolvla_finetuned`
   - Old checkpoints auto-deleted (keeps last 2)
   - Final model pushed to Hub (saves local space)

3. **GPU Status**:
   - Monitor with `watch -n 1 nvidia-smi`
   - Should see high GPU utilization (>80%)

**Post-training verification**:
- [ ] Model uploaded to `Grievous-Robot/smolvla_finetuned` on HuggingFace Hub
- [ ] Check final loss value (should be lower than initial)
- [ ] Verify model files in Hub (should include config, weights, processors)

---

## Training Parameters Reference

### Parameter Sources

#### From HuggingFace/LeRobot (Official Defaults)
These parameters come from the SmolVLA configuration defaults in the LeRobot codebase:

- **Learning Rate**: `1e-4` 
  - Source: `SmolVLAConfig.optimizer_lr` (line 76 in `configuration_smolvla.py`)
  - This is the recommended finetuning learning rate from HuggingFace
  
- **Batch Size**: `64`
  - Source: HuggingFace documentation example (`docs/source/smolvla.mdx` line 60)
  - Recommended starting point, can be adjusted based on GPU memory
  
- **Training Steps**: `20,000`
  - Source: HuggingFace documentation example (`docs/source/smolvla.mdx` line 61)
  - Documentation states: "Training the model for 20k steps will roughly take ~4 hrs on a single A100 GPU"
  
- **Optimizer Settings** (from `SmolVLAConfig`):
  - `optimizer_betas: (0.9, 0.95)` - Adam optimizer momentum parameters
  - `optimizer_eps: 1e-8` - Adam epsilon
  - `optimizer_weight_decay: 1e-10` - Very small weight decay (almost none)
  - `optimizer_grad_clip_norm: 10` - Default gradient clipping (we use 1.0, more conservative)
  
- **Scheduler Settings** (from `SmolVLAConfig`):
  - `scheduler_warmup_steps: 1,000` - Linear warmup for first 1000 steps
  - `scheduler_decay_steps: 30,000` - Cosine decay over 30k steps
  - `scheduler_decay_lr: 2.5e-6` - Final learning rate after decay

- **Finetuning Flags** (from `SmolVLAConfig`):
  - `freeze_vision_encoder: True` - Vision encoder frozen (standard for finetuning)
  - `train_expert_only: True` - Only expert layers train (not VLM backbone)
  - `train_state_proj: True` - State projection layers are trainable

#### Our Custom Adjustments
These are modifications we made based on best practices and constraints:

- **Gradient Clip Norm**: `1.0` (instead of default `10`)
  - **Reason**: More conservative clipping for training stability
  - **Source**: Common practice in vision-language model finetuning
  
- **Weight Decay**: `0.0` (instead of default `1e-10`)
  - **Reason**: For finetuning, weight decay is often set to 0 to preserve pretrained weights
  - **Source**: Finetuning best practices
  
- **Save Frequency**: `5,000` steps (instead of default `20,000`)
  - **Reason**: More frequent checkpoints for 20GB volume constraint
  - **Source**: Our disk space management strategy
  
- **Keep Checkpoints**: `2` (local cleanup)
  - **Reason**: Save disk space on 20GB volume
  - **Source**: Our storage management needs

### When to Adjust Parameters

#### Learning Rate Adjustments

**Keep `1e-4` (default) if**:
- Dataset has >50 episodes
- Loss decreases steadily
- No signs of overfitting
- Training is stable

**Lower to `5e-5` if**:
- Loss plateaus early
- Signs of overfitting (validation loss increases)
- Small dataset (<25 episodes)
- Training becomes unstable

**Lower to `1e-5` if**:
- Very small dataset (<10 episodes)
- Training loss spikes frequently
- Need very fine-grained updates

**Increase to `2e-4` or `5e-4` if**:
- Loss decreases very slowly
- Large dataset (>100 episodes)
- Want faster convergence (with careful monitoring)

#### Batch Size Adjustments

**Keep `64` (default) if**:
- GPU memory allows it
- Training is stable
- Good GPU utilization

**Reduce if**:
- GPU out of memory errors
- Need to fit on smaller GPU

**Increase if**:
- Have GPU memory headroom
- Want faster training (larger batches = fewer steps needed)
- Training is stable

#### Training Steps Adjustments

**Keep `20,000` (default) if**:
- Following HuggingFace recommendations
- Dataset size is reasonable

**Increase if**:
- Large dataset (>100 episodes)
- Loss still decreasing at 20k steps
- Want better convergence

**Decrease if**:
- Small dataset (<25 episodes)
- Loss plateaus early
- Overfitting occurs

---

## Troubleshooting Guide

### Common Issues

#### 1. "No space left on device"
**Solution**: 
- Check disk usage: `df -h /workspace`
- Clean old checkpoints manually
- Reduce `KEEP_CHECKPOINTS` in script
- Increase `SAVE_FREQ` to save less frequently

#### 2. "CUDA out of memory"
**Solution**:
- Reduce `BATCH_SIZE` in `train_grievous.sh`
- Reduce `num_workers` (try 2 instead of 4)
- Use gradient accumulation (not currently in script)

#### 3. Loss not decreasing
**Possible causes**:
- Learning rate too high → Lower to `5e-5`
- Dataset too small → Need more data
- Dataset format incorrect → Verify dataset structure
- Model not loading correctly → Check `--policy.path`

#### 4. Training unstable (loss spikes)
**Solution**:
- Lower learning rate (`5e-5` or `1e-5`)
- Increase gradient clipping (`--optimizer.grad_clip_norm=5.0`)
- Check dataset for corrupted samples

#### 5. Model not uploading to Hub
**Solution**:
- Verify HuggingFace token has write access
- Check `--policy.repo_id` is correct
- Ensure `--policy.push_to_hub=true`
- Check network connectivity

---

## Expected Results

### Success Indicators
- ✅ Loss decreases from initial value (typically 0.5-2.0) to lower value (0.1-0.5)
- ✅ Loss curve is smooth (not spiky)
- ✅ Gradient norms are stable (not exploding)
- ✅ Model successfully uploaded to HuggingFace Hub
- ✅ Training completes all 20,000 steps

### Performance Benchmarks
Based on HuggingFace documentation:
- **Training time**: ~4 hours on A100/RTX 4090
- **Memory usage**: ~20-30GB GPU memory
- **Final loss**: Varies by dataset, but should be significantly lower than initial

---

## Next Steps After Training

1. **Evaluate the model**: Use `lerobot_eval.py` to test on validation data
2. **Deploy for inference**: Use the finetuned model in your inference pipeline
3. **Iterate if needed**: If performance is insufficient, consider:
   - More training data
   - Longer training (more steps)
   - Hyperparameter tuning
   - Different learning rate schedule

---

## References

- **SmolVLA Configuration**: `src/lerobot/policies/smolvla/configuration_smolvla.py`
- **HuggingFace Documentation**: `docs/source/smolvla.mdx`
- **Training Script**: `src/lerobot/scripts/lerobot_train.py`
- **Training Helper Script**: `train_grievous.sh`
- **SmolVLA Paper**: https://huggingface.co/papers/2506.01844
- **Pretrained Model**: https://huggingface.co/lerobot/smolvla_base

