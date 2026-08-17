"""Harmonize DB extension data in clean hydro CSVs.

Applies a three-layer filter to the DB-extension portion of hydro station
clean CSVs (STM03--STM08).  Historical Excel data is untouched.

Filter layers
-------------
1. **Absolute bounds**: HEIGHT_m outside [-0.5, 5.0] → NaN
2. **Rate-of-change**: |dH/dt| > 0.5 m/10min → NaN (3 m/h, physically impossible
   in these channels)
3. **Contiguous clean blocks**: Keep all data blocks (contiguous valid runs)
   after layers 1--2 that exceed a minimum length (24 h) and maintain at
   least 70 % valid fraction.  Discard the rest (removes sawtooth oscillations
   and negative plateaus that survive layers 1--2).

The script modifies clean CSVs in-place.  Back up or regenerate from raw data
if needed.

Usage
-----
    python scripts/preprocessing/harmonize_extension.py          # all stations
    python scripts/preprocessing/harmonize_extension.py --code STM08  # single
"""

import csv
import os
import numpy as np
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLEAN_DIR = REPO_ROOT / "data" / "clean"

HYDRO = ["STM03", "STM04", "STM05", "STM06", "STM07", "STM08"]

# Filter parameters
H_MIN = -0.5
H_MAX = 5.0
MAX_DH_DT = 0.5   # m per 10-min step
BLOCK_VALID_THRESHOLD = 0.7  # fraction of valid rows in a block to keep it
BLOCK_MIN_LENGTH = 144  # minimum block length in rows (24 h at 10-min)


def detect_extension_rows(rows_with_quality):
    """Return boolean array: True for rows from the DB extension.

    Extension rows are identified as having a non-empty QUALITY column.
    The CSV columns are: TIMESTAMP, HEIGHT_m, QUALITY, DATA_TYPE.
    """
    return np.array([
        len(r) > 2 and r[2].strip() != ""
        for r in rows_with_quality
    ], dtype=bool)


def parse_height(val):
    """Parse HEIGHT_m value, returning float or NaN."""
    if val is None or val.strip() == "":
        return np.nan
    try:
        return float(val)
    except (ValueError, TypeError):
        return np.nan


def layer1_abs_bounds(h):
    """NaN-out values outside [H_MIN, H_MAX]."""
    return np.where((h >= H_MIN) & (h <= H_MAX), h, np.nan)


def layer2_rate_of_change(h):
    """NaN-out values where |dh/dt| > MAX_DH_DT per 10-min step.

    A spike at index i is detected if either incoming or outgoing
    difference exceeds the threshold.
    """
    dh = np.abs(np.diff(np.where(~np.isnan(h), h, 0.0), prepend=h[0]))
    mask = dh > MAX_DH_DT
    h[mask] = np.nan
    return h


def layer3_contiguous(h):
    """Keep all valid blocks meeting the quality + length threshold.

    After layers 1--2, the signal contains scattered NaNs and valid
    segments.  Any block with valid-fraction >= BLOCK_VALID_THRESHOLD
    and length >= BLOCK_MIN_LENGTH is kept; everything else is NaN-ed.
    """
    valid = ~np.isnan(h)
    if not np.any(valid):
        return h

    boundaries = np.where(np.diff(valid.astype(int)))[0] + 1
    starts = np.concatenate([[0], boundaries])
    ends = np.concatenate([boundaries, [len(h)]])

    result = np.full_like(h, np.nan)
    for s, e in zip(starts, ends):
        if not valid[s]:
            continue
        length = e - s
        frac = valid[s:e].mean()
        if frac >= BLOCK_VALID_THRESHOLD and length >= BLOCK_MIN_LENGTH:
            result[s:e] = h[s:e]

    return result


def harmonize(code, dry_run=False):
    """Apply three-layer filter to the DB extension of a station's CSV.

    Parameters
    ----------
    code : str
        Station code (STM03--STM08).
    dry_run : bool
        If True, only report statistics without modifying the file.

    Returns
    -------
    stats : dict
        Before/after counts per layer.
    """
    path = CLEAN_DIR / f"{code}.csv"
    if not path.exists():
        print(f"  {code}: file not found, skipping")
        return {}

    # Read all rows
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    if not rows:
        print(f"  {code}: empty file, skipping")
        return {}

    # Identify extension rows
    ext_mask = detect_extension_rows(rows)
    n_ext = int(ext_mask.sum())
    if n_ext == 0:
        print(f"  {code}: no extension rows, skipping")
        return {"code": code, "n_ext": 0}

    # Extract heights
    heights = np.array([parse_height(r[1]) for r in rows], dtype=float)
    ext_heights = heights[ext_mask].copy()
    n_non_null_before = int((~np.isnan(ext_heights)).sum())

    # Layer 1: absolute bounds
    ext_clean = layer1_abs_bounds(ext_heights)
    n_l1 = int((~np.isnan(ext_clean)).sum())

    # Layer 2: rate-of-change
    ext_clean = layer2_rate_of_change(ext_clean)
    n_l2 = int((~np.isnan(ext_clean)).sum())

    # Layer 3: contiguous blocks
    ext_clean = layer3_contiguous(ext_clean)
    n_l3 = int((~np.isnan(ext_clean)).sum())

    # Write results back
    if not dry_run:
        heights[ext_mask] = ext_clean
        # Rebuild rows: extension survivors stay "observed"; discarded -> NaN.
        # (DATA_TYPE "harmonized" was folded into "observed" in Iteration 15;
        #  writing "observed" here also reverts any legacy "harmonized" tags.)
        for i, row in enumerate(rows):
            h_val = heights[i]
            if np.isnan(h_val):
                row[1] = ""
            else:
                row[1] = str(round(float(h_val), 6))
            if ext_mask[i]:
                row[3] = "observed"

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)

    stats = {
        "code": code,
        "n_ext": n_ext,
        "non_null_before": n_non_null_before,
        "after_l1": n_l1,
        "after_l2": n_l2,
        "after_l3": n_l3,
        "retained_pct": round(100 * n_l3 / max(n_non_null_before, 1), 1),
        "discarded": n_non_null_before - n_l3,
    }

    print(f"  {code}: {n_ext} ext rows, {n_non_null_before} non-null before -> "
          f"L1={n_l1} L2={n_l2} L3={n_l3} "
          f"({stats['retained_pct']}% retained, {stats['discarded']} discarded)")

    return stats


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Harmonize DB extension data")
    parser.add_argument("--code", default=None, help="Single station code")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report statistics without modifying files")
    args = parser.parse_args()

    codes = [args.code] if args.code else HYDRO

    print(f"Harmonizing extension data "
          f"({'dry-run, no changes' if args.dry_run else 'WRITING changes'})")
    print(f"Parameters: H in [{H_MIN}, {H_MAX}], |dH/dt| <= {MAX_DH_DT} m/step, "
          f"block valid >= {BLOCK_VALID_THRESHOLD*100:.0f}%, min {BLOCK_MIN_LENGTH} rows")
    print()

    all_stats = []
    for code in codes:
        s = harmonize(code, dry_run=args.dry_run)
        if s:
            all_stats.append(s)

    if all_stats:
        total_ext = sum(s["n_ext"] for s in all_stats)
        total_before = sum(s["non_null_before"] for s in all_stats)
        total_after = sum(s["after_l3"] for s in all_stats)
        print(f"\n=== Total ===")
        print(f"  Extension rows: {total_ext:,}")
        print(f"  Before harmonization: {total_before:,} non-null")
        print(f"  After harmonization:  {total_after:,} non-null "
              f"({100*total_after/max(total_before,1):.1f}%)")
