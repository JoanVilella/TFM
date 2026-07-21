# ABOUTME: Limpieza y estandarización de los datos crudos de la estación meteorológica STM01 (Coll des Telègraf).
# ABOUTME: Genera un CSV limpio en data/clean/ y un TXT de metadatos con T0 y períodos de frecuencia de muestreo.

import openpyxl
import csv
import os
import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

INPUT_PATH = str(REPO_ROOT / "data/raw/stm/STM01_rain_colltelegraf.xlsx")
OUTPUT_CSV = str(REPO_ROOT / "data/clean/STM01.csv")
OUTPUT_META = str(REPO_ROOT / "data/clean/STM01_metadata.txt")
SHEET_NAME = "Sheet1"

# --- Load raw data ---
print("Cargando Excel...")
wb = openpyxl.load_workbook(INPUT_PATH, read_only=True)
ws = wb[SHEET_NAME]
rows = list(ws.iter_rows(values_only=True))
wb.close()

header = rows[0]  # ('TIMESTAMP', 'Precip', 'Temp')
data = rows[1:]

# --- Clean timestamps: strip microsecond artifacts ---
def clean_ts(ts):
    """Remove microsecond artifacts introduced by the Excel export."""
    if ts is None:
        return None
    return ts.replace(microsecond=0)

# --- Detect sampling frequency periods ---
# Collect valid (non-None) timestamps to find period boundaries
valid_ts = [(i, clean_ts(r[0])) for i, r in enumerate(data) if r[0] is not None]

first_ts = valid_ts[0][1]
last_ts = valid_ts[-1][1]

period_15_start = None
period_15_end = None
period_10_start = None
period_10_end = None

for j in range(len(valid_ts) - 1):
    _, t1 = valid_ts[j]
    _, t2 = valid_ts[j + 1]
    diff_min = int(round((t2 - t1).total_seconds() / 60))
    if diff_min == 15:
        if period_15_start is None:
            period_15_start = t1
        period_15_end = t2
    elif diff_min == 10:
        if period_10_start is None:
            period_10_start = t1
        period_10_end = t2

# --- Write clean CSV ---
print("Escribiendo CSV limpio...")
os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)

with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["TIMESTAMP", "PRECIP_mm", "TEMP_C"])
    for row in data:
        ts = clean_ts(row[0])
        precip = row[1]
        temp = row[2]
        # Format timestamp as ISO 8601
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if ts is not None else ""
        # Keep NaN as empty string for traceability
        precip_str = "" if precip is None else str(precip)
        temp_str = "" if temp is None else str(round(temp, 4))
        writer.writerow([ts_str, precip_str, temp_str])

print(f"CSV guardado en: {OUTPUT_CSV}")

# --- Write metadata TXT ---
print("Escribiendo metadatos...")
with open(OUTPUT_META, "w", encoding="utf-8") as f:
    f.write("ESTACIÓN: STM01 - Coll des Telègraf\n")
    f.write("TIPO: Meteorológica\n")
    f.write("VARIABLES: Precipitación (mm), Temperatura del aire (ºC)\n")
    f.write("\n")
    f.write(f"T0 (primer registro):    {first_ts}\n")
    f.write(f"T_end (último registro): {last_ts}\n")
    f.write("\n")
    f.write("PERÍODOS DE FRECUENCIA DE MUESTREO:\n")
    if period_15_start and period_15_end:
        f.write(f"  15 min: {period_15_start}  -->  {period_15_end}\n")
    else:
        f.write("  15 min: no detectado\n")
    if period_10_start and period_10_end:
        f.write(f"  10 min: {period_10_start}  -->  {period_10_end}\n")
    else:
        f.write("  10 min: no detectado\n")
    f.write("\n")
    f.write("NOTAS DE LIMPIEZA:\n")
    f.write("  - Microsegundos artificiales en TIMESTAMP eliminados (artefacto del Excel).\n")
    f.write("  - Valores nulos (None) exportados como celdas vacías.\n")
    f.write("  - Columnas renombradas: Precip -> PRECIP_mm, Temp -> TEMP_C.\n")
    f.write("  - Frecuencia mixta conservada (no se ha realizado resampling).\n")
    f.write(f"  - Total de filas exportadas: {len(data)}\n")

print(f"Metadatos guardados en: {OUTPUT_META}")
print("Listo.")
