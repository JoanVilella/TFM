# TFM Plan — Water Level Prediction at STM08 (Sa Marjal)

## Objective

This TFM has **three complementary objectives**:

1. **Physical model (HEC-HMS)**: Build a physically-based hydrological model of the Sant Miquel basin using **HEC-HMS** software (Hydrologic Engineering Center – Hydrologic Modeling System), calibrated and validated against observed series at stations STM03–STM08.
2. **Data-driven models (ML/AI)**: Develop machine learning and artificial intelligence models to predict **water level** (`HEIGHT_m`) at hydrological station **STM08 - Sa Marjal** at prediction horizons of **t+1h, t+6h and t+24h**, using time series from the remaining available meteorological and hydrological stations as predictors.
3. **Comparison**: Evaluate and compare the performance of both model families (physical vs. data-driven) under standard hydrological metrics (NSE, KGE, RMSE, PBIAS), broken down by prediction horizon and event type (flood/low-flow), analyzing their advantages, limitations, and application contexts.

### Research questions

- **RQ1**: How accurately does a calibrated physical model (HEC-HMS) reproduce observed levels and flood events at STM08?
- **RQ2**: To what extent do data-driven models (baselines → RF/XGBoost → LSTM/GRU → TFT) improve that accuracy, particularly for flood peaks and at t+1h, t+6h and t+24h horizons?
- **RQ3**: How do preprocessing decisions (temporal resolution, lags, intermittency treatment) affect performance, and which predictors dominate the prediction?

