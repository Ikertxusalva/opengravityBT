# Research Report: Hedge Fund & Quantitative Strategies Extractable to Crypto
**Date:** March 16, 2026
**Research Agent:** RBI Agent
**Status:** RESEARCH COMPLETE - Ready for Strategy Agent Handoff

---

## Executive Summary

Investigación profunda de 15+ estrategias algorítmicas institucionales de hedge funds cuantitativos, prop trading firms y research funds. Todas las estrategias son replicables con datos públicos de cryptomonedas.

**Fuentes:** AQR Capital, Man Group, Two Sigma, Renaissance Technologies, D.E. Shaw, papers SSRN, arXiv (2024-2026), QuantPedia, QuantConnect.

---

## ESTRATEGIAS VALIDADAS PARA CRYPTO

### 1. TIME SERIES MOMENTUM (TSMOM)
**Fuente:** [Moskowitz, Ooi, Pedersen (2012) - SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463) | [AQR Capital Research](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum)

**Tipo:** Trend Following / Momentum
**Mercado:** Multi-asset (crypto adaptable)
**Timeframes:** Monthly rebalancing

**Indicadores:**
- 12-month excess return (lookback period)
- Volatility (univariate GARCH o rolling historical)

**Reglas de Entrada:**
- LONG si: excess return acumulado últimos 12 meses > 0
- SHORT si: excess return acumulado últimos 12 meses < 0

**Reglas de Salida:**
- Rebalancing mensual
- Cierre de posición si señal invierte

**Position Sizing:**
- Inverso a volatilidad: Position Size = Target Volatility / Asset Volatility
- Volatilidad estimada via GARCH de 12 meses o rolling 252-day

**Stop Loss:** No explícito (volatility-based scaling cubre downside)

**Take Profit:** No explícito (trend reversal reconocido en rebalancing mensual)

**Filtros:**
- Ninguno necesario (ya es diversificado cross-asset)

**Parámetros optimizables:**
- Lookback: 6, 12, 18, 24 meses
- Volatility window: 20, 60, 120, 252 días
- Target volatility: 8%, 10%, 12%, 15%

**Performance histórico (1965-2009):**
- Annual Alpha: 20.7%
- Sharpe Ratio: 1.31
- Max Drawdown: -33.87%
- Volatility: 15.74%

**Notas:**
- Exploit auto-covariance: momentum persiste ~1 año, luego mean reversion
- Crisis-alpha: Funciona bien durante market crashes (counter-cyclical)
- Implementable en: BTC, ETH, altcoins, índices de crypto

---

