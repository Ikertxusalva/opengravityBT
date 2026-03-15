"""
Manifold Markets Signal
========================
Manifold es un mercado de prediccion con play-money pero forecasters serios.
Detecta mercados donde Manifold y Polymarket tienen precios muy diferentes.

El lag tipico: informacion se refleja en Manifold 5-30 min antes de Polymarket
porque los traders de Manifold reaccionan rapido sin riesgo de capital real.

Sin API key requerida.
"""

import httpx
import time
from typing import Optional

MANIFOLD_BASE = "https://api.manifold.markets/v0"

_manifold_cache: list = []
_manifold_cache_ts: float = 0
CACHE_TTL = 600  # 10 minutos


def _word_overlap(a: str, b: str) -> float:
    a_words = set(a.lower().split())
    b_words = set(b.lower().split())
    noise = {"the", "a", "an", "of", "to", "in", "is", "will", "be", "by",
             "or", "and", "for", "on", "at", "it", "as", "are", "was", "were",
             "before", "after", "above", "below", "between", "more", "less",
             "than", "with", "from", "over", "under", "into", "this", "that"}
    a_words -= noise
    b_words -= noise
    if not a_words or not b_words:
        return 0.0
    return len(a_words & b_words) / len(a_words | b_words)


def _fetch_manifold_markets(limit: int = 300) -> list:
    """Descarga mercados binarios activos de Manifold con cache."""
    global _manifold_cache, _manifold_cache_ts
    now = time.time()
    if _manifold_cache and (now - _manifold_cache_ts) < CACHE_TTL:
        return _manifold_cache

    try:
        r = httpx.get(f"{MANIFOLD_BASE}/markets",
                      params={"limit": limit, "sort": "last-bet-time"},
                      timeout=20)
        if r.status_code != 200:
            return []
        raw = r.json()
        if not isinstance(raw, list):
            return []
        markets = [
            m for m in raw
            if m.get("outcomeType") == "BINARY"
            and m.get("isResolved") is False
            and m.get("probability") is not None
            and float(m.get("volume", 0)) > 100
        ]
        _manifold_cache = markets
        _manifold_cache_ts = now
        return markets
    except Exception:
        return []


def check_manifold_signal(polymarket_question: str,
                          polymarket_price_yes: float,
                          min_edge: float = 0.07,
                          min_similarity: float = 0.40) -> Optional[dict]:
    """
    Busca en Manifold un mercado similar y detecta discrepancia de precio.

    Se usa un threshold de edge mas alto (7%) que para otras señales
    porque Manifold es play-money y tiene menos precision de precio.
    """
    markets = _fetch_manifold_markets()
    if not markets:
        return None

    best_score = 0.0
    best_market = None

    for m in markets:
        q = m.get("question", "")
        score = _word_overlap(polymarket_question, q)
        if score > best_score:
            best_score = score
            best_market = m

    if best_score < min_similarity or best_market is None:
        return None

    manifold_prob = float(best_market.get("probability", 0))
    if manifold_prob <= 0.01 or manifold_prob >= 0.99:
        return None

    edge = manifold_prob - polymarket_price_yes

    if abs(edge) < min_edge:
        return None

    direction = "BUY_YES" if edge > 0 else "BUY_NO"

    return {
        "source": "manifold_signal",
        "edge": round(abs(edge), 4),
        "direction": direction,
        "manifold_prob": round(manifold_prob, 4),
        "manifold_question": best_market.get("question", "")[:60],
        "manifold_volume": best_market.get("volume", 0),
        "polymarket_yes": round(polymarket_price_yes, 4),
        "similarity": round(best_score, 3),
    }
