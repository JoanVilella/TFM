"""Feature engineering for the STM08 water level prediction task.

Transforms the 10-min grid into a modelling-ready training table.

Features generated
------------------
* Lagged predictors (HEIGHT_m, TEMP_C, PRECIP_mm, DISCHARGE_m3s):
    t-1h, t-2h, t-3h, t-6h, t-12h, t-24h  (shifted by N * 6 steps)

* Cumulative precipitation (antecedent precipitation index):
    Rolling sum over 3h, 6h, 12h, 24h, 48h  (per station)

* Flow features (basin topology confirmed, Iteration 16):
    - Individual discharge lags for STM03--STM07.
    - Lateral inflows (inter-station flow differences):
          dQ_03_04 = Q(STM04) - Q(STM03)
          dQ_05_06 = Q(STM06) - Q(STM04) - Q(STM05)
    - Total inflow to STM08: Q_IN_STM08 = Q(STM06) + Q(STM07)
      (replaces the old UPSTREAM_Q sum-of-all-five, which double-counted the
      series stations)

* Temporal features (sin/cos encoding for cyclical variables):
    hour_sin, hour_cos, doy_sin, doy_cos, month (raw)

* Target columns:
    TARGET_t+1h, TARGET_t+6h, TARGET_t+24h  (STM08_HEIGHT_m lead by N * 6 steps)

Design decisions
----------------
* Basin topology (confirmed by the geo team):
    STM03 -> STM04 -> STM06 -> STM08  (main channel, in series)
    STM05 merges into STM06; STM07 merges directly into STM08.
    Hence Q_IN_STM08 = Q6 + Q7, and the lateral inflows are Q4 - Q3 and
    Q6 - Q4 - Q5.  Individual discharge is kept alongside the derived
    differences because the karstic system does not always behave as a clean
    series routing (losses, subsurface flow), so the raw flows carry
    information the differences alone may not.

* Cyclical time encoding: sin/cos preserves circular topology of daily and
  annual cycles for models that don't learn it implicitly (Lim et al. 2021,
  International Journal of Forecasting).

Usage
-----
    from scripts.preprocessing.feature_engineering import build_training_table

    df = build_training_table(grid)
    df.to_parquet("data/processed/training_table.parquet")
"""

import numpy as np
import pandas as pd
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

# Lags in hours (converted to 10-min steps below)
LAG_HOURS = [1, 2, 3, 6, 12, 24]
STEP = 6  # 10-min steps per hour

# Cumulative precipitation windows (hours)
CUM_PRECIP_HOURS = [3, 6, 12, 24, 48]

# Upstream hydro stations with discharge observations
DISCHARGE_STATIONS = ["STM03", "STM04", "STM05", "STM06", "STM07"]

# Predictor sets (station codes)
HYDRO = ["STM03", "STM04", "STM05", "STM06", "STM07", "STM08"]
METEO = ["STM01", "STM02"]
AEMET = ["B013X", "B605X", "B691Y"]

# Which station/variable pairs get lagged
LAG_CONFIG = {
    "HEIGHT_m": HYDRO,
    "TEMP_C": METEO,
    "PRECIP_mm": METEO + AEMET,
    "DISCHARGE_m3s": DISCHARGE_STATIONS,
}

# Which stations get cumulative precipitation
CUM_PRECIP_STATIONS = METEO + AEMET

# Inter-station lateral inflows: name -> (downstream, [upstream terms]).
# The lateral inflow is Q(downstream) minus the sum of the upstream terms
# listed (all of which drain into `downstream` on the confirmed topology).
FLOW_DIFFS = {
    # STM03 -> STM04 (main channel)
    "dQ_03_04": ("STM04", ["STM03"]),
    # STM05 merges into STM06; net inflow beyond STM04 and STM05
    "dQ_05_06": ("STM06", ["STM04", "STM05"]),
}

# Direct inflows to the STM08 wetland: the main channel (STM06) plus the
# tributary that reaches STM08 directly (STM07).  Replaces the old
# UPSTREAM_Q = sum(STM03..STM07), which double-counted the series stations.
INFLOW_STM08 = ["STM06", "STM07"]

TARGET_STATION = "STM08"


# ---------------------------------------------------------------------------
#  Main entry point
# ---------------------------------------------------------------------------

