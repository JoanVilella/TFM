"""Harmonize DB extension data in clean hydro CSVs.

Applies a four-layer filter to the DB-extension portion of hydro station
clean CSVs (STM03--STM08).  Historical Excel data is untouched except as a
climatological reference for layer 4.

Filter layers
-------------
1. **Absolute bounds**: HEIGHT_m outside [-0.5, 5.0] → NaN
2. **Rate-of-change**: |dH/dt| > 0.5 m/10min → NaN (3 m/h, physically impossible
   in these channels)
3. **Contiguous clean blocks**: Keep all data blocks (contiguous valid runs)
   after layers 1--2 that exceed a minimum length (24 h) and maintain at
   least 70 % valid fraction.  Discard the rest.
4. **Diurnal drift correction** (uniform procedure, applied to every station):
   the DB-only segment of some stations exhibits a spurious daily water-level
   oscillation (pressure-transducer thermal drift) that is absent from the
   historical record.  For each station:
     - clim_ext(h): hour-of-day climatology from quiet DB-only rows (H < QUIET_H)
     - clim_hist(h): hour-of-day climatology from quiet historical rows in the
       same calendar months (season-matched reference)
     - drift(h) = clim_ext(h) - clim_hist(h), centred to zero mean
   The correction is subtracted only when the drift amplitude is >=
   DRIFT_MIN_AMPLITUDE (5 mm) AND the ext diurnal range is >= DRIFT_MIN_RATIO
   times the historical range; otherwise it is zeroed and the station is
   documented as having no significant drift.  Corrected rows are tagged
   DATA_TYPE = "corrected".

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

# Layer-4 parameters (diurnal drift correction)
QUIET_H = 0.10             # m: rows below this level are "quiet" (baseflow)
DRIFT_MIN_AMPLITUDE = 0.005  # m: minimum centred drift range to correct (5 mm)
DRIFT_MIN_RATIO = 5.0        # ext diurnal range must exceed hist range by this
MIN_CLIM_SAMPLES = 200       # minimum quiet samples per climatology


def detect_extension_rows(rows_with_quality):
    """Return boolean array: True for rows from the DB extension.

    Extension rows are identified as having a non-empty QUALITY column.
    The CSV columns are: TIMESTAMP, HEIGHT_m, WATER_TEMP_C, QUALITY, DATA_TYPE.
    """
    return np.array([
        len(r) > 3 and r[3].strip() != ""
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


# ---------------------------------------------------------------------------
#  Layer 4: diurnal drift correction
# ---------------------------------------------------------------------------

def _hourly_climatology(timestamps, values, months=None):
    """Mean level per hour-of-day over quiet rows (HEIGHT < QUIET_H).

    timestamps: list of 'YYYY-MM-DD HH:MM:SS' strings.
    values: float array (NaN excluded).
    months: optional set of calendar months to restrict to (season matching).
    Returns (clim[24], counts[24]).
    """
    sums = np.zeros(24)
    cnts = np.zeros(24)
    for ts, v in zip(timestamps, values):
        if not np.isfinite(v) or v >= QUIET_H:
            continue
        if months is not None and int(ts[5:7]) not in months:
            continue
        hh = int(ts[11:13])
        sums[hh] += v
        cnts[hh] += 1
    clim = np.full(24, np.nan)
    ok = cnts > 0
    clim[ok] = sums[ok] / cnts[ok]
    return clim, cnts


def correct_diurnal_drift(ext_ts, ext_h, hist_ts, hist_h):
    """Layer 4 — remove spurious diurnal drift from the DB-only segment.

    Uniform procedure applied to every station; the correction is only
    subtracted when it exceeds DRIFT_MIN_AMPLITUDE and the ext diurnal range
    is at least DRIFT_MIN_RATIO times the historical range.

    Returns (corrected_ext_heights, info_dict).
    """
    corrected = ext_h.copy()
    info = {"applied": False, "rng_ext": np.nan, "rng_hist": np.nan,
            "drift_rng": np.nan}

    months_ext = {int(ts[5:7]) for ts in ext_ts}
    clim_ext, n_ext = _hourly_climatology(ext_ts, ext_h)
    clim_hist, n_hist = _hourly_climatology(hist_ts, hist_h, months=months_ext)

    if n_ext.sum() < MIN_CLIM_SAMPLES or n_hist.sum() < MIN_CLIM_SAMPLES:
        info["reason"] = "insufficient quiet samples"
        return corrected, info

    rng_ext = float(np.nanmax(clim_ext) - np.nanmin(clim_ext))
    rng_hist = float(np.nanmax(clim_hist) - np.nanmin(clim_hist))
    drift = clim_ext - clim_hist
    drift = drift - np.nanmean(drift)
    drift_rng = float(np.nanmax(drift) - np.nanmin(drift))
    info.update({"rng_ext": rng_ext, "rng_hist": rng_hist, "drift_rng": drift_rng})

    if not (np.isfinite(rng_hist) and rng_hist > 0):
        info["reason"] = "degenerate historical climatology"
        return corrected, info
    if drift_rng < DRIFT_MIN_AMPLITUDE or rng_ext < DRIFT_MIN_RATIO * rng_hist:
        info["reason"] = "no significant drift"
        return corrected, info

    hours = np.array([int(ts[11:13]) for ts in ext_ts])
    finite = np.isfinite(corrected)
    corrected[finite] -= drift[hours[finite]]
    info["applied"] = True
    return corrected, info


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

    # Layer 4: diurnal drift correction (uniform procedure, all stations).
    # Uses quiet DB-only rows vs a season-matched historical reference.
    ext_idx = np.where(ext_mask)[0]
    hist_idx = np.where(~ext_mask)[0]
    ext_ts = [rows[i][0] for i in ext_idx]
    hist_ts = [rows[i][0] for i in hist_idx]
    ext_clean, drift_info = correct_diurnal_drift(
        ext_ts, ext_clean, hist_ts, heights[hist_idx])
    n_l4 = int((~np.isnan(ext_clean)).sum())
    if not drift_info["applied"]:
        n_l4 = n_l3

    # Which extension rows were modified by layer 4? When the correction is
    # applied, every surviving (finite) value is shifted by drift(hour).
    corrected_flag = np.isfinite(ext_clean) if drift_info["applied"] \
        else np.zeros(len(ext_clean), dtype=bool)

    # Write results back
    if not dry_run:
        heights[ext_mask] = ext_clean
        # Rebuild rows: extension survivors keep DATA_TYPE "observed", or
        # "corrected" if layer 4 shifted them. Discarded -> NaN.
        # WATER_TEMP_C (row[2]) is left untouched. DATA_TYPE is row[4].
        for i, row in enumerate(rows):
            h_val = heights[i]
            if np.isnan(h_val):
                row[1] = ""
            else:
                row[1] = str(round(float(h_val), 6))
            if ext_mask[i]:
                j = np.searchsorted(ext_idx, i)
                row[4] = "corrected" if corrected_flag[j] else "observed"

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)

    reason = drift_info.get("reason", "")
    stats = {
        "code": code,
        "n_ext": n_ext,
        "non_null_before": n_non_null_before,
        "after_l1": n_l1,
        "after_l2": n_l2,
        "after_l3": n_l3,
        "after_l4": n_l4,
        "drift_applied": drift_info["applied"],
        "rng_ext_mm": round(1000 * drift_info["rng_ext"], 2) if np.isfinite(drift_info["rng_ext"]) else None,
        "rng_hist_mm": round(1000 * drift_info["rng_hist"], 2) if np.isfinite(drift_info["rng_hist"]) else None,
        "drift_rng_mm": round(1000 * drift_info["drift_rng"], 2) if np.isfinite(drift_info["drift_rng"]) else None,
        "drift_reason": reason,
        "retained_pct": round(100 * n_l4 / max(n_non_null_before, 1), 1),
        "discarded": n_non_null_before - n_l4,
    }

    print(f"  {code}: {n_ext} ext rows, {n_non_null_before} non-null before -> "
          f"L1={n_l1} L2={n_l2} L3={n_l3} L4={n_l4} "
          f"({stats['retained_pct']}% retained, {stats['discarded']} discarded)")
    if drift_info["applied"]:
        print(f"      L4 diurnal drift CORRECTED: ext range {stats['rng_ext_mm']} mm "
              f"vs hist {stats['rng_hist_mm']} mm "
              f"(x{stats['rng_ext_mm']/max(stats['rng_hist_mm'],1e-9):.1f}), "
              f"centred drift range {stats['drift_rng_mm']} mm")
    else:
        print(f"      L4 not applied ({reason}): ext range {stats['rng_ext_mm']} mm, "
              f"hist range {stats['rng_hist_mm']} mm")

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
    print(f"Layer 4 (diurnal drift): quiet H < {QUIET_H} m, correct if drift range "
          f">= {1000*DRIFT_MIN_AMPLITUDE:.0f} mm AND ext/hist range ratio >= {DRIFT_MIN_RATIO:.0f}")
    print()

    all_stats = []
    for code in codes:
        s = harmonize(code, dry_run=args.dry_run)
        if s:
            all_stats.append(s)

    if all_stats:
        total_ext = sum(s["n_ext"] for s in all_stats)
        total_before = sum(s["non_null_before"] for s in all_stats)
        total_after = sum(s["after_l4"] for s in all_stats)
        print(f"\n=== Total ===")
        print(f"  Extension rows: {total_ext:,}")
        print(f"  Before harmonization: {total_before:,} non-null")
        print(f"  After harmonization:  {total_after:,} non-null "
              f"({100*total_after/max(total_before,1):.1f}%)")
