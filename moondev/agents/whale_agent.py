"""
whale_agent — tracker de movimientos on-chain de ballenas.

Cada 20 min monitorea grandes transacciones en BTC y ETH.
Si detecta acumulacion o distribucion masiva → analiza con LLM → BUY/SELL/NOTHING.

Señales clave:
  - Tokens saliendo de exchanges → holders acumulando → ALCISTA
  - Tokens entrando a exchanges → presión de venta → BAJISTA
  - Wallets inactivas años moviéndose → distribucion posible → PRECAUCION

Uso: python moondev/agents/whale_agent.py
Nota: usa Whale Alert API (free tier: alertas > $500K)
"""
import sys
import time
import csv
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
from moondev.core.model_factory import ModelFactory
from moondev.core.nice_funcs import get_ohlcv, parse_llm_action
import moondev.config as cfg
from rich.console import Console

console = Console()
CHECK_INTERVAL = 20 * 60  # 20 minutos
DATA_DIR = cfg.DATA_DIR / "whale"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SIGNALS_FILE = DATA_DIR / "whale_signals.csv"

# Umbral para considerar movimiento de ballena
WHALE_THRESHOLD_USD = 500_000   # $500K minimo

SYSTEM_PROMPT = """You are an on-chain whale movement analyst.
Large crypto transactions have been detected.

Analyze the market implications:
- Exchange INFLOWS (moving TO exchange) = selling pressure = BEARISH
- Exchange OUTFLOWS (moving FROM exchange) = accumulation = BULLISH
- Wallet-to-wallet = unknown intent, but large = important player moving

Respond in exactly 3 lines:
Line 1: BUY, SELL, or NOTHING
Line 2: One short reason (accumulation/distribution/unknown)
Line 3: Confidence: X%

Consider: multiple large outflows = stronger signal than single transaction.
"""

# Exchanges conocidos (simplificado)
KNOWN_EXCHANGES = {
    "binance", "coinbase", "kraken", "bybit", "okx",
    "bitfinex", "huobi", "kucoin", "gate.io",
}


def fetch_whale_transactions() -> list[dict]:
    """
    Obtiene transacciones grandes via Whale Alert free tier.
    Retorna mock data si no hay API key configurada.
    """
    whale_api_key = cfg.__dict__.get("WHALE_ALERT_API_KEY", "")

    if not whale_api_key:
        # Mock data para desarrollo/demo
        return [
            {
                "blockchain": "bitcoin",
                "symbol": "BTC",
                "amount": 500,
                "amount_usd": 43_000_000,
                "from_owner": "unknown",
                "to_owner": "binance",
                "direction": "TO_EXCHANGE",
                "timestamp": datetime.now().isoformat(),
            },
            {
                "blockchain": "ethereum",
                "symbol": "ETH",
                "amount": 5000,
                "amount_usd": 15_000_000,
                "from_owner": "coinbase",
                "to_owner": "unknown",
                "direction": "FROM_EXCHANGE",
                "timestamp": datetime.now().isoformat(),
            },
        ]

    try:
        resp = requests.get(
            "https://api.whale-alert.io/v1/transactions",
            params={
                "api_key": whale_api_key,
                "min_value": WHALE_THRESHOLD_USD,
                "currency": "usd",
                "limit": 20,
            },
            timeout=10,
        )
        txs = resp.json().get("transactions", [])
        result = []
        for tx in txs:
            from_owner = tx.get("from", {}).get("owner", "unknown").lower()
            to_owner = tx.get("to", {}).get("owner", "unknown").lower()

            direction = "UNKNOWN"
            if any(ex in to_owner for ex in KNOWN_EXCHANGES):
                direction = "TO_EXCHANGE"
            elif any(ex in from_owner for ex in KNOWN_EXCHANGES):
                direction = "FROM_EXCHANGE"

            result.append({
                "blockchain": tx.get("blockchain", "unknown"),
                "symbol": tx.get("symbol", "").upper(),
                "amount": tx.get("amount", 0),
                "amount_usd": tx.get("amount_usd", 0),
                "from_owner": from_owner,
                "to_owner": to_owner,
                "direction": direction,
                "timestamp": datetime.fromtimestamp(tx.get("timestamp", 0)).isoformat(),
            })
        return result

    except Exception as e:
        console.print(f"[red]Whale Alert API error: {e}[/red]")
        return []


