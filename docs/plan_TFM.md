# Plan TFM — Predicción del nivel de agua en STM08 (Sa Marjal)

## Objetivo

Este TFM tiene un **doble objetivo**:

1. **Modelo físico (HEC-HMS)**: Construir un modelo hidrológico de base física de la cuenca de Sant Miquel con el software **HEC-HMS** (Hydrologic Engineering Center – Hydrologic Modeling System), calibrado y validado con las series observadas en las estaciones STM03–STM08.
2. **Modelos basados en datos (ML/IA)**: Desarrollar modelos de aprendizaje automático e inteligencia artificial para predecir el **nivel de agua** (`HEIGHT_m`) en la estación hidrológica **STM08 - Sa Marjal**, utilizando como predictores las series temporales del resto de estaciones meteorológicas e hidrológicas disponibles.
3. **Comparación**: Evaluar y comparar el rendimiento de ambas familias de modelos (físico vs. datos) bajo las métricas estándar en hidrología (NSE, KGE, RMSE, PBIAS), analizando sus ventajas, limitaciones y contextos de aplicación.

---

## 1. Inventario de datos

### 1.1 Estación objetivo

| Estación | Nombre | Tipo | Variable objetivo | Período | Frecuencia |
|---|---|---|---|---|---|
| STM08 | Sa Marjal | Hidrológica | `HEIGHT_m` / `DISCHARGE_m3s` | 2013-03-04 → 2026-07-15 | 15 min (→ 10 min desde 2022-05-05; → 5 min desde 2026-02-17) |

> **Nota sobre la variable objetivo**: Los CSVs limpios exportan `HEIGHT_m`, `DISCHARGE_m3s`, `VOLUME_m3` y `LOAD_kg`. Para el período extendido (2026-02-17 → 2026-07-15), procedente de la BD interna, **solo `HEIGHT_m` está disponible**; `DISCHARGE_m3s`, `VOLUME_m3` y `LOAD_kg` quedan vacíos. `HEIGHT_m` es la variable a usar como objetivo (nivel de agua directamente medido); `DISCHARGE_m3s` es una transformación monotónica vía curva de aforo y puede usarse como complemento en el período histórico.

### 1.2 Estaciones predictoras

#### Hidrológicas (HEIGHT_m / DISCHARGE_m3s / VOLUME_m3 / LOAD_kg)

| Estación | Nombre | T0 | T_end | Frecuencia |
|---|---|---|---|---|
| STM03 | Es Fangar | 2012-10-01 | 2026-07-15 | 15 min → 10 min (2022) → 5 min (2025-07-23+) |
| STM04 | Gabelli | 2012-12-06 | 2026-07-15 | 15 min → 10 min (2022) → 5 min (2025-09-18+) |
| STM05 | Monnàber | 2012-10-01 | 2026-07-15 | 15 min → 10 min (2022) → 5 min (2025-09-18+) |
| STM06 | Sant Miquel | 2012-10-01 | 2026-07-15 | 15 min → 10 min (2022) → 5 min (2025-09-18+) |
| STM07 | Búger | 2012-10-01 | 2026-07-15 | 15 min → 10 min (2022) → 5 min (2026-02-20+) |

> **Nota extensión BD**: El tramo extendido desde la BD interna solo contiene `HEIGHT_m` (nivel de agua); `DISCHARGE_m3s`, `VOLUME_m3` y `LOAD_kg` quedan vacíos. STM03 tiene ~45 k registros con `quality != 0` en el tramo extendido; STM05 tiene ~3 k.

#### Meteorológicas STM (PRECIP_mm, TEMP_C)

| Estación | Nombre | T0 | T_end | Frecuencia |
|---|---|---|---|---|
| STM01 | Coll des Telègraf | 2012-11-30 | 2026-07-15 | 15 min → 10 min (2022) |
| STM02 | Míner Gran | 2014-09-26 | 2026-07-15 | 15 min → 10 min (2022) |

#### Meteorológicas AEMET (PRECIP_mm, horaria)

| Estación | Nombre | T0 | T_end | Frecuencia |
|---|---|---|---|---|
| B013X | Lluc | 1993-04-16 | 2026-07-02 | 60 min |
| B605X | Muro-S'albufera | 2005-04-12 | 2026-07-02 | 60 min |
| B691Y | Sa Pobla-Sa Canova | 2011-04-19 | 2026-07-02 | 60 min |

