"""
liquidation_agent — detecta spikes de liquidaciones long/short.

Cada 10 min obtiene liquidaciones recientes.
Si long_liq o short_liq sube >50% → analiza con LLM → BUY/SELL/NOTHING.

Uso: python moondev/agents/liquidation_agent.py
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
import pandas as pd
from moondev.core.model_factory import ModelFactory
from moondev.core.nice_funcs import get_ohlcv, parse_llm_action
import moondev.config as cfg
from rich.console import Console

console = Console()
CHECK_INTERVAL = 10 * 60
SPIKE_THRESHOLD = 0.5  # 50% aumento

SYSTEM_PROMPT = """You are a liquidation cascade analyst.
Analyze the provided liquidation data and market context.

Key signals:
- Large LONG liquidations often indicate capitulation → potential bottom
- Large SHORT liquidations often indicate exhaustion → potential top

Respond in exactly 3 lines:
Line 1: BUY, SELL, or NOTHING
Line 2: One short reason
Line 3: Confidence: X%
"""


def fetch_liquidations() -> dict:
    """
    Obtiene liquidaciones de Coinglass o retorna datos mock si no disponible.
    Retorna: {long_usd, short_usd}
    """
    try:
        resp = requests.get(
            "https://open-api.coinglass.com/public/v2/liquidation",
            params={"symbol": "BTC", "time_type": "h1"},
            timeout=10,
        )
        data = resp.json().get("data", {})
        return {
            "long_usd": float(data.get("longLiquidationUsd", 0)),
            "short_usd": float(data.get("shortLiquidationUsd", 0)),
        }
    except Exception:
        # Mock si la API no está disponible
        return {"long_usd": 5_000_000, "short_usd": 2_000_000}


def analyze_liquidations(current: dict, previous: dict, model) -> None:
    long_change = (current["long_usd"] - previous["long_usd"]) / max(previous["long_usd"], 1)
    short_change = (current["short_usd"] - previous["short_usd"]) / max(previous["short_usd"], 1)

    if abs(long_change) < SPIKE_THRESHOLD and abs(short_change) < SPIKE_THRESHOLD:
        return

    console.print(f"[yellow]Spike detectado! Long delta{long_change*100:.0f}% Short delta{short_change*100:.0f}%[/yellow]")

    try:
        df = get_ohlcv("BTC-USD", days=1, timeframe="15m")
        ctx = df.tail(5).to_string()
    except Exception:
        ctx = "No data"

    user = f"""
Long liquidations: ${current['long_usd']:,.0f} (delta{long_change*100:+.1f}%)
Short liquidations: ${current['short_usd']:,.0f} (delta{short_change*100:+.1f}%)

BTC 15m (last 5 candles):
{ctx}
"""
    resp = model.ask(SYSTEM_PROMPT, user)
    action, reason, confidence = parse_llm_action(resp.content)
    color = {"BUY": "green", "SELL": "red", "NOTHING": "dim"}.get(action, "white")
    console.print(f"[{color}]{action}[/{color}] {confidence}% | {reason}")


def main():
    model = ModelFactory().get()
    console.print(f"[bold]liquidation_agent[/bold] | {model.name}")
    previous = {"long_usd": 0, "short_usd": 0}

    while True:
        current = fetch_liquidations()
        console.print(
            f"[dim]Longs: ${current['long_usd']/1e6:.1f}M | Shorts: ${current['short_usd']/1e6:.1f}M[/dim]"
        )
        analyze_liquidations(current, previous, model)
        previous = current
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
