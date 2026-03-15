# Future Research Backlog — RBI Agent

## Áreas No Cubiertas Aún (Para Próximas Sesiones)

### 1. **Graph Neural Networks (GNN) para Transaction Clustering**
**Relevancia**: Market Microstructure + Wash Trading Detection
**Hipótesis**: Las transacciones en blockchain tienen estructura de grafo. Detectando patrones anómalos en grafos podemos identificar:
  - Lavado de dinero ANTES de que se manifeste en precio
  - Traders coordinados (pump-and-dump groups)
  - Arbitrage triangular no evidente

**Papers a buscar**:
  - "Graph Neural Networks for Cryptocurrency Anomaly Detection" (2024-2025)
  - "Blockchain transaction graph analysis" (IEEE)
  - Chainbase.com research on transaction patterns

**Actionable**: Implementar GNN modelo de detección de coordinación → alertas para short positions


### 2. **Natural Language Processing (NLP) on Crypto News & Socials**
**Relevancia**: Sentiment Beyond Fear&Greed, Early Signal Detection
**Hipótesis**: Correlación entre sentiment en Twitter + Reddit + Medium y price moves 1-6 horas después

**Data sources**:
  - Twitter API v2 (filter keywords: #bitcoin, #ethereum, liquidation, crash, etc.)
  - Reddit r/cryptocurrency, r/crypto comments (Pushshift historical archive)
  - Medium crypto publications sentiment
  - Cointelegraph news sentiment

**Actionable**: Entrenar modelo BERT/DistilBERT en crypto corpus → daily sentiment score
  → Correlacionar con OHLCV 4H siguiente


### 3. **Perpetual Futures Funding Rate Forecasting (ML)**
**Relevancia**: Funding Rate Proxy → Sentiment Oscillator
**Current Strategy**: FundingRateProxy (en backlog), pero estático
**Enhancement**: Predecir siguiente funding rate usando LSTM/GRU

**Features**:
  - Funding rate últimas 24h
  - Open Interest trending
  - BTC dominance direction
  - Fear & Greed index
  - Exchange inflows/outflows (whale signal)

**Actionable**: Entrenar LSTM en histórico 2 años → predecir funding en t+1h
  → Si forecasted funding > 0.05% → preparar para reversal


### 4. **Cross-Exchange Arbitrage Exploits (DEX + CEX)**
**Relevancia**: Market Microstructure, Execution Risk
**Actual**: CeFi arbitrage well-known. But DEX-to-CEX mispricing?

**Investigation**:
  - Uniswap v3 liquidity clusters vs Binance order book
  - Flash loan opportunities detection
  - Sandwich attack prediction (MEV)

**Requires**: Real-time DEX liquidity monitoring (Uniswap API, Curve, Balancer)

**Actionable**: Pipeline DEX prices → compare Binance spreads → identify 0.5-2% arb windows


### 5. **Volatility Term Structure Trading (VIX-like for Crypto)**
**Relevancia**: Volatility Surface Enhancement
**Current**: VolatilitySurfaceSkew (new strategy). Extend to term structure.

**Concept**: Deribit has 7d, 14d, 30d, 60d expirations with different IVs
  → If term structure is steep (30d IV >> 7d IV) = market pricing crashes ahead
  → Opportunity: sell 30d calls, buy 7d calls (calendar spread)

**Data**: Deribit historical IV by maturity

**Actionable**: Backtest calendar spreads on Deribit 2023-2026


### 6. **Hidden Order Flow Detection (Iceberg Orders, Block Trades)**
**Relevancia**: Microstructure, Predicting large moves before market sees them
**Hypothesis**: Large institutional trades often hidden in icebergs.
  → Detecting pattern = predicting volume spike + direction

**Methodology**: ML model trained on:
  - Order book snapshots (visible orders)
  - Trade executions (inferred hidden volumes)
  - Price impact (reverse-engineering order size)

**Paper to find**: "Iceberg orders in cryptocurrency markets" (recent 2025)

**Actionable**: Model to detect when hidden buy wall likely (= price bounce coming)


### 7. **Regime Classification Beyond HMM (Transformer Models)**
**Relevancia**: Regime-Adaptive Strategies (HMM es 2020s solution, now outdated)
**Current**: HiddenMarkovRegimeSwitcher (new strategy). Better approach?

**Proposal**: Use Transformer attention to classify regimes
  - Input: OHLCV + RSI + MACD + volatility (last 90 candles)
  - Output: Probability distribution over [bull, bear, sideways, high-vol-low-trend, flash-crash]
  - Advantage over HMM: attention weights show "what mattered most" for regime

**Papers**:
  - "Transformer-based market regime classification" (2024-2025)
  - Any recent "attention mechanisms for financial regime" papers

**Actionable**: Train Vision Transformer on candle charts → compare with HMM performance


### 8. **Multi-Timeframe Confluence Detection (Meta-Strategy)**
**Relevancia**: Ensemble approach, reduce false signals
**Concept**:
  - If 1H + 4H + 1D all give BUY signal simultaneously = high confidence entry
  - Reward confluence with larger position size or tighter SL

**Methodological challenge**: How to standardize signals across timeframes?
  - Option A: Use normalized z-scores for all indicators
  - Option B: Convert all to buy/sell/neutral probabilities

**Actionable**: Backtest "confluence confidence metric" on Tier 1-2 strategies


### 9. **Liquidity Mining Arbitrage (LM Farming Tokens)**
**Relevance**: DeFi-specific, high-edge niche
**Hypothesis**: Some LP tokens on Uniswap v3 concentrated liquidity have mispriced rewards
  → Can farm 200%+ APR if you understand pool dynamics

**Risk**: Impermanent loss often eats profits. Needs dynamic hedging.

**Data Required**:
  - Uniswap subgraph (position history, swap volumes)
  - Token prices across exchanges
  - Gas cost modeling

**Actionable**: Find 3-5 optimal LP ranges per pair → backtest with IL hedging


### 10. **Maker/Taker Imbalance as Leading Indicator**
**Relevance**: Order Flow Microstructure
**Concept**: Ratio of market buy/sell volume to limit orders
  - High maker ratio = patient buying (accumulation)
  - High taker ratio = aggressive selling (distribution)
  - Extreme imbalances precede price moves 30sec-5min later

**Data**: Tamaño de órdenes ejecutadas vs tamaño de órdenes en book

**Actionable**: Build real-time maker/taker ratio detector → feed to existing momentum strategies


### 11. **Optimal Execution Algorithm (TWAP/VWAP Variants)**
**Relevance**: NOT a trading strategy, but infrastructure for strategy deployment
**Current**: TWAP in docs. But can we do better?

**Research**:
  - VWAP (volume-weighted average price) vs TWAP
  - Adaptive TWAP (adjust slice size based on market microstructure)
  - Minimize market impact for large positions

**Paper**: Talos "Execution Insights Through Transaction Cost Analysis" (2024)

**Actionable**: Implement best execution algo → reduce slippage on strategy exits by 10-20%


### 12. **Stablecoin Depegging Prediction**
**Relevance**: Tail Risk Management + Contrarian Entry Signal
**Hypothesis**: Before USDC/USDT depegging events, detectable signals:
  - Basis between spot and futures widens abnormally
  - Borrow rates on lending platforms spike
  - Options vol skew distorts (puts more expensive)

**Recent events**: USDC depeg March 2023 (SVB collapse)

**Actionable**: Monitor 5+ indicators → alert if any combinations trigger = hedge portfolio


### 13. **Latency Arbitrage Exploitation**
**Relevance**: HFT-adjacent, requires ultra-low latency infrastructure
**Concept**: Binance price moves 50ms before Kraken updates in some pairs
  → If you can trade at Binance + Kraken simultaneously with <10ms latency...

**Challenge**: Requires:
  - Direct exchange connections (not REST API)
  - Co-location possible? (some exchanges offer this)
  - WebSocket low-latency optimization

**Status**: Likely not viable for retail but good research exercise


### 14. **Recursive Risk-Parity Rebalancing**
**Relevance**: Portfolio construction for multi-strategy systems
**Concept**: Not single strategy, but how to weigh:
  - 3 Tier 1 strategies (low correlation)
  - 5 Tier 2 strategies
  - Rebalance quarterly based on rolling Sharpe

**Target**: Portfolio Sharpe > individual strategy Sharpes

**Actionable**: Once we have 5+ validated strategies, design allocation framework


### 15. **Catalyst-Driven Event Trading**
**Relevance**: Fundamental + Technical Hybrid
**Concept**:
  - FedoraWeek (Federal Reserve policy decisions)
  - FOMC meeting dates (known in advance)
  - Bitcoin halving events (predictable catalyst)
  - Regulatory announcements (less predictable)

**Research**: Historical returns patterns around these dates

**Actionable**: Build event calendar → overlay with technical signals


---

## Research Methodology Improvements

### Tools to Integrate
- [ ] **Databento**: High-quality crypto OHLCV + order book data (better than Binance free tier)
- [ ] **Tardis.dev**: Order book level 2/3 snapshots + VPIN calculation
- [ ] **Glassnode API Pro**: All on-chain metrics (SOPR, AVELONGS, AVEUN, RHODL, etc.)
- [ ] **Nansen API**: Cluster labels, whale behavior tracking
- [ ] **Panoptic Research**: Volatility surface data for options strategies
- [ ] **Dune Analytics**: SQL queries on blockchain data (can automate insights)

### Academic Sources to Monitor
- [x] arXiv.org (daily emails on "cryptocurrency trading", "market microstructure")
- [ ] SSRN (finance preprints, often 6-12 months ahead of journal publication)
- [ ] Journal of Financial Markets
- [ ] Journal of Futures Markets
- [ ] IEEE Transactions on Neural Networks
- [ ] ResearchGate notifications (follow top crypto researchers)

### Communities to Monitor
- [ ] Paradigm Research Twitter (market structure insights)
- [ ] Talos Trading blog (execution analysis)
- [ ] The Block Research (macroeconomic + on-chain correlation)
- [ ] Crypto Quant Twitter (on-chain metrics)
- [ ] QuantStart forums (quant trading discussions)

---

## Quick Wins (Could be Implemented This Week)

1. **Stablecoin Flow Indicator**
   - Monitor USDC/USDT inflows to exchanges
   - If surge (>$100M) → 12-24h later see price move
   - Data: CryptoQuant API (free tier has this)
   - Implementation: 4-6 hours

2. **Exchange Reserve Alert**
   - Glassnode "exchange netflow"
   - Spike up = accumulation coming
   - Spike down = distribution warning
   - Integration: 2-3 hours

3. **Difficulty Adjustment Impact**
   - Bitcoin has known difficulty adjustment dates
   - Historically +2-3% move before/after
   - Calendar-based + technical filter
   - Implementation: 3-4 hours

4. **Liquidation Heatmap Alerts**
   - CoinGlass liquidation data (free)
   - Alert when liquidation cluster > $50M in range
   - Entry trigger for cascade detector
   - Integration: 1-2 hours

---

## For Next RBI Agent Session

**Suggested Focus**:
1. Implement 2-3 of the "Quick Wins"
2. Deep research on **NLP for Sentiment** (highest ROI potential)
3. Compile **Options-Only Strategies Bundle** (Deribit-specific, high-edge niche)
4. Investigate **DEX Arbitrage Opportunities** (emerging frontier)

**Estimated Research Time**: 4-6 hours for each direction

---

**Last Updated**: March 15, 2026
**Maintained by**: RBI Agent
**Status**: Open for contributions from Strategy/Risk agents
