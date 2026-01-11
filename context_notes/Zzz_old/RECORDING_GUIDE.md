# Grievous Robot Recording Guide

Complete guide for recording datasets with the Grievous robot system.

---

## Quick Start

```bash
# Basic recording with defaults
./test_record.sh

# Custom task and version
TASK="Pick red cube and place in box" VERSION=1 DATASET_NAME="pick-place" ./test_record.sh
```

---

## Keyboard Controls

| Key | Function | When to Use |
|-----|----------|-------------|
| **→ (Right Arrow)** | End episode / Skip reset | When task is complete, or done resetting |
| **← (Left Arrow)** | Re-record episode | When you made a mistake in the current episode |
| **Esc** | Stop recording | When you want to end the entire session |

### Recording Workflow

```
1. Script starts → Episode 0 begins
2. Perform task (teleoperate robot)
3. Press → when task complete
   ├─ Episode saved ✓
   └─ Reset period begins
4. Reset environment (move objects back)
5. Press → when ready for next episode
6. Episode 1 begins → Repeat from step 2
```

**Pro Tip:** Don't wait for timeouts! Use → to control timing precisely.

---

## Dataset Versioning Strategy

### Version Number Format

```
{robot}-{task-name}-v{version}

Examples:
✓ grievous-pick-place-v1
✓ grievous-bimanual-handoff-v2
✓ grievous-drawer-opening-v1
```

### When to Increment Version

| Scenario | Action | Example |
|----------|--------|---------|
| **First recording** | Start at v1 | `pick-place-v1` |
| **Same task, new session** | Increment version | v1 → v2 |
| **Different person recording** | Increment version | v1 → v2 |
| **Hardware change** | Increment version | v1 → v2 |
| **Environment change** | Increment version | v1 → v2 |
| **Continue same session** | Use `--resume` flag | Keep v1 |

### Version Control Best Practices

#### ✅ Good Versioning

```bash
# Session 1: Person A records initial dataset
TASK="Pick cube" DATASET_NAME="pick-place" VERSION=1 EPISODES=25 ./test_record.sh
# → Creates: Grievous-Robot/pick-place-v1 (25 episodes)

# Session 2: Person B adds more demonstrations
TASK="Pick cube" DATASET_NAME="pick-place" VERSION=2 EPISODES=25 ./test_record.sh
# → Creates: Grievous-Robot/pick-place-v2 (25 episodes)

# Session 3: Improved technique with different camera angles
TASK="Pick cube" DATASET_NAME="pick-place" VERSION=3 EPISODES=50 ./test_record.sh
# → Creates: Grievous-Robot/pick-place-v3 (50 episodes)
```

#### ❌ Bad Versioning

```bash
# Don't use random names
DATASET_NAME="test_123_final_FINAL"  # Bad!

# Don't skip versions
VERSION=1  # Then jump to VERSION=5  # Bad!

# Don't reuse versions for different setups
VERSION=1  # With camera A
VERSION=1  # With camera B (overwrites!)  # Bad!
```

---

## Common Recording Scenarios

### Scenario 1: Quick Test (3 episodes, short timeout)

```bash
TASK="System test" \
DATASET_NAME="system-test" \
VERSION=1 \
EPISODES=3 \
EPISODE_TIME=30 \
RESET_TIME=10 \
./test_record.sh
```

### Scenario 2: Full Dataset (50 episodes, keyboard-controlled)

```bash
TASK="Pick red cube and place in blue box" \
DATASET_NAME="pick-place" \
VERSION=1 \
EPISODES=50 \
./test_record.sh

# Press → after each task completion
# Press → to skip reset when ready
```

### Scenario 3: Bimanual Task (longer episodes)

```bash
TASK="Transfer object from left gripper to right gripper" \
DATASET_NAME="bimanual-handoff" \
VERSION=1 \
EPISODES=30 \
EPISODE_TIME=180 \
./test_record.sh
```

### Scenario 4: Mobile Manipulation

```bash
TASK="Navigate to table and pick object" \
DATASET_NAME="mobile-pick" \
VERSION=1 \
EPISODES=20 \
EPISODE_TIME=240 \
RESET_TIME=90 \
./test_record.sh
```

---

## Dataset Naming Conventions

### Task Categories

```
Manipulation:
- pick-place-v1
- pick-place-precise-v1
- pick-place-cluttered-v1

Bimanual:
- bimanual-handoff-v1
- bimanual-assembly-v1
- bimanual-folding-v1

Mobile:
- mobile-reach-v1
- mobile-navigation-v1
- mobile-search-v1

Contact-Rich:
- drawer-opening-v1
- door-opening-v1
- button-press-v1

Multi-Object:
- table-cleanup-v1
- sorting-objects-v1
- stacking-blocks-v1
```

### Naming Guidelines

