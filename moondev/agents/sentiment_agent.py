"""
sentiment_agent — análisis de sentimiento Twitter con BERT.

Cada 15 min busca tweets por token y calcula score POS-NEG.
Alerta si |score| > 0.4 o cambio > 5%.

IMPORTANTE: fetch_tweets_mock() devuelve datos FICTICIOS.
El score resultante es siempre ~0 y NO debe usarse como señal real.
Cuando is_mock=True en sentiment_signals.json, execution_agent ignora la señal.

Uso: python moondev/agents/sentiment_agent.py
Deps extra: transformers torch  (pip install transformers torch)
Para tweets reales: instalar twikit o Tweepy + credenciales Twitter API.
"""
import sys, time, csv, json
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
SENTIMENT_SIGNALS_FILE = cfg.DATA_DIR / "sentiment_signals.json"

# Flag global: True cuando no hay acceso a Twitter API real
_USING_MOCK_TWEETS = True


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
    ⚠️  DATOS FICTICIOS — NO usar como señal de trading.
    Reemplazar con twikit o Tweepy cuando tengas acceso a Twitter API.
    Mientras tanto, execution_agent ignora estas señales (is_mock=True).
    """
    return [
        f"{token} looks bullish today",
        f"I'm buying more {token}",
        f"{token} might dump soon",
    ]


def save_score(token: str, score: float, is_mock: bool) -> None:
    is_new = not SENTIMENT_FILE.exists()
    with open(SENTIMENT_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "token", "score", "is_mock"])
        if is_new:
            w.writeheader()
        w.writerow({"timestamp": datetime.now().isoformat(), "token": token, "score": score, "is_mock": is_mock})


def save_signals(scores: dict[str, float], is_mock: bool) -> None:
    """Escribe sentiment_signals.json que lee execution_agent.
    Cuando is_mock=True, execution_agent debe ignorar esta señal."""
    payload = {
        "timestamp": datetime.now().isoformat(),
        "is_mock": is_mock,
        "scores": scores,
    }
    SENTIMENT_SIGNALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SENTIMENT_SIGNALS_FILE, "w") as f:
        json.dump(payload, f, indent=2)


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
    mock_tag = "[bold red][MOCK — señal ignorada por execution_agent][/bold red]" if _USING_MOCK_TWEETS else ""
    console.print(f"[bold]sentiment_agent[/bold] | BERT | {cfg.MONITORED_TOKENS} {mock_tag}")

    while True:
        console.rule("Sentiment Check")
        if _USING_MOCK_TWEETS:
            console.print("[red]⚠ MODO MOCK — tweets ficticios, señal inactiva en ejecución[/red]")

        cycle_scores: dict[str, float] = {}
        for token in cfg.MONITORED_TOKENS:
            tweets = fetch_tweets_mock(token)
            score = score_tweets(tweets, pipe)
            prev = load_previous_score(token)
            change = abs(score - prev) * 100
            save_score(token, score, is_mock=_USING_MOCK_TWEETS)
            cycle_scores[token] = score

            label = "very positive" if score > 0.3 else "slightly positive" if score > 0 \
                else "slightly negative" if score > -0.3 else "very negative"
            color = "green" if score > 0 else "red"
            console.print(f"[cyan]{token}[/cyan] [{color}]{score:.3f}[/{color}] ({label}) delta{change:.1f}%")

            if abs(score) > SCORE_THRESHOLD or change > CHANGE_THRESHOLD:
                console.print(f"  [bold yellow]ALERTA: sentimiento extremo o cambio brusco[/bold yellow]")

        save_signals(cycle_scores, is_mock=_USING_MOCK_TWEETS)
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
