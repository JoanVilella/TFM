"""Null imputation and missingness indicators for the 10-min grid.

Fills NaN runs up to ``max_interp`` (default 24 h) on the 10-min grid:

* ``HEIGHT_m`` / ``TEMP_C`` — time-linear interpolation
* ``PRECIP_mm``            — time-linear interpolation of the 10-min
  increments (the increments are not cumulative, so a cumulative-and-diff
  fill would redistribute observed rain into the gap)

``DISCHARGE_m3s`` is left untouched: NaN there means the water level fell
outside the rating-curve range, not that data is missing.

Cells filled from a short gap are re-labelled ``DATA_TYPE = "imputed"``.
Gaps longer than ``max_interp`` remain NaN and get a companion
``{col}_MISSING`` (0/1) indicator column so downstream models can tell
"missing" from "zero".

Usage
-----
    from scripts.preprocessing.impute import build_imputed_grid

    grid = pd.read_parquet("data/processed/grid_10min.parquet")
    imputed = build_imputed_grid(grid, max_interp="24h")
    imputed.to_parquet("data/processed/grid_10min_imputed.parquet")
"""

import numpy as np
import pandas as pd
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

HYDRO = ["STM03", "STM04", "STM05", "STM06", "STM07", "STM08"]
METEO = ["STM01", "STM02"]
AEMET = ["B013X", "B605X", "B691Y"]

INSTANTANEOUS_COLS = (
    [f"{c}_HEIGHT_m" for c in HYDRO]
    + [f"{c}_TEMP_C" for c in METEO]
)
PRECIP_COLS = [f"{c}_PRECIP_mm" for c in METEO + AEMET]
IMPUTE_COLS = INSTANTANEOUS_COLS + PRECIP_COLS

MAX_INTERP = "24h"
STEP_MIN = 10  # grid resolution in minutes


def _max_steps(max_interp=MAX_INTERP, step_min=STEP_MIN):
    """Convert a gap cap like '24h' into a number of 10-min steps."""
    return int(pd.Timedelta(max_interp).total_seconds() // (step_min * 60))


def _long_gap_mask(series, max_steps):
    """Boolean mask: True where the value is NaN inside a run > max_steps."""
    null = series.isna()
    if not null.any():
        return null
    groups = (null != null.shift()).cumsum()
    run_len = null.groupby(groups).transform("sum")
    return null & (run_len > max_steps)


def _impute_instantaneous(series, max_steps):
    """Time-linear interpolation restricted to gaps <= max_steps."""
    result = series.interpolate(method="time", limit_direction="both")
    result[_long_gap_mask(series, max_steps)] = np.nan
    result.name = series.name
    return result


def _impute_precip(series, max_steps):
    """Linear interpolation of short gaps in precipitation increments.

    The grid PRECIP_mm columns hold 10-min *increments* (mm/10min), not a
    cumulative series, so a cumulative-curve-and-diff fill would redistribute
    observed rain into the gap (altering real observations at the gap edges).
    Instead we interpolate the increment series linearly across short gaps,
    which fills only the missing cells and leaves every observed value
    untouched.  Long gaps stay NaN (no fabrication).
    """
    return _impute_instantaneous(series, max_steps)


def impute_gaps(grid, max_interp=MAX_INTERP):
    """Fill short gaps (<= max_interp) in HEIGHT/TEMP/PRECIP.

    Parameters
    ----------
    grid : pd.DataFrame
        The 10-min grid from ``build_10min_grid()``.
    max_interp : str
        Gap cap ("24h", "7d", ...).  Longer gaps stay NaN.

    Returns
    -------
    grid : pd.DataFrame
        Copy with short gaps filled and DATA_TYPE = "imputed" on filled cells.
    """
    grid = grid.copy()
    max_steps = _max_steps(max_interp)

    for col in IMPUTE_COLS:
        if col not in grid.columns:
            continue
        was_null = grid[col].isna()
        if not was_null.any():
            continue

        if col in INSTANTANEOUS_COLS:
            grid[col] = _impute_instantaneous(grid[col], max_steps)
        else:
            grid[col] = _impute_precip(grid[col], max_steps)

        now_filled = was_null & grid[col].notna()
        dt_col = f"{col}_DATA_TYPE"
        if dt_col in grid.columns and now_filled.any():
            grid.loc[now_filled, dt_col] = "imputed"

    return grid


def add_missingness_indicators(grid):
    """Add ``{col}_MISSING`` (0/1) columns for cells still missing after imputation."""
    grid = grid.copy()
    for col in IMPUTE_COLS:
        if col in grid.columns:
            grid[f"{col}_MISSING"] = grid[col].isna().astype("int8")
    return grid


def build_imputed_grid(grid, max_interp=MAX_INTERP):
    """Convenience wrapper: impute short gaps + add missingness indicators."""
    grid = impute_gaps(grid, max_interp)
    grid = add_missingness_indicators(grid)
    return grid


# ---------------------------------------------------------------------------
#  CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    from scripts.preprocessing.resample import build_measurements_table

    parser = argparse.ArgumentParser(description="Impute short gaps in the 10-min grid")
    parser.add_argument("--grid", default=str(PROCESSED_DIR / "grid_10min.parquet"))
    parser.add_argument("--output", default=str(PROCESSED_DIR / "grid_10min_imputed.parquet"))
    parser.add_argument("--max-interp", default=MAX_INTERP)
    args = parser.parse_args()

    print(f"Loading grid from {args.grid} ...")
    grid = pd.read_parquet(args.grid)
    print(f"  Grid: {grid.shape[0]:,} rows x {grid.shape[1]} cols")

    before = {c: int(grid[c].isna().sum()) for c in IMPUTE_COLS if c in grid.columns}
    imputed = build_imputed_grid(grid, max_interp=args.max_interp)
    after = {c: int(imputed[c].isna().sum()) for c in IMPUTE_COLS if c in imputed.columns}

    print(f"\nImputation (max_interp={args.max_interp}):")
    print(f"  {'column':<22}{'NaN before':>12}{'NaN after':>12}{'filled':>10}")
    for c in before:
        print(f"  {c:<22}{before[c]:>12,}{after[c]:>12,}{before[c]-after[c]:>10,}")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    imputed.to_parquet(out)
    print(f"\nSaved imputed grid: {out}")

    # Rebuild measurements table from the imputed grid
    print("Building measurements table (long format, imputed) ...")
    meas = build_measurements_table(imputed)
    meas_path = PROCESSED_DIR / "measurements.parquet"
    meas.to_parquet(meas_path)
    meas.to_csv(PROCESSED_DIR / "measurements.csv.gz",
                compression="gzip", index=False)
    print(f"  Measurements: {meas.shape[0]:,} rows x {meas.shape[1]} cols")
    print("  DATA_TYPE counts:")
    print(meas["DATA_TYPE"].value_counts(dropna=False).to_string())
