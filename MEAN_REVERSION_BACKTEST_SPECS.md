# Especificaciones Detalladas para Backtests - Mean Reversion
## Ready-to-Code Specifications

**Objetivo**: Proporcionar especificaciones exactas sin código, listas para ser implementadas.

---

## ESTRATEGIA 1: Bollinger Band RSI Reversion (V3 - Mejorada)

### Nombre Código
```
BollingerRSIReversion_V3_ADXGate
```

### Descripción Ejecutiva
Toca Bollinger Band (oversold/overbought) + confirmación RSI + filtro ADX para evitar whipsaws en trending markets.

### Parámetros (Default)
| Parámetro | Valor | Rango Sugerido | Notas |
|-----------|-------|---|---|
| `bb_period` | 20 | [15, 20, 30] | Período SMA para Bollinger |
| `bb_std_devs` | 2.0 | [1.5, 2.0, 2.5, 3.0] | Desviaciones estándar |
| `rsi_period` | 14 | [10, 14, 21] | Período RSI |
| `rsi_oversold` | 35 | [25, 30, 35, 40] | Threshold oversold |
| `rsi_overbought` | 65 | [60, 65, 70] | Threshold overbought |
| `rsi_recovery_points` | 3 | [1, 3, 5] | Puntos RSI para validar recuperación |
| `adx_period` | 14 | [14] | Período ADX (estándar) |
| `adx_min_threshold` | 22 | [15, 20, 22, 25, 30] | ADX mínimo para permitir entrada |
| `sma200_period` | 200 | [100, 150, 200, 250] | Período SMA para trend macro |
| `max_hold_bars` | 60 | [20, 40, 60, 100] | Máximo barras en posición |
| `position_size` | 0.95 | [0.5, 0.75, 0.95, 1.0] | Tamaño posición (% capital) |

### Inputs Requeridos
```
OHLCV Data:
  - Open[t]
  - High[t]
  - Low[t]
  - Close[t]
  - Volume[t]
```

### Indicadores Precalculados
```
1. Bollinger Bands Superior
   bb_upper[t] = SMA(Close, bb_period)[t] + bb_std_devs × STD(Close, bb_period)[t]

2. Bollinger Bands Inferior
   bb_lower[t] = SMA(Close, bb_period)[t] - bb_std_devs × STD(Close, bb_period)[t]

3. Bollinger Band Medio (SMA)
   bb_mid[t] = SMA(Close, bb_period)[t]

4. RSI (Relative Strength Index)
   Δ[t] = Close[t] - Close[t-1]
   Gain[t] = SMA(max(Δ[t], 0), rsi_period)[t]
   Loss[t] = SMA(max(-Δ[t], 0), rsi_period)[t]
   RS[t] = Gain[t] / Loss[t]
   RSI[t] = 100 - (100 / (1 + RS[t]))

5. ADX (Average Directional Index)
   DM_Plus[t]  = max(High[t] - High[t-1], 0)
   DM_Minus[t] = max(Low[t-1] - Low[t], 0)
   TR[t] = max(High[t] - Low[t], High[t] - Close[t-1], Close[t-1] - Low[t])
   DI_Plus[t]  = SMA(DM_Plus, adx_period)[t] / SMA(TR, adx_period)[t] × 100
   DI_Minus[t] = SMA(DM_Minus, adx_period)[t] / SMA(TR, adx_period)[t] × 100
   DX[t] = abs(DI_Plus[t] - DI_Minus[t]) / (DI_Plus[t] + DI_Minus[t]) × 100
   ADX[t] = SMA(DX, adx_period)[t]

6. SMA200 (Trend Macro)
   sma200[t] = SMA(Close, sma200_period)[t]

7. SMA200 Direction (Últimas 5 barras)
   sma200_rising[t] = sma200[t] > sma200[t-5]
   sma200_falling[t] = sma200[t] < sma200[t-5]
```

### Lógica de Entrada

#### LONG (Compra en Oversold)
```
IF (adx[t] > adx_min_threshold
    AND sma200_rising[t]  // Tendencia alcista de fondo
    AND Close[t] ≤ bb_lower[t] × (1 + 0.002)  // Toque muy cerca del band
    AND min(rsi[t-2:t]) ≤ rsi_oversold
    AND rsi[t] > min(rsi[t-2:t]) + rsi_recovery_points
    AND position_size_available ≥ position_size):
  ENTRY = "LONG"
  entry_price = Close[t]
  entry_bar = t
```

