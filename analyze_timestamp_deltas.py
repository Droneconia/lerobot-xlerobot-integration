#!/usr/bin/env python
"""Analyze timestamp deltas in a parquet file.

This script:
- Reads timestamp data from a parquet file
- Calculates the average delta between consecutive timestamps
- Counts deltas greater than 0.5 seconds
- Excludes deltas > 0.5s from the average calculation
"""

import argparse
import sys
from pathlib import Path

import pandas as pd


def analyze_timestamp_deltas(parquet_path: Path, timestamp_column: str = "timestamp", threshold_s: float = 0.5):
    """Analyze timestamp deltas in a parquet file.
    
    Args:
        parquet_path: Path to the parquet file
        timestamp_column: Name of the timestamp column (default: "timestamp")
        threshold_s: Threshold in seconds for counting large gaps (default: 0.5)
    
    Returns:
        dict: Analysis results containing:
            - average_delta: Average delta excluding values > threshold_s
            - large_gap_count: Number of deltas > threshold_s
            - total_deltas: Total number of deltas calculated
            - valid_deltas: Number of deltas <= threshold_s
            - min_delta: Minimum delta
            - max_delta: Maximum delta
            - min_valid_delta: Minimum valid delta (<= threshold_s)
            - max_valid_delta: Maximum valid delta (<= threshold_s)
    """
    # Read parquet file
    try:
        df = pd.read_parquet(parquet_path)
    except Exception as e:
        print(f"Error reading parquet file: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Check if timestamp column exists
    if timestamp_column not in df.columns:
        available_columns = ", ".join(df.columns.tolist())
        print(
            f"Error: Column '{timestamp_column}' not found in parquet file.\n"
            f"Available columns: {available_columns}",
            file=sys.stderr
        )
        sys.exit(1)
    
    # Extract timestamps
    timestamps = df[timestamp_column].values
    
    if len(timestamps) < 2:
        print("Error: Need at least 2 timestamps to calculate deltas.", file=sys.stderr)
        sys.exit(1)
    
    # Calculate deltas (difference between consecutive timestamps)
    deltas = timestamps[1:] - timestamps[:-1]
    
    # Filter out negative deltas (shouldn't happen, but handle gracefully)
    deltas = deltas[deltas >= 0]
    
    if len(deltas) == 0:
        print("Error: No valid deltas found (all deltas were negative).", file=sys.stderr)
        sys.exit(1)
    
    # Count large gaps (> threshold_s)
    large_gap_mask = deltas > threshold_s
    large_gap_count = int(large_gap_mask.sum())
    
    # Calculate average excluding large gaps
    valid_deltas = deltas[~large_gap_mask]
    
    if len(valid_deltas) == 0:
        print(
            f"Warning: All deltas are greater than {threshold_s}s. "
            "Cannot calculate average excluding large gaps.",
            file=sys.stderr
        )
        average_delta = None
        min_valid_delta = None
        max_valid_delta = None
    else:
        average_delta = float(valid_deltas.mean())
        min_valid_delta = float(valid_deltas.min())
        max_valid_delta = float(valid_deltas.max())
    
    # Calculate overall statistics
    min_delta = float(deltas.min())
    max_delta = float(deltas.max())
    total_deltas = len(deltas)
    valid_deltas_count = len(valid_deltas)
    
    return {
        "average_delta": average_delta,
        "large_gap_count": large_gap_count,
        "total_deltas": total_deltas,
        "valid_deltas": valid_deltas_count,
        "min_delta": min_delta,
        "max_delta": max_delta,
        "min_valid_delta": min_valid_delta,
        "max_valid_delta": max_valid_delta,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Analyze timestamp deltas in a parquet file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze default timestamp column
  python analyze_timestamp_deltas.py data.parquet
  
  # Specify custom timestamp column
  python analyze_timestamp_deltas.py data.parquet --column "time"
  
  # Use custom threshold
  python analyze_timestamp_deltas.py data.parquet --threshold 1.0
        """,
    )
    parser.add_argument(
        "parquet_file",
        type=Path,
        help="Path to the parquet file to analyze",
    )
    parser.add_argument(
        "--column",
        type=str,
        default="timestamp",
        help="Name of the timestamp column (default: 'timestamp')",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Threshold in seconds for counting large gaps (default: 0.5)",
    )
    
    args = parser.parse_args()
    
    # Check if file exists
    if not args.parquet_file.exists():
        print(f"Error: File not found: {args.parquet_file}", file=sys.stderr)
        sys.exit(1)
    
    # Analyze timestamps
    results = analyze_timestamp_deltas(
        args.parquet_file,
        timestamp_column=args.column,
        threshold_s=args.threshold,
    )
    
    # Print results
    print("=" * 60)
    print("Timestamp Delta Analysis")
    print("=" * 60)
    print(f"File: {args.parquet_file}")
    print(f"Timestamp column: {args.column}")
    print(f"Threshold: {args.threshold}s")
    print()
    print("Statistics:")
    print(f"  Total deltas: {results['total_deltas']}")
    print(f"  Valid deltas (<= {args.threshold}s): {results['valid_deltas']}")
    print(f"  Large gaps (> {args.threshold}s): {results['large_gap_count']}")
    print()
    print("Delta values (all):")
    print(f"  Min: {results['min_delta']:.6f}s")
    print(f"  Max: {results['max_delta']:.6f}s")
    print()
    if results['average_delta'] is not None:
        print("Delta values (excluding large gaps):")
        print(f"  Min: {results['min_valid_delta']:.6f}s")
        print(f"  Max: {results['max_valid_delta']:.6f}s")
        print(f"  Average: {results['average_delta']:.6f}s")
    else:
        print("Delta values (excluding large gaps):")
        print("  (No valid deltas to calculate statistics)")
    print("=" * 60)
    
    # Exit with error code if there are large gaps
    if results['large_gap_count'] > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()

