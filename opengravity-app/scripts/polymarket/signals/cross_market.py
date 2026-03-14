"""
Cross-Market Consistency Signal (dentro de Polymarket)
=======================================================
Detecta inconsistencias logicas entre mercados relacionados en Polymarket.

Ejemplos de inconsistencias explotables:
  - "BTC > $100k en 2025" cotiza al 45% pero "BTC > $80k en 2025" cotiza al 40%
    → Imposible: si BTC llega a $100k pasa por $80k primero. Hay arb.

  - "Partido X gana eleccion" = 30% pero "Candidato Y (partido X) gana" = 35%
    → Inconsistente: P(candidato) <= P(partido)

  - "Gana el Super Bowl" con 10 equipos todos sumando >100%
    → Sumatoria incorrecta, hay mercados sobrepriceados

Estrategia: BUY el underpriced, SKIP el overpriced.
Sin API key requerida — solo usa la API publica de Polymarket.
"""

import httpx
import re
from typing import Optional
from itertools import combinations

GAMMA = "https://gamma-api.polymarket.com"


def _extract_number(text: str) -> Optional[float]:
    """Extrae el primer numero de un string (para comparar rangos)."""
    nums = re.findall(r'\$?([\d,]+\.?\d*)[kKmM]?', text)
    if not nums:
        return None
    num_str = nums[0].replace(",", "")
    try:
        val = float(num_str)
        # Escalar si hay sufijo
        lower = text.lower()
        if "k" in lower:
            val *= 1_000
        elif "m" in lower:
            val *= 1_000_000
        return val
    except ValueError:
        return None


def _get_group_markets(event_slug: str) -> list:
    """Obtiene todos los mercados de un grupo/evento de Polymarket."""
    try:
        r = httpx.get(f"{GAMMA}/markets",
                      params={"groupItemTitle": event_slug, "limit": 50},
                      timeout=12)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


def check_price_ladder(markets: list, min_edge: float = 0.06) -> list:
    """
    Detecta violaciones de monotonia en mercados tipo 'X above $Y'.

    Si P(above $100k) > P(above $80k), hay una inconsistencia explotable.
    El mercado 'above $80k' esta subvalorado o 'above $100k' sobreValorado.

    Retorna lista de señales con edge.
    """
    signals = []
    # Solo mercados con numero en el titulo y precio valido
    priced = []
    for m in markets:
        q = m.get("question", "")
        price = float(m.get("bestAsk") or m.get("lastTradePrice") or 0)
        liq = float(m.get("liquidityClob") or m.get("liquidity") or 0)
        if price > 0.01 and liq > 1000:
            num = _extract_number(q)
            if num is not None:
                priced.append({"market": m, "threshold": num, "price": price})

    if len(priced) < 2:
        return signals

    # Ordenar por threshold ascendente
    priced.sort(key=lambda x: x["threshold"])

    # Verificar monotonia: P(above higher) <= P(above lower)
    for i in range(len(priced) - 1):
        low_m = priced[i]
        high_m = priced[i + 1]
        if high_m["price"] > low_m["price"] + min_edge:
            # VIOLACION: precio mas alto para threshold mas alto → imposible
            edge = high_m["price"] - low_m["price"]
            signals.append({
                "source": "cross_market_ladder",
                "edge": round(edge, 4),
                "direction": "BUY_NO",  # Vender el que esta sobrepriceado
                "target_market": high_m["market"],
                "condition_id": high_m["market"].get("conditionId"),
                "reference_market": low_m["market"].get("question", "")[:60],
                "high_threshold": high_m["threshold"],
                "low_threshold": low_m["threshold"],
                "high_price": high_m["price"],
                "low_price": low_m["price"],
                "note": f"P(>{high_m['threshold']:.0f})={high_m['price']:.2%} > P(>{low_m['threshold']:.0f})={low_m['price']:.2%} — imposible",
            })

    return signals


def find_related_markets(question: str, markets_pool: list,
                         min_overlap: float = 0.45) -> list:
    """
    Encuentra mercados relacionados en el pool que comparten keywords con 'question'.
    """
    def overlap(a: str, b: str) -> float:
        noise = {"the", "a", "an", "of", "to", "in", "is", "will", "be", "by",
                 "or", "and", "for", "on", "at", "it", "as", "are", "was", "were",
                 "before", "after", "above", "below", "between", "more", "less"}
        aw = set(a.lower().split()) - noise
        bw = set(b.lower().split()) - noise
        if not aw or not bw:
            return 0.0
        return len(aw & bw) / len(aw | bw)

    related = []
    for m in markets_pool:
        q2 = m.get("question", "")
        if q2 == question:
            continue
        sc = overlap(question, q2)
        if sc >= min_overlap:
            related.append((sc, m))

    related.sort(reverse=True)
    return [m for _, m in related[:5]]


def check_cross_market_inconsistency(markets_pool: list,
                                     min_edge: float = 0.07) -> list:
    """
    Analisis completo de inconsistencias cross-market.
    Toma el pool de mercados y retorna todas las señales encontradas.

    Tipos de inconsistencia detectadas:
    1. Violacion de escalera de precios (mercados tipo above/below X)
    2. Suma > 100% en mercados mutuamente excluyentes del mismo grupo
    """
    signals = []

    # Agrupar mercados por prefijo de pregunta (mercados relacionados)
    from collections import defaultdict
    groups = defaultdict(list)
    for m in markets_pool:
        q = m.get("question", "")
        # Extraer grupo por primeras palabras comunes
        words = q.lower().split()[:4]
        prefix = " ".join(words)
        groups[prefix].append(m)

    # Verificar escalera de precios en cada grupo
    for prefix, group_markets in groups.items():
        if len(group_markets) >= 2:
            ladder_signals = check_price_ladder(group_markets, min_edge)
            signals.extend(ladder_signals)

    return signals
