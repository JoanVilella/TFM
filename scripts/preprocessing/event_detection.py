"""Flood event detection for STM08 via Peak Over Threshold (POT).

Detects discrete hydrological events in the 10-min grid using the
STM08_DISCHARGE_m3s series.  Events are characterised by their start,
peak, and end timestamps, peak discharge and level, duration, and
associated precipitation totals.

Method
------
Peak Over Threshold with independence criterion (Claps & Laio 2003;
Burn et al. 2016).  An event is triggered when Q exceeds a threshold,
and consecutive exceedances are grouped.  Groups separated by less
than the inter-event time are merged.  Start and end are traced
backward/forward until Q returns to baseline.

Parameters (liberal, designed to capture more events initially)
---------------------------------------------------------------
* peak_q_threshold = 0.2 m³/s   (top ~0.1 % of 10-min values)
* inter_event_h = 6             (minimum separation in hours)
* start_q = 0.05 m³/s           (rising limb start threshold)
* end_q = 0.05 m³/s             (return to baseline threshold)
* end_duration_h = 1            (must stay below end_q for this long)

Usage
-----
    from scripts.preprocessing.event_detection import detect_events

    events, grid_with_ids = detect_events(grid)
    events.to_csv("data/processed/events.csv", index=False)
"""

import numpy as np
import pandas as pd
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

TARGET_STATION = "STM08"
Q_COL = f"{TARGET_STATION}_DISCHARGE_m3s"
H_COL = f"{TARGET_STATION}_HEIGHT_m"

# All precipitation columns in the grid
PRECIP_COLS = [
    "STM01_PRECIP_mm", "STM02_PRECIP_mm",
    "B013X_PRECIP_mm", "B605X_PRECIP_mm", "B691Y_PRECIP_mm",
]


# ---------------------------------------------------------------------------
#  Core detection
# ---------------------------------------------------------------------------

