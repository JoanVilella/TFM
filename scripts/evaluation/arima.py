"""ARIMA / ARIMAX baselines for STM08 water-level forecasting (Phase 4).

Univariate ARIMA on the STM08 water level with a *dynamic harmonic
regression* representation of the daily cycle (Fourier exogenous terms at the
24 h period), plus an ARIMAX variant that adds a small curated set of
hydrological exogenous inputs.  A full seasonal state-space component at
period 144 was evaluated and rejected: the resulting 146-state Kalman filter
makes fitting and rolling-origin evaluation computationally impractical,
while Fourier terms capture the deterministic daily cycle with three extra
regressors (Harvey 1989; Hyndman et al. 2011 -- "dynamic harmonic regression").

Both variants are evaluated with a *rolling origin* scheme so predictions are
produced per row (aligned to the training-table index) and comparable with
the other baselines:

* The model is fit once on the train split.
* For every daily origin in validation/test the Kalman state is rolled
  forward with ``SARIMAXResults.apply`` over a trailing window of observed
  levels, then a multi-step forecast supplies every row of the following day.
  Future exogenous values are carried forward from the origin; actual future
  observations are never supplied to the forecast.

Usage
-----
    from scripts.evaluation.arima import fit_arima, fit_arimax

    preds = fit_arima(df, horizon=6)     # {"train": ..., "validation": ..., "test": ...}
"""

import numpy as np
import pandas as pd
import warnings

from scripts.evaluation.baselines import TARGET_STATION, SPLITS

# statsmodels emits high-frequency ValueWarning (frequency inference) and
# FutureWarning noise during fit/apply; silence it for readable notebooks.
warnings.filterwarnings("ignore", category=Warning, module="statsmodels")

ENDOG_COL = f"{TARGET_STATION}_HEIGHT_m"
STEPS_PER_HOUR = 6          # 10-min grid
DAILY_PERIOD = 144          # 24 h
N_HARMONICS = 3             # Fourier pairs for the daily cycle
ORIGIN_STEPS = DAILY_PERIOD             # one origin per day
FORECAST_STEPS = 2 * ORIGIN_STEPS       # 288: covers all leads <= 2 days
APPLY_WINDOW_DAYS = 60                  # trailing window for state rolling

# Candidate orders compared by AIC (simple first); daily cycle enters via
# Fourier exog terms, not a seasonal state-space component.
SPEC_CANDIDATES = [(2, 1, 1), (1, 1, 1)]

# Curated hydrological exogenous set for ARIMAX (median-imputed on train).
EXOG_COLS = [
    "STM04_HEIGHT_m", "STM06_HEIGHT_m", "STM07_HEIGHT_m",
    "STM02_PRECIP_cum_6h", "B013X_PRECIP_cum_6h",
    "STM04_HEIGHT_m_lag_6h", "STM06_HEIGHT_m_lag_6h",
]


def _fourier_exog(df):
    """Daily-cycle Fourier pairs (sin/cos x N_HARMONICS) on the grid phase."""
    n = len(df)
    phase = 2 * np.pi * (np.arange(n) % DAILY_PERIOD) / DAILY_PERIOD
    cols = {}
    for k in range(1, N_HARMONICS + 1):
        cols[f"fourier_sin_{k}"] = np.sin(k * phase)
        cols[f"fourier_cos_{k}"] = np.cos(k * phase)
    return pd.DataFrame(cols, index=df.index)


def _fit_sarimax(endog, exog=None, order=(2, 1, 1)):
    """Fit SARIMAX quietly and return the results object."""
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = SARIMAX(
            endog, exog=exog, order=order,
            enforce_stationarity=False, enforce_invertibility=False,
        )
        return model.fit(disp=False)


def select_spec(train_endog, train_fourier):
    """Compare candidate ARIMA orders by AIC on the tail of the train split.

    Returns the winning order.  AIC is computed on the last two years of the
    train split to keep selection fast; the winner is refit on the full split.
    """
    sel = slice(-min(len(train_endog), 2 * 365 * STEPS_PER_HOUR), None)
    best, best_aic = None, np.inf
    for order in SPEC_CANDIDATES:
        try:
            res = _fit_sarimax(train_endog.iloc[sel], exog=train_fourier.iloc[sel],
                               order=order)
            aic = res.aic
        except Exception as exc:  # noqa: BLE001 - report and skip
            print(f"    spec ARIMA{order}: failed ({exc})")
            continue
        print(f"    spec ARIMA{order}: AIC={aic:.1f}")
        if aic < best_aic:
            best, best_aic = order, aic
    return best or SPEC_CANDIDATES[0]


def _imputer_for(X):
    from sklearn.impute import SimpleImputer
    return SimpleImputer(strategy="median").fit(X)


