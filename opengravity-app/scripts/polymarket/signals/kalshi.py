"""
Kalshi Arbitrage Signal
========================
Compara precios de Kalshi con Polymarket para detectar discrepancias.
Kalshi es un exchange regulado (CFTC) — sus precios son de alta calidad.

Edge = |P(kalshi) - P(polymarket)| > MIN_EDGE
Sin API key requerida.
"""

import httpx
import time
from typing import Optional

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
HEADERS = {"accept": "application/json"}

# Cache en memoria para no hacer demasiadas llamadas
_kalshi_cache: dict = {}
_cache_ts: float = 0
CACHE_TTL = 300  # 5 minutos

# Mapeo: keywords en preguntas → series tickers de Kalshi
# Permite buscar mercados relevantes sin depender de matching de texto completo
KEYWORD_TO_SERIES = {
    "fed": "KXFED", "federal funds": "KXFED", "interest rate": "KXFED",
    "fomc": "KXFED", "rate cut": "KXFED", "rate hike": "KXFED",
    "s&p": "INXAB", "sp500": "INXAB", "stock market": "INXAB",
    "xrp": "KXXRP", "ripple": "KXXRP",
    "nfl": "KXNFLDRAFTPICK", "nba draft": "KXNBADRAFT2",
    "pope": "KXNEWPOPE",
    "mars": "KXELONMARS", "elon": "KXELONMARS",
    "supervolcano": "KXERUPTSUPER",
    "warming": "KXWARMING", "climate": "KXWARMING",
}


def _word_overlap(a: str, b: str) -> float:
    """Score de similitud entre dos strings por overlap de palabras. 0-1."""
    a_words = set(a.lower().split())
    b_words = set(b.lower().split())
    # Quitar stopwords cortas
    noise = {"the", "a", "an", "of", "to", "in", "is", "will", "be", "by",
             "or", "and", "for", "on", "at", "it", "as", "are", "was", "were",
             "before", "after", "above", "below", "between", "more", "less",
             "than", "with", "from", "over", "under", "into", "this", "that"}
    a_words -= noise
    b_words -= noise
    if not a_words or not b_words:
        return 0.0
    intersection = len(a_words & b_words)
    union = len(a_words | b_words)
    return intersection / union


def _fetch_kalshi_markets_by_series(series_ticker: str) -> list:
    """Descarga mercados de una serie específica de Kalshi."""
    try:
        r = httpx.get(f"{KALSHI_BASE}/markets",
                      params={"limit": 50, "series_ticker": series_ticker},
                      headers=HEADERS, timeout=12)
        if r.status_code != 200:
            return []
        return r.json().get("markets", [])
    except Exception:
        return []


def _fetch_kalshi_markets(question: str = "", limit: int = 50) -> list:
    """
    Descarga mercados de Kalshi relevantes para la pregunta.
    1. Busca por keywords → series tickers conocidos
    2. Fallback: mercados generales activos
    """
    global _kalshi_cache, _cache_ts
    now = time.time()

    # Determinar qué series buscar
    q_lower = question.lower()
    series_to_fetch = set()
    for kw, series in KEYWORD_TO_SERIES.items():
        if kw in q_lower:
            series_to_fetch.add(series)

    all_markets = []

    # Buscar en series relevantes
    for series in series_to_fetch:
        cache_key = f"series_{series}"
        if cache_key in _kalshi_cache and (now - _cache_ts) < CACHE_TTL:
            all_markets.extend(_kalshi_cache[cache_key])
        else:
            markets = _fetch_kalshi_markets_by_series(series)
            _kalshi_cache[cache_key] = markets
            all_markets.extend(markets)

    # Si no hay series matches, usar cache general o skip
    if not all_markets:
        if "general" in _kalshi_cache and (now - _cache_ts) < CACHE_TTL:
            return _kalshi_cache["general"]
        # No hacer call general — demasiados MV markets inútiles
        return []

    _cache_ts = now
    return all_markets


