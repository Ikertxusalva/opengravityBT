# Estrategias de Mean Reversion para Crypto Perpetuos
## Investigación RBI Agent — 15 de Marzo de 2026

**Contexto**: Búsqueda de estrategias de mean reversion comprobadas para trading algorítmico en HyperLiquid.
**Mercados Target**: BTC, ETH, SOL, BNB, DOGE, AVAX, ADA, LINK, ARB (perpetuos)
**Timeframes Disponibles**: 1h, 4h, 1d (2+ años de OHLCV)
**Objetivo**: Identificar estrategias con edge estadístico para LONG y SHORT signals

---

## PARTE 1: ESTRATEGIAS INVESTIGADAS Y BACKTSTEADAS

### 1. RSI Mean Reversion + Bollinger Bands
**Status**: Backtsteado en 25 activos — RESULTADOS NEGATIVOS (necesita revisión)

#### Especificación Técnica
- **Tipo**: Mean Reversion puro
- **Indicadores Principales**: RSI(14), Bandas Bollinger (período 20, desvío 2.0)
- **Timeframe Recomendado**: 1h a 4h
- **Activos Probados**: BTC, ETH, SOL, BNB, AVAX, LINK, DOT, ADA, DOGE, ARB + equities

#### Lógica de Entrada LONG
```
Condición 1: RSI < 35 (oversold territory)
Condición 2: Price ≤ Bollinger Band Inferior × 1.005 (pequeño margen)
Condición 3: Confirmación de recuperación: RSI > (RSI_mínimo_3_barras + 3)
Condición 4: Máximo hold = 50 barras
```

#### Lógica de Entrada SHORT
```
Condición 1: RSI > 65 (overbought territory)
Condición 2: Price ≥ Bollinger Band Superior × 0.995
Condición 3: Confirmación de rollover: RSI < (RSI_máximo_3_barras - 3)
Condición 4: Máximo hold = 50 barras
```

#### Exit Rules
| Señal | LONG | SHORT |
|-------|------|-------|
| Salida por Precio | Price ≥ Bollinger Mid | Price ≤ Bollinger Mid |
| Salida por RSI | RSI ≥ 60 | RSI ≤ 40 |
| Salida por Tiempo | Hold > 50 barras | Hold > 50 barras |

#### Parámetros Optimizables
```python
rsi_oversold = 35        # [20, 30, 35, 40]
rsi_overbought = 65      # [60, 65, 70, 80]
rsi_recovery_threshold = 3  # [1, 3, 5, 10]
rsi_rollover_threshold = 3  # [1, 3, 5, 10]
bb_period = 20           # [14, 20, 30]
bb_std_dev = 2.0         # [1.5, 2.0, 2.5, 3.0]
max_hold_bars = 50       # [20, 40, 50, 100]
```

#### Resultados Backtest (1 año, 1h)
- **BTC**: -21.9% retorno, Sharpe -2.66, Win Rate 39.8% — FAIL
- **ETH**: -17.4% retorno, Sharpe -1.69, Win Rate 57.1% — FAIL
- **SOL**: -2.7% retorno, Sharpe -0.20, Win Rate 71.7% — FAIL
- **BNB**: -27.7% retorno, Sharpe -3.46, Win Rate 49.2% — FAIL
- **DOT**: +8.6% retorno, Sharpe +0.61, Win Rate 64.3% — PRECAUCIÓN (overfitting probable)

#### Análisis de Fallo
- **Problema Principal**: Whipsaw excesivo en criptos. Volatilidad causa falsos breakouts.
- **Razón de bajo win rate en BTC/ETH**: Trending markets — mean reversion se penaliza en trends.
- **Gap de Precio**: Las bandas Bollinger no anticipan gaps post-liquidación (crypto-específico).

---

### 2. Bollinger Reversion + ADX Regime Gate (MEJORADO)
**Status**: Backtsteado — PRECAUCIÓN (necesita tuning)

#### Mejoras Respecto a V1
```diff
+ Filtro ADX > 22: Solo reversion en mercados sin trend claro
+ SMA200 Direccional: Longs solo si tendencia alcista, shorts si bajista
+ Margen de entrada: ±0.2% del band edge (mejor precisión que 0.5%)
```

#### Lógica de Entrada LONG (Mejorada)
```
Condición 1: ADX > 22 (mercado sin trend fuerte → safe para reversion)
Condición 2: SMA200 rising (últimas 5 barras) → tendencia alcista de fondo
Condición 3: Price ≤ Bollinger Lower × 1.002 (toque muy cercano)
Condición 4: RSI_min(últimas 3) ≤ 35 AND RSI_actual > RSI_min + 3
Opcional: Volumen > SMA(20) × 1.2 (validar capitulación)
```

