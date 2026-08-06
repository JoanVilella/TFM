# ABOUTME: Extiende los CSV limpios de STM03–STM08 con datos de nivel de agua nuevos
# ABOUTME: desde data/raw/db_exports/prod_data/, integrándolos cronológicamente hasta la fecha actual.

import csv
import os
import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

RAW_DIR   = str(REPO_ROOT / "data/raw/db_exports/prod_data")
CLEAN_DIR = str(REPO_ROOT / "data/clean")

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

    Returns a dict {datetime: height_str} and a count of non-zero quality records.
    """
    path = os.path.join(RAW_DIR, f"{code.lower()}.csv")
    records = {}
    non_zero_quality = 0
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
            if quality != "0":
                non_zero_quality += 1
            ts = parse_db_timestamp(row[7])
            raw_val = row[8].strip()
            if raw_val in ("", "-", "None", "NaN", "nan"):
                val_str = ""
            else:
                try:
                    val_str = str(round(float(raw_val), 6))
                except ValueError:
                    val_str = ""
            records[ts] = val_str
    return records, non_zero_quality


def append_to_clean_csv(code, rows_sorted):
    """Append new (timestamp, height_str) tuples to the clean CSV.

    Only HEIGHT_m is written; DISCHARGE, VOLUME and LOAD are left empty.
    """
    path = os.path.join(CLEAN_DIR, f"{code}.csv")
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for ts, height_str in rows_sorted:
            writer.writerow([ts.strftime("%Y-%m-%d %H:%M:%S"), height_str])


def update_metadata(code, new_last_ts, new_count, non_zero_quality, total_rows):
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
        new_lines.append(f"  - Extensión con datos de nivel de agua (base de datos interna — prod_data): "
                         f"{new_count} registros nuevos añadidos hasta {new_last_ts}.\n")
        new_lines.append(f"  - Solo HEIGHT_m disponible en la extensión; "
                         f"DISCHARGE_m3s, VOLUME_m3 y LOAD_kg se derivarán posteriormente con curvas de aforo.\n")
        if non_zero_quality:
            new_lines.append(f"  - AVISO extensión: {non_zero_quality} registro(s) con quality != 0 incluidos.\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def process_station(code, name):
    print(f"\nProcesando {code} - {name}...")

    last_ts, existing_count = get_last_clean_ts_and_count(code)
    print(f"  Último timestamp en limpio: {last_ts}  ({existing_count} filas)")

    all_new, non_zero_quality = load_new_waterlevel_rows(code)
    print(f"  Registros en fichero nuevo (prod_data): {len(all_new)}")
    if non_zero_quality:
        print(f"  AVISO: {non_zero_quality} registros con quality != 0")

    to_append = sorted(
        [(ts, val) for ts, val in all_new.items() if ts > last_ts],
        key=lambda x: x[0],
    )
    print(f"  Registros a añadir (después de {last_ts}): {len(to_append)}")

    if not to_append:
        print("  Nada que añadir.")
        return

    new_last_ts = to_append[-1][0]
    append_to_clean_csv(code, to_append)
    total_rows = existing_count + len(to_append)
    update_metadata(code, new_last_ts, len(to_append), non_zero_quality, total_rows)

    print(f"  Total filas en CSV resultante: {total_rows}")
    print(f"  T_end actualizado: {new_last_ts}")
    print(f"  CSV actualizado: {os.path.join(CLEAN_DIR, code + '.csv')}")
    print(f"  Metadatos actualizados: {os.path.join(CLEAN_DIR, code + '_metadata.txt')}")


if __name__ == "__main__":
    for code, name in STATIONS.items():
        process_station(code, name)
    print("\nListo.")
