# CHANGELOG — Project Diary

> Quick-reference log of what has been done, decisions made, and open issues.
> Each iteration appends a new entry at the top. Scan this before doing any work.

---

## Iteration 23 — 2026-08-25

### Changes made

**Diurnal-drift normalization + micro-event policy + Phase 4 completion
(XGBoost, ARIMA/SARIMAX)**

### 1. Layer 4 — diurnal drift correction (`harmonize_extension.py`)

The DB-only segments of several stations carry a spurious daily water-level
oscillation (pressure-transducer thermal drift; peaks ~13:00, absent from the
Excel-era record — evaporation would *lower* levels at midday). A uniform
procedure is now applied to every hydro station:

> `drift(h) = clim_ext(h) − clim_hist(h)` (hour-of-day climatologies of quiet
> rows, H < 0.10 m; historical reference restricted to the same calendar
> months), centred to zero mean and subtracted from DB-only rows when the
> drift range ≥ **5 mm** AND ext/hist diurnal-range ratio ≥ **5**. Corrected
> rows tagged `DATA_TYPE = "corrected"`.

| Station | Ext diurnal range | Hist range | Ratio | Action |
|---------|------------------|-----------|-------|--------|
| STM03 | 10.5 mm | 4.7 mm | 2.2× | Not applied (natural cycle preserved) |
| STM04 | 5.0 mm | 0.5 mm | 10.4× | **Corrected** |
| STM05 | 10.6 mm | 1.1 mm | 10.1× | **Corrected** |
| STM06 | 1.6 mm | 0.4 mm | 4.2× | Not applied |
| STM07 | 26.1 mm | 0.8 mm | 32.2× | **Corrected** |
| STM08 | 32.9 mm | 1.2 mm | 26.7× | **Corrected** |

STM08's DB-only hour-of-day range drops 27.8 mm → 5.2 mm; baseline level back
to ~2.3 cm with max 0.20 m (real event).

### 2. Micro-event policy — global minimum peak level

`detect_events(min_peak_h=0.10)`: events with STM08 peak water level below
0.10 m are discarded (global criterion, all data treated equally) and events
renumbered. With layer 4 removing the artifact source, 384 raw detections
shrink to **175 valid events** (train 102 / validation 16 / test 57);
209 sub-0.10 m pulses discarded.

### 3. Phase 4 completed — XGBoost + ARIMA/SARIMAX

| File | Change |
|------|--------|
| `scripts/evaluation/baselines.py` | Trees now **NaN-native** (no imputation; plan gap-handling): RF switched from the median-imputed path, new `fit_xgboost` (300 trees, hist). Ridge stays median-imputed. |
| `scripts/evaluation/arima.py` | New: univariate SARIMAX + Fourier daily cycle ("dynamic harmonic regression"; a 144-period seasonal state-space component was rejected — its 146-state Kalman filter is computationally impractical), spec chosen by AIC ((2,1,1): −48 533 vs (1,1,1): −48 449 on the 2-year tail), **daily rolling origins** via `SARIMAXResults.apply`, per-row forecasts for t+6/36/144. `fit_arimax` adds a curated exog set (STM04/06/07 levels ±6 h lag, 6 h precip cumsums; median-imputed on train). |
| `scripts/evaluation/run_baselines.py` | Six models × three horizons. |
| `requirements.txt` | + `statsmodels>=0.14` |
| `notebooks/04_baselines.ipynb` | Extended to six models; prediction cache shared across cells; validated/extension breakdown and figure updated. |

### Results — test NSE (full / validated / extension)

| model | t+1h | t+6h | t+24h |
|-------|------|------|-------|
| persistence | 0.988 / 0.990 / 0.979 | 0.913 / 0.915 / 0.900 | **0.563** / 0.536 / 0.707 |
| ridge | 0.987 / 0.989 / 0.977 | 0.876 / 0.871 / 0.900 | 0.472 / 0.427 / 0.712 |
| random_forest | 0.982 / 0.984 / 0.973 | 0.761 / 0.753 / 0.802 | 0.292 / 0.301 / 0.241 |
| xgboost | 0.972 / 0.973 / 0.964 | 0.721 / 0.694 / 0.866 | 0.091 / 0.017 / 0.486 |
| arima | 0.856 / 0.852 / 0.874 | 0.777 / 0.764 / 0.845 | 0.455 / 0.417 / 0.653 |
| **arimax** | 0.855 / 0.852 / 0.874 | 0.776 / 0.763 / 0.846 | 0.454 / 0.417 / 0.654 |

