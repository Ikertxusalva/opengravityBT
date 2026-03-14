# Spec: WeakEnsemble
> Para: Backtest Architect | Prioridad: P2 | Sharpe documentado: 0.8–2.37 (según combinación)

## Idea (one-liner)
Combinar 5 señales técnicas débiles (RSI14, MACD hist, BB%B, CCI20, Volume ratio) con ponderación inversamente proporcional a su volatilidad. Long cuando score ensemble > 0.3, short cuando < -0.3. Position sizing proporcional al score.

## Tipo
Multi-Signal Ensemble / Quantitative / Systematic

## Las 5 señales (baja correlación entre sí)
```
1. RSI(14):       normalizado a [-1, 1]  →  (rsi - 50) / 50
2. MACD hist:     normalizado  →  macd_hist / macd_hist.rolling(50).std()
3. BB %B:         ya en [0,1], centrar  →  (bbpct - 0.5) * 2
4. CCI(20):       normalizado  →  cci / 100  (clamp a [-1, 1])
5. Volume ratio:  normalizado  →  (vol/vol_sma - 1)  (clamp a [-1, 1])
```

## Variables en init()
```python
close  = pd.Series(self.data.Close)
high   = pd.Series(self.data.High)
low    = pd.Series(self.data.Low)
volume = pd.Series(self.data.Volume)

# Señal 1: RSI normalizado
rsi_raw = ta.rsi(close, 14)
s1 = (rsi_raw - 50) / 50

# Señal 2: MACD histogram normalizado
macd_df = ta.macd(close, 12, 26, 9)
macd_hist = macd_df.iloc[:, 2]  # MACDh columna
macd_std = macd_hist.rolling(50).std()
s2 = macd_hist / macd_std.replace(0, np.nan)

# Señal 3: Bollinger Band %B centrado
bb = ta.bbands(close, 20, 2.0)
bbpct = (close - bb.iloc[:, 0]) / (bb.iloc[:, 2] - bb.iloc[:, 0])  # %B = (price-lower)/(upper-lower)
s3 = (bbpct - 0.5) * 2

# Señal 4: CCI normalizado
cci_raw = ta.cci(high, low, close, 20)
s4 = (cci_raw / 100).clip(-1, 1)

# Señal 5: Volume ratio normalizado
vol_sma = ta.sma(volume, 20)
s5 = ((volume / vol_sma) - 1).clip(-1, 1)

# Ponderación: inversamente proporcional a volatilidad de cada señal (inv-vol)
w = []
for s in [s1, s2, s3, s4, s5]:
    vol_s = s.rolling(50).std()
    w.append(1.0 / vol_s.replace(0, np.nan))

# Normalizar pesos para que sumen 1
w_total = sum(w)
weights = [wi / w_total for wi in w]

# Score ensemble
score = sum(si * wi for si, wi in zip([s1,s2,s3,s4,s5], weights))

self.score  = self.I(lambda: score.fillna(0).values, name='EnsembleScore')
self.s_rsi  = self.I(lambda: s1.fillna(0).values, name='S_RSI')
self.s_macd = self.I(lambda: s2.fillna(0).values, name='S_MACD')
self.s_bb   = self.I(lambda: s3.fillna(0).values, name='S_BB')
self.s_cci  = self.I(lambda: s4.fillna(0).values, name='S_CCI')
self.s_vol  = self.I(lambda: s5.fillna(0).values, name='S_Vol')
```

## Entry conditions
```
LONG:
1. score[-1] > entry_threshold    (ensemble bullish)
2. score[-2] <= entry_threshold   (cruce — primer toque)

SHORT:
1. score[-1] < -entry_threshold
2. score[-2] >= -entry_threshold

Position size proporcional al score:
  size = abs(score[-1]) * 0.9  (máx 90% del capital)
  size = max(0.05, min(0.9, size))  # clamp entre 5% y 90%
```

## Exit conditions
```
LONG exit:
1. score[-1] < exit_threshold    (señales se debilitan)

SHORT exit:
1. score[-1] > -exit_threshold

STOP (opcional, ATR-based):
  sl = entry_price * (1 - atr_14[-1] / entry_price * sl_atr_mult)
```

## Parámetros optimizables
```python
entry_threshold = 0.3    # rango: [0.15, 0.2, 0.25, 0.3, 0.4]
exit_threshold  = 0.1    # rango: [0.0, 0.05, 0.1, 0.15]
sl_atr_mult     = 2.0    # rango: [1.5, 2.0, 2.5, 3.0]
weight_window   = 50     # ventana para calcular vol de señales, rango: [20, 50, 100]
```

## Performance documentada
| Combinación | Señales | Sharpe |
|-------------|---------|--------|
| SMAC solo | 1 | 0.82 |
| SMAC + ATV | 2 | 1.46 |
| SMAC + ATV + Parabolic SAR | 3 | **2.37** |
| Portfolio óptimo (paper) | Multi | **>2.5** |
| MACD + RSI (crypto BTC/ETH) | 2 | WR 55→73% |

## Edge / Por qué funciona
- Diversificación de señales no correlacionadas reduce errores individuales
- Inversely proportional volatility weighting = Risk Parity de señales
- Metodología inspirada en Jim Simons / Renaissance: muchas señales débiles
- No depende de que una señal siempre funcione: el ensemble es robusto

## Variables nuevas interesantes para explorar
```python
# 6ª señal: Momentum 20 períodos
momentum_20 = close.pct_change(20)
s6 = momentum_20.clip(-0.5, 0.5) / 0.5

# 7ª señal: Stochastic RSI
stoch = ta.stochrsi(close, 14)
stoch_k = stoch.iloc[:, 0]
s7 = (stoch_k - 50) / 50

# 8ª señal: ATR ratio (volatility signal)
atr = ta.atr(high, low, close, 14)
atr_sma = ta.sma(atr, 20)
s8 = -(atr / atr_sma - 1).clip(-1, 1)  # baja volatilidad = señal positiva
```

## Fuentes
- [SMAC+ATV ensemble Sharpe 2.37](https://arxiv.org/html/2509.16707v1)
- [MACD+RSI 73% WR](https://www.quantifiedstrategies.com/macd-and-rsi-strategy/)
- [Inverse Volatility Weighting](https://www.composer.trade/learn/inverse-volatility-weighting)
- Reporte completo: `research/reports/2026-03-01-weak-ensemble-research.md`
