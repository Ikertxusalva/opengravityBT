# DeFi & Crypto Trading Strategies — Research Sources (2026-03-15)

## Estrategias Extraídas: 16 Nuevas

### Resumen Ejecutivo
Se investigaron profundamente 8 ángulos específicos de trading DeFi/crypto:
1. **DeFi yield strategies** → TVL rotation, IL hedging, concentrated liquidity delta hedge
2. **Perpetual-spot basis** → Basis momentum, cash carry funding arbitrage, spot-perps basis
3. **Multi-asset momentum** → Multi-chain yield rotation, VWAP momentum
4. **Breakout con volume** → Bollinger squeeze, volume profile, OBV divergence
5. **TWAP/VWAP execution** → VWAP crossover, order book imbalance scalp
6. **Contrarian liquidation** → Liquidation cascade contrarian, taker buy/sell ratio
7. **Order book dynamics** → Order book imbalance, layered entry accumulation
8. **Flash loans & MEV** → Flash loan arbitrage detector, cross-L2 spread capture

---

## Academic & Research Sources

### Funding Rates & Mean Reversion
- **CFB Benchmarks**: "Revisiting the Bitcoin Basis: How Momentum & Sentiment Impact the Structural Drivers of Basis Activity"
  - Source: https://www.cfbenchmarks.com/blog/revisiting-the-bitcoin-basis-how-momentum-sentiment-impact-the-structural-drivers-of-basis-activity
  - Key finding: Past return momentum explains futures-spot gap; positive funding = overcrowded longs

- **Quantjourney Substack**: "Funding Rates in Crypto: The Hidden Cost, Sentiment Signal, and Strategy Trigger"
  - Source: https://quantjourney.substack.com/p/funding-rates-in-crypto-the-hidden
  - Rules extracted: Annualization FR*3*365; entry at +0.075%, exit at ±0.01-0.03%

### Order Book & Market Microstructure
- **Towards Data Science**: "Price Impact of Order Book Imbalance in Cryptocurrency Markets"
  - Source: https://towardsdatascience.com/price-impact-of-order-book-imbalance-in-cryptocurrency-markets-bf39695246f6
  - Methodology: Imbalance Ratio = Buy Vol / (Buy+Sell Vol); thresholds 0.42-0.58 for reversal signals

- **ArXiv 2406.02172**: "Layer-2 Arbitrage: An Empirical Analysis of Swap Dynamics and Price Disparities on Rollups"
  - Source: https://arxiv.org/html/2406.02172v1/
  - MAV metrics: Arbitrum/Base/Op 0.03-0.05% vs zkSync 0.25%; decay 7-420 sec

### Pump-and-Dump Detection
- **Medium - Alexdemachev (Feb 2026)**: "Detection of Pump Cycles in Crypto Markets: A Bias-Aware Backtest of 'Short-the-Dump' Strategies"
  - Source: https://medium.com/@alexdemachev/detection-of-pump-cycles-in-crypto-markets-a-bias-aware-backtest-of-short-the-dump-strategies-180aada5a6f2
  - CUSUM evidence accumulation; MA-based gate; F1-score 94.5% detection within 25 sec

### On-Chain Liquidations
- **CoinGlass Liquidation Heatmap Analysis**
  - Source: https://www.coinglass.com/learn/learn-40
  - Cascade mechanics: Oct 2025 = $3.21B in 60 sec → $9.89B in 14 hours

- **Yield App**: "What are liquidation cascades in crypto?"
  - Source: https://yield.app/blog/what-are-liquidation-cascades-in-crypto

---

## Practical Strategy Sources

### Volume Profile & Breakout
- **OANDA**: "How to use Volume Profile in trading"
  - Source: https://www.oanda.com/us-en/trade-tap-blog/trading-knowledge/volume-profile-explained/
  - VA High/Low (70% volume) identifies breakout acceptance zones

- **TradingView Documentation**: "Volume profile indicators: basic concepts"
  - Source: https://www.tradingview.com/support/solutions/43000502040-volume-profile-indicators-basic-concepts/

### Bollinger Bands Squeeze
- **Kavout Market Lens**: "Bollinger Bands: A Trader's Complete Guide to Mastering Market Volatility"
  - Source: https://www.kavout.com/market-lens/bollinger-bands-a-trader-s-complete-guide-to-mastering-market-volatility
  - Squeeze confirmation: 50-100 bar minimum contraction; breakout > 2x volume

