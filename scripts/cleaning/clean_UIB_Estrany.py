# ABOUTME: Limpieza y estandarización de los datos horarios de precipitación
# ABOUTME: de estaciones UIB-Estrany (B013X, B691Y, B605X). Genera CSVs limpios y metadatos.

import csv
import os
import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

RAW_DIR = str(REPO_ROOT / "data/raw/aemet")
CLEAN_DIR = str(REPO_ROOT / "data/clean")

STATIONS = {
    "B013X": {
        "name": "Lluc",
        "files": ["UIB-Estrany.phor1", "UIB-Estrany.phor2", "UIB-Estrany.phor3"],
    },
    "B691Y": {
        "name": "Sa Pobla-Sa Canova",
        "files": ["UIB-Estrany.phor2", "UIB-Estrany.phor3"],
    },
    "B605X": {
        "name": "Muro-S'albufera",
        "files": ["UIB-Estrany.phor2", "UIB-Estrany.phor3"],
    },
}


def read_station_rows(station_code, file_bases):
    """Read all rows for a station from the specified source files."""
    rows = []
    for base in file_bases:
        path = os.path.join(RAW_DIR, f"{base}.txt")
        with open(path, "r", encoding="latin-1") as f:
            reader = csv.reader(f, delimiter=";")
            try:
                next(reader)  # skip header
            except StopIteration:
                continue
            for row in reader:
                if row and row[0].strip() == station_code:
                    rows.append(row)
    # Sort chronologically
    rows.sort(key=lambda r: (int(r[1]), int(r[2]), int(r[3])))
    return rows


def parse_hourly_values(row):
    """Extract P24 and hourly PH values from a raw row."""
    p24_raw = row[8].strip()
    p24 = None
    if p24_raw not in ("", "-"):
        try:
            p24 = float(p24_raw)
        except ValueError:
            pass

    hourly = []
    for i in range(9, 33):
        if i < len(row):
            val = row[i].strip()
            if val in ("", "-"):
                hourly.append(None)
            else:
                try:
                    hourly.append(float(val))
                except ValueError:
                    hourly.append(None)
        else:
            hourly.append(None)
    return p24, hourly


def expand_day_to_hourly(year, month, day, hourly_vals):
    """Convert one daily row into 24 hourly (timestamp, value) records.

    Convention:
        PH01 -> 01:00, PH02 -> 02:00, ..., PH23 -> 23:00,
        PH24 -> 00:00 del día siguiente (fin del período 23:00-00:00).
    """
    records = []
    base = datetime.date(year, month, day)
    for idx, val in enumerate(hourly_vals, start=1):
        if idx == 24:
            ts = datetime.datetime.combine(base + datetime.timedelta(days=1), datetime.time(0, 0))
        else:
            ts = datetime.datetime.combine(base, datetime.time(idx, 0))
        records.append((ts, val))
    return records


def process_station(code, info):
    print(f"\nProcesando {code} - {info['name']}...")

    rows = read_station_rows(code, info["files"])
    if not rows:
        print(f"  No se encontraron datos para {code}")
        return

    # --- Data quality checks ---
    p24_only_days = 0
    all_records = []

    for row in rows:
        year = int(row[1])
        month = int(row[2])
        day = int(row[3])
        p24, hourly = parse_hourly_values(row)

        if p24 is not None and all(v is None for v in hourly):
            p24_only_days += 1

        records = expand_day_to_hourly(year, month, day, hourly)
        all_records.extend(records)

    timestamps = [ts for ts, _ in all_records]
    first_ts = timestamps[0]
    last_ts = timestamps[-1]

    # --- Write clean CSV ---
    csv_path = os.path.join(CLEAN_DIR, f"{code}.csv")
    os.makedirs(CLEAN_DIR, exist_ok=True)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["TIMESTAMP", "PRECIP_mm", "QUALITY", "DATA_TYPE"])
        for ts, val in all_records:
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
            # Convert from tenths of mm to mm; keep nulls as empty strings
            val_str = "" if val is None else str(round(val / 10, 4))
            writer.writerow([ts_str, val_str, "", "observed"])

    print(f"  CSV guardado en: {csv_path}")

    # --- Write metadata ---
    meta_path = os.path.join(CLEAN_DIR, f"{code}_metadata.txt")
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write(f"ESTACIÓN: {code} - {info['name']}\n")
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
        f.write("  - Fuente: UIB-Estrany (formato phor de AEMET/SMN).\n")
        f.write("  - Encoding corregido: latin-1 → UTF-8.\n")
        f.write("  - Datos diarios desagregados a registros horarios.\n")
        f.write("  - PHhh asignado a las hh:00 (hora local).\n")
        f.write("  - PH24 se asigna a las 00:00 del día siguiente (período 23:00-00:00).\n")
        f.write("  - Valores nulos (celdas vacías o '-') exportados como celdas vacías.\n")
        f.write("  - Conversión de unidades: décimas de mm → mm (dividido por 10).\n")
        if p24_only_days:
            f.write(f"  - {p24_only_days} días con P24 disponible pero todas las horas nulas.\n")
        f.write(f"  - Total de filas exportadas: {len(all_records)}\n")

    print(f"  Metadatos guardados en: {meta_path}")


if __name__ == "__main__":
    for code, info in STATIONS.items():
        process_station(code, info)
    print("\nListo.")
