"""
registry.py — Catálogo centralizado de estrategias y su estado de validación.
Actualizado por el Backtest Architect tras multi-test de 25 activos.
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import List


class StrategyStatus(Enum):
    GLOBAL = "global"              # Viable multi-asset
    SINGLE_ASSET = "single_asset"  # Solo viable en activos específicos
    LABORATORY = "laboratory"      # Necesita re-diseño
    DEPRECATED = "deprecated"      # Descartada


@dataclass
class StrategyEntry:
    name: str
    module: str           # path relativo al módulo
    class_name: str
    status: StrategyStatus
    viable_assets: List[str] = field(default_factory=list)
    timeframe: str = ""
    notes: str = ""


STRATEGIES: List[StrategyEntry] = [
    # — Producción limitada (single-asset) —
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
    # — Laboratorio (re-diseño necesario) —
    StrategyEntry(
        name="BollingerAltcoin",
        module="moondev.strategies.backtest_architect.bollinger_altcoin",
        class_name="BollingerAltcoin",
        status=StrategyStatus.LABORATORY,
        notes="Señal esporádica (<=4 trades); bajar bb_std o relajar RSI",
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
        notes="0-3 trades por activo; rediseñar señales o timeframe",
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
        module="moondev.strategies.backtest_architect.weak_ensemble",
        class_name="WeakEnsemble",
        status=StrategyStatus.LABORATORY,
        notes="DD -40% a -70% en crypto; ensemble no calibrado",
    ),
    # — Nuevas estrategias (multi-test 2026-03-01, 25 activos x 3 TFs) —
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
    # — Otras (testeadas, sin veredicto formal multi-asset aún) —
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
        name="SupertrendAdaptive",
        module="moondev.strategies.supertrend_adaptive",
        class_name="SupertrendAdaptive",
        status=StrategyStatus.LABORATORY,
        notes="Pendiente de multi-test formal",
    ),
    StrategyEntry(
        name="GapAndGo",
        module="moondev.strategies.gap_and_go",
        class_name="GapAndGo",
        status=StrategyStatus.LABORATORY,
        notes="Pendiente de multi-test formal",
    ),
]


def get_by_status(status: StrategyStatus) -> list:
    return [s for s in STRATEGIES if s.status == status]