def _rolling_origin_preds(df, res, horizon_steps, exog_all=None):
    """Produce per-row h-step predictions via daily rolling origins.

    The prediction for row t at ``horizon_steps`` is the forecast for time
    t + h issued at the latest daily origin <= t (only information available
    at t is used).  Train-split predictions are the in-sample one-step-ahead
    fitted values.
    """
    preds = {}

    # ---- train: in-sample one-step-ahead fitted values -------------------
    train_mask = (df["split"] == "train").to_numpy()
    try:
        fitted = np.asarray(res.fittedvalues)
        preds["train"] = pd.Series(fitted, index=df.index[train_mask])
    except Exception:
        preds["train"] = pd.Series(np.nan, index=df.index[train_mask])

    # ---- rolling origins over validation + test --------------------------
    vt_mask = df["split"].isin(["validation", "test"]).to_numpy()
    p_vt = np.where(vt_mask)[0]
    if len(p_vt) == 0:
        for s in ("validation", "test"):
            preds[s] = pd.Series(dtype=float)
        return preds

    origin_positions = list(range(p_vt[0], p_vt[-1] + 1, ORIGIN_STEPS))
    if origin_positions[-1] != p_vt[-1]:
        origin_positions.append(p_vt[-1])
    print(f"    rolling origins: {len(origin_positions)} "
          f"(window {APPLY_WINDOW_DAYS} d)")

    hist = df[ENDOG_COL].to_numpy(dtype=float)

    # out[u, u-o-1] = forecast issued at daily origin o for grid position u.
    # Later origins overwrite earlier ones (latest-origin-wins).
    out = np.full((len(df), FORECAST_STEPS), np.nan)

    for o in origin_positions:
        w_start = max(0, o - APPLY_WINDOW_DAYS * STEPS_PER_HOUR)
        window = hist[w_start:o + 1]
        finite = np.isfinite(window)
        if finite.sum() < DAILY_PERIOD * 2:
            continue
        w_idx = np.where(finite)[0]
        rows_w = w_start + w_idx
        endog_w = pd.Series(window[w_idx], index=df.index[rows_w])
        exog_w = None
        exog_fut = None
        if exog_all is not None:
            exog_w = exog_all[rows_w]
            # Exogenous values after the origin are unavailable at forecast
            # time. Carry the last observed origin vector forward instead of
            # leaking actual future levels/rainfall into the forecast.
            if o >= len(exog_all):
                continue
            exog_fut = np.repeat(exog_all[o:o + 1], FORECAST_STEPS, axis=0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                res_o = res.apply(endog_w, exog=exog_w)
                fc = res_o.forecast(steps=FORECAST_STEPS, exog=exog_fut)
            except Exception as exc:  # noqa: BLE001
                print(f"    origin {df.index[o]} failed: {exc}")
                continue
        fc = np.asarray(fc).ravel()[:FORECAST_STEPS]
        # out[u, lead-1] = forecast for grid position u = o+1+lead-1
        k_max = int(min(FORECAST_STEPS, len(df) - (o + 1)))
        if k_max > 0:
            out[o + 1 + np.arange(k_max), np.arange(k_max)] = fc[:k_max]

    for s in ("validation", "test"):
        mask = (df["split"] == s).to_numpy()
        idx = df.index[mask]
        p = np.where(mask)[0]
        vals = np.full(len(p), np.nan)
        oi = 0
        for i, t in enumerate(p):
            while oi + 1 < len(origin_positions) and origin_positions[oi + 1] <= t:
                oi += 1
            u = t + horizon_steps          # target time
            if u >= len(df):
                continue
            lead = u - origin_positions[oi]
            if 1 <= lead <= FORECAST_STEPS:
                vals[i] = out[u, lead - 1]
        preds[s] = pd.Series(vals, index=idx)
    return preds


def fit_arima(df, horizon, order=None, splits=SPLITS):
    """Univariate ARIMA + Fourier daily-cycle baseline.

    Fit on the train split; rolling-origin per-row predictions for
    validation/test.  ``order`` overrides automatic AIC selection.
    """
    return _run(df, horizon, use_exog=False, order=order, splits=splits)


def fit_arimax(df, horizon, order=None, splits=SPLITS):
    """ARIMAX baseline: ARIMA + Fourier daily cycle + curated hydrological exog."""
    return _run(df, horizon, use_exog=True, order=order, splits=splits)


def _run(df, horizon, use_exog, order, splits):
    target_col = f"TARGET_t+{horizon}h"
    if target_col not in df.columns:
        raise ValueError(f"missing target {target_col}")

    train_mask = df["split"] == "train"
    train = df[train_mask]
    endog_train = train[ENDOG_COL].astype(float)
    fourier = _fourier_exog(df)

    exog_df = fourier.copy()
    imputer = None
    if use_exog:
        missing = [c for c in EXOG_COLS if c not in df.columns]
        if missing:
            raise ValueError(f"missing exogenous columns: {missing}")
        exog_df[EXOG_COLS] = df[EXOG_COLS].to_numpy(dtype=float)
        imputer = _imputer_for(exog_df.loc[train_mask].to_numpy(dtype=float))
        exog_arr = imputer.transform(exog_df.to_numpy(dtype=float))
    else:
        exog_arr = exog_df.to_numpy(dtype=float)

    chosen = order or select_spec(endog_train, fourier[train_mask])
    print(f"    fitting SARIMAX{chosen} on {len(endog_train):,} train rows "
          f"(exog={exog_df.shape[1]}) ...")
    res = _fit_sarimax(endog_train, exog=exog_arr[train_mask], order=chosen)

    preds = _rolling_origin_preds(
        df, res, horizon_steps=int(horizon * STEPS_PER_HOUR),
        exog_all=exog_arr)
    return {s: preds[s] for s in SPLITS}
