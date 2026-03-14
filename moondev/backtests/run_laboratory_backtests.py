"""
run_laboratory_backtests.py
Ejecuta multi-test para todas las estrategias RBI en estado LABORATORY
con notas "Pendiente de multi-test".

Uso:
    python moondev/backtests/run_laboratory_backtests.py

Criterios del usuario:
    PASS: Sharpe >= 1.0, NumTrades >= 20, MaxDD > -30%
    (nota: config.py define PASS_MIN_TRADES=50; aqui usamos 20 por instruccion)
"""
import sys
import warnings
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
from datetime import datetime, timezone

import pandas as pd
import numpy as np

warnings.filterwarnings("ignore")

# Path setup
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backtesting import Backtest
from moondev.data.data_fetcher import get_ohlcv

# Criterios del usuario (sobrepasan moondev.config para este run)
USER_PASS_SHARPE = 1.0
USER_PASS_MIN_TRADES = 20
USER_PASS_MAX_DD = -30.0  # MaxDD debe ser > -30% (menos negativo)

COMMISSION = 0.00105  # 0.1% + 0.005% slippage

# Simbolos de test (compacto para velocidad: BTC, ETH, SOL + 2 stocks)
SYMBOLS_CRYPTO_1H = ["BTC", "ETH", "SOL"]
SYMBOLS_STOCKS    = ["SPY", "QQQ", "AAPL", "NVDA"]
SYMBOLS_FOREX     = ["EURUSD", "USDJPY"]

# Simbolos 1d para Pine/Moon strategies
SYMBOLS_1D = ["BTC", "ETH", "SPY"]

# PairsBTCETH solo en 4h BTC
SYMBOLS_PAIRS = ["BTC"]


@dataclass
class Result:
    symbol: str
    interval: str
    ret_pct: float = 0.0
    sharpe: float = 0.0
    max_dd: float = 0.0
    trades: int = 0
    win_rate: float = 0.0
    error: Optional[str] = None

    def verdict(self, min_trades: int = USER_PASS_MIN_TRADES) -> str:
        if self.error:
            return "ERROR"
        if (self.sharpe >= USER_PASS_SHARPE
                and self.trades >= min_trades
                and self.max_dd > USER_PASS_MAX_DD):
            return "PASS"
        if self.sharpe >= 0.5 and self.trades >= 10 and self.max_dd > -35.0:
            return "PRECAUCION"
        return "FAIL"


def fetch(symbol: str, interval: str = "1h", days: int = 365) -> Optional[pd.DataFrame]:
    """Descarga OHLCV con el fetcher unificado."""
    try:
        df = get_ohlcv(symbol, interval=interval, days=days)
        if df is None or len(df) < 100:
            return None
        if "open" in df.columns:
            df.columns = [c.capitalize() for c in df.columns]
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        return df if len(df) >= 100 else None
    except Exception as e:
        return None


def run_bt(strategy_cls, symbol: str, interval: str = "1h", days: int = 365) -> Result:
    """Ejecuta backtest para un simbolo."""
    r = Result(symbol=symbol, interval=interval)
    df = fetch(symbol, interval, days)
    if df is None:
        r.error = "Sin datos"
        return r
    try:
        max_price = float(df["Close"].max())
        cash = max(10_000, max_price * 3)
        bt = Backtest(df, strategy_cls, cash=cash, commission=COMMISSION,
                      exclusive_orders=True, finalize_trades=True)
        stats = bt.run()
        r.ret_pct  = float(stats["Return [%]"])
        r.sharpe   = float(stats["Sharpe Ratio"]) if pd.notna(stats["Sharpe Ratio"]) else 0.0
        r.max_dd   = float(stats["Max. Drawdown [%]"])
        r.trades   = int(stats["# Trades"])
        r.win_rate = float(stats["Win Rate [%]"]) if pd.notna(stats["Win Rate [%]"]) else 0.0
    except Exception as e:
        r.error = str(e)[:80]
    return r


