"""
new_listing_agent — detector de nuevos listings en exchanges tier-1.

Cada 30 min monitorea Binance, Coinbase, Bybit para detectar nuevos pares.
Si detecta listing nuevo → analiza con LLM → BUY/SELL/NOTHING.

Edge: "Coinbase/Binance Effect" — tokens suben 20-50% en primeras horas post-listing.
Estrategia: comprar en el anuncio, antes del listing oficial.

Uso: python moondev/agents/new_listing_agent.py
"""
import sys
import time
import json
import csv
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
from moondev.data.binance_data import (
    get_exchange_symbols as _bn_get_exchange_symbols,
    get_price as _bn_get_price,
    get_24h_ticker as _bn_get_24h_ticker,
)
from moondev.core.model_factory import ModelFactory
from moondev.core.nice_funcs import parse_llm_action
import moondev.config as cfg
from rich.console import Console

console = Console()
CHECK_INTERVAL = 30 * 60  # 30 minutos
DATA_DIR = cfg.DATA_DIR / "listings"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SEEN_FILE = DATA_DIR / "seen_listings.json"

SYSTEM_PROMPT = """You are a new listing arbitrage analyst.
A token has been newly listed on a major exchange.

Analyze if this is a good buy opportunity based on:
1. Exchange tier (Binance > Coinbase > Bybit > others)
2. Project fundamentals (utility, team, backers)
3. Market timing (bull/bear market context)
4. Price action since announcement (already pumped?)

Respond in exactly 3 lines:
Line 1: BUY, SELL (short if possible), or NOTHING
Line 2: One short reason
Line 3: Confidence: X%

Key rules:
- Binance listing = stronger effect than others
- If already +30%+ before listing = too late, say NOTHING
- Bear market = weaker listing effect
"""


def load_seen() -> dict:
    if SEEN_FILE.exists():
        return json.loads(SEEN_FILE.read_text())
    return {}


def save_seen(seen: dict) -> None:
    SEEN_FILE.write_text(json.dumps(seen, indent=2))


def get_binance_symbols() -> set:
    """Obtiene todos los pares USDT activos en Binance via binance_data."""
    try:
        return _bn_get_exchange_symbols(quote_asset="USDT")
    except Exception as e:
        console.print(f"[red]Binance API error: {e}[/red]")
        return set()


def get_coinbase_symbols() -> set:
    """Obtiene productos activos en Coinbase."""
    try:
        resp = requests.get(
            "https://api.exchange.coinbase.com/products",
            timeout=10,
        )
        data = resp.json()
        return {
            p["id"]
            for p in data
            if p.get("quote_currency") == "USDT" and p.get("status") == "online"
        }
    except Exception as e:
        console.print(f"[red]Coinbase API error: {e}[/red]")
        return set()


def get_token_price(symbol: str) -> float:
    """Precio actual del token via binance_data."""
    try:
        data = _bn_get_price(symbol)
        return float(data.get("price", 0))
    except Exception:
        return 0.0


def get_token_24h_change(symbol: str) -> float:
    """Cambio 24h en % del token via binance_data."""
    try:
        data = _bn_get_24h_ticker(symbol)
        return float(data.get("change_pct", 0))
    except Exception:
        return 0.0


def analyze_listing(symbol: str, exchange: str, model) -> None:
    price = get_token_price(symbol)
    change_24h = get_token_24h_change(symbol)

    user_content = f"""
New listing detected:
Symbol: {symbol}
Exchange: {exchange}
Current price: ${price:.6f}
24h change: {change_24h:+.1f}%
Listed at: {datetime.now().isoformat()}

Context:
- Already moved {change_24h:+.1f}% in 24h
- Exchange quality: {exchange} (tier-1 if Binance/Coinbase)
"""
    resp = model.ask(SYSTEM_PROMPT, user_content)
    action, reason, confidence = parse_llm_action(resp.content)
    color = {"BUY": "green", "SELL": "red", "NOTHING": "dim"}.get(action, "white")
    console.print(f"  [{color}]{action}[/{color}] {confidence}% | {reason}")

    # Guardar señal
    log_file = DATA_DIR / "listing_signals.csv"
    is_new = not log_file.exists()
    with open(log_file, "a", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["timestamp", "symbol", "exchange", "price", "change_24h", "action", "confidence", "reason"]
        )
        if is_new:
            writer.writeheader()
        writer.writerow({
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "exchange": exchange,
            "price": price,
            "change_24h": change_24h,
            "action": action,
            "confidence": confidence,
            "reason": reason,
        })


def main():
    model = ModelFactory().get()
    console.print(f"[bold]new_listing_agent[/bold] | {model.name} | check cada 30min")

    seen = load_seen()
    if not seen.get("binance"):
        # Primera ejecucion: snapshot sin alertas
        console.print("[dim]Primera ejecucion: creando snapshot de pares existentes...[/dim]")
        seen["binance"] = list(get_binance_symbols())
        seen["coinbase"] = list(get_coinbase_symbols())
        save_seen(seen)
        console.print(f"[dim]Snapshot: {len(seen['binance'])} Binance + {len(seen['coinbase'])} Coinbase[/dim]")

    while True:
        console.rule("Listing Check")
        now_binance = get_binance_symbols()
        now_coinbase = get_coinbase_symbols()

        prev_binance = set(seen.get("binance", []))
        prev_coinbase = set(seen.get("coinbase", []))

        new_binance = now_binance - prev_binance
        new_coinbase = now_coinbase - prev_coinbase

        if new_binance:
            for sym in new_binance:
                console.print(f"\n[bold yellow]NUEVO LISTING BINANCE:[/bold yellow] [cyan]{sym}[/cyan]")
                analyze_listing(sym, "Binance", model)
        else:
            console.print(f"[dim]Binance: {len(now_binance)} pares, 0 nuevos[/dim]")

        if new_coinbase:
            for sym in new_coinbase:
                console.print(f"\n[bold yellow]NUEVO LISTING COINBASE:[/bold yellow] [cyan]{sym}[/cyan]")
                analyze_listing(sym, "Coinbase", model)
        else:
            console.print(f"[dim]Coinbase: {len(now_coinbase)} pares, 0 nuevos[/dim]")

        seen["binance"] = list(now_binance)
        seen["coinbase"] = list(now_coinbase)
        save_seen(seen)

        console.print(f"[dim]Proximo check en 30min...[/dim]")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
