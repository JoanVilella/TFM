"""Feature engineering for the STM08 water level prediction task.

Transforms the 10-min grid into a modelling-ready training table.

Features generated
------------------
* Lagged predictors (HEIGHT_m, TEMP_C, PRECIP_mm):
    t-1h, t-2h, t-3h, t-6h, t-12h, t-24h  (shifted by N * 6 steps)

* Cumulative precipitation (antecedent precipitation index):
    Rolling sum over 3h, 6h, 12h, 24h, 48h  (per station)

* Cumulative upstream discharge:
    Sum of DISCHARGE_m3s at STM03--STM07

* Temporal features (sin/cos encoding for cyclical variables):
    hour_sin, hour_cos, doy_sin, doy_cos, month (raw)

* Target columns:
    TARGET_t+1h, TARGET_t+6h, TARGET_t+24h  (STM08_HEIGHT_m lead by N * 6 steps)

Design decisions
----------------
* DISCHARGE lags skipped: Q = f(H) via rating curve => exact multicollinearity
  with HEIGHT lags.  Only the upstream-aggregated sum is included.
  (Kratzert et al. 2019, HESS 23, 5089--5110)

* Cyclical time encoding: sin/cos preserves circular topology of daily and
  annual cycles for models that don't learn it implicitly (Lim et al. 2021,
  International Journal of Forecasting).

* Upstream Q: currently sums STM03--STM07 DISCHARGE assuming all are parallel
  tributaries.  Pending confirmation of basin topology from the geo team;
  if any stations are in series, the sum double-counts and must be corrected.

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

# Upstream hydro stations (aggregated into UPSTREAM_Q)
UPSTREAM_STATIONS = ["STM03", "STM04", "STM05", "STM06", "STM07"]

# Predictor sets (station codes)
HYDRO = ["STM03", "STM04", "STM05", "STM06", "STM07", "STM08"]
METEO = ["STM01", "STM02"]
AEMET = ["B013X", "B605X", "B691Y"]

# Which station/variable pairs get lagged
LAG_CONFIG = {
    "HEIGHT_m": HYDRO,
    "TEMP_C": METEO,
    "PRECIP_mm": METEO + AEMET,
}

# Which stations get cumulative precipitation
CUM_PRECIP_STATIONS = METEO + AEMET

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

    # --- Cumulative precipitation ---
    for code in CUM_PRECIP_STATIONS:
        col = f"{code}_PRECIP_mm"
        if col not in df.columns:
            continue
        for h in CUM_PRECIP_HOURS:
            new_cols[f"{code}_PRECIP_cum_{h}h"] = (
                df[col].rolling(window=h * STEP, min_periods=1).sum()
            )

    # --- Upstream discharge ---
    q_cols = [f"{s}_DISCHARGE_m3s" for s in UPSTREAM_STATIONS]
    existing_q = [c for c in q_cols if c in df.columns]
    if existing_q:
        new_cols["UPSTREAM_Q"] = df[existing_q].sum(axis=1, min_count=1)

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
    print(f"  Output: {df.shape[1]} columns, {df.shape[0]:,} rows")

    return df


# ---------------------------------------------------------------------------
#  CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build training table")
    parser.add_argument("--grid", default=str(PROCESSED_DIR / "grid_10min.parquet"))
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
