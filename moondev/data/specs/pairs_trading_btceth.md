# Spec: PairsTrading BTC/ETH
> Para: Backtest Architect | Prioridad: P1 | Sharpe documentado: 0.93–1.2

## Idea (one-liner)
Statistical arbitrage BTC/ETH: long BTC + short ETH cuando z-score del spread log-precio baja a -2.0; long ETH + short BTC cuando sube a +2.0. Exit cuando z-score regresa a ±0.5. Hedge ratio OLS.

## Tipo
Statistical Arbitrage / Mean Reversion / Market-Neutral

## Indicadores requeridos
- `log_spread`: log(BTC_price) - β × log(ETH_price)  donde β = hedge ratio OLS
- `zscore_spread`: z-score rolling del spread (ventana 252 días)
- `adf_pvalue`: p-value del test ADF (opcional en backtest, calcular en pre-análisis)

## Datos necesarios
- BTC-USD y ETH-USD simultáneamente
- Timeframe: 1h o 4h
- Período: 365+ días (necesita 252 días de formation + trading period)

⚠️ **backtesting.py limitation**: es mono-símbolo. Usar ETH precio importado como columna adicional:
```python
# Descargar los dos símbolos y mergear
btc = yf.download("BTC-USD", period="2y", interval="1h")
eth = yf.download("ETH-USD", period="2y", interval="1h")
data = btc[["Open","High","Low","Close","Volume"]].copy()
data["ETH"] = eth["Close"]  # columna extra con precio ETH
```

## Hedge ratio (pre-cálculo)
```python
import numpy as np
from statsmodels.api import OLS

log_btc = np.log(btc["Close"])
log_eth = np.log(eth["Close"])

# OLS: log_BTC = β × log_ETH + ε
model = OLS(log_btc, log_eth).fit()
beta = model.params[0]  # hedge ratio típico: ~0.6-0.8
```

## Variables en init()
```python
close_btc = pd.Series(self.data.Close)
close_eth = pd.Series(self.data.ETH)   # columna extra mergeada

log_btc = np.log(close_btc)
log_eth = np.log(close_eth)

# Spread (usando beta pre-calculado como param de clase)
spread = log_btc - self.beta * log_eth

# Z-score rolling
spread_mean = spread.rolling(self.zscore_window).mean()
spread_std  = spread.rolling(self.zscore_window).std()
zscore      = (spread - spread_mean) / spread_std

self.zscore  = self.I(lambda: zscore.values, name='ZScore')
self.spread  = self.I(lambda: spread.values, name='Spread')
```

## Entry conditions
```
LONG SPREAD (BTC barato vs ETH → esperar que BTC suba):
1. zscore[-1] < -self.entry_z          (spread demasiado bajo)
2. zscore[-2] >= -self.entry_z         (cruce hacia abajo — primer toque)
3. abs(zscore[-1]) < self.stop_z       (no en zona de stop)

→ buy(size=0.95)   [proxy: long BTC en backtesting, el short ETH es implícito]

SHORT SPREAD (BTC caro vs ETH):
1. zscore[-1] > self.entry_z
2. zscore[-2] <= self.entry_z
3. abs(zscore[-1]) < self.stop_z

→ sell()  [short BTC en backtesting]
```

## Exit conditions
```
LONG SPREAD exit:
1. zscore[-1] > -self.exit_z           (spread revirtió hacia la media)

SHORT SPREAD exit:
1. zscore[-1] < self.exit_z

STOP (spread sigue divergiendo — cointegración rota):
1. abs(zscore[-1]) > self.stop_z       (z-score > 3.5: salida de emergencia)
```

## Parámetros optimizables
```python
beta         = 0.7    # hedge ratio OLS, rango: [0.5, 0.6, 0.7, 0.8, 0.9]
entry_z      = 2.0    # rango: [1.5, 2.0, 2.5]
exit_z       = 0.5    # rango: [0.0, 0.3, 0.5]
stop_z       = 3.5    # rango: [3.0, 3.5, 4.0]
zscore_window = 504   # barras para rolling z-score en timeframe 4h
                      # ⚠️  BUG CORREGIDO: 252 barras 1h = solo ~10 días (insuficiente)
                      #     504 barras × 4h = ~84 días (~3 meses) — mínimo estadístico válido
                      #     Si se usa 1h: window debe ser 2016 (504 × 4)
                      # rango optimizable: [252, 504, 1008] (en barras 4h)
```

## Performance documentada
| Fuente | Sharpe | Return | Max DD |
|--------|--------|--------|--------|
| Amberdata (empirical) | 0.93 | 16.05% | 15.67% |
| EUR Thesis (2019-2024) | ~1.0 | 16% | ~15.7% |
| 5-min data (no realista) | 3.77 | 75% | N/A |

## Edge / Por qué funciona
- BTC y ETH históricamente cointegrados (ADF p-value < 0.05 en períodos normales)
- Half-life del spread: 5-15 días → mean reversion predecible
- Market-neutral: no depende de si el mercado sube o baja
- Profit factor 3.74 documentado (winners 5.6x más grandes que losers)

## Advertencias críticas
- Cointegración SE ROMPE en bull runs extremos (2021: ETH outperforms enormemente)
- Siempre validar ADF antes de operar: si p-value > 0.1 → no operar ese período
- El backtest DEBE incluir períodos 2021 y 2024 para ver failure modes
- Walk-forward 70/30 obligatorio antes de considerar viable

## Fuentes
- [arXiv:2109.10662](https://arxiv.org/pdf/2109.10662) — paper evaluación pairs trading crypto
- [Amberdata Empirical Results](https://blog.amberdata.io/empirical-results-performance-analysis) — Sharpe 0.93
- Reporte completo: `research/reports/2026-03-01-pairs-trading-btceth-research.md`
