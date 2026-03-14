"""
dd_optimizer.py — Testea parámetros de reducción de drawdown en cualquier estrategia.

Envuelve dinámicamente la clase Strategy con una capa DD que intercepta self.buy()
para aplicar: ATR sizing, ATR stops/TP, filtro de régimen SMA200 y circuit breaker
de volatilidad. Usa bt.optimize() para encontrar la combinación óptima por Calmar Ratio.

Uso standalone:
    uv run python moondev/backtests/dd_optimizer.py <strategy.py> <ClassName>
    uv run python moondev/backtests/dd_optimizer.py <strategy.py> <ClassName> --multi
    uv run python moondev/backtests/dd_optimizer.py <strategy.py> <ClassName> --symbol BTC,ETH
    uv run python moondev/backtests/dd_optimizer.py <strategy.py> <ClassName> --interval 4h --period 2y

Integración con multi_data_tester.py:
    uv run python moondev/backtests/multi_data_tester.py <strategy.py> <ClassName> --optimize-dd

Output:
    Tabla: Baseline vs DD-Optimizado por activo (Return, DD, Calmar, delta)
    Mejores parámetros DD encontrados por símbolo y globales
    JSON guardado en results/dd_opt_<strategy>_<ts>.json
"""
import sys
import warnings
import json
import importlib.util
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backtesting import Backtest
import pandas_ta as ta

from moondev.data.data_fetcher import get_ohlcv, HL_CRYPTO
from moondev.config import (
    BACKTEST_COMMISSION, BACKTEST_SLIPPAGE_PCT,
    PASS_MAX_DD_PCT, CAUTION_MAX_DD_PCT,
    TARGET_RETURN,
)

warnings.filterwarnings("ignore")

COMMISSION = BACKTEST_COMMISSION + (BACKTEST_SLIPPAGE_PCT / 100.0) if BACKTEST_SLIPPAGE_PCT else BACKTEST_COMMISSION

# ── Grid de parámetros DD ─────────────────────────────────────────────────────
# 2 × 3 × 2 × 2 × 2 = 48 combinaciones (~2-4s por símbolo en bt.optimize)
DD_GRID = dict(
    dd_risk_pct      = [0.01, 0.02],       # % equity arriesgado por trade
    dd_atr_sl_mult   = [2.0, 2.5, 3.0],   # ATR × mult = distancia SL
    dd_atr_tp_mult   = [2.5, 3.0],        # ATR × mult = distancia TP
    dd_regime_filter = [False, True],      # True = solo operar sobre SMA200
    dd_vol_mult      = [0.0, 2.0],        # circuit breaker (0=desactivado)
)

TARGET_CALMAR = TARGET_RETURN / abs(PASS_MAX_DD_PCT)  # 50/20 = 2.5


# ── Wrapper factory ───────────────────────────────────────────────────────────

