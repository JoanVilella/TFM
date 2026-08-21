"""Baseline models for STM08 water-level forecasting (Phase 4).

Three lower-bound baselines:

* ``persistence``  — y(t+h) = y(t) (current STM08 level), no training.
* ``ridge``        — linear regression (Ridge) on the median-imputed predictors
  (long gaps filled; ``_MISSING`` masks retained as features).
* ``random_forest`` — RandomForest on the same median-imputed predictors, with
  an optional flood-preserving training subsample for speed.

Imputation is fit on the train split only and applied to every split, so there
is no leakage.  Prediction is always produced for the full train/val/test
splits (subsampling only trims the training rows).  XGBoost (NaN-native) and
ARIMA/SARIMAX are added in a later pass.

Usage
-----
    from scripts.evaluation.baselines import (
        predictor_cols, persistence_predictions, fit_ridge, fit_random_forest,
    )

    preds = fit_ridge(df, horizon=1)          # -> {"train": Series, "test": Series, ...}
"""

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor

TARGET_STATION = "STM08"
SPLITS = ("train", "validation", "test")


def predictor_cols(df):
    """Return the predictor column names of the training table.

    Excludes targets, the split/event_id labels, and the QUALITY / DATA_TYPE
    metadata columns (the ``_MISSING`` indicators are kept as predictors).
    """
    return [
        c for c in df.columns
        if not c.startswith("TARGET")
        and not c.endswith(("_QUALITY", "_DATA_TYPE"))
        and c not in ("split", "event_id")
    ]


def persistence_predictions(df):
    """Persistence baseline: predict the future as the current STM08 level.

    Returns a Series aligned to ``df.index`` (no training involved).
    """
    return df[f"{TARGET_STATION}_HEIGHT_m"].copy()


def _subsample_rows(train, max_rows, seed=42):
    """Cap training rows while keeping every flood-event row."""
    if max_rows is None or len(train) <= max_rows:
        return train
    if "event_id" in train.columns:
        event_rows = train[train["event_id"].notna()]
        non_event = train[train["event_id"].isna()]
        n_non = max_rows - len(event_rows)
        if n_non > 0 and len(non_event) > n_non:
            non_event = non_event.sample(n=n_non, random_state=seed)
        return pd.concat([event_rows, non_event]).sort_index()
    return train.sample(n=max_rows, random_state=seed)


def _fit_predict_sklearn(df, horizon, model, splits=SPLITS, subsample=None):
    """Fit an sklearn estimator (with median imputation) and predict per split.

    The imputer is fit on the (optionally subsampled) train split only; the
    fitted model then predicts every full split.  Returns {split: pd.Series}
    aligned to each split's index.
    """
    cols = predictor_cols(df)
    target = f"TARGET_t+{horizon}h"

    train = df[df["split"] == "train"]
    if target not in df.columns or len(train) == 0:
        raise ValueError(f"missing target {target} or empty train split")

    train_used = _subsample_rows(train, subsample)
    imputer = SimpleImputer(strategy="median")
    X_train = imputer.fit_transform(train_used[cols])
    y_train = train_used[target].values
    model.fit(X_train, y_train)

    preds = {}
    for s in splits:
        sub = df[df["split"] == s]
        Xs = imputer.transform(sub[cols])
        preds[s] = pd.Series(model.predict(Xs), index=sub.index, name=f"pred_{target}")
    return preds


def fit_ridge(df, horizon, alpha=1.0, splits=SPLITS):
    """Ridge regression baseline (median-imputed predictors)."""
    return _fit_predict_sklearn(df, horizon, Ridge(alpha=alpha), splits=splits)


def fit_random_forest(df, horizon, n_estimators=100, n_jobs=-1, subsample=60000,
                      splits=SPLITS):
    """Random Forest baseline (median-imputed predictors).

    ``subsample`` caps the number of training rows for speed (flood-event rows
    are always retained); prediction is still produced for the full splits.
    """
    model = RandomForestRegressor(
        n_estimators=n_estimators, n_jobs=n_jobs, random_state=42,
    )
    return _fit_predict_sklearn(df, horizon, model, splits=splits,
                                subsample=subsample)
