# ABOUTME: Extiende los CSV limpios de STM03–STM08 con datos de nivel de agua y
# ABOUTME: temperatura del agua nuevos desde data/raw/db_exports/prod_data/ y
# ABOUTME: data/raw/watertemp_extended/, integrándolos cronológicamente hasta la fecha actual.

import csv
import os
import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

RAW_DIR   = str(REPO_ROOT / "data/raw/db_exports/prod_data")
CLEAN_DIR = str(REPO_ROOT / "data/clean")
WATERTEMP_DIR = str(REPO_ROOT / "data/raw/watertemp_extended")

STATIONS = {
    "STM03": "Es Fangar",
    "STM04": "Gabelli",
    "STM05": "Monnàber",
    "STM06": "Sant Miquel",
    "STM07": "Búger",
    "STM08": "Sa Marjal",
}


def parse_db_timestamp(ts_str):
    """Parse a DB timestamp like '2026-07-15 00:00:00+00' into a naive UTC datetime."""
    ts_str = ts_str.strip()
    for suffix in ("+00:00", "+00"):
        if ts_str.endswith(suffix):
            ts_str = ts_str[: -len(suffix)]
            break
    return datetime.datetime.strptime(ts_str.strip(), "%Y-%m-%d %H:%M:%S")


def get_last_clean_ts_and_count(code):
    """Iterate the clean CSV to find the last timestamp and the total row count."""
    path = os.path.join(CLEAN_DIR, f"{code}.csv")
    last_ts = None
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if row and row[0]:
                count += 1
                last_ts = datetime.datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
    return last_ts, count


def load_new_waterlevel_rows(code):
    """Load WaterLevel rows for a station from the prod_data CSV.

    DB WaterLevel values are in CENTIMETRES and are converted to metres
    (divided by 100) here.  Rows with quality == "2" (wrong data) are
    dropped; rows with quality == "1" (suspicious) are kept and counted.

    Returns a dict {datetime: height_str}, a dict {datetime: quality_str},
    a count of q=1 records kept, and a count of q=2 records dropped.
    """
    path = os.path.join(RAW_DIR, f"{code.lower()}.csv")
    records = {}
    quality_map = {}
    n_q1 = 0
    n_q2_dropped = 0
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # skip header: id,code_id,station_name,x_utm,y_utm,variable,quality,timestamp,value
        for row in reader:
            if not row or len(row) < 9:
                continue
            variable = row[5].strip()
            if variable != "WaterLevel":
                continue
            quality = row[6].strip()
            if quality == "2":
                n_q2_dropped += 1
                continue
            if quality == "1":
                n_q1 += 1
            ts = parse_db_timestamp(row[7])
            raw_val = row[8].strip()
            if raw_val in ("", "-", "None", "NaN", "nan"):
                val_str = ""
            else:
                try:
                    # DB stores centimetres -> convert to metres.
                    val_str = str(round(float(raw_val) / 100.0, 6))
                except ValueError:
                    val_str = ""
            records[ts] = val_str
            quality_map[ts] = quality
    return records, quality_map, n_q1, n_q2_dropped


def load_watertemp_rows(code):
    """Load WaterTemp rows for a station from the watertemp_extended CSV.

    Returns a dict {datetime: temp_str} and a dict {datetime: quality_str}.
    Only quality == "0" rows are kept (quality 2 = wrong, e.g. STM03 has
    ~53 % flagged).  Missing files (stations with no water temp in the
    extension period) yield empty dicts.
    """
    path = os.path.join(WATERTEMP_DIR, f"{code}_Watertemp.csv")
    if not os.path.exists(path):
        print(f"    (no WaterTemp file for {code}, skipping)")
        return {}, {}

    records = {}
    quality_map = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # skip header: id,code_id,station_name,x_utm,y_utm,variable,quality,timestamp,value
        for row in reader:
            if not row or len(row) < 9:
                continue
            variable = row[5].strip()
            if variable != "WaterTemp":
                continue
            quality = row[6].strip()
            if quality != "0":
                continue
            ts = parse_db_timestamp(row[7])
            raw_val = row[8].strip()
            if raw_val in ("", "-", "None", "NaN", "nan"):
                val_str = ""
            else:
                try:
                    val_str = str(round(float(raw_val), 4))
                except ValueError:
                    val_str = ""
            records[ts] = val_str
            quality_map[ts] = quality
    return records, quality_map