def run_strategy(name: str, strategy_cls, symbols_intervals: List[Tuple[str, str, int]]) -> List[Result]:
    """Corre una estrategia contra multiples (symbol, interval, days)."""
    results = []
    for sym, iv, days in symbols_intervals:
        print(f"    {sym:<10} {iv:<4}", end=" ", flush=True)
        r = run_bt(strategy_cls, sym, iv, days)
        v = r.verdict()
        print(f"Ret={r.ret_pct:+.1f}% Sharpe={r.sharpe:.2f} DD={r.max_dd:.1f}% T={r.trades} -> {v}")
        results.append(r)
    return results


def print_summary(name: str, results: List[Result]) -> dict:
    """Imprime resumen y retorna stats para el registry."""
    valid = [r for r in results if not r.error]
    passing = [r for r in valid if r.verdict() == "PASS"]
    caution = [r for r in valid if r.verdict() == "PRECAUCION"]

    best = max(valid, key=lambda r: r.sharpe, default=None)
    worst = min(valid, key=lambda r: r.ret_pct, default=None)

    pct = len(passing) / len(valid) * 100 if valid else 0
    verdict = "VIABLE" if pct >= 40 else ("SELECTIVO" if pct >= 20 else "NO_VIABLE")

    print(f"\n  RESUMEN {name}")
    print(f"  PASS: {len(passing)}/{len(valid)} ({pct:.0f}%) | PRECAUCION: {len(caution)}")
    if best:
        print(f"  MEJOR:  {best.symbol} {best.interval} Sharpe={best.sharpe:.2f} Ret={best.ret_pct:+.1f}% DD={best.max_dd:.1f}%")
    if worst:
        print(f"  PEOR:   {worst.symbol} {worst.interval} Ret={worst.ret_pct:+.1f}%")
    print(f"  VEREDICTO: {verdict}")
    print()

    return {
        "name": name,
        "passing": len(passing),
        "total": len(valid),
        "pct_pass": pct,
        "verdict": verdict,
        "best": f"{best.symbol} {best.interval} Sharpe={best.sharpe:.2f} Ret={best.ret_pct:+.1f}% DD={best.max_dd:.1f}%" if best else "N/A",
        "worst": f"{worst.symbol} {worst.interval} Ret={worst.ret_pct:+.1f}%" if worst else "N/A",
        "results": [
            {"symbol": r.symbol, "interval": r.interval, "ret": r.ret_pct,
             "sharpe": r.sharpe, "dd": r.max_dd, "trades": r.trades,
             "wr": r.win_rate, "verdict": r.verdict(), "error": r.error}
            for r in results
        ],
    }


def load_strategy_factory(module_path: str, factory_fn: str, **kwargs):
    """Carga una factory de estrategia y la instancia con kwargs."""
    import importlib
    mod = importlib.import_module(module_path)
    factory = getattr(mod, factory_fn)
    return factory(**kwargs)


def load_strategy_class(module_path: str, class_name: str):
    """Carga una clase de estrategia directamente."""
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


# =============================================================================
# MAIN
# =============================================================================

