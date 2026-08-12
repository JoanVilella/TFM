# CHANGELOG — Project Diary

> Quick-reference log of what has been done, decisions made, and open issues.
> Each iteration appends a new entry at the top. Scan this before doing any work.

---

## Iteration 11 — 2026-08-07

### Changes made

**Measurements table (advisor requirement)**

| Change | Detail |
|--------|--------|
| `scripts/preprocessing/resample.py` | Added `build_measurements_table()` — melts the 10-min grid into long format |
| Output (parquet) | `data/processed/measurements.parquet` (98.8 MB) |
| Output (CSV.gz) | `data/processed/measurements.csv.gz` (45.2 MB) |

### Measurements table summary

| Stat | Value |
|------|-------|
| Rows | 10,812,691 (19 vars × 569,089 timestamps) |
| Columns | 6: TIMESTAMP, STATION, VARIABLE, VALUE, QUALITY, DATA_TYPE |
| Variables | HEIGHT_m, DISCHARGE_m3s, TEMP_C, PRECIP_mm |
| Stations | 11 (STM01–STM08 + B013X, B605X, B691Y) |
| QUALITY non-null | 339,705 rows (DB extension data only) |
| DATA_TYPE | All "observed" |

### Advisor tables status

| Table | Status |
|-------|--------|
| Stations | Done (in thesis §3.1, Table 1) |
| Measurements | Done (this iteration) |
| Events | Done (Iteration 10) |
| Training | Done (Iteration 8-9) |

### Remaining open issues

- [ ] `flow_to_meters` inverse rating curve
- [ ] DB extension data harmonization (blocked)
- [ ] Basin topology confirmation (geo team)

*End of Iteration 11.*


---

## Iteration 10 — 2026-08-07

### Changes made

**Flood event detection (Peak Over Threshold)**

| Change | Detail |
|--------|--------|
| `scripts/preprocessing/event_detection.py` | New module: POT-based detection using STM08_DISCHARGE_m3s |
| Method | Peak Over Threshold with independence criterion (Claps & Laio 2003; Burn et al. 2016) |
| Parameters | Q > 0.2 m³/s trigger; 3h core wiggle room; 6h inter-event merge; 12h/24h start/end lookback; 72h max core cap |
| Output | `data/processed/events.csv` (196 events) |
| Training table | Now 144 columns: `event_id` added (Int64, NaN = non-event) |

### Event statistics