Median per-event NSE (57 test events): persistence best at t+1h (0.18);
ARIMAX is not better than ARIMA after future-exogenous leakage is removed
(t+6h −0.73; t+24h −2.51).

### Key findings

1. **No learned model beats persistence in aggregate** — persistence remains
   the strongest reference at all three horizons (test NSE 0.988/0.913/0.563).
2. **Ridge is the strongest non-persistence model by aggregate NSE**
   (0.987/0.876/0.472). ARIMAX is effectively identical to ARIMA when future
   exogenous observations are not leaked into the forecast.
3. Trees degrade sharply with horizon (RF/XGB PBIAS > 60 % at t+24h) despite
   near-perfect training fit — overfitting to the intermittent base state;
   motivates sequence models (Phase 5) rather than more tree tuning.

### Remaining open issues

- [ ] Phase 5 — LSTM/GRU/TFT sequential models
- [ ] Phase 3 — HEC-HMS basin delineation/calibration
- [ ] RF/XGB hyperparameter tuning if trees are kept as Phase 5 baselines

*End of Iteration 23.*


---

## Iteration 22 — 2026-08-25

### Changes made

**CRITICAL FIX — DB extension `WaterLevel` was in centimetres, ingested as metres**

Root cause of the "extension datum shift" (Iteration 18 flag) and the
extension model collapse (Iteration 21): the internal DB (`prod_data`)
exports `WaterLevel` in **centimetres**, but `extend_STM_waterlevel.py`
wrote the raw values straight into the metres-based `HEIGHT_m` column.
Verified against the Excel source at identical timestamps (e.g. STM08
2025-08-28 12:20 flood: validated Excel = 0.3715 m, DB = 37.51 cm).

| File | Change |
|------|--------|
| `scripts/extension/extend_STM_waterlevel.py` | `WaterLevel` ÷100 → m on load; **quality = 2 rows dropped**; quality = 1 kept and counted per station; metadata notes updated (cm→m conversion + q1/q2 counts) |
| Clean CSVs STM03–STM08 | Regenerated from scratch (cleaning → extension → harmonization) to remove the previously appended cm-as-m rows |
| `notebooks/02_preprocessing.ipynb` | Column filters exclude `_DATA_TYPE` string columns from numeric summaries (2 cells) |
| `notebooks/03_harmonization_comparison.ipynb` | Fixed py3.10 f-string syntax errors (3 cells); refreshed before/after comparison table; replaced `to_markdown` (missing `tabulate`) with `to_string` |

### Harmonization after the fix

| Station | Retained (before fix) | Retained (after fix) |
|---------|----------------------|---------------------|
| STM03 | 40.9 % | **100.0 %** |
| STM04 | 77.6 % | **100.0 %** |
| STM05 | 22.3 % | **100.0 %** |
| STM06 | 63.8 % | **100.0 %** |
| STM07 | 61.6 % | **100.0 %** |
| STM08 | 81.1 % | **100.0 %** |

The old bounds filter [−0.5, 5] had been discarding the *real floods*
(any value > 5 cm) and keeping mis-scaled dry-period plateaus as "levels".

### q=1 (suspicious) audit

| Station | q=0 / q=1 ext rows | q=1 value range (m) | q-transition max \|dH\| | Verdict |
|---------|--------------------|--------------------|------------------------|---------|
| STM03 | 51,268 / 51,336 | −0.085 … 0.480 | 0.003 m | Keep (continuous) |
| STM05 | 65,536 / 6,888 | −0.500 … 1.008 | 0.035 m | Keep (continuous); note: q=0 ≈ 0 after Jun-2026 (q1-only tail) |
| STM04/06/07/08 | 100 % q=0 | — | — | — |

q=2: only STM05 WaterLevel had them (10,026 rows) — dropped.

### Pipeline re-run results

| Artifact | Before (broken units) | After (unit-corrected) |
|----------|----------------------|-----------------------|
| Extension harmonization retention | 58.2 % | 100.0 % |
| Events | 361 | **443** (train 192 / val 41 / test 210) |
| Extension events (post 2025-07-23) | 30 (incl. Q = 133–176 m³/s artefacts) | **112** (max Q 16.4 m³/s) |
| STM08 grid 2026 max H | 5.00 m (clipped artefact) | **1.19 m** (real Jan-2026 flood) |
| STM08 max Q overall | 176 m³/s (artefact) | **87.8 m³/s** (Jan-2017, unchanged historical max) |
| Training table | 289 cols × 614,201 rows | unchanged shape |
| Test NSE t+24h extension (ridge) | −3.95 | **+0.71** |
| Test NSE t+6h extension (ridge) | −1.93 | **+0.89** |