def make_dd_strategy(base_cls):
    """
    Devuelve una nueva clase que hereda de base_cls con capa DD inyectada.

    Comportamiento:
    - init(): añade indicadores _dd_atr (ATR-14) y _dd_sma200 antes de super().init()
    - next(): aplica filtros de régimen y volatilidad, luego parchea self.buy()
      para que cualquier llamada de la estrategia base use ATR sizing + ATR stops.

    Los parámetros dd_* son optimizables via bt.optimize().
    """
    class DDWrapped(base_cls):
        # Parámetros DD — valores por defecto razonables
        dd_risk_pct      = 0.02
        dd_atr_sl_mult   = 2.5
        dd_atr_tp_mult   = 3.0
        dd_regime_filter = False
        dd_vol_mult      = 0.0

        def init(self):
            # ATR-14 para sizing y stops
            self._dd_atr = self.I(
                lambda h, l, c: (
                    ta.atr(pd.Series(h), pd.Series(l), pd.Series(c), length=14)
                    .bfill().fillna(0).values
                ),
                self.data.High, self.data.Low, self.data.Close,
            )
            # SMA200 para régimen
            self._dd_sma200 = self.I(
                lambda c: pd.Series(c).rolling(200).mean().bfill().fillna(0).values,
                self.data.Close,
            )
            super().init()

        def next(self):
            # ── Filtro de régimen (solo si hay señal y no hay posición) ─────
            if self.dd_regime_filter and not self.position:
                price   = float(self.data.Close[-1])
                sma200  = float(self._dd_sma200[-1])
                if sma200 > 0 and price < sma200:
                    return   # No operar por debajo de SMA200

            # ── Circuit breaker de volatilidad ──────────────────────────────
            if self.dd_vol_mult > 0 and not self.position:
                atr14  = float(self._dd_atr[-1])
                hist   = list(self._dd_atr[-84:]) if len(self._dd_atr) >= 84 else list(self._dd_atr)
                avg84  = float(np.mean(hist)) if hist else atr14
                if avg84 > 0 and atr14 > avg84 * self.dd_vol_mult:
                    return   # Volatilidad extrema → skip

            # ── Interceptar buy() para ATR sizing y stops ───────────────────
            _orig_buy = self.buy

            def _dd_buy(size=None, sl=None, tp=None, **kw):
                atr_val = float(self._dd_atr[-1])
                price   = float(self.data.Close[-1])

                if atr_val > 0 and price > 0:
                    # ATR position sizing: 2% equity / (SL_distance * price)
                    stop_dist = atr_val * self.dd_atr_sl_mult
                    risk_amt  = float(self.equity) * self.dd_risk_pct
                    size = float(np.clip(risk_amt / (stop_dist * price), 0.05, 0.5))

                    # ATR stops — no sobreescribir si la estrategia los fijó
                    if sl is None:
                        sl = price - atr_val * self.dd_atr_sl_mult
                    if tp is None:
                        tp = price + atr_val * self.dd_atr_tp_mult

                return _orig_buy(size=size, sl=sl, tp=tp, **kw)

            self.buy = _dd_buy
            try:
                super().next()
            finally:
                self.buy = _orig_buy

    DDWrapped.__name__    = f"DD_{base_cls.__name__}"
    DDWrapped.__qualname__ = f"DD_{base_cls.__name__}"
    return DDWrapped


# ── Métricas ──────────────────────────────────────────────────────────────────

def calmar_score(stats) -> float:
    """Calmar penalizado: Return% / |MaxDD%| con penalización progresiva si DD > 35%."""
    ret = float(stats.get("Return [%]", 0) or 0)
    dd  = abs(float(stats.get("Max. Drawdown [%]", 1) or 1))
    if ret <= 0 or dd < 1.0:
        return ret
    c = ret / dd
    caution = abs(CAUTION_MAX_DD_PCT)
    if dd > caution:
        excess = (dd - caution) / caution
        c *= max(0.2, 1.0 - excess)
    return c


def _maximize_fn(s):
    """Función de maximización para bt.optimize(): penaliza si hay < 10 trades."""
    if int(s.get("# Trades", 0) or 0) < 10:
        return -999.0
    return calmar_score(s)


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_strategy_class(filepath: str, classname: str):
    spec = importlib.util.spec_from_file_location("_strat_module", filepath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, classname)


def fetch_data(symbol: str, interval: str = "1h", period: str = "1y") -> Optional[pd.DataFrame]:
    _days = {"1d":1,"5d":5,"1mo":30,"3mo":90,"6mo":180,"1y":365,"2y":730,"5y":1825}
    days = _days.get(period, 365)
    try:
        df = get_ohlcv(symbol, interval=interval, days=days)
        if df is None or len(df) < 100:
            return None
        if "open" in df.columns:
            df.columns = [c.capitalize() for c in df.columns]
        return df[["Open","High","Low","Close","Volume"]].dropna()
    except Exception:
        return None


def _run_bt(strategy_cls, df: pd.DataFrame) -> dict:
    """Ejecuta un backtest simple sin optimización."""
    cash = max(10_000, float(df["Close"].max()) * 3)
    bt   = Backtest(df, strategy_cls, cash=cash, commission=COMMISSION,
                    exclusive_orders=True, finalize_trades=True)
    s    = bt.run()
    return {
        "ret":    float(s["Return [%]"]),
        "dd":     float(s["Max. Drawdown [%]"]),
        "sharpe": float(s["Sharpe Ratio"] or 0),
        "trades": int(s["# Trades"]),
        "calmar": calmar_score(s),
    }


# ── Funciones principales ─────────────────────────────────────────────────────