def detect_events(grid, peak_q_threshold=0.2, inter_event_h=6,
                  start_q=0.05, end_q=0.05, end_duration_h=1,
                  max_start_lookback_h=12, max_end_lookahead_h=24):
    """Detect flood events in STM08 discharge series.

    Parameters
    ----------
    grid : pd.DataFrame
        10-min grid with STM08_DISCHARGE_m3s and STM08_HEIGHT_m columns.
    peak_q_threshold : float
        Q must exceed this to trigger an event (m³/s).
    inter_event_h : float
        Minimum hours between independent events.  Closer groups are merged.
    start_q, end_q : float
        Q thresholds for tracing event start (rising limb) and end (falling
        limb) (m³/s).
    end_duration_h : float
        Q must stay at or below *end_q* for this many hours to confirm end.
    max_start_lookback_h : float
        Maximum hours to trace backward from first exceedance for event start.
    max_end_lookahead_h : float
        Maximum hours to trace forward from last exceedance for event end.

    Returns
    -------
    events : pd.DataFrame
        One row per event with start/peak/end, discharge, level, duration,
        precipitation, and split assignment.
    grid : pd.DataFrame
        Same grid with an ``event_id`` column added (Int64, NaN = no event).
    """
    q = grid[Q_COL].values
    timestamps = grid.index.values
    h = grid[H_COL].values if H_COL in grid.columns else np.full_like(q, np.nan)
    n = len(q)

    inter_event_steps = int(inter_event_h * 6)  # 6 steps per hour
    end_duration_steps = int(end_duration_h * 6)
    max_start_lookback = int(max_start_lookback_h * 6)
    max_end_lookahead = int(max_end_lookahead_h * 6)
    core_gap_steps = int(3 * 6)  # 3 h wiggle within event core

    # ---- Step 1: find all indices where Q > peak threshold ----
    above = np.where(q > peak_q_threshold)[0]
    if len(above) == 0:
        return _empty_result(grid)

    # ---- Step 2: group into event cores, allowing brief dips ----
    groups = _consecutive_groups(above, max_gap=core_gap_steps - 1)

    # ---- Step 3: merge groups separated by less than inter_event_steps ----
    merged = _merge_groups(groups, inter_event_steps)

    # ---- Step 3b: cap extremely long cores (sustained wet-season flow) ----
    max_core_steps = int(72 * 6)  # 72 h
    merged = [(s, min(e, s + max_core_steps)) for s, e in merged]

    # ---- Step 4: for each merged group, expand to find start & end ----
    events_list = []
    event_id_map = np.full(n, pd.NA, dtype=object)  # per-row event assignment
    next_id = 1

    for g_start, g_end in merged:
        # Step 4: define event boundaries from the merged core group.
        # Start = first exceedance, padded backward at most lookback hours
        #         (stop when Q drops below start_q).
        # End   = last exceedance, padded forward at most lookahead hours
        #         (stop when Q stays below end_q for end_duration_steps).

        # ---- Event start ----
        evt_start = g_start
        limit_start = max(0, g_start - max_start_lookback)
        while evt_start > limit_start and q[evt_start - 1] > start_q:
            evt_start -= 1

        # ---- Event end ----
        evt_end = g_end
        limit_end = min(n - 1, g_end + max_end_lookahead)
        below_streak = 0
        for i in range(g_end + 1, limit_end + 1):
            if q[i] <= end_q:
                below_streak += 1
            else:
                below_streak = 0
            if below_streak >= end_duration_steps:
                evt_end = i - end_duration_steps + 1
                break
        else:
            evt_end = limit_end

        # Find peak within the event
        peak_idx = evt_start + np.argmax(q[evt_start:evt_end + 1])
        peak_q_val = q[peak_idx]
        peak_h_val = h[peak_idx]

        start_ts = pd.Timestamp(timestamps[evt_start])
        peak_ts = pd.Timestamp(timestamps[peak_idx])
        end_ts = pd.Timestamp(timestamps[evt_end])

        duration = (end_ts - start_ts).total_seconds() / 3600.0

        # Precipitation during event
        acc_precip = _event_precip(grid, start_ts, end_ts)

        # Max hourly rain intensity
        max_intensity = _max_hourly_intensity(grid, start_ts, end_ts)

        # Split assignment based on peak timestamp
        split = _assign_split(peak_ts)

        events_list.append({
            "event_id": next_id,
            "start_ts": start_ts,
            "peak_ts": peak_ts,
            "end_ts": end_ts,
            "peak_q_m3s": round(peak_q_val, 4),
            "peak_h_m": round(float(peak_h_val), 4),
            "duration_h": round(duration, 2),
            "acc_precip_mm": round(acc_precip, 4),
            "max_intensity_mm_h": round(max_intensity, 4),
            "split": split,
        })

        # Mark event rows in the grid
        event_id_map[evt_start:evt_end + 1] = next_id
        next_id += 1

    events = pd.DataFrame(events_list)

    # Add event_id to grid
    grid = grid.copy()
    grid["event_id"] = pd.array(event_id_map, dtype="Int64")

    return events, grid


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _consecutive_groups(indices, max_gap=1):
    """Group indices into consecutive blocks with gap <= max_gap."""
    groups = []
    if len(indices) == 0:
        return groups
    start = indices[0]
    prev = indices[0]
    for idx in indices[1:]:
        if idx - prev > max_gap:
            groups.append((start, prev))
            start = idx
        prev = idx
    groups.append((start, prev))
    return groups


def _merge_groups(groups, inter_event_steps):
    """Merge groups whose gap < inter_event_steps."""
    if len(groups) <= 1:
        return groups
    merged = [groups[0]]
    for g in groups[1:]:
        last_start, last_end = merged[-1]
        gap = g[0] - last_end
        if gap < inter_event_steps:
            merged[-1] = (last_start, g[1])
        else:
            merged.append(g)
    return merged


