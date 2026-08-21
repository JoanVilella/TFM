"""Hydrological evaluation metrics for water-level prediction.

Standard metrics (NSE, KGE, RMSE, MAE, PBIAS) plus flood-specific metrics
(peak magnitude/timing error, threshold-exceedance detection) and a per-event
aggregation helper.

Scalar metrics accept array-likes and drop NaN pairs internally.  Peak/timing
and per-event helpers expect pandas Series with a DatetimeIndex so they can
slice event windows and measure timing in hours.

Usage
-----
    from scripts.evaluation.metrics import evaluate, threshold_metrics

    m = evaluate(obs, sim)            # dict: nse/kge/rmse/mae/pbias
    t = threshold_metrics(obs, sim, threshold=0.5)
    pe = per_event_metrics(obs_series, sim_series, events_df)
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
#  Alignment helpers
# ---------------------------------------------------------------------------

def _align(obs, sim):
    """Return NaN-free aligned float arrays (obs, sim)."""
    obs = np.asarray(obs, dtype=float)
    sim = np.asarray(sim, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    return obs[mask], sim[mask]


def _align_series(obs, sim):
    """Return two Series aligned on their common index, both NaN-free."""
    if not isinstance(obs, pd.Series) or not isinstance(sim, pd.Series):
        raise TypeError("peak/per-event helpers require pandas Series inputs")
    common = obs.index.intersection(sim.index)
    o = obs.loc[common].astype(float)
    s = sim.loc[common].astype(float)
    mask = o.notna() & s.notna()
    return o.loc[mask], s.loc[mask]


# ---------------------------------------------------------------------------
#  Scalar metrics
# ---------------------------------------------------------------------------

def nse(obs, sim):
    """Nash-Sutcliffe Efficiency (1 = perfect, <=0 worse than mean)."""
    obs, sim = _align(obs, sim)
    if len(obs) < 2 or np.std(obs) == 0:
        return np.nan
    return float(1 - np.sum((obs - sim) ** 2) / np.sum((obs - np.mean(obs)) ** 2))


def kge(obs, sim):
    """Kling-Gupta Efficiency (1 = perfect)."""
    obs, sim = _align(obs, sim)
    if len(obs) < 2:
        return np.nan
    mu_o, mu_s = float(np.mean(obs)), float(np.mean(sim))
    sd_o, sd_s = float(np.std(obs)), float(np.std(sim))
    if sd_o == 0 or sd_s == 0:
        return np.nan
    r = float(np.corrcoef(obs, sim)[0, 1])
    alpha = sd_s / sd_o
    beta = mu_s / mu_o
    return float(1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2))


def rmse(obs, sim):
    obs, sim = _align(obs, sim)
    return float(np.sqrt(np.mean((obs - sim) ** 2)))


def mae(obs, sim):
    obs, sim = _align(obs, sim)
    return float(np.mean(np.abs(obs - sim)))


def pbias(obs, sim):
    """Percent bias (positive = over-estimation)."""
    obs, sim = _align(obs, sim)
    if np.sum(obs) == 0:
        return np.nan
    return float(100 * np.sum(sim - obs) / np.sum(obs))


def evaluate(obs, sim):
    """Bundle the standard scalar metrics into a dict."""
    obs, sim = _align(obs, sim)
    return {
        "n": int(len(obs)),
        "nse": nse(obs, sim),
        "kge": kge(obs, sim),
        "rmse": rmse(obs, sim),
        "mae": mae(obs, sim),
        "pbias": pbias(obs, sim),
    }


# ---------------------------------------------------------------------------
#  Flood-specific metrics
# ---------------------------------------------------------------------------

def peak_error(obs, sim):
    """Peak magnitude and timing error over the full record.

    Parameters
    ----------
    obs, sim : pd.Series with DatetimeIndex.

    Returns
    -------
    dict with ``peak_mag_err`` (m, sim - obs) and ``peak_time_err_h``
    (hours, positive = simulated peak later than observed).
    """
    o, s = _align_series(obs, sim)
    if len(o) == 0:
        return {"peak_mag_err_m": np.nan, "peak_time_err_h": np.nan}
    io, is_ = o.idxmax(), s.idxmax()
    return {
        "peak_mag_err_m": float(s.loc[is_] - o.loc[io]),
        "peak_time_err_h": float((is_ - io).total_seconds() / 3600.0),
    }


def threshold_metrics(obs, sim, threshold):
    """Exceedance-detection metrics (POD / FAR / CSI) for a level threshold.

    ``hits``: both exceed; ``misses``: obs exceeds, sim does not;
    ``false_alarms``: sim exceeds, obs does not.
    """
    obs, sim = _align(obs, sim)
    obs_exc = obs > threshold
    sim_exc = sim > threshold
    hits = int(np.sum(obs_exc & sim_exc))
    misses = int(np.sum(obs_exc & ~sim_exc))
    fas = int(np.sum(~obs_exc & sim_exc))
    pod = hits / (hits + misses) if (hits + misses) > 0 else np.nan
    far = fas / (hits + fas) if (hits + fas) > 0 else np.nan
    csi = hits / (hits + misses + fas) if (hits + misses + fas) > 0 else np.nan
    return {
        "threshold": float(threshold),
        "pod": pod, "far": far, "csi": csi,
        "hits": hits, "misses": misses, "false_alarms": fas,
    }


def per_event_metrics(obs, sim, events):
    """Per-event NSE, peak-magnitude and peak-timing error.

    Parameters
    ----------
    obs, sim : pd.Series with DatetimeIndex covering the full record.
    events : pd.DataFrame with columns ``event_id``, ``start_ts``, ``end_ts``
        (and optionally ``peak_ts``, ``split``).

    Returns
    -------
    pd.DataFrame, one row per event with enough overlap.
    """
    rows = []
    for _, ev in events.iterrows():
        s = pd.Timestamp(ev["start_ts"])
        e = pd.Timestamp(ev["end_ts"])
        o = obs.loc[s:e]
        si = sim.loc[s:e]
        o, si = _align_series(o, si)
        if len(o) < 2:
            continue
        io, is_ = o.idxmax(), si.idxmax()
        rows.append({
            "event_id": ev["event_id"],
            "nse": nse(o.values, si.values),
            "rmse": rmse(o.values, si.values),
            "peak_mag_err_m": float(si.loc[is_] - o.loc[io]),
            "peak_time_err_h": float((is_ - io).total_seconds() / 3600.0),
            "obs_peak_m": float(o.loc[io]),
            "sim_peak_m": float(si.loc[is_]),
        })
    return pd.DataFrame(rows)