def run_baseline(strategy_cls, df: pd.DataFrame) -> dict:
    """Baseline: estrategia original sin capa DD."""
    try:
        return _run_bt(strategy_cls, df)
    except Exception as e:
        return {"error": str(e)[:80]}


def run_dd_optimize(strategy_cls, df: pd.DataFrame) -> dict:
    """
    Optimiza los parámetros DD sobre df via bt.optimize(maximize=calmar_score).
    También guarda los mejores parámetros encontrados.
    """
    dd_cls = make_dd_strategy(strategy_cls)
    try:
        cash = max(10_000, float(df["Close"].max()) * 3)
        bt   = Backtest(df, dd_cls, cash=cash, commission=COMMISSION,
                        exclusive_orders=True, finalize_trades=True)
        opt  = bt.optimize(**DD_GRID, maximize=_maximize_fn, max_tries=300)
        best_params = {k: getattr(opt._strategy, k) for k in DD_GRID}
        return {
            "ret":    float(opt["Return [%]"]),
            "dd":     float(opt["Max. Drawdown [%]"]),
            "sharpe": float(opt["Sharpe Ratio"] or 0),
            "trades": int(opt["# Trades"]),
            "calmar": calmar_score(opt),
            "params": best_params,
        }
    except Exception as e:
        return {"error": str(e)[:80]}


def run_dd_fixed(strategy_cls, df: pd.DataFrame, params: dict) -> dict:
    """Corre la estrategia con parámetros DD fijos (no optimiza, más rápido)."""
    dd_cls = make_dd_strategy(strategy_cls)
    # Fijar parámetros como atributos de clase
    for k, v in params.items():
        setattr(dd_cls, k, v)
    try:
        return _run_bt(dd_cls, df)
    except Exception as e:
        return {"error": str(e)[:80]}


# ── Output ────────────────────────────────────────────────────────────────────

def _delta_str(val: float, higher_better: bool = True) -> str:
    sign = "+" if val > 0 else ""
    mark = ""
    if higher_better and val > 0: mark = " ^"
    if higher_better and val < 0: mark = " v"
    if not higher_better and val < 0: mark = " ^"
    if not higher_better and val > 0: mark = " v"
    return f"({sign}{val:.2f}{mark})"


