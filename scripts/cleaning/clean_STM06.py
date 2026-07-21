# ABOUTME: Limpieza y estandarización de los datos crudos de la estación hidrológica STM06 (Sant Miquel).
# ABOUTME: Genera un CSV limpio en data/clean/ y un TXT de metadatos con T0 y períodos de frecuencia de muestreo.

import openpyxl
import csv
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

INPUT_PATH = str(REPO_ROOT / "data/raw/stm/STM06_santmiquel.xlsx")
OUTPUT_CSV = str(REPO_ROOT / "data/clean/STM06.csv")
OUTPUT_META = str(REPO_ROOT / "data/clean/STM06_metadata.txt")

# --- Load first sheet only ---
print("Cargando Excel (primera hoja)...")
wb = openpyxl.load_workbook(INPUT_PATH, data_only=True)
ws = wb.worksheets[0]
rows = list(ws.iter_rows(values_only=True))
wb.close()

# Header: index 0 = 'HEIGHT...1', 1 = 'HEIGHT...2', 2 = 'DISCHARGE',
#         3 = 'VOLUME', 11 = 'LOAD', 14 = 'DATE UTC'
data = rows[1:]


# --- Clean timestamps: strip microsecond artifacts ---
def clean_ts(ts):
    """Remove microsecond artifacts introduced by the Excel export."""
    if ts is None:
        return None
    return ts.replace(microsecond=0)


# --- Coerce a cell to float, returning None for formulas or non-numeric ---
def to_float(val):
    """Return float for numeric values; None for formula strings or None."""
    if val is None:
        return None
    if isinstance(val, str):
        # Cell contains an unresolved Excel formula; treat as missing
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# --- Detect sampling frequency periods ---
valid_ts = [(i, clean_ts(r[14])) for i, r in enumerate(data) if r[14] is not None]

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

# --- Count formula strings for metadata ---
formula_height    = sum(1 for r in data if isinstance(r[1], str))
formula_discharge = sum(1 for r in data if isinstance(r[2], str))
formula_volume    = sum(1 for r in data if isinstance(r[3], str))
formula_load      = sum(1 for r in data if isinstance(r[11], str))
none_height       = sum(1 for r in data if r[1] is None)
none_load         = sum(1 for r in data if r[11] is None)

# --- Write clean CSV ---
print("Escribiendo CSV limpio...")
os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)

with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["TIMESTAMP", "HEIGHT_m", "DISCHARGE_m3s", "VOLUME_m3", "LOAD_kg"])
    for row in data:
        ts        = clean_ts(row[14])
        height    = to_float(row[1])
        discharge = to_float(row[2])
        volume    = to_float(row[3])
        load      = to_float(row[11])

        ts_str        = ts.strftime("%Y-%m-%d %H:%M:%S") if ts is not None else ""
        height_str    = "" if height is None else str(round(height, 6))
        discharge_str = "" if discharge is None else str(round(discharge, 6))
        volume_str    = "" if volume is None else str(round(volume, 6))
        load_str      = "" if load is None else str(round(load, 6))

        writer.writerow([ts_str, height_str, discharge_str, volume_str, load_str])

print(f"CSV guardado en: {OUTPUT_CSV}")

# --- Write metadata TXT ---
print("Escribiendo metadatos...")
with open(OUTPUT_META, "w", encoding="utf-8") as f:
    f.write("ESTACIÓN: STM06 - Sant Miquel\n")
    f.write("TIPO: Hidrológica\n")
    f.write("VARIABLES: Water level (m), Discharge (m³/s), Volume (m³), Load (kg)\n")
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
    f.write("  - Solo se procesa la primera hoja ('Sheet 1'); el resto son eventos individuales.\n")
    f.write("  - Microsegundos artificiales en TIMESTAMP eliminados (artefacto del Excel).\n")
    f.write("  - Valores nulos (None) exportados como celdas vacías.\n")
    f.write(f"  - HEIGHT_m: {formula_height} celdas con caché vacía + {none_height} celdas None → exportadas como vacías.\n")
    f.write(f"  - DISCHARGE: {formula_discharge} celdas con caché de fórmula vacía (sin valor guardado) → exportadas como vacías.\n")
    f.write(f"  - VOLUME: {formula_volume} celdas con caché de fórmula vacía (sin valor guardado) → exportadas como vacías.\n")
    f.write(f"  - LOAD: {formula_load} celdas con caché de fórmula vacía + {none_load} celdas None → exportadas como vacías.\n")
    f.write("  - Cargado con data_only=True: se recuperan los valores cacheados por Excel en el último guardado.\n")
    f.write("  - Columnas renombradas: HEIGHT...2 → HEIGHT_m, DISCHARGE → DISCHARGE_m3s, VOLUME → VOLUME_m3, LOAD → LOAD_kg.\n")
    f.write("  - Frecuencia mixta conservada (no se ha realizado resampling).\n")
    f.write(f"  - Total de filas exportadas: {len(data)}\n")

print(f"Metadatos guardados en: {OUTPUT_META}")
print("Listo.")
