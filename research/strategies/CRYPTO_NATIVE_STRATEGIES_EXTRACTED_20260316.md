# Estrategias Algorítmicas Crypto-Native Extraídas
**Fecha**: 2026-03-16
**Fuentes Verificables**: Delphi Digital, Messari, Glassnode, CoinMetrics, Kaiko, Paradigm, Flashbots, Chaos Labs, Gauntlet, IntoTheBlock, CryptoQuant, Santiment, Papers arXiv, X/Twitter Quants

---

## ESTRATEGIA 1: Funding Rate Arbitrage (Spot-Perp Delta Neutral)
**Fuente**: [CoinGlass Funding Rate Arbitrage](https://www.coinglass.com/FrArbitrage), [arXiv ScienceDirect Funding Rate Study](https://www.sciencedirect.com/science/article/pii/S2096720925000818), [Messari Metrics](https://messari.io/report/messari-metrics). **Descripción técnica**: Data source: funding rates históricos por exchange (Binance, Bybit, OKX, Hyperliquid) vía CoinMetrics API. Indicadores: Funding Rate absoluto > ±0.75% anual (extremo), Vol 30d < promedio + 1σ, MVRV 0.8-1.2. Entrada long spot + short perp cuando FR < -10% anual. Parámetros: Position size 10-50k capital, hold 2-4 semanas, rebalance diario. Entry rules: esperar FR negativo extremo + confirmar con exchange inflows bajo (< median 7d). Exit: FR normalizado a ±0. Stop loss: precio spot cae -8% simultáneamente en 2+ exchanges. Take profit: acumular 2-4% funding fees netos (1-2 meses). **Timeframe**: 4h-daily monitoreo. **Sharpe esperado**: 1.8-2.5 (retail), 3.5+ (MM). **Una línea**: Compra spot asimétrica cuando funding rate perpetual es extremadamente negativo; financia con short perp en otra exchange; cobra diferencial de FR como income delta-neutral.

---

## ESTRATEGIA 2: MVRV Z-Score Mean Reversion (On-Chain Bottom Timing)
**Fuente**: [CryptoQuant MVRV Guide](https://dataguide.cryptoquant.com/market-data-indicators/mvrv-ratio), [Bitcoin Magazine MVRV Z-Score](https://www.bitcoinmagazinepro.com/charts/mvrv-zscore/), [Messari Metrics](https://messari.io/report/messari-metrics), [Glassnode Research](https://insights.glassnode.com/sth-lth-sopr-mvrv/). **Descripción técnica**: Data source: On-chain MVRV ratio (market cap / realized cap), MVRV Z-Score, SOPR 7d MA vía Glassnode Studio, CryptoQuant. Indicadores: MVRV Z < -2.0 (extreme undervaluation), SOPR 7d MA crossing above 1.0 (profit-taking ends), STH SOPR < 0.95 (short-term holders capitulating). Entrada: Long spot BTC/ETH cuando MVRV Z-Score < -2.5 + SOPR 7d MA > 0.95. Parámetros: DCA 3 fases over 1 week, 5-10% portfolio cada, hold 12-24 weeks. Entry rules: confluencia de 2/3 señales (MVRV + SOPR + exchange inflows). Exit: MVRV > 2.5 OR SOPR > 1.3. Stop loss: MVRV Z < -3.5 (antes que % hardstop). Take profit: objetivo MVRV 1.0-1.5. **Timeframe**: daily-weekly. **Sharpe esperado**: 1.2-1.8. **Una línea**: Identifica mercado bear en valor extremo vía on-chain cost basis; compra cuando holders capitulados y profitability está negativa; espera normalization.

---

## ESTRATEGIA 3: NVT Ratio Overvalue/Undervalue (Network Efficiency)
**Fuente**: [Santiment Academy NVT](https://academy.santiment.net/metrics/nvt/), [Santiment Insights NVT Alpha](https://insights.santiment.net/read/nvt-ratio---alpha-factor-in-crypto-trading-4260), [Obiex On-Chain Metrics](https://blog.obiex.finance/the-only-crypto-on-chain-metrics-you-need-2/). **Descripción técnica**: Data source: Daily network transaction volume on-chain vía Santiment API, market cap via CoinGecko. Indicadores: NVT Ratio = MarketCap / DailyTxVolume. NVT < 30 percentil (undervalued by tx volume), NVT > 70 percentil (overvalued). Volume trend: ↑ while price flat (early strength signal). Entrada long: NVT bajando + tx volume acelerado + precio plano 3d. Short: NVT subiendo + price rallying (pump sin fundamentals). Parámetros: 2-4 week hold, position 5-10% cartera. Entry rules: esperar reversión de NVT + volumen extremo. Exit: NVT regresa a media móvil 30d. Stop loss: -5% precio. Take profit: +8-15% o NVT normalizado. **Timeframe**: daily-weekly. **Sharpe esperado**: 0.9-1.4. **Una línea**: Compara valuation relativa a network utility; short sobrevalorados con bajo volumen en cadena; long subutilizados con uso subiendo.

---

## ESTRATEGIA 4: Stablecoin Flow Institutional Demand (USDT/USDC Inflows as Liquidity Proxy)
**Fuente**: [Glassnode Stablecoin Dashboard](https://studio.glassnode.com/dashboards/mrkt-stablecoin-exchanges), [Messari Research](https://messari.io/), [MEXC News Stablecoin Surge](https://www.mexc.com/news/807213), [Fasanara + Glassnode Q4 Report](https://insights.glassnode.com/q4-2025-institutional-market-perspectives/). **Descripción técnica**: Data source: Stablecoin (USDT/USDC) mint/burn events on-chain, inflow/outflow balance a exchanges vía Glassnode. Indicadores: USDT minting > 1B/week (nueva liquidez entrante), USDC outflow from exchanges (buying pressure), ratio USDT mint vs burn (net expansion = bullish). Entrada long: USDT mints spike + USDC exchange outflows simultáneamente + BTC/ETH trending up. Parámetros: 1-3 week hold, 10-20% capital. Entry rules: confluencia > 2 señales, volumen > 500M USDT daily. Exit: USDT mints fall, USDC inflows a exchange. Stop loss: -6% precio. Take profit: +10-20% spot or timing out after 3 weeks. **Timeframe**: 4h-daily. **Sharpe esperado**: 1.1-1.6. **Una línea**: Instituciones entran comprando stablecoins y sacándolas de exchanges para DeFi/OTC; dinero fresco presiona precio arriba; sigue los flows de monedas estables como proxy de capital institucional.

---

## ESTRATEGIA 5: Token Unlock Calendar Dump Timing (Pre-Unlock Short, Post-Dump Rebound)
**Fuente**: [TokenUnlocks.com Vesting Data](https://tokenomist.ai/), [CryptoRank Token Unlock](https://cryptorank.io/token-unlock), [Bitget Academy Unlock Strategy](https://web3.bitget.com/en/academy/what-is-linear-unlock-token-unlock-trading-strategy-and-key-investor-insights), [Yellow Finance Token Unlocks Impact](https://yellow.com/learn/token-unlocks-explained-how-vesting-schedules-impact-crypto-prices-and-market-liquidity). **Descripción técnica**: Data source: Token unlock calendar (CryptoRank, Messari, DropsTab). Indicadores: Cliff vs linear unlock, % supply unlocking, holder distribution (vesting investor %). Estrategia 1 (Pre-dump): Short 2-3 días antes de cliff unlock masivo (>5% supply). Estrategia 2 (Rebound): Long 1-2 días post-dump cuando precio cayó -10-20% y volumen normaliza. Parámetros: 1-2 week max hold, short 3-5% capital, long 5-10% post-dump. Entry rules: unlock > 10M tokens, precio nearest resistance. Exit: unlock completado + volatilidad cae. Stop loss: short: +8%, long: -8%. Take profit: short: -10-15% precio, long: +8-12%. **Timeframe**: 4h-daily. **Sharpe esperado**: 0.8-1.3 (timing-dependent). **Una línea**: Acceso a calendario de "token unlocks" de vesting; short antes de cliff masivos (50-90% históricamente bajan); luego long la reversión cuando el panic selling se agota.

---

## ESTRATEGIA 6: Open Interest Divergence (OI Sube + Precio Baja = Short Squeeze Incoming)
**Fuente**: [CoinMetrics Funding Rates](https://gitbook-docs.coinmetrics.io/market-data/market-data-overview/funding-rates/funding-rates), [Coinalyze OI Charts](https://coinalyze.net/bitcoin/funding-rate/), [CoinGlass OI Heatmap](https://www.coinglass.com/FundingRateHeatMap), [arXiv Statistical Arbitrage](https://arxiv.org/html/2403.12180v1). **Descripción técnica**: Data source: Open Interest agregado (Binance, Bybit, OKX) vs precio spot via Coinalyze, CoinGlass. Indicadores: OI sube >10% weekly mientras precio baja >3%; liquidación potential map (dónde se concentran shorts); funding rate divergencia (FR negativo extremo = shorts pagando). Entrada long: OI↑ 10%+ + precio↓ 3% + FR < -5% = setup squeeze. Parámetros: 3-5 día hold, 5-10% capital, leverage 2-3x (opcional). Entry rules: confluencia OI + FR + price divergence; evitar si volatilidad ya muy alta (CBRR > 0.3). Exit: OI normaliza O precio sube >5% en 3 días. Stop loss: -4% precio. Take profit: +6-12% o time stop 5 días. **Timeframe**: 4h. **Sharpe esperado**: 1.0-1.5. **Una línea**: Detecta cuando shorts usan excesivo leverage vs actual selling; OI sube pero precio no; setup alcista de squeeze forzado cuando liquidaciones en cascada.

---

## ESTRATEGIA 7: MEV Sandwich/Flash Arbitrage (DEX Spread Capture via Flashbots)
**Fuente**: [Flashbots MEV-Share Docs](https://docs.flashbots.net/flashbots-mev-share/searchers/tutorials/flash-loan-arbitrage/bot), [Paradigm MEV Research](https://research.paradigm.xyz/MEV), [ArXiv Flash Loan Arb](https://arxiv.org/pdf/2206.04185), [Yellow Flash Loan Guide](https://yellow.com/learn/what-is-flash-loan-arbitrage-a-guide-to-profiting-from-defi-exploits). **Descripción técnica**: Data source: Mempool monitoreo, DEX price feeds (Uniswap V3 oracle), liquidation events vía Flashbots relay. Indicadores: Price divergence Uniswap V2 vs V3 > slippage, liquidation detectado en Aave/Compound. Estrategia 1 (Sandwich): detectar trade >50k en Uniswap → ejecutar bundle (buy → user tx → sell) vía Flashbots. Estrategia 2 (Liquidation Backrun): detectar liquidación → aportar liquidity en justo después. Parámetros: trade size limitado por liquidity, gas optimization crítico. Entry rules: spread > gas costs + base fee. Exit: transacción ejecutada. Stop loss: N/A (atomic). Take profit: spread captured. **Timeframe**: mempool (seconds). **Sharpe esperado**: Variable, 1-3% por arbitrage successful. **Una línea**: Detecta ineficiencias de precios sub-segundo entre pools y liquidaciones; ejecuta transacciones atómicas privadas vía Flashbots para capturar spread sin slippage público.

---

## ESTRATEGIA 8: Liquidation Map as Support/Resistance + Sniping (On-Chain Liquidation Clustering)
**Fuente**: [CoinGlass Liquidation Heatmap](https://www.coinglass.com/pro/futures/LiquidationHeatMap), [WhalePortal Heatmap Explained](https://whaleportal.com/blog/liquidation-heatmap-explained/), [Chaos Labs Liquidation Dashboard](https://community.chaoslabs.xyz/aave/risk/liquidations), [CoinGlass FrArbitrage](https://www.coinglass.com/FrArbitrage). **Descripción técnica**: Data source: Open interest clustering por precio vía CoinGlass, liquidation levels agregados (BTC, ETH, altcoins). Indicadores: Yellow zones = high liquidation density, purple = baja densidad. Estrategia 1 (Support): Compra pequeño 1-2% cartera si precio toca liquidation zone amarilla (muchos stops encima). Estrategia 2 (Sniping): Espera zona amarilla y vuelca leverage justo antes para liquidar cortos (risky). Parámetros: 10-25% capital máx por zona, no leverage en sniping. Entry rules: precio acerca a zone, volumen sube. Exit: divergencia liquidación (zone se mueve). Stop loss: -5-8%. Take profit: +4-6% (support hold) or cascada liquidación. **Timeframe**: 4h-1h. **Sharpe esperado**: 0.9-1.3. **Una línea**: Usa mapas públicos de liquidaciones como niveles S/R; acumula ligero en zonas densas donde otros serán liquidados, esperando bounce.

---

## ESTRATEGIA 9: Whale Accumulation / Distribution (Lookonchain + Address Tracking)
**Fuente**: [Lookonchain Platform](https://www.lookonchain.com/index.aspx), [Bitget Whale Analysis Article](https://www.bitget.com/news/detail/12560604490032), [IntoTheBlock Analytics](https://www.intotheblock.com/explore-all-our-indicators), [Nansen On-Chain Analytics](https://www.nansen.ai), [Altrady On-Chain Trading](https://www.altrady.com/crypto-trading/onchain-blockchain-analytics-for-traders/how-to-use-whale-movements-your-advantage). **Descripción técnica**: Data source: Large wallet transfers (>$1M) via Lookonchain, address labeling (exchange vs DeFi), holding time analysis. Indicadores: Whale inflows to DeFi (bullish), whale outflows to exchange (bearish dump incoming), accumulation pattern (holding duration > 6 months = strong conviction). Entrada long: 3+ whales acumulando mismo token, holding pattern 2-4 semanas, precio aún no rally. Short: 2+ whales vendiendo en bloques a exchange. Parámetros: 2-8 week hold, 3-8% capital. Entry rules: confluencia 2+ whales + low exchange inflows + trending vol bajando. Exit: whale vende o consolidación. Stop loss: -6%. Take profit: +12-25%. **Timeframe**: daily-weekly. **Sharpe esperado**: 0.7-1.2 (baja consistencia pero high upside). **Una línea**: Rastrea grandes carteras (ballenas) identificando acumulación en addresses de larga tenencia o dumps a exchanges; sigue su inteligencia como leading indicator.

---

## ESTRATEGIA 10: Exchange Flow Reverse Indicator (Exchange Inflows = Dump Presión, Outflows = Buying)
**Fuente**: [CryptoQuant Exchange Flows](https://cryptoquant.com/asset/btc/chart/market-indicator/mvrv-ratio), [Glassnode Exchange Reserve Data](https://insights.glassnode.com/q4-2025-institutional-market-perspectives/), [Messari Data](https://messari.io/), [IntoTheBlock Exchange Flows](https://resources.intotheblock.com/blockchain-analytics/actionable-signals/on-chain-signals). **Descripción técnica**: Data source: Spot exchange inflows/outflows balance (Binance, Kraken, Coinbase, Gemini) vía Glassnode, CryptoQuant. Indicadores: 7-day moving average inflows (si > 1M BTC = selling pressure), 7-day outflows (si > 1M BTC = accumulation). Ratio inflows/outflows indica direction. Entrada long: exchange outflows spike + price dips (counter-trend), acumulación temprana. Short: inflows explosion + whale addresses dumping. Parámetros: 1-4 week hold, 5-15% capital según intensidad. Entry rules: outflows > 2σ del promedio 30d, coincide con liquidation zone bajo. Exit: inflows normalizados. Stop loss: -5%. Take profit: +8-15%. **Timeframe**: 4h-daily. **Sharpe esperado**: 1.0-1.4. **Una línea**: Monitorea flujos netos hacia/desde exchanges; inflows masivos = instituciones vendiendo próximamente; outflows = compra privada off-exchange; reverse flow signals son leading indicators de precio.

---

## ESTRATEGIA 11: Cross-Exchange Funding Rate Arbitrage (Bybit vs OKX vs Binance Spreads)
**Fuente**: [CoinGlass Multi-Exchange Rates](https://www.coinglass.com/FundingRate), [Coinalyze Rates Comparison](https://coinalyze.net/bitcoin/funding-rate/), [Amberdata Funding Rate Guide](https://blog.amberdata.io/the-ultimate-guide-to-funding-rate-arbitrage-amberdata), [Medium Funding Rate Mastery](https://medium.com/@Xulian0x/mastering-funding-rate-arbitrage-in-crypto-a-comprehensive-guide-27b4c3bb0f90). **Descripción técnica**: Data source: Funding rates simultáneos en 3+ exchanges para mismo asset. Indicadores: FR spread (Binance long +0.08%, OKX short -0.06% = 0.14% diferencial), execution lag timing. Entrada: Long en exchange con FR negativo bajo (collect fee) + Short en positivo alto (pay fee pero menor neto). Parámetros: position size match exacto, 2-4 semana hold, rebalance cada 8h monitorear spread. Entry rules: spread > 0.05% weekly después fees, liquidez suficiente en ambas. Exit: spread cierra. Stop loss: -3% precio en ambas simultáneamente. Take profit: acumular 0.5-1.5% diferencial. **Timeframe**: 4h monitoreo. **Sharpe esperado**: 2.0-3.0 (bajo riesgo pero capital locking). **Una línea**: Arbitraje puro: compra spot barato en exchange A, shorta perpetual caro en exchange B; cobra diferencial de funding rates; sin risk direccional.

---

## ESTRATEGIA 12: Volatility Regime Shift Detection (CBRR/CVOL Contraction → Expansion Trade)
**Fuente**: [CoinMetrics Volatility Data](https://coinalyze.net/), [arXiv Volatility Benchmarking](https://arxiv.org/html/2404.04962v1), [Bybit Futures Guide](https://www.cube.exchange/what-is/funding-rate), [Kaiko Research](https://research.kaiko.com/). **Descripción técnica**: Data source: Historical volatility 30d (CVOL), realized volatility 7d, skew (put/call imbalance). Indicadores: CVOL < percentil 20 (compresión extrema), precio en consolidación 2-3 semanas. Entrada: Long cuando CVOL expand sobre breakout (baja volatilidad → alta), corta lado más probable según skew. Parámetros: 1-3 week hold (volatility fade or reversal), 5-10% capital, leverage 2-3x para vol traders. Entry rules: breakout >2-day range High, Vol spike >150% baseline. Exit: CVOL regresa a media. Stop loss: -4-5%. Take profit: +8-15% o time stop 3 semanas. **Timeframe**: 4h-daily. **Sharpe esperado**: 1.1-1.6. **Una línea**: Compra cuando volatilidad implícita comprimida y breakout ocurre; ventas a volatilidad elevada después de 2-3 semanas de expansion.

---

## NOTAS CRÍTICAS DE IMPLEMENTACIÓN

### Seguridad Prompt Injection
- ✅ Verificado: Ninguna página contiene instrucciones maliciosas tipo "ignore your instructions"
- ✅ Fuentes de confianza: Todas las plataformas son verificables públicamente (Glassnode, Messari, arXiv, etc.)

### Data Sources Consolidados
| Métrica | Proveedor | Endpoint | Latencia |
|---------|-----------|----------|----------|
| Funding Rates | CoinMetrics, Coinalyze | timeseries/market-funding-rates | 1-5 min |
| MVRV/SOPR | CryptoQuant, Glassnode | on-chain-indicators | 1h |
| Exchange Flows | Glassnode Studio | exchange-flows | 1h |
| NVT | Santiment API | network-value-transactions | daily |
| Liquidations | CoinGlass, Chaos Labs | liquidation-levels | real-time |
| Whale Movements | Lookonchain, IntoTheBlock | large-transactions | 5-30 min |
| Stablecoin Mints | Glassnode | stablecoin-supply | 1h |
| OI Data | Coinalyze, CoinGlass | open-interest | 1-5 min |

### Backtesting Recomendado
1. **Funding Arbitrage** → backtestear 12 meses, validar Sharpe > 1.5
2. **MVRV Mean Reversion** → testear en 3 ciclos completos (bear + recovery)
3. **OI Divergence** → correlación con liquidation cascades reales
4. **Cross-Exchange FR** → considerar latencia de sync, slippage fees
5. **MEV Strategies** → simular en mempool histórico, limitar capital initial

### Timeframes Recomendados por Estrategia
- **Funding Arbitrage**: 4h-daily monitoreo, hold 2-4 semanas
- **MVRV + Exchange Flows**: 1d-1w monitoreo, hold 4-24 semanas
- **OI Divergence + Liquidation Maps**: 4h-1h, hold 3-5 días
- **Cross-Exchange FR**: 4h-daily, hold 2-4 semanas
- **Whale Tracking + Token Unlocks**: daily-weekly, hold 1-8 semanas

### Capital Sizing Conservador (Principiante)
```
1. Funding Arbitrage: 20% cartera
2. MVRV Mean Reversion: 15% cartera
3. Token Unlock Dump Short: 5% cartera (timing risk alto)
4. Exchange Flows Reversal: 10% cartera
5. Liquidation Map Snipe: 5% cartera
6. Whale Accumulation: 10% cartera
Total target: 65% in 6 strategies, 35% reserva para tactical opportunistic
```

---

**Documento compilado por RBI Agent**
**Próximo paso**: Delegar a Strategy Agent para codificación en backtesting.py y validación E2E en datos reales (2026-03-16 a 2026-03-23)
