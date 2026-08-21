# ABOUTME: Limpieza y estandarización de los datos crudos de la estación hidrológica STM08 (Sa Marjal).
# ABOUTME: Genera un CSV limpio en data/clean/ y un TXT de metadatos con T0 y períodos de frecuencia de muestreo.

import os
import csv
import datetime
import openpyxl
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

INPUT_PATH = str(REPO_ROOT / "data/raw/stm/STM08_samarjal.xlsx")
OUTPUT_CSV = str(REPO_ROOT / "data/clean/STM08.csv")
OUTPUT_META = str(REPO_ROOT / "data/clean/STM08_metadata.txt")
SHEET_NAME = "data"

# Column indices (0-based) in the 'data' sheet:
#   1 = HEIGHT...2 (filtered/validated), 13 = TEMPERATURE...14 (water temp),
#   14 = DATE.UTC. Only HEIGHT_m and WATER_TEMP_C are extracted; other variables
#   will be derived later from rating curves.
COL_HEIGHT = 1
COL_TEMP   = 13
COL_DATE   = 14

# --- Load sheet ---
print("Cargando Excel (hoja data)...")
wb = openpyxl.load_workbook(INPUT_PATH, data_only=True)
ws = wb[SHEET_NAME]
rows = list(ws.iter_rows(values_only=True))
wb.close()

data = rows[1:]


# --- Clean timestamps: strip microsecond artifacts ---
def clean_ts(ts):
    """Remove microsecond artifacts introduced by the Excel export."""
    if ts is None:
        return None
    if isinstance(ts, datetime.datetime):
        return ts.replace(microsecond=0)
    if isinstance(ts, datetime.date):
        # Some rows store only a date (no time component); treat as 00:00:00
        return datetime.datetime(ts.year, ts.month, ts.day, 0, 0, 0)
    return None


# --- Coerce a cell to float, returning None for formulas or non-numeric ---
def to_float(val):
    """Return float for numeric values; None for formula strings or None."""
    if val is None:
        return None
    if isinstance(val, str):
        # Cell contains an unresolved Excel formula or empty string; treat as missing
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# --- Detect sampling frequency periods ---
valid_ts = [(i, clean_ts(r[COL_DATE])) for i, r in enumerate(data) if clean_ts(r[COL_DATE]) is not None]

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

# --- Count nulls for metadata ---
formula_height = sum(1 for r in data if isinstance(r[COL_HEIGHT], str))
none_height    = sum(1 for r in data if r[COL_HEIGHT] is None)
formula_temp   = sum(1 for r in data if isinstance(r[COL_TEMP], str))
none_temp      = sum(1 for r in data if r[COL_TEMP] is None)
date_only_ts   = sum(1 for r in data if r[COL_DATE] is not None
                     and isinstance(r[COL_DATE], datetime.date)
                     and not isinstance(r[COL_DATE], datetime.datetime))

# --- Write clean CSV ---
print("Escribiendo CSV limpio...")
os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)

with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["TIMESTAMP", "HEIGHT_m", "WATER_TEMP_C", "QUALITY", "DATA_TYPE"])
    for row in data:
        ts     = clean_ts(row[COL_DATE])
        height = to_float(row[COL_HEIGHT])
        temp   = to_float(row[COL_TEMP])

        ts_str     = ts.strftime("%Y-%m-%d %H:%M:%S") if ts is not None else ""
        height_str = "" if height is None else str(round(height, 6))
        temp_str   = "" if temp is None else str(round(temp, 4))

        writer.writerow([ts_str, height_str, temp_str, "", "observed"])

print(f"CSV guardado en: {OUTPUT_CSV}")

# --- Write metadata TXT ---
print("Escribiendo metadatos...")
with open(OUTPUT_META, "w", encoding="utf-8") as f:
    f.write("ESTACIÓN: STM08 - Sa Marjal\n")
    f.write("TIPO: Hidrológica\n")
    f.write("VARIABLES: Water level (m) — HEIGHT...2 (filtered/validated)\n")
    f.write("VARIABLES: Water temperature (°C) — TEMPERATURE...14\n")
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
    f.write("  - Solo se procesa la hoja 'data' (única hoja del fichero).\n")
    f.write("  - Cargado con data_only=True: se recuperan los valores cacheados por Excel en el último guardado.\n")
    f.write("  - Microsegundos artificiales en TIMESTAMP eliminados (artefacto del Excel).\n")
    if date_only_ts:
        f.write(f"  - {date_only_ts} filas con TIMESTAMP de tipo date (sin hora) convertidas a datetime a las 00:00:00.\n")
    f.write("  - Valores nulos (None) exportados como celdas vacías.\n")
    f.write(f"  - HEIGHT_m (HEIGHT...2): {formula_height} celdas con caché vacía + {none_height} celdas None → exportadas como vacías.\n")
    f.write(f"  - WATER_TEMP_C (TEMPERATURE...14): {formula_temp} celdas con caché vacía + {none_temp} celdas None → exportadas como vacías.\n")
    f.write("  - Solo se extraen HEIGHT_m y WATER_TEMP_C. DISCHARGE, VOLUME y LOAD se derivarán posteriormente con curvas de aforo.\n")
    f.write("  - Frecuencia mixta conservada (no se ha realizado resampling).\n")
    f.write(f"  - Total de filas exportadas: {len(data)}\n")

print(f"Metadatos guardados en: {OUTPUT_META}")
print("Listo.")
