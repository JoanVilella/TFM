# Plan TFM — Predicción del nivel de agua en STM08 (Sa Marjal)

## Objetivo

Este TFM tiene **tres objetivos complementarios**:

1. **Modelo físico (HEC-HMS)**: Construir un modelo hidrológico de base física de la cuenca de Sant Miquel con el software **HEC-HMS** (Hydrologic Engineering Center – Hydrologic Modeling System), calibrado y validado con las series observadas en las estaciones STM03–STM08.
2. **Modelos basados en datos (ML/IA)**: Desarrollar modelos de aprendizaje automático e inteligencia artificial para predecir el **nivel de agua** (`HEIGHT_m`) en la estación hidrológica **STM08 - Sa Marjal** en horizontes de predicción de **t+1h, t+6h y t+24h**, utilizando como predictores las series temporales del resto de estaciones meteorológicas e hidrológicas disponibles.
3. **Comparación**: Evaluar y comparar el rendimiento de ambas familias de modelos (físico vs. datos) bajo las métricas estándar en hidrología (NSE, KGE, RMSE, PBIAS), desglosada por horizonte de predicción y por tipo de evento (crecida/estiaje), analizando sus ventajas, limitaciones y contextos de aplicación.

### Preguntas de investigación

- **RQ1**: ¿Con qué precisión reproduce un modelo físico calibrado (HEC-HMS) los niveles y eventos de crecida observados en STM08?
- **RQ2**: ¿Hasta qué punto los modelos basados en datos (baselines → RF/XGBoost → LSTM/GRU → TFT) mejoran esa precisión, en particular en los picos de crecida y en los horizontes t+1h, t+6h y t+24h?
- **RQ3**: ¿Cómo afectan al rendimiento las decisiones de preprocesado (resolución temporal, lags, tratamiento de la intermitencia) y qué predictores dominan la predicción?

