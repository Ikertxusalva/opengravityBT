"""
registry.py -- Catalogo centralizado de estrategias y su estado de validacion.
Actualizado por el Backtest Architect tras multi-test de 25 activos.
Incluye estrategias migradas desde RBI-Backtester (2026-03-14).
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import List


class StrategyStatus(Enum):
    GLOBAL = "global"              # Viable multi-asset
    TESTNET_READY = "testnet_ready" # Validada por backtest, lista para testnet (no activa)
    SINGLE_ASSET = "single_asset"  # Solo viable en activos especificos
    LABORATORY = "laboratory"      # Necesita re-diseno
    DEPRECATED = "deprecated"      # Descartada


@dataclass
class StrategyEntry:
    name: str
    module: str           # path relativo al modulo
    class_name: str
    status: StrategyStatus
    viable_assets: List[str] = field(default_factory=list)
    timeframe: str = ""
    notes: str = ""


STRATEGIES: List[StrategyEntry] = [
    # =========================================================================
    # ESTRATEGIAS ORIGINALES DE OPENGRAVITY (moondev/strategies/)
    # =========================================================================

    # -- Produccion limitada (single-asset) --
    StrategyEntry(
        name="VolatilitySqueezeV3MultiAsset",
        module="moondev.strategies.volatility_squeeze_v3",
        class_name="VolatilitySqueezeV3MultiAsset",
        status=StrategyStatus.SINGLE_ASSET,
        viable_assets=["BTC"],
        timeframe="1h",
        notes="Multi-test 25 activos x 3 TFs: 1h BTC PASS (Sharpe 1.45, DD -4.1%, WR 54.8%, 31 trades), SOL PRECAUCION. 4h AVAX +57.9% pero 9 trades. 1d muerta (<3 trades). Solo viable BTC 1h.",
    ),
    StrategyEntry(
        name="VolatilitySqueezeV2",
        module="moondev.strategies.volatility_squeeze_v2",
        class_name="VolatilitySqueezeV2",
        status=StrategyStatus.SINGLE_ASSET,
        viable_assets=["BTC"],
        timeframe="1h",
        notes="Sharpe 2.18 en BTC pero solo 22 trades; high-conviction squeeze",
    ),
    StrategyEntry(
        name="VolatilitySqueeze",
        module="moondev.strategies.volatility_squeeze",
        class_name="VolatilitySqueeze",
        status=StrategyStatus.SINGLE_ASSET,
        viable_assets=["BTC", "AVAX"],
        timeframe="1h",
        notes="PASS en BTC (Sharpe 1.61) y AVAX; 2/24 activos pasan",
    ),
    StrategyEntry(
        name="RSIBand",
        module="moondev.strategies.rsi_band",
        class_name="RSIBand",
        status=StrategyStatus.SINGLE_ASSET,
        viable_assets=["BNB"],
        timeframe="4h",
        notes="Sharpe 1.19, 51 trades, WR 51% en BNB; estudiar DOT",
    ),
    StrategyEntry(
        name="BreakoutRetest",
        module="moondev.strategies.breakout_retest",
        class_name="BreakoutRetest",
        status=StrategyStatus.SINGLE_ASSET,
        viable_assets=["META"],
        timeframe="1h",
        notes="Sharpe 2.06 en META; overfit confirmado, solo caso de estudio",
    ),
    # -- Laboratorio (re-diseno necesario) --
    StrategyEntry(
        name="BollingerAltcoin",
        module="moondev.strategies.backtest_architect.bollinger_altcoin",
        class_name="BollingerAltcoin",
        status=StrategyStatus.LABORATORY,
        notes="Senal esporadica (<=4 trades); bajar bb_std o relajar RSI",
    ),
    StrategyEntry(
        name="FundingReversal",
        module="moondev.strategies.backtest_architect.funding_reversal",
        class_name="FundingReversal",
        status=StrategyStatus.LABORATORY,
        notes="Proxy RSI sin edge; necesita datos reales de funding",
    ),
    StrategyEntry(
        name="VolumeMomentum",
        module="moondev.strategies.backtest_architect.volume_momentum",
        class_name="VolumeMomentum",
        status=StrategyStatus.LABORATORY,
        notes="0-3 trades por activo; redisenar senales o timeframe",
    ),
    StrategyEntry(
        name="TechnicalPatterns",
        module="moondev.strategies.backtest_architect.technical_patterns",
        class_name="TechnicalPatterns",
        status=StrategyStatus.LABORATORY,
        notes="Engulfings+MACD netamente perdedores; probar otros patrones",
    ),
    StrategyEntry(
        name="SyntheticArb",
        module="moondev.strategies.backtest_architect.synthetic_arb",
        class_name="SyntheticArb",
        status=StrategyStatus.LABORATORY,
        notes="Sin trades suficientes; sin datos reales de funding/OI",
    ),
    StrategyEntry(
        name="WeakEnsemble",
        module="moondev.strategies.weak_ensemble",
        class_name="WeakEnsemble",
        status=StrategyStatus.DEPRECATED,
        notes="Multi-test 2026-03-14 | v4: 300-420 trades, DD -40/-70%. "
              "v5 (regime gate SMA/ADX): mismo resultado -- ensemble EMA/SMA genera senales "
              "tan frecuentes que ningun gate puede controlarlo en mercado lateral 2024-2025. "
              "Causa raiz estructural: 10 senales de media movil en 1h = overtrading inherente. "
              "Descartada definitivamente.",
    ),
    StrategyEntry(
        name="FundingArbReal",
        module="moondev.strategies.backtest_architect.funding_arb_real",
        class_name="FundingArbReal",
        status=StrategyStatus.LABORATORY,
        notes="0/24 PASS en 1h/4h/1d. Proxy funding sin edge. AAPL 1h Sharpe 1.97, GOOGL 4h 1.85 (PRECAUCION, pocos trades). Necesita datos reales de funding.",
    ),
    StrategyEntry(
        name="LiquidationDoubleDip",
        module="moondev.strategies.backtest_architect.liquidation_double_dip",
        class_name="LiquidationDoubleDip",
        status=StrategyStatus.LABORATORY,
        notes="0/24 PASS en 1h/4h/1d. State machine genera muy pocos trades (0-35 por activo en 1h, 0-13 en 4h, 0-1 en 1d). Forex 0 trades. Necesita datos reales de liquidaciones o relajar filtros.",
    ),
    StrategyEntry(
        name="SuperTrendRegimeFilter",
        module="moondev.strategies.supertrend_regime_filter",
        class_name="SuperTrendRegimeFilter",
        status=StrategyStatus.SINGLE_ASSET,
        viable_assets=["NVDA", "META", "GOOGL"],
        timeframe="1h",
        notes="Multi-test 2026-03-14 | HIGH-CONVICTION LOW-FREQUENCY. "
              "1h 1y: NVDA Sharpe 1.24 DD -4.1% (6 trades), META 1.17 (6 trades), GOOGL 0.77. "
              "4h 2y: QQQ Sharpe 1.11 (3 trades), GBPUSD 0.97 (3 trades). "
              "Problema estructural: doble confirmacion (SuperTrend flip + SMA/ADX) -> 5-15 trades/ano. "
              "No pasa PASS_MIN_TRADES=50. Viable en NVDA/META como estrategia discrecional de alta conviccion.",
    ),
    StrategyEntry(
        name="PairsBTCETH",
        module="moondev.strategies.pairs_btceth",
        class_name="PairsBTCETH",
        status=StrategyStatus.LABORATORY,
        viable_assets=["BTC"],
        timeframe="4h",
        notes="Multi-test 2026-03-14 | BTC 4h, BTC 1h, ETH 4h | 0/3 PASS. "
              "BTC 4h: Sharpe=0.37 Ret=+20.3% DD=-26.8% T=22 (mejor resultado). "
              "BTC 1h: Sharpe=0.09 T=5 (zscore_window=504 en 1h = 21 dias, demasiado corto). "
              "ETH 4h: Sharpe=-1.10 Ret=-44.2% (paradoja: ETH como proxy de su propio spread). "
              "Ref empirico Amberdata Sharpe=0.93 no reproducible con datos yfinance 2024-2026. "
              "Diagnostico: mercado 2024-2026 altamente correlado -> spread no revierte. "
              "Considerar aumentar zscore_window a 1008 barras (168 dias) o hedge ratio beta dinamico.",
    ),
    StrategyEntry(
        name="VolatilitySqueezeV4",
        module="moondev.strategies.volatility_squeeze_v4",
        class_name="VolatilitySqueezeV4",
        status=StrategyStatus.LABORATORY,
        viable_assets=[],
        timeframe="1h",
        notes="Fusión V1+V2+V3 + DI+/DI- direction confirmation + EMA50 trend filter. "
              "BB 1.8std (V3) + KC 1.5mult (V3) + ADX>20 (V2) + volume filter (V3) + "
              "min_squeeze_bars=3 (más estricto) + SL 2.0x / TP 4.0x (V2). "
              "Pendiente de multi-test. Objetivo: Sharpe >2.0, DD <5%.",
    ),
    StrategyEntry(
        name="ORBStrategy",
        module="moondev.strategies.orb_strategy",
        class_name="ORBStrategy",
        status=StrategyStatus.DEPRECATED,
        notes="Testeada en multi-test inicial; sin edge consistente",
    ),
    StrategyEntry(
        name="LiquidationDip",
        module="moondev.strategies.liquidation_dip",
        class_name="LiquidationDip",
        status=StrategyStatus.DEPRECATED,
        notes="Proxy de liquidaciones, sin datos reales; no viable",
    ),
    StrategyEntry(
        name="SuperTrendAdaptive",
        module="moondev.strategies.supertrend_adaptive",
        class_name="SuperTrendAdaptive",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 25 activos 1h 1y | 0/24 PASS. "
              "Whipsawing severo en crypto: 100-180 trades/ano, WR 27-35%. "
              "Forex catastrophico (Sharpe -5 a -12). Mejor NVDA Sharpe 0.48. "
              "Diagnostico: trend-follower sin filtro de regimen en mercado lateral.",
    ),
    StrategyEntry(
        name="GapAndGo",
        module="moondev.strategies.gap_and_go",
        class_name="GapAndGo",
        status=StrategyStatus.DEPRECATED,
        notes="Multi-test 2026-03-14 | 25 activos 1h 1y | 0/24 PASS. "
              "Sharpe negativo en todo el universo. "
              "Diagnostico: gap overnight inexistente en crypto 24/7; senal = ruido. "
              "Descartada del pipeline activo.",
    ),

    # =========================================================================
    # ESTRATEGIAS MIGRADAS DESDE RBI-BACKTESTER (2026-03-14)
    # =========================================================================

    # -- Bollinger Bands --
    StrategyEntry(
        name="RBI-BollingerSqueeze",
        module="moondev.strategies.rbi.bollinger",
        class_name="BollingerSqueeze",
        status=StrategyStatus.TESTNET_READY,
        viable_assets=["BTC"],
        timeframe="1h",
        notes="TESTNET CANDIDATE #2 (2026-03-16). BB inside Keltner / Bollinger Squeeze. "
              "BTC: Sharpe=1.02 Ret=+37.7% DD=-19.8% WR=47.7% T=44. "
              "ETH: Sharpe=0.94 Ret=+69.3% DD=-31.0% (DD alto). "
              "SOL: Sharpe=-0.14 (falla). Deploy: SOLO BTC 1h.",
    ),
    StrategyEntry(
        name="RBI-BollingerBreakoutLong",
        module="moondev.strategies.rbi.bollinger",
        class_name="BollingerBreakoutLong",
        status=StrategyStatus.LABORATORY,
        notes="BTC-USD 1h Feb 2026: Sharpe -1.27, Return -15.09%. Migrada desde RBI-Backtester. Pendiente de multi-test.",
    ),
    StrategyEntry(
        name="RBI-BollingerBreakoutShort",
        module="moondev.strategies.rbi.bollinger",
        class_name="BollingerBreakoutShort",
        status=StrategyStatus.LABORATORY,
        notes="BTC-USD 1h Feb 2026: Sharpe -0.91, Return -11.68%. Migrada desde RBI-Backtester. Pendiente de multi-test.",
    ),
    StrategyEntry(
        name="RBI-BollingerRSI",
        module="moondev.strategies.rbi.bollinger",
        class_name="BollingerRSI",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 9 activos 1h | 0/9 PASS. "
              "Mean reversion BB+RSI doble confirmacion. Senales escasas en forex (3-4 trades). "
              "Mejor: USDJPY Sharpe=1.20 DD=-4.9% pero solo 4 trades. "
              "Crypto pierde dinero: BTC -18.2% Sharpe=-1.09, ETH -44.6%. "
              "Diagnostico: filtro doblemente restrictivo -> pocas senales validas. "
              "Ajustar rsi_oversold=35, bb_std=1.5 para mas frecuencia.",
    ),

    # -- RSI --
    StrategyEntry(
        name="RBI-RSIMeanReversion",
        module="moondev.strategies.rbi.rsi",
        class_name="RSIMeanReversion",
        status=StrategyStatus.LABORATORY,
        notes="BTC-USD 1h Feb 2026: Sharpe -1.70, Return -31.06%. Migrada desde RBI-Backtester. Pendiente de multi-test.",
    ),
    StrategyEntry(
        name="RBI-StochRSICrossover",
        module="moondev.strategies.rbi.rsi",
        class_name="StochRSICrossover",
        status=StrategyStatus.LABORATORY,
        notes="BTC-USD 1h Feb 2026: Sharpe -3.27, Return -31.49%. Migrada desde RBI-Backtester. Pendiente de multi-test.",
    ),
    StrategyEntry(
        name="RBI-RSIDivergence",
        module="moondev.strategies.rbi.rsi",
        class_name="RSIDivergence",
        status=StrategyStatus.TESTNET_READY,
        viable_assets=["BTC"],
        timeframe="1h",
        notes="TESTNET CANDIDATE #3 (2026-03-16). RSI divergence detection. "
              "BTC: Sharpe=1.00 Ret=+52.4% DD=-20.4% WR=51.7% T=60. "
              "PELIGRO: ETH Sharpe=-2.46, SOL Sharpe=-3.23 (destruye capital). "
              "Deploy: EXCLUSIVAMENTE BTC 1h. Prohibido en alts.",
    ),

    # -- MACD --
    StrategyEntry(
        name="RBI-MACDHistogram",
        module="moondev.strategies.rbi.macd",
        class_name="MACDHistogram",
        status=StrategyStatus.LABORATORY,
        notes="BTC-USD 1h Feb 2026: Sharpe -1.01, Return -15.59%. Migrada desde RBI-Backtester. Pendiente de multi-test.",
    ),
    StrategyEntry(
        name="RBI-MACDCrossover",
        module="moondev.strategies.rbi.macd",
        class_name="MACDCrossover",
        status=StrategyStatus.LABORATORY,
        notes="BTC-USD 1h Feb 2026: Sharpe -1.30, Return -20.79%. Migrada desde RBI-Backtester. Pendiente de multi-test.",
    ),

    # -- MFI --
    StrategyEntry(
        name="RBI-MFIMeanReversion",
        module="moondev.strategies.rbi.mfi",
        class_name="MFIMeanReversion",
        status=StrategyStatus.LABORATORY,
        notes="BTC-USD 1h Feb 2026: Sharpe -2.19, Return -33.62%. Migrada desde RBI-Backtester. Pendiente de multi-test.",
    ),

    # -- VWAP --
    StrategyEntry(
        name="RBI-VWAPBounce",
        module="moondev.strategies.rbi.vwap",
        class_name="VWAPBounce",
        status=StrategyStatus.LABORATORY,
        notes="BTC-USD 1h Feb 2026: Sharpe -2.01, Return -34.02%. Migrada desde RBI-Backtester. Pendiente de multi-test.",
    ),

    # -- CCI --
    StrategyEntry(
        name="RBI-CCIMeanReversion",
        module="moondev.strategies.rbi.cci",
        class_name="CCIMeanReversion",
        status=StrategyStatus.LABORATORY,
        notes="BTC-USD 1h Feb 2026: Sharpe -0.16, Return -4.5%. Migrada desde RBI-Backtester. Pendiente de multi-test.",
    ),

    # -- SuperTrend --
    StrategyEntry(
        name="RBI-SuperTrendAdaptive",
        module="moondev.strategies.rbi.supertrend",
        class_name="SuperTrendAdaptive",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 9 activos 1h | 1/9 PASS. "
              "PASS: AAPL Sharpe=1.09 Ret=+22.3% DD=-11.7% T=28. "
              "Crypto: BTC Sharpe=-5.69 (whipsaw severo), ETH -0.39, SOL -1.94. "
              "Forex: EURUSD Sharpe=-6.15, USDJPY -2.71 (catastrofico). "
              "Diagnostico: identico al SuperTrendAdaptive original (mismo patron). "
              "Unico edge: acciones trending de baja volatilidad (AAPL). "
              "No supera umbral PASS_MIN_TRADES=50; AAPL tiene 28 trades.",
    ),

    # -- Ichimoku --
    StrategyEntry(
        name="RBI-IchimokuCloud",
        module="moondev.strategies.rbi.ichimoku",
        class_name="IchimokuCloud",
        status=StrategyStatus.LABORATORY,
        notes="BTC-USD 1h Feb 2026: Sharpe -1.21, Return -21.98%. Migrada desde RBI-Backtester. Pendiente de multi-test.",
    ),

    # -- ORB --
    StrategyEntry(
        name="RBI-OpeningRangeBreakout",
        module="moondev.strategies.rbi.orb",
        class_name="OpeningRangeBreakout",
        status=StrategyStatus.LABORATORY,
        notes="BTC-USD 1h Feb 2026: Sharpe -0.92, Return -17.63%. Migrada desde RBI-Backtester. Pendiente de multi-test.",
    ),

    # -- Breakout Retest Sniper --
    StrategyEntry(
        name="RBI-BreakoutRetestSniper",
        module="moondev.strategies.rbi.breakout",
        class_name="BreakoutRetestSniper",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 9 activos 1h | 0/9 PASS. "
              "Breakout + retest en ventana de 3 velas. "
              "Mejor: NVDA Sharpe=0.47 Ret=+8.7% DD=-7.5%. "
              "Peor: USDJPY -43.9% (shorts fallan en forex). "
              "Crypto: BTC T=0 (ninguna entrada), ETH T=3. "
              "Diagnostico: ventana retest=3 demasiado estrecha en 1h; probar retest_window=6-10.",
    ),

    # -- Pine Script adaptadas (9 estrategias) --
    StrategyEntry(
        name="RBI-PineDemarsiStrategy",
        module="moondev.strategies.rbi.pine_promoted",
        class_name="PineDemarsiStrategy",
        status=StrategyStatus.LABORATORY,
        notes="Pine: DemaRSI. Sharpe 0.48, Ret +319.9%, DD -46.4%, 138 trades (BTC-USD 1d). Migrada desde RBI-Backtester.",
    ),
    StrategyEntry(
        name="RBI-PineMicurobertEmaCross",
        module="moondev.strategies.rbi.pine_promoted",
        class_name="PineMicurobertEmaCrossStrategy",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 6 activos (3x1h + 3x1d) | 0/6 PASS. "
              "DEMA+RSI trend following. Mejor: ETH 1d Sharpe=0.44 Ret=+99.3% DD=-46.6%. "
              "Crypto 1h: BTC -52.7% Sharpe=-6.29 T=490 (overtrading), SOL -67.8%. "
              "DD excesivo en todos los casos (>35%). "
              "Diagnostico: overtrading en 1h sin SL/TP fijos; 1d promisorio pero DD alto.",
    ),
    StrategyEntry(
        name="RBI-PineBestEngulfingBreakout",
        module="moondev.strategies.rbi.pine_promoted",
        class_name="PineBestEngulfingBreakoutStrategy",
        status=StrategyStatus.LABORATORY,
        notes="Pine: BEST Engulfing + Breakout. Sharpe 0.38, Ret +134.6%, DD -50.1%, 84 trades (BTC-USD 1d). Migrada desde RBI-Backtester.",
    ),
    StrategyEntry(
        name="RBI-PineFractalBreakout",
        module="moondev.strategies.rbi.pine_promoted",
        class_name="PineFractalBreakoutStrategyByChartart",
        status=StrategyStatus.LABORATORY,
        notes="Pine: Fractal Breakout (ChartArt). VALIDATED. Sharpe 0.36, Ret +47.5%, DD -25.1%, 135 trades (BTC-USD 1d). Migrada desde RBI-Backtester.",
    ),
    StrategyEntry(
        name="RBI-PineUltimateStrategyTemplate",
        module="moondev.strategies.rbi.pine_promoted",
        class_name="PineUltimateStrategyTemplate",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 6 activos (3x1h + 3x1d) | 0/6 PASS. "
              "Mejor: ETH 1d Sharpe=0.52 Ret=+88.3% DD=-36.5%. "
              "1h crypto: ETH -34.8%, SOL -67.8%, BTC perdedor. "
              "DD sistematicamente >35%. Diagnostico: misma logica DEMA+RSI que PineDemarsi; "
              "falta SL/TP para controlar drawdown.",
    ),
    StrategyEntry(
        name="RBI-PineBestAbcdPattern",
        module="moondev.strategies.rbi.pine_promoted",
        class_name="PineBestAbcdPatternStrategy",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 6 activos | 0/6 PASS. "
              "Mejor: ETH 1d Sharpe=0.52 Ret=+88.3% DD=-36.5% (identico a PineUltimate). "
              "Crypto 1h muy perdedor. DD siempre >35%. Mismo patron que resto de Pine: "
              "sin gestion de riesgo -> drawdown incontrolado.",
    ),
    StrategyEntry(
        name="RBI-PineRiskManagement",
        module="moondev.strategies.rbi.pine_promoted",
        class_name="PineStrategyCodeExampleRiskManagement",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 6 activos | 0/6 PASS. "
              "Mejor: ETH 1d Sharpe=0.52 Ret=+88.3% DD=-36.5%. "
              "Ironicamente la estrategia 'Risk Management' no controla DD en backtest. "
              "Crypto 1h: resultados identicos a las demas Pine (misma logica subyacente). "
              "Requiere revision del codigo para aplicar SL/TP reales.",
    ),
    StrategyEntry(
        name="RBI-PineTimeLimiting",
        module="moondev.strategies.rbi.pine_promoted",
        class_name="PineStrategyCodeExample2TimeLimiting",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 6 activos | 0/6 PASS. "
              "Mejor: ETH 1d Sharpe=0.52 Ret=+88.3% DD=-36.5%. "
              "Time-limiting no ayuda a reducir DD en crypto. "
              "Resultados identicos al grupo Pine (misma logica base). "
              "El limite de tiempo no es el problema: es la ausencia de SL.",
    ),
    StrategyEntry(
        name="RBI-PineCombo220EmaBullPower",
        module="moondev.strategies.rbi.pine_promoted",
        class_name="PineCombo220EmaBullPowerStrategy",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 6 activos | 0/6 PASS. "
              "Mejor: ETH 1d Sharpe=0.52 Ret=+88.3% DD=-36.5%. "
              "EMA 2/20 + Bull Power. Mismo patron de fallo que resto del grupo Pine: "
              "overtrading en 1h, DD >35% en 1d. Sin SL/TP no hay control de riesgo.",
    ),

    # -- MoonDev FINAL_WINNING_STRATEGIES (10 estrategias) --
    StrategyEntry(
        name="RBI-MoonATRChannelSystem",
        module="moondev.strategies.rbi.moondev_winning_strategies",
        class_name="MoonATRChannelSystem",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 11 activos (1h+1d) | 0/11 PASS, 1 PRECAUCION. "
              "Mejor: AAPL 1h Sharpe=0.95 Ret=+19.7% DD=-10.2% T=27 (rozando PASS). "
              "Crypto: BTC -22.4%, NVDA -53.0% (shorts devastadores). "
              "Diagnostico: ATR breakout genera longs OK pero shorts en tendencia alcista destruyen capital.",
    ),
    StrategyEntry(
        name="RBI-MoonBollingerReversion",
        module="moondev.strategies.rbi.moondev_winning_strategies",
        class_name="MoonBollingerReversion",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 11 activos | 0/11 PASS. "
              "Mejor: SOL 1h Sharpe=0.20 Ret=+2.9% DD=-17.0%. "
              "Peor: EURUSD -50.3%. Crypto y forex muy negativos. "
              "Diagnostico: BB reversion + RSI en mercado tendencial 2024-2025 -> "
              "mean reversion no funciona contra tendencias fuertes de crypto.",
    ),
    StrategyEntry(
        name="RBI-MoonHybridMomentumReversion",
        module="moondev.strategies.rbi.moondev_winning_strategies",
        class_name="MoonHybridMomentumReversion",
        status=StrategyStatus.SINGLE_ASSET,
        viable_assets=["SPY", "QQQ", "NVDA"],
        timeframe="1h",
        notes="Multi-test 2026-03-14 | 11 activos | 3/11 PASS (27%) | SELECTIVO. "
              "PASS: SPY Sharpe=1.35 Ret=+10.1% DD=-4.0% T=26, "
              "QQQ Sharpe=1.42 Ret=+14.4% DD=-5.8% T=25, "
              "NVDA Sharpe=1.12 Ret=+24.5% DD=-8.8% T=30. "
              "PRECAUCION: SOL Sharpe=0.55 Ret=+14.3% DD=-22.0% T=88. "
              "Crypto: BTC Sharpe=-0.48 T=95, ETH -2.08. Forex: 0 trades (inactiva). "
              "Diagnostico: ADX regime gate funciona bien en acciones US trending. "
              "NOTA: T=25-30 justo en el limite del criterio de 20 trades.",
    ),
    StrategyEntry(
        name="RBI-MoonMACDDivergence",
        module="moondev.strategies.rbi.moondev_winning_strategies",
        class_name="MoonMACDDivergence",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 11 activos | 0/11 PASS. "
              "Todos los activos: Ret=0.0%, T=0 (nunca genera senales en backtest). "
              "Diagnostico: condicion de divergencia demasiado restrictiva -> 0 trades. "
              "Requiere revision de logica de deteccion de divergencias.",
    ),
    StrategyEntry(
        name="RBI-MoonRSIMeanReversion",
        module="moondev.strategies.rbi.moondev_winning_strategies",
        class_name="MoonRSIMeanReversion",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 11 activos | 0/11 PASS. "
              "Mejor: NVDA Sharpe=0.38 Ret=+13.3% DD=-17.0%. "
              "Peor: USDJPY -45.7%. Forex muy negativo. "
              "Diagnostico: RSI oversold/overbought + BB en 2024-2025 no genera edge. "
              "Mercado tendencial invalida la premisa de mean reversion.",
    ),
    StrategyEntry(
        name="RBI-MoonSimpleMomentumCross",
        module="moondev.strategies.rbi.moondev_winning_strategies",
        class_name="MoonSimpleMomentumCross",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 11 activos | 0/11 PASS. "
              "Mejor: BTC 1h Sharpe=0.10 Ret=+1.7% DD=-19.3%. "
              "Peor: SOL -41.0%. EMA cross + volume filter no genera edge. "
              "Diagnostico: EMA crossover simple es una de las senales con menos edge "
              "documentado en crypto; el filtro de volumen no mejora la situacion.",
    ),
    StrategyEntry(
        name="RBI-MoonStochasticMomentum",
        module="moondev.strategies.rbi.moondev_winning_strategies",
        class_name="MoonStochasticMomentum",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 11 activos | 0/11 PASS. "
              "Todos: T=0 o T=1 (practicamente sin senales). "
              "Diagnostico: stochastic OS/OB + EMA + volume demasiado restrictivo. "
              "Triple confirmacion -> cerca de 0 entradas. Relajar thresholds.",
    ),
    StrategyEntry(
        name="RBI-MoonTrendFollowingMA",
        module="moondev.strategies.rbi.moondev_winning_strategies",
        class_name="MoonTrendFollowingMA",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 11 activos | 0/11 PASS. "
              "Mejor: AAPL 1h Sharpe=0.35 Ret=+6.5% DD=-18.2%. "
              "Peor: BTC -49.3%. Triple EMA alignment + volume surge. "
              "Diagnostico: requiere alineacion de 3 EMAs con volumen -> pocas senales. "
              "Cuando entra, drawdown alto por ausencia de SL dinamico.",
    ),
    StrategyEntry(
        name="RBI-MoonVolatilityBreakout",
        module="moondev.strategies.rbi.moondev_winning_strategies",
        class_name="MoonVolatilityBreakout",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 11 activos | 0/11 PASS. "
              "Mejor: BTC 1d Sharpe=0.22 Ret=+13.6% DD=-25.6%. "
              "Peor: BTC 1h -35.0%. ATR breakout + volume. "
              "Diagnostico: funciona marginalmente en 1d pero insuficiente Sharpe y alto DD. "
              "En 1h: whipsaw severo en crypto.",
    ),
    StrategyEntry(
        name="RBI-MoonVolumeWeightedBreakout",
        module="moondev.strategies.rbi.moondev_winning_strategies",
        class_name="MoonVolumeWeightedBreakout",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 11 activos | 0/11 PASS, 1 PRECAUCION. "
              "Mejor: AAPL 1h Sharpe=0.59 Ret=+12.2% DD=-9.8% T=26. "
              "Peor: SOL -61.1%. Rolling VWAP breakout + volumen + momentum. "
              "Diagnostico: en acciones low-vol funciona aceptablemente pero sin superar Sharpe=1.0. "
              "Crypto muy negativo (SOL -61%, BTC -29%). "
              "Probar only-long + stop loss fijo.",
    ),

    # -- Estrategias avanzadas (FINAL_WINNING_STRATEGIES) --
    StrategyEntry(
        name="RBI-TrendCapturePro",
        module="moondev.strategies.rbi.trend_capture_pro",
        class_name="TrendCapturePro",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 9 activos 1h | 0/9 PASS, 1 PRECAUCION. "
              "Mejor: ETH 1h Sharpe=0.73 Ret=+8.7% DD=-13.9% T=44. "
              "Peor: SOL -6.4% T=10. Target Sharpe 2.0+ no alcanzado. "
              "BTC Sharpe=-0.49, SPY=0.42, QQQ=0.48. "
              "Diagnostico: trailing stops complejos no compensan el filtro ADX/EMA. "
              "Sistema de confirmacion multi-factor reduce trades a niveles insuficientes.",
    ),
    StrategyEntry(
        name="RBI-SelectiveMomentumSwing",
        module="moondev.strategies.rbi.selective_momentum_swing",
        class_name="SelectiveMomentumSwing",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 9 activos 1h | 0/9 PASS. "
              "Todos los activos: Ret=0.0%, T=0 (nunca genera senales). "
              "Target Sharpe 2.2-3.5 no alcanzado en ningun activo. "
              "Diagnostico: pullback_threshold + volume_multiplier + volatility_filter + "
              "RSI combinados -> 0 entradas en 1h. Demasiados filtros para 1h. "
              "Probar en 4h o 1d con parametros mas relajados.",
    ),
    StrategyEntry(
        name="RBI-DivergenceVolatilityEnhanced",
        module="moondev.strategies.rbi.divergence_volatility_enhanced",
        class_name="DivergenceVolatilityEnhanced",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 9 activos 1h | 0/9 PASS. "
              "Mejor: SOL 1h Sharpe=2.13 Ret=+7.7% DD=-1.2% T=5 (solo 5 trades -> invalido). "
              "BTC T=4, ETH T=3 (casi sin trades). SPY/QQQ T=7-8. "
              "Target Sharpe 2.0-3.0 aparece en SOL pero con estadistica insuficiente. "
              "Diagnostico: deteccion de divergencias + confirmacion MACD+BB+volume -> "
              "ultra-selectivo, <10 trades por activo. Reducir min_separation o relajar filtros.",
    ),

    # -- Estrategias institucionales (factories) --
    StrategyEntry(
        name="RBI-OrderBookImbalance",
        module="moondev.strategies.rbi.institutional_strategies",
        class_name="make_orderbook_imbalance_strategy",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 7 activos 1h | 0/7 PASS. "
              "Todos T=0 (ningun trade generado en backtest). "
              "En backtest: imbalance=0.5 fijo (proxy) + RSI<40 + imbalance>0.65 -> "
              "condicion imbalance NUNCA se cumple porque se usa valor fixo 0.5. "
              "Diagnostico: estrategia solo viable en modo live con datos reales de Hyperliquid. "
              "Sin datos de order book no hay senales.",
    ),
    StrategyEntry(
        name="RBI-LiquidationCascade",
        module="moondev.strategies.rbi.institutional_strategies",
        class_name="make_liquidation_cascade_strategy",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 7 activos 1h | 0/7 PASS, 3 PRECAUCION. "
              "Mejor: QQQ Sharpe=1.13 Ret=+9.3% DD=-4.4% T=18 (bajo Sharpe umbral trades). "
              "SPY Sharpe=0.97 T=10, AAPL Sharpe=0.74 T=10. "
              "Crypto: BTC -20.7%, ETH T=3. "
              "Diagnostico: RSI<25 + BB inferior en crypto es extremadamente raro -> pocos trades. "
              "En acciones funciona mejor (QQQ cerca de PASS). Probar rsi_oversold=30.",
    ),
    StrategyEntry(
        name="RBI-HeatMapRotation",
        module="moondev.strategies.rbi.institutional_strategies",
        class_name="make_heatmap_rotation_strategy",
        status=StrategyStatus.TESTNET_READY,
        viable_assets=["ETH", "SOL"],
        timeframe="1h",
        notes="TESTNET CANDIDATE #1 (2026-03-16). Mass backtest 88 strats: avg Sharpe 1.58, best 2.20 (SOL). "
              "ETH: Sharpe=1.83 Ret=+35.7% DD=-14.2% WR=55.9% T=59. "
              "SOL: Sharpe=2.20 Ret=+83.1% DD=-11.3% WR=61.4% T=70. "
              "BTC: Sharpe=0.70 (sub-par, no recomendado). "
              "Edge: correlacion BTC como filtro de regimen para altcoins. "
              "Deploy: ETH + SOL 1h. NO activar sin revision manual.",
    ),

    # -- Estrategias macro (factories, requieren yfinance) --
    StrategyEntry(
        name="RBI-VIXFearMeanReversion",
        module="moondev.strategies.rbi.macro_strategies",
        class_name="make_vix_fear_strategy",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 5 stocks 1d | 0/5 PASS. "
              "Todos T=1 (un solo trade en 5 anos). VIX>=30 + precio>SMA50. "
              "Mejor: AAPL Sharpe=0.73 Ret=+9.9% DD=-1.2%. "
              "Diagnostico: VIX>=30 ocurrio muy poco en 2021-2026 (COVID spike en 2020 no capturado). "
              "Bajar threshold a vix_buy=25 o ampliar periodo a 10 anos.",
    ),
    StrategyEntry(
        name="RBI-DXYForexRotation",
        module="moondev.strategies.rbi.macro_strategies",
        class_name="make_dxy_forex_strategy",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 7 activos 1d | 0/7 PASS. "
              "Mejor (enganaoso): NVDA Sharpe=0.76 Ret=+609.2% DD=-41.5% (DD>-30% -> FAIL). "
              "Diagnostico: en mode='long' con DXY>=104 el timing no es preciso. "
              "DD sistematicamente alto. Forex (EURUSD, USDJPY) baja actividad. "
              "NVDA retorno alto pero drawdown invalida la estrategia como viable.",
    ),
    StrategyEntry(
        name="RBI-YieldCurveSignal",
        module="moondev.strategies.rbi.macro_strategies",
        class_name="make_yield_curve_strategy",
        status=StrategyStatus.LABORATORY,
        notes="Multi-test 2026-03-14 | 5 stocks 1d | 0/5 PASS. "
              "Mejor: NVDA Sharpe=0.14 Ret=+33.2% DD=-68.1% (DD catastrofico). "
              "Peor: MSFT -11.0%. Spread 10Y-2Y en 2022-2026: invertido largo tiempo. "
              "Diagnostico: curva invertida 2022-2024 -> pocas senales de normalizacion. "
              "El unico trade en NVDA fue durante normalizacion 2024 (por eso el retorno). "
              "Estrategia de baja frecuencia por diseno; necesita datos de 20+ anos.",
    ),
]


def get_by_status(status: StrategyStatus) -> list:
    return [s for s in STRATEGIES if s.status == status]
