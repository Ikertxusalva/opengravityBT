"""
sentiment_agent — análisis de sentimiento Twitter con BERT.

Cada 15 min busca tweets por token y calcula score POS-NEG.
Alerta si |score| > 0.4 o cambio > 5%.

Uso: python moondev/agents/sentiment_agent.py
Deps extra: transformers torch  (pip install transformers torch)
"""
import sys, time, csv
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import moondev.config as cfg
from rich.console import Console

console = Console()
CHECK_INTERVAL = 15 * 60
SCORE_THRESHOLD = 0.4
CHANGE_THRESHOLD = 5.0
SENTIMENT_FILE = cfg.DATA_DIR / "sentiment_history.csv"


def load_sentiment_model():
    """Carga BERT sentiment model (requiere transformers + torch)."""
    try:
        from transformers import pipeline
        return pipeline(
            "sentiment-analysis",
            model="finiteautomata/bertweet-base-sentiment-analysis",
            device=-1,  # CPU
        )
    except ImportError:
        console.print("[yellow]transformers/torch no instalado. Usando modo mock.[/yellow]")
        return None


def score_tweets(texts: list[str], pipe) -> float:
    """Retorna score POS - NEG en rango [-1, 1]."""
    if not texts:
        return 0.0
    if pipe is None:
        # Mock: retorna 0
        return 0.0
    results = pipe(texts, batch_size=8, truncation=True, max_length=128)
    pos = sum(r["score"] for r in results if r["label"] == "POS")
    neg = sum(r["score"] for r in results if r["label"] == "NEG")
    n = len(results)
    return (pos - neg) / n if n else 0.0


def fetch_tweets_mock(token: str) -> list[str]:
    """
    Mock de búsqueda Twitter.
    Reemplazar con twikit o Tweepy cuando tengas acceso a API.
    """
    return [
        f"{token} looks bullish today",
        f"I'm buying more {token}",
        f"{token} might dump soon",
    ]


def save_score(token: str, score: float) -> None:
    is_new = not SENTIMENT_FILE.exists()
    with open(SENTIMENT_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "token", "score"])
        if is_new:
            w.writeheader()
        w.writerow({"timestamp": datetime.now().isoformat(), "token": token, "score": score})


def load_previous_score(token: str) -> float:
    if not SENTIMENT_FILE.exists():
        return 0.0
    cutoff = (datetime.now() - timedelta(minutes=30)).isoformat()
    rows = []
    with open(SENTIMENT_FILE) as f:
        for row in csv.DictReader(f):
            if row["token"] == token and row["timestamp"] >= cutoff:
                rows.append(float(row["score"]))
    return rows[0] if rows else 0.0


def main():
    pipe = load_sentiment_model()
    console.print(f"[bold]sentiment_agent[/bold] | BERT | {cfg.MONITORED_TOKENS}")

    while True:
        console.rule("Sentiment Check")
        for token in cfg.MONITORED_TOKENS:
            tweets = fetch_tweets_mock(token)
            score = score_tweets(tweets, pipe)
            prev = load_previous_score(token)
            change = abs(score - prev) * 100
            save_score(token, score)

            label = "very positive" if score > 0.3 else "slightly positive" if score > 0 \
                else "slightly negative" if score > -0.3 else "very negative"
            color = "green" if score > 0 else "red"
            console.print(f"[cyan]{token}[/cyan] [{color}]{score:.3f}[/{color}] ({label}) delta{change:.1f}%")

            if abs(score) > SCORE_THRESHOLD or change > CHANGE_THRESHOLD:
                console.print(f"  [bold yellow]ALERTA: sentimiento extremo o cambio brusco[/bold yellow]")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
