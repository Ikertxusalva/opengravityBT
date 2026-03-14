# Specs Index — Backtest Architect
> Generado: 2026-03-01 | 5 estrategias listas para codificar

## Cómo usar estas specs

El Backtest Architect lee estas specs y genera código Python compatible con `backtesting.py`.
Cada spec tiene: idea, indicadores, entry/exit conditions exactas, parámetros optimizables, y variables nuevas a crear.

```bash
# Correr multi-test después de generar el código:
cd C:\Users\ijsal\Desktop\RBI-Backtester
C:\Users\ijsal\.local\bin\uv.exe run python moondev/backtests/multi_data_tester.py moondev/strategies/<archivo.py> <ClaseName>
```

---

## Estrategias por prioridad

| Prioridad | Archivo spec | Clase destino | Sharpe doc | Dificultad | Estado |
|-----------|-------------|--------------|-----------|-----------|--------|
| 🔴 P0 | `funding_arb_real.md` | `FundingArbReal` | 1.8–3.5 | Baja | ⏳ Pendiente |
| 🟡 P1 | `whale_following.md` | `WhaleFollowing` | 0.7–1.0 | Baja | ⏳ Pendiente |
| 🟡 P1 | `pairs_trading_btceth.md` | `PairsTrading` | 0.93–1.2 | Media | ⏳ Pendiente |
| 🟢 P2 | `weak_ensemble.md` | `WeakEnsemble` | 0.8–2.37 | Baja | ⏳ Pendiente |
| 🟢 P2 | `hmm_adaptive.md` | `HMMAdaptive` | 0.48–1.9 | Media | ⏳ Pendiente |

---

## Variables nuevas documentadas por estrategia

### FundingArbReal
- `funding_proxy` = (close - SMA20) / SMA20 * 0.1
- `zscore_spread` = (funding_proxy - mean) / std rolling 20
- `regime_signal` = 1 cuando funding > threshold

### WhaleFollowing
- `vol_ratio` = volume / volume_SMA20
- `whale_long` = vol_ratio > 2.0 AND close > close[-1] (large bullish candle)
- `ema200`, `ema50`, `rsi7` como filtros de contexto

### PairsTrading
- `log_spread` = log(BTC_close) - beta * log(ETH_close)
- `zscore_spread` = (spread - spread.rolling(252).mean()) / spread.rolling(252).std()
- `beta` = OLS hedge ratio (~0.7 histórico)
- ETH precio como columna adicional en el DataFrame

### WeakEnsemble
- `s1_rsi` = (RSI14 - 50) / 50
- `s2_macd` = MACD_hist / MACD_hist.rolling(50).std()
- `s3_bb` = (BB%B - 0.5) * 2
- `s4_cci` = (CCI20 / 100).clip(-1, 1)
- `s5_vol` = (volume/vol_SMA20 - 1).clip(-1, 1)
- `ensemble_score` = suma ponderada inv-vol de las 5 señales

### HMMAdaptive
- `log_returns` = log(close / close.shift(1))
- `hmm_state` = GaussianHMM(n=2).predict(log_returns)
- `bull_state` = argmax(model.means_)
- `regime` = 1 si hmm_state == bull_state else 0

---

## Notas de implementación

### PairsTrading — merge de dos símbolos
```python
btc = yf.download("BTC-USD", period="2y", interval="1h", auto_adjust=True)
eth = yf.download("ETH-USD", period="2y", interval="1h", auto_adjust=True)
data = btc[["Open","High","Low","Close","Volume"]].copy()
data.columns = ["Open","High","Low","Close","Volume"]
data["ETH"] = eth["Close"].reindex(data.index)
data = data.dropna()
```

### HMMAdaptive — dependencia adicional
```bash
C:\Users\ijsal\.local\bin\uv.exe add hmmlearn
```

### FundingArbReal — datos reales (opcional)
```python
# Alternativa al proxy: usar funding histórico de HyperLiquid
import requests
resp = requests.post("https://api.hyperliquid.xyz/info", json={
    "type": "fundingHistory",
    "coin": "BTC",
    "startTime": int(start_ts_ms)
})
funding_df = pd.DataFrame(resp.json())
```