#### SHORT (Venta en Overbought)
```
IF (adx[t] > adx_min_threshold
    AND NOT sma200_rising[t]  // Tendencia bajista de fondo
    AND Close[t] ≥ bb_upper[t] × (1 - 0.002)  // Toque muy cerca del band
    AND max(rsi[t-2:t]) ≥ rsi_overbought
    AND rsi[t] < max(rsi[t-2:t]) - rsi_recovery_points
    AND position_size_available ≥ position_size):
  ENTRY = "SHORT"
  entry_price = Close[t]
  entry_bar = t
```

### Lógica de Salida

#### LONG Position
```
CLOSE_LONG_IF:
  (entry_bar + max_hold_bars ≤ t)                    // Timeout
  OR (Close[t] ≥ bb_mid[t])                          // Precio sube a media
  OR (Close[t] ≥ bb_upper[t])                        // Precio toca banda superior
  OR (rsi[t] ≥ 65)                                   // RSI entra overbought
  OR (Close[t] ≤ entry_price × 0.97)                 // Stop loss 3%
```

#### SHORT Position
```
CLOSE_SHORT_IF:
  (entry_bar + max_hold_bars ≤ t)                    // Timeout
  OR (Close[t] ≤ bb_mid[t])                          // Precio baja a media
  OR (Close[t] ≤ bb_lower[t])                        // Precio toca banda inferior
  OR (rsi[t] ≤ 35)                                   // RSI entra oversold
  OR (Close[t] ≥ entry_price × 1.03)                 // Stop loss 3%
```

### Métricas de Evaluación
```
Métricas Primarias:
  1. Total Return (%)
  2. Sharpe Ratio (target: > 0.8)
  3. Sortino Ratio (target: > 0.8)
  4. Calmar Ratio (target: > 0.3)
  5. Max Drawdown (%)
  6. Win Rate (%)
  7. Total Trades
  8. Avg Trade Duration (barras)

Métricas Secundarias:
  - Consecutive Wins/Losses
  - Profit Factor (Gross Profit / Gross Loss)
  - Recovery Factor (Total Profit / Max DD)
```

### Validación
```
Mínimo para considerar viable:
  - Total Trades ≥ 20 por activo
  - Sharpe ≥ 0.5
  - Max DD < 40%
  - Win Rate > 45%
```

---

## ESTRATEGIA 2: Z-Score Mean Reversion

### Nombre Código
```
ZScoreReversion_Simple
```

### Descripción
Mean reversion basada en desviación estándar estadística. Cuando el precio se desvía más de k sigmas de su media, es probable revertir.

### Parámetros (Default)
| Parámetro | Valor | Rango Sugerido |
|-----------|-------|---|
| `lookback_period` | 20 | [10, 15, 20, 30] |
| `entry_z_long` | -1.5 | [-1.0, -1.5, -2.0] |
| `entry_z_short` | +1.5 | [+1.0, +1.5, +2.0] |
| `exit_z_threshold` | 0.0 | [0.0, 0.3, 0.5] |
| `adx_filter_enabled` | true | [true, false] |
| `adx_max_for_entry` | 20 | [15, 20, 25] |
| `max_hold_bars` | 100 | [50, 100, 200] |
| `position_size` | 0.95 | [0.75, 0.95, 1.0] |

### Indicadores
```
1. Rolling Mean
   mean[t] = SMA(Close, lookback_period)[t]

2. Rolling Standard Deviation
   std[t] = STD(Close, lookback_period)[t]

3. Z-Score
   z_score[t] = (Close[t] - mean[t]) / std[t]

4. ADX (si enabled)
   [ver ESTRATEGIA 1 para cálculo ADX]
```

### Lógica de Entrada

#### LONG
```
IF (z_score[t] ≤ entry_z_long
    AND (NOT adx_filter_enabled OR adx[t] ≤ adx_max_for_entry)
    AND position_size_available ≥ position_size):
  ENTRY = "LONG"
  entry_price = Close[t]
  entry_bar = t
  entry_z_score = z_score[t]
```

#### SHORT
```
IF (z_score[t] ≥ entry_z_short
    AND (NOT adx_filter_enabled OR adx[t] ≤ adx_max_for_entry)
    AND position_size_available ≥ position_size):
  ENTRY = "SHORT"
  entry_price = Close[t]
  entry_bar = t
  entry_z_score = z_score[t]
```

### Lógica de Salida

#### Ambas Posiciones
```
CLOSE_IF:
  (entry_bar + max_hold_bars ≤ t)                    // Timeout
  OR (z_score[t] ≥ exit_z_threshold AND position.is_long)   // Mean revert
  OR (z_score[t] ≤ -exit_z_threshold AND position.is_short)  // Mean revert
  OR (Close[t] ≤ entry_price × 0.95)                 // SL 5%
  OR (Close[t] ≥ entry_price × 1.05)                 // TP 5%
```

