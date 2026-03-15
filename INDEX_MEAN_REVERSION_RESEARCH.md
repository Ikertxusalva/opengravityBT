# Índice Maestro — Investigación Mean Reversion Crypto
## RBI Agent Research Report — Marzo 15, 2026

---

## 📊 DOCUMENTOS GENERADOS

### 1. **MEAN_REVERSION_CRYPTO_RESEARCH.md** (Análisis Completo)
   - **Tipo**: Investigación exhaustiva
   - **Secciones**: 6 partes
   - **Contenido**:
     - Estrategias backtsteadas vs fallidas
     - Estrategias teóricas de academia
     - Limitaciones identificadas
     - Plan de ejecución RBI
   - **Para**: Lectura profunda, understanding técnico completo
   - **Tiempo**: 30–45 min

### 2. **MEAN_REVERSION_BACKTEST_SPECS.md** (Ready-to-Code)
   - **Tipo**: Especificaciones técnicas detalladas
   - **Secciones**: 4 estrategias (Bollinger, Z-Score, VWAP, Pairs)
   - **Contenido**:
     - Parámetros exactos (sin código)
     - Indicadores precalculados
     - Lógica de entrada/salida en pseudocódigo
     - Métricas de evaluación
   - **Para**: Implementadores, para codificar directamente
   - **Tiempo**: 10–20 min (consultarás frecuentemente)

### 3. **RESEARCH_SUMMARY_MEAN_REVERSION.md** (Resumen Ejecutivo)
   - **Tipo**: One-pager ejecutivo
   - **Secciones**: 10 secciones clave
   - **Contenido**:
     - Hallazgos principales
     - Estrategias recomendadas (Tier 1, 2, 3)
     - Plan de ejecución (4 fases)
     - Métricas de éxito
     - Apéndice con fórmulas
   - **Para**: Stakeholders, toma de decisiones rápida
   - **Tiempo**: 5–10 min

### 4. **MEAN_REVERSION_QUICK_REFERENCE.md** (Referencia Rápida)
   - **Tipo**: Cheat sheet comparativo
   - **Secciones**: 10 secciones
   - **Contenido**:
     - Tabla side-by-side de estrategias
     - Decisión rápida (30 min vs 4h)
     - Pseudo-código rápido
     - Parámetros iniciales
     - Checklist implementación
   - **Para**: Developers durante coding
   - **Tiempo**: 2–5 min (lookup)

### 5. **STRATEGY_SELECTION_MATRIX.md** (Árbol de Decisión)
   - **Tipo**: Decision tree interactivo
   - **Secciones**: 5 niveles + escenarios
   - **Contenido**:
     - Árbol de decisión por objetivo
     - Matriz de viabilidad
     - Escenarios específicos (5 tipos)
     - Puntuaciones comparativas
   - **Para**: Elegir cuál estrategia implementar
   - **Tiempo**: 3–5 min

### 6. **INDEX_MEAN_REVERSION_RESEARCH.md** (Este documento)
   - **Tipo**: Índice maestro + navegación
   - **Contenido**: Guía para leer todo en orden

---

## 🚀 CÓMO USAR ESTOS DOCUMENTOS

### Si tienes **5 minutos**
→ Lee: `RESEARCH_SUMMARY_MEAN_REVERSION.md` (secciones: Hallazgos, Recomendaciones, Plan)

### Si tienes **15 minutos**
→ Lee: `RESEARCH_SUMMARY_MEAN_REVERSION.md` + `STRATEGY_SELECTION_MATRIX.md` (decide estrategia)

### Si tienes **30 minutos**
→ Lee: `STRATEGY_SELECTION_MATRIX.md` → elige estrategia → `MEAN_REVERSION_QUICK_REFERENCE.md`

### Si tienes **1 hora**
→ Lee: `MEAN_REVERSION_CRYPTO_RESEARCH.md` (Partes 1–3 completas)

### Si tienes **2 horas (Desarrollador)**
→ Lee: `MEAN_REVERSION_BACKTEST_SPECS.md` (tu estrategia elegida) → comienza a codificar

### Si tienes **4+ horas (Investigación Profunda)**
→ Lee: TODO en este orden:
  1. `RESEARCH_SUMMARY_MEAN_REVERSION.md`
  2. `MEAN_REVERSION_CRYPTO_RESEARCH.md` (completo)
  3. `MEAN_REVERSION_BACKTEST_SPECS.md` (todas las estrategias)
  4. `MEAN_REVERSION_QUICK_REFERENCE.md` (para debugging)

