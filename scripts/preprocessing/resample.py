"""
10-min grid builder for STM08 water level prediction.

Builds a uniform 10-minute grid from mixed-frequency clean CSVs.

Strategy
--------
* Instantaneous (HEIGHT_m, TEMP_C):
    5 min → 10 min : mean of 2 consecutive values
    15 min → 10 min : linear interpolation
    10 min → 10 min : passthrough

* Cumulative (PRECIP_mm):
    All frequencies: convert to cumulative rainfall series, interpolate to
    10-min grid, differentiate back.  This is mass-conserving for any
    source frequency.

* AEMET hourly (60 min → 10 min):
    Template-based disaggregation using STM01/STM02 10-min patterns when
    they overlap.  Falls back to conservative cumulative interpolation
    when no template is available.

Usage
-----
    from scripts.preprocessing.resample import build_10min_grid

    grid, gaps = build_10min_grid(
        start="2014-09-26",
        end="2025-07-22",
        clean_dir="data/clean",
        quality_filter=None,   # use None for now; pass lambda q: q==0 later
        interpolate_gaps="3h",  # max gap size for linear interpolation
    )
    grid.to_parquet("data/processed/grid_10min.parquet")
"""

import numpy as np
import pandas as pd
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLEAN_DIR = REPO_ROOT / "data" / "clean"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

HYDRO = ["STM03", "STM04", "STM05", "STM06", "STM07", "STM08"]
METEO = ["STM01", "STM02"]
AEMET = ["B013X", "B605X", "B691Y"]

DEFAULT_START = "2014-09-26"
DEFAULT_END_VALIDATED = "2025-07-22"


# ---------------------------------------------------------------------------
#  Loading
# ---------------------------------------------------------------------------

def load_station(code, clean_dir=None):
    """Load a single clean CSV. Returns DataFrame with DatetimeIndex."""
    root = Path(clean_dir) if clean_dir else CLEAN_DIR
    path = root / f"{code}.csv"
    df = pd.read_csv(path, low_memory=False)
    df["TIMESTAMP"] = pd.to_datetime(df["TIMESTAMP"], errors="coerce")
    df = df.dropna(subset=["TIMESTAMP"]).set_index("TIMESTAMP").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df


def load_all(clean_dir=None, quality_filter=None):
    """Load all 11 stations.  Optionally filter by QUALITY column.

    Parameters
    ----------
    clean_dir : pathlib.Path or None
    quality_filter : callable or None
        e.g. ``lambda q: q.isna() or int(q) == 0`` to keep good data only.
        Applied row-wise to the QUALITY column.  Rows where QUALITY does not
        pass are set to NaN (preserving the timestamp).
    """
    data = {}
    for code in HYDRO + METEO + AEMET:
        df = load_station(code, clean_dir)
        _fix_dtypes(df)
        if quality_filter is not None and "QUALITY" in df.columns:
            _apply_quality_filter(df, quality_filter)
        data[code] = df
    return data


def _fix_dtypes(df):
    """Coerce measurement columns to float; keep QUALITY/DATA_TYPE as-is."""
    _NUMERIC_COLS = {"HEIGHT_m", "PRECIP_mm", "TEMP_C", "DISCHARGE_m3s",
                      "VOLUME_m3", "LOAD_kg"}
    for col in df.columns:
        if col in _NUMERIC_COLS:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    if "QUALITY" in df.columns:
        df["QUALITY"] = pd.to_numeric(df["QUALITY"], errors="coerce").astype("Int64")


def _apply_quality_filter(df, quality_filter):
    """NaN-out measurement values where QUALITY fails the filter."""
    cols = [c for c in df.columns if c not in ("QUALITY", "DATA_TYPE")]
    mask = df["QUALITY"].apply(lambda q: not quality_filter(q))
    df.loc[mask, cols] = np.nan


# ---------------------------------------------------------------------------
#  Instantaneous resampling (HEIGHT_m, TEMP_C)
# ---------------------------------------------------------------------------

