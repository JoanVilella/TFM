# ABOUTME: Limpieza y estandarización de los datos crudos de la estación meteorológica STM02 (Míner Gran).
# ABOUTME: Genera un CSV limpio en data/clean/ y un TXT de metadatos con T0 y períodos de frecuencia de muestreo.

import openpyxl
import csv
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

INPUT_PATH = str(REPO_ROOT / "data/raw/stm/STM02_rain_minergran.xlsx")
OUTPUT_CSV = str(REPO_ROOT / "data/clean/STM02.csv")
OUTPUT_META = str(REPO_ROOT / "data/clean/STM02_metadata.txt")
SHEET_NAME = "miner_gran_15min"

# --- Load raw data ---
print("Cargando Excel...")
wb = openpyxl.load_workbook(INPUT_PATH, read_only=True)
ws = wb[SHEET_NAME]
rows = list(ws.iter_rows(values_only=True))
wb.close()

# Header: ('DATE.UTC', <excel_serial>, 'Precip', 'Temp', None, None)
# Keep only cols 0 (TIMESTAMP), 2 (Precip), 3 (Temp); drop serial, empty cols
data = rows[1:]

# --- Recover tipping-bucket formulas -------------------------------------------------
_TIP_BUCKET_RE = re.compile(r"^=(?:0\.2\*(\d+)|(\d+)\*0\.2)$")

def recover_precip(val):
    """Evaluate raw Excel tipping-bucket formulas (=0.2*N or =N*0.2).
    Returns the numeric value (0.2*N) as a float, or the original value if it's
    a plain number, or None if it's an untreatable string/None."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        if val.upper() == "NAN":
            return None
        m = _TIP_BUCKET_RE.match(val.strip())
        if m:
            n = int(m.group(1) or m.group(2))
            return round(0.2 * n, 4)
        # Other formula strings (not tipping-bucket) → null
        if val.startswith("="):
            return None
        try:
            return float(val)
        except ValueError:
            return None
    return None

# Run formula-pattern scan on the whole column before writing (for metadata)
_tip_count = 0
for row in data:
    precip_raw = row[2]
    if isinstance(precip_raw, str) and _TIP_BUCKET_RE.match(precip_raw.strip()):
        _tip_count += 1

def clean_ts(ts):
    """Remove microsecond artifacts introduced by the Excel export."""
    if ts is None:
        return None
    return ts.replace(microsecond=0)

# --- Detect sampling frequency periods ---
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
        precip_val = recover_precip(row[2])
        temp = row[3]
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if ts is not None else ""
        precip_str = "" if precip_val is None else str(precip_val)
        # Treat None, 'NAN', and Excel formula strings as empty (null)
        if temp is None or isinstance(temp, str):
            temp_str = ""
        else:
            temp_str = str(round(temp, 4))
        writer.writerow([ts_str, precip_str, temp_str])

print(f"CSV guardado en: {OUTPUT_CSV}")

# --- Write metadata TXT ---
print("Escribiendo metadatos...")
with open(OUTPUT_META, "w", encoding="utf-8") as f:
    f.write("ESTACIÓN: STM02 - Míner Gran\n")
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
    f.write("  - Columna de serial Excel (DATE.UTC duplicado numérico) eliminada.\n")
    f.write("  - 1 celda de Temp contenía una fórmula Excel (=AVERAGE); tratada como nulo.\n")
    f.write(f"  - {_tip_count} celdas de Precip contenían fórmulas Excel de tipping-bucket (=0.2*N); evaluadas y recuperadas.\n")
    f.write("  - 22261 celdas de Temp contenían el string 'NAN'; tratadas como nulo.\n")
    f.write("  - Dos columnas vacías/basura al final eliminadas.\n")
    f.write("  - Microsegundos artificiales en TIMESTAMP eliminados (artefacto del Excel).\n")
    f.write("  - Valores nulos (None) exportados como celdas vacías.\n")
    f.write("  - Columnas renombradas: Precip -> PRECIP_mm, Temp -> TEMP_C.\n")
    f.write("  - Frecuencia mixta conservada (no se ha realizado resampling).\n")
    f.write(f"  - Total de filas exportadas: {len(data)}\n")

print(f"Metadatos guardados en: {OUTPUT_META}")
print("Listo.")