### ⚠️ New finding — diurnal sensor drift in the DB-only period

From 2026-02-17 (STM08 DB-only segment), a daily water-level oscillation
peaking ~13:00 (amplitude ±0.6 cm around a ~2.4 cm base) crosses the event
trigger daily, generating ~85 micro-events (#357–#443 tail, peak H
0.03–0.08 m). The Excel-era record shows no such diurnal cycle → classic
pressure-transducer thermal drift artifact in the DB-only data.

### Remaining open issues

- [ ] Decide policy for the diurnal micro-events (e.g. minimum peak-H
      criterion for event validity, or raise threshold) before per-event
      evaluation is used for model selection.
- [x] ~~Extension datum shift~~ — **Resolved (this iteration): unit bug,
      not datum shift.** Plan §3 #9 closed.
- [ ] XGBoost + ARIMA/SARIMAX (second baseline pass)
- [ ] Feature selection / subsample tuning for RF

*End of Iteration 22.*


---

## Iteration 21 — 2026-08-21

### Changes made

**Phase 4 — baseline models (persistence, ridge, random forest) + metrics module**

First modelling pass: three lower-bound baselines for STM08 water-level
forecasting, evaluated per horizon and split with a custom hydrological-metrics
module.

| File | Detail |
|------|--------|
| `scripts/evaluation/metrics.py` | NSE, KGE, RMSE, MAE, PBIAS + peak magnitude/timing error, threshold-exceedance (POD/FAR/CSI), and a per-event aggregation helper |
| `scripts/evaluation/baselines.py` | `persistence_predictions`, `fit_ridge` (median-imputed predictors + `_MISSING` masks), `fit_random_forest` (with a flood-preserving training subsample, default 60 k rows) |
| `scripts/evaluation/run_baselines.py` | CLI driver: runs the 3 models × 3 horizons × 3 splits, writes `results/metrics/` |
| `notebooks/04_baselines.ipynb` | Deliverable notebook (executed): summary + per-event metrics + validated-vs-extension test breakdown |
| `requirements.txt` | + `scikit-learn`, `xgboost` |

### Results — test NSE

The test split spans 2022-07 → 2026-07; the 2026 extension (12 % of test) is
datum-shifted, so test NSE is reported for the **validated** window
(pre-2025-07-22) separately from the extension:

| model | t+1h | t+6h | t+24h |
|-------|------|------|-------|
| persistence | 0.990 | 0.915 | 0.536 |
| ridge | 0.989 | 0.871 | 0.427 |
| random_forest | 0.980 | 0.834 | 0.354 |

*(validated test window)*

### Key findings

1. **Persistence is the strongest baseline** — classic for a highly intermittent
   regime (STM08 near 0 m most of the time). All models are close at t+1h and
   degrade with horizon; no model beats persistence at t+24h.
2. **The 2026 extension collapses every model** (ridge t+6h NSE −1.9, t+24h −4.0;
   RF 0.14–0.35) — direct evidence of the unresolved datum shift (Iteration 18).
   Until Phase C resolves it, the extension is excluded from meaningful
   evaluation.
3. Median per-event NSE is negative for all models — the intermittent flood
   peaks are where every baseline fails, reinforcing the need for the
   flood-aware metrics and later model families.

### Remaining open issues

- [ ] XGBoost + ARIMA/SARIMAX (second baseline pass)
- [ ] Extension datum shift (Phase C — still pending data-provider confirmation)
- [ ] Feature selection / subsample tuning for RF

*End of Iteration 21.*


---

## Iteration 20 — 2026-08-21

### Changes made

**Water temperature (`WATER_TEMP_C`) captured for hydro stations + wired as a predictor**

The hydro stations (STM03–STM08) record a water-temperature column in their
raw Excel files that was never extracted (only `HEIGHT_m` was). This iteration
adds water temperature to the whole pipeline, plus a DB export of water temp
for the extended timeline.

### Historical capture (cleaning scripts)

Each `clean_STM03–STM08.py` now also extracts `WATER_TEMP_C`. Water-temperature
column indices (0-based) differ per station:

