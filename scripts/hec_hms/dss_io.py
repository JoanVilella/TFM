"""DSS I/O module for HEC-HMS integration via JPype.

Reads and writes HEC-DSS time series using the hec-monolith JAR shipped
with HEC-HMS (Java 17 required).  Set JAVA_HOME to a JDK 17 installation.

Usage
-----
    from scripts.hec_hms.dss_io import write_precip, read_ts

    write_precip("output.dss", gage_data, "15Dec2016", interval_min=15)
    df = read_ts("output.dss")
"""

import os
import numpy as np
import pandas as pd
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HEC_HMS_DIR = REPO_ROOT / "hec_hms" / "STM"

# HEC-HMS installation paths (configurable)
HEC_INSTALL = os.environ.get("HEC_HMS_HOME",
    r"C:\Program Files\HEC\HEC-HMS\4.13")
HEC_LIB_DIR = os.path.join(HEC_INSTALL, "lib")
HEC_BIN_DIR = os.path.join(HEC_INSTALL, "bin")

# JDK 17 (bundled JRE or explicit)
JDK_17 = os.environ.get("JAVA_HOME_17",
    r"C:\Program Files\Java\jdk-17")

# Our precipitation stations -> HEC-HMS gage names
PRECIP_GAGES = {
    "STM01": "STM01", "STM02": "STM02",
    "B013X": "B013X", "B605X": "B605X", "B691Y": "B691Y",
}

FLOW_ELEMENTS = {
    "STM03": ["S1", "J10", "R16"],
    "STM04": ["R7", "S17"],
    "STM05": ["R17", "S15"],
    "STM06": ["R10"],
    "STM07": ["R3", "S23"],
    "STM08": ["R14", "S27", "Sink-1"],
}

_JVM_STARTED = False


def _ensure_jvm():
    """Start the JVM if not already running."""
    global _JVM_STARTED
    if _JVM_STARTED:
        return

    import jpype
    import glob

    jvm_path = os.path.join(JDK_17, "bin", "server", "jvm.dll")
    all_jars = glob.glob(os.path.join(HEC_LIB_DIR, "*.jar"))

    jpype.startJVM(jvm_path, classpath=all_jars,
                   *[f"-Djava.library.path={HEC_BIN_DIR}"])

    _JVM_STARTED = True


def _build_pathname(gage, variable, date_str, interval_min, tag="OBS"):
    """Build a 7-part DSS pathname."""
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
        Output DSS file path.
    gage_data : dict
        {gage_name: pd.Series} with DatetimeIndex and float values.
    start_date : str
        Start date in DDMMMYYYY format (e.g. "15Dec2016").
    interval_min : int
        Time interval in minutes.
    units : str
        Data units ("MM").
    tag : str
        Data tag ("OBS").
    """
    _ensure_jvm()

    import jpype
    HecDss = jpype.JClass("hec.heclib.dss.HecDss")
    TSC = jpype.JClass("hec.io.TimeSeriesContainer")
    HecTime = jpype.JClass("hec.heclib.util.HecTime")

    dss = HecDss.open(str(dss_path))

    for gage, series in gage_data.items():
        series = series.dropna()
        if len(series) == 0:
            continue

        pathname = _build_pathname(gage, "PRECIP-INC", start_date,
                                   interval_min, tag)

        vals = np.asarray(series.values, dtype=np.float64)
        jvals = jpype.JArray(jpype.JDouble, 1)(vals.tolist())

        ht = HecTime()
        ht.set(series.index[0].strftime("%d %B %Y, %H:%M"))

        tsc = TSC()
        tsc.fullName = pathname
        tsc.interval = jpype.JObject(interval_min, jpype.JInt)
        tsc.startHecTime = ht
        tsc.values = jvals
        tsc.numberValues = jpype.JObject(len(vals), jpype.JInt)
        tsc.units = units
        tsc.type = "PER-CUM"

        dss.put(tsc)

    dss.done()


def read_ts(dss_path, path_pattern="/*/*/*/*/*/*/"):
    """Read time series from a DSS file.

    Returns
    -------
    dict
        {pathname: pd.Series}.
    """
    _ensure_jvm()

    import jpype
    HecDss = jpype.JClass("hec.heclib.dss.HecDss")

    dss = HecDss.open(str(dss_path))
    results = {}

    for pathname in dss.getPathnameList():
        pn_str = str(pathname)
        if path_pattern != "/*/*/*/*/*/*/":
            # Simple wildcard: only include matching paths
            if not _match_simple(pn_str, path_pattern):
                continue

        ts = dss.get(pathname, True)
        if ts is None:
            continue

        # times is int[] — minutes since 1900-01-01 00:00 (DSS convention)
        BASE = pd.Timestamp("1900-01-01")
        n = ts.numberValues
        mins = list(ts.times)[:n]
        times = [BASE + pd.Timedelta(minutes=int(m)) for m in mins]
        vals_list = [ts.values[i] for i in range(n)]

        s = pd.Series(vals_list, index=pd.DatetimeIndex(times),
                       name=pn_str)
        results[pn_str] = s

    dss.done()
    return results


def _match_simple(pathname, pattern):
    """Simple wildcard match: * matches anything in one part."""
    import re
    parts_p = pathname.strip("/").split("/")
    parts_w = pattern.strip("/").split("/")
    if len(parts_p) != len(parts_w):
        return False
    for p, w in zip(parts_p, parts_w):
        if w != "*" and p != w:
            return False
    return True
