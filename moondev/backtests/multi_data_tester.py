"""
multi_data_tester.py — Corre cualquier estrategia contra 25 activos.

Usa criterios y config centralizados en moondev.config y moondev.backtests.criteria.
Uso:
    uv run python moondev/backtests/multi_data_tester.py <strategy_file.py> <ClassName>

Ejemplo:
    uv run python moondev/backtests/multi_data_tester.py moondev/strategies/bollinger_altcoin.py BollingerAltcoin

Output:
    Tabla con Return%, Sharpe, Sortino, MaxDD%, Trades, WinRate% para cada activo.
    Veredicto global al final (VIABLE / SELECTIVO / NO VIABLE).
"""
import sys
import importlib.util
import warnings
import json
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from backtesting import Backtest

# Fetcher unificado y config/criterios moondev
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from moondev.data.data_fetcher import get_ohlcv, HL_CRYPTO, STOCKS as _STOCKS, FOREX as _FOREX
from moondev.config import (
    BACKTEST_COMMISSION,
    BACKTEST_SLIPPAGE_PCT,
    BACKTEST_DEFAULT_PERIOD,
    BACKTEST_DEFAULT_INTERVAL,
    BACKTEST_MIN_BARS,
    PASS_SHARPE,
    PASS_MAX_DD_PCT,
    PASS_MIN_TRADES,
    PASS_MIN_WINRATE_PCT,
)
from moondev.backtests.criteria import verdict as criteria_verdict, global_verdict_label, is_valid_sample

# Silenciar warnings no críticos
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# ── Data sources (25 activos: crypto + stocks + forex) ────────────────────────
CRYPTO = HL_CRYPTO[:10]  # BTC, ETH, SOL, BNB, AVAX, LINK, DOT, ADA, DOGE, MATIC
STOCKS = _STOCKS
FOREX  = _FOREX
ALL_SYMBOLS = CRYPTO + STOCKS + FOREX  # 25 total

# Commission efectiva (config + proxy slippage)
COMMISSION = BACKTEST_COMMISSION + (BACKTEST_SLIPPAGE_PCT / 100.0) if BACKTEST_SLIPPAGE_PCT else BACKTEST_COMMISSION
DEFAULT_PERIOD = BACKTEST_DEFAULT_PERIOD
DEFAULT_INTERVAL = BACKTEST_DEFAULT_INTERVAL


@dataclass
class SymbolResult:
    symbol: str
    ret_pct: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    max_dd: float = 0.0
    trades: int = 0
    win_rate: float = 0.0
    n_bars: int = 0
    error: Optional[str] = None

    @property
    def verdict(self) -> str:
        return criteria_verdict(self)


def load_strategy_class(filepath: str, classname: str):
    """Importa dinámicamente la clase de estrategia desde un archivo .py.
    Añade automáticamente src/ al path si el archivo viene del ecosistema RBI."""
    # Inyectar src/ para estrategias RBI que importan 'from rbi.strategies...'
    src_dir = str(Path(filepath).resolve().parent)
    while src_dir and not src_dir.endswith("src"):
        parent = str(Path(src_dir).parent)
        if parent == src_dir:
            break
        src_dir = parent
    if src_dir.endswith("src") and src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    spec = importlib.util.spec_from_file_location("_strategy_module", filepath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, classname)


def fetch_data(symbol: str, period: str, interval: str) -> Optional[pd.DataFrame]:
    """Descarga OHLCV via data_fetcher (HL para crypto, yfinance para stocks/forex)."""
    # Convertir period string a días aproximados
    _period_to_days = {
        "1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
        "1y": 365, "2y": 730, "5y": 1825,
    }
    days = _period_to_days.get(period, 365)
    try:
        df = get_ohlcv(symbol, interval=interval, days=days)
        if df is None or len(df) < 50:
            return None
        # Asegurar columnas con mayúsculas (backtesting.py las requiere así)
        if "open" in df.columns:
            df.columns = [c.capitalize() for c in df.columns]
        return df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    except Exception:
        return None


