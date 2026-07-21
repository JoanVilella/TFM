# TFM — Hydrological Modelling of the Sant Miquel Basin

Master's thesis (TFM): comparison of a physics-based hydrological model
(**HEC-HMS**) with machine-learning models for predicting the water level
(`HEIGHT_m`) at the **STM08 – Sa Marjal** station, using the remaining STM and
AEMET stations as predictors. See `docs/plan_TFM.md` for the full work plan.

## Repository structure

```
├── data/                  # NOT tracked in git (~850 MB, see .gitignore)
│   ├── raw/               #   original, immutable data
│   │   ├── stm/           #     STM01–STM08 station exports (.xlsx + hydro .csv)
│   │   ├── aemet/         #     UIB-Estrany .phor files (B013X, B605X, B691Y)
│   │   └── db_exports/    #     dumps from the internal database
│   │       ├── waterlevel/    #   extension data STM03–STM08 (HEIGHT_m)
│   │       ├── precipitation/ #   extension data STM01–STM02
│   │       ├── discharge/     #   discharge extracts STM03–STM05
│   │       └── raw_B013X_B605X_B691Y_2023_01_01_2026_07_14.csv
│   ├── clean/             #   standardized CSVs + metadata (pipeline output)
│   └── processed/         #   modeling datasets (e.g. dataset_hourly.parquet)
├── scripts/
│   ├── cleaning/          # raw → clean (clean_STM01–08.py, clean_UIB_Estrany.py)
│   └── extension/         # clean → clean+DB extension (extend_*.py)
├── notebooks/             # 01_eda … 07_comparison (per plan)
├── hec_hms/               # HEC-HMS project files
├── results/
│   ├── figures/           # plots for the thesis
│   └── metrics/           # NSE / KGE / RMSE / PBIAS tables
├── thesis/                # LaTeX memoir (IEEEtran template)
└── docs/                  # plan_TFM.md, bitacora.md (lab notebook)
```

## Data pipeline

All scripts resolve their paths from the repository root (via `__file__`),
so they can be run from any working directory.

```bash
pip install -r requirements.txt

# 1. Clean the raw station exports → data/clean/
python scripts/cleaning/clean_STM01.py   # ... through clean_STM08.py
python scripts/cleaning/clean_UIB_Estrany.py

# 2. Extend the clean series with the internal DB exports (run after cleaning)
python scripts/extension/extend_STM_waterlevel.py   # STM03–STM08 (HEIGHT_m)
python scripts/extension/extend_STM_meteo.py        # STM01–STM02 (precip/temp)
python scripts/extension/extend_AEMET_DB.py         # B013X, B605X, B691Y
```

Each clean CSV in `data/clean/` has a companion `*_metadata.txt` with the
start date (`T0`) and the sampling-frequency periods of the station.

## Thesis

The LaTeX memoir lives in `thesis/` (`document.tex`, IEEEtran template).
Compile with any standard LaTeX toolchain (e.g. `pdflatex` + `bibtex`).