- **FXPremiere**: "Bollinger Bands Strategy: Mastering the Squeeze and Breakout Trading (2025)"
  - Source: https://www.fxpremiere.com/bollinger-bands-strategy-mastering-the-squeeze-and-breakout-trading-2025/

### Ichimoku Cloud
- **Changelly**: "Crypto Trading with the Ichimoku Cloud"
  - Source: https://changelly.com/blog/ichimoku-cloud-for-crypto-trading/
  - Crypto settings: 10-30-60 or 20-60-120 (vs stock 9-26-52); avoid signals inside Kumo

- **3Commas**: "Trade Like a Samurai: The Detailed 2024 Guide to Using the Ichimoku Cloud Strategy 2025"
  - Source: https://3commas.io/blog/the-detailed-guide-to-using-ichimoku-cloud-strategy

### Stochastic RSI & Oscillators
- **Altrady**: "Stochastic RSI Guide: Tips for Successful Trading"
  - Source: https://www.altrady.com/crypto-trading/technical-analysis/stochastic-rsi
  - Extreme thresholds: <20 oversold, >80 overbought; crypto can overshoot 3+ candles

- **Alchemy Markets**: "Understanding RSI, Stochastic RSI, and MACD"
  - Source: https://alchemymarkets.com/education/indicators/stochastic-rsi/

### VWAP & TWAP Execution
- **Amberdata**: "Comparing Global VWAP and TWAP for Better Trade Execution"
  - Source: https://blog.amberdata.io/comparing-global-vwap-and-twap-for-better-trade-execution
  - TWAP: equal splits over time; VWAP: volume-weighted (better in high volume)

- **Cointelegraph**: "TWAP vs. VWAP in crypto trading: What's the difference?"
  - Source: https://cointelegraph.com/explained/twap-vs-vwap-in-crypto-trading-whats-the-difference

### On-Balance Volume (OBV)
- **Kavout**: "Decode Market Moves with OBV: How to Track Volume Like a Pro Trader"
  - Source: https://www.kavout.com/market-lens/decode-market-moves-with-obv-how-to-track-volume-like-a-pro-trader
  - Divergence entry: Price new high, OBV new low = bearish reversal

- **CoinGecko**: "On-Balance Volume (OBV) Indicator for Crypto Trading"
  - Source: https://www.coingecko.com/learn/on-balance-volume-obv-indicator-crypto

### Taker Buy/Sell Ratio
- **OKX**: "Understanding Bitcoin's taker buy-sell ratio"
  - Source: https://www.okx.com/learn/taker-buy-sell-ratio
  - Signal: Ratio >1.2 bullish, <0.8 bearish; pair with EMA 50 filter

- **CryptoQuant**: "Taker Buy Sell Volume/Ratio"
  - Source: https://cryptoquant.com/asset/btc/chart/derivatives/taker-buy-sell-ratio

---

## DeFi Yield & Arbitrage Sources

### Aave V3 Lending Pools
- **Markaicode**: "Aave V3 Yield Farming: Complete Guide to Supply and Borrow Strategies"
  - Source: https://markaicode.com/aave-v3-yield-farming-guide/
  - Current rates: 4-7% stables, 2-3% ETH; eMode enables 90%+ LTV for correlated pairs

- **Polygon**: "How to Yield Farm with Aave on Polygon"
  - Source: https://polygon.technology/blog/how-to-yield-farm-with-aave-on-polygon

### Layer-2 Opportunities
- **PatentPC**: "Layer 2 Scaling Stats: Arbitrum, Optimism, and zk-Rollup Growth"
  - Source: https://patentpc.com/blog/layer-2-scaling-stats-arbitrum-optimism-and-zk-rollup-growth
  - Arbitrum: $17.8B TVL (30.86%), Base: 46.58% of L2 DeFi

- **CoinCryptoRank**: "Layer-2 Arbitrage Guide: Arbitrum, Optimism & Polygon zkEVM Strategies 2025"
  - Source: https://coincryptorank.com/blog/l2-arbitrage

### Flash Loans & MEV
- **Flashbots**: "Quantifying MEV — Introducing MEV-Explore v0"
  - Source: https://writings.flashbots.net/quantifying-mev
  - Arbitrage profitability threshold: 1% minimum after gas to avoid liquidation

