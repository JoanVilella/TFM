# ABOUTME: Limpieza y estandarización de los datos crudos de la estación hidrológica STM03 (Es Fangar).
# ABOUTME: Genera un CSV limpio en data/clean/ y un TXT de metadatos con T0 y períodos de frecuencia de muestreo.

import zipfile
import re
import io
import os
import csv
import datetime
import openpyxl

INPUT_PATH = r"data\raw\excel\STM03_esfangar.xlsx"
OUTPUT_CSV = r"data\clean\STM03.csv"
OUTPUT_META = r"data\clean\STM03_metadata.txt"
SHEET_NAME = "STM03"

# Namespace mapping: the file uses strict OOXML namespaces (purl.oclc.org)
# which openpyxl does not support. We rewrite them to the transitional
# namespaces before parsing, and also strip any broken externalReferences node.
_STRICT_NS  = "http://purl.oclc.org/ooxml/spreadsheetml/main"
_TRANSIT_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_STRICT_REL  = "http://purl.oclc.org/ooxml/officeDocument/relationships"
_TRANSIT_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _patch_xlsx(src_path):
    """Return a BytesIO with strict OOXML namespaces replaced by transitional ones."""
    buf = io.BytesIO()
    with zipfile.ZipFile(src_path, "r") as zin:
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename.endswith(".xml") or item.filename.endswith(".rels"):
                    text = data.decode("utf-8")
                    text = text.replace(_STRICT_NS, _TRANSIT_NS)
                    text = text.replace(_STRICT_REL, _TRANSIT_REL)
                    # Remove externalReferences node that triggers an openpyxl bug
                    text = re.sub(
                        r"<externalReferences>.*?</externalReferences>",
                        "",
                        text,
                        flags=re.DOTALL,
                    )
                    data = text.encode("utf-8")
                zout.writestr(item, data)
    buf.seek(0)
    return buf


# Column indices (0-based) in the 'STM03' sheet:
#   2 = DISCHARGE, 3 = VOLUME, 12 = LOAD, 16 = DATE.UTC
# Note: an extra SSC.Calibrated High column at index 11 shifts LOAD to index 12
# and pushes DATE.UTC to index 16 compared to the standard layout.
COL_DISCHARGE = 2
COL_VOLUME    = 3
COL_LOAD      = 12
COL_DATE      = 16

# --- Load sheet STM03 ---
print("Cargando Excel (hoja STM03)...")
patched = _patch_xlsx(INPUT_PATH)
wb = openpyxl.load_workbook(patched, data_only=True)
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
formula_discharge = sum(1 for r in data if isinstance(r[COL_DISCHARGE], str))
formula_volume    = sum(1 for r in data if isinstance(r[COL_VOLUME], str))
formula_load      = sum(1 for r in data if isinstance(r[COL_LOAD], str))
none_discharge    = sum(1 for r in data if r[COL_DISCHARGE] is None)
none_volume       = sum(1 for r in data if r[COL_VOLUME] is None)
none_load         = sum(1 for r in data if r[COL_LOAD] is None)
date_only_ts      = sum(1 for r in data if r[COL_DATE] is not None
                        and isinstance(r[COL_DATE], datetime.date)
                        and not isinstance(r[COL_DATE], datetime.datetime))

# --- Write clean CSV ---
print("Escribiendo CSV limpio...")
os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)

with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["TIMESTAMP", "DISCHARGE_m3s", "VOLUME_m3", "LOAD_kg"])
    for row in data:
        ts        = clean_ts(row[COL_DATE])
        discharge = to_float(row[COL_DISCHARGE])
        volume    = to_float(row[COL_VOLUME])
        load      = to_float(row[COL_LOAD])

        ts_str        = ts.strftime("%Y-%m-%d %H:%M:%S") if ts is not None else ""
        discharge_str = "" if discharge is None else str(round(discharge, 6))
        volume_str    = "" if volume is None else str(round(volume, 6))
        load_str      = "" if load is None else str(round(load, 6))

        writer.writerow([ts_str, discharge_str, volume_str, load_str])

print(f"CSV guardado en: {OUTPUT_CSV}")

# --- Write metadata TXT ---
print("Escribiendo metadatos...")
with open(OUTPUT_META, "w", encoding="utf-8") as f:
    f.write("ESTACIÓN: STM03 - Es Fangar\n")
    f.write("TIPO: Hidrológica\n")
    f.write("VARIABLES: Discharge (m³/s), Volume (m³), Load (kg)\n")
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
    f.write("  - Solo se procesa la hoja 'STM03'; las otras hojas son auxiliares.\n")
    f.write("  - El fichero usa namespaces strict OOXML (purl.oclc.org); se reescriben a\n")
    f.write("    namespaces transitionales antes de cargar con openpyxl (en memoria, sin modificar el original).\n")
    f.write("  - Cargado con data_only=True: se recuperan los valores cacheados por Excel en el último guardado.\n")
    f.write("  - En esta hoja hay una columna extra SSC.Calibrated High (índice 11); LOAD ocupa el índice 12\n")
    f.write("    y DATE.UTC el índice 16, desplazados respecto al layout estándar de otras estaciones.\n")
    f.write("  - Microsegundos artificiales en TIMESTAMP eliminados (artefacto del Excel).\n")
    if date_only_ts:
        f.write(f"  - {date_only_ts} filas con TIMESTAMP de tipo date (sin hora) convertidas a datetime a las 00:00:00.\n")
    f.write("  - Valores nulos (None) exportados como celdas vacías.\n")
    f.write(f"  - DISCHARGE: {formula_discharge} celdas con caché vacía + {none_discharge} celdas None → exportadas como vacías.\n")
    f.write(f"  - VOLUME: {formula_volume} celdas con caché vacía + {none_volume} celdas None → exportadas como vacías.\n")
    f.write(f"  - LOAD: {formula_load} celdas con caché vacía + {none_load} celdas None → exportadas como vacías.\n")
    f.write("  - Columnas renombradas: DISCHARGE → DISCHARGE_m3s, VOLUME → VOLUME_m3, LOAD → LOAD_kg.\n")
    f.write("  - Frecuencia mixta conservada (no se ha realizado resampling).\n")
    f.write(f"  - Total de filas exportadas: {len(data)}\n")

print(f"Metadatos guardados en: {OUTPUT_META}")
print("Listo.")