def _resample_instantaneous(series, target_idx, max_gap="3h"):
    """Resample a point-measurement series to *target_idx*.

    * 5-min → mean of 2 consecutive values (aggregation)
    * 10-min / 15-min → linear interpolation with gap cap
    """
    series = series.dropna()
    if series.empty:
        return pd.Series(np.nan, index=target_idx, name=series.name)

    # --- strategy: resample to 1-min, then take closest or interpolate ---
    # Push data onto a 1-min grid (forward-fill for up to 1 step)
    s_1min = series.reindex(
        series.asfreq("1min").index.union(target_idx)
    ).sort_index()
    s_1min = s_1min.interpolate(method="time", limit_direction="both")

    # Gap mask: interpolate only across gaps ≤ max_gap
    gap_mask = _gap_mask(series, target_idx, max_gap)

    result = s_1min.reindex(target_idx)
    result[~gap_mask] = np.nan
    result.name = series.name
    return result


# ---------------------------------------------------------------------------
#  Cumulative-precipitation resampling (PRECIP_mm, any source frequency)
# ---------------------------------------------------------------------------

def _resample_precip(series, target_idx, max_gap="3h"):
    """Resample cumulative-format precipitation to *target_idx*.

    PRECIP_mm at time t is the rain accumulated over the interval ending at t.
    Strategy: cumsum → interpolate cumulative → diff on target grid.
    Mass-conserving for any source frequency.
    """
    series = series.dropna()
    if series.empty:
        return pd.Series(np.nan, index=target_idx, name=series.name)

    # Build cumulative rainfall curve at source timestamps
    cumulative = series.cumsum()
    cumulative.name = series.name

    # Extend cumulative curve to include the target grid points
    all_pts = cumulative.index.union(target_idx)
    cumulative_full = cumulative.reindex(all_pts).sort_index()

    # Interpolate cumulative (linear is mass-conserving for cumulative)
    cumulative_full = cumulative_full.interpolate(method="time", limit_direction="both")

    # Back-fill the first target point if it's before the first data point
    if target_idx[0] < cumulative.index[0]:
        first_val = cumulative.iloc[0]
        cumulative_full.loc[:cumulative.index[0]] = first_val

    # Sample at target points
    cum_at_target = cumulative_full.reindex(target_idx)

    # Differentiate to get 10-min accumulations
    # First value is cumulative at first target point (≈ first source value)
    result = cum_at_target.diff()
    result.iloc[0] = cum_at_target.iloc[0]

    # Gap mask: NaN-out results that cross large gaps in source data
    gap_mask = _gap_mask(series, target_idx, max_gap)
    result[~gap_mask] = np.nan
    result.name = series.name
    return result


# ---------------------------------------------------------------------------
#  AEMET hourly disaggregation (60 min → 10 min)
# ---------------------------------------------------------------------------

def _disaggregate_aemet(aemet_series, stm01_10min, stm02_10min,
                        target_idx, max_gap="3h"):
    """Disaggregate hourly AEMET precipitation to 10-min.

    Template-based: when STM01 or STM02 have 10-min precip in the same hour,
    use their temporal pattern to distribute the hourly total.
    Falls back to conservative cumulative interpolation otherwise.
    """
    aemet_series = aemet_series.dropna()
    if aemet_series.empty:
        return pd.Series(np.nan, index=target_idx, name=aemet_series.name)

    # Conservative fallback: cumulative interpolation (already handled above)
    # We implement template-based approach here

    result = pd.Series(np.nan, index=target_idx, name=aemet_series.name)

    for hour_ts in aemet_series.index:
        hour_start = hour_ts - pd.Timedelta(hours=1)
        hourly_total = aemet_series.loc[hour_ts]

        if pd.isna(hourly_total):
            continue

        # Find target slots in this hour window
        mask_10min = (target_idx > hour_start) & (target_idx <= hour_ts)
        slots = target_idx[mask_10min]
        n_slots = len(slots)
        if n_slots == 0:
            continue

        # Try to get template from STM01 or STM02 10-min data
        template = _get_template(stm01_10min, hour_start, hour_ts, n_slots)
        if template is None:
            template = _get_template(stm02_10min, hour_start, hour_ts, n_slots)

        if template is not None and template.sum() > 0:
            weights = template / template.sum()
            result.loc[slots] = hourly_total * weights.values
        else:
            # No template: uniform split (but mass-conserving)
            result.loc[slots] = hourly_total / n_slots

    # Apply gap mask on hourly boundary gaps
    gap_mask = _gap_mask(aemet_series, target_idx, max_gap)
    result[~gap_mask] = np.nan
    return result


