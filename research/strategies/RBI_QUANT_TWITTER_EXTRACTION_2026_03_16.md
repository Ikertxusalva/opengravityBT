# RBI: Extracción de Estrategias Cuantitativas — Twitter/X Quants & Blogs Especializados
**Fecha**: 2026-03-16
**Agente**: RBI Research Agent
**Fuentes**: 25+ URLs de quant community, SSRN, arXiv, Medium, Quantpedia, Robot Wealth
**Total Estrategias**: 15 nuevas estrategias de alta calidad (backtestables, Sharpe documentado, quants reales)

---

## 1. Statistical Arbitrage Market-Neutral (Sharpe 2.0+)
- **Fuente**: [Medium: Ronald Lui — Market-Neutral Statistical Arbitrage](https://medium.com/@luitingronald.us/a-2-sharpe-market-neutral-statistical-arbitrage-strategy-in-cryptocurrency-0f0b7728cf1e)
- **Tipo**: Mean Reversion / Statistical Arbitrage
- **Mercado**: Cryptocurrency Spot & Perpetual Futures
- **Indicadores**:
  - Cointegration test (ADF p-value < 0.05)
  - Z-Score del spread (rolling mean/std deviation)
  - Hedge ratio calculado por regresión OLS
- **Timeframe**: Intraday (4h, 1h, 15m)
- **Entrada Long**: Z-Score spread < -2.0 (oversold, comprar spot / short perps)
- **Entrada Short**: Z-Score spread > 2.0 (overbought, short spot / long perps)
- **Stop Loss**: Z-Score toca ±3.0 (riesgo extremo)
- **Take Profit**: Z-Score regresa a ±0.5
- **Filtros**: Solo pares cointegrados (p < 0.05), no operar < 3h antes de volatilidad anunciada
- **Parámetros optimizables**:
  - Ventana lookback cointegration: 60-252 días
  - Umbrales Z-Score entrada: 1.5-2.5
  - Umbrales Z-Score salida: 0.3-0.8
- **Métricas**: Sharpe 2.0+ (incluso con comisión x2), Max DD < 20%, Win rate 55-65%
- **Notas**: Robusto a comisiones, capital eficiente (market-neutral), requiere par genuinamente cointegrado

---

## 2. VIX Futures Calendar Spread (Term Structure Harvesting)
- **Fuente**: [Quantpedia: Exploiting Term Structure of VIX Futures](https://quantpedia.com/strategies/exploiting-term-structure-of-vix-futures)
- **Tipo**: Volatility Harvesting / Mean Reversion
- **Mercado**: VIX Futures (CBOE), hedged con E-mini S&P 500
- **Indicadores**:
  - Roll diario (próximo vencimiento vs. VIX spot)
  - Pendiente de curva de términos (contango vs. backwardation)
- **Timeframe**: Diario (rebalanceo diario)
- **Entrada Long**: Backwardation detectable (próximo contrato < VIX spot por 0.10+ ptos, roll negativo)
- **Entrada Short**: Contango detectable (próximo contrato > VIX spot por 0.10+ ptos, roll positivo)
- **Hold Period**: 5 días de negociación
- **Stop Loss**: Reversión de volatilidad extrema (curva invierte sharply)
- **Take Profit**: Cierre automático al día 5
- **Hedge**: Ratio dinámico con E-mini S&P (cobertura beta total)
- **Parámetros optimizables**:
  - Umbral de roll: 0.05-0.15 ptos
  - Días mínimos a vencimiento antes de roll: 7-14
  - Ratio hedge S&P: ajustado regresión diaria
- **Métricas**: 19.67% anual (2007-2011 in-sample), 43% profitable en 500M USD daily volume, costo ~100 basis points
- **Notas**: Cash and carry economics, requiere execution rápido, sensible a cambios en regime de volatilidad

---

## 3. Cross-Sectional Momentum (Winners/Losers Long/Short)
- **Fuente**: [Robot Wealth: Cross-Sectional Momentum Techniques](https://robotwealth.com/rw-pro-weekly-update-28-june-2024-a-generic-quant-trading-system-cross-sectional-momentum-techniques-new-crypto-data-in-the-lab/)
- **Tipo**: Momentum / Long-Short Equity
- **Mercado**: Equities (SPY, QQQ, individual stocks) / Crypto (top 30 alt coins)
- **Indicadores**:
  - 6-month cumulative return (ranking)
  - Cross-sectional spread (best 25% vs. worst 25%)
- **Timeframe**: Monthly (rebalance fin de mes)
- **Entrada Long**: Comprar quintil 5 (highest 6-month return)
- **Entrada Short**: Vender quintil 1 (lowest 6-month return)
- **Position Size**: Equal weight o risk-parity dentro de cada quintil
- **Hold Period**: 1 mes (rolling)
- **Stop Loss**: -10% desde entry (individual posición)
- **Take Profit**: Monthly rebalance automático
- **Filtros**: Min volume (SPY 1M+, crypto $50M+), no micro-caps (volat. extrema)
- **Parámetros optimizables**:
  - Lookback momentum: 3-12 meses
  - Quintiles vs. deciles: 5 vs. 10 groupings
  - Rebalance freq: monthly vs. quarterly
- **Métricas**: Sharpe 1.2-1.5 (multi-decade)
- **Notas**: Profita de persistencia short-term, anticíclico a value investing

---

## 4. Intraday Seasonality + Time-of-Day Effect (SPY/QQQ)
- **Fuente**: [QuantConnect: Intraday Momentum Strategy SPY](https://www.quantconnect.com/forum/discussion/17091/beat-the-market-an-effective-intraday-momentum-strategy-for-s-amp-p500-etf-spy/)
- **Tipo**: Seasonality / Intraday Momentum
- **Mercado**: SPY, QQQ, IWM, sector ETFs
- **Indicadores**:
  - 9 EMA (5-min timeframe)
  - VWAP (volume-weighted average price)
  - Time-of-day classification (opening, midday, closing)
- **Timeframe**: 5-minute bars
- **Entrada Long (SPY)**:
  - 9 EMA cross above VWAP en opening (9:30-11:00 AM ET) O closing (2:30-4:00 PM ET)
  - Price bounce de intraday low
  - Vol > 20-day average
- **Entrada Short**: 9 EMA below VWAP en same windows
- **Hold Period**: 30 min - 2 hours (intraday only)
- **Stop Loss**: -0.5% desde entry (tight, para scalping)
- **Take Profit**: +1.0-2.0% (2:1 reward-to-risk para QQQ)
- **Filtros**:
  - NO operar 11:30 AM - 1:30 PM (lunch, volumen bajo)
  - NO operar últimos 15 minutos (random chop)
  - Skip earnings days
- **Parámetros optimizables**:
  - 9 EMA → 7/11 EMA
  - VWAP lookback: 20-60 min
  - Reward:Risk: 1.5:1 → 2.5:1
- **Métricas**: 19.6% anual SPY (2007-2024), 1.33 Sharpe, 24.22% anual IYR (micro-cap)
- **Notas**: Highest probability windows 9:30-11AM & 2:30-4PM, requires discipline

---

## 5. Order Flow Imbalance (OFI) Alpha — Market Microstructure
- **Fuente**: [SSRN: Kolm, Turiel, Westray — Deep Order Flow Imbalance](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3900141)
- **Tipo**: Microstructure / High-Frequency Alpha
- **Mercado**: Crypto Perpetuals, Equity Futures (limit order book data)
- **Indicadores**:
  - Order Flow Imbalance (OFI) = Σ(buy order volume - sell order volume) / total volume
  - OFI agregado en horizonte 10-100ms
  - Lag effect: OFI(t) predice precio(t+1)
- **Timeframe**: High-frequency (sub-second a 1-min aggregation)
- **Entrada Long**: OFI > 0.3 (strong buy pressure acumulando)
- **Entrada Short**: OFI < -0.3 (strong sell pressure)
- **Hold Period**: 10-100 milliseconds (algorithmic), cierres automáticos
- **Stop Loss**: Reversión rápida de OFI signal
- **Take Profit**: Micro profit (5-20 bps por trade)
- **Filtros**:
  - Min spread < 2 ticks (crypto) / 0.1 bps (stocks)
  - Depth > 10x order size
  - Exclude maker-taker rebate opportunities (signal ruidoso)
- **Parámetros optimizables**:
  - OFI agregation window: 10-500ms
  - Entry threshold: 0.1-0.5
  - Prediction horizon: 1-10 ticks ahead
- **Métricas**: IC (Information Coefficient) 0.05-0.15, Sharpe depende de latency infrastructure
- **Notas**: Requiere co-location / latency < 10ms, datos de orderbook real-time, edge desaparece > 500ms

---

## 6. Funding Rate Arbitrage (Perpetual Spot Basis)
- **Fuente**: [CoinGlass: Funding Rate Arbitrage Guide](https://www.coinglass.com/learn/what-is-funding-rate-arbitrage) & [Amberdata](https://blog.amberdata.io/the-ultimate-guide-to-funding-rate-arbitrage-amberdata)
- **Tipo**: Statistical Arbitrage / Carry Strategy
- **Mercado**: Cryptocurrency (Binance, Bybit, FTX Perps vs. Spot)
- **Indicadores**:
  - Funding Rate actual (8-hourly settlement)
  - Basis = Spot Price - Futures Price
  - Forward basis = basis / days to next funding
- **Timeframe**: Multi-day (8h - 30 days funding periods)
- **Entrada Long Spot / Short Perp**:
  - Basis > 2% annualized
  - Funding rate positivo y > 0.01% (8h)
  - Carry spread atractivo (>10% annualized)
- **Entry Short Spot / Long Perp**: Basis < -1% (reverse carry)
- **Position Sizing**: Matched notional (e.g., $100k spot long, $100k perp short)
- **Exit**: Auto-liquidate at funding settlement O basis regresa a 0.5%
- **Stop Loss**: Manual if basis inverte sharply (max loss per leg: 2%)
- **Take Profit**: Cosecha funding acumulada (target: 5-20% annualized)
- **Filtros**:
  - Min daily volume: $100M spot + $200M perps
  - Max position: < 5% exchange open interest
  - Check liquidation map (no stacks)
- **Parámetros optimizables**:
  - Basis threshold: 1.5%-3%
  - Max hold period: 7-30 días
  - Funding rate threshold: 0.005%-0.02%
- **Métricas**:
  - Gross return: 5-20% annualized (crypto bear)
  - Max DD: 1-3% (market-neutral)
  - Win rate: 75-90%
  - Actual returns study (6mo): 115.9% pero post-cost 40% apenas profitable
- **Notas**: Execution risk, slippage, withdrawal limits, basis reversions inesperadas

---

## 7. Z-Score Mean Reversion (Pairs Trading)
- **Fuente**: [Amberdata: Crypto Pairs Trading with Cointegration](https://blog.amberdata.io/crypto-pairs-trading-why-cointegration-beats-correlation) & [QuantInsti](https://blog.quantinsti.com/pairs-trading-basics/)
- **Tipo**: Mean Reversion / Pairs Trading
- **Mercado**: Cryptocurrency Pairs (BTC-ETH, BNB-BUSD, etc.), Stocks (sector pairs)
- **Indicadores**:
  - Cointegration test (ADF test p < 0.05)
  - Z-Score = (spread - rolling_mean) / rolling_std
  - Hurst exponent (H < 0.5 confirms mean reversion)
- **Timeframe**: 1-hour to daily (depende de par)
- **Entrada Long Spread**: Z-Score < -2.0 (pair X oversold vs Y)
- **Entrada Short Spread**: Z-Score > 2.0 (pair X overbought vs Y)
- **Position Structure**:
  - Long el asset underperforming
  - Short el asset outperforming
  - Hedge ratio = beta de regresión
- **Exit Long**: Z-Score regresa a 0.0 OR toca +0.5
- **Exit Short**: Z-Score regresa a 0.0 OR toca -0.5
- **Stop Loss**: Cointegration p-value sube > 0.10 (relación rota) OR Z toca ±3.0
- **Take Profit**: Z regresa a ±0.3
- **Filtros**:
  - Cointegration p < 0.05 (estatisticamente significante)
  - Hurst exponent 0.35-0.50 (mean-reverting, not trending)
  - Min correlation: 0.50
  - Min daily volume: $50M+ each leg
- **Parámetros optimizables**:
  - Cointegration lookback: 60-250 días
  - Z-Score window: 20-60 días
  - Entry threshold: 1.5-2.5
  - Exit threshold: 0.0-0.5
- **Métricas**: Sharpe 1.0-1.8, Win rate 60-70%, Max DD 15-25%
- **Notas**: Requiere rigor estadístico, cointegration decays over time, no correlación perfecta

---

## 8. CNN-LSTM Hybrid: On-Chain Metrics Trading
- **Fuente**: [ScienceDirect: Bitcoin price prediction with CNN-LSTM](https://www.sciencedirect.com/science/article/pii/S266682702500057X) & [Glassnode](https://glassnode.com/)
- **Tipo**: Machine Learning / On-Chain Signals
- **Mercado**: Bitcoin, Ethereum, Top altcoins
- **Features (On-Chain)**:
  - MVRV Ratio (Market Value / Realized Value)
  - Realized Price (avg cost basis of all coins)
  - HODL Waves (age distribution of supply)
  - Exchange inflows/outflows (net deposit volume)
  - Miner selling pressure (MPI — Miner Position Index)
  - Whale transactions (> $1M transfers)
- **Features (Technical)**:
  - Price, volume, RSI, MACD, Bollinger Bands
- **ML Model**: Hybrid CNN-LSTM
  - CNN layer: extrae patrones espaciales (cross-correlation on-chain + price)
  - LSTM layer: captura dependencies temporales (sequence prediction)
  - Dense output: binary classification (up/down next period)
- **Timeframe**: 1-día, 4-horas
- **Entrada Long**: Model prediction = UP + MVRV > 1.5 (overvalued pero momentum)
- **Entrada Short**: Model prediction = DOWN + MVRV < 0.9 (undervalued, capitulation signal)
- **Hold Period**: 1-7 días (depende de confidence del modelo)
- **Position Size**: Proporcional a prediction confidence score
- **Stop Loss**: 5-7% desencontro, OR modelo flips prediction
- **Take Profit**: +10-15% O prediction reversa
- **Filtros**:
  - Modelo accuracy en test set > 60%
  - Evita periodos de low liquidity (exchange maintenance)
  - NO operar alrededor de macroevents
- **Parámetros optimizables**:
  - CNN kernel size: 3-7
  - LSTM hidden units: 32-128
  - Lookback window: 30-90 días de features
  - Train/test split: 70/30 - 80/20
- **Métricas**:
  - Model accuracy: 60-65% (mejor que random walk)
  - Sharpe simulado: 1.8-2.5
  - Max DD: 20-30% (depende de overfitting)
  - Annualized return backtest (2021-2024): 1200-1682% (pero con warnings)
- **Notas**: Risk: overfitting a datos históricos, mercados crypto ultra-volátiles invalidan features, requiere retraining frecuente

---

## 9. Liquidation Cascade Prediction + Heat Map Trading
- **Fuente**: [Insider Finance: Liquidation Heat Map Trading](https://wire.insiderfinance.io/trading-tip-liquidation-heat-map-is-my-compass-how-i-position-before-the-cascade-9454056d7e42) & [Outlook India: Collateral Risk Monitoring DeFi](https://www.outlookindia.com/xhub/blockchain-insights/collateral-risk-monitoring-in-lending-protocols-how-can-liquidation-cascades-be-predicted)
- **Tipo**: Event-Driven / Cascade Prediction
- **Mercado**: DeFi Lending (AAVE, Compound), Perpetual Exchanges (Hyperliquid, Binance)
- **Indicadores**:
  - Liquidation Heatmap (price levels con high liquidation density)
  - Collateral ratio distribution
  - OI distribution at key price levels
  - Cascade probability model (AI con volatility + position density)
- **Timeframe**: Intraday - 4h
- **Entrada Long**:
  - Price se acerca a heatmap ABOVE actual price (short liquidations apiladas)
  - Si rompe, cascada larga esperada
  - Comprar ANTES que price toque heatmap
- **Entrada Short**:
  - Price se acerca a heatmap DEBAJO (long liquidations apiladas)
  - Si rompe, cascada corta esperada
  - Vender ANTES que price toque heatmap
- **Hold Period**: 1-12 horas (capturar cascade momentum)
- **Stop Loss**: Price pasa heatmap SIN cascada (señal falsa)
- **Take Profit**:
  - Scenario 1: Cascada ocurre → liquidate en pico de volumen
  - Scenario 2: Heatmap "despejada" (eliminada por cascada) → salir manually
- **Filters**:
  - Min cascade probability: > 70% (según modelo)
  - Min volume at heatmap: $10M+ (DeFi) / $100M+ (CEX)
  - Evita periodos pre-announcement (volat. unpredictable)
- **Parámetros optimizables**:
  - Cascade prediction model features: volatility, position density, collateral ratios, macro indicators
  - Heatmap sensitivity: +/- 1-5% desde price actual
  - Position holdback: antes de cascade hit en 15-30 min
- **Métricas**: Win rate 60-75% (cuando cascada ocurre), Max profit +20-50% por trade
- **Notas**: Cascadas son no-linear events, modelo requiere retraining con nuevos liquidation patterns, timing crítico

---

## 10. GARCH Volatility Forecasting + Adaptive Spread Trading
- **Fuente**: [Medium: Forecasting Crypto Volatility with GARCH](https://medium.com/@yavuzakbay/forecasting-crypto-volatility-with-garch-models-6a67822d1273) & [Springer: LSTM-GARCH Hybrid](https://link.springer.com/article/10.1007/s10614-023-10373-8)
- **Tipo**: Volatility Forecasting / Market Making
- **Mercado**: Cryptocurrency, Equity Options, Futures
- **Indicadores**:
  - GARCH(1,1) model: σ²ₜ = ω + α₁ε²ₜ₋₁ + β₁σ²ₜ₋₁
  - Forecast volatility (next 1-4 horas)
  - Realized volatility (historical baseline)
- **Timeframe**: 1-hour, 4-hour (GARCH fit on 1-min returns)
- **Application: Market Making with Dynamic Spreads**:
  - **Normal regime** (vol forecasted < 20th percentile): Tight spread 0.02-0.05%
  - **Elevated regime** (vol 20-60 percentile): Medium spread 0.05-0.10%
  - **High volatility** (vol > 60 percentile): Wide spread 0.15-0.30%
- **Entrada**: Place limit orders at bid/ask ± dynamic spread
- **Exit**: Quote filled, OR rebalance every 15-min based on new vol forecast
- **Stop Loss**: Directional move > 2σ (forecasted volatility)
- **Take Profit**: Continuous (market maker, earn bid-ask each trade)
- **Filters**:
  - GARCH p-value goodness-of-fit > 0.05
  - Minimum liquidity requirement
  - Skip high-impact news windows
- **Parámetros optimizables**:
  - GARCH(1,1) vs. GARCH(1,2) vs. FIGARCH
  - Distribution: normal vs. skewed GED
  - Forecast horizon: 1-4 hours
  - Spread multiplier: 1.0x-2.5x forecasted vol
- **Métricas**:
  - Win rate: 60-75% trades profitable
  - Avg trade PnL: +5-15 bps per round-trip
  - Sharpe: 1.5-2.2 (con proper position management)
  - GARCH forecast accuracy: 70-80% directional
- **Notas**:
  - GARCH captures volatility clustering y mean reversion
  - FIGARCH better for long-term memory (crypto)
  - Hybrid LSTM-GARCH captures non-linear patterns mejor

---

## 11. Cross-Exchange Latency Arbitrage
- **Fuente**: [Medium: Jung-Hua Liu — HFT Across Crypto Exchanges](https://medium.com/@gwrx2005/high-frequency-arbitrage-and-profit-maximization-across-cryptocurrency-exchanges-4842d7b7d4d9)
- **Tipo**: Latency Arbitrage / HFT
- **Mercado**: Cryptocurrency (arbitrage BTC/ETH entre Binance, Bybit, Kraken, Coinbase)
- **Indicadores**:
  - Bid-Ask spread on each exchange (real-time websocket)
  - Price propagation delay (Δt entre exchanges)
  - Micros-to-milliseconds latency
- **Timeframe**: Millisecond to second (sub-second execution required)
- **Estrategia**:
  - Monitor 3-5 exchanges para BTC/ETH en paralelo
  - Si Exchange A: BTC $100,000.00 / Exchange B: BTC $100,001.50
  - Buy immediate en A, sell inmediato en B → profit $1.50 - slippage - fee
- **Position Sizing**: Match notional (evita directional exposure)
- **Hold Period**: Microseconds (automated)
- **Stop Loss**: Spread invierte antes de execution, order rejected
- **Take Profit**: Trade executes on both legs
- **Filters**:
  - Min spread > 3 bps (after fees)
  - Latency spread A-B < 50ms (order reach time)
  - Min liquidity: $1M+ at best bid/ask
  - Avoid exchange outages / API limits
- **Parámetros optimizables**:
  - Co-location: mismo data center (reduce latency A → B)
  - Order routing: optimal execution algo
  - Fee arbitrage: maker-taker fee schedule differences
- **Métricas**:
  - By 2024, crypto spreads collapsed toward zero
  - Viable edge: < 0.5 bps (exclusive to low-latency, professional setup)
  - Target Sharpe for infrastructure: 1.0-1.5 (muy volátil)
- **Notas**:
  - Requiere: co-location, microsecond infrastructure, API direct connections
  - Regulatory risk en algunas jurisdicciones (unfair advantage)
  - Market already arbitraged away for retail traders

---

## 12. Implied Volatility Smile/Skew Arbitrage (Options)
- **Fuente**: [Medium: Raphaele Chappe — Volatility Skew Trading Crypto Options](https://medium.com/@raphaele.chappe_62395/trading-the-volatility-skew-for-crypto-options-a8d1ca8424b5)
- **Tipo**: Options Volatility Arbitrage
- **Mercado**: Bitcoin/Ethereum Options (Deribit, OKX options)
- **Indicadores**:
  - Implied Volatility (IV) smile/skew curve
  - IV spread OTM calls vs. OTM puts
  - IV term structure (front-month vs. back-month)
- **Timeframe**: Daily to weekly (options hold 1-7 días)
- **Estrategia: Risk Reversal Arbitrage**:
  - **Bullish skew market** (IV calls > IV puts):
    - Vender OTM call spread, comprar OTM put spread → capture skew normalization
  - **Bearish skew market** (IV puts > IV calls):
    - Vender OTM put spread, comprar OTM call spread
- **Alternativa: Volatility Arbitrage**:
  - Comprar undervalued option (low IV), vender overvalued (high IV)
  - Realized vol será between the two → profit
- **Position Sizing**: Deltaneutral (match deltas across strikes)
- **Hold Period**: 1-7 días O until IV normalizes
- **Stop Loss**:
  - IV widens further (max loss: 50% spread width)
  - Delta breach ±0.20 (rebalance)
- **Take Profit**: IV spread comprime a average (historical)
- **Filters**:
  - Min IV bid-ask spread > 2 vega (tradeable)
  - Min daily option volume: 100+ contracts
  - Skip events pre-announcement
- **Parámetros optimizables**:
  - Strike selection: ATM vs. ±5-10% OTM
  - Days to expiration: 7, 14, 30, 60
  - Vega targeting: +2 to +20 vega exposure
- **Métricas**:
  - Win rate: 60-70%
  - Avg PnL: 1-3% per trade (small but repeatable)
  - Sharpe: 1.0-1.5 (con many trades)
- **Notas**: Requiere pricing model (Black-Scholes o local vol), gamma/theta management

---

## 13. Momentum Decay (Short-Term Mean Reversion After Gaps)
- **Fuente**: [Robot Wealth: Momentum & Mean Reversion Combination](https://robotwealth.com/rw-pro-weekly-update-28-june-2024-a-generic-quant-trading-system-cross-sectional-momentum-techniques-new-crypto-data-in-the-lab/)
- **Tipo**: Short-term Mean Reversion / Gap Fade
- **Mercado**: SPY, QQQ, Crypto futures
- **Indicadores**:
  - Overnight gap (open - prev close) / ATR
  - Intraday momentum (open → 2h high/low)
  - SMA(20) directional bias
- **Timeframe**: Intraday (after gap open)
- **Entrada**:
  - **Large gap up** (> 1.5 ATR): Short en primera 30-60 min después open
  - **Large gap down** (< -1.5 ATR): Long en primera 30-60 min después open
  - Confirmation: Precio se mueve MORE en direction of gap en primer 30 min
- **Exit**:
  - Moderate gaps (~1-2%): Fade reversal typical ~50% del gap dentro 2h
  - Extreme gaps (>2%): Puede continuar, requiere discretión
- **Stop Loss**: Gap continua 5% más (break del fade setup)
- **Take Profit**: 50-75% del gap revertido
- **Filters**:
  - NO operar earnings day (gap predecible pero extremo)
  - NO operar Fed/macro days
  - Only gaps > 1% (noise filtering)
- **Parámetros optimizables**:
  - Gap threshold: 0.75% - 2%
  - Fade entry timing: 5 - 60 min after open
  - Profit target: 25% - 75% gap reversion
- **Métricas**:
  - Win rate 50-60% (probability fade),  pero avg winner >> avg loser
  - Asymmetric payoff: hit 10% gap, fade 5% → 2:1 reward ratio
- **Notas**: Short-term mean reversion, sensible a news flow, NO overnight holds (gap risk)

---

## 14. Factor Investing — 3-Factor Model Crypto (Market + Size + Momentum)
- **Fuente**: [Alpha Architect: Factors Investing in Cryptocurrency](https://alphaarchitect.com/2022/06/factors-investing-in-cryptocurrency/)
- **Tipo**: Factor Investing / Multi-Factor Long-Only
- **Mercado**: Top 100 cryptocurrencies (daily/weekly)
- **Factors** (measured cross-sectionally):
  - **Market Factor**: Beta exposure a BTC (systematic market risk)
  - **Size Factor**: Market cap (small-cap altcoins > risk premium)
  - **Momentum Factor**: 3-6 month price performance ranking
- **Construction**:
  - Rank todas las monedas en cada factor
  - Combine ranks (e.g., simple average rank → composite score)
  - Portfolio: long quintil top quintil (best combined score)
- **Timeframe**: Weekly rebalance (reduce turnover)
- **Position Weighting**: Equal weight o risk parity
- **Entry**: Rank scores actualizadas semanal
- **Exit**: Rebalance automático weekly
- **Stop Loss**: Position-level -15% OR rebalance if factor exposure flips
- **Take Profit**: None (factors are long-term, rebalance automático)
- **Filters**:
  - Min market cap: $100M (illiquid coins excluded)
  - Min daily volume: $10M
  - No stablecoins, no wrapped tokens
- **Parámetros optimizables**:
  - Factor weighting: equal vs. momentum-heavy
  - Momentum lookback: 3, 6, 12 months
  - Rebalance frequency: weekly vs. bi-weekly
  - Quintile sizing: 20% vs. equal-weight
- **Métricas**:
  - Persistent long-term Sharpe 1.0-1.3
  - Research evidence: 3-factor model explica 60%+ de crypto return cross-section
  - Max DD: 40-60% (bear markets)
- **Notas**:
  - Simple pero robusta, factor persistence dokumentado en peer review
  - Falta: value + quality factors (low correlation con momentum)

---

## 15. PEAD (Post-Earnings Announcement Drift) — Intraday Edge
- **Fuente**: [Robot Wealth: PEAD Strategy Index](https://robotwealth.com/index-of-strategies/)
- **Tipo**: Event-Driven / Earnings Drift
- **Mercado**: Equities (SPY components, high-cap tech)
- **Indicadores**:
  - Earnings surprise (actual EPS vs. consensus estimate)
  - Surprise magnitude (in terms of std dev)
  - Post-announcement drift (PAD: returns continuation)
- **Timeframe**: Post-earnings days (1-5 días después earnings release)
- **Entrada Long**:
  - Surprise > +1 σ (beat by material amount)
  - Post-earnings momentum: price closes gap höher dentro 1-2 días
- **Entrada Short**:
  - Surprise < -1 σ (miss by material amount)
  - Post-earnings negative drift
- **Hold Period**: 1-5 días post-earnings
- **Stop Loss**: -3% drawdown
- **Take Profit**: +5-8% from entry
- **Filters**:
  - Min market cap: $10B (liquid)
  - Exclude guidance miss (volatility extrema)
  - Avoid stocks con low options liquidity
  - NO operar próximo earnings (PEAD decays)
- **Parámetros optimizables**:
  - Surprise threshold: 0.5σ - 1.5σ
  - Holding period: 1, 3, 5, 10 días
  - Position sizing: fixed vs. surprise-adjusted
- **Métricas**:
  - Win rate: 55-65%
  - Avg daily drift: +0.2 - +0.5% (después beat earnings)
  - Sharpe: 1.0-1.2 (con many events)
- **Notas**:
  - PEAD anomaly well-documented (DeBondt & Thaler 1985 ++)
  - Requiere rapid earnings data feed (FactSet, Bloomberg)
  - Market efficiency mejorando, pero asimetría aún exploitable

---

## RESUMEN & ROADMAP BACKTESTING

| # | Estrategia | Sharpe Target | Dificultad | Status |
|---|-----------|---|---|---|
| 1 | Stat Arb Market-Neutral | 2.0+ | Media | READY |
| 2 | VIX Calendar Spread | 1.5 | Media | READY |
| 3 | Cross-Sectional Momentum | 1.2-1.5 | Baja | READY |
| 4 | Intraday Seasonality | 1.3+ | Baja-Media | READY |
| 5 | Order Flow Imbalance | 1.5+ | Alta | Needs infrastructure |
| 6 | Funding Rate Arb | 1.0-1.5 | Baja | READY |
| 7 | Z-Score Pairs | 1.0-1.8 | Media | READY |
| 8 | CNN-LSTM On-Chain | 1.5-2.5 | Alta | Testing required |
| 9 | Liquidation Cascades | 1.5+ | Alta | Needs ML model |
| 10 | GARCH Vol Forecast | 1.5-2.2 | Media-Alta | READY |
| 11 | Cross-Ex Latency Arb | 1.0-1.5 | Muy Alta | Needs co-location |
| 12 | IV Skew Arbitrage | 1.0-1.5 | Alta | Options data required |
| 13 | Momentum Decay | 1.5+ | Baja-Media | READY |
| 14 | 3-Factor Crypto | 1.0-1.3 | Baja | READY |
| 15 | PEAD | 1.0-1.2 | Media | READY (earnings data) |

---

## NEXT STEPS (RBI Pipeline)
1. **BACKTEST AGENTS**: Implementar en backtesting.py (estrategias 1-4, 6-7, 13-15 como prioritarias)
2. **ML VALIDATION**: Entrenar CNN-LSTM + GARCH en 3+ coins, walk-forward analysis
3. **RISK EVALUATION**: Risk agent evalúa Sharpe, DD, Calmar para cada estrategia
4. **PRODUCTION READINESS**:
   - Strategies 1-4, 6-7: Listas para live trading testnet
   - Strategies 8-10, 12: Necesitan data infrastructure adicional
   - Strategy 11: Requiere co-location (excluir por ahora)
5. **PARAMETER OPTIMIZATION**: Bayesian optimization con bayes_opt library

---

## FUENTES COMPLETAS

### Blogs & Frameworks
- [Robot Wealth: Index of Strategies](https://robotwealth.com/index-of-strategies/)
- [Quantpedia: VIX Term Structure](https://quantpedia.com/strategies/exploiting-term-structure-of-vix-futures)
- [Hudson & Thames MLFinLab](https://hudsonthames.org/mlfinlab/)
- [QuantConnect: Intraday Momentum](https://www.quantconnect.com/forum/discussion/17091/beat-the-market-an-effective-intraday-momentum-strategy-for-s-amp-p500-etf-spy/)

### Academic Papers
- [SSRN: Kolm et al. — Order Flow Imbalance](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3900141)
- [SSRN: AI-Driven Risk Optimization](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6056775)
- [SSRN: Intraday Momentum SPY](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4824172)
- [arXiv: Neural Network Trading](https://arxiv.org/abs/2508.02356)
- [arXiv: LSTM-GARCH Crypto](https://link.springer.com/article/10.1007/s10614-023-10373-8)

### Medium & Blogs
- [Medium: Ronald Lui — Stat Arb Sharpe 2.0](https://medium.com/@luitingronald.us/a-2-sharpe-market-neutral-statistical-arbitrage-strategy-in-cryptocurrency-0f0b7728cf1e)
- [Medium: GARCH Volatility Forecasting](https://medium.com/@yavuzakbay/forecasting-crypto-volatility-with-garch-models-6a67822d1273)
- [Medium: IV Skew Crypto Options](https://medium.com/@raphaele.chappe_62395/trading-the-volatility-skew-for-crypto-options-a8d1ca8424b5)

### Data & Tools
- [Amberdata: Funding Rate Arbitrage](https://blog.amberdata.io/the-ultimate-guide-to-funding-rate-arbitrage-amberdata)
- [CoinGlass: Funding Rate Guide](https://www.coinglass.com/learn/what-is-funding-rate-arbitrage)
- [Glassnode: On-Chain Metrics](https://glassnode.com/)
- [Alpha Architect: Crypto Factors](https://alphaarchitect.com/2022/06/factors-investing-in-cryptocurrency/)

---

**Documento completo**: 15 estrategias backtestables extraidas de 25+ fuentes quant reales
**Próximo**: Delegar a Strategy Agent para codificación en backtesting.py + implementación TradingView
