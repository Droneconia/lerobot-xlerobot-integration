#!/usr/bin/env python
"""
Transform LeRobot dataset action and observation.state from 12 to 6 or 15 dims, then push to Hub.

- 12 → 6: --arm left (first 6) or --arm right (last 6).
- 12 → 15: pad with zeros.

The new dataset is always pushed to the Hub as {repo_id}_separated (e.g. user/dataset → user/dataset_separated).

Usage (from repo root):
  PYTHONPATH=src python helper-scripts/transform_dataset.py --repo_id USER/DATASET --target_dim 6 [--arm left|right]
  PYTHONPATH=src python helper-scripts/transform_dataset.py --repo_id USER/DATASET --target_dim 15
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import shutil
from pathlib import Path

import numpy as np
from datasets import load_dataset
from huggingface_hub import HfApi

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SOURCE_DIM = 12
TARGET_DIMS = (6, 15)
ARM_CHOICES = ("left", "right")

# Video keys are dataset info keys and folder names: observation.images.left_wrist, etc.
# 6D: remove the wrist camera key for the arm we're not keeping. Always keep head.
# arm=left (keep left 6) -> remove observation.images.right_wrist
# arm=right (keep right 6) -> remove observation.images.left_wrist
WRIST_VIDEO_KEY_TO_REMOVE_6D = {
    "left": "observation.images.right_wrist",
    "right": "observation.images.left_wrist",
}


def _to_6_or_15(arr: list | np.ndarray, target_dim: int, arm: str) -> list[float]:
    """Transform 12D to 6 (left=first 6, right=last 6) or 15 (pad zeros)."""
    a = np.asarray(arr, dtype=np.float32).flatten()
    if target_dim == 6:
        out = a[:6] if arm == "left" else a[6:12]
    else:
        out = np.zeros(15, dtype=np.float32)
        out[: min(12, len(a))] = a[:12]
    return out.tolist()


def _updated_features(features: dict, target_dim: int, arm: str) -> dict:
    """New feature dict with updated action and observation.state shape and names.
    For 6D, also removes the opposite wrist camera key from dataset info
    (observation.images.left_wrist or observation.images.right_wrist). Head camera is never removed."""
    from lerobot.datasets.utils import DEFAULT_FEATURES, _validate_feature_names

    new = dict(features)
    for key in ("action", "observation.state"):
        if key not in new:
            continue
        ft = dict(new[key])
        names = ft.get("names")
        ft["shape"] = (target_dim,)
        if names is not None and len(names) != target_dim:
            if target_dim == 6:
                ft["names"] = list(names)[:6] if arm == "left" else list(names)[6:12]
            else:
                ft["names"] = list(names)[:12] + [f"dim_{i}" for i in range(12, 15)]
        new[key] = ft

    # 6D: remove the wrist camera key from dataset info (same name as the video folder)
    if target_dim == 6:
        key_to_remove = WRIST_VIDEO_KEY_TO_REMOVE_6D.get(arm)
        if key_to_remove and key_to_remove in new:
            new.pop(key_to_remove)

    new = {**new, **DEFAULT_FEATURES}
    _validate_feature_names(new)
    return new


def run(repo_id: str, target_dim: int, arm: str = "left", root: Path | None = None) -> str:
    from lerobot.datasets.lerobot_dataset import CODEBASE_VERSION, LeRobotDataset
    from lerobot.datasets.utils import (
        DEFAULT_CHUNK_SIZE,
        DEFAULT_DATA_FILE_SIZE_IN_MB,
        DEFAULT_DATA_PATH,
        DEFAULT_VIDEO_FILE_SIZE_IN_MB,
        create_empty_dataset_info,
        get_hf_features_from_features,
        write_info,
        write_stats,
    )
    from lerobot.utils.constants import HF_LEROBOT_HOME

    if target_dim not in TARGET_DIMS:
        raise ValueError(f"target_dim must be one of {TARGET_DIMS}, got {target_dim}")
    if target_dim == 6 and arm not in ARM_CHOICES:
        raise ValueError(f"arm must be one of {ARM_CHOICES} when target_dim=6, got {arm!r}")

    # New repo: always {repo_id}_separated
    new_repo_id = f"{repo_id.rstrip('/')}_separated"
    default_root = Path(HF_LEROBOT_HOME)
    src_root = Path(root) if root is not None else default_root / repo_id
    dst_root = default_root / new_repo_id.replace("/", "_")

    src_root = src_root.resolve()
    dst_root = dst_root.resolve()
    if src_root == dst_root:
        raise ValueError(
            "Source and destination would be the same; use a different repo_id or root so the "
            "transformed dataset is written to a new directory."
        )

    logger.info("Loading dataset from %s", src_root)
    dataset = LeRobotDataset(repo_id, root=src_root)
    meta = dataset.meta
    features = meta.features

    if "action" not in features or "observation.state" not in features:
        raise ValueError("Dataset must contain 'action' and 'observation.state'")

    action_dim = features["action"]["shape"][0]
    if action_dim != SOURCE_DIM:
        logger.warning("Source action dim is %s (expected %s); transforming anyway.", action_dim, SOURCE_DIM)

    new_features = _updated_features(features, target_dim, arm)
    # Video keys to keep: for 6D remove the opposite wrist (observation.images.left_wrist / right_wrist)
    all_video_keys = [k for k, ft in features.items() if ft.get("dtype") == "video"]
    if target_dim == 6:
        key_to_remove = WRIST_VIDEO_KEY_TO_REMOVE_6D.get(arm)
        video_keys = [k for k in all_video_keys if k != key_to_remove]
        if key_to_remove and key_to_remove in all_video_keys:
            logger.info("6D %s arm: removing key and folder %s", arm, key_to_remove)
    else:
        video_keys = all_video_keys

    # Build transform for dataset.map()
    def transform_example(example: dict) -> dict:
        out = dict(example)
        if "action" in out:
            out["action"] = _to_6_or_15(out["action"], target_dim, arm)
        if "observation.state" in out:
            out["observation.state"] = _to_6_or_15(out["observation.state"], target_dim, arm)
        return out

    # Load all data with datasets, map, then write back in LeRobot chunk layout
    data_dir = src_root / "data"
    parquet_paths = sorted(data_dir.glob("*/*.parquet"))
    if not parquet_paths:
        raise FileNotFoundError(f"No parquet files in {data_dir}")

    hf_features = get_hf_features_from_features(new_features)
    dst_root.mkdir(parents=True, exist_ok=True)
    (dst_root / "meta").mkdir(exist_ok=True)
    (dst_root / "data").mkdir(exist_ok=True)

    for src_path in parquet_paths:
        # datasets: load one parquet, map, save
        ds = load_dataset("parquet", data_files=[str(src_path)], split="train")
        ds = ds.map(transform_example, desc="Transform", batched=False, num_proc=1)
        ds = ds.cast(hf_features)

        rel = src_path.relative_to(src_root)
        parts = rel.parts
        chunk_idx = int(parts[1].split("-")[1])
        file_idx = int(parts[2].split("-")[1].split(".")[0])
        dst_path = dst_root / DEFAULT_DATA_PATH.format(chunk_index=chunk_idx, file_index=file_idx)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        ds.to_parquet(str(dst_path))

    # Meta: info, episodes, tasks, stats, videos
    info = create_empty_dataset_info(
        CODEBASE_VERSION,
        meta.fps,
        new_features,
        use_videos=len(video_keys) > 0,
        robot_type=meta.robot_type,
        chunks_size=DEFAULT_CHUNK_SIZE,
        data_files_size_in_mb=DEFAULT_DATA_FILE_SIZE_IN_MB,
        video_files_size_in_mb=DEFAULT_VIDEO_FILE_SIZE_IN_MB,
    )
    info["total_episodes"] = meta.total_episodes
    info["total_frames"] = meta.total_frames
    info["total_tasks"] = meta.info.get("total_tasks", 0)
    info["splits"] = meta.info.get("splits", {"train": f"0:{meta.total_episodes}"})
    write_info(info, dst_root)

    for name in ("meta/episodes", "meta/tasks.parquet", "meta/subtasks.parquet"):
        src = src_root / name
        if src.exists():
            dst = dst_root / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy(src, dst)

    if meta.stats:
        filtered = {k: v for k, v in meta.stats.items() if k in new_features}
        write_stats(filtered, dst_root)

    # Copy only the video folders we're keeping (for 6D we dropped one wrist camera)
    src_videos = src_root / "videos"
    if src_videos.exists():
        (dst_root / "videos").mkdir(exist_ok=True)
        for vkey in video_keys:
            src_v = src_videos / vkey
            if src_v.exists():
                shutil.copytree(src_v, dst_root / "videos" / vkey, dirs_exist_ok=True)

    # Push to Hub
    logger.info("Pushing to Hub as %s", new_repo_id)
    api = HfApi()
    api.create_repo(repo_id=new_repo_id, repo_type="dataset", exist_ok=True)
    api.upload_folder(
        folder_path=str(dst_root),
        repo_id=new_repo_id,
        repo_type="dataset",
        ignore_patterns=["*.pyc", "__pycache__", ".DS_Store"],
    )

    # Push dataset card (README) like LeRobot does
    from lerobot.datasets.utils import create_lerobot_dataset_card
    card = create_lerobot_dataset_card(
        dataset_info=info,
        license="apache-2.0",
    )
    card.push_to_hub(repo_id=new_repo_id, repo_type="dataset")

    # Tag with codebase version (e.g. v3.0) like LeRobot push_to_hub
    from huggingface_hub.errors import RevisionNotFoundError
    with contextlib.suppress(RevisionNotFoundError):
        api.delete_tag(repo_id=new_repo_id, tag=CODEBASE_VERSION, repo_type="dataset")
    api.create_tag(repo_id=new_repo_id, tag=CODEBASE_VERSION, revision=None, repo_type="dataset")
    logger.info("Tagged repo with %s", CODEBASE_VERSION)

    logger.info("Done. Dataset available at https://huggingface.co/datasets/%s", new_repo_id)
    return new_repo_id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transform action/observation.state 12→6 or 12→15 and push to Hub as {repo_id}_separated.",
    )
    parser.add_argument("--repo_id", required=True, help="LeRobot dataset repo_id (e.g. username/dataset-name).")
    parser.add_argument("--target_dim", type=int, required=True, choices=[6, 15], help="Target dimension (6 or 15).")
    parser.add_argument(
        "--arm",
        default="left",
        choices=["left", "right"],
        help="When target_dim=6: left=first 6, right=last 6. Ignored for 15.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Local dataset root (default: HF_LEROBOT_HOME / repo_id).",
    )
    args = parser.parse_args()

    run(repo_id=args.repo_id, target_dim=args.target_dim, arm=args.arm, root=args.root)


if __name__ == "__main__":
    main()
