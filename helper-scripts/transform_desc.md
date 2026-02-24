# Transform action/observation dimensions (LeRobot datasets)

Reference for changing action and observation state from 12D to 6D or 15D. The actual implementation is **`transform_dataset.py`** in this folder.

## LeRobot dataset feature schema (this project)

**Original (12D):**

```json
{
  "action": {
    "dtype": "float32",
    "shape": [12],
    "names": [
      "left_shoulder_pan.pos", "left_shoulder_lift.pos", "left_elbow_flex.pos",
      "left_wrist_flex.pos", "left_wrist_roll.pos", "left_gripper.pos",
      "right_shoulder_pan.pos", "right_shoulder_lift.pos", "right_elbow_flex.pos",
      "right_wrist_flex.pos", "right_wrist_roll.pos", "right_gripper.pos"
    ]
  },
  "observation.state": {
    "dtype": "float32",
    "shape": [12],
    "names": ["...same as action names"]
  },
  "observation.images.left_head": { "dtype": "video", "shape": [480, 640, 3] },
  "observation.images.left_wrist": { "dtype": "video", "shape": [480, 640, 3] },
  "observation.images.right_wrist": { "dtype": "video", "shape": [480, 640, 3] },
  "timestamp": { "dtype": "float32", "shape": [1] },
  "frame_index": { "dtype": "int64", "shape": [1] },
  "episode_index": { "dtype": "int64", "shape": [1] },
  "index": { "dtype": "int64", "shape": [1] },
  "task_index": { "dtype": "int64", "shape": [1] }
}
```

- **12 → 6:** Use first 6 (left arm) or last 6 (right arm); drop the opposite wrist camera (head camera kept).
- **12 → 15:** Pad action and observation.state with 3 zeros.

## Approach (matches `transform_dataset.py`)

1. **Load** with `LeRobotDataset`, then use `datasets.load_dataset("parquet", data_dir=...)` for the data splits.
2. **Transform** with `.map()` (slice or pad actions and observation.state).
3. **Schema** with `Features` + `.cast()` so `action` and `observation.state` have the new `Sequence(Value('float32'), length=N)`.
4. **Write** LeRobot layout: chunked parquet under `data/`, copy/update `meta/` (info, stats, episodes, tasks). For 6D, remove one wrist video from `info`, stats, and `videos/`.
5. **Push** with `HfApi().upload_folder()` to `{repo_id}_separated`, then dataset card and codebase version tag.

## Prerequisites

```bash
huggingface-cli login
```

## Usage

See `transform_dataset.py --help` and `dataset_changes.md` for copy-paste commands per dataset.
