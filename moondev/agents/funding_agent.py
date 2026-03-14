"""
funding_agent — monitor de tasas de funding en HyperLiquid.

Cada 15 min consulta funding rates de MONITORED_TOKENS.
Si annual_rate < -5% o > 20% → analiza con LLM → BUY/SELL/NOTHING.

Uso: python moondev/agents/funding_agent.py
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from moondev.data.hyperliquid_data import get_funding_snapshot
from moondev.core.model_factory import ModelFactory
from moondev.core.nice_funcs import parse_llm_action, get_ohlcv, add_indicators
import moondev.config as cfg
from rich.console import Console

console = Console()
CHECK_INTERVAL = 15 * 60  # 15 minutos
NEG_THRESHOLD = -5.0
POS_THRESHOLD = 20.0

SYSTEM_PROMPT = """You are a funding rate carry trade analyst.
Analyze the provided funding rate data and market context.

Respond in exactly 3 lines:
Line 1: BUY, SELL, or NOTHING
Line 2: One short reason
Line 3: Confidence: X%

Consider:
- Negative funding in uptrend = potential long (funding reversal)
- Positive funding in downtrend = potential short
- Extreme funding (>100% annual) = carry trade opportunity
"""


def get_funding_rates() -> dict:
    """Obtiene funding rates de HyperLiquid via hyperliquid_data."""
    snapshot = get_funding_snapshot(tokens=list(cfg.MONITORED_TOKENS))
    return {
        name: {"hourly": info["hourly"], "annual": info["annual"]}
        for name, info in snapshot.items()
    }


def analyze_token(symbol: str, annual_rate: float, model) -> None:
    try:
        df = get_ohlcv(f"{symbol}-USD", days=7, timeframe="1h")
        df = add_indicators(df)
        last5 = df.tail(5).to_string()
    except Exception:
        last5 = "No data available"

    user_content = f"""
Token: {symbol}
Annual Funding Rate: {annual_rate:.2f}%
Hourly Funding Rate: {annual_rate / 24 / 365:.4f}%

Market context (last 5 candles 1h):
{last5}

SMA20 > SMA50 (uptrend)? {df['sma20'].iloc[-1] > df['sma50'].iloc[-1] if 'sma20' in df.columns else 'N/A'}
"""
    resp = model.ask(SYSTEM_PROMPT, user_content)
    action, reason, confidence = parse_llm_action(resp.content)
    color = {"BUY": "green", "SELL": "red", "NOTHING": "dim"}.get(action, "white")
    console.print(f"  [{color}]{action}[/{color}] {confidence}% | {reason}")


def main():
    model = ModelFactory().get()
    console.print(f"[bold]funding_agent[/bold] | {model.name} | check cada 15min")

    while True:
        console.rule("Funding Rate Check")
        rates = get_funding_rates()
        if not rates:
            console.print("[yellow]Sin datos de funding[/yellow]")
        for symbol, r in rates.items():
            annual = r["annual"]
            console.print(f"[cyan]{symbol}[/cyan] annual: {annual:.1f}%", end=" ")
            if annual < NEG_THRESHOLD or annual > POS_THRESHOLD:
                console.print("→ ANALYZING")
                analyze_token(symbol, annual, model)
            else:
                console.print("→ [dim]dentro de rango normal[/dim]")

        console.print(f"[dim]Próximo check en 15min...[/dim]")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