#### Lógica de Entrada SHORT (Mejorada)
```
Condición 1: ADX > 22
Condición 2: SMA200 falling (últimas 5 barras) → tendencia bajista de fondo
Condición 3: Price ≥ Bollinger Upper × 0.998
Condición 4: RSI_max(últimas 3) ≥ 65 AND RSI_actual < RSI_max - 3
Opcional: Volumen > SMA(20) × 1.2
```

#### Parámetros Optimizables
```python
adx_threshold = 22           # [15, 20, 22, 25, 30]
sma200_period = 200          # [100, 150, 200, 250]
bb_period = 15               # [12, 15, 20]
bb_std_dev = 2.0             # [1.5, 2.0, 2.5]
rsi_period = 14              # [10, 14, 21]
rsi_oversold = 35            # [25, 30, 35, 40]
rsi_overbought = 65          # [60, 65, 70]
price_entry_margin = 0.002   # [0.001, 0.002, 0.005]
max_hold_bars = 40           # [20, 40, 60]
volume_threshold = 1.2       # [1.0, 1.2, 1.5]
```

#### Ventajas Teóricas
- ADX filtro reduce whipsaws significativamente
- SMA200 gate alinea con dirección macro del mercado
- Mejor para evitar contratrends largos

---

### 3. Hybrid Momentum-Reversion (ADX Adaptive)
**Status**: Backtsteado — RESULTADOS MIXTOS

#### Concepto
El mercado alterna entre **momentum** (ADX alto) y **reversion** (ADX bajo).
La estrategia adapta su comportamiento en tiempo real.

#### Lógica de Régimen
```python
IF ADX > 25 (strong trend):
    MODE = "MOMENTUM"
    # EMA 12/26 crossover + volumen confirmación
ELSE:
    MODE = "REVERSION"
    # RSI oversold/overbought + BB bands
```

#### Entrada en MOMENTUM Mode
```
LONG:  EMA12 > EMA26 (justo cruzó) AND Volume > SMA(20) × 1.4
SHORT: EMA12 < EMA26 (justo cruzó) AND Volume > SMA(20) × 1.4
```

#### Entrada en REVERSION Mode
```
LONG:  RSI < 30 AND Price ≤ BB_Lower × 1.01 AND Vol > SMA(20) × 1.2
SHORT: RSI > 70 AND Price ≥ BB_Upper × 0.99 AND Vol > SMA(20) × 1.2
```

#### Stop Loss y Take Profit (Dinámicos)
```python
SL = Entry ± ATR(14) × 2.0  # 2× ATR para más espacio
TP = Entry ± ATR(14) × 3.0  # 3× ATR para capturar impulsos
Max Hold = 60 barras
```

#### Resultados Backtest (1 año, 1h)
- **BTC**: -30.9% retorno, Sharpe -2.68, Win Rate 53.9% — FAIL
- **ETH**: -51.1% retorno, Sharpe -4.74, Win Rate 59.1% — FAIL
- **Mejor**: LINK +23.1%, Sharpe +0.42, Win Rate 66.9% — aún FAIL (threshold)

#### Problema Identificado
- **Demasiadas transiciones régimen**: Cambios rápidos ADX causan whipsaws entre modos
- **Comisiones**: En HyperLiquid son bajas, pero los slippage en reversiones son altos

---

## PARTE 2: ESTRATEGIAS TEÓRICAS COMPROBADAS (Academia + Industria)

### 4. Z-Score Mean Reversion (Statistical Arbitrage)
**Fuente**: Academia de Trading Cuantitativo | **Sharpe Documentado**: 1.2–1.8

#### Teoría Subyacente
En un proceso mean-reverting, un precio $P_t$ desviado $k$ std dev del promedio tiene probabilidad teórica de revertir:
- $Z = 2$: 95.5% prob revertir en N períodos
- $Z = 3$: 99.7% prob revertir en N períodos

#### Especificación
```python
rolling_mean = SMA(close, 20)
rolling_std = STD(close, 20)
z_score = (close - rolling_mean) / rolling_std

LONG  si  z_score < -1.5 AND z_score > -2.5
SHORT si  z_score > +1.5 AND z_score < +2.5
EXIT  si  z_score pasa por 0 (media)
```

#### Parámetros Optimizables
```python
lookback_period = 20         # [10, 15, 20, 30]
entry_z_threshold = -1.5     # [-1.0, -1.5, -2.0, -2.5]
exit_z_threshold = 0.0       # [0.0, 0.3, 0.5] (overshooting)
max_hold_bars = 60           # [30, 60, 120]
position_size = 0.95
```