def print_comparison_table(all_results: list[dict], strategy_name: str,
                            interval: str, period: str) -> None:
    W = 100
    valid = [r for r in all_results if "error" not in r["base"] and "error" not in r["opt"]]

    print()
    print("+" + "=" * W + "+")
    print(f"|  DD OPTIMIZER - {strategy_name:<{W-18}}|")
    print(f"|  Interval: {interval:<6} | Period: {period:<6} | Grid: 48 combos | Symbols: {len(all_results):<{W-60}}|")
    print("+" + "=" * W + "+")
    print()

    # --- Tabla BASE (estrategia original) ---
    print("  BASELINE (estrategia original)")
    print(f"  {'Symbol':<12} {'Return%':>9} {'Sharpe':>8} {'MaxDD%':>9} {'Trades':>8} {'Calmar':>8}   Veredicto")
    print("  " + "-" * (W - 2))

    for r in all_results:
        sym  = r["symbol"]
        base = r["base"]
        if "error" in base:
            print(f"  {sym:<12} {'-':>9} {'-':>8} {'-':>9} {'-':>8} {'-':>8}   SIN DATOS")
            continue
        cal = base["calmar"]
        tag = "PASS" if cal > 0 else "FAIL"
        print(
            f"  {sym:<12} {base['ret']:>+8.1f}% {base['sharpe']:>8.2f} "
            f"{base['dd']:>+8.1f}% {base['trades']:>8d} {cal:>8.2f}   {tag}"
        )

    print("  " + "-" * (W - 2))
    if valid:
        avg_ret = np.mean([r["base"]["ret"] for r in valid])
        avg_dd  = np.mean([r["base"]["dd"]  for r in valid])
        avg_cal = np.mean([r["base"]["calmar"] for r in valid])
        print(f"  {'PROMEDIO':<12} {avg_ret:>+8.1f}% {'':>8} {avg_dd:>+8.1f}% {'':>8} {avg_cal:>8.2f}")

    # --- Tabla DD OPTIMIZADO ---
    print()
    print("  DD OPTIMIZADO (con capa de drawdown reduction)")
    print(f"  {'Symbol':<12} {'Return%':>9} {'Sharpe':>8} {'MaxDD%':>9} {'Trades':>8} {'Calmar':>8}   Veredicto")
    print("  " + "-" * (W - 2))

    improvements = 0
    for r in all_results:
        sym = r["symbol"]
        opt = r["opt"]
        base = r["base"]
        if "error" in opt:
            print(f"  {sym:<12} {'-':>9} {'-':>8} {'-':>9} {'-':>8} {'-':>8}   SIN DATOS")
            continue
        cal = opt["calmar"]
        base_cal = base.get("calmar", 0) if "error" not in base else 0
        delta = cal - base_cal
        improved = delta > 0.05
        if improved:
            improvements += 1

        if improved and cal > 0:
            tag = "PASS ^^"
        elif improved:
            tag = "MEJOR"
        elif delta < -0.05:
            tag = "PEOR"
        else:
            tag = "="
        print(
            f"  {sym:<12} {opt['ret']:>+8.1f}% {opt['sharpe']:>8.2f} "
            f"{opt['dd']:>+8.1f}% {opt['trades']:>8d} {cal:>8.2f}   {tag}"
        )

    print("  " + "-" * (W - 2))
    if valid:
        avg_ret = np.mean([r["opt"]["ret"] for r in valid])
        avg_dd  = np.mean([r["opt"]["dd"]  for r in valid])
        avg_cal = np.mean([r["opt"]["calmar"] for r in valid])
        print(f"  {'PROMEDIO':<12} {avg_ret:>+8.1f}% {'':>8} {avg_dd:>+8.1f}% {'':>8} {avg_cal:>8.2f}")

    # --- Tabla DELTA (comparativa) ---
    print()
    print("  COMPARATIVA BASE vs DD")
    print(f"  {'Symbol':<12} {'Calmar BASE':>12} {'Calmar DD':>10} {'Delta':>8} {'DD BASE':>9} {'DD Optim':>9} {'dDD':>7}  Mejor?")
    print("  " + "-" * (W - 2))

    for r in all_results:
        sym = r["symbol"]
        base = r["base"]
        opt = r["opt"]
        if "error" in base or "error" in opt:
            print(f"  {sym:<12} {'':>12} {'':>10} {'':>8} {'':>9} {'':>9} {'':>7}  SIN DATOS")
            continue
        d_cal = opt["calmar"] - base["calmar"]
        d_dd  = abs(opt["dd"]) - abs(base["dd"])
        if d_cal > 0.05:
            tag = "[MEJOR]"
        elif d_cal < -0.05:
            tag = "[PEOR]"
        else:
            tag = "[=]"
        print(
            f"  {sym:<12} {base['calmar']:>12.2f} {opt['calmar']:>10.2f} {d_cal:>+8.2f} "
            f"{base['dd']:>+8.1f}% {opt['dd']:>+8.1f}% {d_dd:>+6.1f}%  {tag}"
        )

    print("  " + "-" * (W - 2))

    # --- Resumen final ---
    print()
    print("+" + "-" * W + "+")
    print(f"|  RESUMEN: {improvements}/{len(valid)} simbolos mejoraron Calmar con capa DD" + " " * (W - 52 - len(str(improvements)) - len(str(len(valid)))) + "|")
    if valid:
        avg_base_cal = np.mean([r["base"]["calmar"] for r in valid])
        avg_opt_cal  = np.mean([r["opt"]["calmar"]  for r in valid])
        avg_base_dd  = np.mean([abs(r["base"]["dd"]) for r in valid])
        avg_opt_dd   = np.mean([abs(r["opt"]["dd"])  for r in valid])
        line1 = f"|  Calmar promedio: {avg_base_cal:.2f} -> {avg_opt_cal:.2f}  (delta: {avg_opt_cal-avg_base_cal:>+.2f})"
        print(f"{line1:<{W+1}}|")
        line2 = f"|  DD promedio:     {avg_base_dd:.1f}% -> {avg_opt_dd:.1f}%  (delta: {avg_opt_dd-avg_base_dd:>+.1f}%)"
        print(f"{line2:<{W+1}}|")
    print("+" + "-" * W + "+")


