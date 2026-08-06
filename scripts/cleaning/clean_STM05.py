# ABOUTME: Limpieza y estandarización de los datos crudos de la estación hidrológica STM05 (Monnàber).
# ABOUTME: Genera un CSV limpio en data/clean/ y un TXT de metadatos con T0 y períodos de frecuencia de muestreo.

import zipfile
import re
import io
import os
import csv
import datetime
import openpyxl
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

INPUT_PATH = str(REPO_ROOT / "data/raw/stm/STM05_monnaber.xlsx")
OUTPUT_CSV = str(REPO_ROOT / "data/clean/STM05.csv")
OUTPUT_META = str(REPO_ROOT / "data/clean/STM05_metadata.txt")
SHEET_NAME = "STM05"

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


# --- Load sheet STM05 ---
print("Cargando Excel (hoja STM05)...")
patched = _patch_xlsx(INPUT_PATH)
wb = openpyxl.load_workbook(patched, data_only=True)
ws = wb[SHEET_NAME]
rows = list(ws.iter_rows(values_only=True))
wb.close()

# Header: index 1 = 'HEIGHT...2' (filtered/validated), 14 = 'DATE.UTC'
# Only HEIGHT_m is extracted; other variables will be derived later from rating curves.
data = rows[1:]


# --- Clean timestamps: strip microsecond artifacts ---
def clean_ts(ts):
    """Remove microsecond artifacts introduced by the Excel export."""
    if ts is None:
        return None
    if isinstance(ts, datetime.datetime):
        return ts.replace(microsecond=0)
    if isinstance(ts, datetime.date):
        return datetime.datetime(ts.year, ts.month, ts.day, 0, 0, 0)
    return None


# --- Coerce a cell to float, returning None for formulas or non-numeric ---
def to_float(val):
    """Return float for numeric values; None for formula strings or None."""
    if val is None:
        return None
    if isinstance(val, str):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# --- Detect sampling frequency periods ---
valid_ts = [(i, clean_ts(r[14])) for i, r in enumerate(data) if clean_ts(r[14]) is not None]

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
formula_height = sum(1 for r in data if isinstance(r[1], str))
none_height    = sum(1 for r in data if r[1] is None)
date_only_ts   = sum(1 for r in data if r[14] is not None and isinstance(r[14], datetime.date)
                     and not isinstance(r[14], datetime.datetime))

# --- Write clean CSV ---
print("Escribiendo CSV limpio...")
os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)

with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["TIMESTAMP", "HEIGHT_m"])
    for row in data:
        ts     = clean_ts(row[14])
        height = to_float(row[1])

        ts_str     = ts.strftime("%Y-%m-%d %H:%M:%S") if ts is not None else ""
        height_str = "" if height is None else str(round(height, 6))

        writer.writerow([ts_str, height_str])

print(f"CSV guardado en: {OUTPUT_CSV}")

# --- Write metadata TXT ---
print("Escribiendo metadatos...")
with open(OUTPUT_META, "w", encoding="utf-8") as f:
    f.write("ESTACIÓN: STM05 - Monnàber\n")
    f.write("TIPO: Hidrológica\n")
    f.write("VARIABLES: Water level (m) — HEIGHT...2 (filtered/validated)\n")
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
    f.write("  - Solo se procesa la hoja 'STM05'; las otras hojas son gráficos o auxiliares.\n")
    f.write("  - El fichero usa namespaces strict OOXML (purl.oclc.org); se reescriben a\n")
    f.write("    namespaces transitionales antes de cargar con openpyxl (en memoria, sin modificar el original).\n")
    f.write("  - Cargado con data_only=True: se recuperan los valores cacheados por Excel en el último guardado.\n")
    f.write("  - Microsegundos artificiales en TIMESTAMP eliminados (artefacto del Excel).\n")
    f.write(f"  - {date_only_ts} filas con TIMESTAMP de tipo date (sin hora) convertidas a datetime a las 00:00:00.\n")
    f.write("  - Valores nulos (None) exportados como celdas vacías.\n")
    f.write(f"  - HEIGHT_m (HEIGHT...2): {formula_height} celdas con caché vacía + {none_height} celdas None → exportadas como vacías.\n")
    f.write("  - Solo se extrae HEIGHT_m (nivel validado). DISCHARGE, VOLUME y LOAD se derivarán posteriormente con curvas de aforo.\n")
    f.write("  - Frecuencia mixta conservada (no se ha realizado resampling).\n")
    f.write(f"  - Total de filas exportadas: {len(data)}\n")

print(f"Metadatos guardados en: {OUTPUT_META}")
print("Listo.")