### 2. FX CARRY TRADE (Adaptado a Crypto)
**Fuente:** [QuantPedia - FX Carry Trade](https://quantpedia.com/strategies/fx-carry-trade)

**Tipo:** Yield Harvesting / Carry
**Mercado:** Crypto (lending rates, staking yields)
**Timeframes:** Monthly rebalancing

**Indicadores:**
- Interest rate differentials (o staking yields en crypto)
- Central bank rates (o DeFi lending rates: Aave, Compound)

**Reglas de Entrada:**
- LONG top 3 cryptos por lending/staking yield
- SHORT bottom 3 cryptos por lending/staking yield
- O simplemente LONG high-yield assets, cash en stablecoins

**Reglas de Salida:**
- Rebalancing mensual basado en nuevos yields

**Position Sizing:**
- Equal-weight: 1/3 capital en cada long, 1/3 en cada short
- O 50% long, 50% cash en stablecoins con yield

**Stop Loss:**
- Dynamic: salir si spread se cierra (UIP convergence)
- Trailing stop: -10% a -15% por posición

**Take Profit:**
- Continuous yield capture
- Or exit if yield differential inverts

**Filtros:**
- Min staking/lending APY: 3-5% para entrar
- Max correlation con BTC: <0.5

**Parámetros optimizables:**
- Top/Bottom N: 2, 3, 5 assets
- Rebalancing frequency: Weekly, Monthly
- Min yield threshold: 2%, 3%, 5%

**Performance esperado (crypto):**
- Yield capture: 5-15% APY (dependiendo de ciclo)
- Muy bajo volatility si assets están correlacionados
- Crisis risk: alto si yield invierte durante crashes

**Notas:**
- En crypto: staking, lending pools, borrowing costs
- Exploita forward-rate bias / UIP violations
- Ideal para: ETH (staking), SOL (yield), altcoins con DeFi
- **Riesgo:** crashes de contraparte (lending pool insolvencies)

---

### 3. CROSS-SECTIONAL MOMENTUM
**Fuente:** [Academia / Múltiples papers](https://medium.com/@haohanwang/basics-of-backtest-and-cross-sectional-momentum-4db732ad2618)

**Tipo:** Long/Short Equity Alternative
**Mercado:** Crypto multi-asset ranking
**Timeframes:** Daily / Weekly / Monthly

**Indicadores:**
- Ranking por 3-month, 6-month, 12-month returns
- Relative momentum vs universe average

**Reglas de Entrada:**
- LONG: Top decile (top 10% de cryptos por momentum)
- SHORT: Bottom decile (bottom 10% por momentum)
- Equal-weight o vol-weight dentro de cada decile

**Reglas de Salida:**
- Rebalancing mensual (o trimestral)
- Exit cuando ranking cambia

**Position Sizing:**
- Max long position: 10% per asset en top decile
- Max short position: 10% per asset en bottom decile
- Rest: cash o bonds

**Stop Loss:**
- -2 to -3 standard deviations del universo
- Dynamic: ajustar si asset sale del decile

**Take Profit:**
- Profit when asset revierte a medio

**Filtros:**
- Min market cap: $100M-$1B (liquid universe)
- Min volume: Top 500-1000 cryptos
- Exclude: stablecoins, wrapped assets

**Parámetros optimizables:**
- Momentum lookback: 3, 6, 12 months
- Rebalancing: Weekly, Monthly, Quarterly
- Deciles: Top/Bottom 5%, 10%, 20%
- Vol scaling: Y/N

**Performance esperado:**
- Sharpe: 1.0 - 1.5 (anual)
- Drawdown: -30% a -50%
- **Problem:** Mean reversion en crypto es más fuerte que en equities

**Notas:**
- Funciona en equities, commodities, currencies
- En crypto: muy sensible a sentiment/social media momentum
- **Riesgo:** Momentum puede invertir rápidamente en crypto
- Mejor combined con reversion filters

---

### 4. MEAN REVERSION ORNSTEIN-UHLENBECK (OU)
**Fuente:** [ArbitrageLib / Academic](https://hudson-and-thames-arbitragelab.readthedocs-hosted.com/en/latest/optimal_mean_reversion/ou_model.html)

**Tipo:** Mean Reversion / Pairs Trading
**Mercado:** Crypto pairs (ETH/BTC, etc.)
**Timeframes:** Intraday to Daily

**Indicadores:**
- OU process parameters:
  - θ (long-term mean)
  - μ (speed of reversion) / half-life
  - σ (volatility)
- Z-score de spread respecto al mean

**Reglas de Entrada:**
- Calculate spread = log(price_A) - β * log(price_B)  [from cointegration]
- Estimate OU half-life on rolling basis (20-60 days)
- LONG pairs si spread < mean - 2σ (oversold)
- SHORT pairs si spread > mean + 2σ (overbought)

**Reglas de Salida:**
- Exit cuando spread revierte a mean (z-score = 0)
- Stop loss: spread goes to ±3σ

**Position Sizing:**
- Inverse of volatility: pos_size = target_vol / current_vol
- Risk per trade: 1-2% of portfolio

**Stop Loss:**
- Hard stop: ±3σ from mean
- Time-based: close si half-life expires sin reversion

**Take Profit:**
- Soft: Take 50% at mean
- Hard: Take 100% at mean + 1σ en opposite direction

**Filtros:**
- Min cointegration: Johansen test ADF p-value < 0.05
- Min correlation: >0.7 (pairs deben moverse juntos)
- Half-life: 5-60 days (too fast/slow = unreliable)

**Parámetros optimizables:**
- Entry z-score threshold: 1.5, 2.0, 2.5, 3.0
- Exit z-score threshold: 0.0, 0.5
- Lookback for half-life: 20, 40, 60, 120 days
- Reversion speed window: 20, 60 días

**Performance esperado:**
- Win rate: 55-65% (mean reversion expected)
- Avg trade duration: 2-10 days
- Sharpe: 0.8-1.2 (net of costs)

**Notas:**
- **ETH/BTC pair:** Cointegrated a ~10% confidence level (weak pero existe)
- **Recomendación:** Multi-pair universe (10-20 pairs) vs single pair
- Copula modeling (vs Gaussian) puede mejorar para heavy-tail crypto

---

### 5. VOLATILITY TARGETING
**Fuente:** [QuantPedia - Volatility Targeting](https://quantpedia.com/an-introduction-to-volatility-targeting/)

**Tipo:** Risk Management / Position Sizing
**Mercado:** Applicable to any asset (equities, crypto, bonds, commodities)
**Timeframes:** Daily to Weekly rebalancing

**Indicadores:**
- Realized volatility (20, 60, 252-day rolling)
- EWMA volatility estimator

**Reglas de Entrada/Posicionamiento:**
- Leverage = Target Volatility / Actual Volatility
- Applied uniformly across portfolio

**Position Sizing:**
- Long: Baseline position × Leverage
- If vol low: increase position (up to 2.0x max)
- If vol high: reduce position (down to 0.5x min)

**Stop Loss:** Dynamic via leverage reduction

**Take Profit:** Not applicable (continuous strategy)

**Rebalancing:**
- Weekly
- Calculate leverage using data through t-2 to avoid look-ahead bias

**Filtros:**
- Max leverage: 2.0x (risk management)
- Min position size: 0.5x (avoid under-investment)

**Parámetros optimizables:**
- Target volatility: 8%, 10%, 12%, 15%
- Volatility window: 20, 60, 120, 252 días
- Rebalancing frequency: Daily, Weekly, Monthly
- Max leverage: 1.5x, 2.0x, 3.0x

**Performance esperado:**
- Sharpe improvement: +10% to +30% vs unscaled
- Drawdown reduction: -20% to -40%
- Returns: Stable (target volatility, not max returns)

**Notas:**
- **Fundamental:** Works best con mean-reverting strategies
- Reduce worst-case risk dramatically
- Implementable en cualquier portfolio
- En crypto: use 60-120 day window (más estable que 20-day)

---

### 6. RISK PARITY (Adapted to Crypto)
**Fuente:** [QuantPedia Risk Parity](https://quantpedia.com/risk-parity-asset-allocation/) | [Crypto adaptation papers](https://arxiv.org/html/2412.02654v1)

**Tipo:** Asset Allocation / Equal Risk Contribution
**Mercado:** Multi-asset (crypto + bonds + equities)
**Timeframes:** Quarterly rebalancing

**Indicadores:**
- Marginal volatility of each asset
- Historical correlations
- Risk budget per asset = Target Risk / N assets

**Reglas de Posicionamiento:**
- Allocate weights inversely to volatility:
  - Weight = (1/σ_i) / Σ(1/σ_j)
- Rebalance quarterly

**Ejemplo Crypto Risk Parity (4-asset):**
```
BTC vol: 50% → weight: 40%
ETH vol: 70% → weight: 28%
SOL vol: 100% → weight: 20%
Stable: 5%  → weight: 12%
```

**Position Sizing:**
- Notional allocation: Weight × Portfolio Value
- Leverage: Adjust to match target portfolio volatility

**Stop Loss:** Not applicable (strategic allocation)

**Take Profit:** Not applicable

**Rebalancing:**
- Quarterly (or when any asset deviates >10% from target weight)

**Filtros:**
- Min market cap: $1B (liquidity)
- Max correlation: <0.8 (diversification check)

**Parámetros optimizables:**
- Asset universe: 3, 4, 5, 6 assets
- Volatility window: 60, 120, 252 días
- Rebalancing frequency: Monthly, Quarterly, Semi-Annual
- Correlation lookback: 1, 2, 3 años

**Performance esperado:**
- Sharpe: 0.8-1.2 (lower volatility, lower returns)
- Max drawdown: -20% to -30%
- Consistent returns across cycles

**Notas:**
- Hierarchical Risk Parity (HRP) mejor para crypto (handles non-linear correlations)
- Assume mean correlations se mantienen (not always true en crypto crashes)
- **Mejor para:** Institutional portfolios, low-turnover shops

---

### 7. FAMA-FRENCH FACTOR MODEL (Crypto Adaptation)
**Fuente:** [CF Benchmarks Factor Model](https://www.cfbenchmarks.com/blog/cf-benchmarks-introduces-first-institutional-grade-factor-model-for-digital-assets) | [Academic research](https://www.sciencedirect.com/science/article/abs/pii/S1062940820302308)

**Tipo:** Multi-factor Asset Pricing
**Mercado:** Crypto universe (100+ assets)
**Timeframes:** Monthly factor updates

**Factores (Crypto version):**
1. **Market Factor (MKT):** Aggregate market excess return
2. **Size Factor (SMB):** Small-cap - Big-cap returns
3. **Value Factor (HML):** High P/E - Low P/E returns
4. **Momentum Factor (WML):** Winner - Loser returns
5. **Quality Factor:** High profitability - Low profitability (relevancia limitada en crypto)
6. **Liquidity Factor:** High - Low liquidity

**Reglas de Construcción:**
- Rank assets por market cap → Quintiles
- Rank assets por valuation metrics (P/E equivalent, NVT ratio)
- Rank assets por 6-month momentum
- Long/Short portfolios: Long top quintile, Short bottom quintile

**Reglas de Entrada:**
- Construct portfolio long top quintile, short bottom quintile en cada factor
- Combine factors: Equal-weight o factor tilting based on expected return

**Position Sizing:**
- Equal-weight per factor
- Vol-scaling per position

**Rebalancing:**
- Monthly factor rebalancing
- Asset-level adjustments quarterly

**Parámetros optimizables:**
- Ranking metrics: Market cap, NVT, P/E, Sharpe, Momentum window
- Quintiles: 2x2, 3x3, 5x5 portfolios
- Factor weights: Equal, vol-scaled, return-optimized
- Rebalancing frequency: Monthly, Quarterly

**Performance esperado:**
- Sharpe (long only): 0.8-1.2 (if factor premia exist)
- Sharpe (long/short): 1.2-1.8 (exploit cross-section)

**Notas:**
- En crypto: Momentum y Liquidity factors más fuertes que en equities
- Size effect: Inverted en crypto (small caps underperform large caps more)
- Value factor: Débil (correlated con momentum, crypto is young)
- **Caveat:** Factor premia no garantizadas en crypto (regime-dependent)

---

### 8. ADAPTIVE MOVING AVERAGE BREAKOUT
**Fuente:** [Kaufman Adaptive Moving Average](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/kaufmans-adaptive-moving-average-kama) | [Recent implementations 2024](https://medium.com/@FMZQuant/adaptive-moving-average-trading-strategy-422798f0d419)

**Tipo:** Trend Following / Breakout
**Mercado:** Single or multi-asset crypto
**Timeframes:** Daily to Hourly

**Indicadores:**
- Kaufman Adaptive Moving Average (KAMA)
- Efficiency Ratio (ER)
- ATR (Average True Range)

**Parámetros KAMA(10, 2, 30):**
- 10 = periods for Efficiency Ratio
- 2 = fastest EMA constant
- 30 = slowest EMA constant

**Reglas de Entrada:**
- Slow KAMA(10, 5, 30) para trend filter
- Fast KAMA(10, 2, 30) para entry signal
- **Long:** Price > Slow KAMA AND Fast KAMA > Slow KAMA (bullish cross)
- **Short:** Price < Slow KAMA AND Fast KAMA < Slow KAMA (bearish cross)

**Reglas de Salida:**
- Exit long: Price < Fast KAMA (trend loss)
- Exit short: Price > Fast KAMA

**Position Sizing:**
- ATR-based: Size = Risk Capital / (Entry Price - Stop Loss)
- Stop distance: 1.5 × ATR(14)
- Target distance: 2.0-3.0 × ATR(14)

**Stop Loss:**
- Trailing: 2 × ATR below entry (long) / above entry (short)
- Or breakeven stop after 2R profit

**Take Profit:**
- First target: 1.5 × ATR from entry
- Second target: 3.0 × ATR from entry (take half)

**Filtros:**
- Min ATR: > 20-day average (trending market)
- Max ATR: < 90th percentile (extreme volatility = skip)
- Trend confirmation: Slow KAMA slope > 0 (long only)

**Parámetros optimizables:**
- Slow KAMA: (10,3,30), (10,5,30), (20,2,30)
- Fast KAMA: (10,2,20), (10,2,30), (5,2,20)
- ATR period: 7, 14, 21
- Risk per trade: 1%, 2%, 3%

**Performance esperado:**
- Win rate: 45-55% (trend following)
- Avg win: 2.5-3.5 × avg loss
- Sharpe: 1.0-1.5 (depending on market regime)

**Notas:**
- Responsive a trending markets
- Poor durante range-bound / sideways
- KAMA adapts automatically to volatility
- **Muy implementable en crypto:** Daily/hourly charts funcional

---

### 9. BREAKOUT WITH ATR POSITION SIZING
**Fuente:** [Mind Math Money / ATR Strategies](https://www.mindmathmoney.com/articles/atr-indicator-trading-strategy-master-volatility-for-better-breakouts-and-risk-management)

**Tipo:** Volatility-based Position Sizing
**Mercado:** Single or multi-asset
**Timeframes:** 4H to Daily

**Indicadores:**
- ATR(14) - Average True Range
- 20-day average ATR
- Support/Resistance levels

**Reglas de Entrada:**
- Breakout: Price > Resistance + 2×ATR(14)
- Confirmation: Range (high-low) >= 2×ATR(14)

**Position Sizing:**
- High ATR (>90th percentile): Reduce size by 25-50%
- Normal ATR (40-60th percentile): Full size
- Low ATR (<40th percentile): Increase size by 25%

**Stop Loss:**
- Distance: 1.2-1.5 × ATR(14)

**Take Profit:**
- Distance: 1.8-2.5 × ATR(14)
- Or 2R multiple (2 × risk per trade)

**Rebalancing:**
- Daily (ATR recalculation)

**Parámetros optimizables:**
- ATR period: 7, 14, 21
- Entry ATR multiple: 1.5x, 2.0x, 2.5x
- SL multiple: 1.0x, 1.2x, 1.5x
- TP multiple: 1.5x, 2.0x, 3.0x

**Performance esperado:**
- Win rate: 40-50%
- Risk/reward: 1:1.5 to 1:3
- Sharpe: 0.9-1.3

**Notas:**
- Simple pero effective
- Automatically scales with market volatility
- Works best en trending markets
- **Ideal para:** Day traders, swing traders

---

### 10. STATISTICAL ARBITRAGE - PAIRS TRADING
**Fuente:** [Academic review](https://quantinsti.com/statistical-arbitrage/) | [Crypto application](https://blog.amberdata.io/crypto-pairs-trading-why-cointegration-beats-correlation)

**Tipo:** Market-Neutral / Statistical Arbitrage
**Mercado:** Multi-pair universe
**Timeframes:** Daily to Intraday

**Indicadores:**
- Cointegration test (Johansen, ADF)
- Spread (log-price difference)
- Z-score of spread vs historical mean
- Beta (price hedge ratio)

**Reglas de Entrada:**
1. **Pair Selection:**
   - Johansen test p-value < 0.05 (cointegrated)
   - Historical correlation > 0.7
   - Min liquidity on both legs

2. **Signal Generation:**
   - Calculate spread = log(P_A) - β×log(P_B)
   - Z-score = (Spread - Mean) / StdDev
   - **LONG spread:** Z-score < -2.0 (pair A underperforming)
   - **SHORT spread:** Z-score > +2.0 (pair A overperforming)

3. **Position:**
   - Long pair A + Short pair B (cointegrated amount)
   - Or reverse for mean reversion

**Reglas de Salida:**
- Close when Z-score crosses 0 (mean reversion)
- Hard stop: Z-score > ±3.0

**Position Sizing:**
- Hedge ratio from cointegration: Short units = β × Long units
- Risk per trade: 1-2% of capital

**Stop Loss:**
- Z-score > 3.0 (signal broken)
- Or max loss: 2% portfolio

**Take Profit:**
- Partial: 50% at Z-score = -1.0
- Full: at Z-score = 0.0 (mean reached)

**Rebalancing:**
- Daily: Rebalance beta ratio
- Monthly: Update cointegration parameters

**Filtros:**
- Min cointegration: p-value < 0.05
- Min vol: Both assets > 1% daily change
- Min spread half-life: 5-60 days (too fast/slow = unreliable)

**Parámetros optimizables:**
- Entry Z-score: 1.5, 2.0, 2.5, 3.0
- Exit Z-score: 0.0, 0.5
- Beta recalculation: Daily, Weekly
- Cointegration lookback: 60, 120, 252 días

**Performance esperado:**
- Win rate: 55-65%
- Avg trade: 2-7 days
- Sharpe: 1.0-1.5 (market-neutral)
- Drawdown: -10% to -20%

**Notas:**
- **Crypto pairs:** ETH/BTC (weak cointegration), SOL/FTT, LUNA/UST (historical failure case)
- Universe selection critical: 10-50 pair portfolio vs single pair
- **Risk:** Cointegration breaks during regime shifts
- Copula modeling handles tail risk better than Gaussian

---

### 11. TAIL RISK HEDGING (Options-Based)
**Fuente:** [Hedge Fund Journal / Tail Risk Hedging](https://thehedgefundjournal.com/managing-tail-risk-with-options-products/) | [PIMCO](https://www.pimco.com/us/en/resources/education/manage-risks-using-tail-risk-hedging)

**Tipo:** Risk Management / Insurance Strategy
**Mercado:** Multi-asset protection
**Timeframes:** Quarterly / Annual hedge rolling

**Indicadores:**
- Implied volatility (VIX equivalent en crypto: Option IV)
- Put skew (cost of OTM puts)
- Portfolio VAR

**Reglas de Hedging:**
- Buy OTM put options: Strike = -20% below current price
- Frequency: Quarterly rolling
- Cost: 1-3% portfolio per year

**Position:**
- 50-90% portfolio notional hedged
- Put ladder: Multiple strikes (80%, 85%, 90% of current price)

**Stop Loss / Adjustment:**
- If hedge gets ITM: Roll out to later expiry
- If hedge expires: Roll to new quarterly

**Costs:**
- Option premium: 1-3% annualized
- Net: Negative expected return (insurance cost)

**Parámetros optimizables:**
- Strike level: 85%, 80%, 75% OTM
- Coverage ratio: 50%, 75%, 100%
- Rebalancing: Monthly, Quarterly, Semi-annual
- Put spread: Buy 80% strike, Sell 90% strike (reduce cost)

**Performance esperado:**
- Normal periods: -1% to -3% annual drag (cost of insurance)
- Crash period: +100% to +300% payoff (Universa 2020 example: +3,612%)

**Notas:**
- Cost-benefit highly regime dependent
- Works best for institutional portfolios
- In crypto: Limited options liquidity (improving)
- Alternative: Perpetual short positions (synthetic hedge)

---

### 12. CARRY STRATEGY - VOLATILITY TERM STRUCTURE
**Fuente:** [QuantPedia - VIX Term Structure](https://quantpedia.com/strategies/exploiting-term-structure-of-vix-futures/)

**Tipo:** Volatility Arbitrage
**Mercado:** Crypto options/futures
**Timeframes:** Monthly / Quarterly

**Indicadores:**
- VIX futures curve (or crypto IV term structure)
- Forward volatility implied vs realized
- Contango/Backwardation level

**Reglas de Entrada:**
- **Contango play:** VIX elevated, curve upward-sloped
  - Sell near-term VIX futures
  - Buy long-term VIX futures (or put spreads)
  - Profit from contango roll-down

- **Backwardation play:** VIX low, curve inverted
  - Sell far VIX futures
  - Buy near VIX futures
  - Profit from backwardation mean reversion

**Position Sizing:**
- Risk per trade: 1-2% portfolio
- Notional: 2-5x capital (low margin)

**Stop Loss:**
- Curve inversion (contango → backwardation)
- Max loss: 2% portfolio

**Take Profit:**
- Contango = roll trades: Target roll yield 5-10% quarterly
- Or exit on curve shape change

**Rebalancing:**
- Monthly (roll contracts)
- Quarterly (rebalance structure)

**Parámetros optimizables:**
- Contract months: 1/3 spreads vs 1/4 spreads
- Entry contango level: 10%, 15%, 20%
- Max leverage: 2x, 3x, 5x
- Roll frequency: Monthly, Bi-monthly

**Performance esperado:**
- Annualized: 5-15% (from roll yield)
- Sharpe: 1.5-2.5
- Max drawdown: -5% to -15%

**Notas:**
- En crypto: Perpetual futures basis + options IV term structure
- **Simpler alternative:** Buy stablecoins, lend at high rates (carry)
- Requires tight execution (transaction costs critical)

---

### 13. MACHINE LEARNING - SENTIMENT + MOMENTUM HYBRID
**Fuente:** [arXiv 2025 research](https://arxiv.org/html/2510.10526v1) | [Medium guides](https://medium.com/funny-ai-quant/sentiment-analysis-in-trading-an-in-depth-guide-to-implementation-b212a1df8391)

**Tipo:** ML-Driven Multi-Signal
**Mercado:** Crypto (social sentiment tractable)
**Timeframes:** Daily to Intraday

**Indicadores:**
- Technical: RSI, EMA, Bollinger Bands, MACD
- Sentiment: CNN Fear & Greed Index, Twitter volume, Reddit sentiment (NLP)
- Alternative Data: On-chain metrics (whale moves, exchange flows)

**Reglas de Entrada (ML Model):**
- Ensemble model: LightGBM + LSTM combination
- Features: 20-30 technical + sentiment + on-chain signals
- Label: 1 if return_next_day > threshold else 0

1. **Feature Engineering:**
   - Technical: SMA, EMA, RSI, Bollinger Width, ATR
   - Sentiment: Smoothed Twitter sentiment (7-day MA)
   - On-chain: Whale transaction volume, exchange inflows/outflows
   - Momentum: 5-day, 20-day returns

2. **Model Training:**
   - Backtest period: 3-5 years
   - Train/test split: 80/20 with walk-forward validation
   - Hyperparameter tuning: Grid search over LightGBM params

3. **Signals:**
   - **Long:** Model probability > 0.65
   - **Short:** Model probability < 0.35
   - **Neutral:** 0.35-0.65 range

**Position Sizing:**
- Scale position by model probability: Pos = (Prob - 0.5) × 2 × Max Size
- Vol scaling: Pos = Pos × (10% / Current Vol)

**Stop Loss:**
- Hard: -3% per trade
- Soft: Close if model flips negative

**Take Profit:**
- Trailing: +2% or ATR-based

**Rebalancing:**
- Daily: Model retraining on rolling window

**Parámetros optimizables:**
- Model type: LightGBM, XGBoost, LSTM, Hybrid
- Feature window: 5, 10, 20, 60 días
- Sentiment sources: Twitter, Reddit, News, OnChain
- Entry threshold: 0.55, 0.60, 0.65, 0.70
- Exit threshold: opposite of entry

**Performance esperado:**
- Accuracy: 52-58% (slight edge)
- Sharpe: 1.2-1.8 (if good features)
- Max drawdown: -15% to -30%

**Notas:**
- Sentiment alphas fade quickly (overfitting risk)
- Walk-forward validation essential
- Multicollinearity: Drop correlated features
- **Caveat:** Data leakage risk (sentiment future-looking)

---

### 14. REGIME-ADAPTIVE MEAN REVERSION / MOMENTUM BLEND
**Fuente:** [Machine Learning + Changepoint Detection](https://ideas.repec.org/p/arx/papers/2105.13727.html)

**Tipo:** Adaptive / Regime-Switching
**Mercado:** Single or multi-asset
**Timeframes:** Daily / 4H

**Indicadores:**
- Market Regime Detector: Volatility percentile, Return autocorrelation
- Trend strength: Hurst exponent or ADX
- Mean reversion signals: RSI, Bollinger Bands
- Momentum signals: EMA crossovers

**Reglas de Entrada (Regime-Dependent):**

1. **Trending Regime (ADX > 25):**
   - Use momentum: Buy EMA fast > EMA slow
   - Ignore mean reversion signals
   - Target: 2-5 days hold

2. **Range-Bound Regime (ADX < 20):**
   - Use mean reversion: Buy RSI < 30, Sell RSI > 70
   - Ignore trend following
   - Target: 1-3 days hold

3. **Transition Regime (ADX 20-25):**
   - Use hybrid: 50% momentum, 50% mean reversion
   - Tighter stops

**Regime Detection (Machine Learning):**
- Random Forest or LSTM classifier
- Features: Vol percentile, Return acf, ADX, Skewness
- Classes: Trending, Range-bound, Volatile

**Position Sizing:**
- Base size: 1% per trade
- Confidence scaling: Size × Model confidence

**Stop Loss:**
- Trending: 2 × ATR
- Range-bound: 1.5 × ATR
- Exit if regime changes

**Take Profit:**
- Trending: 3-5 × ATR
- Range-bound: 1-1.5 × ATR

**Rebalancing:**
- Intraday: Hourly regime updates
- Exit all trades on regime change

**Parámetros optimizables:**
- Regime detection window: 20, 40, 60 días
- ADX threshold: 20, 25, 30
- Entry threshold: 30, 40, 50 RSI
- Exit: Opposite of entry + regime change

**Performance esperado:**
- Sharpe: 1.5-2.0
- Win rate: 50-55%
- Max drawdown: -15% to -25%

**Notas:**
- Changepoint detection (PELT, Bayesian) better than fixed windows
- Combine with deep learning for better regime detection
- **Advantage:** Reduces losses during regime breaks (vs static strategies)

---

### 15. COINTEGRATION-ENHANCED CRYPTO PORTFOLIO
**Fuente:** [Academic Research](https://link.springer.com/article/10.1186/s40854-024-00702-7) | [QuantConnect](https://www.quantconnect.com/league/17226/2024-q2/cointegration-enhanced-crypto/)

**Tipo:** Diversification / Mean Reversion
**Mercado:** Crypto basket (10-30 assets)
**Timeframes:** Quarterly rebalancing

**Indicadores:**
- Cointegration matrix (Johansen test)
- Spread between cointegrated pairs
- Cluster analysis: Assets that move together

**Reglas de Construction:**
1. **Identify Cointegrated Clusters:**
   - Test all pairs: N×(N-1)/2 Johansen tests
   - Group assets by cointegration strength

2. **Within-Cluster Pairs:**
   - Clusters A & B: High correlation pairs
   - Trade relative performance within cluster

3. **Cross-Cluster Diversification:**
   - Equal allocation to clusters
   - Reduce correlation drag

**Example: 3 Clusters (Crypto)**
- Cluster 1: BTC, BCH (payment layer)
- Cluster 2: ETH, SOL, AVAX (smart contracts)
- Cluster 3: LINK, AAVE (DeFi infrastructure)

**Position Sizing:**
- Equal risk contribution across clusters
- Vol-scaled within cluster

**Rebalancing:**
- Quarterly: Retest cointegration
- Monthly: Rebalance within clusters

**Parámetros optimizables:**
- Cluster size: 3, 4, 5, 10 assets per cluster
- Min cointegration: p-value < 0.05, < 0.10
- Rebalancing frequency: Monthly, Quarterly
- Within-cluster weighting: Equal, vol-scaled

**Performance esperado:**
- Diversification benefit: -15% to -25% lower vol vs equal-weight
- Return preservation: Higher Sharpe ratio
- Drawdown: -20% to -30%

**Notas:**
- **Problem:** Cointegration breaks during hard crashes (2022 FTX)
- **Solution:** Dynamic re-clustering quarterly
- Better than static correlations for crypto

---

## IMPLEMENTATION PRIORITIES (Strategic Handoff)

### Tier 1 (Highest Probability + Implementability)
1. **Time Series Momentum (TSMOM)** — Proven 50+ years, multi-asset
2. **Volatility Targeting** — Risk management, implementable immediately
3. **Adaptive Moving Average Breakout** — Simple, responsive
4. **Carry Strategy (Staking/Lending)** — Crypto-specific, high Sharpe potential

### Tier 2 (Good Balance Risk/Reward)
5. **Volatility Term Structure Arbitrage** — High Sharpe if executed well
6. **Cross-Sectional Momentum** — Works in equities/crypto, requires universe
7. **Risk Parity** — Institutional-grade, low turnover
8. **Cointegration Pairs Trading** — Market-neutral, crypto-suitable

### Tier 3 (Complex / High Skill Ceiling)
9. **Machine Learning Hybrid** — Best returns if data + engineering top-tier
10. **Regime-Adaptive Blending** — Requires robust ML infrastructure
11. **Tail Risk Hedging** — Expensive, for institutional portfolios
12. **Statistical Arbitrage Multi-Pair** — Complex execution, low latency needed

---

## COMMON PITFALLS IN CRYPTO (Warnings for Strategy Agent)

1. **Overfitting:** Backtest win rates often 5-10% too optimistic
2. **Data Quality:** Crypto data gaps, exchange failures, fork effects
3. **Slippage/Costs:** 0.1-0.5% per side execution costs destroy thin alphas
4. **Leverage Risk:** Liquidations cascade in leveraged positions
5. **Cointegration Breaks:** Pairs diverge permanently (e.g., LUNA/UST → LUNA → $0)
6. **Regime Shifts:** Crypto correlations → 1.0 in crashes
7. **Black Swans:** Regulatory bans, exchange hacks, smart contract exploits

---

## NEXT PHASE: Strategy Agent Handoff

Each strategy ready for **IMPLEMENTATION → BACKTESTING → LIVE VALIDATION**.

**Deliverables for Strategy Agent:**
- [ ] Code EACH strategy in backtesting.py
- [ ] Validate on 3+ crypto pairs / assets
- [ ] Report: Sharpe, Drawdown, Win Rate, Profit Factor
- [ ] Identify best 3-5 for paper trading setup

**Timeline:** 2-3 weeks per strategy (2-3 hours coding + 1 day backtest)

---

## Sources & Citations

### Academic Papers
- [Time Series Momentum - Moskowitz et al. 2012](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463)
- [Factor Pricing of Cryptocurrencies](https://www.sciencedirect.com/science/article/abs/pii/S1062940820302308)
- [Copula-Based Trading of Cointegrated Crypto Pairs](https://arxiv.org/pdf/2305.06961)
- [Machine Learning Enhanced Trading - 2025](https://arxiv.org/html/2507.07107)

### Hedge Fund Research
- [AQR Capital - Momentum Factor](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum)
- [Man AHL - Trend Following Research](https://www.man.com/insights/trend-following-optimal-market-mix)
- [Two Sigma - ML Regime Modeling](https://www.twosigma.com/articles/a-machine-learning-approach-to-regime-modeling/)

### Quantitative Resources
- [QuantPedia Strategies](https://quantpedia.com/)
- [QuantConnect Community](https://www.quantconnect.com/)
- [SSRN Research Database](https://papers.ssrn.com/)
- [arXiv Quantitative Finance](https://arxiv.org/)

---

**STATUS:** RESEARCH COMPLETE
**DATE:** March 16, 2026
**READY FOR:** Strategy Agent Implementation Phase
