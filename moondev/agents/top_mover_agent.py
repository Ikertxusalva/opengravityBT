"""
top_mover_agent — analista de top gainers y losers del mercado crypto.

Cada 15 min obtiene los tokens con mayor movimiento 24h.
Clasifica cada uno como: Momentum / Contrarian / Ignorar.
LLM decide BUY/SELL/NOTHING para los mejores setups.

Edge:
  - Momentum: tokens con catalizador real + volumen confirman → continúan
  - Contrarian: tokens +40%+ sin catalizador → reversión probable

Uso: python moondev/agents/top_mover_agent.py
"""
import sys
import time
import csv
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from moondev.data.binance_data import get_all_24h_tickers
from moondev.core.model_factory import ModelFactory
from moondev.core.nice_funcs import get_ohlcv, add_indicators, parse_llm_action
import moondev.config as cfg
from rich.console import Console

console = Console()
CHECK_INTERVAL = 15 * 60  # 15 minutos
DATA_DIR = cfg.DATA_DIR / "top_movers"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SIGNALS_FILE = DATA_DIR / "signals.csv"

# Filtros de calidad
MIN_VOLUME_24H = 5_000_000   # $5M mínimo de volumen
MIN_MARKET_CAP = 10_000_000  # $10M mínimo market cap
MAX_MARKET_CAP = 2_000_000_000  # $2B máximo (sin mega caps)
TOP_N = 20  # analizar top 20 movers

MOMENTUM_PROMPT = """You are a momentum trading analyst.
A crypto token has made a significant price move in the last 24 hours.

Analyze if this is a momentum trade (follow the trend) or contrarian (fade it):

Consider:
1. Move size: +20-30% may continue, +50%+ is likely exhausted
2. Volume: high volume = real move, low volume = fakeout
3. Catalyst: fundamental reason? (listing, partnership, upgrade)
4. Market context: bull market = momentum works, bear = fade it

Respond in exactly 3 lines:
Line 1: BUY (momentum), SELL (short/fade), or NOTHING
Line 2: One short reason (momentum/contrarian)
Line 3: Confidence: X%
"""


def get_top_movers() -> list[dict]:
    """Obtiene top gainers y losers via binance_data."""
    try:
        tickers = get_all_24h_tickers()
        filtered = []
        for t in tickers:
            if not t.get("symbol", "").endswith("USDT"):
                continue
            volume = float(t.get("quoteVolume", 0))
            if volume < MIN_VOLUME_24H:
                continue
            filtered.append({
                "symbol": t["symbol"],
                "price": float(t["lastPrice"]),
                "change_pct": float(t["priceChangePercent"]),
                "volume_24h": volume,
                "high_24h": float(t["highPrice"]),
                "low_24h": float(t["lowPrice"]),
            })
        filtered.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
        return filtered[:TOP_N]
    except Exception as e:
        console.print(f"[red]Binance ticker error: {e}[/red]")
        return []


def classify_mover(token: dict) -> str:
    """Clasifica el tipo de oportunidad."""
    change = token["change_pct"]
    vol = token["volume_24h"]

    if abs(change) > 40:
        return "CONTRARIAN"  # Muy extendido, probable reversión
    elif abs(change) > 15 and vol > 50_000_000:
        return "MOMENTUM"    # Movimiento fuerte con volumen = continúa
    elif abs(change) > 10:
        return "WATCH"       # Interesante pero esperar confirmación
    else:
        return "IGNORE"


def analyze_mover(token: dict, setup_type: str, model) -> None:
    symbol_base = token["symbol"].replace("USDT", "")
    try:
        df = get_ohlcv(f"{symbol_base}-USD", days=3, timeframe="1h")
        df = add_indicators(df)
        ctx = df.tail(5).to_string()
    except Exception:
        ctx = "No data available"

    user_content = f"""
Token: {token['symbol']}
Setup type: {setup_type}
Price: ${token['price']:.6f}
24h Change: {token['change_pct']:+.1f}%
24h Volume: ${token['volume_24h'] / 1e6:.1f}M
24h High: ${token['high_24h']:.6f}
24h Low: ${token['low_24h']:.6f}

Market data last 5 candles 1h:
{ctx}
"""
    resp = model.ask(MOMENTUM_PROMPT, user_content)
    action, reason, confidence = parse_llm_action(resp.content)
    color = {"BUY": "green", "SELL": "red", "NOTHING": "dim"}.get(action, "white")
    console.print(
        f"  [{color}]{action}[/{color}] {confidence}% | {setup_type} | {reason}"
    )

    if action != "NOTHING" and confidence >= cfg.STRATEGY_MIN_CONFIDENCE:
        is_new = not SIGNALS_FILE.exists()
        with open(SIGNALS_FILE, "a", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["timestamp", "symbol", "change_pct", "volume_24h",
                           "setup_type", "action", "confidence", "reason"],
            )
            if is_new:
                writer.writeheader()
            writer.writerow({
                "timestamp": datetime.now().isoformat(),
                "symbol": token["symbol"],
                "change_pct": token["change_pct"],
                "volume_24h": token["volume_24h"],
                "setup_type": setup_type,
                "action": action,
                "confidence": confidence,
                "reason": reason,
            })


def main():
    model = ModelFactory().get()
    console.print(f"[bold]top_mover_agent[/bold] | {model.name} | top {TOP_N} movers cada 15min")

    while True:
        console.rule("Top Mover Check")
        movers = get_top_movers()

        if not movers:
            console.print("[yellow]Sin datos de mercado[/yellow]")
            time.sleep(CHECK_INTERVAL)
            continue

        # Clasificar y filtrar los que valen la pena analizar
        to_analyze = []
        for t in movers:
            setup = classify_mover(t)
            direction = "+" if t["change_pct"] > 0 else ""
            if setup in ("MOMENTUM", "CONTRARIAN"):
                console.print(
                    f"[cyan]{t['symbol']:<12}[/cyan] "
                    f"{direction}{t['change_pct']:.1f}%  "
                    f"Vol: ${t['volume_24h']/1e6:.0f}M  "
                    f"[yellow]{setup}[/yellow]"
                )
                to_analyze.append((t, setup))
            else:
                console.print(
                    f"[dim]{t['symbol']:<12} {direction}{t['change_pct']:.1f}%  "
                    f"Vol: ${t['volume_24h']/1e6:.0f}M  {setup}[/dim]"
                )

        # Analizar top 5 con LLM
        console.print(f"\nAnalizando {min(len(to_analyze), 5)} setups con LLM...")
        for token, setup in to_analyze[:5]:
            console.print(f"\n[bold]{token['symbol']}[/bold] {token['change_pct']:+.1f}%")
            analyze_mover(token, setup, model)

        console.print(f"\n[dim]Proximo check en 15min...[/dim]")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
