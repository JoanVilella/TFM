"""Export precipitation for a single event to HEC-HMS DSS format.

Loads the 10-min grid, extracts precipitation for the selected event window,
resamples to 15-min incremental, and writes to a DSS file that HEC-HMS can
use as precipitation forcing.

Also generates a point-gage meteorologic model (.met file) configured for
the 5 available precipitation stations.

Usage
-----
    python scripts/hec_hms/export_event.py                      # Dec 2016, default
    python scripts/hec_hms/export_event.py --start 2018-03-20   # specific event
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.hec_hms.dss_io import write_precip, PRECIP_GAGES, HEC_HMS_DIR
from scripts.preprocessing.resample import _resample_precip

GRID_PATH = REPO_ROOT / "data" / "processed" / "grid_10min.parquet"


def export_event_precip(grid, start, end, dss_path, interval_min=15):
    """Extract precipitation for an event window and write to DSS.

    Parameters
    ----------
    grid : pd.DataFrame
        The 10-min grid.
    start, end : str
        Event window (inclusive).
    dss_path : str or Path
        Output DSS file.
    interval_min : int
        Target time interval (15 min for HEC-HMS).

    Returns
    -------
    gage_data : dict
        {gage_name: pd.Series} with resampled precip data.
    """
    # Create target grid for resampling
    target_idx = pd.date_range(start, end, freq=f"{interval_min}min")

    gage_data = {}
    for code, gage_name in PRECIP_GAGES.items():
        col = f"{code}_PRECIP_mm"
        if col not in grid.columns:
            continue

        # Extract event window
        series = grid[col].loc[start:end].dropna()

        # Resample to target interval
        if len(series) > 0:
            resampled = _resample_precip(series, target_idx, max_gap="6h")
            gage_data[gage_name] = resampled
            print(f"  {gage_name} ({code}): {resampled.notna().sum():,}"
                  f" valid out of {len(resampled):,} "
                  f"({resampled.notna().mean()*100:.1f}%)")

    # Write to DSS
    start_date_dss = pd.Timestamp(start).strftime("%d%b%Y").upper()
    write_precip(str(dss_path), gage_data, start_date_dss,
                 interval_min=interval_min)

    return gage_data


def generate_meteo_model(output_path, gage_names, interval_min=15):
    """Generate a HEC-HMS meteorologic model XML with point gages.

    Uses the Gage Weights method with equal weights for all gages.
    """
    meteo_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<MetModel name="Meteo_5gages" version="4.0" xsi:noNamespaceSchemaLocation="http://www.hec.usace.army.mil/xml/schema/SHESSchema/MetModel.xsd" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <Meteorology Met Name="Meteo_5gages" Description="5-gage precipitation (STM01, STM02, B013X, B605X, B691Y)" Time Shift Method="NONE">
        <MetData Met Method="Precipitation">
            <MetData Met Method="Gage Weights">
                <MetComponent Name="GageWeights" Version="1.0">
'''

    for gage in gage_names:
        meteo_xml += f'''                    <GageWeights GageName="{gage}" Weight="1.00">
                        <DataSource Type="Dss">
                            <DssInfo DssFileName="event_precip.dss" Path="" />
                        </DataSource>
                    </GageWeights>
'''

    meteo_xml += '''                </MetComponent>
            </MetData>
        </MetData>
    </Meteorology>
</MetModel>
'''

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(meteo_xml)

    print(f"\nMeteo model written: {output_path}")
    print(f"  {len(gage_names)} gages with equal weights")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Export event precip to DSS")
    parser.add_argument("--start", default="2016-12-15",
                        help="Event start (YYYY-MM-DD)")
    parser.add_argument("--end", default="2016-12-25",
                        help="Event end (YYYY-MM-DD)")
    parser.add_argument("--output", default=None,
                        help="Output DSS file path")
    parser.add_argument("--interval", type=int, default=15,
                        help="Target time interval (minutes)")
    args = parser.parse_args()

    if args.output is None:
        args.output = str(HEC_HMS_DIR / "event_precip.dss")

    print(f"Loading grid from {GRID_PATH} ...")
    grid = pd.read_parquet(GRID_PATH)
    print(f"  Grid: {grid.shape[0]:,} rows x {grid.shape[1]} cols")

    print(f"\nExporting precipitation: {args.start} to {args.end}")
    print(f"  Interval: {args.interval} min")
    print(f"  Output: {args.output}")

    gage_data = export_event_precip(
        grid, args.start, args.end, args.output, args.interval)

    # Generate meteorologic model
    meteo_path = str(HEC_HMS_DIR / "Meteo_5gages.met")
    generate_meteo_model(meteo_path, list(PRECIP_GAGES.values()),
                         args.interval)

    print(f"\nDone. Next steps:")
    print(f"  1. Open HEC-HMS project at: {HEC_HMS_DIR}")
    print(f"  2. Create a new Meteorologic Model -> Import Meteo_5gages.met")
    print(f"  3. In Gage Weights, set each gage's DSS file to: event_precip.dss")
    print(f"  4. Set the simulation time window to: {args.start} to {args.end}")
    print(f"  5. Create a new Control Specification with {args.interval}-min interval")
    print(f"  6. Run the simulation")