| Stat | Value |
|------|-------|
| Total events | 196 |
| Train / Val / Test | 100 / 16 / 80 |
| Mean duration | 20.8 h |
| Median duration | 11.8 h |
| Max duration | 108.0 h |
| Top peak Q | 19.81 m³/s (event #53, Mar 2018) |
| Rows in events | 23,725 (4.2% of training table) |

### Detected event characteristics (per event)

| Column | Description |
|--------|-------------|
| `event_id` | Sequential integer |
| `start_ts`, `peak_ts`, `end_ts` | Event timestamps |
| `peak_q_m3s`, `peak_h_m` | Peak discharge and level |
| `duration_h` | Hours from start to end |
| `acc_precip_mm` | Total precip across all stations during event |
| `max_intensity_mm_h` | Max hourly rain rate |
| `split` | train / validation / test (by peak timestamp) |

### Remaining open issues

- [ ] Build the remaining advisor tables (Measurements [grid in long format], Events table already exists)
- [ ] `flow_to_meters` inverse rating curve
- [ ] DB extension data harmonization (blocked)
- [ ] Basin topology confirmation (geo team)

*End of Iteration 10.*


---

## Iteration 9 — 2026-08-07

### Changes made

**Chronological split added to training table**

| Change | Detail |
|--------|--------|
| `feature_engineering.py` | `add_chronological_split()` added; called automatically by `build_training_table()` |
| `split` column | Categorical: `train` / `validation` / `test` (strictly chronological) |
| Training table | Now 143 columns (1 new), 96 MB |

### Split breakdown

| Partition | Period | Rows | % |
|-----------|--------|------|---|
| Train | 2014-09-26 → 2020-12-31 | 324,594 | 57.6% |
| Validation | 2021-01-01 → 2022-06-30 | 78,576 | 13.9% |
| Test | 2022-07-01 → 2025-07-22 | 160,528 | 28.5% |

### Remaining open issues

- [ ] Define reproducible event detection rule
- [ ] Build the 4 required advisor tables (stations [done in thesis], measurements, events, training)
- [ ] Count usable flood events
- [ ] DB extension data harmonization (blocked on data provider)
- [ ] `flow_to_meters` inverse rating curve (needed for HEC-HMS validation)
- [ ] Basin topology confirmation (geo team — affects UPSTREAM_Q calculation)

*End of Iteration 9.*


---

## Iteration 8 — 2026-08-07

### Changes made

**Feature engineering — training table built**

| Change | Detail |
|--------|--------|
| `scripts/preprocessing/feature_engineering.py` | New module: `build_training_table()` transforms the 10-min grid into a modelling-ready DataFrame |
| Lagged predictors | HEIGHT_m (6 stations), TEMP_C (2 stations), PRECIP_mm (5 stations) at t-1h, t-2h, t-3h, t-6h, t-12h, t-24h |
| Cumulative precipitation | Rolling sums over 3h, 6h, 12h, 24h, 48h (antecedent precipitation index) for 5 stations |
| Upstream discharge | `UPSTREAM_Q` = sum of STM03–STM07 DISCHARGE_m3s |
| Temporal features | `hour_sin`, `hour_cos`, `doy_sin`, `doy_cos` (sin/cos encoding), `month` (raw integer) |
| Targets | `TARGET_t+1h`, `TARGET_t+6h`, `TARGET_t+24h` (STM08_HEIGHT_m shifted by +6, +36, +144 steps) |
| Output | `data/processed/training_table.parquet` (96 MB, 563,698 rows × 142 columns) |

### Design decisions

| Decision | Justification |
|----------|--------------|
| DISCHARGE lags skipped | Q = f(H) via rating curve → exact multicollinearity with HEIGHT lags. Only upstream-aggregated sum included. (Kratzert et al. 2019, HESS 23, 5089–5110) |
| sin/cos for cyclical time | Preserves circular topology of daily and annual cycles for models that don't learn it implicitly (Lim et al. 2021, Int. J. Forecasting) |
| Month as raw integer | Only 12 categories; tree models split on it; DL models embed it |

### Training table summary

| Stat | Value |
|------|-------|
| Rows | 563,698 (dropped 5,391 for missing targets at series end) |
| Columns | 142 (30 base + 112 engineered) |
| Column groups | 30 base, 78 lags, 25 cumulative precip, 1 upstream Q, 5 temporal, 3 targets |
| Size | 96.0 MB (Parquet) |

### Pending questions

- [ ] **Basin topology**: `UPSTREAM_Q` currently sums STM03–STM07 DISCHARGE assuming all are parallel tributaries. If stations are in series, the sum double-counts. Pending confirmation from the geo team. When confirmed, update `UPSTREAM_STATIONS` in `feature_engineering.py`.

### Remaining open issues

- [ ] Chronological split (train up to 2020-12-31, val 2021–2022-06, test 2022-07+)
- [ ] Define reproducible event detection rule
- [ ] Build the 4 required advisor tables (stations, measurements, events, training)
- [ ] DB extension data harmonization (blocked on data provider)
- [ ] `flow_to_meters` inverse rating curve (needed for HEC-HMS validation)

*End of Iteration 8.*


---

## Iteration 7 — 2026-08-07

### Changes made

**DISCHARGE_m3s derived from HEIGHT_m via rating curves**

| Change | Detail |
|--------|--------|
| `scripts/preprocessing/rating_curve.py` | New module: parses `data/rating_curves/rating_curves.csv`, builds piecewise polynomial functions (meters_to_flow direction only) |
| `scripts/preprocessing/resample.py` | `build_10min_grid()` now calls `apply_discharge()` automatically |
| 10-min grid | 6 new `{STATION}_DISCHARGE_m3s` columns added (30 cols total, up from 24) |

### Rating curve format

- Piecewise polynomial: Q(H) = Σ(base_i · H^exp_i) over interval [x0, x1)
- 6 stations (STM03–STM08), 1–3 segments each
- Last segment has no upper bound (NULL = ∞)
- H values outside all segments return NaN

### Discharge statistics

| Station | Max Q (m³/s) | Null rate | Notes |
|---------|-------------|-----------|-------|
| STM03 | 8.85 | 10.0% | |
| STM04 | 26.87 | 3.0% | |
| STM05 | 155.97 | 13.8% | Highest peak |
| STM06 | 112.09 | 6.9% | |
| STM07 | 45.48 | 2.5% | |
| STM08 | 19.81 | 0.8% | Target station (wetland outlet) |

### Deferred to future

- [ ] `flow_to_meters` (inverse direction, Q→H): needed for HEC-HMS validation.

### Remaining open issues

- [ ] Feature engineering (lags, cumulative precip, temporal features) → Training table
- [ ] Chronological split (train up to 2020-12-31, val 2021–2022-06, test 2022-07+)
- [ ] Define reproducible event detection rule
- [ ] Build the 4 required advisor tables (stations, measurements, events, training)
- [ ] DB extension data harmonization (blocked on data provider)
- [ ] `flow_to_meters` inverse rating curve (needed for HEC-HMS validation)

*End of Iteration 7.*


---

## Iteration 6 — 2026-08-07

### Changes made

**10-min grid construction (Phase 2 — resampling)**

Built the uniform 10-minute grid from all 11 clean CSVs using the validated window
2014-09-26 → 2025-07-22 (~11 years, 569,089 timestamps, 24 columns).

| Change | Detail |
|--------|--------|
| `scripts/preprocessing/resample.py` | Reusable module: `build_10min_grid()`, parameterized for start/end dates and quality filter |
| Instantaneous (HEIGHT_m, TEMP_C) | 5→10 min: mean aggregation; 15→10 min: linear interpolation (gap-capped at 3 h) |
| Precip — STM (cumulative) | Cumsum → interpolate cumulative → diff on 10-min grid (mass-conserving) |
| Precip — AEMET (hourly → 10-min) | Template-based disaggregation using STM01/STM02 10-min patterns; fallback to conservative cumulative interpolation |
| Quality columns | Forward-filled from source data to 10-min grid (NaN = Excel data with no flag) |
| Output | `data/processed/grid_10min.parquet` (120.1 MB) |
| Notebook | `notebooks/02_preprocessing.ipynb` — loads grid, verifies resampling, gap analysis, mass conservation checks |

### Grid summary

| Stat | Value |
|------|-------|
| Rows | 569,089 (10-min) |
| Columns | 24 (13 measurements + 11 quality) |
| Period | 2014-09-26 → 2025-07-22 |
| Duration | ~10.8 years |
| Null rates (worst) | STM02_TEMP_C 28.7%, STM01_TEMP_C 18.3%, STM05_HEIGHT_m 13.8% |
| Null rates (best) | STM08_HEIGHT_m 0.8%, STM02_PRECIP_mm 1.9%, STM07_HEIGHT_m 2.4% |

### Remaining open issues

- [ ] Feature engineering (lags, cumulative precip, temporal features) → Training table
- [ ] Chronological split (train up to 2020-12-31, val 2021–2022-06, test 2022-07+)
- [ ] Define reproducible event detection rule
- [ ] Build the 4 required advisor tables (stations, measurements, events, training)
- [ ] DISCHARGE/VOLUME/LOAD derivation via rating curves
- [ ] DB extension data harmonization (blocked on data provider)

*End of Iteration 6.*


---

## Iteration 5 — 2026-08-07

### Changes made

**Added QUALITY and DATA_TYPE columns to all clean CSVs**

| Change | Detail |
|--------|--------|
| Quality flag meanings | 0 = good data, 1 = suspicious data, 2 = wrong data (only from prod_data DB exports; Excel data has no flags) |
| Cleaning scripts (9) | All now write `QUALITY` (empty for Excel data) and `DATA_TYPE` ("observed") columns |
| Extension scripts (3) | `extend_STM_waterlevel.py`, `extend_STM_meteo.py`, `extend_AEMET_DB.py` now preserve the `quality` field from prod_data CSVs and write `QUALITY` + `DATA_TYPE` columns |
| CSVs regenerated | All 11 clean CSVs regenerated from scratch (cleaning → extension), matching previous Iteration 2 row counts |
| Notebook loader | `01_eda.ipynb` cell 4 updated: `QUALITY` kept as nullable `Int64`, `DATA_TYPE` as string; both excluded from `_coerce_numeric()` |
| Quality summary | Notebook now prints a quality-flag distribution table per station on load |
| Metadata | All 11 `_metadata.txt` files now include a `CALIDAD (QUALITY)` section documenting flag meanings |

### Modified files

| File | Changes |
|------|---------|
| `scripts/cleaning/clean_STM01.py` | Header → `TIMESTAMP, PRECIP_mm, TEMP_C, QUALITY, DATA_TYPE`; rows write `"", "observed"` |
| `scripts/cleaning/clean_STM02.py` | Same as STM01 |
| `scripts/cleaning/clean_STM03.py` | Header → `TIMESTAMP, HEIGHT_m, QUALITY, DATA_TYPE`; rows write `"", "observed"` |
| `scripts/cleaning/clean_STM04.py` | Same as STM03 |
| `scripts/cleaning/clean_STM05.py` | Same as STM03 |
| `scripts/cleaning/clean_STM06.py` | Same as STM03 |
| `scripts/cleaning/clean_STM07.py` | Same as STM03 |
| `scripts/cleaning/clean_STM08.py` | Same as STM03 |
| `scripts/cleaning/clean_UIB_Estrany.py` | Header → `TIMESTAMP, PRECIP_mm, QUALITY, DATA_TYPE`; rows write `"", "observed"` |
| `scripts/extension/extend_STM_waterlevel.py` | `load_new_waterlevel_rows()` returns quality_map; `append_to_clean_csv()` writes QUALITY + DATA_TYPE |
| `scripts/extension/extend_STM_meteo.py` | Tracks quality per variable (Rain10m/AirTemp), merges as max(worst) per timestamp |
| `scripts/extension/extend_AEMET_DB.py` | Tracks quality alongside value; rewrites full CSV with QUALITY + DATA_TYPE |
| `notebooks/01_eda.ipynb` | Cell 4: QUALITY → Int64, DATA_TYPE → string; quality summary table |
| `data/clean/*_metadata.txt` | All 11 files: added CALIDAD (QUALITY) section |

### Remaining open issues

- [ ] DISCHARGE/VOLUME/LOAD will be derived from HEIGHT_m via rating curves (user's next step).
- [ ] STM03 has 51,336 records with `quality != 0` — most are in the extension period.
- [ ] Define reproducible event detection rule (start/end criteria).
- [ ] Build the 4 required tables: stations, measurements, events, training.
- [ ] DB extension data (2025–2026) still has unvalidated artifacts (177 m spikes, etc.).

*End of Iteration 5.*


---

## Iteration 4 — 2026-08-06

### Changes made

**Fixed `clean_STM02.py` tipping-bucket formula handling**

`clean_STM02.py` (line ~70) was writing raw Excel formula strings (`=0.2*N`, `=N*0.2`) verbatim to the `PRECIP_mm` column of `STM02.csv`. The `TEMP_C` column already had a string guard (`isinstance(temp, str)`) that nullified formula strings, but `PRECIP_mm` did not.

| Change | Detail |
|--------|--------|
| Added `import re` | For tipping-bucket regex matching |
| Added `recover_precip()` | Evaluates `=0.2*N` / `=N*0.2` → numeric `0.2*N` mm; nullifies other formula strings and `"NAN"` |
| Pre-export scan | Counts tipping-bucket cells for metadata (73 found) |
| Updated CSV writing | `recover_precip(row[2])` replaces the old `str(precip)` |
| Updated metadata | Added note: "73 celdas de Precip contenían fórmulas Excel de tipping-bucket (=0.2*N); evaluadas y recuperadas." |

**Removed formula-recovery workaround from notebook loader**

- `_coerce_numeric()` in `01_eda.ipynb` cell 4 simplified: removed `FORMULA_RE`, regex extraction, and recovery logic. Now just `pd.to_numeric(s, errors="coerce")`.
- Updated §2 and §8 markdown comments to reflect the fix is upstream.
- Dead `load_station` v1 still present in cell 4 (harmless, overridden).

**Re-executed notebook**

- Notebook re-executed after `clean_STM02.py` regeneration → **"WARNING PRECIP_mm: recovered 73 raw Excel tipping-bucket formulas" is gone.**
- All 22 cells executed successfully with 0 errors.
- All 14 figures regenerated.

### Remaining open issues

- [ ] STM03 has 51,336 records with `quality != 0` — most are in the extension period.
- [ ] DISCHARGE/VOLUME/LOAD will be derived from HEIGHT_m via rating curves (user's next step).
- [ ] Quality flag meanings (0/1/...) still undocumented. Flags are counted but not preserved in clean CSVs.

*End of Iteration 4.*


---

## Iteration 3 — 2026-08-06

### Changes made

**Updated `01_eda.ipynb` comments to match re-executed results**

The notebook was re-executed after the v2 CSV format change (HEIGHT_m only), but several markdown comments still reflected Iteration 1 numbers (when DISCHARGE/VOLUME/LOAD were present). Fixed:

| Location | Before | After |
|----------|--------|-------|
| §3.1 plausibility screening | kept −0.5 m ≤ H ≤ 5 m **and** 0 ≤ Q ≤ 200 m³/s | keeps −0.5 m ≤ H ≤ 5 m only (Q/V/L are all NaN) |
| §8 missing data | `LOAD_kg` (STM03 43 %), `DISCHARGE_m3s`/`VOLUME_m3` (22 %), `STM02 TEMP_C` (29 %) | DISCHARGE/VOLUME/LOAD 100 % NaN (intentional); `STM02 TEMP_C` 28.6 %, `STM01 TEMP_C` 11.0 % |
| §8 NaN runs | 31 NaN runs | **32** NaN runs |

### Remaining open issues

- [ ] STM03 has 51,336 records with `quality != 0` — most are in the extension period.
- [ ] DISCHARGE/VOLUME/LOAD will be derived from HEIGHT_m via rating curves (user's next step).
- [ ] Quality flag meanings (0/1/...) still undocumented. Flags are counted but not preserved in clean CSVs.
- [x] ~~`clean_STM02.py` still has the tipping-bucket formula issue (73 cells with `=0.2*N`)~~ → **Fixed in Iteration 4.**

*End of Iteration 3.*


---

## Iteration 2 — 2026-08-06

### Changes made

**Data source change: staging DB → production DB (prod_data)**

The old `data/raw/db_exports/waterlevel/`, `precipitation/`, and the combined AEMET CSV (from staging) have been replaced with CSVs from the production database in `data/raw/db_exports/prod_data/`. The prod_data files have better quality (fewer artifacts, validated records).

**CSV format change: hydro stations now contain only HEIGHT_m**

The hydro cleaning scripts (`clean_STM03–STM08.py`) now extract only `HEIGHT...2` (the validated/filtered water level). DISCHARGE, VOLUME, and LOAD columns are no longer exported from Excel. These will be derived later from rating curves.

**Modified scripts**

| Script | Changes |
|--------|---------|
| `scripts/cleaning/clean_STM03.py` | Only extracts HEIGHT_m (col 1) + DATE.UTC (col 16). |
| `scripts/cleaning/clean_STM04.py` | Only extracts HEIGHT_m (col 1) + DATE.UTC (col 14). |
| `scripts/cleaning/clean_STM05.py` | Only extracts HEIGHT_m (col 1) + DATE.UTC (col 14). |
| `scripts/cleaning/clean_STM06.py` | Only extracts HEIGHT...2 (col 1) + DATE UTC (col 14). |
| `scripts/cleaning/clean_STM07.py` | Only extracts HEIGHT_m (col 1) + DATE.UTC (col 15). |
| `scripts/cleaning/clean_STM08.py` | Only extracts HEIGHT...2 (col 1) + DATE.UTC (col 14). |
| `scripts/extension/extend_STM_waterlevel.py` | Source: `prod_data/{code.lower()}.csv`. Writes only HEIGHT_m column. |
| `scripts/extension/extend_STM_meteo.py` | Source: `prod_data/{code.lower()}.csv`. |
| `scripts/extension/extend_AEMET_DB.py` | Source: `prod_data/{code}.csv` (per-station, not combined). Added `Rain60m` variable filter. |

**Regenerated all clean CSVs**

All 11 clean CSVs were regenerated from scratch:
1. Re-ran `clean_UIB_Estrany.py` (AEMET phor → clean)
2. Re-ran `clean_STM01.py`, `clean_STM02.py` (meteo Excel → clean)
3. Re-ran `clean_STM03–STM08.py` (hydro Excel → clean — HEIGHT_m only)
4. Re-ran `extend_AEMET_DB.py` (prod_data → merge into clean)
5. Re-ran `extend_STM_meteo.py` (prod_data → append)
6. Re-ran `extend_STM_waterlevel.py` (prod_data → append)

**Updated 01_eda.ipynb**

- Loader adds empty `DISCHARGE_m3s`, `VOLUME_m3`, `LOAD_kg` columns (NaN-filled) to prevent KeyErrors in downstream code
- Intermittency stats now use only `HEIGHT_m` (DISCHARGE unavailable)
- Plausibility screening simplified to HEIGHT_m only (removed DISCHARGE screening + QC dict)
- STM08 overview shows only HEIGHT_m (single panel); rating curve figure removed
- Notebook re-executed: 0 errors
- 13 figures regenerated (`stm08_rating_curve.png` removed since DISCHARGE is unavailable)

### Data state after regeneration

| Station | Rows | T0 | T_end |
|---------|------|----|----|
| STM03 | 595,356 | 2012-10-01 | 2026-08-05 |
| STM04 | 587,756 | 2012-12-06 | 2026-08-05 |
| STM05 | 569,422 | 2012-10-01 | 2026-08-05 |
| STM06 | 570,087 | 2012-10-01 | 2026-08-05 |
| STM07 | 563,449 | 2012-10-01 | 2026-08-05 |
| STM08 | 563,734 | 2013-03-04 | 2026-08-05 |
| STM01 | 532,894 | 2012-11-30 | 2026-08-05 |
| STM02 | 481,211 | 2014-09-26 | 2026-08-05 |
| B013X | 260,424 | 1993-04-16 | 2026-08-05 |
| B605X | 177,226 | 2005-04-12 | 2026-08-05 |
| B691Y | 125,343 | 2011-04-19 | 2026-08-05 |

### Quality flags in prod_data

| Station | Non-zero quality records |
|---------|-------------------------|
| STM03 | 51,336 |
| STM04 | 0 |
| STM05 | 16,914 |
| STM06 | 0 |
| STM07 | 0 |
| STM08 | 0 |
| STM01 | 0 |
| STM02 | 1 |
| B013X | 582 |
| B605X | 584 |
| B691Y | 595 |

### Remaining open issues

- [ ] STM03 has 51,336 records with `quality != 0` — most are in the extension period. The extension section of the EDA (3.1) still flags these as "unvalidated extension" in plots with red shading.
- [ ] DISCHARGE/VOLUME/LOAD will be derived from HEIGHT_m via rating curves (user's next step).
- [ ] Quality flag meanings (0/1/...) still undocumented. Flags are counted but not preserved in clean CSVs.
- [x] ~~`clean_STM02.py` still has the tipping-bucket formula issue (73 cells with `=0.2*N`)~~ → **Fixed in Iteration 4.**

*End of Iteration 2.*


---

## Iteration 1 — 2026-08-05

### What was done

| Task | Details |
|------|---------|
| **Environment setup** | Created `.venv` with Python 3.14. Added packages: pandas 3.0.5, numpy 2.5.1, matplotlib 3.11.1, scipy 1.18.0, seaborn, pyarrow, jupyter, nbclient 0.11.0, ipykernel, openpyxl. See `requirements.txt`. |
| **EDA notebook** | Created `notebooks/01_eda.ipynb` — 8 sections, 29 cells (22 code + 7 markdown), all executed without errors. |
| **Figures generated** | 14 figures saved to `results/figures/eda/` (see below). |
| **Plan update** | `docs/plan_TFM.md` Fase 1 checkboxes ticked. Advisor feedback from `docs/advisor_feedback.md` integrated: quality flags, event definition, 4 required tables, ARIMA/SARIMAX, hybrid model, evaluation metrics, new bibliography, RiscBal group reference. |

### Notebook sections (`01_eda.ipynb`)

| # | Section | What it does |
|---|---------|-------------|
| 1 | Station inventory | Parses 11 metadata files + sensor registry; produces station table + map (`station_map.png`) |
| 2 | Data loading & integrity | Loads all 11 CSVs; detects invalid timestamps (4 in STM03), duplicates (1712 in STM03, 674 in STM05, 441 in STM01), recovers 73 Excel tipping-bucket formulas in STM02 `PRECIP_mm` |
| 3 | Missing-data analysis | Null rates per station/variable (STM03: 43% `LOAD_kg`, STM02: 29% `TEMP_C`); monthly heatmap; STM08 gap analysis (31 NaN runs); intermittency stats (STM08: 85% zero discharge); **physical-plausibility screening** (see key findings) |
| 4 | Full time-series visualization | Water level (HYDRO), daily precipitation (METEO + AEMET), temperature, STM08 overview + rating curve (`hydro_height_full.png`, `meteo_precip_daily.png`, `meteo_temp_full.png`, `stm08_overview.png`, `stm08_rating_curve.png`) |
| 5 | Lagged cross-correlation | Hydro-hydro on 10-min grid (lags −2h to +72h); precip-level at 1h resolution. **STM04 is best predictor** (r=0.908, lag≈30min); STM06 next (r=0.887, lag≈1h) (`ccf_hydro_vs_stm08.png`, `ccf_precip_vs_stm08.png`) |
| 6 | Flood event identification | Literature-based rule (quasi-peak-over-threshold on discharge); ~30 events detected in validated window; top-5 events characterized; **events overlapping gaps are flagged** (`events_summary.png`, `events_top5.png`). Identified events exported to `data/processed/events_stm08.csv`. |
| 7 | Seasonality | Monthly climatology: precip peaks Sep–Nov; STM08 level peaks Nov–Dec; dry summer (Jun–Aug) (`seasonality.png`) |
| 8 | Summary | Key findings auto-generated; action items for Phase 2 |

### Figures in `results/figures/eda/`

```
station_map.png           — Station network map (hydro/metéo/AEMET color-coded)
null_rate_heatmap_height.png — Monthly null-rate heatmap for HEIGHT_m
stm08_gap_distribution.png   — STM08 gap-length histogram (log-log)
stm08_overview.png        — STM08: HEIGHT, DISCHARGE, VOLUME, LOAD (full series)
stm08_rating_curve.png    — STM08 rating curve (HEIGHT vs DISCHARGE, color=year)
extension_raw_levels.png  — Raw DB-extension HEIGHT_m vs plausible band [-0.5, 5] m
hydro_height_full.png     — Plausibility-screened water level (6 hydro stations)
meteo_precip_daily.png    — Daily precipitation sums (all meteo/AEMET stations)
meteo_temp_full.png       — Air temperature (STM01, STM02)
ccf_hydro_vs_stm08.png    — Cross-correlation: hydro level vs STM08
ccf_precip_vs_stm08.png   — Cross-correlation: precipitation vs STM08
events_summary.png        — Flood events: H/Q time series + event markers
events_top5.png           — Top-5 events: zoomed hydrographs
seasonality.png           — Monthly climatology (precip, level, temperature)
```

### Key findings

1. **DB extension is unvalidated**: 2025–2026 data has non-physical artifacts (spikes up to 177 m, negative plateaus, daily sawtooth oscillations). 100% of out-of-range values are in 2025–2026. Quantitative analyses in the EDA restricted to validated window **2014-09-26 → 2025-07-22**.

2. **STM02 Excel formulas**: 73 cells of `PRECIP_mm` contain raw `=0.2*N` formulas (tipping-bucket counts). Recovered in the notebook loader, but the upstream cleaning script (`clean_STM02.py`) needs to be fixed.

3. **Quality flags not preserved**: The clean CSVs do not include `quality` column. Flags were counted but not exported (STM03 ≈ 45 k non-zero, STM05 ≈ 3 k). **Advisor requires flags to be preserved and documented.**

4. **STM08 is highly intermittent**: 85% of valid discharge is zero; 79% of level ≤ 0.01 m. The peak event (Dec 2016) reached 2.83 m.

5. **Best predictors of STM08**: STM04 (r=0.908, lag≈30 min) and STM06 (r=0.887, lag≈1 h) show strongest linear correlation. This provides a first estimate of basin concentration time.

6. **~30 flood events detected** (preliminary) in the validated window. Events spanning data gaps are flagged — the definitive count must come from Phase 2 on the consolidated 10-min grid.

### Configuration & parameters

- **Analysis windows**: Full common 2014-09-26 → 2026-07-02; validated-hist 2014-09-26 → 2025-07-22
- **Plausibility screening**: HEIGHT_m ∈ [−0.5, 5.0] m; DISCHARGE_m3s ∈ [0, 200] m³/s
- **Cross-correlation**: 10-min grid (hydro), 1-h resolution (precip), lags up to +72 h
- **Flood detection**: literature-based quasi-POT on discharge
- **Station groups**: HYDRO=[STM03…STM08], METEO=[STM01,STM02], AEMET=[B013X,B605X,B691Y]

### Open issues (carry to Phase 2)

- [ ] Fix `clean_STM02.py` to recover tipping-bucket formulas upstream
- [ ] Clarify quality flag meanings (0/1/...) and treatment policy (advisor requirement)
- [ ] Harmonize DB extension datums/units (coordinate with data provider)
- [ ] Preserve quality flags in clean CSVs
- [ ] Define reproducible event start/end criteria and count events on the 10-min grid
- [ ] Build the 4 required tables: stations, measurements, events, training
- [ ] Decide precipitation disaggregation method (hourly → 10 min) with justification
- [ ] Confirm basin topology: which stations are upstream of STM08 (Fase 0 checkbox)

### Files modified/created

| File | Action |
|------|--------|
| `.venv/` | Created (Python 3.14 + all deps from `requirements.txt`) |
| `requirements.txt` | Updated with all dependencies |
| `notebooks/01_eda.ipynb` | Created (8 sections, 22 executed code cells) |
| `docs/plan_TFM.md` | Fase 1 ticked; advisor feedback integrated; action items added |
| `docs/CHANGELOG.md` | Created (this file) |
| `results/figures/eda/` | 14 figures saved |
| `data/processed/events_stm08.csv` | Generated (event identification output) |

---

*End of Iteration 1.*
