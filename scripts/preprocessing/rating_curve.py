"""Rating curve module: HEIGHT_m -> DISCHARGE_m3s via piecewise polynomials.

Reads data/rating_curves/rating_curves.csv and builds callable rating-curve
functions for each hydro station (STM03--STM08).  Only the `meters_to_flow`
direction is implemented; `flow_to_meters` (inverse) is deferred.

The polynomial for a segment is:

    Q(H) = sum_i (base_i * H^exp_i)

where bases and exponents are listed in the CSV from highest term to lowest.

Usage
-----
    from scripts.preprocessing.rating_curve import load_rating_curves, apply_discharge

    curves = load_rating_curves()          # -> {station_code: callable}
    discharge = curves["STM03"](0.5)       # -> float (m3/s)

    # Apply to a 10-min grid:
    grid = apply_discharge(grid, curves)
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


def load_rating_curves(path=None):
    """Load all meters_to_flow rating curves.

    Returns
    -------
    curves : dict
        {station_code: callable(height) -> discharge}.
    """
    if path is None:
        path = CURVES_PATH

    # Group rows by station
    raw_segments = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["type"] != "meters_to_flow":
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

    # Build callables
    curves = {}
    for code, segments in raw_segments.items():
        segments.sort(key=lambda s: s["order"])
        curves[code] = _build_piecewise(segments, code)

    return curves


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
