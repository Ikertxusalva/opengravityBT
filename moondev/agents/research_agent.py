"""
research_agent — genera ideas de estrategias de trading.

Uso:
    python moondev/agents/research_agent.py           # loop continuo
    python moondev/agents/research_agent.py --test    # una idea y para
"""
import sys
import csv
import hashlib
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from moondev.core.model_factory import ModelFactory, clean_response
import moondev.config as cfg

SYSTEM_PROMPT = """You are an expert quantitative trading strategy researcher.
Generate ONE unique, specific trading strategy idea in 1-2 sentences.

Focus on:
- Technical indicators (RSI, MACD, Bollinger, Ichimoku, etc.)
- Volume patterns and anomalies
- Volatility-based entries
- Price action patterns (engulfing, divergence, breakout)
- Mean reversion vs trend following

Rules:
- Be specific about entry/exit conditions
- Mention timeframe and asset class
- NO generic descriptions like "buy low sell high"
- Response: ONLY the strategy idea, nothing else
"""

USER_PROMPT = "Generate a unique trading strategy idea."


def idea_hash(idea: str) -> str:
    return hashlib.md5(idea.encode()).hexdigest()


def load_seen_hashes(log_file: Path) -> set:
    if not log_file.exists():
        return set()
    with open(log_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["hash"] for row in reader}


def save_idea(idea: str, model_name: str, log_file: Path, ideas_file: Path) -> None:
    h = idea_hash(idea)
    # Append to CSV log
    is_new = not log_file.exists()
    with open(log_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["hash", "timestamp", "model", "idea"])
        if is_new:
            writer.writeheader()
        writer.writerow({
            "hash": h,
            "timestamp": datetime.now().isoformat(),
            "model": model_name,
            "idea": idea,
        })
    # Append to ideas.txt para rbi_agent
    with open(ideas_file, "a", encoding="utf-8") as f:
        f.write(f"{idea}\n")


def generate_idea(model) -> str:
    resp = model.ask(SYSTEM_PROMPT, USER_PROMPT, temperature=0.9, max_tokens=200)
    return clean_response(resp.content).strip()


def main(test_mode: bool = False):
    cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg.IDEAS_FILE.touch(exist_ok=True)

    model = ModelFactory().get()
    print(f"[research_agent] Usando modelo: {model.name}")

    while True:
        seen = load_seen_hashes(cfg.IDEAS_LOG)
        idea = generate_idea(model)

        if idea_hash(idea) in seen:
            print(f"[research_agent] Idea duplicada, regenerando...")
        else:
            save_idea(idea, model.name, cfg.IDEAS_LOG, cfg.IDEAS_FILE)
            print(f"\n[research_agent] Nueva idea guardada:\n  {idea}\n")

        if test_mode:
            break

        time.sleep(5)


if __name__ == "__main__":
    test_mode = "--test" in sys.argv
    main(test_mode=test_mode)
