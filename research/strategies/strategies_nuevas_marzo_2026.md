# Estrategias de Trading Nuevas Extraídas — Marzo 2026

## Resumen
10+ estrategias nuevas e innovadoras extraídas de research en microstructura, volatilidad, sentiment y arbitraje estadístico. Todas candidatas para backtesting E2E.

---

## 1. VPINLiquidityToxicity
**Estrategia**: Trading basado en VPIN (Volume-Synchronized Probability of Informed Trading). Mide la probabilidad de que operadores informados estén activos en el mercado mediante desequilibrio de flujo de órdenes en buckets de volumen fijo. Cuando VPIN > 0.7 señala volatilidad inminente y cascadas de liquidación. Entrada: VPIN cruza 0.65 hacia arriba → LONG si precio está en soporte. Salida: VPIN cae a 0.45. SL: -2% bajo entrada. TP: +3.5% o después de 4h. Filtro: No operar si Fear&Greed > 85 (extrema avaricia). Timeframe: 5m/15m. Mercado: BTC/ETH perpetuos. Parámetros: volumen_bucket=500 BTC, vpin_threshold_enter=0.65, vpin_threshold_exit=0.45.
**Fuente**: [Order Flow and Cryptocurrency Returns](https://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2025-Greece/papers/OrderFlowpaper.pdf) | [Bitcoin wild moves](https://www.sciencedirect.com/science/article/pii/S0275531925004192)

---

## 2. DynamicCointegrationPairsOrnstein
**Estrategia**: Pairs trading con cointegración dinámica modelando spread como proceso Ornstein-Uhlenbeck (OU). Identifica pares de criptos cointegrados (p.ej. BTC-ETH, ETH-SOL, DOGE-LTC) usando test Engle-Granger. Calcula half-life del proceso OU para optimizar timing. Entrada LONG: spread cae 2 desvíos estándar por debajo de media. Entrada SHORT: spread sube 2 desvíos por encima. SL: ±3.5 desvíos. TP: cuando spread revierte a media. Lookback ventana dinámica: 30-60 días. Mercado: Spot pairs. Timeframe: 4H. Parámetros: cointegration_test=engle_granger, half_life_target=20-40 periodos, z_score_entry=±2.0.
**Fuente**: [Evaluation of Dynamic Cointegration-Based Pairs Trading](https://arxiv.org/abs/2109.10662) | [Optimal Stopping in Pairs Trading OU Model](https://hudsonthames.org/optimal-stopping-in-pairs-trading-ornstein-uhlenbeck-model/)

---

## 3. VolatilitySurfaceSkewArbitraje
**Estrategia**: Trading de IV skew en opciones de cripto. Identifica cuando IV de OTM calls es anormalmente elevada vs ATM (inversión del smile normal). Entrada: vende OTM calls, compra ATM calls (call spread). Si IV skew está en extremo histórico (top 10%), estructura se vuelve mispriced. TP cuando spread collapsa 20% de amplitud. SL si volatilidad realizada explota +30% más que IV implícita. Rebalance cada 3 horas. Mercado: BTC/ETH opciones (Deribit). Timeframe: análisis multi-strike 4h, exit señal 1h. Parámetros: skew_percentile_threshold=85, iv_smile_inversion_detection=yes, moneyness_levels=[0.9, 1.0, 1.1].
**Fuente**: [Trading the Volatility Skew for Crypto Options](https://medium.com/@raphaele.chappe_62395/trading-the-volatility-skew-for-crypto-options-a8d1ca8424b5) | [Understanding IV Skew In Crypto Options Markets](https://pi42.com/blog/iv-skew-crypto-options/)

---

## 4. BTCDominanceAltseasonRotation
**Estrategia**: Arbitraje sectorial mediante rotación de dominancia BTC y altseason. Cuando dominancia BTC cae de 62% → 48% en 14 días, liquidity rota hacia altcoins. Entrada LONG: basket ponderado [SOL, AVAX, MATIC, OP, DYDX] (DeFi + Layer2). Salida: dominancia BTC sube de nuevo a 55%+. SL: -4% del basket. TP: +8% cuando altseason index >75 (top 100 alts outperform BTC 90d). Timeframe: 4H/1D. Parámetros: dominance_threshold_entry=48%, altseason_index_confirm=75, rotation_lag_periods=3, weighting=equal_weight.
**Fuente**: [What Is Bitcoin Dominance?](https://www.mexc.com/learn/article/what-is-bitcoin-dominance-complete-guide-to-the-btc-dominance-chart-trading-strategies-1/) | [Altcoin Season Index Explained](https://whaleportal.com/blog/altcoin-season-index-explained-how-to-use-this-indicator-to-profit-from-alt-season/)

---

## 5. FearGreedExtremeReversion
**Estrategia**: Contrarian sentiment mean-reversion usando Crypto Fear&Greed Index. Entrada LONG: cuando FGI < 25 (Extreme Fear) por >6h AND MVRV Z-score < 0.5. Entrada SHORT: cuando FGI > 75 (Extreme Greed) por >6h AND MVRV Z-score > 2.0. SL: ±3% del precio entrada. TP: +4% LONG o -3% SHORT. No operar si FGI en rango 40-60 (neutro). Filtro: solo si volatilidad realizada 30-día es > 35% anualizado. Timeframe: 1H señal, 4H ejecución. Mercado: BTC/ETH. Parámetros: fgi_extreme_low=25, fgi_extreme_high=75, hold_duration_min=6h, mvrv_zscore_confirm=yes.
**Fuente**: [Crypto Fear and Greed Index](https://alternative.me/crypto/fear-and-greed-index/) | [Crypto Fear and Greed Index Explained](https://calebandbrown.com/blog/fear-and-greed-index/)

---

## 6. HiddenMarkovRegimeSwitcher
**Estrategia**: Detección de regímenes de mercado con HMM (3 estados: bull, bear, neutral). Calibra parámetros de estrategia según régimen detectado. En régimen Bull: trend-following con SMA 50/200. En régimen Neutral: mean-reversion con Bollinger Bands ±1.5 std. En régimen Bear: stop-loss agresivo (-1.5%), risk-off. Transición entre regímenes: cuando probabilidad suavizada del estado alcanza 70%+. Entrada: señal técnica + confirmación HMM. Timeframe: 1D estados, 4H ejecución. Parámetros: n_states=3, hidden_markov_returns_window=60d, transition_prob_threshold=0.70.
**Fuente**: [Regime-Switching Factor Investing with Hidden Markov Models](https://www.mdpi.com/1911-8074/13/12/311) | [Market Regime Detection using HMM](https://www.quantstart.com/articles/market-regime-detection-using-hidden-markov-models-in-qstrader/)

---

## 7. OrderBookLiquidityClusterBreakout
**Estrategia**: Identifica clusters de liquidez grande (>100 BTC en rango <0.5%) en order book. Cuando precio se acerca a cluster 50 bps, 2 opciones: (a) Bounce si cluster es de buyers (LONG), (b) Breakout si volumen market buy >> cluster size (SHORT). Detecta trade size clustering inusual: si últimas 10 trades = mismo size ±5%, posible pump/dump coming → evita entrada. Entrada: price toca cluster + volumen 5m > media móvil 20d * 1.8. TP: después de revertir 40bps del cluster. SL: 30 bps rotura cluster. Timeframe: 5m órdenes, 1H confirm. Parámetros: cluster_size_min=50BTC, cluster_proximity_bps=50, volume_multiplier_confirm=1.8, trade_size_cluster_detection=enabled.
**Fuente**: [Order Book Liquidity on Crypto Exchanges](https://www.mdpi.com/1911-8074/18/3/124) | [Liquidity Clusters Magnitude](https://www.luxalgo.com/library/indicator/liquidity-clusters-magnitude/)

---

## 8. FuturesTermStructureContangoBasis
**Estrategia**: Carry trading de basis BTC perpetual vs spot. Explota contango persistente cuando futures premium > 0.05% anualizado. Entrada LONG: compra spot BTC + SHORT perp equals size. Hold mientras contango > 0.02% 4h. TP: cuando basis cae a neutral o entra backwardation. SL: si basis sube >0.10% anualizado (señal de sobrecalentamiento). Retorna cada 3 días para rebalance. Filtro: no operar en extremo Fear&Greed (<20 o >80) donde basis puede invertir. Mercado: Binance spot + perps. Timeframe: 4H rebalance, 1H monitor. Parámetros: contango_threshold_entry=0.05%, basis_sl_threshold=0.10%, rebalance_interval=3d.
**Fuente**: [Revisiting the Bitcoin Basis](https://www.cfbenchmarks.com/blog/revisiting-the-bitcoin-basis-how-momentum-sentiment-impact-the-structural-drivers-of-basis-activity) | [Spot ETFs Give Rise to Crypto Basis Trading](https://www.cmegroup.com/openmarkets/equity-index/2025/Spot-ETFs-Give-Rise-to-Crypto-Basis-Trading.html)

---

## 9. LiquidationCascadeVolumeDetector
**Estrategia**: Anticipa cascadas de liquidación mediante detección de liquidation clusters. Monitorea liquidaciones en tiempo real por precio. Cuando liquidaciones >5% volumen 5m en range de ±1% → primera señal. Calcula si hay más liquidaciones potenciales mapeando posiciones apalancadas a partir de funding rates. Entrada CONTRA-cascada: SHORT si cascada es LONG (longs siendo liquidados = precio puede caer más). TP: 2% debajo de zona liquidación máxima. SL: +1.5% sobre entrada si no hay confirmación cascada en 30 min. Timeframe: 1m detección, 5m ejecución. Parámetros: liquidation_cluster_threshold=5% vol, cascade_range_pct=1.0, funding_rate_extreme_z_score=2.5.
**Fuente**: [Liquidations in Crypto: How to Anticipate Volatile Market Moves](https://blog.amberdata.io/liquidations-in-crypto-how-to-anticipate-volatile-market-moves) | [The Evolution of Crypto's Infamous Liquidation Cascade](https://allstarcharts.com/crypto-cascade/)

---

## 10. OnChainWhaleAccumulationMomentum
**Estrategia**: Sigue patrones de acumulación whale mediante análisis on-chain (Glassnode, Nansen). Señales: (1) Whale active addresses (>1000 BTC) salen de exchanges = holding intent. (2) Grandes inflows hacia direcciones nuevas = distribución. (3) Stablecoin inflows a exchanges 24h antes = compra coming. Entrada LONG: acumulación whale confirmada + SOPR < 1.0 (traders están bajo agua = bottom nearby). TP: +5% después confirmación visual price dump stop en cluster. SL: -2%. Timeframe: 4H/1D datos on-chain, 1H entrada. Parámetros: whale_address_threshold=1000_btc, stablecoin_inflow_lookback=24h, sopr_threshold_confirm=1.0, accumulation_confirmation_periods=3.
**Fuente**: [On-Chain Trading Strategies: How to Use Whale Movements](https://www.altrady.com/crypto-trading/onchain-blockchain-analytics-for-traders/how-to-use-whale-movements-your-advantage) | [Forecasting Crypto Trends: Whale Movements](https://www.nansen.ai/post/forecasting-crypto-trends-5-proven-strategies-for-predicting-whale-movements)

---

## 11. IntradaySeasonalityUTCTimeZones
**Estrategia**: Explota seasonalidad intradiaria comprobada en BTC: mejor rentabilidad 21:00-23:00 UTC (cierre de bolsas NYSE/LSE/Hang Seng). Entrada LONG: 20:50 UTC si RSI(14) > 50 en 1H chart. Salida: 23:15 UTC automático. Máx hold 2h 25 min. TP: +2.5% o tiempo cierre. SL: -1.2%. Parámetro de viernes: +bonus de +0.5% en TP por Friday effect (mejores returns). Timeframe: 1H. Mercado: BTC/USDT. Parámetros: utc_entry_window=20:50-21:00, utc_exit_time=23:15, friday_bonus=0.5%, holdtime_max=145min, rsi_confirm=50.
**Fuente**: [Intraday and daily dynamics of cryptocurrency](https://www.sciencedirect.com/science/article/pii/S1059056024006506) | [Bitcoin Intraday Seasonality Trading Strategy](https://www.quantifiedstrategies.com/bitcoin-intraday-seasonality-trading-strategy-backtest-results/)

---

## 12. AdaptiveMovingAverageKaufmanMomentum
**Estrategia**: Trend-following con Kaufman's Adaptive Moving Average (KAMA) que se ajusta dinámicamente según noise del mercado. KAMA = SMA 10 cuando volatilidad baja, EMA 3 cuando volatilidad alta. Entrada LONG: KAMA 50 cruza sobre KAMA 200 + RSI > 40. Entrada SHORT: KAMA 50 cruza bajo KAMA 200 + RSI < 60. TP: ±2.5%. SL: ±1.5%. Filtro: no operar si ATR 14 < 50 bps (sin volumen suficiente). Timeframe: 4H. Mercado: altcoins volatiles (DOGE, SHIB, PEPE). Parámetros: kama_fast_period=3, kama_slow_period=50, kama_long_period=200, efficiency_ratio_lookback=34.
**Fuente**: [Adaptive Moving Average Algorithm](https://www.luxalgo.com/library/indicator/adaptive-momentum-oscillator/) | [MESA Adaptive Moving Average](https://www.cryptohopper.com/resources/technical-indicators/434-mesa-adaptive-moving-average)

---

## 13. VarianceRiskPremiumHarvester
**Estrategia**: Venta de volatilidad mediante short straddle en opciones BTC/ETH. Vende ATM call + ATM put con expiración 7d. Entrada cuando IV percentile > 75 (IV elevada = premium alto para vender). TP: 50% de max profit (credit recibido). SL: si realized vol > IV implícita + 15%. Rebalance cada 2d. Posición size: 0.5 BTC notional. Filtro: no operar si skew está extreme (IV calls >> IV puts). Mercado: Deribit BTC/ETH opciones. Timeframe: 4H monitor, 1D entry. Parámetros: iv_percentile_threshold=75, premium_profit_target=0.50, realized_vol_sl_delta=0.15, position_sizing=0.5btc.
**Fuente**: [Portfolio Timing and Allocation with the Variance Risk Premium](https://harbourfronttechnologies.wordpress.com/2026/01/31/portfolio-timing-and-allocation-with-the-variance-risk-premium/) | [Variance Trading With Onchain Synthetic Perps](https://panoptic.xyz/research/variance-risk-premium-onchain-synthetic-perps)

---

## 14. PCAFactorMomentumLongShort
**Estrategia**: Factor-neutral long-short usando PCA en top 10 cryptos. Extrae 3 principales componentes (capturan ~90% de varianza). PC1 = market beta, PC2 = tamaño/volatilidad, PC3 = momentum. Construye cartera: LONG en cryptos con >0.5 exposición a PC3, SHORT en cryptos con <-0.5. Rebalance cada 7d. Posición size: 2 Bitcoin notional cada side. Target Sharpe: 2.0+. SL: si Sharpe cae <1.0 en ventana rolling 20d. Timeframe: 1D análisis, 4H rebalance. Parámetros: n_components=3, rebalance_days=7, long_threshold_pc3=0.50, short_threshold_pc3=-0.50, target_sharpe=2.0.
**Fuente**: [Principal component analysis based construction](https://www.sciencedirect.com/science/article/abs/pii/S0957417420306151) | [Using PCA on Crypto Correlations to Build Diversified Portfolio](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3918398)

---

## 15. SocialVolumeSpikeAnomalyDetection
**Estrategia**: Detecta anomalías en volumen social y social sentiment. Monitorea % cambio OBV (On-Balance Volume) 5m: si OBV sube >25% sin que precio suba =bulls entrando sigilosamente. Entrada LONG: OBV spike >25% + precio plano ±1%. TP: +2.5% cuando precio alcanza volumen anticipado. SL: si OBV revierte en próximas 4 velas -3%. Filtro: rechaza pump&dump usando trade size clustering detection (varianza trade size > 20% = sospechoso). Timeframe: 5m órdenes, 15m confirm. Parámetros: obv_spike_threshold=0.25, price_flatness_tolerance=0.01, trade_size_variance_reject=0.20, hold_time_max=4h.
**Fuente**: [Social volume spike detection crypto trading](https://altfins.com/knowledge-base/crypto-volume-tracker-spot-unusual-volume/) | [Detecting Crypto Pump-and-Dump Schemes](https://arxiv.org/html/2503.08692v1)

---

## Matriz de Estrategias

| # | Nombre | Categoría | Timeframe | Mercado | Dificultad |
|---|--------|-----------|-----------|---------|-----------|
| 1 | VPINLiquidityToxicity | Microstructure | 5m-15m | Perps | Alto |
| 2 | DynamicCointegrationPairs | Stat Arb | 4H | Spot | Muy Alto |
| 3 | VolatilitySurfaceSkew | Volatility | 1H-4H | Opciones | Muy Alto |
| 4 | BTCDominanceAltseason | Sector Rotation | 4H-1D | Spot Basket | Medio |
| 5 | FearGreedExtreme | Sentiment | 1H | BTC/ETH | Bajo |
| 6 | HiddenMarkovRegime | Regime-Adaptive | 1D-4H | BTC/ETH | Muy Alto |
| 7 | OrderBookLiquidity | Microstructure | 5m-1H | Spot | Alto |
| 8 | FuturesTermStructure | Basis Trading | 4H-1D | Spot+Perps | Medio |
| 9 | LiquidationCascade | Liquidation | 1m-5m | Perps | Alto |
| 10 | OnChainWhaleAccumulation | On-Chain | 4H-1D | Spot | Medio |
| 11 | IntradaySeasonality | Pattern | 1H | BTC | Bajo |
| 12 | AdaptiveMovingAverage | Trend-Following | 4H | Altcoins | Bajo |
| 13 | VarianceRiskPremium | Volatility | 1D | Opciones | Muy Alto |
| 14 | PCAFactorMomentum | Stat Arb | 1D-7D | Multi-Crypto | Muy Alto |
| 15 | SocialVolumeSpikeAnomaly | Microstructure | 5m-15m | Spot | Alto |

---

## Notas Importantes

1. **Nuevas vs Backlog Existente**: Las 15 estrategias NO aparecen en el backlog oficial (LiquidationDoubleDip, RSIBand, PairsTradingBTCETH, etc.). Todas enfatizan **nuevas dimensiones** de análisis.

2. **Backtesting Priority**:
   - Tier 1 (Implementar primero): FearGreedExtreme, IntradaySeasonality, AdaptiveMovingAverage (bajo riesgo implementación)
   - Tier 2: BTCDominanceAltseason, OnChainWhaleAccumulation, FuturesTermStructure
   - Tier 3: VPINLiquidityToxicity, OrderBookLiquidity, LiquidationCascade (requieren APIs + data quality)
   - Tier 4 (Research): DynamicCointegrationPairs, VolatilitySurfaceSkew, HiddenMarkovRegime, VarianceRiskPremium, PCAFactorMomentum (complejas, requieren validación exhaustiva)

3. **Data Requirements**:
   - **VPIN/Order Flow**: Coinalyze, 3Commas API, Tardis.dev
   - **On-Chain**: Glassnode, Nansen, CryptoQuant API
   - **Opciones**: Deribit API, Skew.com
   - **Fear&Greed/MVRV**: Alternative.me, CoinGlass, Glassnode
   - **Intraday 5m**: Binance WebSocket, Gateio, Bybit

4. **Edge Temporal**: Todas las estrategias usan data/research de 2025-2026. Papers incluyen noviembre 2025 → febrero 2026. Máxima relevancia actual.

---

**Próximos pasos**:
- Handed off a Strategy Agent para codificación + backtesting de Tier 1 strategies
- Risk Agent evalúa Sharpe, Sortino, max drawdown en historical data
- Registry: estrategias con Sharpe >1.5 + win rate >55% → producción
