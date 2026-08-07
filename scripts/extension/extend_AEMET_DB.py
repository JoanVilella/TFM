# ABOUTME: Extiende los CSV limpios de B013X, B605X y B691Y con datos nuevos
# ABOUTME: extraídos de la base de datos de producción (2023-01-01 → actualidad), integrándolos cronológicamente.

import csv
import os
import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

RAW_DIR   = str(REPO_ROOT / "data/raw/db_exports/prod_data")
CLEAN_DIR = str(REPO_ROOT / "data/clean")

STATIONS = {
    "B013X": "Lluc",
    "B605X": "Muro-S'albufera",
    "B691Y": "Sa Pobla-Sa Canova",
}


def parse_db_timestamp(ts_str):
    """Parse a DB timestamp string like '2023-01-01 00:00:00+00' into a naive UTC datetime."""
    ts_str = ts_str.strip()
    for suffix in ("+00:00", "+00"):
        if ts_str.endswith(suffix):
            ts_str = ts_str[: -len(suffix)]
            break
    return datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")


def load_existing_clean(code):
    """Load existing clean CSV into (records dict, quality dict)."""
    path = os.path.join(CLEAN_DIR, f"{code}.csv")
    records = {}
    quality_map = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if not row:
                continue
            ts = datetime.datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            records[ts] = row[1]
            quality_map[ts] = row[2] if len(row) > 2 else ""
    return records, quality_map


def load_new_db_rows(code):
    """Load Rain60m rows for a station from prod_data CSV.

    Returns a dict {datetime: precip_str}, a dict {datetime: quality_str},
    and a count of non-zero quality records. Values are already in mm.
    """
    path = os.path.join(RAW_DIR, f"{code}.csv")
    records = {}
    quality_map = {}
    non_zero_quality = 0
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # skip header: id,code_id,station_name,x_utm,y_utm,variable,quality,timestamp,value
        for row in reader:
            if not row or len(row) < 9:
                continue
            variable = row[5].strip()
            if variable != "Rain60m":
                continue
            quality = row[6].strip()
            if quality != "0":
                non_zero_quality += 1
            ts = parse_db_timestamp(row[7])
            raw_val = row[8].strip()
            if raw_val in ("", "-", "None"):
                val_str = ""
            else:
                try:
                    val_str = str(round(float(raw_val), 4))
                except ValueError:
                    val_str = ""
            records[ts] = val_str
            quality_map[ts] = quality
    return records, quality_map, non_zero_quality


def write_clean_csv(code, merged, quality_merged):
    """Write merged records to the clean CSV, sorted chronologically."""
    path = os.path.join(CLEAN_DIR, f"{code}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["TIMESTAMP", "PRECIP_mm", "QUALITY", "DATA_TYPE"])
        for ts in sorted(merged.keys()):
            q = quality_merged.get(ts, "")
            data_type = "observed" if q != "" else "observed"
            writer.writerow([ts.strftime("%Y-%m-%d %H:%M:%S"), merged[ts], q, data_type])
    return path


def update_metadata(code, name, merged, new_count, non_zero_quality, overlap_count):
    """Rewrite the metadata TXT with updated T_end and total rows."""
    timestamps = sorted(merged.keys())
    first_ts = timestamps[0]
    last_ts  = timestamps[-1]
    total_rows = len(timestamps)

    path = os.path.join(CLEAN_DIR, f"{code}_metadata.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"ESTACIÓN: {code} - {name}\n")
        f.write("TIPO: Meteorológica (precipitación horaria)\n")
        f.write("VARIABLES: Precipitación (mm)\n")
        f.write("\n")
        f.write(f"T0 (primer registro):    {first_ts}\n")
        f.write(f"T_end (último registro): {last_ts}\n")
        f.write("\n")
        f.write("PERÍODOS DE FRECUENCIA DE MUESTREO:\n")
        f.write(f"  60 min: {first_ts}  -->  {last_ts}\n")
        f.write("\n")
        f.write("NOTAS DE LIMPIEZA:\n")
        f.write("  - Fuente original: UIB-Estrany / RiscBal (formato phor de AEMET/SMN), hasta 2023-01-01.\n")
        f.write("  - Extensión: base de datos de producción (prod_data, Rain60m), desde 2023-01-01.\n")
        f.write("  - Valores originales UIB-Estrany en décimas de mm → convertidos a mm (÷10).\n")
        f.write("  - Valores de prod_data ya en mm (sin conversión).\n")
        f.write("  - Timestamps de prod_data en UTC (sufijo +00 eliminado); serie completa en UTC.\n")
        f.write(f"  - Registros incorporados de prod_data: {new_count}.\n")
        f.write(f"  - Solapamiento en el punto de unión (2023-01-01 00:00:00): {overlap_count} registro(s) — se conserva el valor original.\n")
        if non_zero_quality:
            f.write(f"  - AVISO: {non_zero_quality} registro(s) con quality != 0 incluidos (filtro de calidad no aplicado).\n")
        f.write("  - Valores nulos exportados como celdas vacías.\n")
        f.write(f"  - Total de filas exportadas: {total_rows}\n")
    return path


def process_station(code, name):
    print(f"\nProcesando {code} - {name}...")

    existing, existing_quality = load_existing_clean(code)
    print(f"  Registros existentes: {len(existing)}")

    new_records, new_quality, non_zero_quality = load_new_db_rows(code)
    print(f"  Registros nuevos (prod_data): {len(new_records)}")
    if non_zero_quality:
        print(f"  AVISO: {non_zero_quality} registros con quality != 0")

    overlap = set(existing.keys()) & set(new_records.keys())
    print(f"  Solapamiento en la unión: {len(overlap)} timestamp(s)")

    merged = {**new_records, **existing}
    quality_merged = {**new_quality, **existing_quality}

    csv_path  = write_clean_csv(code, merged, quality_merged)
    meta_path = update_metadata(code, name, merged, len(new_records), non_zero_quality, len(overlap))

    print(f"  Total filas en CSV resultante: {len(merged)}")
    print(f"  CSV actualizado: {csv_path}")
    print(f"  Metadatos actualizados: {meta_path}")


if __name__ == "__main__":
    for code, name in STATIONS.items():
        process_station(code, name)
    print("\nListo.")