def _get_template(stm_series, hour_start, hour_ts, n_slots):
    """Extract a 10-min precipitation pattern from an STM series for one hour.

    Returns a pd.Series of length *n_slots* with the 10-min precipitation
    values, or None if no valid pattern exists.
    """
    mask = (stm_series.index > hour_start) & (stm_series.index <= hour_ts)
    window = stm_series.loc[mask].dropna()
    if len(window) < 2:
        return None
    # Reindex to match the target slots
    target_slots_in_hour = pd.date_range(
        hour_start + pd.Timedelta(minutes=10),
        hour_ts,
        freq="10min"
    )
    template = window.reindex(target_slots_in_hour)
    if template.isna().all():
        return None
    template = template.fillna(0)
    return template


# ---------------------------------------------------------------------------
#  Gap handling
# ---------------------------------------------------------------------------

def _gap_mask(series, target_idx, max_gap="3h"):
    """Build a boolean mask: True where target grid points are within *max_gap*
    of at least one source data point."""
    max_gap_td = pd.Timedelta(max_gap)
    mask = np.zeros(len(target_idx), dtype=bool)

    source_ts = series.dropna().index.sort_values()
    if len(source_ts) == 0:
        return mask

    for i, ts in enumerate(target_idx):
        # Find nearest source point after this target
        pos = source_ts.searchsorted(ts)
        if pos < len(source_ts):
            if (source_ts[pos] - ts) <= max_gap_td:
                mask[i] = True
                continue
        if pos > 0:
            if (ts - source_ts[pos - 1]) <= max_gap_td:
                mask[i] = True
    return mask


# ---------------------------------------------------------------------------
#  Main entry point
# ---------------------------------------------------------------------------

