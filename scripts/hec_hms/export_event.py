"""Export precipitation for a single event to HEC-HMS DSS format.

Loads the 10-min grid and writes precipitation directly at 10-min resolution
(no resampling needed).  Generates a matching 10-min control specification
and updates the 5-gage meteorologic model.

Usage
-----
    python scripts/hec_hms/export_event.py                      # Dec 2016
    python scripts/hec_hms/export_event.py --start 2018-03-20   # specific event
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.hec_hms.dss_io import write_precip, PRECIP_GAGES, HEC_HMS_DIR

GRID_PATH = REPO_ROOT / "data" / "processed" / "grid_10min.parquet"


def export_event_precip(grid, start, end, dss_path):
    """Extract 10-min precipitation for an event window and write to DSS.

    No resampling — the grid is already at 10-min resolution.
    """
    gage_data = {}
    for code, gage_name in PRECIP_GAGES.items():
        col = f"{code}_PRECIP_mm"
        if col not in grid.columns:
            continue

        series = grid[col].loc[start:end].dropna()
        if len(series) > 0:
            gage_data[gage_name] = series
            print(f"  {gage_name} ({code}): {series.notna().sum():,}"
                  f" valid out of {len(series):,}"
                  f" ({series.notna().mean()*100:.1f}%)")

    start_date_dss = pd.Timestamp(start).strftime("%d%b%Y").upper()
    write_precip(str(dss_path), gage_data, start_date_dss, interval_min=10)

    return gage_data


def generate_control_spec(output_path, start, end, interval_min=10):
    """Generate a HEC-HMS control specification XML."""
    start_ts = pd.Timestamp(start).strftime("%d %B %Y, %H:%M")
    end_ts = pd.Timestamp(end).strftime("%d %B %Y, %H:%M")

    control_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<SimulationControl name="Control_10min" version="4.0" xsi:noNamespaceSchemaLocation="http://www.hec.usace.army.mil/xml/schema/SHESSchema/SimulationControl.xsd" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <SimulationControl Controls Name="Control_10min" Description="{interval_min}-min interval for event {start} to {end}" Time Interval="{interval_min}">
        <SimulationControl Computer Starting Period="1" Ending Period="1">
            <SimulationControl TimeWindow Name="Event_{start}_{end}" Version="1.0">
                <TimeWindow Start Time="{start_ts}" End Time="{end_ts}"/>
            </SimulationControl>
        </SimulationControl Computer>
    </SimulationControl Controls>
</SimulationControl>
'''
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(control_xml)
    print(f"\nControl spec written: {output_path}")


def generate_meteo_model(output_path, gage_names):
    """Generate HEC-HMS meteorologic model XML with 5 point gages."""
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
    print(f"Meteo model written: {output_path}")
    print(f"  {len(gage_names)} gages with equal weights")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Export event precip to DSS")
    parser.add_argument("--start", default="2016-12-16",
                        help="Event start (YYYY-MM-DD)")
    parser.add_argument("--end", default="2016-12-26",
                        help="Event end (YYYY-MM-DD)")
    parser.add_argument("--output", default=None,
                        help="Output DSS file path")
    args = parser.parse_args()

    if args.output is None:
        args.output = str(HEC_HMS_DIR / "event_precip.dss")

    print(f"Loading grid from {GRID_PATH} ...")
    grid = pd.read_parquet(GRID_PATH)
    print(f"  Grid: {grid.shape[0]:,} rows x {grid.shape[1]} cols")

    print(f"\nExporting precipitation: {args.start} to {args.end}")
    print(f"  Interval: 10 min (direct from grid)")
    print(f"  Output: {args.output}")

    gage_data = export_event_precip(grid, args.start, args.end, args.output)

    # Generate control spec + meteo model
    generate_control_spec(
        str(HEC_HMS_DIR / "Control_10min.control"),
        args.start, args.end)

    generate_meteo_model(
        str(HEC_HMS_DIR / "Meteo_5gages.met"),
        list(PRECIP_GAGES.values()))

    print(f"\nDone. Next steps in HEC-HMS GUI:")
    print(f"  1. Open project: {HEC_HMS_DIR}")
    print(f"  2. Create Meteorologic Model -> Import Meteo_5gages.met")
    print(f"     Point each gage DSS to: event_precip.dss")
    print(f"  3. Create Control Spec -> Import Control_10min.control")
    print(f"  4. Create Run: Basin=STM.basin, Meteo=Meteo_5gages, Control=Control_10min")
    print(f"  5. Run simulation -> Save output to event_output.dss")
    print(f"  6. Back in Python: read_ts('event_output.dss') to get results")