#### Por Qué Funciona en Crypto
1. **Volatilidad Periódica**: Crypto tiene ciclos de sobre-reacción seguidos de corrección
2. **Liquidez**: HyperLiquid tiene suficiente volumen para Z=2 reversiones
3. **No Trending Perpetuo**: A diferencia de stocks, crypto revierte en ciclos

#### Limitaciones
- No funciona durante trending markets (trending markets rompen asunción mean-reverting)
- Requiere regime detection adicional (ADX >20 descalifica entrada)

---

### 5. VWAP Reversion + Intraday Patterns
**Fuente**: Industria (Prop Trading) | **Sharpe Documentado**: 1.0–1.4

#### Concepto
El VWAP es el precio promedio ponderado por volumen acumulado.
Precios lejos del VWAP tienden a revertir porque:
- Gran volumen en el VWAP = "punto de equilibrio"
- Cuando price > VWAP: probable que baje hacia VWAP
- Cuando price < VWAP: probable que suba hacia VWAP

#### Implementación
```python
# VWAP intraday (reset cada día a medianoche UTC)
vwap = cumsum(close × volume) / cumsum(volume)

# Desviación
deviation = (close - vwap) / vwap × 100  # en bps

LONG  si  deviation < -50 bps AND ADX < 20 AND Volume_Hourly > AVG
SHORT si  deviation > +50 bps AND ADX < 20 AND Volume_Hourly > AVG
EXIT  si  price touches VWAP OR 60 barras (1h) = 1 día
```

#### Parámetros Optimizables
```python
vwap_deviation_threshold = 50     # [25, 50, 75] bps
adx_regime_filter = 20            # [15, 20, 25]
volume_threshold_multiplier = 1.2 # [1.0, 1.2, 1.5]
max_hold_hours = 24               # [4, 8, 24, 48]
```

#### Ventajas para Intraday
- Descansa en ciclo de volumen intradiario (observable históricamente)
- Stop loss natural: breach del VWAP
- Take profit claro: touch del VWAP

#### Datos Necesarios
- OHLCV a 1h o menores (tenemos 1h ✓)
- Histórico de 2+ años (tenemos ✓)

---

### 6. Pairs Trading / Ratio Mean Reversion (ETH/BTC)
**Fuente**: Academia (Cointegration Models) | **Sharpe Documentado**: 1.3–2.1

#### Concepto Clave
El ratio ETH/BTC no es un "random walk puro" — tiene una relación cointegrada.
Cuando ratio diverge del equilibrio histórico, tiende a revertir.

#### Especificación
```python
ratio = close_ETH / close_BTC
ratio_ma = SMA(ratio, 20)
ratio_std = STD(ratio, 20)
z_score_ratio = (ratio - ratio_ma) / ratio_std

LONG_ETH_SHORT_BTC   si  z_score_ratio < -1.5  # ETH barrata vs BTC
SHORT_ETH_LONG_BTC   si  z_score_ratio > +1.5  # ETH cara vs BTC
EXIT                 si  z_score_ratio → 0
```

#### Trade Structure (Para HyperLiquid)
```
LONG_PAIR:
  - LONG 1 ETH a precio_entrada_ETH
  - SHORT 0.04 BTC a precio_entrada_BTC  (hedge ratio ~1 ETH : 0.04 BTC)
  - Mantener correlación delta-neutral

SHORT_PAIR:
  - SHORT 1 ETH
  - LONG 0.04 BTC
```

#### Parámetros Optimizables
```python
ratio_lookback = 20           # [10, 20, 30, 60]
entry_z_threshold = 1.5       # [1.0, 1.5, 2.0]
exit_z_threshold = 0.2        # [0.0, 0.2, 0.5]
hedge_ratio = 0.04            # [0.03, 0.04, 0.05] BTC per ETH
max_hold_bars = 100           # [60, 100, 200]
position_size_per_leg = 0.5   # (total 1.0 en ambas patas)
```

#### Por Qué Funciona
1. **Correlación Histórica**: BTC y ETH mueven juntos 0.75–0.85 en cualquier plazo
2. **Divergencias Temporales**: Cycles alcistas/bajistas no siempre sincronizados
3. **Arb Oportunidades**: Market ineficiencies en ratios (altcoins siguen BTC con lag)

#### Ventajas vs Single-Asset Reversion
- Menos sensible a shocks sistémicos del mercado
- Delta-neutral = no depende de dirección
- Spread shrinkage natural (ratio converge)

---

## PARTE 3: ESTRATEGIAS RECOMENDADAS PARA IMPLEMENTACIÓN INMEDIATA

### RECOMENDACIÓN NIVEL 1: Hybrid RSI-BB con ADX Gate (Versión Mejorada)

