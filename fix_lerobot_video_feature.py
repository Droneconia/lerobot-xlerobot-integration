#!/usr/bin/env python3
"""
Fix LeRobot v3.0 dataset feature-key mismatches by renaming a feature key across
the on-disk dataset artifacts.

Why this exists:
LeRobot merge (`aggregate.validate_all_metadata`) requires *exact* equality of the
`features` dict across datasets. For video features, the feature key must also
match the episode metadata column namespace:

  videos/<video_feature_key>/{chunk_index,file_index,from_timestamp,to_timestamp}

If a dataset's `meta/info.json` and `videos/<key>/...` directory use one key (e.g.
`observation.images.left_head`) but `meta/episodes/*.parquet` still references
another (e.g. `observation.images.left_top`), merges will fail and/or the dataset
loader will not find the correct video mapping.

Important:
`meta/episodes/*.parquet` can also contain per-episode statistics columns under:

  stats/<feature_key>/{min,max,mean,std,count,q..}

If those stats columns still use the old feature_key, dataset editing operations
like `delete_episodes` can fail during stats aggregation. This script renames both
the `videos/<feature_key>/...` columns AND any `stats/<feature_key>/...` columns.

This script can rename, in-place:
- `meta/info.json` (features dict key)
- `meta/stats.json` (dataset-level stats key)
- `meta/episodes/**/*.parquet` column namespaces:
  - `videos/<feature_key>/...`
  - `stats/<feature_key>/...`
- `videos/<feature_key>/` folder name

By default it only changes `meta/episodes/**/*.parquet` (the minimal fix for many
failures). Enable the other edits via flags.

Example:
  conda run -n grievous python fix_lerobot_video_feature_key_in_episodes.py \
    --dataset_dir hf_datasets/table-sweep-112ep-merged \
    --from_key observation.images.left_top \
    --to_key observation.images.left_head
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pyarrow.parquet as pq


def _episode_parquet_paths(dataset_dir: Path) -> list[Path]:
    episodes_dir = dataset_dir / "meta" / "episodes"
    return sorted(episodes_dir.glob("*/*.parquet"))


def _rename_mapping(from_key: str, to_key: str) -> dict[str, str]:
    """Map the 4 video episode-metadata columns from from_key -> to_key."""
    return {
        f"videos/{from_key}/chunk_index": f"videos/{to_key}/chunk_index",
        f"videos/{from_key}/file_index": f"videos/{to_key}/file_index",
        f"videos/{from_key}/from_timestamp": f"videos/{to_key}/from_timestamp",
        f"videos/{from_key}/to_timestamp": f"videos/{to_key}/to_timestamp",
    }


def _schema_names(parquet_path: Path) -> list[str]:
    return list(pq.read_schema(parquet_path).names)


def _now_suffix() -> str:
    # Example: 20260219T121016
    return _dt.datetime.now().strftime("%Y%m%dT%H%M%S")


def _backup_file(path: Path, *, suffix: str) -> Path:
    backup_path = path.with_name(path.name + f".bak.{suffix}")
    backup_path.write_bytes(path.read_bytes())
    return backup_path


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    # Keep it readable/diffable.
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, sort_keys=True)
        f.write("\n")


def _stats_rename_mapping(schema_names: list[str], from_key: str, to_key: str) -> dict[str, str]:
    """Return a mapping for any `stats/<from_key>/...` columns present in schema_names."""
    from_prefix = f"stats/{from_key}/"
    to_prefix = f"stats/{to_key}/"
    mapping: dict[str, str] = {}
    for col in schema_names:
        if col.startswith(from_prefix):
            mapping[col] = to_prefix + col[len(from_prefix) :]
    return mapping


def _build_parquet_rename_map(schema_names: list[str], from_key: str, to_key: str) -> dict[str, str]:
    """Build a rename mapping for one `meta/episodes` parquet file.

    - Renames the 4 `videos/<from_key>/*` columns iff they are present (must be all-or-nothing).
    - Renames all `stats/<from_key>/*` columns that are present.
    """
    schema_set = set(schema_names)

    # Video mapping columns: require all 4 if any are present.
    video_map = _rename_mapping(from_key, to_key)
    present_video = [c for c in video_map.keys() if c in schema_set]
    if present_video and len(present_video) != 4:
        missing = sorted([c for c in video_map.keys() if c not in schema_set])
        raise ValueError(
            "Found only a subset of expected video mapping columns for from_key.\n"
            f"present={sorted(present_video)}\nmissing={missing}"
        )

    mapping: dict[str, str] = {}
    if len(present_video) == 4:
        mapping.update(video_map)

    # Stats columns: rename whatever exists.
    mapping.update(_stats_rename_mapping(schema_names, from_key, to_key))
    return mapping


def _scan_remaining(
    episode_paths: Iterable[Path], *, from_key: str, to_key: str
) -> tuple[list[tuple[Path, list[str]]], list[tuple[Path, list[str]]]]:
    """Return (remaining_from, present_to) for videos/stats columns."""
    remaining_from: list[tuple[Path, list[str]]] = []
    present_to: list[tuple[Path, list[str]]] = []
    from_markers = (f"videos/{from_key}/", f"stats/{from_key}/")
    to_markers = (f"videos/{to_key}/", f"stats/{to_key}/")
    for p in episode_paths:
        names = _schema_names(p)
        rem = [c for c in names if c.startswith(from_markers)]
        if rem:
            remaining_from.append((p, rem))
        pres = [c for c in names if c.startswith(to_markers)]
        if pres:
            present_to.append((p, pres))
    return remaining_from, present_to


def rename_feature_key_in_episode_metadata(
    *,
    dataset_dir: Path,
    from_key: str,
    to_key: str,
    backup: bool,
    check_only: bool,
) -> None:
    if not dataset_dir.exists():
        raise FileNotFoundError(f"dataset_dir does not exist: {dataset_dir}")

    episode_paths = _episode_parquet_paths(dataset_dir)
    if len(episode_paths) == 0:
        raise FileNotFoundError(f"No episode parquet files found under: {dataset_dir / 'meta/episodes'}")

    per_file_map: dict[Path, dict[str, str]] = {}
    for p in episode_paths:
        mapping = _build_parquet_rename_map(_schema_names(p), from_key, to_key)
        if mapping:
            per_file_map[p] = mapping

    targets = sorted(per_file_map.keys())
    print(f"[info] dataset_dir={dataset_dir}")
    print(f"[info] episode_parquets={len(episode_paths)} targets_with_from_key={len(targets)}")
    print(f"[info] from_key={from_key} -> to_key={to_key}")

    if len(targets) == 0:
        # This is not necessarily an error: dataset may already be fixed.
        remaining_from, _present_to = _scan_remaining(episode_paths, from_key=from_key, to_key=to_key)
        if remaining_from:
            # This would be surprising: no renames proposed, yet from_key appears.
            print("[warn] from_key columns still appear in some files, but no rename mapping was built.")
            for p, cols in remaining_from:
                print(f"  - {p}: {cols[:10]}")
            raise SystemExit(2)
        print("[ok] No from_key columns found. Nothing to do.")
        return

    # Preflight: ensure we won't clobber existing 'to_key' columns accidentally.
    collisions: list[tuple[Path, list[str]]] = []
    for p in targets:
        names = set(_schema_names(p))
        mapping = per_file_map[p]
        present_to = sorted([dst for dst in mapping.values() if dst in names])
        if present_to:
            collisions.append((p, present_to))

    if collisions:
        msg = "\n".join([f"  - {p}: existing_to_cols={cols}" for p, cols in collisions])
        raise ValueError(
            "Refusing to rename because some files already contain to_key columns.\n"
            "This could indicate a partial previous fix or a mixed-schema dataset.\n"
            + msg
        )

    if check_only:
        print("[check-only] Would rename columns in:")
        for p in targets:
            mapping = per_file_map[p]
            n_video = sum(1 for k in mapping if k.startswith("videos/"))
            n_stats = sum(1 for k in mapping if k.startswith("stats/"))
            print(f"  - {p}  (video_cols={n_video}, stats_cols={n_stats})")
        return

    backup_suffix = _now_suffix()
    for p in targets:
        if backup:
            b = _backup_file(p, suffix=backup_suffix)
            print(f"[backup] {p} -> {b}")

        df = pd.read_parquet(p)
        df = df.rename(columns=per_file_map[p])
        df.to_parquet(p, index=False)
        print(f"[write] updated {p}")

    # Post-verify using schema only (fast).
    remaining_from, _present_to = _scan_remaining(episode_paths, from_key=from_key, to_key=to_key)
    if remaining_from:
        print("[error] Post-verification failed: from_key columns still present.")
        for p, cols in remaining_from:
            print(f"  - {p}: {cols[:10]}")
        raise SystemExit(2)

    print("[ok] Episode metadata columns renamed successfully and verified (no from_key columns remain).")


def rename_feature_key_in_info_json(
    *, dataset_dir: Path, from_key: str, to_key: str, backup: bool, check_only: bool
) -> bool:
    """Rename feature key in `meta/info.json` features dict.

    Returns True if a change would be made / was made.
    """
    info_path = dataset_dir / "meta" / "info.json"
    if not info_path.exists():
        raise FileNotFoundError(f"Missing info.json: {info_path}")

    info = _load_json(info_path)
    features = info.get("features", None)
    if not isinstance(features, dict):
        raise ValueError(f"Expected info['features'] to be a dict in {info_path}")

    if from_key not in features:
        return False
    if to_key in features:
        raise ValueError(f"Refusing to rename info.json: destination key already exists: {to_key}")

    new_features = dict(features)
    new_features[to_key] = new_features.pop(from_key)
    info["features"] = new_features

    if check_only:
        print(f"[check-only] Would update {info_path} (features key rename)")
        return True

    if backup:
        b = _backup_file(info_path, suffix=_now_suffix())
        print(f"[backup] {info_path} -> {b}")
    _write_json(info_path, info)
    print(f"[write] updated {info_path}")
    return True


def rename_feature_key_in_stats_json(
    *, dataset_dir: Path, from_key: str, to_key: str, backup: bool, check_only: bool
) -> bool:
    """Rename feature key in `meta/stats.json` top-level dict.

    Returns True if a change would be made / was made.
    """
    stats_path = dataset_dir / "meta" / "stats.json"
    if not stats_path.exists():
        # Some datasets may not have stats.
        return False

    stats = _load_json(stats_path)
    if not isinstance(stats, dict):
        raise ValueError(f"Expected stats.json to be a dict: {stats_path}")

    if from_key not in stats:
        return False
    if to_key in stats:
        raise ValueError(f"Refusing to rename stats.json: destination key already exists: {to_key}")

    new_stats = dict(stats)
    new_stats[to_key] = new_stats.pop(from_key)

    if check_only:
        print(f"[check-only] Would update {stats_path} (top-level key rename)")
        return True

    if backup:
        b = _backup_file(stats_path, suffix=_now_suffix())
        print(f"[backup] {stats_path} -> {b}")
    _write_json(stats_path, new_stats)
    print(f"[write] updated {stats_path}")
    return True


def rename_videos_dir(
    *, dataset_dir: Path, from_key: str, to_key: str, check_only: bool
) -> bool:
    """Rename `videos/<from_key>/` directory to `videos/<to_key>/`.

    Returns True if a change would be made / was made.
    """
    videos_dir = dataset_dir / "videos"
    src = videos_dir / from_key
    dst = videos_dir / to_key

    if not src.exists():
        return False
    if dst.exists():
        raise ValueError(f"Refusing to rename videos dir: destination already exists: {dst}")

    if check_only:
        print(f"[check-only] Would rename directory {src} -> {dst}")
        return True

    src.rename(dst)
    print(f"[write] renamed directory {src} -> {dst}")
    return True


def confirm_no_from_key_artifacts(*, dataset_dir: Path, from_key: str) -> None:
    """Fail-fast confirmation scan for leftover from_key artifacts."""
    leftovers: list[str] = []

    # meta/info.json
    info_path = dataset_dir / "meta" / "info.json"
    if info_path.exists():
        info = _load_json(info_path)
        feats = info.get("features", {})
        if isinstance(feats, dict) and from_key in feats:
            leftovers.append(f"{info_path}: features still contains '{from_key}'")

    # meta/stats.json
    stats_path = dataset_dir / "meta" / "stats.json"
    if stats_path.exists():
        stats = _load_json(stats_path)
        if isinstance(stats, dict) and from_key in stats:
            leftovers.append(f"{stats_path}: top-level stats still contains '{from_key}'")

    # videos folder
    if (dataset_dir / "videos" / from_key).exists():
        leftovers.append(f"{dataset_dir / 'videos' / from_key}: directory still exists")

    # episode parquet schemas
    ep_paths = _episode_parquet_paths(dataset_dir)
    from_markers = (f"videos/{from_key}/", f"stats/{from_key}/")
    for p in ep_paths:
        names = _schema_names(p)
        hits = [c for c in names if c.startswith(from_markers)]
        if hits:
            leftovers.append(f"{p}: remaining columns like {hits[:5]}")

    if leftovers:
        print("[error] Confirmation failed: from_key artifacts remain:")
        for msg in leftovers:
            print(f"  - {msg}")
        raise SystemExit(2)

    print("[ok] Confirmation passed: no from_key artifacts found in info/stats/episodes/videos.")


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Rename a LeRobot v3.0 feature key across dataset artifacts (episodes parquet, and optionally meta/videos)."
        )
    )
    p.add_argument(
        "--dataset_dir",
        type=Path,
        default=Path("hf_datasets/table-sweep-112ep-merged"),
        help="Path to the dataset root directory (relative to repo root by default).",
    )
    p.add_argument(
        "--from_key",
        type=str,
        default="observation.images.left_top",
        help="Feature key currently present (e.g. 'observation.images.left_top').",
    )
    p.add_argument(
        "--to_key",
        type=str,
        default="observation.images.left_head",
        help="Desired feature key (e.g. 'observation.images.left_head').",
    )
    p.add_argument(
        "--edit_info_json",
        action="store_true",
        help="Also rename the feature key in meta/info.json (features dict key).",
    )
    p.add_argument(
        "--edit_stats_json",
        action="store_true",
        help="Also rename the feature key in meta/stats.json (top-level key).",
    )
    p.add_argument(
        "--rename_videos_dir",
        action="store_true",
        help="Also rename videos/<from_key>/ directory to videos/<to_key>/ when present.",
    )
    p.add_argument(
        "--confirm",
        action="store_true",
        help="After applying changes, scan and assert no from_key artifacts remain.",
    )
    p.add_argument(
        "--no_backup",
        action="store_true",
        help="Disable writing .bak.<timestamp> backups next to each modified parquet.",
    )
    p.add_argument(
        "--check_only",
        action="store_true",
        help="Only report which files would change; do not modify anything.",
    )
    return p.parse_args(argv)


def main(argv: list[str]) -> None:
    args = parse_args(argv)
    # Minimal fix is always episode metadata (videos/stats column namespaces).
    rename_feature_key_in_episode_metadata(
        dataset_dir=args.dataset_dir,
        from_key=args.from_key,
        to_key=args.to_key,
        backup=not args.no_backup,
        check_only=args.check_only,
    )

    if args.edit_info_json:
        rename_feature_key_in_info_json(
            dataset_dir=args.dataset_dir,
            from_key=args.from_key,
            to_key=args.to_key,
            backup=not args.no_backup,
            check_only=args.check_only,
        )

    if args.edit_stats_json:
        rename_feature_key_in_stats_json(
            dataset_dir=args.dataset_dir,
            from_key=args.from_key,
            to_key=args.to_key,
            backup=not args.no_backup,
            check_only=args.check_only,
        )

    if args.rename_videos_dir:
        rename_videos_dir(
            dataset_dir=args.dataset_dir,
            from_key=args.from_key,
            to_key=args.to_key,
            check_only=args.check_only,
        )

    if args.confirm and not args.check_only:
        confirm_no_from_key_artifacts(dataset_dir=args.dataset_dir, from_key=args.from_key)


if __name__ == "__main__":
    main(sys.argv[1:])