> **Fuentes**: hasta 2023-01-01 proceden de UIB-Estrany (formato phor, décimas de mm → mm); desde 2023-01-01 se extienden con datos de la BD interna (`Rain60m`, ya en mm). Se detectaron ~582–584 registros con `quality != 0` por estación en el tramo BD (incluidos en el CSV, pendiente de revisar si deben filtrarse).

---

## 2. Ventana temporal común

Tras extender las series STM03–STM08 con datos de la BD interna, la intersección de todos los conjuntos es:

```
Inicio:  2014-09-26  (STM02 arranca en sept-2014)
Fin:     2026-07-02  (límite AEMET; el resto de estaciones llegan a 2026-07-15)
```

Esto da **~12 años** de datos solapados con todas las fuentes activas. Todas las series STM (hidrológicas y meteorológicas) llegan ahora a **2026-07-15**; las AEMET hasta **2026-07-02**.

> **Nota**: En el tramo extendido de las estaciones hidrológicas (desde ~2025-07 / 2026-02 según estación), solo `HEIGHT_m` está disponible; `DISCHARGE_m3s`, `VOLUME_m3` y `LOAD_kg` quedan vacíos.

---

## 3. Retos principales

1. **Frecuencias mixtas**: 5 min / 10 min / 15 min (STM según período) vs 60 min (AEMET). Necesario remuestrear a frecuencia común.
2. **Datos faltantes**: Algunas estaciones tienen miles de celdas nulas (p.ej. STM03 tiene >130 k nulos en `LOAD_kg`). `LOAD_kg` es la variable con más nulos; el tramo extendido solo tiene `HEIGHT_m`.
3. **Heterogeneidad del tramo extendido**: Desde ~2025-07/2026-02 solo está disponible `HEIGHT_m` (sin caudal ni volumen); el split de train/val/test debe tener esto en cuenta.
4. **Leakage temporal**: En series temporales es crítico hacer el split cronológico estricto.
5. **Eventos de crecida esporádicos**: El caudal es cero la mayor parte del tiempo; el modelo debe capturar bien los picos.
6. **Quality != 0 en BD**: STM03 (~45 k registros) y STM05 (~3 k registros) tienen datos con calidad no validada en el tramo extendido; revisar si deben filtrarse.

---

## 4. Plan de trabajo

### Fase 0 — Revisión y decisiones previas

- [x] ~~Decidir variable objetivo~~: `HEIGHT_m` es la variable objetivo (nivel de agua, disponible en todo el período incluido el tramo extendido). `DISCHARGE_m3s` complementario para el período histórico.
- [x] ~~Decidir si incluir estaciones AEMET~~ — Series AEMET extendidas hasta 2026-07-02 con datos de BD; se incluyen todas.
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

### Fase 3 — Modelo físico con HEC-HMS

**Objetivo**: Construir un modelo hidrológico de base física de la cuenca de Sant Miquel calibrado con datos observados.

- [ ] **Delineación de la cuenca**: Obtener el MDT (Modelo Digital del Terreno) de la zona y delimitar la cuenca hidrográfica y las subcuencas drenantes hacia STM08.
- [ ] **Configuración del modelo HEC-HMS**:
  - Definir los parámetros morfométricos de cada subcuenca (área, pendiente, longitud de cauce).
  - Seleccionar los métodos de transformación lluvia-escorrentía (p.ej. SCS Curve Number) y de tránsito de avenidas (p.ej. Muskingum).
  - Asignar las series de precipitación de las estaciones STM01, STM02 y AEMET como entrada forzante.
- [ ] **Calibración y validación**:
  - Calibrar los parámetros del modelo (CN, Manning, tiempos de concentración) frente a caudales observados en STM06 / STM08 mediante optimización automática (p.ej. algoritmo DCEA integrado en HEC-HMS).
  - Validar con eventos de crecida independientes del período de calibración.
- [ ] **Análisis de incertidumbre**: Identificar los parámetros más sensibles y sus rangos de variación.

**Entregable**: Proyecto HEC-HMS calibrado (`hec_hms/`) + notebook de análisis de resultados `03_hec_hms.ipynb`

### Fase 4 — Modelos de referencia (*baselines*)

**Objetivo**: Establecer límites inferiores de rendimiento.