def run_single(strategy_cls, symbol: str, period: str, interval: str) -> SymbolResult:
    """Ejecuta el backtest para un símbolo y retorna SymbolResult."""
    result = SymbolResult(symbol=symbol)
    df = fetch_data(symbol, period, interval)
    if df is None:
        result.error = "Sin datos"
        return result
    result.n_bars = len(df)
    try:
        max_price = float(df["Close"].max())
        cash = max(10_000, max_price * 3)
        bt = Backtest(df, strategy_cls, cash=cash, commission=COMMISSION,
                      exclusive_orders=True, finalize_trades=True)
        stats = bt.run()
        result.ret_pct  = float(stats["Return [%]"])
        result.sharpe   = float(stats["Sharpe Ratio"]) if pd.notna(stats["Sharpe Ratio"]) else 0.0
        result.max_dd   = float(stats["Max. Drawdown [%]"])
        result.trades   = int(stats["# Trades"])
        result.win_rate = float(stats["Win Rate [%]"]) if pd.notna(stats["Win Rate [%]"]) else 0.0
        _sr = stats.get("Sortino Ratio")
        result.sortino = float(_sr) if _sr is not None and pd.notna(_sr) else 0.0
        _cr = stats.get("Calmar Ratio")
        result.calmar  = float(_cr) if _cr is not None and pd.notna(_cr) else 0.0
    except Exception as e:
        result.error = str(e)[:60]
    return result


def print_table(results: list[SymbolResult], strategy_name: str,
                period: str, interval: str) -> None:
    """Imprime tabla formateada y veredicto global."""
    # Header (solo ASCII para evitar problemas de codificación en Windows)
    print()
    print("+" + "-" * 78 + "+")
    print(f"|  BACKTEST ARCHITECT - {strategy_name:<54}|")
    print(f"|  Interval: {interval:<6} | Period: {period:<6} | Data sources: {len(results):<22}|")
    print("+" + "-" * 78 + "+")
    print()

    # Columnas
    header = f"{'Symbol':<14} {'Return%':>8} {'Sharpe':>7} {'MaxDD%':>8} {'Trades':>7} {'WinRate%':>9}   Veredicto"
    print(header)
    print("-" * 78)

    passing = 0
    best = max((r for r in results if not r.error), key=lambda r: r.sharpe, default=None)
    worst = min((r for r in results if not r.error), key=lambda r: r.ret_pct, default=None)

    for r in results:
        if r.error:
            print(f"{r.symbol:<14} {'-':>8} {'-':>7} {'-':>8} {'-':>7} {'-':>9}   ERROR: {r.error}")
            continue
        v = r.verdict
        if "PASS" in v:
            passing += 1
        print(
            f"{r.symbol:<14} {r.ret_pct:>+8.1f}% {r.sharpe:>7.2f} "
            f"{r.max_dd:>+8.1f}% {r.trades:>7d} {r.win_rate:>8.1f}%   {v}"
        )

    print("-" * 78)

    # Resumen (criterios desde moondev.config)
    valid = [r for r in results if not r.error]
    total = len(valid)
    pct_pass = (passing / total * 100) if total else 0
    print(
        f"\nRESUMEN: {passing}/{total} activos pasan criterios "
        f"(Sharpe>={PASS_SHARPE}, DD>={PASS_MAX_DD_PCT}%, Trades>={PASS_MIN_TRADES}, WR>={PASS_MIN_WINRATE_PCT}%)"
    )
    if best:
        print(f"MEJOR:   {best.symbol} (Sharpe {best.sharpe:.2f}, Sortino {best.sortino:.2f}, Return {best.ret_pct:+.1f}%)")
    if worst:
        print(f"PEOR:    {worst.symbol} (Return {worst.ret_pct:+.1f}%)")

    print(f"\nVEREDICTO GLOBAL: {global_verdict_label(pct_pass)} ({pct_pass:.0f}% de activos pasan)\n")


