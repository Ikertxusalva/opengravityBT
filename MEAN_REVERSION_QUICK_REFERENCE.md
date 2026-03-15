# Quick Reference — Mean Reversion Strategies
## One-Page Comparison

---

## SIDE-BY-SIDE COMPARISON

| Aspecto | Bollinger RSI V3 | Z-Score | VWAP Intraday | Pairs ETH/BTC |
|---------|---|---|---|---|
| **Sharpe Esperado** | 0.6–1.0 | 0.8–1.2 | 0.7–1.3 | 1.0–1.8 |
| **Complejidad** | 🟡 Media | 🟢 Baja | 🟡 Media | 🔴 Alta |
| **Implementación** | 3–4 horas | 1–2 horas | 2–3 horas | 5–6 horas |
| **Parámetros** | 10+ | 6–8 | 8+ | 5 |
| **Indicadores Requeridos** | RSI, BB, ADX, SMA200 | Media, StdDev, ADX | VWAP, Vol SMA, ADX | Ratio, Mean, StdDev |
| **Timeframes** | 1h–4h | 1h–1d | **1h** (intraday) | 1h–4h |
| **Assets Testeable** | Todos (9) | Todos (9) | Todos (9) | ETH/BTC, SOL/BTC, etc. |
| **Regime Filter** | ADX (CRÍTICO) | ADX (CRÍTICO) | ADX (CRÍTICO) | N/A (delta-neutral) |
| **Max Trades/Día** | 2–5 | 3–8 | 5–20 | 1–2 |
| **Riesgo Whipsaw** | 🟡 Medio | 🟢 Bajo | 🟢 Bajo | 🟢 Bajo |
| **Validación** | ✅ Backtests previos | ⏳ Nuevo | ⏳ Nuevo | ⏳ Nuevo |

---

## DECISIÓN RÁPIDA

### Si tienes **30 minutos**: Comienza con **Z-Score**
- Más simple, menos parámetros
- Fundamentación estadística clara
- Rápido de codificar

### Si tienes **2 horas**: Implementa ambas Z-Score + Bollinger RSI
- Puedes iterar en paralelo
- Comparar resultados
- Una probablemente superará a la otra

### Si tienes **4 horas**: Añade VWAP Intraday
- Captura movimientos intradiarios diferentes
- Diversificación de estrategias

### Si buscas **máxima diversificación**: Pairs Trading
- Hedge sistemático
- Sharpe teórico más alto
- Requiere 2× ejecución (ambas patas)

---

## ENTRADA RÁPIDA (Pseudo-Código)

### Bollinger RSI V3
```python
IF ADX > 22 AND SMA200_RISING:
  IF RSI < 35 AND PRICE <= BB_LOWER:
    BUY
  ELIF RSI > RECOVERY_THRESHOLD:
    SELL (cierra)
```

### Z-Score
```python
ZSCORE = (PRICE - MEAN_20) / STD_20
IF ZSCORE < -1.5:
  BUY
ELIF ZSCORE > +1.5:
  SELL
ELIF ZSCORE == 0.0:
  CLOSE
```

### VWAP
```python
DEV_BPS = (PRICE - VWAP) / VWAP × 10000
IF DEV_BPS < -50:
  BUY
ELIF DEV_BPS > +50:
  SELL
ELIF abs(DEV_BPS) < 10:
  CLOSE
```

### Pairs
```python
RATIO = ETH_PRICE / BTC_PRICE
ZSCORE_RATIO = (RATIO - MEAN_20_RATIO) / STD_20_RATIO
IF ZSCORE_RATIO < -1.5:
  BUY 1 ETH, SELL 0.04 BTC
ELIF ZSCORE_RATIO > +1.5:
  SELL 1 ETH, BUY 0.04 BTC
ELIF abs(ZSCORE_RATIO) < 0.2:
  CLOSE BOTH
```

---

## PARÁMETROS INICIALES (NO OPTIMIZAR AÚN)

### Bollinger RSI V3
```python
bb_period = 20
bb_std = 2.0
rsi_period = 14
rsi_oversold = 35
rsi_overbought = 65
adx_min = 22        # CLAVE
sma200_period = 200 # CLAVE
max_hold_bars = 60
```