def build_10min_grid(start=DEFAULT_START, end=DEFAULT_END_VALIDATED,
                     clean_dir=None, quality_filter=None,
                     interpolate_gaps="3h",
                     aemet_template_stations=None):
    """Build the uniform 10-min grid for all stations.

    Parameters
    ----------
    start, end : str or datetime
        Grid boundaries. Default: validated window 2014-09-26 → 2025-07-22.
    clean_dir : pathlib.Path or None
        Path to clean/ directory.  Default: data/clean/ relative to repo root.
    quality_filter : callable or None
        Function QUALITY column → bool.  Pass ``lambda q: q == 0`` to keep
        only good-quality data when ready.
    interpolate_gaps : str
        Max gap size for linear interpolation ("3h", "1h", etc.).
    aemet_template_stations : list of str or None
        Which STM stations to use as disagg template.  Default: ["STM01","STM02"].

    Returns
    -------
    grid : pd.DataFrame
        10-min-indexed DataFrame with columns for every station/variable.
        Precip columns are 10-min accumulations (mm / 10 min).
    gap_info : dict
        Per-station gap statistics.
    """
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    target_idx = pd.date_range(start, end, freq="10min", name="TIMESTAMP")

    if clean_dir is None:
        clean_dir = CLEAN_DIR

    if aemet_template_stations is None:
        aemet_template_stations = ["STM01", "STM02"]

    print(f"Loading data from {clean_dir} ...")
    data = load_all(clean_dir, quality_filter)
    print(f"  Loaded {len(data)} stations")

    # Step 1: Build 10-min grid for STM stations (hydro + meteo)
    grid_columns = {}
    gap_info = {}
    max_gap = interpolate_gaps

    for code in HYDRO:
        print(f"  Resampling {code} (HEIGHT_m) ...")
        df = data[code]
        s = _clip_to_window(df["HEIGHT_m"], start, end)
        resampled = _resample_instantaneous(s, target_idx, max_gap=max_gap)
        grid_columns[f"{code}_HEIGHT_m"] = resampled
        gap_info[code] = _gap_stats(s, resampled)

    for code in METEO:
        print(f"  Resampling {code} (TEMP_C, PRECIP_mm) ...")
        df = data[code]
        s_temp = _clip_to_window(df["TEMP_C"], start, end)
        s_prec = _clip_to_window(df["PRECIP_mm"], start, end)
        grid_columns[f"{code}_TEMP_C"] = _resample_instantaneous(
            s_temp, target_idx, max_gap=max_gap)
        grid_columns[f"{code}_PRECIP_mm"] = _resample_precip(
            s_prec, target_idx, max_gap=max_gap)
        gap_info[code] = _gap_stats(s_temp, grid_columns[f"{code}_TEMP_C"])

    # Step 2: Build 10-min grid for AEMET stations (template-based disaggregation)
    # First, get the 10-min template patterns from STM01 and STM02
    templates = {}
    for tpl_code in aemet_template_stations:
        if tpl_code in grid_columns:
            templates[tpl_code] = grid_columns[f"{tpl_code}_PRECIP_mm"]

    for code in AEMET:
        print(f"  Resampling {code} (PRECIP_mm, hourly -> 10-min) ...")
        df = data[code]
        s_prec = _clip_to_window(df["PRECIP_mm"], start, end)

        # Use the first available template, or conservative fallback
        tpl_s = templates.get("STM01") if "STM01" in templates else None

        if tpl_s is not None and not tpl_s.dropna().empty:
            result = _disaggregate_aemet(
                s_prec, tpl_s,
                templates.get("STM02", tpl_s),
                target_idx, max_gap=max_gap)
        else:
            # Conservative fallback
            result = _resample_precip(s_prec, target_idx, max_gap=max_gap)

        grid_columns[f"{code}_PRECIP_mm"] = result
        gap_info[code] = _gap_stats(s_prec, result)

    # Build final DataFrame
    grid = pd.DataFrame(grid_columns, index=target_idx)
    grid.index.name = "TIMESTAMP"

    # Add QUALITY columns (forward-fill from source, aligned to 10-min)
    grid = _add_quality_columns(grid, data, target_idx, start, end)

    # Add DISCHARGE_m3s via rating curves
    print("  Computing DISCHARGE_m3s for all hydro stations ...")
    from scripts.preprocessing.rating_curve import load_rating_curves, apply_discharge
    curves = load_rating_curves()
    grid = apply_discharge(grid, curves)

    print(f"\nGrid built: {len(grid)} rows, {len(grid.columns)} columns")
    print(f"  {start} -> {end}")
    return grid, gap_info


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _clip_to_window(series, start, end):
    """Clip a series to the [start, end] window."""
    return series.loc[(series.index >= start) & (series.index <= end)]


def _gap_stats(original, resampled):
    """Return gap statistics for a resampled series."""
    total = len(resampled)
    nan_count = int(resampled.isna().sum())
    return {
        "total": total,
        "nan": nan_count,
        "nan_pct": round(100 * nan_count / max(total, 1), 1),
    }


def _add_quality_columns(grid, data, target_idx, start, end):
    """Add per-station quality columns to the grid (forward-filled)."""
    for code in HYDRO + METEO + AEMET:
        if "QUALITY" not in data[code].columns:
            continue
        q_series = _clip_to_window(data[code]["QUALITY"], start, end)
        if q_series.empty:
            continue
        # Reindex to 10-min grid, forward-fill quality flag
        q_resampled = q_series.reindex(
            q_series.index.union(target_idx)
        ).sort_index().ffill().reindex(target_idx)
        grid[f"{code}_QUALITY"] = q_resampled.astype("Int64")
    return grid


# ---------------------------------------------------------------------------
#  CLI entry point (for quick regeneration)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build 10-min grid")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END_VALIDATED)
    parser.add_argument("--output", default=str(PROCESSED_DIR / "grid_10min.parquet"))
    parser.add_argument("--clean-dir", default=None)
    args = parser.parse_args()

    grid, gaps = build_10min_grid(
        start=args.start,
        end=args.end,
        clean_dir=Path(args.clean_dir) if args.clean_dir else None,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    grid.to_parquet(out_path)
    print(f"\nSaved: {out_path}")

    # Print gap summary
    gdf = pd.DataFrame(gaps).T
    gdf["nan_pct"] = gdf["nan_pct"].apply(lambda x: f"{x}%")
    print("\nGap summary:")
    print(gdf.to_string())