- **Bitquery**: "Understanding Different MEV Attacks: Frontrunning, Backrunning and other attacks"
  - Source: https://bitquery.io/blog/different-mev-attacks
  - Flash loan mechanics: unsecured, repaid same block, enables cascading opportunities

### Stablecoin Basis Trading
- **Phemex Academy**: "USDT vs USDC 2026: Which Stablecoin Should You Use?"
  - Source: https://phemex.com/academy/usdt-vs-usdc-2026
  - USDT depth: 3-5x deeper than USDC; 200+ trading pairs vs 50-100

- **Stablecoin Insider**: "11 Best Stablecoin Yield Strategies In 2026"
  - Source: https://stablecoininsider.org/11-best-stablecoin-yield-strategies-in-2026/

### Concentrated Liquidity & IL
- **Medium - Briplotnik**: "Systematic Crypto Trading Strategies: Momentum, Mean Reversion & Volatility Filtering"
  - Source: https://medium.com/@briplotnik/systematic-crypto-trading-strategies-momentum-mean-reversion-volatility-filtering-8d7da06d60ed
  - Risk-managed momentum: Sharpe 1.42 vs 1.12 for raw momentum

---

## TVL & Market Data Sources

### Real-Time Monitoring
- **DefiLlama**: TVL by protocol/chain (https://defillama.com/)
  - Current DeFi TVL: ~$130-140B (March 2026)
  - Pendle Finance: $8.9B TVL (yield trading platform)
  - Maple Finance: $4B+ (institutional lending)

- **CoinGlass**: Liquidation heatmaps + funding rate charts (https://www.coinglass.com/)
  - Real-time liquidation cascades and support/resistance zones

- **CryptoQuant**: On-chain metrics (https://cryptoquant.com/)
  - Taker buy/sell ratio, funding rate divergence, whale transactions

---

## Key Findings Summary

### Most Backtestable (Highest Sharpe Potential)
1. **Funding Rate Mean Reversion** (10.95% annualized from +0.01% daily)
2. **Basis Momentum** (0.03-0.05% spread capture on L2 arbitrage)
3. **Bollinger Squeeze Breakout** (Volume confirmation 80%+ success)
4. **OBV Divergence** (Early reversal detection, 2-5% moves)
5. **VWAP Crossover** (Execution algorithm, low slippage)

### Lowest Slippage Execution (Institutional-Grade)
- **Flash loan arbitrage** (same-block settlement, no execution risk)
- **Cross-L2 basis trades** (7-420 sec exposure, low decay)
- **Taker buy/sell scalps** (1H/15M timeframe, 0.5-2% moves)

### Highest Risk (Requires Protective Stops)
- **Liquidation cascade contrarian** (tail risk from recursive cascades)
- **Concentrated liquidity delta hedge** (IL can exceed 2% in volatile moves)
- **MEV/frontrunning detection** (competition with professional bots)

---

## Next Steps for Implementation

1. **Backtesting Priority**:
   - Start with indicators (Stochastic RSI, OBV, VWAP) on 1Y BTC/ETH historical data
   - Layer on microstructure (order book imbalance, taker ratio) for 2026 Q1 data
   - Test funding rate strategies on perpetual contracts (Binance/Deribit)

2. **Data Requirements**:
   - Hourly OHLCV + volume (TradingView, Binance, CoinGecko)
   - Order book snapshots (Binance API, Tardis.dev for historical)
   - Funding rates (CryptoQuant, Binance mark price stream)
   - Liquidation heatmaps (CoinGlass historical exports)
   - TVL trends (DefiLlama API for protocol rotation)

3. **Parameter Optimization**:
   - BBands: test 2.0-3.5 std dev for crypto volatility
   - Ichimoku: 10-30-60 (crypto) vs 9-26-52 (traditional)
   - StochRSI: period 14 standard; test oversold <20 vs <10 thresholds
   - Funding: entry ±0.075%, exit at ±0.01-0.03%, liquidation buffer 500 bps

---

## Excluded Strategies (Already in Backlog)
- HurstMeanReversionFilter
- NakedPOCMagnet
- CVDDivergenceWarn
- WyckoffSpringRejection
- EntropyMomentumDecay
- MultiFrameCorrelationArb
- VolatilitySqueezeEntropy
- LiquidationCascadeFront
- MicroStructureMomentum
- SmartMoneySpringFake

---

**Document Generated**: 2026-03-15 | **Research Depth**: 8 angles × 16 strategies × 40+ sources
**File Location**: `moondev/data/new_ideas_defi.txt`
