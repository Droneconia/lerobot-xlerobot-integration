#!/usr/bin/env python
"""
Rename video (and other feature) keys throughout a LeRobot dataset so it can merge with others.

Same local vs repo behavior as transform_dataset: repo_id is required; --root is optional.
If omitted, uses HF_LEROBOT_HOME / repo_id (downloads from Hub if missing). If --root is
given, that path is the dataset root (folder with meta/, data/, videos/). After renaming,
uploads back to the same repo (overwriting previous content).

Usage (from repo root):
  PYTHONPATH=src python helper-scripts/convert_names.py --repo_id Grievous-Robot/DATASET_NAME --rename observation.images.left_wrist observation.images.wrist_left
  PYTHONPATH=src python helper-scripts/convert_names.py --repo_id Grievous-Robot/DATASET_NAME --rename old_key new_key --root /path/to/dataset
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from datasets import load_dataset
from huggingface_hub import HfApi, snapshot_download

from lerobot.datasets.utils import (
    EPISODES_DIR,
    INFO_PATH,
    STATS_PATH,
    load_info,
    load_stats,
    write_info,
    write_stats,
)
from lerobot.utils.constants import HF_LEROBOT_HOME

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

VIDEOS_DIR = "videos"


def rename_in_info(root: Path, renames: list[tuple[str, str]]) -> None:
    if not (root / INFO_PATH).exists():
        return
    info = load_info(root)
    features = info.get("features") or {}
    for old_key, new_key in renames:
        if old_key in features:
            features[new_key] = features.pop(old_key)
            logger.info("info.json: %s -> %s", old_key, new_key)
    write_info(info, root)


def rename_in_stats(root: Path, renames: list[tuple[str, str]]) -> None:
    stats = load_stats(root)
    if stats is None:
        return
    for old_key, new_key in renames:
        if old_key in stats:
            stats[new_key] = stats.pop(old_key)
            logger.info("stats.json: %s -> %s", old_key, new_key)
    write_stats(stats, root)


def rename_video_folders(root: Path, renames: list[tuple[str, str]]) -> None:
    videos_root = root / VIDEOS_DIR
    if not videos_root.exists():
        return
    for old_key, new_key in renames:
        src = videos_root / old_key
        dst = videos_root / new_key
        if src.exists():
            if dst.exists():
                logger.warning("Skipping folder rename %s -> %s (destination exists)", old_key, new_key)
            else:
                src.rename(dst)
                logger.info("videos: %s -> %s", old_key, new_key)


def _column_rename_map(cols: list[str], renames: list[tuple[str, str]]) -> dict[str, str]:
    new_cols = {}
    for c in cols:
        new_c = c
        for old_key, new_key in renames:
            if c.startswith(f"videos/{old_key}/"):
                new_c = f"videos/{new_key}/" + c[len(f"videos/{old_key}/") :]
                break
            if c.startswith(f"stats/{old_key}/"):
                new_c = f"stats/{new_key}/" + c[len(f"stats/{old_key}/") :]
                break
        if new_c != c:
            new_cols[c] = new_c
    return new_cols


def rename_in_episodes(root: Path, renames: list[tuple[str, str]]) -> None:
    episodes_root = root / EPISODES_DIR
    if not episodes_root.exists():
        return
    parquet_files = sorted(episodes_root.glob("*/*.parquet"))
    for path in parquet_files:
        ds = load_dataset("parquet", data_files=[str(path)], split="train")
        cols = ds.column_names
        new_cols = _column_rename_map(cols, renames)
        if not new_cols:
            continue
        ds = ds.rename_columns(new_cols)
        ds.to_parquet(str(path))
        logger.debug("episodes %s: renamed %s", path.relative_to(root), list(new_cols.keys()))
    if parquet_files:
        logger.info("Updated %d episode parquet file(s)", len(parquet_files))


def run(
    repo_id: str,
    renames: list[tuple[str, str]],
    root: Path | None = None,
    push_to_hub: bool = True,
) -> Path:
    # Same local vs repo logic as transform_dataset: root is optional; when omitted use HF_LEROBOT_HOME / repo_id
    default_root = Path(HF_LEROBOT_HOME)
    root = Path(root) if root is not None else default_root / repo_id
    root = root.resolve()
    if not root.is_dir():
        logger.info("Dataset not found locally; downloading from Hub...")
        root = Path(snapshot_download(repo_id=repo_id, repo_type="dataset", local_dir=str(root)))
    if not root.is_dir():
        raise FileNotFoundError(f"Dataset root not found: {root}")

    if not renames:
        raise ValueError("Provide at least one --rename OLD NEW")

    for old_key, new_key in renames:
        if old_key == new_key:
            raise ValueError(f"Old and new key must differ: {old_key!r}")

    logger.info("Renaming in %s", root)
    rename_in_info(root, renames)
    rename_in_stats(root, renames)
    rename_video_folders(root, renames)
    rename_in_episodes(root, renames)

    if push_to_hub:
        # Upload back to the same repo (overwrite)
        logger.info("Uploading to Hub %s (overwriting previous content)...", repo_id)
        api = HfApi()
        api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)
        # Remove old video folders from the Hub so renamed names don't leave stale paths
        old_keys = [old_k for old_k, _ in renames]
        delete_patterns = [f"videos/{k}/*" for k in old_keys]
        api.upload_folder(
            folder_path=str(root),
            repo_id=repo_id,
            repo_type="dataset",
            commit_message="Convert video/feature names (convert_names.py)",
            ignore_patterns=["*.pyc", "__pycache__", ".DS_Store", ".cache"],
            delete_patterns=delete_patterns if delete_patterns else None,
        )
        logger.info("Done. Repo %s updated on the Hub.", repo_id)
    else:
        logger.info("Done. Run without --no-push to upload to the Hub.")
    return root


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rename video/feature keys throughout a LeRobot dataset (info, stats, videos folder, episodes).",
    )
    parser.add_argument(
        "--repo_id",
        required=True,
        help="Dataset repo_id (e.g. Grievous-Robot/table-sweep-granular-sweep-20260222_172001_separated).",
    )
    parser.add_argument(
        "--rename",
        action="append",
        nargs=2,
        metavar=("OLD", "NEW"),
        default=[],
        help="Rename key OLD to NEW. Can be repeated for multiple renames.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Local dataset root (folder with meta/, data/, videos/). If omitted, uses HF_LEROBOT_HOME / repo_id.",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Only download and rename locally; do not upload back to the Hub.",
    )
    args = parser.parse_args()

    renames = [tuple(r) for r in args.rename]
    run(
        repo_id=args.repo_id,
        renames=renames,
        root=args.root,
        push_to_hub=not args.no_push,
    )


if __name__ == "__main__":
    main()
