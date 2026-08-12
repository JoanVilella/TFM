"""DSS I/O module for HEC-HMS integration.

Reads and writes HEC-DSS time series files using pydsstools.

Environment
-----------
Requires Java JDK installed and JAVA_HOME set.  The hec-monolith JAR
is bundled with HEC-HMS and loaded automatically by pydsstools.

Usage
-----
    from scripts.hec_hms.dss_io import write_precip, read_ts

    write_precip("output.dss", gage_data, interval_min=15)
    df = read_ts("Validation.dss", "//R14/FLOW-OBSERVED/*/*/*/")
"""

import os
import numpy as np
import pandas as pd
from pathlib import Path
from pydsstools.heclib.dss import HecDss

# Suppress rasterio import warning (we don't use grids)
import warnings
warnings.filterwarnings("ignore", category=ImportWarning)

REPO_ROOT = Path(__file__).resolve().parents[2]
HEC_HMS_DIR = REPO_ROOT / "hec_hms" / "STM"

# Our precipitation stations -> HEC-HMS gage names
PRECIP_GAGES = {
    "STM01": "STM01",
    "STM02": "STM02",
    "B013X": "B013X",
    "B605X": "B605X",
    "B691Y": "B691Y",
}

# HEC-HMS observed flow elements
FLOW_ELEMENTS = {
    "STM03": ["S1", "J10", "R16"],
    "STM04": ["R7", "S17"],
    "STM05": ["R17", "S15"],
    "STM06": ["R10"],
    "STM07": ["R3", "S23"],
    "STM08": ["R14", "S27", "Sink-1"],
}


def _build_pathname(gage, variable, date_str, interval_min, tag="OBS"):
    """Build a 7-part DSS pathname.

    Pathname: /<empty>/GAGE/VARIABLE/DDMMMYYYY/INTERVAL/TAG/

    Parameters
    ----------
    gage : str
        Gage or element name.
    variable : str
        Data type (PRECIP-INC, FLOW, STAGE, etc.).
    date_str : str
        Start date in DDMMMYYYY format (e.g. "15DEC2016").
    interval_min : int
        Time interval in minutes.
    tag : str
        Data tag (OBS, RUN:Validation, etc.).
    """
    if interval_min >= 60:
        interval_str = f"{interval_min // 60}Hour"
    else:
        interval_str = f"{interval_min}Minute"
    return f"//{gage}/{variable}/{date_str}/{interval_str}/{tag}/"


def write_precip(dss_path, gage_data, start_date, interval_min=15,
                 units="MM", tag="OBS"):
    """Write incremental precipitation time series to a DSS file.

    Parameters
    ----------
    dss_path : str or Path
        Path to output DSS file (created if it doesn't exist).
    gage_data : dict
        {gage_name: pd.Series} with DatetimeIndex and float values.
    start_date : str
        Start date in DDMMMYYYY format (e.g. "15DEC2016").
    interval_min : int
        Time interval in minutes (default 15).
    units : str
        Data units (default "MM").
    tag : str
        Data tag (default "OBS").
    """
    dss_path = str(dss_path)
    dss = HecDss.Open(dss_path, mode="rw")

    for gage, series in gage_data.items():
        series = series.dropna()
        if len(series) == 0:
            continue

        pathname = _build_pathname(gage, "PRECIP-INC", start_date,
                                   interval_min, tag)

        values = series.values.astype(np.float64).tolist()
        start_time = series.index[0].strftime("%d%b%Y %H%M").upper()

        dss.put_ts(pathname, values=values, start_time=start_time,
                   data_units=units, data_type="PER-CUM")

    dss.close()


def read_ts(dss_path, path_pattern="/*/*/*/*/*/*/"):
    """Read time series from a DSS file.

    Parameters
    ----------
    dss_path : str
        Path to DSS file.
    path_pattern : str
        Wildcard pattern to search for paths (e.g. "//R14/FLOW*/*/*/*/").

    Returns
    -------
    dict
        {pathname: pd.Series} mapping each matching pathname to its time series.
    """
    dss = HecDss.Open(str(dss_path))
    results = {}

    for pathname in dss.search_path(path_pattern):
        data = dss.read_ts(pathname)
        if data is None:
            continue
        times = pd.to_datetime([str(t) for t in data.pyofts()])
        values = data.values
        s = pd.Series(values, index=times, name=pathname)
        results[pathname] = s

    dss.close()
    return results


def read_observed_flow(dss_path, station, run_tag_pattern="*"):
    """Read all observed flow records for a station from a DSS file.

    Parameters
    ----------
    dss_path : str
        Path to DSS file.
    station : str
        Station code (STM03--STM08).
    run_tag_pattern : str
        Run tag filter (default "*").

    Returns
    -------
    dict
        {element_name: pd.Series} mapping elements to flow time series.
    """
    if station not in FLOW_ELEMENTS:
        return {}

    result = {}
    for elem in FLOW_ELEMENTS[station]:
        pattern = f"//{elem}/FLOW*/{run_tag_pattern}/"
        ts_dict = read_ts(dss_path, pattern)
        result.update(ts_dict)

    return result