| Station | HEIGHT | WATER_TEMP | DATE |
|---------|--------|------------|------|
| STM03 | 1 | 15 | 16 |
| STM04 | 1 | 13 | 14 |
| STM05 | 1 | 13 | 14 |
| STM06 | 1 | 13 | 14 |
| STM07 | 1 | 14 | 15 |
| STM08 | 1 | 13 | 14 |

Clean CSV header is now `TIMESTAMP, HEIGHT_m, WATER_TEMP_C, QUALITY, DATA_TYPE`.

Clean-CSV `WATER_TEMP_C` coverage (historical Excel data, before the extension):

| Station | Non-null |
|---------|----------|
| STM03 | 31.7 % |
| STM04 | 66.7 % |
| STM05 | 17.9 % |
| STM06 | 36.6 % |
| STM07 | 20.1 % |
| STM08 | 29.7 % |

> Note: an earlier raw-CSV proxy (~0 % for STM05/06/07) proved misleading —
> the Excel files do contain water temp for all stations.

### Extended timeline (DB export)

New water-temperature export from the internal DB (`WaterTemp` variable,
quality = 0 only) lives in `data/raw/watertemp_extended/{CODE}_Watertemp.csv`.
Only **STM03, STM05, STM08** have water temp in the extension period
(2025-07-23 → 2026-08-05); STM04/06/07 have none. STM03's export is ~53 %
`quality = 2` (wrong), which is discarded on load.

`extend_STM_waterlevel.py` now merges water level (`prod_data`) + water temp
(`watertemp_extended`) on the union of timestamps (worst quality), dropping
non-zero-quality water-temp rows, and writes the 5-column schema.

### Downstream pipeline

| File | Change |
|------|--------|
| `harmonize_extension.py` | Updated column indices for the 5-col schema (`QUALITY` = r3, `DATA_TYPE` = r4); water temp left untouched by the height filter |
| `resample.py` | `WATER_TEMP_C` in `_NUMERIC_COLS` + `DATA_TYPE_MAP`; resampled as instantaneous; water-temp plausibility clamp (NaN outside [−1, 45] °C); added to `build_measurements_table` |
| `impute.py` | `WATER_TEMP_C` added to `INSTANTANEOUS_COLS` (short-gap interpolation + `_MISSING` masks) |
| `feature_engineering.py` | `WATER_TEMP_C` dropped from the training table (capture-only, not a predictor — see finding below) |

### Design decisions

- **Water temp dropped as a predictor** (capture-only): after the re-run
  revealed multi-year outages (see below), `WATER_TEMP_C` is retained in the
  clean CSVs, grid, and measurements table but removed from the training table
  via a `WATER_TEMP_C` substring drop in `feature_engineering.py`.
- **Drop `quality = 2` water temp** in the extension (STM03 ~53 % flagged).
- **Water-temp plausibility range [−1, 45] °C** (separate from the −15 °C air
  sentinel) catches probes out of water / direct-sun outliers (e.g. 46.8/48.9 °C).

### Results (full pipeline re-run)

| Artifact | Before | After |
|----------|--------|-------|
| Grid columns | 49 | 61 (+6 `WATER_TEMP_C` + 6 `_DATA_TYPE`) |
| Training table | 289 cols | 289 cols (water temp dropped) |
| Training rows | 614,201 | 614,201 (unchanged) |
| Measurements | 11.76 M rows | 15.47 M rows |
| Events | 361 | 361 (unchanged) |

### ⚠️ Critical finding — water temp has multi-year outages

The water-temperature sensors are not logged continuously. Availability by
year (10-min grid) shows long whole-sensor outages:

| Year | STM04 | STM08 |
|------|-------|-------|
| 2014–2017 | 83–100 % | 66–95 % |
| 2018–2023 | **1–31 %** | **0 %** |
| 2024–2025 | 71–100 % | 96–100 % |
| 2026 | 0 % | 100 % |

STM08 water temperature is **absent for 2016–2023** (eight consecutive years);
STM04 for ~2018–2023. Per-split null rates for the two water-temp predictor
stations:

| Column | train | validation | test |
|--------|-------|------------|------|
| STM04_WATER_TEMP_C | 46.9 % | **91.2 %** | 48.6 % |
| STM08_WATER_TEMP_C | 85.2 % | **100.0 %** | 38.4 % |