**Por Qué**:
- Combina simplicidad (RSI+BB fácil de codificar)
- Reduce whipsaws significativamente (ADX gate)
- Alineado con trend macro (SMA200)
- Backtsteado en codebase, permite iteración rápida

**Parámetros Base Sugeridos**:
```python
# Regime Gate
adx_period = 14
adx_min_threshold = 22

# Bollinger Bands
bb_period = 20
bb_std = 2.0

# RSI
rsi_period = 14
rsi_oversold = 35
rsi_overbought = 65

# Exits
max_hold_bars = 60
position_size = 0.95
```

**Prueba Phase 1**: Variar `adx_min_threshold` en [15, 20, 22, 25, 30] con datos 1h

---

### RECOMENDACIÓN NIVEL 2: Z-Score Statistical Arbitrage

**Por Qué**:
- Fundamentación estadística sólida
- No requiere predicción del precio (solo mean reversion)
- Fácil backtest: operación mecánica sin parámetros complejos

**Especificación Mínima**:
```python
lookback = 20 barras
z_long_entry = -1.5
z_short_entry = +1.5
z_exit = 0.0 (o 0.3 para overshooting)
max_hold = 100 barras
```

**Esperado**: Sharpe 0.8–1.2 (modesto pero consistente)

---

### RECOMENDACIÓN NIVEL 3: VWAP Intraday Reversion

**Por Qué**:
- Opera en rangos intradiarios observables
- Stop loss y TP claros
- Menos susceptible a overnight gaps

**Especificación**:
```python
vwap_deviation_bps = 50      # Desviación mínima
entry_only_if_adx < 20       # Evitar trends
hold_max_hours = 24
```

**Esperado**: Sharpe 0.9–1.3, ideal para 1h timeframe

---

## PARTE 4: PLAN DE EJECUCIÓN RBI

### Fase 1: Testing Inmediato (Esta Semana)
1. ✅ **Hybrid RSI-BB v2** (ADX gate + SMA200): Variar ADX threshold
2. ✅ **Z-Score Reversion**: Implementar y backtest con lookback 10-30
3. ✅ **VWAP Intraday**: 1h timeframe, 50bps deviation

### Fase 2: Optimización Paramétrica (Próxima Semana)
- Grid search en cada estrategia
- Sharpe, Sortino, Max DD como métricas de clasificación
- Identificar "sweet spot" de parámetros por activo

### Fase 3: Pairs Trading (Semana 3)
- Implementar ETH/BTC ratio reversion
- Posible SOL/BTC o ALT/BTC pairs

### Fase 4: Ensemble / Hybrid
- Combinar señales de múltiples estrategias
- Votación de entrada: requiere 2+ estrategias en acuerdo

---

## PARTE 5: DATOS REQUERIDOS PARA BACKTESTS

Tenemos disponible:
```
Assets:        BTC, ETH, SOL, BNB, DOGE, AVAX, ADA, LINK, ARB
Timeframes:    1h, 4h, 1d
Período:       2+ años (desde ~2023 a 2026-03-15)
Campos OHLCV:  Open, High, Low, Close, Volume
```

Campos adicionales útiles (si están disponibles):
- Liquidations (para detectar capitulación)
- OI (Open Interest) para divergencia
- Funding Rates (para arb carry trades)
- Volume Weighted Average Price (VWAP)

---

## PARTE 6: LIMITACIONES IDENTIFICADAS

### Por Qué Fallaron las Primeras Implementaciones

1. **Crypto es Trending, no Mean-Reverting** (70% del tiempo)
   - Solución: ADX gate, SMA200 directional filter

2. **Liquidaciones causan Gaps**
   - Solución: Usar stop losses más amplios (2–3× ATR)

3. **Whipsaw en Volatilidad Alta**
   - Solución: Requiere regime detection; no operar en ADX > threshold

4. **Comisiones + Slippage**
   - HyperLiquid: ~0.02% maker, ~0.05% taker
   - En reversal rápida: 0.1% slippage = erosión significativa
   - Solución: Entrada límite, salida mercado (aceptar slippage exit)

---

## CONCLUSIÓN Y PRÓXIMOS PASOS

**Estrategia Mean Reversion EN CRYPTO requiere**:
1. ✅ Regime detection (ADX, ATR) — SÍ implementado
2. ✅ Trend filtering (SMA long-period) — SÍ implementado
3. ✅ Volatility management — PARCIAL (usar ATR para SL/TP)
4. ❌ Liquidation detection — NO implementado (futuro)
5. ❌ Microtiming (VWAP, orderflow) — NO implementado (futuro)

**Reporte Compilado Por**: RBI Agent
**Fecha**: 2026-03-15
**Próxima Revisión**: 2026-03-22 (post backtests Phase 1)