def append_to_clean_csv(code, rows_sorted):
    """Append new (timestamp, height_str, temp_str, quality_str) tuples.

    HEIGHT_m and WATER_TEMP_C are written; DISCHARGE, VOLUME and LOAD are
    left empty.  QUALITY is the worst (max) of the two source variables;
    DATA_TYPE is always "observed".
    """
    path = os.path.join(CLEAN_DIR, f"{code}.csv")
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for ts, height_str, temp_str, quality_str in rows_sorted:
            writer.writerow([ts.strftime("%Y-%m-%d %H:%M:%S"), height_str, temp_str, quality_str, "observed"])


def update_metadata(code, new_last_ts, new_count, n_q1, n_q2_dropped, total_rows):
    """Update T_end and total-rows in the metadata TXT; append an extension note."""
    path = os.path.join(CLEAN_DIR, f"{code}_metadata.txt")
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    already_extended = any("Extensión con datos de nivel de agua" in l for l in lines)

    new_lines = []
    for line in lines:
        if line.startswith("T_end"):
            new_lines.append(f"T_end (último registro): {new_last_ts}\n")
        elif line.strip().startswith("- Total de filas exportadas:"):
            new_lines.append(f"  - Total de filas exportadas: {total_rows}\n")
        else:
            new_lines.append(line)

    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"

    if not already_extended:
        new_lines.append(f"  - Extensión con datos de nivel de agua y temperatura del agua (prod_data + watertemp_extended): "
                         f"{new_count} registros nuevos añadidos hasta {new_last_ts}.\n")
        new_lines.append(f"  - Solo HEIGHT_m y WATER_TEMP_C disponibles en la extensión; "
                         f"DISCHARGE_m3s, VOLUME_m3 y LOAD_kg se derivarán posteriormente con curvas de aforo.\n")
        new_lines.append(f"  - WATER_TEMP_C en la extensión: solo se conservan registros quality = 0.\n")
        new_lines.append(f"  - IMPORTANTE: el DB exporta WaterLevel en CENTÍMETROS; convertido a metros (/100) al añadir.\n")
        new_lines.append(f"  - Registros quality = 1 (sospechosos) conservados: {n_q1}; quality = 2 (erróneos) descartados: {n_q2_dropped}.\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def process_station(code, name):
    print(f"\nProcesando {code} - {name}...")

    last_ts, existing_count = get_last_clean_ts_and_count(code)
    print(f"  Último timestamp en limpio: {last_ts}  ({existing_count} filas)")

    all_new, quality_map, n_q1, n_q2_dropped = load_new_waterlevel_rows(code)
    print(f"  Registros en fichero nuevo (prod_data): {len(all_new)}")
    if n_q1:
        print(f"  AVISO: {n_q1} registros con quality = 1 (sospechosos) conservados")
    if n_q2_dropped:
        print(f"  {n_q2_dropped} registros con quality = 2 (erróneos) descartados")

    temp_rows, temp_q = load_watertemp_rows(code)
    print(f"  Registros de WaterTemp (watertemp_extended): {len(temp_rows)}")

    # Merge water level + water temp on the union of timestamps.  Each column
    # is filled where available; QUALITY is the worst (max) of the two sources.
    all_ts = set(all_new.keys()) | set(temp_rows.keys())
    merged = {}
    for ts in all_ts:
        h = all_new.get(ts, "")
        t = temp_rows.get(ts, "")
        q_ints = []
        for q_map in (quality_map, temp_q):
            if ts in q_map:
                try:
                    q_ints.append(int(q_map[ts]))
                except (ValueError, TypeError):
                    pass
        q_str = str(max(q_ints)) if q_ints else ""
        merged[ts] = (h, t, q_str)

    to_append = sorted(
        [(ts, h, t, q) for ts, (h, t, q) in merged.items() if ts > last_ts],
        key=lambda x: x[0],
    )
    print(f"  Registros a añadir (después de {last_ts}): {len(to_append)}")

    if not to_append:
        print("  Nada que añadir.")
        return

    new_last_ts = to_append[-1][0]
    append_to_clean_csv(code, to_append)
    total_rows = existing_count + len(to_append)
    update_metadata(code, new_last_ts, len(to_append), n_q1, n_q2_dropped, total_rows)

    print(f"  Total filas en CSV resultante: {total_rows}")
    print(f"  T_end actualizado: {new_last_ts}")
    print(f"  CSV actualizado: {os.path.join(CLEAN_DIR, code + '.csv')}")
    print(f"  Metadatos actualizados: {os.path.join(CLEAN_DIR, code + '_metadata.txt')}")


if __name__ == "__main__":
    for code, name in STATIONS.items():
        process_station(code, name)
    print("\nListo.")
