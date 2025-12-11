#!/usr/bin/env python
"""
Script to push LeRobot training checkpoints to HuggingFace Hub.

This script can push individual checkpoints or all checkpoints from a training run.
By default, it pushes the FULL checkpoint (both pretrained_model/ and training_state/),
which allows you to resume training later. It handles authentication, creates repos
if needed, and optionally deletes local checkpoints after successful upload to save disk space.

Usage:
    # Push a single full checkpoint (default: includes training_state for resuming)
    python push_checkpoint_to_hub.py \
        --checkpoint_dir /workspace/outputs/smolvla_finetuned/checkpoints/005000 \
        --repo_id Grievous-Robot/smolvla_finetuned_5k \
        --delete_after_push

    # Push all checkpoints from a training run
    python push_checkpoint_to_hub.py \
        --output_dir /workspace/outputs/smolvla_finetuned \
        --repo_prefix Grievous-Robot/smolvla_finetuned \
        --delete_after_push

    # Push only pretrained_model (for inference only, cannot resume training)
    python push_checkpoint_to_hub.py \
        --checkpoint_dir /workspace/outputs/smolvla_finetuned/checkpoints/005000 \
        --repo_id Grievous-Robot/smolvla_finetuned_5k \
        --pretrained_only
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from huggingface_hub import HfApi, login
from huggingface_hub.utils import HfHubHTTPError

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def push_checkpoint(
    checkpoint_dir: Path,
    repo_id: str,
    pretrained_only: bool = False,
    private: bool = False,
    delete_after_push: bool = False,
    token: Optional[str] = None,
) -> bool:
    """
    Push a single checkpoint to HuggingFace Hub.

    Args:
        checkpoint_dir: Path to the checkpoint directory (e.g., checkpoints/005000)
        repo_id: HuggingFace Hub repository ID (e.g., "org/model_name")
        pretrained_only: If True, only push pretrained_model/ (for inference). If False, push entire checkpoint.
        private: Whether to create a private repository
        delete_after_push: If True, delete local checkpoint after successful push
        token: HuggingFace token (if None, uses cached token from huggingface-cli login)

    Returns:
        True if successful, False otherwise
    """
    checkpoint_dir = Path(checkpoint_dir).resolve()

    if not checkpoint_dir.exists():
        logger.error(f"Checkpoint directory does not exist: {checkpoint_dir}")
        return False

    # Determine what to push
    if pretrained_only:
        source_dir = checkpoint_dir / "pretrained_model"
        if not source_dir.exists():
            logger.error(f"pretrained_model directory not found in {checkpoint_dir}")
            return False
        logger.info(f"Pushing only pretrained_model from {checkpoint_dir} (for inference only)")
    else:
        source_dir = checkpoint_dir
        # Verify both directories exist for full checkpoint
        pretrained_dir = checkpoint_dir / "pretrained_model"
        training_state_dir = checkpoint_dir / "training_state"
        if not pretrained_dir.exists():
            logger.error(f"pretrained_model directory not found in {checkpoint_dir}")
            return False
        if not training_state_dir.exists():
            logger.warning(f"training_state directory not found in {checkpoint_dir}. This checkpoint cannot be used to resume training.")
        logger.info(f"Pushing full checkpoint from {checkpoint_dir} (includes training_state for resuming)")

    # Initialize HuggingFace API
    api = HfApi(token=token)

    try:
        # Create repo if it doesn't exist
        logger.info(f"Creating/verifying repository: {repo_id}")
        api.create_repo(repo_id=repo_id, private=private, exist_ok=True, repo_type="model")

        # Upload the checkpoint
        logger.info(f"Uploading checkpoint to {repo_id}...")
        commit_info = api.upload_folder(
            repo_id=repo_id,
            repo_type="model",
            folder_path=str(source_dir),
            commit_message=f"Upload checkpoint from {checkpoint_dir.name}",
            allow_patterns=["*.safetensors", "*.json", "*.yaml", "*.md", "*.txt"],
            ignore_patterns=["*.tmp", "*.log", "__pycache__"],
        )

        logger.info(f"✓ Successfully pushed to {commit_info.repo_url.url}")

        # Optionally delete local checkpoint after successful push
        if delete_after_push:
            logger.info(f"Deleting local checkpoint: {checkpoint_dir}")
            import shutil

            shutil.rmtree(checkpoint_dir)
            logger.info(f"✓ Deleted local checkpoint")

        return True

    except HfHubHTTPError as e:
        logger.error(f"Failed to push checkpoint: {e}")
        if "401" in str(e):
            logger.error("Authentication failed. Please run 'huggingface-cli login' or provide --token")
        return False
    except Exception as e:
        logger.error(f"Unexpected error while pushing checkpoint: {e}")
        return False


def push_all_checkpoints(
    output_dir: Path,
    repo_prefix: str,
    pretrained_only: bool = False,
    private: bool = False,
    delete_after_push: bool = False,
    token: Optional[str] = None,
) -> None:
    """
    Push all checkpoints from a training run to HuggingFace Hub.

    Each checkpoint will be pushed to a separate repo with the step number as suffix.

    Args:
        output_dir: Path to the training output directory (contains checkpoints/ subdirectory)
        repo_prefix: Prefix for repository names (e.g., "org/model_name" -> "org/model_name_5k")
        pretrained_only: If True, only push pretrained_model/ from each checkpoint
        private: Whether to create private repositories
        delete_after_push: If True, delete local checkpoints after successful push
        token: HuggingFace token (if None, uses cached token from huggingface-cli login)
    """
    output_dir = Path(output_dir).resolve()
    checkpoints_dir = output_dir / "checkpoints"

    if not checkpoints_dir.exists():
        logger.error(f"Checkpoints directory not found: {checkpoints_dir}")
        return

    # Find all checkpoint directories (numeric names like 005000, 010000, etc.)
    checkpoint_dirs = sorted(
        [d for d in checkpoints_dir.iterdir() if d.is_dir() and d.name.isdigit()],
        key=lambda x: int(x.name),
    )

    if not checkpoint_dirs:
        logger.warning(f"No checkpoint directories found in {checkpoints_dir}")
        return

    logger.info(f"Found {len(checkpoint_dirs)} checkpoints to push")

    # Push each checkpoint
    successful = 0
    failed = 0

    for checkpoint_dir in checkpoint_dirs:
        step = checkpoint_dir.name
        # Convert step number to readable format (e.g., "005000" -> "5k")
        step_num = int(step)
        if step_num >= 1000:
            step_suffix = f"{step_num // 1000}k"
        else:
            step_suffix = step

        repo_id = f"{repo_prefix}_{step_suffix}"

        logger.info(f"\n{'='*60}")
        logger.info(f"Pushing checkpoint {step} to {repo_id}")
        logger.info(f"{'='*60}")

        success = push_checkpoint(
            checkpoint_dir=checkpoint_dir,
            repo_id=repo_id,
            pretrained_only=pretrained_only,
            private=private,
            delete_after_push=delete_after_push,
            token=token,
        )

        if success:
            successful += 1
        else:
            failed += 1

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"Push Summary: {successful} successful, {failed} failed")
    logger.info(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(
        description="Push LeRobot training checkpoints to HuggingFace Hub",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Input options (mutually exclusive)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--checkpoint_dir",
        type=Path,
        help="Path to a single checkpoint directory (e.g., checkpoints/005000)",
    )
    input_group.add_argument(
        "--output_dir",
        type=Path,
        help="Path to training output directory (will push all checkpoints)",
    )

    # Repository options
    repo_group = parser.add_argument_group("Repository options")
    repo_group.add_argument(
        "--repo_id",
        type=str,
        help="HuggingFace Hub repository ID for single checkpoint (e.g., 'org/model_name')",
    )
    repo_group.add_argument(
        "--repo_prefix",
        type=str,
        help="Repository prefix for all checkpoints (e.g., 'org/model_name' -> 'org/model_name_5k')",
    )
    repo_group.add_argument(
        "--private",
        action="store_true",
        help="Create private repositories (default: public)",
    )

    # Push options
    push_group = parser.add_argument_group("Push options")
    push_group.add_argument(
        "--pretrained_only",
        action="store_true",
        help="Only push pretrained_model/ directory (for inference only, cannot resume training). Default: push full checkpoint (pretrained_model + training_state)",
    )
    push_group.add_argument(
        "--delete_after_push",
        action="store_true",
        help="Delete local checkpoint after successful push (saves disk space)",
    )

    # Authentication
    auth_group = parser.add_argument_group("Authentication")
    auth_group.add_argument(
        "--token",
        type=str,
        help="HuggingFace token (if not provided, uses cached token from 'huggingface-cli login')",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.checkpoint_dir and not args.repo_id:
        parser.error("--repo_id is required when using --checkpoint_dir")

    if args.output_dir and not args.repo_prefix:
        parser.error("--repo_prefix is required when using --output_dir")

    # Check authentication
    if not args.token:
        try:
            # Try to get token from cache
            from huggingface_hub.utils import HfFolder

            token = HfFolder.get_token()
            if not token:
                logger.warning("No HuggingFace token found. Please run 'huggingface-cli login' or provide --token")
        except Exception:
            logger.warning("Could not retrieve cached token. Please run 'huggingface-cli login' or provide --token")

    # Push checkpoint(s)
    if args.checkpoint_dir:
        # Push single checkpoint
        success = push_checkpoint(
            checkpoint_dir=args.checkpoint_dir,
            repo_id=args.repo_id,
            pretrained_only=args.pretrained_only,
            private=args.private,
            delete_after_push=args.delete_after_push,
            token=args.token,
        )
        sys.exit(0 if success else 1)
    else:
        # Push all checkpoints
        push_all_checkpoints(
            output_dir=args.output_dir,
            repo_prefix=args.repo_prefix,
            pretrained_only=args.pretrained_only,
            private=args.private,
            delete_after_push=args.delete_after_push,
            token=args.token,
        )


if __name__ == "__main__":
    main()

