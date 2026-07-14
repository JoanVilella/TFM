# Plan TFM — Predicción del nivel de agua en STM08 (Sa Marjal)

## Objetivo

Predecir el **nivel de agua** (caudal / *discharge*, proxy del nivel) en la estación hidrológica **STM08 - Sa Marjal** utilizando como predictores las series temporales del resto de estaciones meteorológicas e hidrológicas disponibles.

---

## 1. Inventario de datos

### 1.1 Estación objetivo

| Estación | Nombre | Tipo | Variable objetivo | Período | Frecuencia |
|---|---|---|---|---|---|
| STM08 | Sa Marjal | Hidrológica | `DISCHARGE_m3s` | 2013-03-04 → 2026-02-17 | 15 min (→ 10 min desde 2022-05-05) |

> **Nota sobre la variable objetivo**: Los CSVs limpios exportan `DISCHARGE_m3s`, `VOLUME_m3` y `LOAD_kg`, pero **no** exportan la altura de lámina de agua (`HEIGHT`) directamente. `DISCHARGE_m3s` es una transformación monotónica de `HEIGHT` vía la curva de aforo, por lo que predecir caudal es equivalente a predecir nivel. Valorar si merece la pena re-extraer `HEIGHT` del Excel original para trabajar directamente en unidades de nivel (m).

### 1.2 Estaciones predictoras

#### Hidrológicas (DISCHARGE_m3s, VOLUME_m3, LOAD_kg)

| Estación | Nombre | T0 | T_end | Frecuencia |
|---|---|---|---|---|
| STM03 | Es Fangar | 2012-10-01 | 2025-07-23 | 15 min → 10 min (2022) |
| STM04 | Gabelli | 2012-12-06 | 2025-09-18 | 15 min → 10 min (2022) |
| STM05 | Monnàber | 2012-10-01 | 2025-09-18 | 15 min → 10 min (2022) |
| STM06 | Sant Miquel | 2012-10-01 | 2025-09-18 | 15 min → 10 min (2022) |
| STM07 | Búger | 2012-10-01 | 2026-02-20 | 15 min → 10 min (2022) |

#### Meteorológicas STM (PRECIP_mm, TEMP_C)

| Estación | Nombre | T0 | T_end | Frecuencia |
|---|---|---|---|---|
| STM01 | Coll des Telègraf | 2012-11-30 | 2025-09-25 | 15 min → 10 min (2022) |
| STM02 | Míner Gran | 2014-09-26 | 2025-08-12 | 15 min → 10 min (2022) |

#### Meteorológicas AEMET (PRECIP_mm, horaria)

| Estación | Nombre | T0 | T_end | Frecuencia |
|---|---|---|---|---|
| B013X | Lluc | 1993-04-16 | 2026-07-14 | 60 min |
| B605X | Muro-S'albufera | 2005-04-12 | 2026-07-14 | 60 min |
| B691Y | Sa Pobla-Sa Canova | 2011-04-19 | 2026-07-14 | 60 min |

> **Fuentes**: hasta 2023-01-01 proceden de UIB-Estrany (formato phor, décimas de mm → mm); desde 2023-01-01 se extienden con datos de la BD interna (`Rain60m`, ya en mm). Se detectaron ~582–584 registros con `quality != 0` por estación en el tramo BD (incluidos en el CSV, pendiente de revisar si deben filtrarse).

---

## 2. Ventana temporal común

Tras extender las series AEMET con datos de la BD interna, la intersección de todos los conjuntos es:

```
Inicio:  2014-09-26  (STM02 arranca en sept-2014)
Fin:     ~2025-07    (límite del conjunto más corto: STM03, hasta 2025-07-23)
```

Esto da **~11 años** de datos solapados con todas las fuentes activas. Las series AEMET ahora llegan a 2026-07-14, por lo que **ya no limitan la ventana**.

---

## 3. Retos principales

1. **Frecuencias mixtas**: 10 min / 15 min (STM) vs 60 min (AEMET). Necesario remuestrear a frecuencia común.
2. **Datos faltantes**: Algunas estaciones tienen miles de celdas nulas (p.ej. STM03 tiene >130 k nulos en `LOAD_kg`). `LOAD_kg` es la variable con más nulos en todas las estaciones.
3. **Sin `HEIGHT` en los CSV limpios**: Considerar si re-extraerlo de los Excels crudos para STM08.
4. **Leakage temporal**: En series temporales es crítico hacer el split cronológico estricto.
5. **Eventos de crecida esporádicos**: El caudal es cero la mayor parte del tiempo; el modelo debe capturar bien los picos.

---

## 4. Plan de trabajo

### Fase 0 — Revisión y decisiones previas

- [ ] Decidir variable objetivo: `DISCHARGE_m3s` vs `HEIGHT` (re-extraer del Excel crudo de STM08).
- [x] ~~Decidir si incluir estaciones AEMET~~ — Series AEMET extendidas hasta 2026-07-14 con datos de BD; se incluyen todas.
- [ ] Confirmar la topología de la cuenca: qué estaciones son aguas arriba de STM08 y cuál es el tiempo de concentración aproximado (importante para definir el horizonte de predicción y los lags).

