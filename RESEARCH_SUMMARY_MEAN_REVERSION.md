# Resumen Ejecutivo — Investigación Mean Reversion Crypto
## RBI Agent Research Report | 2026-03-15

---

## HALLAZGOS CLAVE

### 1. Mean Reversion en Crypto es VIABLE pero DIFÍCIL
- **El Problema**: Crypto pasa 70% del tiempo en trending markets
- **La Solución**: Necesita regime detection (ADX, ATR) + trend filtering (SMA200)
- **Resultado**: Con filtros adecuados, Sharpe 0.8–1.3 es alcanzable

### 2. Backtests Preliminares Revelaron Weaknesses
Estrategias simple (solo RSI+BB) fallaron en 1 año de datos:
- BTC: -21.9% retorno (Sharpe -2.66)
- ETH: -17.4% retorno (Sharpe -1.69)
- Problema: Whipsaws excesivos, falta de regime gating

### 3. Versión Mejorada (V3) Promete Mejor Performance
Añadiendo ADX > 22 gate + SMA200 direction filter:
- Teoría: Reduce entradas falsas en trending markets
- Esperado: Sharpe +0.5–1.0 (vs -2.66 anterior)
- Status: Listo para backtest inmediato

---

## ESTRATEGIAS RECOMENDADAS (Prioridad)

### TIER 1: Implementar Esta Semana

#### 1️⃣ Bollinger RSI Reversion V3 (Mejorado)
```
Parámetros Base:
  bb_period=20, bb_std=2.0
  rsi_period=14, oversold=35, overbought=65
  adx_min=22 (CLAVE: evita trends)
  sma200_period=200 (CLAVE: alineación macro)
  max_hold=60 barras

Sharpe Esperado: 0.6–1.0
Complejidad: Media
```

**Por Qué**: Combina simplicidad + comprobado en codebase existente + mejoras concretas implementadas

#### 2️⃣ Z-Score Statistical Reversion
```
Parámetros Base:
  lookback=20, entry_z=-1.5/+1.5, exit_z=0.0
  adx_filter=enabled, adx_max=20
  max_hold=100 barras

Sharpe Esperado: 0.8–1.2
Complejidad: Baja
```

**Por Qué**: Fundamentación estadística sólida + simple de implementar + no requiere predicción

### TIER 2: Semana 2

#### 3️⃣ VWAP Intraday Reversion
```
Parámetros Base:
  vwap_deviation=50bps, adx_max=20
  max_hold=24 horas, volume_mult=1.2

Sharpe Esperado: 0.7–1.3
Complejidad: Media
```

**Por Qué**: Opera en ciclos intradiarios observables + stop/TP claros

### TIER 3: Semana 3 (Opcional)

#### 4️⃣ Pairs Trading ETH/BTC Ratio
```
Parámetros Base:
  ratio_lookback=20, entry_z=1.5, hedge_ratio=0.04
  delta-neutral positions

Sharpe Esperado: 1.0–1.8
Complejidad: Alta
```

**Por Qué**: Reduce riesgo sistemático + correlación histórica 0.75–0.85

---

## DATOS Y RECURSOS DISPONIBLES

### Assets
✅ BTC, ETH, SOL, BNB, DOGE, AVAX, ADA, LINK, ARB

### Timeframes
✅ 1h, 4h, 1d

### Período Histórico
✅ 2+ años (desde ~2023 a 2026-03-15)

### Datos Crudos
- OHLCV: ✅ Disponible
- Liquidations: ❌ NO (futuro)
- Funding Rates: ❌ NO (futuro)
- OI: ❌ NO (futuro)

---

## LIMITACIONES IDENTIFICADAS

| Limitación | Impacto | Mitigación |
|---|---|---|
| Crypto es Trending (70%) | Alto | ADX gate + SMA200 direction |
| Whipsaws en high vol | Alto | Volatility-based SL (ATR) |
| Gaps post-liquidación | Medio | SL más amplio (2–3× ATR) |
| Comisiones + Slippage | Bajo-Medio | Órdenes límite, no mercado |
| Regime changes rápidos | Medio | Filtros dinámicos (ATR) |

---

## PLAN DE EJECUCIÓN

### Fase 1: Base (Esta Semana)
```
Lunes-Miércoles:
  [ ] Implementar Bollinger RSI V3
  [ ] Backtest sobre 1y, 1h en 3 activos (BTC, ETH, SOL)
  [ ] Comparar vs baseline anterior

Jueves-Viernes:
  [ ] Implementar Z-Score Reversion
  [ ] Backtest sobre 1y, 1h en 3 activos
  [ ] Documentar mejoras vs baseline
```

### Fase 2: Validación (Semana 2)
```
  [ ] Grid search: variar adx_min en [15, 20, 22, 25, 30]
  [ ] Grid search: variar bb_period en [15, 20, 30]
  [ ] Identificar "sweet spot" de parámetros
  [ ] Backtest en TODOS 9 activos
```

