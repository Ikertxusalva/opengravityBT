# TABLA COMPARATIVA: 15 Estrategias Hedge Fund

## Resumen Rápido

| # | Nombre | Tipo | Sharpe | Drawdown | Win% | Complejidad | Crypto-Ready | Fuente |
|----|--------|------|--------|----------|------|------------|-------------|--------|
| 1 | Time Series Momentum | Trend | 1.31 | -33.9% | 48% | ⭐ | ✓ | AQR 2012 |
| 2 | Volatility Targeting | Risk Mgmt | +30% | -20% | N/A | ⭐ | ✓ | Man Group |
| 3 | KAMA Breakout | Trend | 1.0-1.5 | -20% | 45-55% | ⭐ | ✓ | Kaufman 2024 |
| 4 | Carry Strategy | Yield | 0.8-1.2 | -15% | 65%+ | ⭐ | ✓✓ | Quantpedia |
| 5 | Vol Term Structure | Arbitrage | 1.5-2.5 | -10% | 50-60% | ⭐⭐ | ✓ | CTA Research |
| 6 | Cross-Sec Momentum | Long/Short | 1.0-1.5 | -40% | 48% | ⭐⭐ | ✓ | Academia |
| 7 | Risk Parity | Allocation | 0.8-1.2 | -25% | N/A | ⭐ | ✓ | Institutional |
| 8 | Cointegration Pairs | Market-Neutral | 1.0-1.5 | -15% | 55-65% | ⭐⭐ | ✓ | Academic |
| 9 | Mean Reversion OU | Pairs | 0.8-1.2 | -20% | 55-65% | ⭐⭐⭐ | ✓ | ArbitrageLib |
| 10 | ML Hybrid (Sentiment) | Multi-Signal | 1.2-1.8 | -20% | 52-58% | ⭐⭐⭐⭐ | ✓ | arXiv 2025 |
| 11 | Regime-Adaptive | Blended | 1.5-2.0 | -18% | 50-55% | ⭐⭐⭐ | ✓ | Academic 2024 |
| 12 | Tail Risk Hedging | Protection | -0.1 | +300% | 5% | ⭐⭐⭐ | ✓ | Institutional |
| 13 | Fama-French Factors | Multi-Factor | 1.0-1.8 | -30% | 48% | ⭐⭐ | ✓ | CF Benchmarks |
| 14 | Stat Arb Multi-Pair | Arbitrage | 1.2-1.5 | -20% | 58-65% | ⭐⭐⭐ | ✓ | SSRN 2024 |
| 15 | ATR Dynamic Breakout | Breakout | 0.9-1.3 | -25% | 40-50% | ⭐ | ✓ | Trading Systems |

---

## Detalles por Categoría

### 🔴 TIER 1: Implementar Primero (Máxima Prioridad)

#### Time Series Momentum (TSMOM)
```
Indicador Principal:    12-month excess return
Entry Long:            Retorno 12m > 0
Entry Short:           Retorno 12m < 0
Position Sizing:       Inverso a volatilidad
Rebalancing:           Mensual
Performance:           Sharpe 1.31 | Alpha 20.7% | DD -33.87%
Volatility:            15.74%
Período Validación:    1965-2009 (44 años)
Crypto Adaptable:      SÍ (BTC, ETH, índices)
```

#### Volatility Targeting
```
Mecanismo:             Leverage = Target Vol / Actual Vol
Frecuencia:            Semanal
Target Vol:            8-12% annualized
Max Leverage:          2.0x
Look-back:             20/60/120 días
Sharpe Improvement:    +10-30%
Drawdown Reduction:    -20-40%
Uso Principal:         Capa de risk management
Crypto Adaptable:      SÍ (universal)
```

#### Adaptive Moving Average (KAMA)
```
Indicador:             Kaufman Adaptive MA
Parámetros Fast:       KAMA(10, 2, 30)
Parámetros Slow:       KAMA(10, 5, 30)
Entry Long:            Price > Slow KAMA + Fast > Slow
Entry Short:           Opuesto
Stop Loss:             1.5x ATR(14)
Take Profit:           2-3x ATR(14)
Timeframe:             1H - 4H - 1D
Win Rate:              45-55%
Sharpe:                1.0-1.5
Crypto:                ✓ (BTC, ETH, alts)
```

#### Carry Strategy (Staking/Lending)
```
Universo:              Top cryptos by yield
APY Target:            5-15% annualized
Entry Long:            Top 3 by APY
Entry Short:           Bottom 3 (o neutral)
Position Sizing:       Equal-weight
Rebalancing:           Mensual
Volatility:            BAJA (si assets correlados)
Riesgo Principal:      Counterparty failure
Crypto Specific:       ✓✓ (ETH staking, DeFi)
Sharpe:                0.8-1.2
```

