# Spec: WhaleFollowing
> Para: Backtest Architect | Prioridad: P1 | Sharpe documentado: 0.7–1.0

## Idea (one-liner)
Seguir las posiciones de los top traders del leaderboard de HyperLiquid: comprar cuando un whale abre long, vender cuando cierra. Filtrar por ROI >20% en 30 días y mínimo 50 trades históricos.

## Tipo
Momentum / Copy Trading / Smart Money Following

## Indicadores requeridos
- `whale_signal`: +1 (whale abre long), -1 (whale abre short), 0 (sin cambio)
- `position_size_whale`: tamaño relativo de la posición del whale (normado 0-1)
- `whale_pnl_30d`: PnL porcentual del whale en últimos 30 días
- `whale_winrate`: win rate histórico del whale

## Simulación en backtesting.py (approach)
Ya que no tenemos datos reales de whale en tiempo real, simular así:
- **Proxy 1 (simple)**: usar cambio de momentum institucional
  `whale_signal = 1 si RSI(7) cruza arriba de 40 Y volume > 2x media Y precio > EMA200`
  (asume que el "smart money" entra en momentum con confirmación)
- **Proxy 2 (avanzado)**: large volume candles como proxy de entrada institucional
  `large_vol = volume[-1] > volume_sma * 2.5`
  `price_up = close[-1] > close[-2]`
  `whale_enters_long = large_vol AND price_up`

## Entry conditions (proxy momentum institucional)
```
LONG:
1. volume[-1] > volume_sma_20 * 2.0   (volumen inusualmente alto)
2. close[-1] > ema_200[-1]            (tendencia principal alcista)
3. rsi_7[-1] > 40 AND rsi_7[-2] < 40  (RSI cruzando al alza desde zona neutral)
4. close[-1] > close[-2]              (vela actual alcista)

SHORT:
1. volume[-1] > volume_sma_20 * 2.0
2. close[-1] < ema_200[-1]            (tendencia bajista)
3. rsi_7[-1] < 60 AND rsi_7[-2] > 60  (RSI cruzando a la baja)
4. close[-1] < close[-2]
```

## Exit conditions
```
LONG exit (cualquiera):
1. rsi_7[-1] > 75                     (sobrecomprado → whale toma ganancias)
2. volume[-1] < volume_sma_20 * 0.5   (volumen cae → señal de agotamiento)
3. close[-1] < ema_50[-1]             (precio rompe soporte clave)
4. atr_stop: close < entry_price * (1 - atr_14[-1] / close[-1] * 2)

SHORT exit (cualquiera):
1. rsi_7[-1] < 25
2. volume[-1] < volume_sma_20 * 0.5
3. close[-1] > ema_50[-1]
```

## Stop Loss
```python
sl_multiplier = 2.0  # ATR-based
sl = entry_price - atr_14[-1] * sl_multiplier  # para longs
sl = entry_price + atr_14[-1] * sl_multiplier  # para shorts
```

## Take Profit
```python
tp_multiplier = 3.0  # R:R = 1.5 mínimo
tp = entry_price + atr_14[-1] * tp_multiplier  # para longs
```

## Parámetros optimizables
```python
volume_multiplier = 2.0   # rango: [1.5, 2.0, 2.5, 3.0]
ema_trend_period  = 200   # rango: [100, 200]
rsi_period        = 7     # rango: [5, 7, 10, 14]
rsi_entry_bull    = 40    # rango: [35, 40, 45]
sl_atr_mult       = 2.0   # rango: [1.5, 2.0, 2.5]
tp_atr_mult       = 3.0   # rango: [2.5, 3.0, 4.0]
```

## Variables nuevas a crear
```python
# En init():
close  = pd.Series(self.data.Close)
high   = pd.Series(self.data.High)
low    = pd.Series(self.data.Low)
volume = pd.Series(self.data.Volume)

self.ema200     = self.I(lambda: ta.ema(close, 200).values, name='EMA200')
self.ema50      = self.I(lambda: ta.ema(close, 50).values, name='EMA50')
self.rsi7       = self.I(lambda: ta.rsi(close, 7).values, name='RSI7')
self.atr14      = self.I(lambda: ta.atr(high, low, close, 14).values, name='ATR14')
self.vol_sma20  = self.I(lambda: ta.sma(volume, 20).values, name='VolSMA20')

# Whale signal proxy (large volume candle en dirección de la tendencia)
def whale_long():
    v = volume.values
    vs = ta.sma(volume, 20).values
    c = close.values
    return np.where((v > vs * 2.0) & (c > np.roll(c, 1)), 1.0, 0.0)

self.whale_long = self.I(whale_long, name='WhaleLong')
```

## Edge / Por qué funciona
- White Whale en HL generó >$50M en 30 días (caso real documentado)
- Leaderboard de HL es transparente y verificable on-chain
- El whale ya procesó la información → el copier llega tarde pero el momentum continúa
- clearinghouseState endpoint (weight=2) permite monitorear múltiples whales barato

## Limitaciones del backtest
- El proxy de "large volume = whale" es una aproximación
- En producción real: usar `clearinghouseState` de HL cada 30s
- El lag real entre detección y ejecución puede erosionar el edge

## Fuentes
- [Dwellir: Hyperliquid Copy Trading Bot](https://www.dwellir.com/blog/hyperliquid-copy-trading-bot-python)
- [HyperLiquid Docs: clearinghouseState](https://docs.chainstack.com/reference/hyperliquid-info-clearinghousestate)
- Reporte completo: `research/reports/2026-03-01-whale-following-research.md`