def save_results(results: list[SymbolResult], strategy_name: str,
                 period: str, interval: str) -> None:
    """Guarda resultados detallados en JSON dentro de results/ (criterios desde config)."""
    from moondev.backtests.criteria import global_verdict

    valid = [r for r in results if not r.error]
    total = len(valid)
    passing = sum(1 for r in valid if criteria_verdict(r) == "PASS")
    best = max(valid, key=lambda r: r.sharpe, default=None)
    worst = min(valid, key=lambda r: r.ret_pct, default=None)
    pct_pass = (passing / total * 100) if total else 0.0
    global_v = global_verdict(pct_pass)

    payload = {
        "strategy": strategy_name,
        "period": period,
        "interval": interval,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "config": {"min_bars": BACKTEST_MIN_BARS},
        "symbols": [
            {
                "symbol": r.symbol,
                "return_pct": r.ret_pct if not r.error else None,
                "sharpe": r.sharpe if not r.error else None,
                "sortino": r.sortino if not r.error else None,
                "calmar": r.calmar if not r.error else None,
                "max_dd": r.max_dd if not r.error else None,
                "trades": r.trades if not r.error else None,
                "win_rate": r.win_rate if not r.error else None,
                "n_bars": r.n_bars if not r.error else None,
                "verdict": r.verdict,
                "error": r.error,
            }
            for r in results
        ],
        "summary": {
            "passing": passing,
            "total_valid": total,
            "pct_pass": pct_pass,
            "global_verdict": global_v,
            "best_symbol": best.symbol if best else None,
            "best_sharpe": best.sharpe if best else None,
            "best_sortino": best.sortino if best else None,
            "best_return_pct": best.ret_pct if best else None,
            "worst_symbol": worst.symbol if worst else None,
            "worst_return_pct": worst.ret_pct if worst else None,
        },
    }

    results_dir = Path(__file__).resolve().parents[2] / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"multi_{strategy_name}_{period}_{interval}_{timestamp}.json"
    out_path = results_dir / filename
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def main():
    if len(sys.argv) < 3:
        print("Uso: uv run python moondev/backtests/multi_data_tester.py <strategy.py> <ClassName>")
        print("     [--symbols BTC-USD,ETH-USD]  (opcional, subset)")
        print("     [--interval 1h]              (opcional, default 1h)")
        print("     [--period 1y]                (opcional, default 1y)")
        print("     [--optimize-dd]              (opcional, busca mejores params DD tras el test)")
        sys.exit(1)

    filepath  = sys.argv[1]
    classname = sys.argv[2]

    # Opciones extra
    interval     = DEFAULT_INTERVAL
    period       = DEFAULT_PERIOD
    symbols      = ALL_SYMBOLS
    optimize_dd  = False

    for i, arg in enumerate(sys.argv[3:], 3):
        if arg == "--interval" and i + 1 < len(sys.argv):
            interval = sys.argv[i + 1]
        elif arg == "--period" and i + 1 < len(sys.argv):
            period = sys.argv[i + 1]
        elif arg == "--symbols" and i + 1 < len(sys.argv):
            symbols = sys.argv[i + 1].split(",")
        elif arg == "--optimize-dd":
            optimize_dd = True

    print(f"\nCargando {classname} desde {filepath}...")
    strategy_cls = load_strategy_class(filepath, classname)
    print(f"Corriendo contra {len(symbols)} activos ({interval}, {period})...")
    print("(esto puede tardar 1-3 minutos)")

    results = []
    for i, symbol in enumerate(symbols, 1):
        print(f"  [{i:>2}/{len(symbols)}] {symbol:<14}", end="\r")
        r = run_single(strategy_cls, symbol, period, interval)
        results.append(r)

    print_table(results, classname, period, interval)
    save_results(results, classname, period, interval)

    # ── Fase DD Optimizer (opcional) ─────────────────────────────────────────
    if optimize_dd:
        print("\n" + "=" * 80)
        print("  FASE 2: DD OPTIMIZER — buscando mejores parametros de drawdown reduction")
        print("=" * 80)
        from moondev.backtests.dd_optimizer import (
            run_baseline, run_dd_optimize,
            print_comparison_table, print_best_params, save_results_json,
            fetch_data,
        )
        # Convertir símbolos al formato del data_fetcher (HL usa BTC, no BTC-USD)
        _hl_fmt = {s.replace("-USD","").replace("/USDT","") for s in symbols
                   if any(c in s for c in ["-","/"]) }
        dd_symbols = [s.replace("-USD","").replace("/USDT","") for s in symbols
                      if s in CRYPTO + [s.replace("-USD","") for s in CRYPTO]]
        # Fallback: usar los mismos símbolos si no hay traducción
        if not dd_symbols:
            dd_symbols = [s.split("-")[0] for s in symbols]

        dd_results = []
        for i, sym in enumerate(dd_symbols[:10], 1):  # max 10 para no tardar demasiado
            print(f"  [{i:>2}/{len(dd_symbols[:10])}] {sym:<12} baseline + DD optimize...", end="\r")
            df = fetch_data(sym, interval, period)
            if df is None:
                dd_results.append({"symbol": sym, "base": {"error": "no data"}, "opt": {"error": "no data"}})
                continue
            base = run_baseline(strategy_cls, df)
            opt  = run_dd_optimize(strategy_cls, df)
            dd_results.append({"symbol": sym, "base": base, "opt": opt})

        print_comparison_table(dd_results, classname, interval, period)
        print_best_params(dd_results)
        out = save_results_json(dd_results, classname, interval, period)
        print(f"\n  DD results guardados: {out.name}")


if __name__ == "__main__":
    main()