---

### 🟡 TIER 2: Balance Risk/Reward

#### Volatility Term Structure Arbitrage
```
Asset:                 VIX futures (crypto: IV term structure)
Estrategia:            Exploit contango/backwardation
Contango:              Sell near, buy long
Backdownation:         Opuesto
Rebalancing:           Monthly roll
Holding Period:        5-20 días
Sharpe:                1.5-2.5
Target Return:         5-15% annualized
Execution Risk:        Alta (costs críticos)
Crypto Ready:          ✓ (Deribit options)
```

#### Cross-Sectional Momentum
```
Universo:              Top 500 cryptos
Ranking Metric:        3/6/12-month returns
Entry Long:            Top decile (10%)
Entry Short:           Bottom decile (10%)
Rebalancing:           Mensual
Min Market Cap:        $100M-$1B
Sharpe:                1.0-1.5
Max Drawdown:          -30% to -50%
Win Rate:              ~48%
Crypto Warning:        Reversión más rápida que stocks
```

#### Risk Parity
```
Principio:             Equal risk contribution
Asignación:            Inverse to volatility
Ejemplo 4-asset:       BTC 40% | ETH 28% | SOL 20% | Stable 12%
Fórmula:               Weight = (1/σᵢ) / Σ(1/σⱼ)
Rebalancing:           Trimestral o ±10% deviation
Holding:               Strategic allocation (long-term)
Sharpe:                0.8-1.2
Max Drawdown:          -20% to -30%
Consistencia:          Alto across cycles
Hierarchical:          ✓ (better for crypto)
```

#### Cointegration Pairs Trading
```
Test:                  Johansen (p-value < 0.05)
Spread Formula:        log(P_A) - β×log(P_B)
Signal Metric:         Z-score of spread
Entry Long:            Z-score > 2 (oversold)
Entry Short:           Z-score < -2 (overbought)
Exit:                  Z-score = 0 (mean reversion)
Hard Stop:             Z-score > ±3.0
Win Rate:              55-65%
Sharpe:                1.0-1.5
Market Neutral:        SÍ
Caveat:                Breaks during crashes
```

---

### 🟣 TIER 3: Complejos (High Skill)

#### Mean Reversion Ornstein-Uhlenbeck
```
Modelo:                OU process
Parámetros OU:         θ (mean), μ (speed), σ (vol)
Half-Life:             5-60 días (optimal)
Pairs Típicas:         ETH/BTC, SOL/FTT, etc.
Lookback:              120 días rolling
Entry Threshold:       Z-score > 2σ
Exit Threshold:        Z-score = 0
Confidence:            Rolling cointegration test
Sharpe:                0.8-1.2
Complejidad:           Alta (estimación parámetros)
```

#### Machine Learning Hybrid
```
Modelo Base:           LightGBM + LSTM
Features (30+):        Technical | Sentiment | On-chain
Technical:             SMA, EMA, RSI, BB, ATR, MACD
Sentiment:             Twitter volume, Fear&Greed, Reddit NLP
On-chain:              Whale flows, Exchange inflows, SOPR
Training Data:         3-5 años (walk-forward)
Entry:                 Probability > 0.65
Exit:                  Probability < 0.35
Sharpe:                1.2-1.8
Max Drawdown:          -20%
Accuracy Target:       52-58%
Warning:               Overfitting risk (need validation)
Crypto Ready:          ✓ (data available)
```

#### Regime-Adaptive Blending
```
Estados:               3 (Trending | Range-bound | Transition)
Detector:              Random Forest / LSTM
Features:              Vol, autocorr, ADX, skewness
Trending (ADX>25):     Use momentum (KAMA cross)
Range-bound (ADX<20):  Use mean reversion (RSI extremes)
Transition:            50/50 blend
Retraining:            Every 60 periods
SL/TP:                 Dynamic per regime
Sharpe:                1.5-2.0
Win Rate:              50-55%
Advantage:             Adapta a regime breaks
```

#### Tail Risk Hedging
```
Instrumento:           OTM Put options
Strike:                -20% from spot
Cost:                  1-3% annualized
Coverage:              50-90% notional
Rebalancing:           Quarterly rolling
Expected Return:       -1% to -3% (insurance cost)
Crash Payoff:          +100% to +300%
Ejemplo:               Universa 2020: +3,612%
Strategy Type:         Protective
Crypto:                Limited options liquidity (improving)
Alternative:           Perpetual short synth hedge
```

---

### 📊 Matriz de Selección

#### POR OBJETIVO