def print_best_params(all_results: list[dict]) -> None:
    """Muestra parámetros DD más frecuentes entre símbolos que mejoraron."""
    improved = [
        r["opt"]["params"]
        for r in all_results
        if "params" in r.get("opt", {})
        and r["opt"]["calmar"] > r["base"]["calmar"]
    ]

    W = 100
    print()
    print("+" + "-" * W + "+")
    title = f"|  PARAMETROS DD RECOMENDADOS (basado en {len(improved)} simbolos que mejoraron)"
    print(f"{title:<{W+1}}|")
    print("+" + "-" * W + "+")

    if not improved:
        print("|  (ningun simbolo mejoro - la capa DD no beneficia esta estrategia)" + " " * 32 + "|")
        print("+" + "-" * W + "+")
        return

    print(f"  {'Parametro':<24} {'Valor':>8} {'Frecuencia':>12}")
    print("  " + "-" * 50)
    for key in DD_GRID:
        vals = [p[key] for p in improved if key in p]
        if vals:
            most_common, count = Counter(vals).most_common(1)[0]
            pct = count / len(vals) * 100
            print(f"  {key:<24} {str(most_common):>8}   {pct:>5.0f}%")

    print()
    best_line = "  HARDCODE -> " + "  ".join(
        f"{key}={Counter([p[key] for p in improved if key in p]).most_common(1)[0][0]}"
        for key in DD_GRID
    )
    print(best_line)
    print()


def save_results_json(all_results: list[dict], strategy_name: str,
                       interval: str, period: str) -> Path:
    out_dir = Path(__file__).resolve().parents[2] / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"dd_opt_{strategy_name}_{interval}_{ts}.json"
    payload = {
        "strategy": strategy_name,
        "interval": interval,
        "period": period,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dd_grid": {k: v for k, v in DD_GRID.items()},
        "target_calmar": TARGET_CALMAR,
        "results": all_results,
    }
    with out.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    return out


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print("Uso: uv run python moondev/backtests/dd_optimizer.py <strategy.py> <ClassName>")
        print("     [--symbol BTC,ETH,SOL]   (default: BTC,ETH,SOL)")
        print("     [--interval 1h]           (default: 1h)")
        print("     [--period 1y]             (default: 1y)")
        print("     [--multi]                 (10 crypto symbols)")
        sys.exit(1)

    filepath  = sys.argv[1]
    classname = sys.argv[2]

    interval = "1h"
    period   = "1y"
    symbols  = ["BTC", "ETH", "SOL"]

    for i, arg in enumerate(sys.argv[3:], 3):
        if   arg == "--interval" and i + 1 < len(sys.argv): interval = sys.argv[i + 1]
        elif arg == "--period"   and i + 1 < len(sys.argv): period   = sys.argv[i + 1]
        elif arg == "--symbol"   and i + 1 < len(sys.argv): symbols  = sys.argv[i + 1].split(",")
        elif arg == "--multi":  symbols = HL_CRYPTO[:10]

    print(f"\nCargando {classname} desde {filepath}...")
    base_cls = load_strategy_class(filepath, classname)

    print(f"DD Optimizer | {len(symbols)} simbolos | {interval} | {period} | Grid ~48 combinaciones")
    print("(esto puede tardar ~30-60s dependiendo del numero de simbolos)")

    all_results = []
    for i, sym in enumerate(symbols, 1):
        print(f"  [{i:>2}/{len(symbols)}] {sym:<12} baseline...", end="\r")
        df = fetch_data(sym, interval, period)
        if df is None:
            print(f"  [{i:>2}/{len(symbols)}] {sym:<12} SIN DATOS")
            all_results.append({"symbol": sym, "base": {"error": "no data"}, "opt": {"error": "no data"}})
            continue

        base = run_baseline(base_cls, df)

        print(f"  [{i:>2}/{len(symbols)}] {sym:<12} optimizando DD...          ", end="\r")
        opt  = run_dd_optimize(base_cls, df)

        all_results.append({"symbol": sym, "base": base, "opt": opt})

    print_comparison_table(all_results, classname, interval, period)
    print_best_params(all_results)
    out = save_results_json(all_results, classname, interval, period)
    print(f"\n  Guardado: {out.name}\n")


if __name__ == "__main__":
    main()
