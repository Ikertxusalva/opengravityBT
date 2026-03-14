# Spec: FundingArbReal
> Para: Backtest Architect | Prioridad: P0 | Sharpe documentado: 1.8–3.5

## Idea (one-liner)
Delta-neutral funding rate arbitrage: long spot + short perp cuando funding rate > 0.01%/8h en HyperLiquid; exit cuando rate < 0.005%/8h. Ganar el funding sin exposición direccional.

## Tipo
Market-Neutral / Carry Trade

## Indicadores requeridos
- `funding_rate`: float, % por 8h (de metaAndAssetCtxs HL API o simulado con historical data)
- `spread_zscore`: z-score del spread perp-spot sobre rolling 20 períodos
- Sin indicadores técnicos de precio (estrategia de carry puro)

## Entry conditions (TODAS deben ser True)
```
LONG (cobrar funding):
1. funding_rate > 0.01  (en % por 8h; equivale a >11% APR)
2. spread_zscore > 1.5  (perp cotiza por encima del spot → longs pagan)
3. volume_24h > 100_000  (liquidez mínima en USD)
4. bid_ask_spread < 0.003  (0.3% máximo)

→ Acción: buy(size=0.95)  [proxy: long en backtesting.py]
```

## Exit conditions (CUALQUIERA dispara salida)
```
1. funding_rate < 0.005  (rate demasiado bajo, no cubre costos)
2. funding_rate < 0  (rate negativo: los shorts pagan ahora)
3. spread_zscore < 0.3  (spread convergió, oportunidad terminó)
4. Tiempo máximo: 7 días (evitar hold indefinido)
```

## Stop Loss
- No SL de precio (es delta-neutral, precio no importa)
- SL lógico: si funding_rate < -0.02%/8h por 2 períodos consecutivos → cerrar

## Take Profit
- No TP de precio
- Exit natural: cuando rate cae bajo threshold de exit
- Acumular funding cada período (en backtesting simulado como return fijo)

## Parámetros optimizables
```python
funding_entry_threshold = 0.01   # % por 8h, rango: [0.005, 0.02, 0.03]
funding_exit_threshold  = 0.005  # % por 8h, rango: [0.001, 0.005, 0.01]
zscore_entry            = 1.5    # rango: [1.0, 1.5, 2.0, 2.5]
zscore_exit             = 0.3    # rango: [0.0, 0.3, 0.5]
max_hold_periods        = 42     # 7 días × 6 períodos/día (4h bars), rango: [18, 42, 84]
```

## Simulación en backtesting.py (approach)
Ya que backtesting.py no tiene "funding rate" nativo, simular así:
- **Feature engineering**: calcular funding_rate como función del precio:
  `funding_proxy = (close - sma_20) / sma_20 * 0.01`  (cuando perp > spot → rate positivo)
- O usar **datos históricos de funding rate de HyperLiquid** exportados a CSV
- El "return" de cada período activo = funding_rate cobrado - comisión
- Archivo de datos: `moondev/data/ohlcv/BTC_funding_history.csv` (si existe)

## Variables nuevas a crear
```python
# En init():
close = pd.Series(self.data.Close)
sma20 = ta.sma(close, 20)

# Funding rate proxy (cuando precio perp > precio promedio → longs pagan)
funding_proxy = (close - sma20) / sma20 * 0.1  # escalar a % razonable

# Z-score del spread
spread_mean = ta.sma(funding_proxy, 20)
spread_std  = funding_proxy.rolling(20).std()
zscore      = (funding_proxy - spread_mean) / spread_std

self.funding = self.I(lambda: funding_proxy.values, name='Funding')
self.zscore  = self.I(lambda: zscore.values, name='ZScore')
```

## Edge / Por qué funciona
- arXiv:2212.06888 (WashU): Sharpe 1.8 retail, 3.5 market makers
- Deviaciones no-arb del 60-90%/año en crypto (vs <1% en forex)
- HyperLiquid paga funding cada hora → alto frequency de ingresos
- Delta-neutral: no depende de dirección del mercado

## Datos para backtest
- Símbolo: BTC-USD (yfinance) como proxy, timeframe 4h, 365 días
- Para backtesting real: usar `fundingHistory` API de HL
- API endpoint: `POST https://api.hyperliquid.xyz/info {"type":"fundingHistory","coin":"BTC","startTime":ms}`

## Advertencias
- El proxy de funding con SMA es una aproximación: los resultados reales pueden diferir
- En bear markets, funding puede ser negativo sistemáticamente (shorts pagan)
- Los resultados del paper (Sharpe 3.5) son para market makers sin fees
- Para backtest válido: usar datos reales de funding histórico de HL

## Fuentes
- [arXiv:2212.06888](https://arxiv.org/abs/2212.06888) — paper principal
- [HyperLiquid Docs: Funding](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding)
- Reporte completo: `research/reports/2026-03-01-funding-arb-real-research.md`