**Máximo Sharpe (Risk-Adjusted):**
1. Volatility Term Structure Arb (1.5-2.5)
2. Regime-Adaptive (1.5-2.0)
3. ML Hybrid (1.2-1.8)

**Máximo Retorno (Long-term):**
1. Time Series Momentum (20.7% alpha)
2. Cross-Sec Momentum (Tier 2)
3. ML Hybrid (si data quality)

**Mínimo Drawdown:**
1. Volatility Targeting (-20 máx)
2. Risk Parity (-25 máx)
3. Carry Strategy (-15 máx)

**Máxima Consistencia:**
1. Risk Parity (stable across cycles)
2. Volatility Targeting (mathematical floor)
3. Time Series Momentum (long validation)

**Crypto-Específico (Rendimiento Alto):**
1. Carry Strategy (5-15% APY)
2. KAMA Breakout (volatile markets)
3. Cross-Sec Momentum (trending markets)

---

#### POR COMPLEJIDAD TÉCNICA

```
⭐ SIMPLE (Implementar en 1-2 días)
  • Volatility Targeting
  • Risk Parity
  • KAMA Breakout
  • Carry Strategy
  • ATR Dynamic Breakout

⭐⭐ INTERMEDIO (1 semana)
  • Time Series Momentum
  • Vol Term Structure
  • Cross-Sec Momentum
  • Cointegration Pairs
  • Fama-French Factors

⭐⭐⭐ AVANZADO (2+ semanas)
  • Mean Reversion OU
  • Stat Arb Multi-Pair
  • Regime-Adaptive

⭐⭐⭐⭐ EXPERTO (3+ semanas)
  • ML Hybrid (Sentiment)
  • Tail Risk Hedging (si opciones real-time)
```

---

## Recomendación de Combinación (Portfolio de Estrategias)

### OPCIÓN 1: Conservative Growth
```
40% Volatility Targeting (base risk mgmt)
30% Risk Parity (diversificación)
20% Time Series Momentum (alpha)
10% Carry Strategy (yield)
Expected Sharpe: 1.1-1.3
Expected DD: -25%
```

### OPCIÓN 2: Aggressive Alpha
```
30% Time Series Momentum (20.7% alpha)
25% Cross-Sectional Momentum (trending)
20% ML Hybrid Sentiment (if data ready)
15% Volatility Term Structure (arbitrage)
10% Tail Risk Hedge (protection)
Expected Sharpe: 1.4-1.6
Expected DD: -35%
Max Leverage: 2.0x
```

### OPCIÓN 3: Market-Neutral
```
50% Cointegration Pairs (long/short neutral)
30% Stat Arb Multi-Pair
20% Risk Parity (diversification)
Expected Sharpe: 1.2-1.4
Expected DD: -15%
Beta to Market: ~0
```

### OPCIÓN 4: Crypto-Optimized
```
35% Carry Strategy (5-15% APY)
25% KAMA Breakout (1h-4h volatility)
20% Cross-Sec Momentum (alts trending)
15% Risk Parity (BTC/ETH/alts)
5% Tail Risk Hedge (OTM puts)
Expected Sharpe: 1.2-1.5
Expected DD: -25%
```

---

## Próximos Pasos

### FASE 1: Selección (Esta Semana)
- [ ] Elegir 3-5 estrategias para Phase 1
- [ ] Recomendación: TSMOM + Vol Targeting + KAMA
- [ ] Decidir: Solo TIER 1 o mezclar con TIER 2?

### FASE 2: Codificación (2-3 Semanas)
- [ ] Strategy Agent: Implement en backtesting.py
- [ ] Test en 25+ assets
- [ ] Walk-forward validation

### FASE 3: Validation (1-2 Semanas)
- [ ] Backtest Architect: Deep analysis
- [ ] Risk Agent: Evaluate metrics
- [ ] Select top 3-5

### FASE 4: Live (1-2 Semanas)
- [ ] Paper trading
- [ ] Execution slippage check
- [ ] 4 weeks live sim

---

## Quick Reference: Parámetros Iniciales

| Estrategia | Start Here | Optimize After |
|-----------|-----------|----------------|
| TSMOM | 12m lookback, vol target 10% | 6/18m, 8-15% vol |
| Vol Target | 10% target, weekly rebal | 8-15%, daily-weekly |
| KAMA | (10,2,30) slow & (10,5,30) fast | (10,3,30), (20,2,30) |
| Carry | Top/Bottom 3, 5% min APY | Top/Bottom 2-5, 3-8% APY |
| Cointegration | 120d window, z>2 entry | 60/180d, z>1.5-2.5 |
| ML Hybrid | 30 features, 80/20 train/test | Add/remove features |

---

**Last Updated:** March 16, 2026
**Status:** READY FOR IMPLEMENTATION