def main():
    all_summaries = []
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    print("=" * 70)
    print("  BACKTEST ARCHITECT -- Multi-test estrategias LABORATORY")
    print(f"  Criterios PASS: Sharpe>={USER_PASS_SHARPE}, Trades>={USER_PASS_MIN_TRADES}, DD>{USER_PASS_MAX_DD}%")
    print(f"  Inicio: {ts}")
    print("=" * 70)

    # Simbolos estandar 1h (BTC + stocks)
    std_1h = (
        [(s, "1h", 365) for s in SYMBOLS_CRYPTO_1H]
        + [(s, "1h", 365) for s in SYMBOLS_STOCKS]
        + [(s, "1h", 365) for s in SYMBOLS_FOREX]
    )

    # Simbolos 1d (Pine/Moon)
    std_1d = [(s, "1d", 730) for s in SYMBOLS_1D]

    # Simbolos solo crypto 1h
    crypto_1h = [(s, "1h", 365) for s in SYMBOLS_CRYPTO_1H]

    # ==========================================================================
    # 1. RBI-BollingerRSI
    # ==========================================================================
    print("\n[1/20] RBI-BollingerRSI")
    try:
        cls = load_strategy_class("moondev.strategies.rbi.bollinger", "BollingerRSI")
        results = run_strategy("BollingerRSI", cls, std_1h)
        all_summaries.append(print_summary("RBI-BollingerRSI", results))
    except Exception as e:
        print(f"  ERROR al cargar: {e}")
        all_summaries.append({"name": "RBI-BollingerRSI", "verdict": "ERROR", "error": str(e)})

    # ==========================================================================
    # 2. RBI-BreakoutRetestSniper
    # ==========================================================================
    print("\n[2/20] RBI-BreakoutRetestSniper")
    try:
        cls = load_strategy_class("moondev.strategies.rbi.breakout", "BreakoutRetestSniper")
        results = run_strategy("BreakoutRetestSniper", cls, std_1h)
        all_summaries.append(print_summary("RBI-BreakoutRetestSniper", results))
    except Exception as e:
        print(f"  ERROR al cargar: {e}")
        all_summaries.append({"name": "RBI-BreakoutRetestSniper", "verdict": "ERROR", "error": str(e)})

    # ==========================================================================
    # 3. RBI-SuperTrendAdaptive (RBI version)
    # ==========================================================================
    print("\n[3/20] RBI-SuperTrendAdaptive")
    try:
        cls = load_strategy_class("moondev.strategies.rbi.supertrend", "SuperTrendAdaptive")
        results = run_strategy("SuperTrendAdaptive", cls, std_1h)
        all_summaries.append(print_summary("RBI-SuperTrendAdaptive", results))
    except Exception as e:
        print(f"  ERROR al cargar: {e}")
        all_summaries.append({"name": "RBI-SuperTrendAdaptive", "verdict": "ERROR", "error": str(e)})

    # ==========================================================================
    # 4. RBI-PineMicurobertEmaCross
    # ==========================================================================
    print("\n[4/20] RBI-PineMicurobertEmaCross")
    try:
        cls = load_strategy_class("moondev.strategies.rbi.pine_promoted", "PineMicurobertEmaCrossStrategy")
        results = run_strategy("PineMicurobertEmaCross", cls, crypto_1h + std_1d)
        all_summaries.append(print_summary("RBI-PineMicurobertEmaCross", results))
    except Exception as e:
        print(f"  ERROR al cargar: {e}")
        all_summaries.append({"name": "RBI-PineMicurobertEmaCross", "verdict": "ERROR", "error": str(e)})

    # ==========================================================================
    # 5. RBI-PineUltimateStrategyTemplate
    # ==========================================================================
    print("\n[5/20] RBI-PineUltimateStrategyTemplate")
    try:
        cls = load_strategy_class("moondev.strategies.rbi.pine_promoted", "PineUltimateStrategyTemplate")
        results = run_strategy("PineUltimateStrategyTemplate", cls, crypto_1h + std_1d)
        all_summaries.append(print_summary("RBI-PineUltimateStrategyTemplate", results))
    except Exception as e:
        print(f"  ERROR al cargar: {e}")
        all_summaries.append({"name": "RBI-PineUltimateStrategyTemplate", "verdict": "ERROR", "error": str(e)})

    # ==========================================================================
    # 6. RBI-PineBestAbcdPattern
    # ==========================================================================
    print("\n[6/20] RBI-PineBestAbcdPattern")
    try:
        cls = load_strategy_class("moondev.strategies.rbi.pine_promoted", "PineBestAbcdPatternStrategy")
        results = run_strategy("PineBestAbcdPattern", cls, crypto_1h + std_1d)
        all_summaries.append(print_summary("RBI-PineBestAbcdPattern", results))
    except Exception as e:
        print(f"  ERROR al cargar: {e}")
        all_summaries.append({"name": "RBI-PineBestAbcdPattern", "verdict": "ERROR", "error": str(e)})

    # ==========================================================================
    # 7. RBI-PineRiskManagement
    # ==========================================================================
    print("\n[7/20] RBI-PineRiskManagement")
    try:
        cls = load_strategy_class("moondev.strategies.rbi.pine_promoted", "PineStrategyCodeExampleRiskManagement")
        results = run_strategy("PineRiskManagement", cls, crypto_1h + std_1d)
        all_summaries.append(print_summary("RBI-PineRiskManagement", results))
    except Exception as e:
        print(f"  ERROR al cargar: {e}")
        all_summaries.append({"name": "RBI-PineRiskManagement", "verdict": "ERROR", "error": str(e)})

    # ==========================================================================
    # 8. RBI-PineTimeLimiting
    # ==========================================================================
    print("\n[8/20] RBI-PineTimeLimiting")
    try:
        cls = load_strategy_class("moondev.strategies.rbi.pine_promoted", "PineStrategyCodeExample2TimeLimiting")
        results = run_strategy("PineTimeLimiting", cls, crypto_1h + std_1d)
        all_summaries.append(print_summary("RBI-PineTimeLimiting", results))
    except Exception as e:
        print(f"  ERROR al cargar: {e}")
        all_summaries.append({"name": "RBI-PineTimeLimiting", "verdict": "ERROR", "error": str(e)})

    # ==========================================================================
    # 9. RBI-PineCombo220EmaBullPower
    # ==========================================================================
    print("\n[9/20] RBI-PineCombo220EmaBullPower")
    try:
        cls = load_strategy_class("moondev.strategies.rbi.pine_promoted", "PineCombo220EmaBullPowerStrategy")
        results = run_strategy("PineCombo220EmaBullPower", cls, crypto_1h + std_1d)
        all_summaries.append(print_summary("RBI-PineCombo220EmaBullPower", results))
    except Exception as e:
        print(f"  ERROR al cargar: {e}")
        all_summaries.append({"name": "RBI-PineCombo220EmaBullPower", "verdict": "ERROR", "error": str(e)})

    # ==========================================================================
    # 10-19. RBI-Moon* strategies
    # ==========================================================================
    moon_strategies = [
        ("RBI-MoonATRChannelSystem",        "MoonATRChannelSystem"),
        ("RBI-MoonBollingerReversion",      "MoonBollingerReversion"),
        ("RBI-MoonHybridMomentumReversion", "MoonHybridMomentumReversion"),
        ("RBI-MoonMACDDivergence",          "MoonMACDDivergence"),
        ("RBI-MoonRSIMeanReversion",        "MoonRSIMeanReversion"),
        ("RBI-MoonSimpleMomentumCross",     "MoonSimpleMomentumCross"),
        ("RBI-MoonStochasticMomentum",      "MoonStochasticMomentum"),
        ("RBI-MoonTrendFollowingMA",        "MoonTrendFollowingMA"),
        ("RBI-MoonVolatilityBreakout",      "MoonVolatilityBreakout"),
        ("RBI-MoonVolumeWeightedBreakout",  "MoonVolumeWeightedBreakout"),
    ]

    for i, (name, cls_name) in enumerate(moon_strategies, 10):
        print(f"\n[{i}/20] {name}")
        try:
            cls = load_strategy_class("moondev.strategies.rbi.moondev_winning_strategies", cls_name)
            results = run_strategy(name, cls, std_1h + std_1d[:2])
            all_summaries.append(print_summary(name, results))
        except Exception as e:
            print(f"  ERROR al cargar: {e}")
            all_summaries.append({"name": name, "verdict": "ERROR", "error": str(e)})

    # ==========================================================================
    # 20. RBI-TrendCapturePro
    # ==========================================================================
    print("\n[20/26] RBI-TrendCapturePro")
    try:
        cls = load_strategy_class("moondev.strategies.rbi.trend_capture_pro", "TrendCapturePro")
        results = run_strategy("TrendCapturePro", cls, std_1h)
        all_summaries.append(print_summary("RBI-TrendCapturePro", results))
    except Exception as e:
        print(f"  ERROR al cargar: {e}")
        all_summaries.append({"name": "RBI-TrendCapturePro", "verdict": "ERROR", "error": str(e)})

    # ==========================================================================
    # 21. RBI-SelectiveMomentumSwing
    # ==========================================================================
    print("\n[21/26] RBI-SelectiveMomentumSwing")
    try:
        cls = load_strategy_class("moondev.strategies.rbi.selective_momentum_swing", "SelectiveMomentumSwing")
        results = run_strategy("SelectiveMomentumSwing", cls, std_1h)
        all_summaries.append(print_summary("RBI-SelectiveMomentumSwing", results))
    except Exception as e:
        print(f"  ERROR al cargar: {e}")
        all_summaries.append({"name": "RBI-SelectiveMomentumSwing", "verdict": "ERROR", "error": str(e)})

    # ==========================================================================
    # 22. RBI-DivergenceVolatilityEnhanced
    # ==========================================================================
    print("\n[22/26] RBI-DivergenceVolatilityEnhanced")
    try:
        cls = load_strategy_class("moondev.strategies.rbi.divergence_volatility_enhanced", "DivergenceVolatilityEnhanced")
        results = run_strategy("DivergenceVolatilityEnhanced", cls, std_1h)
        all_summaries.append(print_summary("RBI-DivergenceVolatilityEnhanced", results))
    except Exception as e:
        print(f"  ERROR al cargar: {e}")
        all_summaries.append({"name": "RBI-DivergenceVolatilityEnhanced", "verdict": "ERROR", "error": str(e)})

    # ==========================================================================
    # 23. RBI-OrderBookImbalance (factory)
    # ==========================================================================
    print("\n[23/26] RBI-OrderBookImbalance")
    try:
        cls = load_strategy_factory(
            "moondev.strategies.rbi.institutional_strategies",
            "make_orderbook_imbalance_strategy",
            coin="BTC"
        )
        results = run_strategy("OrderBookImbalance", cls, crypto_1h + [(s, "1h", 365) for s in SYMBOLS_STOCKS])
        all_summaries.append(print_summary("RBI-OrderBookImbalance", results))
    except Exception as e:
        print(f"  ERROR al cargar: {e}")
        all_summaries.append({"name": "RBI-OrderBookImbalance", "verdict": "ERROR", "error": str(e)})

    # ==========================================================================
    # 24. RBI-LiquidationCascade (factory)
    # ==========================================================================
    print("\n[24/26] RBI-LiquidationCascade")
    try:
        cls = load_strategy_factory(
            "moondev.strategies.rbi.institutional_strategies",
            "make_liquidation_cascade_strategy",
            coin="BTC"
        )
        results = run_strategy("LiquidationCascade", cls, crypto_1h + [(s, "1h", 365) for s in SYMBOLS_STOCKS])
        all_summaries.append(print_summary("RBI-LiquidationCascade", results))
    except Exception as e:
        print(f"  ERROR al cargar: {e}")
        all_summaries.append({"name": "RBI-LiquidationCascade", "verdict": "ERROR", "error": str(e)})

    # ==========================================================================
    # 25. RBI-HeatMapRotation (factory)
    # ==========================================================================
    print("\n[25/26] RBI-HeatMapRotation")
    try:
        cls = load_strategy_factory(
            "moondev.strategies.rbi.institutional_strategies",
            "make_heatmap_rotation_strategy",
            base_asset="BTC-USD"
        )
        results = run_strategy("HeatMapRotation", cls, crypto_1h + [(s, "1h", 365) for s in SYMBOLS_STOCKS])
        all_summaries.append(print_summary("RBI-HeatMapRotation", results))
    except Exception as e:
        print(f"  ERROR al cargar: {e}")
        all_summaries.append({"name": "RBI-HeatMapRotation", "verdict": "ERROR", "error": str(e)})

    # ==========================================================================
    # 26. Macro strategies (VIX, DXY, YieldCurve) - solo stocks/ETFs
    # ==========================================================================
    macro_symbols = [(s, "1d", 1825) for s in ["SPY", "QQQ", "AAPL", "NVDA", "MSFT"]]

    print("\n[26a/26] RBI-VIXFearMeanReversion")
    try:
        cls = load_strategy_factory(
            "moondev.strategies.rbi.macro_strategies",
            "make_vix_fear_strategy",
        )
        results = run_strategy("VIXFearMeanReversion", cls, macro_symbols)
        all_summaries.append(print_summary("RBI-VIXFearMeanReversion", results))
    except Exception as e:
        print(f"  ERROR: {e}")
        all_summaries.append({"name": "RBI-VIXFearMeanReversion", "verdict": "ERROR", "error": str(e)})

    print("\n[26b/26] RBI-DXYForexRotation")
    try:
        cls = load_strategy_factory(
            "moondev.strategies.rbi.macro_strategies",
            "make_dxy_forex_strategy",
            mode="long"
        )
        results = run_strategy("DXYForexRotation", cls, macro_symbols
                               + [(s, "1d", 1825) for s in ["EURUSD", "USDJPY"]])
        all_summaries.append(print_summary("RBI-DXYForexRotation", results))
    except Exception as e:
        print(f"  ERROR: {e}")
        all_summaries.append({"name": "RBI-DXYForexRotation", "verdict": "ERROR", "error": str(e)})

    print("\n[26c/26] RBI-YieldCurveSignal")
    try:
        cls = load_strategy_factory(
            "moondev.strategies.rbi.macro_strategies",
            "make_yield_curve_strategy",
        )
        results = run_strategy("YieldCurveSignal", cls, macro_symbols)
        all_summaries.append(print_summary("RBI-YieldCurveSignal", results))
    except Exception as e:
        print(f"  ERROR: {e}")
        all_summaries.append({"name": "RBI-YieldCurveSignal", "verdict": "ERROR", "error": str(e)})

    # ==========================================================================
    # 27. PairsBTCETH (4h)
    # ==========================================================================
    print("\n[27/27] PairsBTCETH")
    try:
        cls = load_strategy_class("moondev.strategies.pairs_btceth", "PairsBTCETH")
        # Testear en 4h BTC (design target) y 1h BTC (alternativo)
        results = run_strategy("PairsBTCETH", cls, [
            ("BTC", "4h", 730),
            ("BTC", "1h", 365),
            ("ETH", "4h", 730),
        ])
        all_summaries.append(print_summary("PairsBTCETH", results))
    except Exception as e:
        print(f"  ERROR al cargar: {e}")
        all_summaries.append({"name": "PairsBTCETH", "verdict": "ERROR", "error": str(e)})

    # ==========================================================================
    # TABLA FINAL
    # ==========================================================================
    print("\n" + "=" * 70)
    print("  TABLA FINAL -- Resultado por estrategia")
    print("=" * 70)
    print(f"{'Estrategia':<42} {'PASS':>5} {'Total':>6}  {'Mejor activo':<35}  Veredicto")
    print("-" * 100)

    pass_strategies = []
    for s in all_summaries:
        passing = s.get("passing", 0)
        total = s.get("total", 0)
        best_str = s.get("best", "N/A")
        verdict = s.get("verdict", "ERROR")
        name = s["name"]
        marker = " <-- PASS" if verdict == "VIABLE" else (" <<" if verdict == "SELECTIVO" else "")
        print(f"{name:<42} {passing:>5} {total:>6}  {best_str:<35}  {verdict}{marker}")
        if verdict in ("VIABLE", "SELECTIVO"):
            pass_strategies.append(name)

    print("-" * 100)
    print(f"\nEstrategias con potencial ({len(pass_strategies)}): {', '.join(pass_strategies) if pass_strategies else 'ninguna'}")

    # Guardar JSON
    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    out_file = results_dir / f"laboratory_backtest_{ts}.json"
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(all_summaries, f, indent=2, default=str)
    print(f"\nResultados completos guardados: {out_file}")

    return all_summaries


if __name__ == "__main__":
    main()