This reproduces the exact distribution-shift hazard that dropped `STM02_TEMP_C`
(Iteration 19): water temperature is effectively **absent in the validation
split** (2021–2022).

### Remaining open issues

- [x] **Decide water-temp predictor fate** — **Resolved: dropped as predictor**
      (capture-only). Water temp stays in CSV/grid/measurements; the training
      table is unchanged from Iteration 19 (289 cols).
- [ ] Confirm whether water temp for STM04/06/07 should be backfilled from the
      DB (the current export only covers STM03/05/08).
- [ ] Verify the residual water-temp range after the [−1, 45] °C clamp is
      physically sensible.

*End of Iteration 20.*

---

## Iteration 19 — 2026-08-18

### Changes made

**Gap-handling strategy for model training + STM02_TEMP dropped**

Assessed how the remaining long gaps (post-imputation NaNs) affect model
training and wrote a concrete per-model-family strategy into `plan_TFM.md`
(new "Gap-handling strategy for model training" section).

### STM02_TEMP_C dropped

| Finding | Value |
|---------|-------|
| Pearson / Spearman vs target | −0.26 / −0.40 (weak, purely seasonal) |
| Correlation is lag-invariant | lags add no dynamic signal |
| Fill rate: train / val / test | 87 % / **0 %** / 51 % |
| Redundant with | `doy_sin`/`doy_cos`/`month` (always present, `doy_cos` r=+0.25) |

`STM02_TEMP_C` (raw + 6 lags + `_MISSING` + `_DATA_TYPE`) is removed from the
training table via `DROP_COLUMNS` in `feature_engineering.py`.  `STM01_TEMP_C`
is retained (still ~91 % available in test).

### Results

| Artifact | Before | After |
|----------|--------|-------|
| Training table | 304 cols, 269 predictors | 289 cols, 255 predictors |
| Validation complete-case | 0.0 % | 26.2 % |
| Test complete-case | 27.2 % | 49.9 % |

### Gap-handling strategy (summary, see plan_TFM)

- Trees (RF/XGBoost/LightGBM): NaN + masks, no imputation — **proceed first**.
- Linear/ARIMA: fill long gaps (fwd-fill/median) + masks; never complete-case
  on validation (was empty before the STM02_TEMP drop).
- LSTM/GRU/TFT: fill + masks (TFT native masking); handle train→test
  feature-availability shift explicitly.
- Report per-event metrics; note 20–37 % of event peaks have missing predictors.

*End of Iteration 19.*


---

## Iteration 18 — 2026-08-18

### Changes made

**Critical data-quality fixes: resampling corruption, negatives, TEMP sentinel**

A deeper audit (triggered by strange values in the extended data) uncovered a
**critical resampling bug** that was silently corrupting the historical record,
plus two smaller data-quality issues.

### 1. CRITICAL — resampling was silently dropping samples (sub-minute timestamp drift)

The STM sensors log timestamps with a sub-minute offset that drifts over time
(e.g. STM08 seconds drift 14→29 over a month; STM03/04/05/07 have :59).
`_resample_instantaneous` relied on `series.asfreq("1min")`, which only keeps
samples landing exactly on a whole minute — the rest were dropped and their
values replaced by linear interpolation. The grid therefore looked complete
(low null rate) while the true flood peaks were erased.

| Station | Raw hist max H | Grid before | Grid after |
|---------|----------------|-------------|------------|
| STM05 | 3.48 | 3.40 | **3.48** |
| STM06 | 2.29 | 1.78 | **2.29** |
| STM08 (target) | 2.83 | 1.31 | **2.83** |

**Fix** (`resample.py: load_station`): round `TIMESTAMP` to the nearest minute
before use, then deduplicate. This corrects the whole historical record — e.g.
STM08 peak discharge rises from 19.81 to 87.84 m³/s (Jan-2017 flood).

### 2. Negative values clipped to 0

`HEIGHT_m` and `PRECIP_mm` values `< 0` are clipped to `0` (a water level /
rainfall depth cannot be negative; small negatives are sensor drift).
28,317 HEIGHT cells clipped across STM03–STM08. Applied in `resample.py:
_normalize_values` (load step).

### 3. TEMP sentinel → NaN

STM02 `TEMP_C` contains a −100 °C sensor sentinel. Values `< −15 °C` (a
physical lower bound for Mallorca) are set to NaN: **40,299 cells** in STM02.
Legitimate winter temperatures (≥ −7 °C) are preserved.

### Results

