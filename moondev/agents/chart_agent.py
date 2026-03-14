"""
chart_agent — analista de patrones de price action y estructura de mercado.

Cada 30 min analiza los MONITORED_TOKENS en múltiples timeframes.
Detecta: estructura HH/HL vs LH/LL, niveles clave, patrones técnicos.
LLM genera análisis técnico con entrada/SL/TP concretos.

Patrones detectados:
  - Estructura de mercado: HH/HL (alcista) vs LH/LL (bajista)
  - Bull/Bear flag, inside bar, doble techo/suelo
  - Niveles Fibonacci (38.2%, 50%, 61.8%)
  - Confluencias: nivel + indicador + volumen

Uso: python moondev/agents/chart_agent.py
"""
import sys
import time
import csv
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import pandas_ta as ta
from moondev.core.model_factory import ModelFactory
from moondev.core.nice_funcs import get_ohlcv, parse_llm_action
import moondev.config as cfg
from rich.console import Console

console = Console()
CHECK_INTERVAL = 30 * 60  # 30 minutos
DATA_DIR = cfg.DATA_DIR / "chart"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SIGNALS_FILE = DATA_DIR / "chart_signals.csv"

SYSTEM_PROMPT = """You are a technical price action analyst.
Analyze the market structure and key levels provided.

Your analysis should identify:
1. Market structure: bullish (HH/HL) or bearish (LH/LL)
2. Key support/resistance levels (horizontal + moving averages)
3. Patterns: flag, triangle, double top/bottom, inside bar
4. Confluence zones (3+ factors at same level = strong signal)

Respond in exactly 3 lines:
Line 1: BUY (at support/breakout), SELL (at resistance/breakdown), or NOTHING (no setup)
Line 2: Pattern + entry level (e.g., "Bull flag, entry at $85,000 breakout")
Line 3: Confidence: X%

Only signal if there is a clear 3+ confluence setup. Otherwise say NOTHING.
"""


def detect_market_structure(df: pd.DataFrame, lookback: int = 5) -> dict:
    """
    Detecta la estructura de mercado:
    - HH/HL = Higher Highs / Higher Lows = alcista
    - LH/LL = Lower Highs / Lower Lows = bajista
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(highs)

    if n < lookback * 2:
        return {"structure": "UNKNOWN", "last_swing_high": 0, "last_swing_low": 0}

    # Pivot highs y lows (simplificado: máx/mín de ventana)
    swing_highs = []
    swing_lows = []
    for i in range(lookback, n - lookback):
        if highs[i] == max(highs[i - lookback:i + lookback + 1]):
            swing_highs.append(highs[i])
        if lows[i] == min(lows[i - lookback:i + lookback + 1]):
            swing_lows.append(lows[i])

    structure = "UNKNOWN"
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        hh = swing_highs[-1] > swing_highs[-2]   # Higher High
        hl = swing_lows[-1] > swing_lows[-2]     # Higher Low
        lh = swing_highs[-1] < swing_highs[-2]   # Lower High
        ll = swing_lows[-1] < swing_lows[-2]     # Lower Low

        if hh and hl:
            structure = "BULLISH (HH/HL)"
        elif lh and ll:
            structure = "BEARISH (LH/LL)"
        elif hh and ll:
            structure = "MIXED (HH/LL - volatile)"
        else:
            structure = "RANGING"

    return {
        "structure": structure,
        "last_swing_high": swing_highs[-1] if swing_highs else 0,
        "last_swing_low": swing_lows[-1] if swing_lows else 0,
    }


def detect_inside_bar(df: pd.DataFrame) -> bool:
    """Inside bar: rango de la vela actual dentro del rango de la anterior."""
    if len(df) < 2:
        return False
    current = df.iloc[-1]
    previous = df.iloc[-2]
    return (current["high"] <= previous["high"] and
            current["low"] >= previous["low"])


def get_fib_levels(high: float, low: float) -> dict:
    """Calcula niveles de Fibonacci entre el último swing high y low."""
    diff = high - low
    return {
        "fib_0": high,
        "fib_236": high - diff * 0.236,
        "fib_382": high - diff * 0.382,
        "fib_500": high - diff * 0.500,
        "fib_618": high - diff * 0.618,
        "fib_100": low,
    }


def analyze_chart(symbol: str, model) -> None:
    try:
        df_1h = get_ohlcv(f"{symbol}-USD", days=30, timeframe="1h")
        df_4h = get_ohlcv(f"{symbol}-USD", days=90, timeframe="4h")
        df_1d = get_ohlcv(f"{symbol}-USD", days=365, timeframe="1d")
    except Exception as e:
        console.print(f"[red]{symbol}: error obteniendo datos — {e}[/red]")
        return

    if len(df_1h) < 50:
        return

    # Añadir indicadores
    close = df_1h["close"]
    ema50  = ta.ema(close, 50).iloc[-1]
    ema200 = ta.ema(close, 200).iloc[-1] if len(close) >= 200 else None
    sma20  = ta.sma(close, 20).iloc[-1]
    rsi    = ta.rsi(close, 14).iloc[-1]
    atr    = ta.atr(df_1h["high"], df_1h["low"], close, 14).iloc[-1]

    current_price = close.iloc[-1]
    structure_1h = detect_market_structure(df_1h)
    structure_4h = detect_market_structure(df_4h, lookback=3) if len(df_4h) >= 10 else {"structure": "N/A"}
    inside = detect_inside_bar(df_1h)

    # Fibonacci del ultimo swing
    high_30d = df_1h["high"].max()
    low_30d = df_1h["low"].min()
    fibs = get_fib_levels(high_30d, low_30d)

    # Distancia al nivel Fib 61.8% (el más importante)
    fib618 = fibs["fib_618"]
    dist_fib618 = abs(current_price - fib618) / current_price * 100

    # Nivel EMA más cercano
    levels = {"EMA50": ema50, "SMA20": sma20}
    if ema200:
        levels["EMA200"] = ema200
    nearest_ma = min(levels.items(), key=lambda x: abs(current_price - x[1]))
    dist_nearest_ma = abs(current_price - nearest_ma[1]) / current_price * 100

    user_content = f"""