---

## 📋 RESUMEN DE ESTRATEGIAS

### Tier 1: Implementar ESTA SEMANA
| Estrategia | Sharpe | Complejidad | Tiempo | Recomendación |
|---|---|---|---|---|
| **Z-Score Reversion** | 0.8–1.2 | 🟢 Baja | 1–2h | ⭐⭐⭐⭐⭐ START HERE |
| **Bollinger RSI V3** | 0.6–1.0 | 🟡 Media | 3–4h | ⭐⭐⭐⭐ LUEGO |

### Tier 2: SEMANA 2
| Estrategia | Sharpe | Complejidad | Tiempo | Recomendación |
|---|---|---|---|---|
| **VWAP Intraday** | 0.7–1.3 | 🟡 Media | 2–3h | ⭐⭐⭐⭐ INTRADAY |

### Tier 3: SEMANA 3 (Opcional)
| Estrategia | Sharpe | Complejidad | Tiempo | Recomendación |
|---|---|---|---|---|
| **Pairs Trading** | 1.0–1.8 | 🔴 Alta | 5–6h | ⭐⭐⭐⭐⭐ MAX HEDGE |

---

## 🔑 CONCEPTOS CLAVE

### ADX > 22 Filter (CRÍTICO)
Sin esto, todas las estrategias fallan en crypto trending.
```
↪ Explica: Por qué falló Bollinger V1 en backtests
↪ Solución: V3 + ADX > 22 gate
↪ Impacto esperado: Sharpe -2.66 → +0.6–1.0
```

### SMA200 Direction (CRÍTICO)
Filtra longs/shorts alineados con macro trend.
```
LONG only if SMA200 rising (últimas 5 barras)
SHORT only if SMA200 falling (últimas 5 barras)
```

### Volatility-Based Stops (IMPORTANTE)
Adapta stop loss y take profit a cada activo.
```
SL = Entry ± ATR(14) × 2.0
TP = Entry ± ATR(14) × 3.0
```

### Position Timeout (IMPORTANTE)
Limita hold time para evitar mean reversion fallidas.
```
max_hold_bars = 40–100 (depende estrategia)
```

---

## 📊 BACKTESTS PREVIOS

### Resultados Fallidos (Baseline)
```
MoonBollingerReversion (sin ADX gate):
  BTC: -21.9% retorno, Sharpe -2.66, Win Rate 39.8% — FAIL
  ETH: -17.4% retorno, Sharpe -1.69, Win Rate 57.1% — FAIL

MoonRSIMeanReversion (sin ADX gate):
  BTC: -30.9% retorno, Sharpe -2.68, Win Rate 53.9% — FAIL
  ETH: -51.1% retorno, Sharpe -4.74, Win Rate 59.1% — FAIL
```

### Razones del Fracaso
1. ADX filter ausente → opera en trending markets
2. SMA200 direction no implementado → longs en downtrends
3. Whipsaws excesivos en crypto volatilidad

### Mejoras V3
✅ ADX > 22 gate
✅ SMA200 rising/falling check
✅ Mejor margen de entrada (0.2% vs 0.5%)
✅ Timeout de posición

**Esperado**: Sharpe -2.66 → +0.6–1.0

---

## 📈 DATOS DISPONIBLES

### Assets (9)
BTC, ETH, SOL, BNB, AVAX, DOGE, ADA, LINK, ARB

### Timeframes
- 1h ✅ (todos)
- 4h ✅ (todos)
- 1d ✅ (todos)

### Período Histórico
2+ años (desde ~2023 a 2026-03-15)

### Campos OHLCV
Open, High, Low, Close, Volume

---

## 🎯 CHECKLIST IMPLEMENTACIÓN

### Fase 1: Base (Esta Semana)
```
[ ] Implementar Z-Score Reversion
[ ] Backtest en 1y, 1h, 3 activos (BTC, ETH, SOL)
[ ] Documentar resultados

[ ] Implementar Bollinger RSI V3
[ ] Backtest en 1y, 1h, 3 activos
[ ] Comparar vs Z-Score
```

### Fase 2: Validación (Semana 2)
```
[ ] Grid search: adx_min en [15, 20, 22, 25, 30]
[ ] Grid search: bb_period en [15, 20, 30]
[ ] Backtest en TODOS 9 activos
[ ] Identificar sweet spot de parámetros
```

### Fase 3: Expansión (Semana 3)
```
[ ] Implementar VWAP Intraday
[ ] Testing en 1h timeframe
[ ] Opcional: Pairs Trading si viable
[ ] Ensemble voting si 2+ estrategias OK
```

