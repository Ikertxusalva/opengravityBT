"""
sniper_agent — scanner de nuevos tokens en Solana (modo alerta).

Polling cada 10s al endpoint de MoonDev API o a DexScreener.
Alerta cuando detecta tokens nuevos. NO ejecuta compras (solo descubre).

Uso: python moondev/agents/sniper_agent.py
"""
import sys, time, csv
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
import moondev.config as cfg
from rich.console import Console

console = Console()
POLL_INTERVAL = 10  # segundos
SNIPER_DATA = cfg.DATA_DIR / "sniper"
SNIPER_DATA.mkdir(parents=True, exist_ok=True)
RECENT_TOKENS_FILE = SNIPER_DATA / "recent_tokens.csv"

# Tokens excluidos (stablecoins, wrapped SOL, etc.)
EXCLUDE = {"So11111111111111111111111111111111111111112"}

DEXSCREENER_URL = "https://api.dexscreener.com/token-boosts/latest/v1"


def fetch_new_tokens() -> list[dict]:
    """Obtiene tokens recientes de DexScreener boosts."""
    try:
        resp = requests.get(DEXSCREENER_URL, timeout=10)
        data = resp.json()
        tokens = []
        for item in data:
            if item.get("chainId") != "solana":
                continue
            addr = item.get("tokenAddress", "")
            if addr in EXCLUDE:
                continue
            tokens.append({
                "address": addr,
                "url": item.get("url", ""),
                "amount": item.get("amount", 0),
                "timestamp": datetime.now().isoformat(),
            })
        return tokens
    except Exception as e:
        console.print(f"[red]DexScreener error: {e}[/red]")
        return []


def load_seen() -> set:
    if not RECENT_TOKENS_FILE.exists():
        return set()
    with open(RECENT_TOKENS_FILE, newline="") as f:
        return {row["address"] for row in csv.DictReader(f)}


def save_token(token: dict) -> None:
    is_new = not RECENT_TOKENS_FILE.exists()
    with open(RECENT_TOKENS_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["address", "url", "amount", "timestamp"])
        if is_new:
            writer.writeheader()
        writer.writerow(token)


def main():
    console.print("[bold]sniper_agent[/bold] | Solana token scanner | 10s polling")
    seen = load_seen()
    console.print(f"[dim]{len(seen)} tokens ya vistos[/dim]")

    while True:
        tokens = fetch_new_tokens()
        new = [t for t in tokens if t["address"] not in seen]

        for token in new:
            console.print(
                f"\n[bold yellow]NUEVO TOKEN[/bold yellow] "
                f"[cyan]{token['address'][:12]}...[/cyan] "
                f"boosts: {token['amount']}"
            )
            console.print(f"  {token['url']}")
            save_token(token)
            seen.add(token["address"])

        if not new:
            console.print(f"[dim]({len(tokens)} tokens, 0 nuevos)[/dim]", end="\r")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