| Artifact | Before | After |
|----------|--------|-------|
| Historical STM08 max H | 1.31 m | 2.83 m |
| Historical STM08 max Q | 19.81 m³/s | 87.84 m³/s |
| Events | 224 | 361 (train 192 / val 41 / test 128) |
| STM02 grid null rate | 26.4 % | 36.2 % (sentinel now NaN) |
| Training table | 304 cols, 614,201 rows | 304 cols, 614,201 rows |

### Flagged for later (see plan_TFM)

- [ ] **Extension datum shift** — STM08 reads 3–5 m continuously from 2026-02-17 (historical max 2.83 m), suggesting a sensor recalibration/offset; produces implausible discharge (176/156/133 m³/s). Pending data-provider confirmation (user asking the team). Phase C will re-harmonize with station-specific bounds.
- [ ] **−0.5 m offset floor** — STM03/04/07 have many values at exactly −0.5 m (now clipped to 0); may represent a real sensor bias rather than noise.
- [ ] **−100 °C sentinel root cause** — STM02 temperature sentinel origin unknown.

*End of Iteration 18.*


---

## Iteration 17 — 2026-08-18

### Changes made

**event_id merged into the training table + event-detection overlap fix**

Closed the loose end left by Iteration 15: the regenerated training table
was missing the `event_id` column needed for per-event evaluation.

| Change | Detail |
|--------|--------|
| `event_detection.py` CLI | Default grid switched to `grid_10min_imputed.parquet`; output grid name now derived from the input (`{stem}_with_events.parquet`) |
| `feature_engineering.py` CLI | Default grid switched to `grid_10min_imputed_with_events.parquet` so `event_id` flows into the training table |
| `detect_events()` | Fixed overlapping-event row assignment: rows are now assigned to the event with the **nearest peak** (was: later events overwrote earlier events, leaving some events with 0 rows) |
| Duplicate-peak merge | Events sharing an identical `peak_ts` (boundary-expansion artefact) are collapsed into their union window |

### Why the fix was needed

Boundary expansion (start −12 h, end +24 h) made adjacent events overlap; the
old `event_id_map[start:end] = id` assignment overwrote earlier events' rows,
so a nested event ended up with **0 rows** in the grid. Two further events
(103/104 and 191/192) were true duplicates — a single physical peak detected
twice — and have been merged.

### Results

| Artifact | Before | After |
|----------|--------|-------|
| Events | 226 | 224 (100 train / 15 val / 109 test) |
| 0-row events | 2 (and 6 truncated) | 0 |
| Duplicate peaks | 2 pairs | 0 |
| Training table | 303 cols, no event_id | 304 cols, event_id present |
| Event rows in training table | — | 29,543 |

### Remaining open issues