### Fase 1 — Análisis exploratorio (EDA)

**Objetivo**: Entender la calidad y estructura de los datos antes de modelizar.

- [ ] Cargar todos los CSVs y calcular tasas de nulos por estación y variable.
- [ ] Visualizar las series temporales completas de cada estación.
- [ ] Calcular la correlación cruzada con desfase temporal (*cross-correlation*) entre cada predictor y STM08 para identificar:
  - Qué estaciones explican mejor el nivel en STM08.
  - El lag óptimo (tiempo de concentración).
- [ ] Identificar y caracterizar los eventos de crecida históricos.
- [ ] Analizar la estacionalidad (invierno vs verano en clima mediterráneo).

**Entregable**: Notebook `01_eda.ipynb`

### Fase 2 — Preprocesado y construcción del dataset

**Objetivo**: Producir un DataFrame listo para modelizar.

- [ ] **Remuestreo**: Agregar todas las series a resolución horaria (suma para precipitación, media para caudal y temperatura). Justificar la resolución elegida.
- [ ] **Alineación temporal**: Indexar por `TIMESTAMP UTC` común, rellenar huecos de índice.
- [ ] **Imputación de nulos**:
  - Huecos cortos (< 3 h): interpolación lineal.
  - Huecos largos: marcar con flag o excluir del entrenamiento.
- [ ] **Feature engineering**:
  - Lags de cada predictor: *t-1h, t-2h, t-3h, t-6h, t-12h, t-24h*.
  - Precipitación acumulada: últimas 3 h, 6 h, 12 h, 24 h, 48 h (índice de precipitación antecedente).
  - Caudal acumulado aguas arriba (suma de STM03–STM07 en t-lag).
  - Variables temporales: hora del día, mes, día del año (útiles para modelos que no capturan estacionalidad implícitamente).
- [ ] **Split cronológico**:
  - Train: hasta 2020-12-31
  - Validation: 2021-01-01 → 2022-06-30
  - Test: 2022-07-01 → fin de ventana

**Entregable**: `02_preprocessing.ipynb` + `data/processed/dataset_hourly.parquet`

### Fase 3 — Modelos de referencia (*baselines*)

**Objetivo**: Establecer límites inferiores de rendimiento.

- [ ] **Persistencia**: `y_pred(t) = y(t-1)` — línea base trivial.
- [ ] **Regresión lineal** con lags seleccionados.
- [ ] **Random Forest / Gradient Boosting (XGBoost/LightGBM)**: robustos, interpretables, manejan nulos bien.

**Métricas** (estándar en hidrología):
- NSE (*Nash-Sutcliffe Efficiency*) — métrica principal.
- KGE (*Kling-Gupta Efficiency*).
- RMSE y MAE.
- PBIAS (sesgo volumétrico).

**Entregable**: `03_baselines.ipynb`

### Fase 4 — Modelos secuenciales

**Objetivo**: Capturar las dependencias temporales de largo alcance.

- [ ] **LSTM / GRU**: arquitectura encoder-decoder para predicción multi-step.
- [ ] **Temporal Fusion Transformer (TFT)**: estado del arte en series temporales multivariables, maneja covariables conocidas (meteo) y pasadas (hidro).
- [ ] Ajuste de hiperparámetros con *Optuna* o *Ray Tune*.

**Entregable**: `04_deep_learning.ipynb`

### Fase 5 — Interpretabilidad y análisis de resultados

- [ ] Feature importance (SHAP values) para entender qué predictores dominan.
- [ ] Análisis de errores: ¿el modelo falla más en crecidas o en estiajes?
- [ ] Curvas de error por umbral de caudal.
- [ ] Comparación de predicciones vs observaciones en eventos seleccionados.

**Entregable**: `05_interpretability.ipynb`

### Fase 6 — Escritura de la memoria

- [ ] Introducción y contexto hidrológico de la cuenca.
- [ ] Descripción de los datos y del preprocesado.
- [ ] Resultados y comparación de modelos.
- [ ] Discusión y conclusiones.

---

## 5. Stack tecnológico propuesto

| Categoría | Herramienta |
|---|---|
| Manipulación de datos | `pandas`, `polars` (opcional para velocidad) |
| Visualización | `matplotlib`, `seaborn`, `plotly` |
| ML clásico | `scikit-learn`, `xgboost`, `lightgbm` |
| Deep Learning | `PyTorch` + `pytorch-forecasting` (TFT) |
| Hiperparámetros | `optuna` |
| Métricas hidrológicas | `hydroeval` o implementación propia |
| Entorno | Jupyter Notebooks, Python ≥ 3.10 |

---

## 6. Preguntas abiertas / pendientes de Fran

- Curvas de aforo de STM08: ¿están calibradas para todo el período o cambian con el tiempo?
- Confirmación de la topología de la cuenca: ¿todas las STM drenan hacia Sa Marjal?
- STM09, STM10, STM11 (mencionadas en la bitácora): ¿están disponibles? Podrían añadir información.
- Horizonte de predicción deseado: ¿nowcasting (t+1h) o previsión a t+6h, t+24h?
