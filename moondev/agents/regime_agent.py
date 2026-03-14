"""
regime_agent — detector de régimen de mercado + selector de estrategia.

Detecta el régimen actual del mercado (BULL / BEAR / SIDEWAYS) usando:
  - Tendencia: SMA20 vs SMA50 vs SMA200
  - Volatilidad: ATR rolling vs media histórica
  - Momentum: RSI14 + ROC20
  - Volumen: ratio vs media 20 barras

Luego consulta los resultados de multi-test en results/multi_*.json
y selecciona la estrategia con mejor Sharpe para el régimen detectado.

Uso:
    python moondev/agents/regime_agent.py [symbol] [interval]

Ejemplo:
    python moondev/agents/regime_agent.py BTC 1h
"""
from __future__ import annotations

import sys
import json
import glob
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import pandas_ta as ta
import warnings
warnings.filterwarnings("ignore")

import moondev.config as cfg
from moondev.data.data_fetcher import get_ohlcv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

# ── Config ─────────────────────────────────────────────────────────────────────
DEFAULT_SYMBOL   = "BTC"
DEFAULT_INTERVAL = "1h"
DEFAULT_DAYS     = 90          # datos para detectar régimen
RESULTS_DIR      = Path("results")

# Umbrales de régimen
BULL_RSI_MIN    = 55           # RSI > 55 confirma bull
BEAR_RSI_MAX    = 45           # RSI < 45 confirma bear
BULL_TREND_BARS = 10           # SMA20 > SMA50 al menos N barras seguidas
VOL_HIGH_MULT   = 1.5          # ATR > 1.5x media = alta volatilidad
VOL_LOW_MULT    = 0.7          # ATR < 0.7x media = compresión


# ── Detector de régimen ────────────────────────────────────────────────────────
class MarketRegime:
    BULL    = "BULL"
    BEAR    = "BEAR"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOL = "HIGH_VOLATILITY"