- [ ] **Persistencia**: `y_pred(t) = y(t-1)` — línea base trivial.
- [ ] **Regresión lineal** con lags seleccionados.
- [ ] **Random Forest / Gradient Boosting (XGBoost/LightGBM)**: robustos, interpretables, manejan nulos bien.

**Métricas** (estándar en hidrología):
- NSE (*Nash-Sutcliffe Efficiency*) — métrica principal.
- KGE (*Kling-Gupta Efficiency*).
- RMSE y MAE.
- PBIAS (sesgo volumétrico).

**Entregable**: `04_baselines.ipynb`

### Fase 5 — Modelos secuenciales

**Objetivo**: Capturar las dependencias temporales de largo alcance.

- [ ] **LSTM / GRU**: arquitectura encoder-decoder para predicción multi-step.
- [ ] **Temporal Fusion Transformer (TFT)**: estado del arte en series temporales multivariables, maneja covariables conocidas (meteo) y pasadas (hidro).
- [ ] Ajuste de hiperparámetros con *Optuna* o *Ray Tune*.

**Entregable**: `05_deep_learning.ipynb`

### Fase 6 — Interpretabilidad y análisis de resultados

- [ ] Feature importance (SHAP values) para entender qué predictores dominan.
- [ ] Análisis de errores: ¿el modelo falla más en crecidas o en estiajes?
- [ ] Curvas de error por umbral de caudal.
- [ ] Comparación de predicciones vs observaciones en eventos seleccionados.

**Entregable**: `06_interpretability.ipynb`

### Fase 7 — Comparación HEC-HMS vs. ML/IA

**Objetivo**: Confrontar el modelo físico con los modelos basados en datos sobre los mismos eventos y períodos.

- [ ] Evaluar ambas familias con las métricas comunes (NSE, KGE, RMSE, MAE, PBIAS) en train/val/test.
- [ ] Análisis por tipo de evento: crecidas, estiajes y condiciones ordinarias.
- [ ] Discutir los requisitos de datos de cada enfoque (datos de entrada, esfuerzo de calibración, transferibilidad).
- [ ] Identificar en qué escenarios el modelo físico supera a los datos y viceversa.

**Entregable**: `07_comparison.ipynb`

### Fase 8 — Escritura de la memoria

- [ ] Introducción y contexto hidrológico de la cuenca de Sant Miquel.
- [ ] Descripción del modelo físico HEC-HMS: metodología, calibración y resultados.
- [ ] Descripción de los datos y del preprocesado para los modelos ML/IA.
- [ ] Resultados y comparación entre el modelo físico y los modelos basados en datos.
- [ ] Discusión: ventajas, limitaciones y recomendaciones de uso de cada enfoque.
- [ ] Conclusiones.

---

## 5. Stack tecnológico propuesto

| Categoría | Herramienta |
|---|---|
| Manipulación de datos | `pandas`, `polars` (opcional para velocidad) |
| Visualización | `matplotlib`, `seaborn`, `plotly` |
| Modelo físico | **HEC-HMS** (USACE) |
| SIG / MDT | QGIS o ArcGIS + HEC-GeoHMS para delineación de cuenca |
| ML clásico | `scikit-learn`, `xgboost`, `lightgbm` |
| Deep Learning | `PyTorch` + `pytorch-forecasting` (TFT) |
| Hiperparámetros | `optuna` |
| Métricas hidrológicas | `hydroeval` o implementación propia |
| Entorno | Jupyter Notebooks, Python ≥ 3.10 |

---

## 6. Preguntas abiertas / pendientes de Fran

### Específicas de HEC-HMS

- ¿Está disponible un MDT de alta resolución (LiDAR o similar) para la cuenca de Sant Miquel?
- ¿Existe cartografía de usos del suelo y tipos de suelo para calcular el CN (Curve Number)?
- ¿Se dispone de aforos de caudales punta en eventos históricos para calibrar el modelo?
- ¿Las estaciones aguas arriba (STM03–STM07) actúan como puntos de control internos en la cuenca?

### Generales

- Curvas de aforo de STM08: ¿están calibradas para todo el período o cambian con el tiempo?
- Confirmación de la topología de la cuenca: ¿todas las STM drenan hacia Sa Marjal?
- STM09, STM10, STM11 (mencionadas en la bitácora): ¿están disponibles? Podrían añadir información.
- Horizonte de predicción deseado: ¿nowcasting (t+1h) o previsión a t+6h, t+24h?