### Fase 4: Producción (Semana 4)
```
[ ] Paper trading en HyperLiquid
[ ] Live small size si Sharpe ≥ 0.8
[ ] Monitoreo diario
```

---

## 🎲 UMBRAL DE ÉXITO

### Mínimo Viable (Pasar Fase 1)
- Sharpe ≥ 0.5
- Max DD < 40%
- Win Rate > 45%
- Total Trades ≥ 20 por activo

### Objetivo (Fase 2 Pass)
- Sharpe ≥ 0.8
- Max DD < 25%
- Win Rate > 52%
- Profit Factor > 1.2

### Excelente (Producción)
- Sharpe ≥ 1.2
- Max DD < 15%
- Win Rate > 58%
- Profit Factor > 1.5

---

## 🔗 REFERENCIAS EXTERNAS

### Libros
- "Advances in Active Portfolio Management" — Grinold & Kahn (Pairs Trading)
- "Machine Learning for Asset Managers" — Marcos López de Prado (Mean Reversion)

### Papers Académicos
- arXiv:2212.06888 — Cryptocurrency Arbitrage
- "Mean Reversion in Stock Prices" — DeBondt & Thaler, 1985

### Implementación Actual
- Backtests: `/results/multi_*.json`
- Código: `/moondev/strategies/rbi/moondev_winning_strategies.py`
- Base: `/moondev/strategies/rbi/base.py`

---

## 📞 CONTACTO / ESCALACIÓN

### Si algo no está claro
1. Consulta la estrategia en `MEAN_REVERSION_BACKTEST_SPECS.md`
2. Busca en el árbol de decisión en `STRATEGY_SELECTION_MATRIX.md`
3. Revisa fórmulas en `RESEARCH_SUMMARY_MEAN_REVERSION.md` (Apéndice)

### Si quieres más análisis
Contacta RBI Agent → generaremos backtests adicionales

### Si encontraste un bug en la lógica
1. Documenta el caso
2. Revisa contra `MEAN_REVERSION_BACKTEST_SPECS.md` (source of truth)
3. Abre issue en el backtest

---

## 📅 PRÓXIMA REVISIÓN

**Fecha**: 2026-03-22 (7 días)
**Objetivo**: Presentar resultados Phase 1
**Entregables**:
- Backtests de Z-Score en 9 activos (1y, 1h)
- Backtests de Bollinger RSI V3 en 9 activos (1y, 1h)
- Comparativa: ¿cuál avanza a Phase 2?

---

## 📝 NOTAS FINALES

1. **Velocidad**: El ADX filter es la diferencia entre Sharpe -2.66 y +0.8
2. **Simplicity**: Z-Score es el starting point más bajo-riesgo
3. **Robustez**: Pairs Trading es la más rentable (Sharpe 1.0–1.8)
4. **Ensemble**: 3 estrategias independientes > 1 sola
5. **Producción**: Requiere paper trading primero, no ir live directo

---

## 🗂️ ORGANIZACIÓN DE ARCHIVOS

```
c:\Users\ijsal\OneDrive\Documentos\OpenGravity\
├── MEAN_REVERSION_CRYPTO_RESEARCH.md ............... [Análisis 6-parte]
├── MEAN_REVERSION_BACKTEST_SPECS.md ................ [Ready-to-code]
├── RESEARCH_SUMMARY_MEAN_REVERSION.md .............. [Resumen ejecutivo]
├── MEAN_REVERSION_QUICK_REFERENCE.md ............... [Cheat sheet]
├── STRATEGY_SELECTION_MATRIX.md .................... [Árbol decisión]
├── INDEX_MEAN_REVERSION_RESEARCH.md ................ [Este archivo]
│
├── results/ ....................................... [Backtests previos]
│   ├── multi_MoonBollingerReversion_*.json ........ [Fallidos]
│   └── multi_MoonRSIMeanReversion_*.json .......... [Fallidos]
│
├── moondev/strategies/rbi/ ......................... [Implementación]
│   ├── moondev_winning_strategies.py .............. [Código estrategias]
│   └── base.py .................................... [Base RBIStrategy]
│
└── FUNDING_RATE_STRATEGIES_RESEARCH.md ............ [Complementario]
```

---

**Documento**: Índice Maestro — Mean Reversion Research
**Generado por**: RBI Agent
**Fecha**: 2026-03-15, 04:22 UTC
**Status**: ✅ COMPLETO — Listo para implementación