def detect_regime(df: pd.DataFrame) -> dict:
    """
    Analiza OHLCV y retorna régimen actual con score de confianza.

    Retorna:
        {
            "regime": "BULL" | "BEAR" | "SIDEWAYS" | "HIGH_VOLATILITY",
            "confidence": 0-100,
            "signals": {...},
            "description": str,
        }
    """
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    # ── Indicadores ──────────────────────────────────────────────────────────
    sma20  = ta.sma(close, 20)
    sma50  = ta.sma(close, 50)
    sma200 = ta.sma(close, 200)
    rsi    = ta.rsi(close, 14)
    atr    = ta.atr(high, low, close, 14)
    roc    = ta.roc(close, 20)   # Rate of Change 20

    # Usar últimos valores
    last_close  = float(close.iloc[-1])
    last_sma20  = float(sma20.iloc[-1])  if pd.notna(sma20.iloc[-1])  else last_close
    last_sma50  = float(sma50.iloc[-1])  if pd.notna(sma50.iloc[-1])  else last_close
    last_sma200 = float(sma200.iloc[-1]) if pd.notna(sma200.iloc[-1]) else last_close
    last_rsi    = float(rsi.iloc[-1])    if pd.notna(rsi.iloc[-1])    else 50.0
    last_atr    = float(atr.iloc[-1])    if pd.notna(atr.iloc[-1])    else 0.0
    last_roc    = float(roc.iloc[-1])    if pd.notna(roc.iloc[-1])    else 0.0

    # ATR relativo al precio
    atr_pct     = (last_atr / last_close * 100) if last_close else 0
    atr_mean    = float(atr.rolling(50).mean().iloc[-1]) if len(atr) > 50 else last_atr
    atr_ratio   = (last_atr / atr_mean) if atr_mean > 0 else 1.0

    # SMA20 > SMA50 en las últimas N barras (tendencia sostenida)
    sma_bull_bars = int(((sma20 > sma50).astype(int)).tail(BULL_TREND_BARS).sum())
    sma_bear_bars = int(((sma20 < sma50).astype(int)).tail(BULL_TREND_BARS).sum())

    # Volumen vs media
    vol_mean  = float(volume.rolling(20).mean().iloc[-1])
    vol_ratio = (float(volume.iloc[-1]) / vol_mean) if vol_mean > 0 else 1.0

    # ── Señales individuales ─────────────────────────────────────────────────
    signals = {
        "sma20_vs_50":   "UP"   if last_sma20 > last_sma50  else "DOWN",
        "price_vs_sma200": "ABOVE" if last_close > last_sma200 else "BELOW",
        "rsi":           round(last_rsi, 1),
        "roc_20":        round(last_roc, 2),
        "atr_ratio":     round(atr_ratio, 2),
        "atr_pct":       round(atr_pct, 2),
        "vol_ratio":     round(vol_ratio, 2),
        "sma_bull_bars": sma_bull_bars,
        "sma_bear_bars": sma_bear_bars,
    }

    # ── Scoring ──────────────────────────────────────────────────────────────
    bull_score = 0
    bear_score = 0

    # Tendencia (peso 40%)
    if last_sma20 > last_sma50:  bull_score += 20
    else:                         bear_score += 20
    if last_close > last_sma200: bull_score += 20
    else:                         bear_score += 20

    # Momentum RSI (peso 30%)
    if last_rsi > BULL_RSI_MIN:  bull_score += 15
    elif last_rsi < BEAR_RSI_MAX: bear_score += 15
    if last_roc > 2:              bull_score += 15
    elif last_roc < -2:           bear_score += 15

    # Consistencia tendencia (peso 30%)
    bull_score += int(sma_bull_bars / BULL_TREND_BARS * 30)
    bear_score += int(sma_bear_bars / BULL_TREND_BARS * 30)

    # ── Régimen ──────────────────────────────────────────────────────────────
    # Alta volatilidad tiene prioridad sobre tendencia
    if atr_ratio >= VOL_HIGH_MULT:
        regime = MarketRegime.HIGH_VOL
        confidence = min(100, int(atr_ratio * 40))
        description = f"Volatilidad extrema (ATR {atr_ratio:.1f}x media). Estrategias de breakout."
    elif bull_score > bear_score + 20:
        regime = MarketRegime.BULL
        confidence = min(100, bull_score)
        description = f"Tendencia alcista. SMA20>SMA50 {sma_bull_bars}/{BULL_TREND_BARS} barras. RSI={last_rsi:.0f}."
    elif bear_score > bull_score + 20:
        regime = MarketRegime.BEAR
        confidence = min(100, bear_score)
        description = f"Tendencia bajista. SMA20<SMA50 {sma_bear_bars}/{BULL_TREND_BARS} barras. RSI={last_rsi:.0f}."
    else:
        regime = MarketRegime.SIDEWAYS
        confidence = 50 + abs(bull_score - bear_score)
        description = f"Mercado lateral/sin tendencia. RSI={last_rsi:.0f}, ATR ratio={atr_ratio:.1f}x."

    return {
        "regime":      regime,
        "confidence":  confidence,
        "signals":     signals,
        "description": description,
    }


# ── Selector de estrategia por régimen ────────────────────────────────────────
# Mapa de régimen → tipos de estrategia preferidos
REGIME_STRATEGY_MAP = {
    MarketRegime.BULL:    ["trend", "momentum", "breakout", "orb"],
    MarketRegime.BEAR:    ["short", "momentum", "breakout"],
    MarketRegime.SIDEWAYS:["mean_reversion", "squeeze", "bollinger", "rsi"],
    MarketRegime.HIGH_VOL:["squeeze", "breakout", "volatility", "atr"],
}

# Tags por estrategia (para matching)
STRATEGY_TAGS = {
    "VolatilitySqueeze":  ["squeeze", "breakout", "volatility"],
    "VolatilitySqueezeV2":["squeeze", "breakout", "volatility", "trend"],
    "RSIBand":            ["mean_reversion", "rsi", "momentum"],
    "ORBStrategy":        ["breakout", "orb", "momentum"],
    "LiquidationDip":     ["mean_reversion", "short"],
    "GapAndGo":           ["momentum", "breakout"],
    "WeakEnsemble":       ["trend", "momentum"],
    "BollingerAltcoin":   ["mean_reversion", "bollinger"],
    "SupertrendAdaptive": ["trend", "momentum"],
    "BreakoutRetest":     ["breakout", "trend"],
}