- [ ] HEC-HMS work (deferred, Iteration 14)
- [ ] Review the 176 m³/s peak in the harmonized extension (event #224, Apr 2026) — plausibly a real extreme or a residual harmonization artefact

*End of Iteration 17.*


---

## Iteration 16 — 2026-08-18

### Changes made

**Basin topology confirmed + discharge flow features (Phase 2, final)**

The geo team confirmed the drainage topology, resolving the long-standing
open issue. The `UPSTREAM_Q` feature (which summed STM03–STM07 assuming
parallel tributaries) was wrong — it double/triple-counted the series
stations — and has been replaced with correct flow features.

### Confirmed topology

```
STM03 → STM04 → STM06 → STM08   (main channel, in series)
                ↑
              STM05               (tributary → merges into STM06)
                        ↑
                      STM07       (tributary → merges into STM08 directly)
```

### New / changed features (`feature_engineering.py`)

| Change | Detail |
|--------|--------|
| `DISCHARGE_m3s` lags | STM03–STM07 individual discharge, lagged 1/2/3/6/12/24 h (30 cols). Kept because the karstic system does not always behave as a clean series routing. |
| `dQ_03_04` | Lateral inflow = Q(STM04) − Q(STM03), + 6 lags |
| `dQ_05_06` | Lateral inflow = Q(STM06) − Q(STM04) − Q(STM05), + 6 lags |
| `Q_IN_STM08` | Total wetland inflow = Q(STM06) + Q(STM07), + 6 lags. Replaces `UPSTREAM_Q`. |
| `UPSTREAM_Q` | Removed (double-counted the series stations) |

### Results

| Artifact | Before | After |
|----------|--------|-------|
| Training table columns | 253 | 303 |
| Predictor columns | ~215 | 269 |
| Training rows | 614,201 | 614,201 (unchanged) |
| Size | 101.6 MB | 189.7 MB |

### Verification

- `dQ_03_04`, `dQ_05_06`, `Q_IN_STM08` match hand-computed values at spot checks.
- 30 discharge-lag columns, 14 lateral-inflow columns, 7 `Q_IN_STM08` columns present.
- Lag columns align exactly with `base.shift(6)` (0 non-NaN mismatches).
- Single genuine index gap remains: Nov-2016 (STM08 30-day gap target shadow), as expected.

### Remaining open issues

- [ ] HEC-HMS work (deferred, Iteration 14)
- [ ] Merge `event_id` back into the training table (per-event evaluation hook)

*End of Iteration 16.*


---

## Iteration 15 — 2026-08-17

### Changes made

**Data-type refactor + null imputation (Phase 2)**

Standardised the `DATA_TYPE` vocabulary to the advisor's five labels and
implemented the null-imputation step on the 10-min grid.

### 1. DATA_TYPE refactor

| Change | Detail |
|--------|--------|
| Vocabulary | `observed` / `corrected` / `imputed` / `derived` / `simulated` (collapses the previous `harmonized` tag into `observed`) |
| `resample.py` | `_add_datatype_columns()` now assigns a deterministic per-variable label from `DATA_TYPE_MAP` (replaces the station-level forward-fill); added `sys.path.insert` so `scripts.*` imports work from the CLI |
| `build_measurements_table()` | Reads per-variable `{col}_DATA_TYPE` grid columns instead of station-level columns |
| `apply_discharge()` order | DISCHARGE computed *before* DATA_TYPE assignment so discharge gets a label |
| `harmonize_extension.py` | Extension rows keep `DATA_TYPE = "observed"` (no more `harmonized`) |
| `clean_STM02.py` | Recovered tipping-bucket cells now tagged `corrected` at source level (73 cells) |
| Clean CSVs | Relabelled `harmonized` → `observed` in STM03–STM08 (no value changes) |

### DATA_TYPE mapping

| Label | Trigger |
|-------|---------|
| `observed` | measured + re-gridded (5→10 mean, 10→10, 15→10 interp, cumulative-precip re-gridding) |
| `corrected` | source-level fix (STM02 tipping-bucket recovery); lives in clean CSVs only |
| `imputed` | missing value filled (null imputation ≤ 24 h) |
| `derived` | DISCHARGE (rating curve), AEMET hourly→10-min disaggregation |
| `simulated` | model output (HEC-HMS / ML; separate files) |

### 2. Null imputation (`scripts/preprocessing/impute.py`, new)

| Change | Detail |
|--------|--------|
| `impute_gaps(grid, max_interp="24h")` | Fills NaN runs ≤ 24 h: time-linear for HEIGHT/TEMP, linear interpolation of the 10-min increments for PRECIP. Longer gaps stay NaN. Filled cells tagged `DATA_TYPE = "imputed"` |
| `add_missingness_indicators(grid)` | Adds `{col}_MISSING` (0/1) for cells still missing after imputation |
| DISCHARGE | Left untouched (NaN there = out-of-rating-curve-range, not missing) |
| `feature_engineering.py` | Each lagged value now paired with a lagged `_MISSING` mask; default grid switched to `grid_10min_imputed.parquet` |

> **Note on precip**: an earlier cumulative-curve-and-diff fill was rejected — the
> grid PRECIP_mm are 10-min *increments*, so cumulative interpolation redistributes
> observed rain into the gap (altering 23 real observations). Linear interpolation
> of the increments fills only the gap and preserves every observed value.

### Results

| Artifact | Before | After |
|----------|--------|-------|
| Imputed cells (gaps ≤ 24 h) | — | 12,404 (1.7 % of all NaN) |
| Long-gap cells left NaN (> 24 h) | — | ~723 k |
| Grid columns | 41 | 49 (per-variable DATA_TYPE) |
| Imputed grid columns | — | 62 (+13 `_MISSING`) |
| Measurements table | 10,812,691 rows | 11,756,611 rows |
| Measurements DATA_TYPE | observed + harmonized | observed 6.18 M / derived 5.57 M / imputed 12.4 k |
| Training table | 144 cols, 611,648 rows | 253 cols, 614,201 rows (train 325,049 / val 78,624 / test 210,528) |

### Verification

- 0 residual gaps ≤ 24 h (except boundary edges)
- Long gaps still NaN; 0 originally-present values altered
- Precip observed totals unchanged (0 deviation)
- `_MISSING` masks align 1:1 with remaining NaN
- Target-hole behaviour confirmed: rows with NaN targets (e.g. the Nov-2016 STM08 30-day gap) are dropped from training

### Remaining open issues

- [ ] Basin topology confirmation (geo team)
- [ ] HEC-HMS work (deferred, Iteration 14)

*End of Iteration 15.*


---

## Iteration 14 — 2026-08-17

### Changes made

**HEC-HMS project initial setup (Phase 3) — on hold, to be resumed later**

| Change | Detail |
|--------|--------|
| `hec_hms/STM/` | New HEC-HMS project added: basin model (`STM.basin`, 1597 lines), validation basin (`STM_val.basin`), terrain, grid, run config, control + meteorology specs |
| `scripts/hec_hms/dss_io.py` | DSS I/O via JPype against the HEC-HMS bundled hec-monolith JAR (JDK 17 required). Replaces pydsstools. `write_precip()` / `read_ts()` use native Java classes (`HecDss`, `TimeSeriesContainer`, `HecTime`), with simple wildcard pathname matching |
| `scripts/hec_hms/export_event.py` | Exports event precipitation at native 10-min resolution (no 15-min resampling); auto-generates matching `Control_10min.control` XML and 5-gage meteorologic model |
| Meteorology configs | Native HEC-HMS format: `Meteo_Inverse.met` (inverse distance squared), `Meteo_TR.met` switched from gridded to weighted-gages, `STM.gage` (STM01 stage data reference) |

### Remaining open issues

- [ ] HEC-HMS basin delineation, calibration, validation and uncertainty analysis (deferred — a lot of work ahead)
- [ ] Basin topology confirmation (geo team)

*End of Iteration 14.*


---

## Iteration 13 — 2026-08-07

### Changes made

**DB extension data harmonization**

| Change | Detail |
|--------|--------|
| `scripts/preprocessing/harmonize_extension.py` | New module: 3-layer filter for DB extension data in hydro CSVs |
| Layer 1 | Absolute bounds: H ∈ [-0.5, 5.0] m |
| Layer 2 | Rate-of-change: \|dH/dt\| ≤ 0.5 m/10min (3 m/h) |
| Layer 3 | Contiguous clean blocks: keep blocks ≥ 24h with ≥ 70% valid fraction |
| Full pipeline rebuilt | Grid, training table, events, measurements regenerated with harmonized extension |

### Harmonization results

| Station | Retained | Discarded |
|---------|----------|-----------|
| STM03 | 40.9% | 28,665 |
| STM04 | 77.6% | 18,530 |
| STM05 | 22.3% | 52,610 |
| STM06 | 63.8% | 30,280 |
| STM07 | 61.6% | 16,243 |
| STM08 | **81.1%** | 8,699 |
| **Total** | **58.2%** | 155,027 |

### Pipeline after harmonization

| Artifact | Before | After | Change |
|----------|--------|-------|--------|
| Grid rows | 569,089 | 618,769 | +49,680 |
| Grid period | 2014-09 → 2025-07 | 2014-09 → 2026-07 | +10 months |
| Duration | 10.8 years | 11.8 years | +1 year |
| Training table | 563,698 rows | 611,648 rows | +47,950 |
| Events | 196 | 226 | +30 (all in test) |
| Test events | 80 | 110 | +37.5% |

### Remaining open issues

- [x] DB extension data harmonization — **Done (Iteration 13-14)**
- [ ] Basin topology confirmation (geo team)

*End of Iteration 13.*


---

## Iteration 12 — 2026-08-07

### Changes made

**`flow_to_meters` inverse rating curve implemented**

| Change | Detail |
|--------|--------|
| `scripts/preprocessing/rating_curve.py` | `load_rating_curves()` now accepts `direction` parameter: `"meters_to_flow"` (default, H→Q) or `"flow_to_meters"` (Q→H) |
| STM03–STM07 | Explicit `flow_to_meters` rows from CSV used directly |
| STM08 | Auto-inverted via 10,000-point dense sampling of the forward curve + linear interpolation; roundtrip error < 1 mm |

### Remaining open issues

- [ ] DB extension data harmonization (blocked on data provider)
- [ ] Basin topology confirmation (geo team)

*End of Iteration 12.*


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