Symbol: {symbol}
Current Price: ${current_price:.4f}
ATR (14): ${atr:.4f} ({atr/current_price*100:.2f}%)

Market Structure:
- 1H: {structure_1h['structure']}
- 4H: {structure_4h['structure']}
- Last swing high (1H): ${structure_1h['last_swing_high']:.4f}
- Last swing low (1H): ${structure_1h['last_swing_low']:.4f}

Key Levels (1H):
- EMA50: ${ema50:.4f} (dist: {abs(current_price-ema50)/current_price*100:.1f}%)
- SMA20: ${sma20:.4f} (dist: {abs(current_price-sma20)/current_price*100:.1f}%)
{"- EMA200: $" + f"{ema200:.4f}" if ema200 else "- EMA200: insufficient data"}
- Fib 61.8%: ${fib618:.4f} (dist: {dist_fib618:.1f}%)
- Fib 50.0%: ${fibs['fib_500']:.4f}
- 30d High: ${high_30d:.4f}
- 30d Low: ${low_30d:.4f}

Indicators:
- RSI(14): {rsi:.1f}
- Inside Bar: {inside}
- Nearest MA: {nearest_ma[0]} at ${nearest_ma[1]:.4f} ({dist_nearest_ma:.1f}% away)

Confluence check at current price area:
- Near 61.8% Fib (<2%): {dist_fib618 < 2.0}
- Near MA (<1%): {dist_nearest_ma < 1.0}
- RSI oversold (<35): {rsi < 35}
- RSI overbought (>65): {rsi > 65}
- Inside bar (compression): {inside}
"""
    resp = model.ask(SYSTEM_PROMPT, user_content)
    action, pattern_info, confidence = parse_llm_action(resp.content)

    color = {"BUY": "green", "SELL": "red", "NOTHING": "dim"}.get(action, "white")
    console.print(
        f"  [cyan]{symbol}[/cyan] ${current_price:.2f} | "
        f"Struct: {structure_1h['structure']} | "
        f"RSI: {rsi:.0f} | "
        f"[{color}]{action}[/{color}] {confidence}% | {pattern_info}"
    )

    if action != "NOTHING" and confidence >= cfg.STRATEGY_MIN_CONFIDENCE:
        is_new = not SIGNALS_FILE.exists()
        with open(SIGNALS_FILE, "a", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["timestamp", "symbol", "price", "structure_1h",
                           "rsi", "action", "confidence", "pattern"],
            )
            if is_new:
                writer.writeheader()
            writer.writerow({
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "price": current_price,
                "structure_1h": structure_1h["structure"],
                "rsi": round(rsi, 1),
                "action": action,
                "confidence": confidence,
                "pattern": pattern_info,
            })


def main():
    model = ModelFactory().get()
    console.print(f"[bold]chart_agent[/bold] | {model.name} | {cfg.MONITORED_TOKENS} | check cada 30min")

    while True:
        console.rule("Chart Analysis")
        for token in cfg.MONITORED_TOKENS:
            console.print(f"\n[bold]{token}[/bold]")
            analyze_chart(token, model)

        console.print(f"\n[dim]Proximo analisis en 30min...[/dim]")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