def aggregate_flows(txs: list[dict]) -> dict:
    """Agrega flujos por token: total a exchanges vs desde exchanges."""
    flows = {}
    for tx in txs:
        sym = tx["symbol"]
        if sym not in flows:
            flows[sym] = {"to_exchange_usd": 0, "from_exchange_usd": 0, "unknown_usd": 0}
        if tx["direction"] == "TO_EXCHANGE":
            flows[sym]["to_exchange_usd"] += tx["amount_usd"]
        elif tx["direction"] == "FROM_EXCHANGE":
            flows[sym]["from_exchange_usd"] += tx["amount_usd"]
        else:
            flows[sym]["unknown_usd"] += tx["amount_usd"]
    return flows


def analyze_whale_flow(symbol: str, flows: dict, model) -> None:
    try:
        df = get_ohlcv(f"{symbol}-USD", days=3, timeframe="1h")
        ctx = df.tail(5).to_string()
    except Exception:
        ctx = "No data available"

    f = flows.get(symbol, {})
    to_ex = f.get("to_exchange_usd", 0)
    from_ex = f.get("from_exchange_usd", 0)
    net = from_ex - to_ex  # positivo = outflow neto = alcista

    user_content = f"""
Token: {symbol}
Time window: last 20 min

Exchange flows:
- TO exchange (sell pressure):   ${to_ex / 1e6:.1f}M
- FROM exchange (accumulation):  ${from_ex / 1e6:.1f}M
- NET outflow (positive = bullish): ${net / 1e6:+.1f}M

Market context (last 5 candles 1h):
{ctx}
"""
    resp = model.ask(SYSTEM_PROMPT, user_content)
    action, reason, confidence = parse_llm_action(resp.content)
    color = {"BUY": "green", "SELL": "red", "NOTHING": "dim"}.get(action, "white")
    console.print(
        f"  {symbol} | Inflow: ${to_ex/1e6:.1f}M | Outflow: ${from_ex/1e6:.1f}M | "
        f"[{color}]{action}[/{color}] {confidence}% | {reason}"
    )

    if action != "NOTHING" and confidence >= cfg.STRATEGY_MIN_CONFIDENCE:
        is_new = not SIGNALS_FILE.exists()
        with open(SIGNALS_FILE, "a", newline="") as f_:
            writer = csv.DictWriter(
                f_,
                fieldnames=["timestamp", "symbol", "to_exchange_usd", "from_exchange_usd",
                           "net_usd", "action", "confidence", "reason"],
            )
            if is_new:
                writer.writeheader()
            writer.writerow({
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "to_exchange_usd": to_ex,
                "from_exchange_usd": from_ex,
                "net_usd": net,
                "action": action,
                "confidence": confidence,
                "reason": reason,
            })


def main():
    model = ModelFactory().get()
    console.print(f"[bold]whale_agent[/bold] | {model.name} | monitor on-chain cada 20min")
    console.print(f"[dim]Threshold: ${WHALE_THRESHOLD_USD/1e6:.1f}M+ USD[/dim]")

    while True:
        console.rule("Whale Check")
        txs = fetch_whale_transactions()

        if not txs:
            console.print("[yellow]Sin transacciones de ballenas detectadas[/yellow]")
            time.sleep(CHECK_INTERVAL)
            continue

        # Mostrar transacciones individuales
        for tx in txs:
            dir_color = "red" if tx["direction"] == "TO_EXCHANGE" else "green" if tx["direction"] == "FROM_EXCHANGE" else "yellow"
            console.print(
                f"  [cyan]{tx['symbol']}[/cyan] "
                f"${tx['amount_usd']/1e6:.1f}M "
                f"[{dir_color}]{tx['direction']}[/{dir_color}] "
                f"{tx['from_owner']} -> {tx['to_owner']}"
            )

        # Agregar y analizar por token
        flows = aggregate_flows(txs)
        total_usd = sum(
            v["to_exchange_usd"] + v["from_exchange_usd"]
            for v in flows.values()
        )

        if total_usd > WHALE_THRESHOLD_USD:
            console.print(f"\n[yellow]Flujo total: ${total_usd/1e6:.1f}M — analizando...[/yellow]")
            for symbol in flows:
                if symbol in [t.upper() for t in cfg.MONITORED_TOKENS]:
                    analyze_whale_flow(symbol, flows, model)

        console.print(f"[dim]Proximo check en 20min...[/dim]")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
