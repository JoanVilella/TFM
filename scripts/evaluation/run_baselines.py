"""Run Phase 4 baselines and save evaluation metrics.

Fits persistence, ridge and random-forest baselines for each horizon
(t+1h, t+6h, t+24h), evaluates them per split (train/validation/test) with
standard + flood-specific metrics, and writes the results to results/metrics/.

Usage
-----
    python scripts/evaluation/run_baselines.py
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluation.baselines import (
    persistence_predictions, fit_ridge, fit_random_forest, fit_xgboost,
)
from scripts.evaluation.arima import fit_arima, fit_arimax
from scripts.evaluation import metrics as M

PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RESULTS_DIR = REPO_ROOT / "results" / "metrics"

HORIZONS = [1, 6, 24]
SPLITS = ["train", "validation", "test"]
MODELS = ["persistence", "ridge", "random_forest", "xgboost", "arima", "arimax"]

# Exceedance thresholds (m) for the threshold-detection metrics.  STM08 is
# near 0 m at rest and reaches ~2.8 m in the largest historical flood, so
# 0.5 m and 1.0 m bracket "notable" and "clearly flooding" levels.
THRESHOLDS = [0.5, 1.0]


def load_table():
    return pd.read_parquet(PROCESSED_DIR / "training_table.parquet")


def load_events():
    return pd.read_csv(PROCESSED_DIR / "events.csv")


def run_model(df, model_name, horizon):
    """Return {split: prediction Series} for one model and horizon."""
    target = f"TARGET_t+{horizon}h"
    if model_name == "persistence":
        pred = persistence_predictions(df)
        return {s: pred.loc[df["split"] == s] for s in SPLITS}
    if model_name == "ridge":
        return fit_ridge(df, horizon)
    if model_name == "random_forest":
        return fit_random_forest(df, horizon)
    if model_name == "xgboost":
        return fit_xgboost(df, horizon)
    if model_name == "arima":
        return fit_arima(df, horizon)
    if model_name == "arimax":
        return fit_arimax(df, horizon)
    raise ValueError(model_name)


def evaluate_split(obs, sim):
    """Bundle standard + flood metrics for one split."""
    row = M.evaluate(obs, sim)
    row["peak_mag_err_m"] = M.peak_error(obs, sim)["peak_mag_err_m"]
    row["peak_time_err_h"] = M.peak_error(obs, sim)["peak_time_err_h"]
    for t in THRESHOLDS:
        tm = M.threshold_metrics(obs, sim, t)
        row[f"pod@{t}m"] = tm["pod"]
        row[f"far@{t}m"] = tm["far"]
        row[f"csi@{t}m"] = tm["csi"]
    return row


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    df = load_table()
    events = load_events()
    target_col = "STM08_HEIGHT_m"
    print(f"Training table: {df.shape[0]:,} rows x {df.shape[1]} cols")

    summary_rows = []
    per_event_rows = []

    for model_name in MODELS:
        for horizon in HORIZONS:
            target = f"TARGET_t+{horizon}h"
            print(f"\n=== {model_name}  |  t+{horizon}h ===")
            preds = run_model(df, model_name, horizon)

            for split in SPLITS:
                sub = df[df["split"] == split]
                obs = sub[target]
                sim = preds[split]
                r = evaluate_split(obs, sim)
                summary_rows.append({
                    "model": model_name, "horizon_h": horizon, "split": split, **r,
                })
                print(f"  {split:<11} NSE={r['nse']:7.3f}  KGE={r['kge']:7.3f}  "
                      f"RMSE={r['rmse']:.3f}  PBIAS={r['pbias']:6.1f}%")

            # Per-event evaluation on the test split only
            obs_test = df.loc[df["split"] == "test", target]
            sim_test = preds["test"]
            ev_test = events[events["split"] == "test"]
            pe = M.per_event_metrics(obs_test, sim_test, ev_test)
            if len(pe):
                pe["model"] = model_name
                pe["horizon_h"] = horizon
                per_event_rows.append(pe)
                print(f"  test events: {len(pe)} evaluated, "
                      f"median event NSE={pe['nse'].median():.3f}")

    summary = pd.DataFrame(summary_rows)
    summary_path = RESULTS_DIR / "baselines_summary.csv"
    summary.to_csv(summary_path, index=False)
    print(f"\nSaved summary -> {summary_path}")

    if per_event_rows:
        pe_all = pd.concat(per_event_rows, ignore_index=True)
        pe_path = RESULTS_DIR / "baselines_per_event.csv"
        pe_all.to_csv(pe_path, index=False)
        print(f"Saved per-event -> {pe_path}")

    print("\n=== Summary ===")
    piv = summary.pivot_table(
        index=["model", "horizon_h"], columns="split", values="nse")
    print(piv.round(3).to_string())


if __name__ == "__main__":
    main()