def find_kalshi_match(polymarket_question: str,
                      min_similarity: float = 0.25) -> Optional[dict]:
    """
    Busca el mercado de Kalshi más similar a la pregunta de Polymarket.
    Retorna el mercado Kalshi si hay coincidencia suficiente.
    """
    kalshi_markets = _fetch_kalshi_markets(polymarket_question)
    if not kalshi_markets:
        return None

    best_score = 0.0
    best_market = None

    for km in kalshi_markets:
        title = km.get("title", "") or km.get("subtitle", "") or ""
        subtitle = km.get("yes_sub_title", "") or ""
        combined = f"{title} {subtitle}"
        score = _word_overlap(polymarket_question, combined)
        if score > best_score:
            best_score = score
            best_market = km

    if best_score >= min_similarity and best_market:
        return {"market": best_market, "similarity": round(best_score, 3)}
    return None


def get_kalshi_probability(ticker: str) -> Optional[float]:
    """Obtiene la probabilidad YES de un mercado Kalshi por su ticker."""
    try:
        r = httpx.get(f"{KALSHI_BASE}/markets/{ticker}",
                      headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        m = r.json().get("market", {})
        yes_ask = m.get("yes_ask_dollars")
        yes_bid = m.get("yes_bid_dollars")
        if yes_ask is not None and yes_bid is not None:
            return (float(yes_ask) + float(yes_bid)) / 2
        elif yes_ask is not None:
            return float(yes_ask)
        return None
    except Exception:
        return None


def check_kalshi_arb(polymarket_question: str,
                     polymarket_price_yes: float,
                     min_edge: float = 0.05) -> Optional[dict]:
    """
    Señal de arbitraje Kalshi vs Polymarket.

    Si ya encontramos mercados en la misma serie (por keyword match),
    usamos similarity mínima de 0.10 porque el filtro de serie ya garantiza relevancia.
    """
    # Saber si hay match por keyword (serie pre-filtrada)
    q_lower = polymarket_question.lower()
    has_series_match = any(kw in q_lower for kw in KEYWORD_TO_SERIES)
    min_sim = 0.10 if has_series_match else 0.30

    match = find_kalshi_match(polymarket_question, min_similarity=min_sim)
    if not match:
        return None

    km = match["market"]
    ticker = km.get("ticker", "")
    similarity = match["similarity"]

    # Precio de Kalshi
    yes_ask = km.get("yes_ask_dollars")
    yes_bid = km.get("yes_bid_dollars")
    if yes_ask is None:
        return None

    try:
        yes_ask_f = float(yes_ask)
        yes_bid_f = float(yes_bid) if yes_bid is not None else yes_ask_f
    except (TypeError, ValueError):
        return None

    # Kalshi: YES ask > 0.99 o < 0.01 = mercado sin liquidez
    if yes_ask_f >= 0.99 or yes_ask_f <= 0.01:
        return None

    kalshi_mid = (yes_ask_f + yes_bid_f) / 2
    edge = kalshi_mid - polymarket_price_yes  # positivo = Kalshi dice YES más probable

    if abs(edge) < min_edge:
        return None

    # Sólo señal si la similitud es razonable
    if similarity < 0.25:
        return None

    direction = "BUY_YES" if edge > 0 else "BUY_NO"

    return {
        "source": "kalshi_arb",
        "edge": round(abs(edge), 4),
        "direction": direction,
        "kalshi_ticker": ticker,
        "kalshi_title": km.get("title", "")[:60],
        "kalshi_mid": round(kalshi_mid, 4),
        "polymarket_yes": round(polymarket_price_yes, 4),
        "similarity": similarity,
    }


def get_all_kalshi_stats() -> dict:
    """Resumen de mercados Kalshi disponibles por categoría."""
    markets = _fetch_kalshi_markets()
    total = len(markets)
    series = {}
    for m in markets:
        ticker = m.get("event_ticker", "UNKNOWN")
        prefix = ticker[:4] if ticker else "?"
        series[prefix] = series.get(prefix, 0) + 1
    return {"total": total, "by_prefix": dict(sorted(series.items(),
            key=lambda x: x[1], reverse=True)[:10])}