def load_multi_results() -> list[dict]:
    """Carga todos los resultados de multi-test de results/multi_*.json."""
    results = []
    for path in sorted(glob.glob(str(RESULTS_DIR / "multi_*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            strategy = d.get("strategy", Path(path).stem)
            symbols  = d.get("symbols", [])
            if not symbols:
                continue

            valid   = [s for s in symbols if not s.get("error")]
            passing = [s for s in valid if s.get("verdict") == "PASS"]
            best    = max(valid, key=lambda s: s.get("sharpe", -99), default={})

            results.append({
                "strategy":    strategy,
                "file":        path,
                "total":       len(valid),
                "passing":     len(passing),
                "pct_pass":    len(passing) / len(valid) * 100 if valid else 0,
                "best_sharpe": best.get("sharpe", 0),
                "best_symbol": best.get("symbol", "?"),
                "best_return": best.get("return_pct", 0),
            })
        except Exception:
            continue
    return results


def select_strategy(regime: str, results: list[dict]) -> Optional[dict]:
    """
    Selecciona la mejor estrategia para el régimen dado.
    Prioriza estrategias con tags coincidentes + mayor Sharpe.
    """
    preferred_tags = REGIME_STRATEGY_MAP.get(regime, [])

    scored = []
    for r in results:
        name = r["strategy"]
        tags = STRATEGY_TAGS.get(name, [])

        # Bonus por tags coincidentes
        tag_bonus = sum(1 for t in preferred_tags if t in tags) * 10

        # Score = Sharpe ponderado + bonus tags + % activos pasan
        score = r["best_sharpe"] * 20 + tag_bonus + r["pct_pass"] * 0.5
        scored.append({**r, "regime_score": round(score, 2)})

    if not scored:
        return None

    scored.sort(key=lambda x: x["regime_score"], reverse=True)
    return scored[0]


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    symbol   = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SYMBOL
    interval = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_INTERVAL

    console.print(f"\n[bold]Descargando datos {symbol} {interval} {DEFAULT_DAYS}d...[/bold]")
    df = get_ohlcv(symbol, interval=interval, days=DEFAULT_DAYS)
    if df is None or len(df) < 50:
        console.print(f"[red]Sin datos para {symbol}[/red]")
        sys.exit(1)

    # Detectar régimen
    regime_data = detect_regime(df)
    regime      = regime_data["regime"]
    confidence  = regime_data["confidence"]
    description = regime_data["description"]

    color = {"BULL": "green", "BEAR": "red", "SIDEWAYS": "yellow", "HIGH_VOLATILITY": "magenta"}
    emoji = {"BULL": "🟢", "BEAR": "🔴", "SIDEWAYS": "🟡", "HIGH_VOLATILITY": "🟣"}

    console.print(Panel(
        f"[bold {color.get(regime,'white')}]{emoji.get(regime,'')} RÉGIMEN: {regime}[/bold {color.get(regime,'white')}]\n"
        f"Confianza: {confidence}%\n"
        f"{description}",
        title=f"Market Regime — {symbol} {interval}",
        expand=False,
    ))

    # Señales detalladas
    sigs = regime_data["signals"]
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Señal", style="cyan")
    table.add_column("Valor", justify="right")
    for k, v in sigs.items():
        table.add_row(k, str(v))
    console.print(table)

    # Cargar resultados de backtest y seleccionar estrategia
    results = load_multi_results()
    if results:
        best = select_strategy(regime, results)
        if best:
            console.print(f"\n[bold green]Estrategia recomendada para {regime}:[/bold green]")
            console.print(f"  Nombre:      {best['strategy']}")
            console.print(f"  Mejor activo: {best['best_symbol']} (Sharpe {best['best_sharpe']:.2f}, Return {best['best_return']:+.1f}%)")
            console.print(f"  Activos OK:  {best['passing']}/{best['total']} ({best['pct_pass']:.0f}%)")
            console.print(f"  Score régimen: {best['regime_score']:.2f}")
        else:
            console.print("\n[yellow]Sin estrategias disponibles en results/[/yellow]")
    else:
        console.print("\n[yellow]Sin resultados de backtest. Corre multi_data_tester primero.[/yellow]")

    # Output para otros agentes
    output = {
        "symbol":      symbol,
        "interval":    interval,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "regime":      regime,
        "confidence":  confidence,
        "description": description,
        "signals":     regime_data["signals"],
        "recommended_strategy": best["strategy"] if results and best else None,
        "recommended_tags":    REGIME_STRATEGY_MAP.get(regime, []),
    }

    out_path = cfg.DATA_DIR / "regime_state.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    console.print(f"\n[dim]Estado guardado en {out_path}[/dim]")

    return output


if __name__ == "__main__":
    main()