> **Context and novelty**: The comparative HEC-HMS vs. ML literature predominantly uses daily data and perennial basins. This TFM studies a **Mediterranean torrential basin** with intermittent regime (largely zero series and flash floods), **sub-hourly** data from a dense station network, and with the objective of **water level in a wetland** (Sa Marjal, adjacent to s'Albufera).

---

## 1. Data inventory

### 1.1 Target station

| Station | Name | Type | Target variable | Period | Frequency |
|---|---|---|---|---|---|
| STM08 | Sa Marjal | Hydrological | `HEIGHT_m` / `DISCHARGE_m3s` | 2013-03-04 → 2026-07-15 | 15 min (→ 10 min from 2022-05-05; → 5 min from 2026-02-17) |

> **Note on the target variable**: Clean CSVs export `HEIGHT_m`, `DISCHARGE_m3s`, `VOLUME_m3` and `LOAD_kg`. For the extended period (2026-02-17 → 2026-07-15), sourced from the internal DB, **only `HEIGHT_m` is available**; `DISCHARGE_m3s`, `VOLUME_m3` and `LOAD_kg` are empty. `HEIGHT_m` is the variable to use as target (directly measured water level); `DISCHARGE_m3s` is a monotonic transformation via rating curve and may be used as a complement in the historical period.

### 1.2 Predictor stations

#### Hydrological (HEIGHT_m / DISCHARGE_m3s / VOLUME_m3 / LOAD_kg)

| Station | Name | T0 | T_end | Frequency |
|---|---|---|---|---|
| STM03 | Es Fangar | 2012-10-01 | 2026-07-15 | 15 min → 10 min (2022) → 5 min (2025-07-23+) |
| STM04 | Gabelli | 2012-12-06 | 2026-07-15 | 15 min → 10 min (2022) → 5 min (2025-09-18+) |
| STM05 | Monnàber | 2012-10-01 | 2026-07-15 | 15 min → 10 min (2022) → 5 min (2025-09-18+) |
| STM06 | Sant Miquel | 2012-10-01 | 2026-07-15 | 15 min → 10 min (2022) → 5 min (2025-09-18+) |
| STM07 | Búger | 2012-10-01 | 2026-07-15 | 15 min → 10 min (2022) → 5 min (2026-02-20+) |

> **DB extension note**: The extended segment from the internal DB only contains `HEIGHT_m` (water level); `DISCHARGE_m3s`, `VOLUME_m3` and `LOAD_kg` are empty. STM03 has ~45 k records with `quality != 0` in the extended segment; STM05 has ~3 k.

#### STM Meteorological (PRECIP_mm, TEMP_C)

| Station | Name | T0 | T_end | Frequency |
|---|---|---|---|---|
| STM01 | Coll des Telègraf | 2012-11-30 | 2026-07-15 | 15 min → 10 min (2022) |
| STM02 | Míner Gran | 2014-09-26 | 2026-07-15 | 15 min → 10 min (2022) |

#### AEMET Meteorological (PRECIP_mm, hourly)

| Station | Name | T0 | T_end | Frequency |
|---|---|---|---|---|
| B013X | Lluc | 1993-04-16 | 2026-07-02 | 60 min |
| B605X | Muro-S'albufera | 2005-04-12 | 2026-07-02 | 60 min |
| B691Y | Sa Pobla-Sa Canova | 2011-04-19 | 2026-07-02 | 60 min |

> **Sources**: up to 2023-01-01 from UIB-Estrany (phor format, tenths of mm → mm) — **RiscBal** research group (https://www.uib.eu/research/structures/structure/RiscBal/); from 2023-01-01 onward extended with internal DB data (`Rain60m`, already in mm). ~582–584 records with `quality != 0` per station were detected in the DB segment (included in CSV, pending review on whether they should be filtered).

---

## 2. Common time window

After extending the STM03–STM08 series with internal DB data, the intersection of all datasets is:

```
Start:  2014-09-26  (STM02 starts in Sept-2014)
End:    2026-07-02  (AEMET limit; remaining stations reach 2026-07-15)
```

This yields **~12 years** of overlapping data with all sources active. All STM series (hydrological and meteorological) now reach **2026-07-15**; AEMET series reach **2026-07-02**.

> **Note**: In the extended segment of hydrological stations (from ~2025-07 / 2026-02 depending on station), only `HEIGHT_m` is available; `DISCHARGE_m3s`, `VOLUME_m3` and `LOAD_kg` are empty.

---

## 3. Main challenges

1. **Mixed frequencies**: 5 min / 10 min / 15 min (STM depending on period) vs 60 min (AEMET). A common **10-min** grid is adopted. Precise terminology (non-interchangeable): *aggregating*, *resampling*, *downsampling* and *disaggregating*. Hourly precipitation **must not** be naively divided by 6 to generate 10-min data (assumes uniform distribution and may distort flash-flood events). The specific disaggregation method must be justified.
2. **Missing data**: Some stations have thousands of null cells (e.g., STM03 has >130 k nulls in `LOAD_kg`). `LOAD_kg` is the variable with most nulls; the extended segment has only `HEIGHT_m`.
3. **Extended-segment heterogeneity**: From ~2025-07/2026-02 only `HEIGHT_m` is available (no discharge or volume); the train/val/test split must account for this.
4. **Temporal leakage**: In time series, a strict chronological split is critical.
5. **Sporadic flood events**: Discharge is zero most of the time; the model must capture peaks well.
6. **Quality != 0 in DB**: STM03 (~45 k records) and STM05 (~3 k records) have unvalidated-quality data in the extended segment; review whether to filter.
7. **Hydrological event definition**: Must be defined objectively and reproducibly (start/end thresholds, stabilization criterion). A single event **cannot be split across train and test** (leakage). EDA identification is preliminary; the definitive one will be done in Phase 2 on the consolidated grid.
8. **Quality flags (advisor requirement)**: ✅ Resolved (Iteration 5). Quality flags documented (0=good, 1=suspicious, 2=wrong) and preserved as `QUALITY` column in all clean CSVs. `DATA_TYPE` column ("observed") also added for future use (corrected/imputed/simulated). Excel-origin data has empty quality (no flag available).

---

## 4. Work plan

### Phase 0 — Review and preliminary decisions

- [x] ~~Decide target variable~~: `HEIGHT_m` is the target variable (water level, available throughout the entire period including the extended segment). `DISCHARGE_m3s` complementary for the historical period.
- [x] ~~Decide whether to include AEMET stations~~ — AEMET series extended to 2026-07-02 with DB data; all included.
- [x] ~~Data for HEC-HMS~~ — DEM, land-use and soil-type cartography **available**; the physical model is a full pillar of the TFM.
- [x] ~~Prediction horizon~~ — **Multi-horizon: t+1h, t+6h and t+24h** (multi-step architectures: LSTM/GRU encoder-decoder and TFT).
- [x] ~~Hybrid model (ML correcting HEC-HMS)~~ — Discarded as own contribution; kept as future work. The TFM is a strict physical vs. data-driven comparison.
- [x] ~~Thesis language~~ — English.
- [ ] Confirm basin topology: which stations are upstream of STM08 and what is the approximate concentration time (important for defining prediction horizon and lags). **Pending: geo team needs to confirm whether STM03–07 are parallel tributaries or if some are in series. Currently `UPSTREAM_Q` sums all five assuming parallel configuration.**

### Phase 1 — Exploratory Data Analysis (EDA)

**Objective**: Understand data quality and structure before modeling.

- [x] Load all CSVs and compute null rates per station and variable.
- [x] Visualize full time series for each station.
- [x] Compute lagged cross-correlation between each predictor and STM08 to identify:
  - Which stations best explain STM08 water level.
  - The optimal lag (concentration time).
- [x] Identify and characterize historical flood events.
- [x] Analyze seasonality (winter vs. summer in Mediterranean climate).

**Deliverable**: Notebook `01_eda.ipynb` ✅ Completed (2026-08-05). 8 sections, 14 figures in `results/figures/eda/`.

> **Key EDA findings**: (1) The DB extension (2025–2026) contains **unvalidated** data with spikes up to 177 m, negative plateaus and non-physical daily oscillations → quantitative analyses restricted to the validated historical window (2014-09-26 → 2025-07-22). (2) 73 Excel tipping-bucket formula cells recovered in STM02 (`PRECIP_mm`). (3) Cross-correlations show STM04 (r=0.908, lag ≈ 30 min) and STM06 (r=0.887, lag ≈ 1 h) as the best linear predictors of STM08. (4) STM08 has 85% zero discharge — highly intermittent regime. (5) EDA identified preliminary events with a reproducible literature-based rule, but events overlapping data gaps may be fragmented; definitive identification must be done in Phase 2 on the consolidated 10-min grid.

### 4b. Required tables (*advisor feedback*)

The advisor requests four tables as minimum deliverables before any modeling:

| Table | Key columns |
|---|---|
| **Stations** | ID, sensor type, measured variable, location, altitude, sampling frequency, relative position to STM08 |
| **Measurements** | datetime, station, precipitation, level, temperature, quality flag, data type (observed/corrected/imputed/simulated) |
| **Events** | event ID, start/end datetime, accumulated precipitation, maximum intensity, maximum level at STM08, time to peak, duration |
| **Training** | one row per timestamp, with current + past observations, plus target columns: `level_STM08_30min`, `level_STM08_60min`, `level_STM08_120min` |

A table assigning each **event** (not each row) to **train / validation / test** is also required.

### Phase 2 — Preprocessing and dataset construction

**Objective**: Produce a modeling-ready DataFrame.

- [x] **Resampling**: Build the dataset on a **uniform 10-min grid**: temporal disaggregation of hourly AEMET series (60 → 10 min), downsampling of STM historical 15-min period, and aggregation of recent 5-min records. Precipitation treated as cumulative; level and temperature as instantaneous states. [Done — Iteration 6: template-based disaggregation for AEMET, cumulative-curve interpolation for STM precip, linear interpolation for instantaneous variables. See `scripts/preprocessing/resample.py`.]
- [x] **Temporal alignment**: Index by common `TIMESTAMP UTC`, fill index gaps. [Done — Iteration 6-7: 10-min grid built and augmented with DISCHARGE from rating curves. See `scripts/preprocessing/resample.py` and `rating_curve.py`.]
- [ ] **Null imputation**:
  - Short gaps (< 3 h): linear interpolation.
  - Long gaps: flag or exclude from training.
- [x] **Feature engineering**:
  - Lags of each predictor: *t-1h, t-2h, t-3h, t-6h, t-12h, t-24h*. [Done — Iteration 8]
  - Cumulative precipitation: last 3 h, 6 h, 12 h, 24 h, 48 h (antecedent precipitation index). [Done — Iteration 8]
  - Cumulative upstream discharge (sum of STM03–STM07 at t-lag). [Done — Iteration 8: `UPSTREAM_Q` assumes parallel tributaries; pending basin topology confirmation from geo team]
  - Temporal variables: hour of day, month, day of year (sin/cos encoding for hour and doy, raw for month). [Done — Iteration 8]
- [x] **Chronological split**:
  - Train: up to 2020-12-31 [Done — Iteration 9: 324,594 rows, 57.6%]
  - Validation: 2021-01-01 → 2022-06-30 [Done — Iteration 9: 78,576 rows, 13.9%]
  - Test: 2022-07-01 → end of window [Done — Iteration 9: 160,528 rows, 28.5%]

**Deliverable**: `02_preprocessing.ipynb` + `data/processed/dataset_10min.parquet`

### Phase 3 — Physical model with HEC-HMS

**Objective**: Build a physically-based hydrological model of the Sant Miquel basin calibrated with observed data.

- [ ] **Basin delineation**: Obtain the DEM (Digital Elevation Model) for the area and delineate the watershed and sub-basins draining toward STM08.
- [ ] **HEC-HMS model setup**:
  - Define morphometric parameters for each sub-basin (area, slope, channel length).
  - Select rainfall-runoff transformation methods (e.g., SCS Curve Number) and flood routing methods (e.g., Muskingum).
  - Assign precipitation series from stations STM01, STM02 and AEMET as forcing input.
- [ ] **Calibration and validation**:
  - Calibrate model parameters (CN, Manning, concentration times) against observed discharge at STM06 / STM08 using automatic optimization (e.g., DCEA algorithm built into HEC-HMS).
  - Validate with independent flood events from the calibration period.
- [ ] **Uncertainty analysis**: Identify the most sensitive parameters and their variation ranges.

**Deliverable**: Calibrated HEC-HMS project (`hec_hms/`) + results analysis notebook `03_hec_hms.ipynb`

### Phase 4 — Baseline models

**Objective**: Establish lower-bound performance baselines.

- [ ] **Persistence**: `y_pred(t) = y(t-1)` — trivial baseline (mandatory as minimum reference).
- [ ] **Linear regression** with selected lags.
- [ ] **ARIMA / SARIMAX**: ARIMA uses only level history; ARIMAX adds exogenous variables (precipitation, upstream levels).
- [ ] **Random Forest / Gradient Boosting (XGBoost/LightGBM)**: robust, interpretable, handle nulls well.

**Metrics** (standard in hydrology):
- NSE (*Nash-Sutcliffe Efficiency*) — primary metric.
- KGE (*Kling-Gupta Efficiency*).
- RMSE and MAE.
- PBIAS (volumetric bias).
- **Peak error** (magnitude) and **peak timing error**.
- **Threshold exceedance detection** and **false alarm rate**.
- **Lead time / effective flood anticipation**.
- **Per-event evaluation** (not just aggregate).

**Deliverable**: `04_baselines.ipynb`

### Phase 5 — Sequential models

**Objective**: Capture long-range temporal dependencies and produce **multi-horizon predictions (t+1h, t+6h, t+24h)**.

- [ ] **LSTM / GRU**: encoder-decoder architecture for multi-step prediction (simultaneous output at t+1/6/24h).
- [ ] **Temporal Fusion Transformer (TFT)**: state of the art in multivariate time series, handles known covariates (meteo) and past inputs (hydro); natively multi-horizon.
- [ ] Hyperparameter tuning with *Optuna* or *Ray Tune*.
- [ ] Evaluation broken down by prediction horizon (quantify metric degradation as horizon increases).

**Deliverable**: `05_deep_learning.ipynb`

### Phase 5b — Hybrid model (HEC-HMS + ML)

**Objective**: Use ML to correct physical model errors.

- [ ] Train an ML model (XGBoost or similar) that takes HEC-HMS outputs as features and learns to predict the residual (difference between observed and HEC-HMS-simulated level).
- [ ] Evaluate whether the hybrid correction improves physical-model-only metrics.

**Deliverable**: Notebook `05b_hybrid.ipynb` (optional, if time permits).

### Phase 6 — Interpretability and results analysis

- [ ] Feature importance (SHAP values) to understand which predictors dominate.
- [ ] Error analysis: does the model fail more during floods or low-flow periods?
- [ ] Error curves by discharge threshold.
- [ ] Prediction vs. observation comparison for selected events.

**Deliverable**: `06_interpretability.ipynb`

### Phase 7 — HEC-HMS vs. ML/AI comparison

**Objective**: Confront the physical model with data-driven models on the same events and periods.

- [ ] Evaluate both families with common metrics (NSE, KGE, RMSE, MAE, PBIAS) on train/val/test, broken down by prediction horizon (t+1/6/24h) for ML models.
- [ ] Analysis by event type: floods, low-flows and ordinary conditions.
- [ ] Discuss data requirements of each approach (input data, calibration effort, transferability).
- [ ] Identify scenarios where the physical model outperforms data-driven ones and vice versa.

**Deliverable**: `07_comparison.ipynb`

### Phase 8 — Thesis writing

- [ ] Introduction and hydrological context of the Sant Miquel basin.
- [ ] Description of the HEC-HMS physical model: methodology, calibration and results.
- [ ] Description of data and preprocessing for ML/AI models.
- [ ] Results and comparison between physical and data-driven models.
- [ ] Discussion: advantages, limitations and usage recommendations for each approach.
- [ ] Conclusions.

---

## 5. Proposed tech stack

| Category | Tool |
|---|---|
| Data manipulation | `pandas`, `polars` (optional for speed) |
| Visualization | `matplotlib`, `seaborn`, `plotly` |
| Physical model | **HEC-HMS** (USACE) |
| GIS / DEM | QGIS or ArcGIS + HEC-GeoHMS for basin delineation |
| Classic ML | `scikit-learn`, `xgboost`, `lightgbm` |
| Deep Learning | `PyTorch` + `pytorch-forecasting` (TFT) |
| Hyperparameters | `optuna` |
| Hydrological metrics | `hydroeval` or custom implementation |
| Environment | Jupyter Notebooks, Python ≥ 3.10 |

---

## 6. Open questions / pending from Fran

### HEC-HMS specific

- ~~Is a high-resolution DEM (LiDAR or similar) available for the Sant Miquel basin?~~ — **Resolved: available.**
- ~~Is land-use and soil-type cartography available for computing CN (Curve Number)?~~ — **Resolved: available.**
- Are peak discharge measurements from historical events available for model calibration?
- Do the upstream stations (STM03–STM07) act as internal checkpoints within the basin?

### General

- Rating curves for STM08: are they calibrated for the entire period or do they change over time?
- Confirmation of basin topology: do all STM stations drain toward Sa Marjal?
- STM09, STM10, STM11 (mentioned in the logbook): are they available? They could add information.
- ~~Desired prediction horizon: nowcasting (t+1h) or forecasting at t+6h, t+24h?~~ — **Resolved: multi-horizon t+1h, t+6h and t+24h.**

---

## 7. Key references (state of the art)

- Kratzert, F., et al. (2018). *Rainfall–runoff modelling using Long Short-Term Memory (LSTM) networks*. Hydrol. Earth Syst. Sci., 22, 6005–6022. — LSTM outperforms the conceptual SAC-SMA model across 241 basins (CAMELS).
- Lim, B., et al. (2021). *Temporal Fusion Transformers for interpretable multi-horizon time series forecasting*. International Journal of Forecasting. — TFT architecture: natively multi-horizon and interpretable.
- Marasini, U. & Pokhrel, M. (2024). *Comparative analysis of rainfall-runoff simulation using an LSTM deep learning model and HEC-HMS: mountainous basin of Nepal*. Discover Civil Engineering. — LSTM > HEC-HMS in a mountainous basin.
- Manjitha, H.H.U. & Perera, D. (2025). *HEC-HMS and machine learning approaches for streamflow forecasting: a comparative study* (Sri Lanka). — LSTM wins in both wet and dry basins; HEC-HMS drops to NSE 0.49 in dry regime.
- Belina, Y., et al. (2024). *Comparative analysis of HEC-HMS and machine learning models for rainfall-runoff prediction in the upper Baro watershed, Ethiopia*. Hydrology Research. — ANN NSE 0.98 vs HEC-HMS 0.85 in a data-scarce basin.
- Khan, I. (2026). *Comparative Analysis of HEC-HMS and Temporal Fusion Transformer for Streamflow Prediction under Climate Change Scenarios (Swat River Basin)*. — HEC-HMS underestimates flood peaks; TFT captures extreme events.
- Cho, M., et al. (2022). *Water Level Prediction Model Applying an LSTM–GRU Method for Flood Prediction*. Water, 14(14). — NSE 0.94 predicting water level.
- Frame, J. M., et al. (2022). *Deep learning rainfall–runoff predictions of extreme events*. Hydrol. Earth Syst. Sci., 26, 3377–3392. — LSTM behavior during extreme events.
- Xiang, Z. & Demir, I. (2020). *Distributed long-term hourly streamflow predictions using deep learning*. Environmental Modelling & Software, 131, 104788. — LSTM seq2seq for rainfall–runoff.
- Koya, S. R. & Roy, T. (2024). *Temporal Fusion Transformer for streamflow prediction*. Journal of Hydrology, 631, 130694. — TFT vs. LSTM/Transformers.
- Fordjour, A. & Kalyanapu, A. (2024). *GRU-based flood prediction using multi-station water levels*. Water, 16(7), 993.
- Agaj, T., et al. (2024). *ARIMA/ETS for water level forecasting*. Water Practice & Technology, 19(3), 925–938.
- Szczepanek, R. (2022). *XGBoost/LightGBM/CatBoost for daily streamflow forecasting*. Applied Sciences, 12(14), 7045.
- USACE HEC-HMS case study — *Kaskaskia basin flood forecasting*.
- USACE HEC-HMS Applications Guide (official documentation).
- Future work (hybrids): Makhloufi, N. (2026) — XGBoost as HEC-HMS error corrector (KGE 0.65 → 0.83); Solanki, H., et al. (2025, Water Resources Research) — ML post-processing of hydrological models.

---

## 8. Action items (next steps)

### Immediate (before modeling)
- [x] EDA completed (`01_eda.ipynb`).
- [x] Clarify and document the meaning of **quality flags** and their treatment policy. [Done — Iteration 5: 0=good, 1=suspicious, 2=wrong; documented in metadata and CSV columns]
- [x] Define the **event detection rule** (start/end criteria) in a reproducible manner. [Done — Iteration 10: POT-based detection, Q > 0.2 m³/s trigger, 196 events across ~11 years. See `scripts/preprocessing/event_detection.py`.]
- [ ] Build the **4 tables required** by the advisor: stations, measurements, events, training.
- [x] Generate the **event** (not row) assignment table to train / validation / test. [Done — Iteration 10: events.csv includes `split` column based on peak timestamp]
- [x] Count and evaluate the number of **usable flood events** in the historical record (~12 years, highly intermittent regime — TFT needs enough events to train). [Done — Iteration 10: 196 events detected (100 train, 16 val, 80 test)]

### Phase 2 (preprocessing)
- [x] Recover and preserve **quality flags** in clean CSVs (currently not included). [Done — Iteration 5: QUALITY and DATA_TYPE columns added to all 11 CSVs]
- [x] Fix `clean_STM02.py` script to recover Excel tipping-bucket formulas in `PRECIP_mm`. [Already done — Iteration 4]
- [x] Derive DISCHARGE_m3s from HEIGHT_m via rating curves. [Done — Iteration 7: `scripts/preprocessing/rating_curve.py`]
- [ ] Implement `flow_to_meters` inverse rating curve (Q→H) — needed for HEC-HMS validation.
- [ ] Harmonize DB extension units/datums (177 m spikes, negative plateaus, oscillations) — coordinate with data provider.

### Documentation
- [x] Reference the group as **RiscBal** (https://www.uib.eu/research/structures/structure/RiscBal/) in the thesis. [Done — Iteration 6: all references updated in `thesis/document.tex`]