def build_training_table(grid, horizons_h=(1, 6, 24)):
    """Apply full feature engineering pipeline to the 10-min grid.

    Parameters
    ----------
    grid : pd.DataFrame
        The 10-min grid from build_10min_grid().
    horizons_h : tuple
        Prediction horizons in hours (default: 1, 6, 24).

    Returns
    -------
    df : pd.DataFrame
        Feature-engineered DataFrame with target columns.  Rows where any
        target is NaN are dropped.
    """
    df = grid.copy()

    print("Feature engineering ...")
    print(f"  Input: {df.shape[1]} columns, {df.shape[0]:,} rows")

    new_cols = {}

    # --- Lagged features ---
    for var, stations in LAG_CONFIG.items():
        for code in stations:
            col = f"{code}_{var}"
            if col not in df.columns:
                continue
            for h in LAG_HOURS:
                new_cols[f"{code}_{var}_lag_{h}h"] = df[col].shift(h * STEP)
                # Pair each lagged value with its lagged missingness mask
                miss_col = f"{col}_MISSING"
                if miss_col in df.columns:
                    new_cols[f"{miss_col}_lag_{h}h"] = df[miss_col].shift(h * STEP)

    # --- Cumulative precipitation ---
    for code in CUM_PRECIP_STATIONS:
        col = f"{code}_PRECIP_mm"
        if col not in df.columns:
            continue
        for h in CUM_PRECIP_HOURS:
            new_cols[f"{code}_PRECIP_cum_{h}h"] = (
                df[col].rolling(window=h * STEP, min_periods=1).sum()
            )

    # --- Flow features: lateral inflows + total inflow to STM08 ---
    for name, (down, ups) in FLOW_DIFFS.items():
        down_col = f"{down}_DISCHARGE_m3s"
        up_cols = [f"{u}_DISCHARGE_m3s" for u in ups]
        up_cols = [c for c in up_cols if c in df.columns]
        if down_col not in df.columns or not up_cols:
            continue
        lateral = df[down_col] - df[up_cols].sum(axis=1, min_count=1)
        new_cols[name] = lateral
        for h in LAG_HOURS:
            new_cols[f"{name}_lag_{h}h"] = lateral.shift(h * STEP)

    inflow_cols = [f"{c}_DISCHARGE_m3s" for c in INFLOW_STM08
                   if f"{c}_DISCHARGE_m3s" in df.columns]
    if inflow_cols:
        inflow = df[inflow_cols].sum(axis=1, min_count=1)
        new_cols["Q_IN_STM08"] = inflow
        for h in LAG_HOURS:
            new_cols[f"Q_IN_STM08_lag_{h}h"] = inflow.shift(h * STEP)

    # --- Temporal features ---
    idx = df.index
    hour = idx.hour + idx.minute / 60.0
    doy = idx.dayofyear
    new_cols["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    new_cols["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    new_cols["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    new_cols["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    new_cols["month"] = idx.month.astype("int8")

    # --- Target columns ---
    target_col = f"{TARGET_STATION}_HEIGHT_m"
    for h in horizons_h:
        new_cols[f"TARGET_t+{h}h"] = df[target_col].shift(-h * STEP)

    # Concat all new columns at once (avoids fragmentation)
    df_new = pd.DataFrame(new_cols, index=df.index)
    df = pd.concat([df, df_new], axis=1)

    print(f"  After features: {df.shape[1]} columns")

    n_before = len(df)
    target_cols = [f"TARGET_t+{h}h" for h in horizons_h]
    df = df.dropna(subset=target_cols)
    n_dropped = n_before - len(df)
    print(f"  Dropped {n_dropped:,} rows with NaN targets "
          f"(end-of-series, {horizons_h[-1]}h horizon)")

    # --- Chronological split ---
    df = add_chronological_split(df)

    print(f"  Output: {df.shape[1]} columns, {df.shape[0]:,} rows")

    return df


def add_chronological_split(df, train_end="2020-12-31",
                            val_end="2022-06-30"):
    """Add a ``split`` column (train/val/test) via strict chronological cut.

    Parameters
    ----------
    df : pd.DataFrame
        Training table with DatetimeIndex.
    train_end : str
        Last timestamp in training set.
    val_end : str
        Last timestamp in validation set.

    Returns
    -------
    df : pd.DataFrame
        Same DataFrame with ``split`` column added.
    """
    ts = pd.Timestamp
    train_mask = df.index <= ts(train_end)
    val_mask = (df.index > ts(train_end)) & (df.index <= ts(val_end))
    test_mask = df.index > ts(val_end)

    df["split"] = "test"
    df.loc[train_mask, "split"] = "train"
    df.loc[val_mask, "split"] = "validation"
    df["split"] = df["split"].astype("category")

    n_train = train_mask.sum()
    n_val = val_mask.sum()
    n_test = test_mask.sum()
    print(f"  Chronological split: train={n_train:,}  "
          f"val={n_val:,}  test={n_test:,}")
    return df


# ---------------------------------------------------------------------------
#  CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build training table")
    parser.add_argument("--grid", default=str(PROCESSED_DIR / "grid_10min_imputed.parquet"))
    parser.add_argument("--output", default=str(PROCESSED_DIR / "training_table.parquet"))
    args = parser.parse_args()

    print(f"Loading grid from {args.grid} ...")
    grid = pd.read_parquet(args.grid)
    print(f"  Grid: {grid.shape[0]:,} rows x {grid.shape[1]} cols")

    df = build_training_table(grid)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out)
    print(f"\nSaved: {out}")
    print(f"  Size: {out.stat().st_size / 1e6:.1f} MB")
