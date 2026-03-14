"""
coingecko_agent — análisis macro dual-agent con memoria rolling.

Cada 30 min: Technical Agent (Haiku) + Fundamental Agent (Sonnet)
analizan BTC/ETH con datos CoinGecko. Synopsis se guarda en memoria.

Uso: python moondev/agents/coingecko_agent.py
Requiere: COINGECKO_API_KEY en config/env
"""
import sys, time, json
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
import moondev.config as cfg
from moondev.core.model_factory import ModelFactory
from rich.console import Console

console = Console()
CHECK_INTERVAL = 30 * 60
MEMORY_FILE = cfg.AGENT_MEMORY_DIR / "coingecko_agent.json"
MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
MAX_MEMORY_ROUNDS = 50

TECH_SYSTEM = """You are a technical analyst. Analyze the provided market data.
Focus on: price action, volume trends, support/resistance, indicators.
Output a concise technical analysis (3-5 sentences). Mention specific tokens."""

FUND_SYSTEM = """You are a fundamental analyst. Review the technical analysis provided
and add fundamental context: adoption, development activity, macro environment.
Output a concise fundamental perspective (3-5 sentences). Agree or disagree with technician."""

SYNOPSIS_SYSTEM = """Summarize this analysis round in 1-2 sentences.
Focus on actionable insights and tokens mentioned."""


def fetch_coin_data(coin_id: str) -> dict:
    headers = {"x-cg-pro-api-key": cfg.COINGECKO_API_KEY} if cfg.COINGECKO_API_KEY else {}
    try:
        resp = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}",
            params={"market_data": "true"},
            headers=headers,
            timeout=10,
        )
        data = resp.json()
        md = data.get("market_data", {})
        return {
            "name": data.get("name"),
            "price": md.get("current_price", {}).get("usd", 0),
            "change_24h": md.get("price_change_percentage_24h", 0),
            "change_7d": md.get("price_change_percentage_7d", 0),
            "market_cap": md.get("market_cap", {}).get("usd", 0),
            "volume": md.get("total_volume", {}).get("usd", 0),
        }
    except Exception as e:
        return {"name": coin_id, "error": str(e)}


def load_memory() -> list:
    if MEMORY_FILE.exists():
        return json.loads(MEMORY_FILE.read_text())
    return []


def save_memory(rounds: list) -> None:
    MEMORY_FILE.write_text(json.dumps(rounds[-MAX_MEMORY_ROUNDS:], indent=2))


def main():
    tech_model = ModelFactory().get("claude", "claude-haiku-4-5-20251001")
    fund_model = ModelFactory().get("claude", "claude-opus-4-5-20251101")
    console.print(f"[bold]coingecko_agent[/bold] | Tech: {tech_model.name} | Fund: {fund_model.name}")

    memory = load_memory()
    round_n = len(memory) + 1

    while True:
        console.rule(f"Ronda {round_n}")

        # Fetch data
        btc = fetch_coin_data("bitcoin")
        eth = fetch_coin_data("ethereum")
        market_data = f"""
BTC: ${btc['price']:,.0f} | 24h: {btc['change_24h']:.2f}% | 7d: {btc['change_7d']:.2f}%
ETH: ${eth['price']:,.0f} | 24h: {eth['change_24h']:.2f}% | 7d: {eth['change_7d']:.2f}%
"""
        # Contexto de rondas anteriores
        hist = "\n".join(f"Round {r['round']}: {r['synopsis']}" for r in memory[-5:])
        context = f"Previous analysis:\n{hist}\n\nCurrent data:\n{market_data}" if hist else market_data

        # Technical agent
        tech_resp = tech_model.ask(TECH_SYSTEM, context)
        console.print(f"[cyan][Technical][/cyan] {tech_resp.content[:300]}")

        # Fundamental agent (recibe análisis técnico)
        fund_input = f"Technical analysis:\n{tech_resp.content}\n\nMarket data:\n{market_data}"
        fund_resp = fund_model.ask(FUND_SYSTEM, fund_input)
        console.print(f"[magenta][Fundamental][/magenta] {fund_resp.content[:300]}")

        # Synopsis
        synopsis_input = f"Technical: {tech_resp.content}\nFundamental: {fund_resp.content}"
        syn_resp = tech_model.ask(SYNOPSIS_SYSTEM, synopsis_input)

        memory.append({
            "round": round_n,
            "timestamp": datetime.now().isoformat(),
            "synopsis": syn_resp.content.strip(),
        })
        save_memory(memory)
        console.print(f"[dim]Synopsis: {syn_resp.content.strip()}[/dim]")

        round_n += 1
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