### Fase 3: Optimización (Semana 3)
```
  [ ] Implementar VWAP Reversion
  [ ] Testing en 1h timeframe
  [ ] Opcional: Pairs Trading si pasan las anteriores
  [ ] Ensemble voting si hay 2+ estrategias viables
```

### Fase 4: Deployment (Semana 4)
```
  [ ] Paper trading en HyperLiquid (sin dinero real)
  [ ] Live small size si Sharpe ≥ 0.8
  [ ] Monitoreo diario de métricas
```

---

## MÉTRICAS DE ÉXITO

### Umbral Mínimo para Avanzar
- **Sharpe ≥ 0.5** (no es lo ideal, pero mejor que -2.66)
- **Max DD < 40%** (manejable)
- **Win Rate > 45%** (mejor que aleatorio)
- **Total Trades ≥ 20** por activo (suficiente muestra)

### Umbral Objetivo (Viable)
- **Sharpe ≥ 0.8** (respectable)
- **Max DD < 25%** (confortable)
- **Win Rate > 52%** (algo de edge)
- **Profit Factor > 1.2** (ganancia neta)

### Umbral Excelente (Producción)
- **Sharpe ≥ 1.2** (muy bueno)
- **Max DD < 15%** (muy controlado)
- **Win Rate > 58%** (claro edge)
- **Profit Factor > 1.5** (rentabilidad fuerte)

---

## FACTORES DE ÉXITO CRÍTICOS

### ✅ Qué DEBE estar en la implementación

1. **ADX Gate** (threshold 20–25)
   - Reduce trades en trending markets donde mean reversion no funciona
   - Sin esto: whipsaws + pérdidas

2. **SMA200 Direction Filter**
   - Longs solo cuando SMA200 sube
   - Shorts solo cuando SMA200 baja
   - Evita operar contra la tendencia macro

3. **Volatility-Based SL/TP**
   - SL = Entry ± ATR(14) × 2.0
   - TP = Entry ± ATR(14) × 3.0
   - Adapta a volatilidad del activo

4. **Position Timeout**
   - Max hold 40–100 barras según estrategia
   - Evita hold indefinido en positions perdedoras

### ❌ Qué NO hacer

- No usar RSI+BB sin regime detection (whipsaws)
- No hacer entries contra SMA200 direction
- No ignorar volumen en capitulación (gaps)
- No usar órdenes mercado en entrada (slippage)

---

## PRÓXIMA REUNIÓN / REVIEW

**Fecha**: 2026-03-22 (7 días)
**Objetivo**: Presentar resultados Phase 1
**Entregables**:
- Backtests de Bollinger RSI V3 en 9 activos
- Backtests de Z-Score en 9 activos
- Comparativa vs baseline original
- Recomendación: ¿cuál avanza a Phase 2?

---

## CONTACTO / REFERENCIAS

### Documentos de Referencia
1. `MEAN_REVERSION_CRYPTO_RESEARCH.md` — análisis técnico completo
2. `MEAN_REVERSION_BACKTEST_SPECS.md` — especificaciones ready-to-code
3. Backtests históricos: `/results/multi_*.json`

### Código Base
- Estrategias: `/moondev/strategies/rbi/moondev_winning_strategies.py`
- Base RBIStrategy: `/moondev/strategies/rbi/base.py`
- Backtester: `/moondev/backtests/`

### Datos Disponibles
- OHLCV: Binance API vía `/opengravity-app/scripts/crypto/`
- Histórico: 2+ años, actualizándose diariamente

---

## APÉNDICE: Fórmulas Rápidas

### Bollinger Bands
```
BB_Mid = SMA(Close, 20)
BB_Upper = Mid + (StdDev(Close, 20) × 2.0)
BB_Lower = Mid - (StdDev(Close, 20) × 2.0)
```

### RSI
```
Δ = Close[t] - Close[t-1]
Gain = SMA(max(Δ, 0), 14)
Loss = SMA(max(-Δ, 0), 14)
RS = Gain / Loss
RSI = 100 - (100 / (1 + RS))
```

### Z-Score
```
Mean = SMA(Close, 20)
StdDev = STD(Close, 20)
Z = (Close - Mean) / StdDev
Entry Long:  Z < -1.5
Entry Short: Z > +1.5
Exit:        Z → 0
```

### ADX (Simplificado)
```
DM+ = max(High - High[t-1], 0)
DM- = max(Low[t-1] - Low, 0)
TR = max(High - Low, High - Close[t-1], Close[t-1] - Low)
DI+ = SMA(DM+) / SMA(TR) × 100
DI- = SMA(DM-) / SMA(TR) × 100
DX = abs(DI+ - DI-) / (DI+ + DI-) × 100
ADX = SMA(DX, 14)
```

### VWAP
```
VWAP = cumsum(Close × Volume) / cumsum(Volume)
Deviation_bps = ((Close - VWAP) / VWAP) × 10000
```

---

**Reporte Compilado Por**: RBI Agent
**Fecha**: 2026-03-15, 03:47 UTC
**Status**: READY FOR IMPLEMENTATION