### Variante: Z-Score con ADX Filtro OFF
```
Cuándo usar: Testing puro sin regime filter
Cuándo no: En crypto trending
```

---

## ESTRATEGIA 3: VWAP Reversion Intraday

### Nombre Código
```
VWAPReversion_IntraDay
```

### Descripción
Revierte desde extremos VWAP. Opera intraday sobre desviaciones de volumen ponderado.

### Parámetros (Default)
| Parámetro | Valor | Rango Sugerido |
|-----------|-------|---|
| `vwap_deviation_bps` | 50 | [25, 50, 75, 100] |
| `adx_max_threshold` | 20 | [15, 20, 25] |
| `volume_threshold_mult` | 1.2 | [1.0, 1.2, 1.5] |
| `max_hold_hours` | 24 | [4, 8, 24, 48] |
| `max_hold_bars_1h` | 24 | = max_hold_hours (a 1h) |
| `position_size` | 0.95 | [0.75, 0.95] |

### Indicadores
```
1. VWAP (Volume Weighted Average Price)
   vwap[t] = cumsum(Close[1..t] × Volume[1..t]) / cumsum(Volume[1..t])

   NOTA: Se resetea al inicio de cada día (UTC)

2. VWAP Deviation (en basis points)
   dev_bps[t] = ((Close[t] - vwap[t]) / vwap[t]) × 10000

3. Volume SMA (lookback 20)
   vol_sma[t] = SMA(Volume, 20)[t]

4. ADX [ver ESTRATEGIA 1]

5. Hour Marker (para tracking intraday)
   hour[t] = timestamp[t].hour
   entry_hour[position] = timestamp[entry].hour
   hours_elapsed[t] = (timestamp[t].hour - entry_hour) % 24
```

### Lógica de Entrada

#### LONG (Precio muy bajo vs VWAP)
```
IF (dev_bps[t] < -vwap_deviation_bps  // Precio está vwap_deviation_bps bps BAJO
    AND adx[t] < adx_max_threshold     // Mercado sin trend fuerte
    AND Volume[t] > vol_sma[t] × volume_threshold_mult  // Volumen activo
    AND position_size_available ≥ position_size):
  ENTRY = "LONG"
  entry_price = Close[t]
  entry_bar = t
  entry_dev_bps = dev_bps[t]
```

#### SHORT (Precio muy alto vs VWAP)
```
IF (dev_bps[t] > +vwap_deviation_bps  // Precio está vwap_deviation_bps bps ALTO
    AND adx[t] < adx_max_threshold
    AND Volume[t] > vol_sma[t] × volume_threshold_mult
    AND position_size_available ≥ position_size):
  ENTRY = "SHORT"
  entry_price = Close[t]
  entry_bar = t
  entry_dev_bps = dev_bps[t]
```

### Lógica de Salida

#### LONG Position
```
CLOSE_LONG_IF:
  (hours_elapsed[t] ≥ max_hold_hours)        // Timeout intraday
  OR (dev_bps[t] ≥ 0)                        // Precio tocar VWAP (o pasar)
  OR (dev_bps[t] > -10)                      // Parcial recovery
  OR (Close[t] ≤ entry_price × 0.97)         // SL 3%
```

#### SHORT Position
```
CLOSE_SHORT_IF:
  (hours_elapsed[t] ≥ max_hold_hours)
  OR (dev_bps[t] ≤ 0)
  OR (dev_bps[t] < +10)
  OR (Close[t] ≥ entry_price × 1.03)
```

### Notas Importantes
```
- VWAP reset: Ocurre a medianoche UTC (00:00 UTC)
- Trades pueden cruzar reset (manejar como cierre si overlap)
- Intraday = max 24–48 horas hold
```

---

## ESTRATEGIA 4: Pairs Trading ETH/BTC Ratio Reversion

### Nombre Código
```
PairsReversion_ETHBTC
```

### Descripción
Detecta desviaciones en el ratio ETH/BTC y tradesea la reversión. Delta-neutral (posiciones opuestas en ambos assets).

### Parámetros (Default)
| Parámetro | Valor | Rango Sugerido |
|-----------|-------|---|
| `ratio_lookback` | 20 | [15, 20, 30, 60] |
| `entry_z_threshold` | 1.5 | [1.0, 1.5, 2.0] |
| `exit_z_threshold` | 0.2 | [0.0, 0.2, 0.5] |
| `hedge_ratio` | 0.04 | [0.03, 0.04, 0.05] |
| `max_hold_bars` | 100 | [50, 100, 200] |
| `position_size_eth` | 0.5 | [0.3, 0.5] |
| `position_size_btc` | 0.5 | [0.3, 0.5] |

