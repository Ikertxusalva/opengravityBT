"""
optimization_agent — optimizador de parámetros de estrategias.

Pipeline:
  1. Carga estrategia Python (clase backtesting.py)
  2. Descubre parámetros optimizables (class variables numéricas)
  3. Grid search ±50% en pasos del 25%
  4. Walk-forward validation 70/30 en el mejor resultado
  5. Penaliza overfitting: score = Sharpe_oos / Sharpe_is
  6. Guarda mejores params en DATA_DIR/optimized/<strategy>.json

Uso:
    python moondev/agents/optimization_agent.py <strategy_file.py> <ClassName> [symbol]

Ejemplo:
    python moondev/agents/optimization_agent.py moondev/strategies/volatility_squeeze.py VolatilitySqueeze BTC
"""
from __future__ import annotations

import sys
import json
import time
import itertools
import importlib.util
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

from backtesting import Backtest
import moondev.config as cfg
from moondev.data.data_fetcher import get_ohlcv
from rich.console import Console
from rich.table import Table
from rich.progress import track

console = Console()

# ── Configuración ──────────────────────────────────────────────────────────────
DEFAULT_SYMBOL   = "BTC"
DEFAULT_INTERVAL = cfg.BACKTEST_DEFAULT_INTERVAL
DEFAULT_DAYS     = 365
STEP_PCT         = 0.25     # pasos del grid: ±25%, ±50%
GRID_RANGE       = [-0.5, -0.25, 0.0, 0.25, 0.5]  # variación % sobre default
IS_SPLIT         = 0.70     # 70% in-sample, 30% out-of-sample
MAX_COMBOS       = 200      # límite de combinaciones para no tardar siglos
OVF_PENALTY      = 0.5      # score = sharpe_oos * (1 - penalty * max(0, 1 - ratio))

# Parámetros DD incluidos en el grid conjunto cuando se usa --dd
DD_PARAMS_GRID = {
    "dd_risk_pct":      [0.01, 0.02],
    "dd_atr_sl_mult":   [2.0, 2.5, 3.0],
    "dd_atr_tp_mult":   [2.5, 3.0],
    "dd_regime_filter": [False, True],
    "dd_vol_mult":      [0.0, 2.0],
}

OUTPUT_DIR = cfg.DATA_DIR / "optimized"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ── Carga dinámica de estrategia ───────────────────────────────────────────────
def load_strategy(filepath: str, classname: str):
    spec = importlib.util.spec_from_file_location("_strat", filepath)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, classname)


def discover_params(strategy_cls) -> dict[str, Any]:
    """
    Descubre class variables numéricas (int/float) que sean parámetros
    optimizables. Excluye dunder y strings.
    """
    params = {}
    for key, val in vars(strategy_cls).items():
        if key.startswith("_"):
            continue
        if callable(val):
            continue
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            params[key] = val
    return params


