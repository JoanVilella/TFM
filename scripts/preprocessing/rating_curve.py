"""Rating curve module: HEIGHT_m ↔ DISCHARGE_m3s via piecewise polynomials.

Reads data/rating_curves/rating_curves.csv and builds callable rating-curve
functions for each hydro station (STM03--STM08) in either direction.

The polynomial for a segment is:

    y(x) = sum_i (base_i * x^exp_i)

where bases and exponents are listed in the CSV from highest term to lowest.

Usage
-----
    from scripts.preprocessing.rating_curve import load_rating_curves, apply_discharge

    # H -> Q (forward)
    h_to_q = load_rating_curves()
    q = h_to_q["STM08"](1.2)          # -> float (m3/s)

    # Q -> H (inverse)
    q_to_h = load_rating_curves(direction="flow_to_meters")
    h = q_to_h["STM08"](5.0)          # -> float (m); STM08 auto-inverted

    # Apply to a 10-min grid:
    grid = apply_discharge(grid, h_to_q)
"""

import json
import csv
import numpy as np
import pandas as pd
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CURVES_PATH = REPO_ROOT / "data" / "rating_curves" / "rating_curves.csv"

HYDRO_STATIONS = ["STM03", "STM04", "STM05", "STM06", "STM07", "STM08"]


def _parse_braced_list(raw):
    """Parse a CSV value like '{0.5223}' or '{4.9727,5.9079}' into a list of floats."""
    raw = raw.strip()
    if raw == "NULL" or raw == "":
        return []
    # Remove braces and split
    inner = raw.strip("{}")
    if inner == "":
        return []
    return [float(x.strip()) for x in inner.split(",")]


def load_rating_curves(path=None, direction="meters_to_flow"):
    """Load rating curves in the specified direction.

    Parameters
    ----------
    path : Path or None
        Path to rating_curves.csv.
    direction : str
        ``"meters_to_flow"`` (H → Q) or ``"flow_to_meters"`` (Q → H).
        For STM08, the inverse direction is auto-generated via dense sampling
        of the forward curve (no explicit flow_to_meters rows exist).

    Returns
    -------
    curves : dict
        {station_code: callable(x) -> y}.
    """
    if path is None:
        path = CURVES_PATH

    # Group rows by station for the requested direction
    raw_segments = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["type"] != direction:
                continue
            code = row["station_code"]
            seg = {
                "order": int(row["section_order"]),
                "x0": float(row["initial_x"]),
                "x1": None if row["final_x"].strip() == "NULL" else float(row["final_x"]),
                "bases": _parse_braced_list(row["bases"]),
                "exponents": _parse_braced_list(row["exponents"]),
            }
            raw_segments.setdefault(code, []).append(seg)

    # Build callables from explicit rows
    curves = {}
    for code, segments in raw_segments.items():
        segments.sort(key=lambda s: s["order"])
        curves[code] = _build_piecewise(segments, code)

    # STM08: auto-invert forward curve if direction is flow_to_meters
    if direction == "flow_to_meters" and "STM08" not in curves:
        forward_fn = load_rating_curves(path, direction="meters_to_flow").get("STM08")
        if forward_fn is not None:
            curves["STM08"] = _invert_forward(forward_fn)

    return curves


def _invert_forward(forward_fn, q_max=500.0, n=10000):
    """Invert a forward rating curve Q=f(H) via dense sampling.

    Builds H = f⁻¹(Q) by sampling H uniformly, computing Q, and interpolating.
    """
    h_samples = np.linspace(0, 5.0, n)
    q_samples = forward_fn(h_samples)
    # Keep only the monotonic, non-NaN portion
    valid = ~np.isnan(q_samples)
    h_samples = h_samples[valid]
    q_samples = q_samples[valid]

    def inverse(q):
        qi = np.asarray(q, dtype=float)
        scalar = qi.ndim == 0
        qi = np.atleast_1d(qi)
        result = np.interp(qi, q_samples, h_samples, left=np.nan, right=np.nan)
        return result.item() if scalar else result

    return inverse


def _build_piecewise(segments, code):
    """Build a vectorized piecewise polynomial function from ordered segments."""

    def curve(height):
        """Evaluate Q = f(H) for scalar or array H."""
        h = np.asarray(height, dtype=float)
        scalar = h.ndim == 0
        h = np.atleast_1d(h)
        result = np.full_like(h, np.nan, dtype=float)

        for seg in segments:
            mask = (h >= seg["x0"])
            if seg["x1"] is not None:
                mask &= (h < seg["x1"])
            if not np.any(mask):
                continue

            h_seg = h[mask]
            q = np.zeros_like(h_seg, dtype=float)
            for base, exp in zip(seg["bases"], seg["exponents"]):
                q += base * (h_seg ** exp)
            result[mask] = q

        return result.item() if scalar else result

    return curve


def apply_discharge(grid, curves=None, stations=None):
    """Add {STATION}_DISCHARGE_m3s columns to the 10-min grid.

    Parameters
    ----------
    grid : pd.DataFrame
        The 10-min grid with {STATION}_HEIGHT_m columns.
    curves : dict, optional
        Pre-loaded rating curves.
    stations : list, optional
        Which stations to process (default: all HYDRO).

    Returns
    -------
    grid : pd.DataFrame
        Same DataFrame with new DISCHARGE columns added.
    """
    if curves is None:
        curves = load_rating_curves()
    if stations is None:
        stations = HYDRO_STATIONS

    for code in stations:
        if code not in curves:
            continue
        height_col = f"{code}_HEIGHT_m"
        if height_col not in grid.columns:
            continue

        print(f"  Computing DISCHARGE_m3s for {code} ...")
        q = curves[code](grid[height_col].values)
        grid[f"{code}_DISCHARGE_m3s"] = q

    return grid


# ---------------------------------------------------------------------------
#  CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test rating curves")
    parser.add_argument("--station", default="STM08")
    parser.add_argument("--heights", nargs="+", type=float,
                        default=[0.0, 0.2, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0])
    args = parser.parse_args()

    curves = load_rating_curves()

    print(f"Rating curves loaded: {list(curves.keys())}")
    print()
    for code, fn in curves.items():
        print(f"  {code}: H range check")
        for h in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]:
            q = fn(h)
            print(f"    H={h:.1f} m -> Q={q:.4f} m3/s")
        print()