def _split_long_cores(merged, max_core_steps):
    """Split cores that exceed max_core_steps into chunks.

    Each chunk is at most max_core_steps wide, with a 12-step (2h) overlap
    to avoid cutting events at the exact peak.
    """
    if max_core_steps <= 0:
        return merged
    result = []
    for start, end in merged:
        span = end - start + 1
        if span <= max_core_steps:
            result.append((start, end))
        else:
            pos = start
            while pos < end:
                chunk_end = min(pos + max_core_steps, end)
                result.append((pos, chunk_end))
                pos = chunk_end - 12  # 2h overlap
                if pos <= start:
                    break
    return result


def _event_precip(grid, start_ts, end_ts):
    """Sum all precipitation columns during the event window."""
    window = grid.loc[start_ts:end_ts]
    total = 0.0
    for col in PRECIP_COLS:
        if col in window.columns:
            s = window[col].dropna()
            total += s.sum()
    return total


def _max_hourly_intensity(grid, start_ts, end_ts):
    """Maximum hourly rainfall intensity from any station during event."""
    window = grid.loc[start_ts:end_ts]
    best = 0.0
    for col in PRECIP_COLS:
        if col not in window.columns:
            continue
        hourly = window[col].resample("1h", closed="right", label="right").sum()
        if len(hourly) > 0:
            best = max(best, hourly.max())
    return best


def _assign_split(peak_ts):
    """Assign train/val/test partition based on peak timestamp."""
    peak = pd.Timestamp(peak_ts)
    if peak <= pd.Timestamp("2020-12-31"):
        return "train"
    elif peak <= pd.Timestamp("2022-06-30"):
        return "validation"
    else:
        return "test"


def _empty_result(grid):
    """Return empty events DataFrame and grid with empty event_id."""
    columns = ["event_id", "start_ts", "peak_ts", "end_ts",
               "peak_q_m3s", "peak_h_m", "duration_h",
               "acc_precip_mm", "max_intensity_mm_h", "split"]
    events = pd.DataFrame(columns=columns)
    grid = grid.copy()
    grid["event_id"] = pd.array([pd.NA] * len(grid), dtype="Int64")
    return events, grid


# ---------------------------------------------------------------------------
#  CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Detect flood events")
    parser.add_argument("--grid", default=str(PROCESSED_DIR / "grid_10min.parquet"))
    parser.add_argument("--output", default=str(PROCESSED_DIR / "events.csv"))
    parser.add_argument("--threshold", type=float, default=0.2)
    args = parser.parse_args()

    print(f"Loading grid from {args.grid} ...")
    grid = pd.read_parquet(args.grid)
    print(f"  Grid: {grid.shape[0]:,} rows x {grid.shape[1]} cols")

    events, grid_out = detect_events(grid, peak_q_threshold=args.threshold,
                                     max_start_lookback_h=12,
                                     max_end_lookahead_h=24)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    events.to_csv(out, index=False)
    print(f"\nDetected {len(events)} events -> {out}")
    print(f"  Per-split: {events['split'].value_counts().to_dict()}")

    if len(events) > 0:
        print(f"\nEvent summary:")
        print(events.describe().to_string())
        print(f"\nTop 5 by peak Q:")
        top5 = events.nlargest(5, "peak_q_m3s")
        for _, e in top5.iterrows():
            print(f"  #{int(e['event_id'])}  peak={e['peak_ts']}  "
                  f"Q={e['peak_q_m3s']:.2f} m3/s  H={e['peak_h_m']:.2f} m  "
                  f"dur={e['duration_h']:.1f}h  split={e['split']}")

    # Save grid with event_id
    grid_path = Path(args.grid)
    grid_path_new = grid_path.with_name("grid_10min_with_events.parquet")
    grid_out.to_parquet(grid_path_new)
    print(f"\nGrid with event_id saved to {grid_path_new}")