def build_grid(params: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Genera todas las combinaciones del grid ±50% en pasos de 25%.
    Limita a MAX_COMBOS combinaciones aleatorias si se excede.
    """
    keys = list(params.keys())
    value_sets = []
    for k, default in params.items():
        vals = set()
        for pct in GRID_RANGE:
            v = default * (1 + pct)
            # Respetar tipo original
            if isinstance(default, int):
                v = max(1, int(round(v)))
            else:
                v = round(v, 6)
            vals.add(v)
        value_sets.append(sorted(vals))

    all_combos = list(itertools.product(*value_sets))
    if len(all_combos) > MAX_COMBOS:
        rng = np.random.default_rng(42)
        idx = rng.choice(len(all_combos), MAX_COMBOS, replace=False)
        all_combos = [all_combos[i] for i in idx]

    return [dict(zip(keys, combo)) for combo in all_combos]


# ── Ejecución de backtest ──────────────────────────────────────────────────────
def run_backtest(strategy_cls, data: pd.DataFrame, params: dict) -> dict:
    """Corre un backtest con params dados, retorna métricas clave."""
    try:
        # Aplicar params a la clase dinámicamente
        for k, v in params.items():
            setattr(strategy_cls, k, v)

        cash = max(10_000, float(data["Close"].max()) * 3)
        bt = Backtest(data, strategy_cls, cash=cash,
                      commission=cfg.BACKTEST_COMMISSION,
                      exclusive_orders=True, finalize_trades=True)
        stats = bt.run()

        sharpe = float(stats["Sharpe Ratio"]) if pd.notna(stats["Sharpe Ratio"]) else 0.0
        dd     = float(stats["Max. Drawdown [%]"])
        trades = int(stats["# Trades"])
        wr     = float(stats["Win Rate [%]"]) if pd.notna(stats["Win Rate [%]"]) else 0.0
        ret    = float(stats["Return [%]"])
        return {"sharpe": sharpe, "max_dd": dd, "trades": trades,
                "win_rate": wr, "return_pct": ret, "error": None}
    except Exception as e:
        return {"sharpe": -99.0, "max_dd": -100.0, "trades": 0,
                "win_rate": 0.0, "return_pct": -100.0, "error": str(e)[:80]}


# ── Walk-forward validation ────────────────────────────────────────────────────
def walk_forward(strategy_cls, data: pd.DataFrame, params: dict) -> dict:
    """
    Divide datos en IS (70%) y OOS (30%).
    Corre backtest en cada parte con los params dados.
    Retorna métricas IS + OOS + ratio anti-overfitting.
    """
    split = int(len(data) * IS_SPLIT)
    data_is  = data.iloc[:split].copy()
    data_oos = data.iloc[split:].copy()

    if len(data_is) < 100 or len(data_oos) < 50:
        return {"is": {}, "oos": {}, "ratio": 0.0, "score": 0.0}

    metrics_is  = run_backtest(strategy_cls, data_is,  params)
    metrics_oos = run_backtest(strategy_cls, data_oos, params)

    sharpe_is  = metrics_is["sharpe"]
    sharpe_oos = metrics_oos["sharpe"]

    # Ratio OOS/IS: 1.0 = perfecto, <0.5 = overfitting grave
    ratio = (sharpe_oos / sharpe_is) if sharpe_is > 0 else 0.0
    ratio = max(0.0, min(ratio, 2.0))  # clamp

    # Score final penalizado por overfitting
    penalty = max(0.0, 1.0 - ratio) * OVF_PENALTY
    score   = sharpe_oos * (1.0 - penalty)

    return {
        "is":    metrics_is,
        "oos":   metrics_oos,
        "ratio": round(ratio, 3),
        "score": round(score, 4),
    }


# ── Reporte ────────────────────────────────────────────────────────────────────
def print_results(best_params: dict, wf: dict, default_params: dict,
                  strategy_name: str, symbol: str) -> None:
    console.print(f"\n[bold cyan]== OPTIMIZATION AGENT — {strategy_name} @ {symbol} ==[/bold cyan]\n")

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Param",       style="cyan",  width=20)
    table.add_column("Default",     style="white", justify="right")
    table.add_column("Optimizado",  style="green", justify="right")
    table.add_column("Cambio",      style="yellow",justify="right")

    for k in default_params:
        dv  = default_params[k]
        ov  = best_params.get(k, dv)
        pct = ((ov - dv) / dv * 100) if dv else 0
        table.add_row(k, str(dv), str(ov), f"{pct:+.0f}%")
    console.print(table)

    is_m  = wf.get("is",  {})
    oos_m = wf.get("oos", {})
    console.print(f"\n[bold]Walk-Forward Results:[/bold]")
    console.print(f"  IS  (70%): Sharpe={is_m.get('sharpe',0):+.2f}  Return={is_m.get('return_pct',0):+.1f}%  DD={is_m.get('max_dd',0):.1f}%  Trades={is_m.get('trades',0)}")
    console.print(f"  OOS (30%): Sharpe={oos_m.get('sharpe',0):+.2f}  Return={oos_m.get('return_pct',0):+.1f}%  DD={oos_m.get('max_dd',0):.1f}%  Trades={oos_m.get('trades',0)}")
    console.print(f"  Ratio OOS/IS: {wf.get('ratio',0):.2f}  |  Score final: [bold green]{wf.get('score',0):.4f}[/bold green]")

    if wf.get("ratio", 0) >= 0.7:
        console.print("\n[bold green]✓ Sin overfitting significativo (ratio >= 0.7)[/bold green]")
    elif wf.get("ratio", 0) >= 0.4:
        console.print("\n[bold yellow]⚠ Overfitting moderado (ratio 0.4-0.7) — validar más[/bold yellow]")
    else:
        console.print("\n[bold red]✗ Overfitting severo (ratio < 0.4) — NO usar estos params[/bold red]")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 3:
        console.print("[red]Uso: python optimization_agent.py <strategy.py> <ClassName> [symbol] [--dd][/red]")
        console.print("[dim]  --dd  incluye parametros DD (ATR sizing, stops, regime) en el grid[/dim]")
        sys.exit(1)

    filepath    = sys.argv[1]
    classname   = sys.argv[2]
    symbol      = next((sys.argv[i+1] for i, a in enumerate(sys.argv[3:], 3)
                        if not a.startswith("--")), DEFAULT_SYMBOL)
    with_dd     = "--dd" in sys.argv or "--optimize-dd" in sys.argv

    console.print(f"\n[bold]Cargando {classname} desde {filepath}...[/bold]")
    strategy_cls = load_strategy(filepath, classname)

    default_params = discover_params(strategy_cls)

    # Si se activa --dd, envolver con la capa DD y añadir sus params al grid
    if with_dd:
        from moondev.backtests.dd_optimizer import make_dd_strategy
        strategy_cls = make_dd_strategy(strategy_cls)
        # Añadir los params DD al dict de defaults para el grid y el reporte
        dd_defaults = {k: v[len(v)//2] for k, v in DD_PARAMS_GRID.items()}  # valor central
        default_params.update({k: v for k, v in dd_defaults.items()
                                if isinstance(v, (int, float)) and not isinstance(v, bool)})
        console.print(f"[cyan]Modo DD activado:[/cyan] capa de drawdown inyectada en la estrategia")

    if not default_params:
        console.print("[red]No se encontraron parámetros optimizables.[/red]")
        sys.exit(1)

    console.print(f"[cyan]Parámetros descubiertos:[/cyan] {list(default_params.keys())}")

    # Descargar datos
    console.print(f"\n[bold]Descargando datos {symbol} {DEFAULT_INTERVAL} {DEFAULT_DAYS}d...[/bold]")
    df = get_ohlcv(symbol, interval=DEFAULT_INTERVAL, days=DEFAULT_DAYS)
    if df is None or len(df) < 200:
        console.print(f"[red]Sin datos suficientes para {symbol}[/red]")
        sys.exit(1)

    # Capitalizar columnas para backtesting.py
    df.columns = [c.capitalize() for c in df.columns]
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    console.print(f"Datos: {len(df)} barras ({df.index[0]} -> {df.index[-1]})")

    # Grid search — si hay params DD booleanos, añadirlos como combos separados
    grid = build_grid(default_params)
    if with_dd:
        # Añadir también las combinaciones booleanas de dd_regime_filter
        bool_combos = []
        for combo in grid[:MAX_COMBOS // 2]:
            for regime in DD_PARAMS_GRID["dd_regime_filter"]:
                for vol in DD_PARAMS_GRID["dd_vol_mult"]:
                    c = dict(combo)
                    c["dd_regime_filter"] = regime
                    c["dd_vol_mult"] = vol
                    bool_combos.append(c)
        grid = bool_combos[:MAX_COMBOS]

    console.print(f"\n[bold]Grid search: {len(grid)} combinaciones{'  (incl. DD params)' if with_dd else ''}...[/bold]")

    results = []
    for combo in track(grid, description="Optimizando..."):
        m = run_backtest(strategy_cls, df, combo)
        if not m["error"] and m["trades"] >= cfg.CAUTION_MIN_TRADES:
            results.append({"params": combo, "metrics": m})

    if not results:
        console.print("[red]Sin resultados válidos en grid search.[/red]")
        sys.exit(1)

    # Ordenar por Calmar (Return/|DD|) cuando hay capa DD, sino por Sharpe
    if with_dd:
        results.sort(
            key=lambda x: x["metrics"]["return_pct"] / max(abs(x["metrics"]["max_dd"]), 1),
            reverse=True,
        )
        metric_label = "Calmar"
        metric_val   = lambda r: f"{r['metrics']['return_pct'] / max(abs(r['metrics']['max_dd']),1):.2f}"
    else:
        results.sort(key=lambda x: x["metrics"]["sharpe"], reverse=True)
        metric_label = "Sharpe"
        metric_val   = lambda r: f"{r['metrics']['sharpe']:.2f}"

    best = results[0]
    console.print(
        f"\n[green]Mejor combo IS: {metric_label}={metric_val(best)}  "
        f"Return={best['metrics']['return_pct']:+.1f}%  "
        f"DD={best['metrics']['max_dd']:.1f}%  "
        f"Trades={best['metrics']['trades']}[/green]"
    )

    # Walk-forward del mejor
    console.print("\n[bold]Walk-forward validation (70/30)...[/bold]")
    wf = walk_forward(strategy_cls, df, best["params"])

    print_results(best["params"], wf, default_params, classname, symbol)

    # Guardar resultado
    output = {
        "strategy":      classname,
        "symbol":        symbol,
        "interval":      DEFAULT_INTERVAL,
        "days":          DEFAULT_DAYS,
        "generated_at":  datetime.now(timezone.utc).isoformat(),
        "default_params": default_params,
        "best_params":    best["params"],
        "is_metrics":    wf.get("is",  {}),
        "oos_metrics":   wf.get("oos", {}),
        "wf_ratio":      wf.get("ratio", 0),
        "final_score":   wf.get("score", 0),
        "top5_results":  [
            {"params": r["params"], "sharpe": r["metrics"]["sharpe"]}
            for r in results[:5]
        ],
    }

    outfile = OUTPUT_DIR / f"{classname}_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)
    console.print(f"\n[bold green]Guardado en {outfile}[/bold green]")

    return output


if __name__ == "__main__":
    main()