> **Contexto y novedad**: La literatura comparativa HEC-HMS vs. ML usa mayoritariamente datos diarios y cuencas perennes. Este TFM estudia una **cuenca de torrente mediterráneo** con régimen intermitente (serie mayoritariamente nula y crecidas relámpago), con datos **sub-horarios** de una red densa de estaciones, y con objetivo el **nivel de agua en un humedal** (Sa Marjal, junto a s'Albufera).

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

> **Fuentes**: hasta 2023-01-01 proceden de UIB-Estrany (formato phor, décimas de mm → mm) — grupo de investigación **RiscBal** (https://www.uib.eu/research/structures/structure/RiscBal/); desde 2023-01-01 se extienden con datos de la BD interna (`Rain60m`, ya en mm). Se detectaron ~582–584 registros con `quality != 0` por estación en el tramo BD (incluidos en el CSV, pendiente de revisar si deben filtrarse).

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

1. **Frecuencias mixtas**: 5 min / 10 min / 15 min (STM según período) vs 60 min (AEMET). Se adopta una rejilla común de **10 min**. Terminología precisa (no intercambiable): *aggregating*, *resampling*, *downsampling* y *disaggregating*. **No se debe** dividir ingenuamente la precipitación horaria entre 6 para generar datos cada 10 min (asume distribución uniforme y puede distorsionar eventos de crecida rápida). El método concreto de desagregación debe justificarse.
2. **Datos faltantes**: Algunas estaciones tienen miles de celdas nulas (p.ej. STM03 tiene >130 k nulos en `LOAD_kg`). `LOAD_kg` es la variable con más nulos; el tramo extendido solo tiene `HEIGHT_m`.
3. **Heterogeneidad del tramo extendido**: Desde ~2025-07/2026-02 solo está disponible `HEIGHT_m` (sin caudal ni volumen); el split de train/val/test debe tener esto en cuenta.
4. **Leakage temporal**: En series temporales es crítico hacer el split cronológico estricto.
5. **Eventos de crecida esporádicos**: El caudal es cero la mayor parte del tiempo; el modelo debe capturar bien los picos.
6. **Quality != 0 en BD**: STM03 (~45 k registros) y STM05 (~3 k registros) tienen datos con calidad no validada en el tramo extendido; revisar si deben filtrarse.
7. **Definición de evento hidrológico**: Debe definirse de forma objetiva y reproducible (umbrales de inicio/fin, criterio de estabilización). Un mismo evento **no puede partirse entre train y test** (leakage). La identificación en el EDA es preliminar; la definitiva se hará en la Fase 2 sobre la rejilla consolidada.
8. **Quality flags (requisito del tutor)**: Los flags de calidad deben documentarse (qué significa cada valor: válido, inválido, missing, fallo de sensor, corregido/interpolado/estimado) y **preservarse** para distinguir mediciones originales de modificadas. Los CSVs limpios actuales no conservan los flags — **acción prioritaria para Fase 2**.

---

## 4. Plan de trabajo

### Fase 0 — Revisión y decisiones previas

- [x] ~~Decidir variable objetivo~~: `HEIGHT_m` es la variable objetivo (nivel de agua, disponible en todo el período incluido el tramo extendido). `DISCHARGE_m3s` complementario para el período histórico.
- [x] ~~Decidir si incluir estaciones AEMET~~ — Series AEMET extendidas hasta 2026-07-02 con datos de BD; se incluyen todas.
- [x] ~~Datos para HEC-HMS~~ — MDT, cartografía de usos del suelo y tipos de suelo **disponibles**; el modelo físico es un pilar completo del TFM.
- [x] ~~Horizonte de predicción~~ — **Multi-horizonte: t+1h, t+6h y t+24h** (arquitecturas multi-step: LSTM/GRU encoder-decoder y TFT).
- [x] ~~Modelo híbrido (ML corrigiendo HEC-HMS)~~ — Descartado como contribución propia; queda como trabajo futuro. El TFM es una comparación estricta físico vs. datos.
- [x] ~~Idioma de la memoria~~ — Inglés.
- [ ] Confirmar la topología de la cuenca: qué estaciones son aguas arriba de STM08 y cuál es el tiempo de concentración aproximado (importante para definir el horizonte de predicción y los lags).

### Fase 1 — Análisis exploratorio (EDA)

**Objetivo**: Entender la calidad y estructura de los datos antes de modelizar.

- [x] Cargar todos los CSVs y calcular tasas de nulos por estación y variable.
- [x] Visualizar las series temporales completas de cada estación.
- [x] Calcular la correlación cruzada con desfase temporal (*cross-correlation*) entre cada predictor y STM08 para identificar:
  - Qué estaciones explican mejor el nivel en STM08.
  - El lag óptimo (tiempo de concentración).
- [x] Identificar y caracterizar los eventos de crecida históricos.
- [x] Analizar la estacionalidad (invierno vs verano en clima mediterráneo).

**Entregable**: Notebook `01_eda.ipynb` ✅ Completado (2026-08-05). 8 secciones, 14 figuras en `results/figures/eda/`.

> **Hallazgos principales del EDA**: (1) La extensión de BD (2025–2026) contiene datos **sin validar** con spikes de hasta 177 m, mesetas negativas y oscilaciones diarias no físicas → los análisis cuantitativos se restringen a la ventana histórica validada (2014-09-26 → 2025-07-22). (2) Se recuperaron 73 celdas de fórmulas Excel de tipping-bucket en STM02 (`PRECIP_mm`). (3) Las correlaciones cruzadas muestran que STM04 (r=0.908, lag ≈ 30 min) y STM06 (r=0.887, lag ≈ 1 h) son los mejores predictores lineales de STM08. (4) STM08 tiene un 85% de caudal cero — régimen altamente intermitente. (5) El EDA identificó eventos preliminares con una regla reproducible basada en literatura, pero los eventos que solapan con gaps de datos pueden estar fragmentados; la identificación definitiva debe hacerse en la Fase 2 sobre la rejilla de 10 min consolidada.

### 4b. Tablas requeridas (*advisor feedback*)

El tutor solicita cuatro tablas como entregables mínimos antes de cualquier modelización:

| Tabla | Columnas clave |
|---|---|
| **Stations** | ID, tipo de sensor, variable medida, ubicación, altitud, frecuencia de muestreo, posición relativa a STM08 |
| **Measurements** | datetime, estación, precipitación, nivel, temperatura, quality flag, tipo de dato (observed/corrected/imputed/simulated) |
| **Events** | event ID, start/end datetime, precipitación acumulada, intensidad máxima, nivel máximo en STM08, tiempo al pico, duración |
| **Training** | una fila por timestamp, con observaciones actuales + pasadas, más columnas target: `nivel_STM08_30min`, `nivel_STM08_60min`, `nivel_STM08_120min` |

También se requiere una tabla que asigne cada **evento** (no cada fila) a **train / validation / test**.

### Fase 2 — Preprocesado y construcción del dataset

**Objetivo**: Producir un DataFrame listo para modelizar.

- [ ] **Remuestreo**: Construir el dataset sobre una **rejilla uniforme de 10 min**: desagregación temporal de las series horarias AEMET (60 → 10 min), remuestreo del período histórico STM de 15 min y agregación de los registros recientes de 5 min. Precipitación tratada como acumulado; nivel y temperatura como estados instantáneos. (Método concreto de desagregación pendiente de decidir; justificar la elección.)
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

**Entregable**: `02_preprocessing.ipynb` + `data/processed/dataset_10min.parquet`

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

- [ ] **Persistencia**: `y_pred(t) = y(t-1)` — línea base trivial (obligatoria como referencia mínima).
- [ ] **Regresión lineal** con lags seleccionados.
- [ ] **ARIMA / SARIMAX**: ARIMA usa solo la historia del nivel; ARIMAX añade variables exógenas (precipitación, niveles aguas arriba).
- [ ] **Random Forest / Gradient Boosting (XGBoost/LightGBM)**: robustos, interpretables, manejan nulos bien.

**Métricas** (estándar en hidrología):
- NSE (*Nash-Sutcliffe Efficiency*) — métrica principal.
- KGE (*Kling-Gupta Efficiency*).
- RMSE y MAE.
- PBIAS (sesgo volumétrico).
- **Error en el pico** (magnitud) y **error en el timing del pico**.
- **Detección de excedencia de umbrales** y tasa de **falsas alarmas**.
- **Lead time / anticipación efectiva** de crecidas.
- Evaluación **por evento** (no solo agregada).

**Entregable**: `04_baselines.ipynb`

### Fase 5 — Modelos secuenciales

**Objetivo**: Capturar las dependencias temporales de largo alcance y producir predicciones **multi-horizonte (t+1h, t+6h, t+24h)**.

- [ ] **LSTM / GRU**: arquitectura encoder-decoder para predicción multi-step (salida simultánea a t+1/6/24h).
- [ ] **Temporal Fusion Transformer (TFT)**: estado del arte en series temporales multivariables, maneja covariables conocidas (meteo) y pasadas (hidro); multi-horizonte de forma nativa.
- [ ] Ajuste de hiperparámetros con *Optuna* o *Ray Tune*.
- [ ] Evaluación desglosada por horizonte de predicción (cuantificar la degradación de las métricas al aumentar el horizonte).

**Entregable**: `05_deep_learning.ipynb`

### Fase 5b — Modelo híbrido (HEC-HMS + ML)

**Objetivo**: Usar ML para corregir los errores del modelo físico.

- [ ] Entrenar un modelo ML (XGBoost o similar) que tome las salidas de HEC-HMS como features y aprenda a predecir el residual (diferencia entre nivel observado y simulado por HEC-HMS).
- [ ] Evaluar si la corrección híbrida mejora las métricas del modelo físico solo.

**Entregable**: Notebook `05b_hybrid.ipynb` (opcional, si el tiempo lo permite).

### Fase 6 — Interpretabilidad y análisis de resultados

- [ ] Feature importance (SHAP values) para entender qué predictores dominan.
- [ ] Análisis de errores: ¿el modelo falla más en crecidas o en estiajes?
- [ ] Curvas de error por umbral de caudal.
- [ ] Comparación de predicciones vs observaciones en eventos seleccionados.

**Entregable**: `06_interpretability.ipynb`

### Fase 7 — Comparación HEC-HMS vs. ML/IA

**Objetivo**: Confrontar el modelo físico con los modelos basados en datos sobre los mismos eventos y períodos.

- [ ] Evaluar ambas familias con las métricas comunes (NSE, KGE, RMSE, MAE, PBIAS) en train/val/test, desglosadas por horizonte de predicción (t+1/6/24h) en el caso de los modelos ML.
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

- ~~¿Está disponible un MDT de alta resolución (LiDAR o similar) para la cuenca de Sant Miquel?~~ — **Resuelto: disponible.**
- ~~¿Existe cartografía de usos del suelo y tipos de suelo para calcular el CN (Curve Number)?~~ — **Resuelto: disponible.**
- ¿Se dispone de aforos de caudales punta en eventos históricos para calibrar el modelo?
- ¿Las estaciones aguas arriba (STM03–STM07) actúan como puntos de control internos en la cuenca?

### Generales

- Curvas de aforo de STM08: ¿están calibradas para todo el período o cambian con el tiempo?
- Confirmación de la topología de la cuenca: ¿todas las STM drenan hacia Sa Marjal?
- STM09, STM10, STM11 (mencionadas en la bitácora): ¿están disponibles? Podrían añadir información.
- ~~Horizonte de predicción deseado: ¿nowcasting (t+1h) o previsión a t+6h, t+24h?~~ — **Resuelto: multi-horizonte t+1h, t+6h y t+24h.**

---

## 7. Referencias clave (estado del arte)

- Kratzert, F., et al. (2018). *Rainfall–runoff modelling using Long Short-Term Memory (LSTM) networks*. Hydrol. Earth Syst. Sci., 22, 6005–6022. — LSTM supera al modelo conceptual SAC-SMA en 241 cuencas (CAMELS).
- Lim, B., et al. (2021). *Temporal Fusion Transformers for interpretable multi-horizon time series forecasting*. International Journal of Forecasting. — Arquitectura TFT: multi-horizonte nativo e interpretable.
- Marasini, U. & Pokhrel, M. (2024). *Comparative analysis of rainfall-runoff simulation using an LSTM deep learning model and HEC-HMS: mountainous basin of Nepal*. Discover Civil Engineering. — LSTM > HEC-HMS en cuenca montañosa.
- Manjitha, H.H.U. & Perera, D. (2025). *HEC-HMS and machine learning approaches for streamflow forecasting: a comparative study* (Sri Lanka). — LSTM gana en cuencas húmeda y seca; HEC-HMS cae a NSE 0.49 en régimen seco.
- Belina, Y., et al. (2024). *Comparative analysis of HEC-HMS and machine learning models for rainfall-runoff prediction in the upper Baro watershed, Ethiopia*. Hydrology Research. — ANN NSE 0.98 vs HEC-HMS 0.85 en cuenca con datos escasos.
- Khan, I. (2026). *Comparative Analysis of HEC-HMS and Temporal Fusion Transformer for Streamflow Prediction under Climate Change Scenarios (Swat River Basin)*. — HEC-HMS subestima picos de crecida; TFT captura eventos extremos.
- Cho, M., et al. (2022). *Water Level Prediction Model Applying an LSTM–GRU Method for Flood Prediction*. Water, 14(14). — NSE 0.94 prediciendo nivel de agua.
- Frame, J. M., et al. (2022). *Deep learning rainfall–runoff predictions of extreme events*. Hydrol. Earth Syst. Sci., 26, 3377–3392. — Comportamiento de LSTM durante eventos extremos.
- Xiang, Z. & Demir, I. (2020). *Distributed long-term hourly streamflow predictions using deep learning*. Environmental Modelling & Software, 131, 104788. — LSTM seq2seq para rainfall–runoff.
- Koya, S. R. & Roy, T. (2024). *Temporal Fusion Transformer for streamflow prediction*. Journal of Hydrology, 631, 130694. — TFT vs. LSTM/Transformers.
- Fordjour, A. & Kalyanapu, A. (2024). *GRU-based flood prediction using multi-station water levels*. Water, 16(7), 993.
- Agaj, T., et al. (2024). *ARIMA/ETS for water level forecasting*. Water Practice & Technology, 19(3), 925–938.
- Szczepanek, R. (2022). *XGBoost/LightGBM/CatBoost for daily streamflow forecasting*. Applied Sciences, 12(14), 7045.
- USACE HEC-HMS case study — *Kaskaskia basin flood forecasting*.
- USACE HEC-HMS Applications Guide (documentación oficial).
- Trabajo futuro (híbridos): Makhloufi, N. (2026) — XGBoost como corrector de errores de HEC-HMS (KGE 0.65 → 0.83); Solanki, H., et al. (2025, Water Resources Research) — post-procesado de modelos hidrológicos con ML.

---

## 8. Action items (próximos pasos)

### Inmediatos (antes de modelizar)
- [x] EDA completado (`01_eda.ipynb`).
- [ ] Clarificar y documentar el significado de los **quality flags** y su política de tratamiento.
- [ ] Definir la **regla de detección de eventos** (criterios de inicio/fin) de forma reproducible.
- [ ] Construir las **4 tablas requeridas** por el tutor: stations, measurements, events, training.
- [ ] Generar la tabla de asignación de **eventos** (no filas) a train / validation / test.
- [ ] Contar y evaluar el número de **eventos de crecida utilizables** en el registro histórico (~12 años, régimen altamente intermitente — el TFT necesita suficientes eventos para entrenar).

### Fase 2 (preprocesado)
- [ ] Recuperar y preservar los **quality flags** en los CSVs limpios (actualmente no incluidos).
- [ ] Corregir el script `clean_STM02.py` para recuperar las fórmulas Excel de tipping-bucket en `PRECIP_mm`.
- [ ] Armonizar unidades/datums del tramo de extensión BD (spikes de 177 m, mesetas negativas, oscilaciones) — coordinar con el proveedor de datos.

### Documentación
- [ ] Referenciar al grupo como **RiscBal** (https://www.uib.eu/research/structures/structure/RiscBal/) en la memoria.