### Indicadores
```
1. Ratio ETH/BTC
   ratio[t] = Close_ETH[t] / Close_BTC[t]

2. Ratio Mean y StdDev
   ratio_mean[t] = SMA(ratio, ratio_lookback)[t]
   ratio_std[t] = STD(ratio, ratio_lookback)[t]

3. Ratio Z-Score
   z_ratio[t] = (ratio[t] - ratio_mean[t]) / ratio_std[t]
```

### Lógica de Entrada

#### LONG_ETH_SHORT_BTC (ETH barrata vs BTC)
```
IF (z_ratio[t] ≤ -entry_z_threshold
    AND position_size_available ≥ position_size_eth + position_size_btc):
  ENTRY = "LONG_ETH_SHORT_BTC"
  entry_eth_price = Close_ETH[t]
  entry_btc_price = Close_BTC[t]
  entry_bar = t
  entry_z_ratio = z_ratio[t]

  // Tamaños:
  // Long:  1.0 ETH (normalized a position_size_eth)
  // Short: hedge_ratio BTC
```

#### SHORT_ETH_LONG_BTC (ETH cara vs BTC)
```
IF (z_ratio[t] ≥ +entry_z_threshold
    AND position_size_available ≥ position_size_eth + position_size_btc):
  ENTRY = "SHORT_ETH_LONG_BTC"
  entry_eth_price = Close_ETH[t]
  entry_btc_price = Close_BTC[t]
  entry_bar = t
  entry_z_ratio = z_ratio[t]

  // Tamaños:
  // Short: 1.0 ETH
  // Long:  hedge_ratio BTC
```

### Lógica de Salida

#### Ambas Posiciones
```
CLOSE_PAIR_IF:
  (entry_bar + max_hold_bars ≤ t)           // Timeout
  OR (abs(z_ratio[t]) ≤ exit_z_threshold)   // Convergencia
  OR (Close_ETH[t] ≤ entry_eth_price × 0.95)  // SL individual 5%
  OR (Close_BTC[t] ≤ entry_btc_price × 0.95)  // SL individual 5%

  // Cierre ambas patas simultáneamente
```

### Estructura de Posición (Recordatorio)
```
LONG_PAIR ejemplo:
  Long:  +1 ETH a $2000
  Short: -0.04 BTC a $50000

  Exposición neta: Neutral al dirección BTC
  Exposición: Beneficia si ETH/BTC sube

SHORT_PAIR ejemplo:
  Short: -1 ETH a $2000
  Long:  +0.04 BTC a $50000

  Exposición: Beneficia si ETH/BTC baja
```

---

## EVALUACIÓN COMPARATIVA

### Características Resumidas

| Estrategia | Complejidad | Sharpe Esperado | Mejor Para | Riesgos |
|---|---|---|---|---|
| Bollinger RSI V3 | Media | 0.5–1.0 | Crypto intraday | Whipsaws si ADX mal calibrado |
| Z-Score Simple | Baja | 0.6–1.2 | Base sólida | Ignora trends |
| VWAP Intraday | Media | 0.7–1.3 | Intraday/scalp | Overnight gaps |
| Pairs Trading | Media-Alta | 1.0–1.8 | Reducir riesgo sistemático | Ejecutar ambas patas |

### Recomendación de Ejecución

**Semana 1**: Implementar #1 y #2 (simplicidad)
**Semana 2**: Testing #3 (VWAP)
**Semana 3**: Opcional #4 (Pairs, si hay capital)

---

## NOTAS FINALES

1. **Comisiones HyperLiquid**: ~0.02% maker, ~0.05% taker
   - Restar ~0.1% por trade al ROI esperado

2. **Slippage**: En órdenes mercado ~0.05–0.1% en crypto volátil
   - Usar órdenes límite para mejor fill

3. **Capital Requerido**: Cada activo ≥ 0.95 posición_size
   - Para 9 activos (BTC, ETH, SOL, BNB, AVAX, LINK, ARB, ADA, DOGE):
   - Mínimo 9 × 0.95 = 8.55 posiciones simultáneas posibles

4. **Rebalanceo**: Diario (UTC) recomendado para VWAP y Pairs

5. **Monitoreo**: Logs mínimo:
   - Entry timestamp, precio, z-score (si aplica)
   - Exit timestamp, precio, PnL
   - Duración trade