- Use lowercase with hyphens
- Be descriptive but concise
- Avoid abbreviations (unless standard)
- Include difficulty if relevant: `-easy`, `-hard`
- Include object details if important: `-red-cube`, `-large-box`

---

## Collaborative Recording Workflow

### Two-Person Team

**Person A (Morning Session):**
```bash
# Record pick-place v1
TASK="Pick cube" DATASET_NAME="pick-place" VERSION=1 EPISODES=25 ./test_record.sh
```

**Person B (Afternoon Session):**
```bash
# Record pick-place v2 (more data)
TASK="Pick cube" DATASET_NAME="pick-place" VERSION=2 EPISODES=25 ./test_record.sh

# OR record different task
TASK="Open drawer" DATASET_NAME="drawer-opening" VERSION=1 EPISODES=20 ./test_record.sh
```

### Dataset Organization

```
Grievous-Robot/
├── pick-place-v1           (Person A, 25 eps, 2025-01-15)
├── pick-place-v2           (Person B, 25 eps, 2025-01-15)
├── pick-place-v3           (Person A, 50 eps, 2025-01-20, improved)
├── drawer-opening-v1       (Person B, 20 eps, 2025-01-16)
├── bimanual-handoff-v1     (Person A, 30 eps, 2025-01-17)
└── mobile-reach-v1         (Person B, 15 eps, 2025-01-18)
```

---

## Troubleshooting

### Issue: "Cannot write to Grievous-Robot"

**Solution:**
```bash
# Verify you're logged in
huggingface-cli whoami

# Verify organization access
./verify_org_access.sh

# If fails, contact org admin for write access
```

### Issue: "Episode timeout reached"

**Solution:**  
Press → earlier! Timeouts are safety nets, not intended workflow.

### Issue: "Wrong episode recorded"

**Solution:**  
Press ← (Left Arrow) immediately to discard and re-record.

### Issue: "Motor overload during shutdown"

**Solution:**  
Support robot arms physically before pressing Ctrl+C.

---

## Data Quality Checklist

Before starting a recording session:

- [ ] Robot calibrated and functioning
- [ ] Cameras providing clear images
- [ ] Lighting consistent
- [ ] Objects positioned correctly
- [ ] Task clearly defined
- [ ] Version number decided
- [ ] HuggingFace login verified

During recording:

- [ ] Perform task smoothly (not too fast/slow)
- [ ] Complete task successfully each episode
- [ ] Use → to end episodes (don't rely on timeout)
- [ ] Reset environment carefully between episodes
- [ ] Monitor for hardware issues

After recording:

- [ ] Check dataset uploaded to HuggingFace
- [ ] Verify episode count is correct
- [ ] Sample check a few episodes
- [ ] Document any issues in dataset card

---

## Advanced: Resuming Recording

If you want to add episodes to an existing dataset:

```bash
# TODO: Implement --resume functionality
# This will append to existing dataset rather than create new version
```

---

## Dataset Card Template

After recording, visit your dataset on HuggingFace and add metadata:

```markdown
---
tags:
- robotics
- grievous
- manipulation
- lerobot
license: apache-2.0
---

# Grievous Pick-Place v1

## Task Description
Pick a red cube from the table and place it in a blue box.

## Recording Details
- **Episodes:** 25
- **Duration:** ~30 seconds per episode
- **Demonstrator:** Researcher A
- **Date:** 2025-01-15
- **Environment:** Lab bench with consistent lighting

## Success Criteria
- Cube successfully grasped
- Cube placed inside box
- No collisions

## Notes
- Some episodes have faster demonstrations
- Episodes 10-15 recorded with slightly different camera angle (adjusted afterward)
```

---

## Reference: Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TASK` | "Test record" | Task description for dataset |
| `VERSION` | 1 | Dataset version number |
| `DATASET_NAME` | "test-record" | Base dataset name |
| `EPISODES` | 50 | Maximum episodes to record |
| `EPISODE_TIME` | 120 | Max seconds per episode (safety timeout) |
| `RESET_TIME` | 60 | Max seconds for reset (safety timeout) |

---

## Quick Reference Card

Print this and keep near your recording station:

```
╔════════════════════════════════════════════════════════════════╗
║                GRIEVOUS RECORDING QUICK REFERENCE              ║
╠════════════════════════════════════════════════════════════════╣
║ KEYBOARD:                                                      ║
║   →   End episode / Skip reset                                ║
║   ←   Re-record episode                                       ║
║   Esc Stop recording                                          ║
╠════════════════════════════════════════════════════════════════╣
║ WORKFLOW:                                                      ║
║   1. Perform task                                             ║
║   2. Press → when done                                        ║
║   3. Reset environment                                        ║
║   4. Press → when ready                                       ║
║   5. Repeat                                                   ║
╠════════════════════════════════════════════════════════════════╣
║ VERSION:                                                       ║
║   New session → Increment version                            ║
║   Same session → Keep version                                ║
╚════════════════════════════════════════════════════════════════╝
```

