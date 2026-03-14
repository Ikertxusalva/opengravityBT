"""
news_agent — analista de noticias crypto en tiempo real.

Cada 10 min obtiene noticias recientes via CryptoCompare/CoinStats.
LLM clasifica impacto (alto/medio/bajo) y dirección (alcista/bajista).
Alerta cuando detecta eventos que mueven precio.

Categorías de impacto:
  - ALTO: regulación, hacks, ETF, hard fork → acción inmediata
  - MEDIO: partnerships, listings, upgrades → monitorear
  - BAJO: ruido, opiniones, análisis genérico → ignorar

Uso: python moondev/agents/news_agent.py
"""
import sys
import time
import csv
import hashlib
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
from moondev.core.model_factory import ModelFactory
from moondev.core.nice_funcs import parse_llm_action
import moondev.config as cfg
from rich.console import Console

console = Console()
CHECK_INTERVAL = 10 * 60  # 10 minutos
DATA_DIR = cfg.DATA_DIR / "news"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SEEN_FILE = DATA_DIR / "seen_news.txt"
SIGNALS_FILE = DATA_DIR / "news_signals.csv"

MAX_SEEN = 500   # máximo hashes guardados

SYSTEM_PROMPT = """You are a crypto news impact analyst.
Analyze the following news headline and determine its market impact.

Classification rules:
- HACK/EXPLOIT = HIGH BEARISH (immediate risk)
- ETF APPROVAL/REJECTION = HIGH (direction depends)
- REGULATORY BAN = HIGH BEARISH
- INSTITUTIONAL ADOPTION = MEDIUM-HIGH BULLISH
- NEW EXCHANGE LISTING = MEDIUM BULLISH for that token
- FUD without source = LOW (potential contrarian BUY)
- Generic analysis/opinion = IGNORE

Respond in exactly 3 lines:
Line 1: BUY, SELL, or NOTHING
Line 2: Impact level + reason (e.g., "HIGH BEARISH: major hack detected")
Line 3: Confidence: X%

If impact is LOW or news is old/generic, say NOTHING.
"""

CRYPTOCOMPARE_URL = "https://min-api.cryptocompare.com/data/v2/news/"


def load_seen() -> set:
    if not SEEN_FILE.exists():
        return set()
    return set(SEEN_FILE.read_text().splitlines())


def save_seen(seen: set) -> None:
    # Mantener solo los ultimos MAX_SEEN
    recent = list(seen)[-MAX_SEEN:]
    SEEN_FILE.write_text("\n".join(recent))


def news_hash(title: str) -> str:
    return hashlib.md5(title.encode()).hexdigest()[:12]


def fetch_news(tokens: list[str]) -> list[dict]:
    """Obtiene noticias recientes de CryptoCompare (sin API key para primeras llamadas)."""
    articles = []
    for token in tokens[:3]:  # máximo 3 tokens para no saturar
        try:
            resp = requests.get(
                CRYPTOCOMPARE_URL,
                params={"categories": token, "excludeCategories": "Sponsored"},
                timeout=10,
            )
            data = resp.json()
            for item in data.get("Data", [])[:5]:  # top 5 por token
                articles.append({
                    "title": item.get("title", ""),
                    "body": item.get("body", "")[:300],
                    "url": item.get("url", ""),
                    "source": item.get("source", ""),
                    "published_at": item.get("published_on", 0),
                    "token": token,
                })
        except Exception as e:
            console.print(f"[red]News API error ({token}): {e}[/red]")
    return articles


def is_high_impact_keyword(title: str) -> bool:
    """Detecta palabras clave de alto impacto para pre-filtrar."""
    keywords = [
        "hack", "exploit", "breach", "stolen", "drained",
        "etf approved", "etf rejected", "etf approval",
        "sec", "regulation", "ban", "illegal",
        "bankruptcy", "insolvency", "shut down",
        "partnership", "acquisition", "launch",
        "upgrade", "hard fork", "mainnet",
        "institutional", "billion", "major",
    ]
    title_lower = title.lower()
    return any(kw in title_lower for kw in keywords)


def analyze_news(article: dict, model) -> None:
    user_content = f"""
Headline: {article['title']}
Source: {article['source']}
Token context: {article['token']}
Summary: {article['body'][:200]}
"""
    resp = model.ask(SYSTEM_PROMPT, user_content)
    action, reason, confidence = parse_llm_action(resp.content)

    if action == "NOTHING":
        return  # No mostrar ruido

    color = {"BUY": "green", "SELL": "red"}.get(action, "dim")
    console.print(f"\n  [{color}]{action}[/{color}] {confidence}% | {reason}")
    console.print(f"  [link]{article['url']}[/link]")

    if confidence >= cfg.STRATEGY_MIN_CONFIDENCE:
        is_new = not SIGNALS_FILE.exists()
        with open(SIGNALS_FILE, "a", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["timestamp", "token", "title", "source",
                           "action", "confidence", "reason", "url"],
            )
            if is_new:
                writer.writeheader()
            writer.writerow({
                "timestamp": datetime.now().isoformat(),
                "token": article["token"],
                "title": article["title"],
                "source": article["source"],
                "action": action,
                "confidence": confidence,
                "reason": reason,
                "url": article["url"],
            })


def main():
    model = ModelFactory().get()
    console.print(f"[bold]news_agent[/bold] | {model.name} | {cfg.MONITORED_TOKENS} | check cada 10min")

    seen = load_seen()

    while True:
        console.rule("News Check")
        articles = fetch_news(cfg.MONITORED_TOKENS)
        new_count = 0

        for article in articles:
            h = news_hash(article["title"])
            if h in seen:
                continue

            seen.add(h)
            new_count += 1

            # Pre-filtrar: solo analizar noticias con keywords de impacto
            if is_high_impact_keyword(article["title"]):
                console.print(f"[yellow]IMPACTO POTENCIAL:[/yellow] {article['title'][:80]}")
                analyze_news(article, model)
            else:
                console.print(f"[dim]{article['token']} | {article['title'][:70]}...[/dim]")

        console.print(f"[dim]{new_count} noticias nuevas procesadas[/dim]")
        save_seen(seen)

        console.print(f"[dim]Proximo check en 10min...[/dim]")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