### Z-Score
```python
lookback = 20
entry_z = [-1.5, +1.5]
exit_z = 0.0
adx_max = 20        # CLAVE
max_hold = 100
```

### VWAP
```python
vwap_dev_bps = 50
adx_max = 20        # CLAVE
volume_mult = 1.2
max_hold_hours = 24
```

### Pairs
```python
lookback = 20
entry_z_ratio = 1.5
exit_z_ratio = 0.2
hedge_ratio = 0.04
max_hold = 100
```

---

## CHECKLIST IMPLEMENTACIÓN

### Antes de Backtest
```
□ Indicadores calculados correctamente (vr manual vs código)
□ ADX filtering aplicado (sin esto → fail)
□ SMA200 direction check en Bollinger (sin esto → fail)
□ Entry conditions exactas (no "aproximado")
□ Exit conditions para todas las paths
□ Position size y leverage aplicados
□ Timeframe correcto (1h default)
□ Comisiones incluidas (~0.05% taker)
```

### Validación Post-Backtest
```
□ Total trades ≥ 20 por activo
□ Sharpe ratio calculado correctamente
□ Max drawdown real (no teórico)
□ Win rate plausible (no > 70% en reversion)
□ Log de trades: entrada, salida, PnL
□ Curva de equity suave (no spikes raros)
```

---

## ORDEN DE IMPLEMENTACIÓN RECOMENDADO

### Semana 1
```
1. Z-Score (más rápido, validación del pipeline)
2. Bollinger RSI V3 (iterar con ADX gate)
```

### Semana 2
```
3. VWAP Intraday (nuevo angle)
4. Comparativa entre las 3
```

### Semana 3
```
5. Pairs Trading (si las 3 anteriores tienen Sharpe > 0.5)
6. Ensemble voting (si 2+ viables)
```

---

## SEÑALES DE ALERTA

### ❌ Sharpe > 1.5 en Backtest
- Probable overfitting
- Redunda parámetros, aumenta max_hold_bars
- Reduce confianza en producción

### ❌ Win Rate > 70%
- Demasiados trades pequeños ganadores
- Probabilidad: 1–2 grandes pérdidas erosionan todo
- Espera la prueba de producción

### ❌ Max Drawdown > 40%
- Riesgo inmanejable
- Revisar SL, ATR multiplier, position_size

### ❌ Trades < 10 por activo en 1 año
- Señal demasiado rara
- Relaxar thresholds (Z < -1.0 en lugar de -1.5)

### ✅ Sharpe 0.5–1.0, Win 50–55%, DD < 30%
- **Señal VERDE**: viable para producción pequeña

---

## DATOS NECESARIOS (Verificar Disponibilidad)

```
✅ OHLCV histórico 2+ años
  - Open[t], High[t], Low[t], Close[t], Volume[t]

✅ Assets disponibles
  - BTC, ETH, SOL, BNB, AVAX, DOGE, ADA, LINK, ARB

✅ Timeframes
  - 1h (todos necesitan), 4h (opcional), 1d (opcional)

⏳ Futuro
  - Liquidations (para capitulación detection)
  - Funding Rates (para arb)
  - OI (para divergencia)
```

---

## PRODUCCIÓN: UMBRALES MÍNIMOS

**Para ir a live (pequeño size)**:

- Sharpe ≥ 0.5
- Max DD < 40%
- Trades ≥ 20 por activo
- Win Rate > 45%
- Calmar > 0.2

---

## NOTAS FINALES

1. **ADX > 22 es el factor más crítico** — sin esto todas fallan en crypto
2. **SMA200 direction** — alinea con macro trend, reduce reversions falsas
3. **Volatility-based stops** — ATR multipliers adaptan a cada activo
4. **Ensemble > single** — si hay 2+ viables, votación mejora edge
5. **Comisiones importan** — Sharpe teórico 1.0 → práctico 0.8 post-comisiones

---

## CONTACTOS

- Backtests: `/results/multi_*.json`
- Código: `/moondev/strategies/rbi/`
- Documentación: Este directorio

**Última actualización**: 2026-03-15
**Siguiente review**: 2026-03-22

