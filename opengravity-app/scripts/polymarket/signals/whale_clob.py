"""
Polymarket Whale Tracker (CLOB-native)
========================================
Detecta smart money en el CLOB de Polymarket analizando los trades recientes.

A diferencia del whale_agent de moondev (que sigue flujos on-chain de BTC/ETH),
este modulo trackea directamente a los traders grandes de Polymarket:

  - Trades grandes (>$1000 en una sola orden) = informacion valiosa
  - Clusteres de trades grandes en la misma direccion en <60min = smart money
  - Wallets que aparecen repetidamente en mercados ganaderos = whales conocidos

La API del CLOB de Polymarket es completamente publica.
Sin API key requerida.
"""

import httpx
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from statistics import mean
from typing import Optional

CLOB = "https://clob.polymarket.com"

# Whales conocidos de Polymarket (wallets publicamente identificadas)
# Se actualiza con el tiempo segun el historial de trades
KNOWN_WHALES: set = set()

# Umbral minimo para considerar "trade grande"
WHALE_TRADE_USD = 1_000    # $1k por trade
WHALE_CLUSTER_USD = 5_000  # $5k agregado en 1h = señal fuerte


def _parse_trade_usd(trade: dict) -> float:
    """Calcula el valor USD de un trade del CLOB."""
    size = float(trade.get("size", 0) or 0)
    price = float(trade.get("price", 0) or 0)
    return size * price


def _parse_ts(trade: dict) -> Optional[datetime]:
    """Parsea el timestamp de un trade a datetime UTC."""
    ts = trade.get("timestamp") or trade.get("created_at")
    if not ts:
        return None
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def fetch_recent_trades(condition_id: str, limit: int = 200) -> list:
    """Descarga los trades mas recientes de un mercado."""
    try:
        r = httpx.get(f"{CLOB}/trades",
                      params={"market": condition_id, "limit": limit},
                      timeout=12)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


def check_whale_activity(condition_id: str,
                         direction_hint: str = None,
                         lookback_hours: int = 2,
                         min_edge: float = 0.04) -> Optional[dict]:
    """
    Detecta actividad de ballenas en un mercado de Polymarket.

    Señales:
    1. Trade individual > WHALE_TRADE_USD
    2. Cluster de trades en misma direccion > WHALE_CLUSTER_USD en lookback_hours

    Retorna señal si smart money confirma o inicia una direccion clara.
    """
    trades = fetch_recent_trades(condition_id)
    if not trades:
        return None

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=lookback_hours)

    # Filtrar trades recientes con valor USD calculable
    recent = []
    for t in trades:
        ts = _parse_ts(t)
        if ts and ts >= cutoff:
            usd = _parse_trade_usd(t)
            if usd >= WHALE_TRADE_USD:
                recent.append({
                    "usd": usd,
                    "side": t.get("side", "").upper(),
                    "price": float(t.get("price", 0) or 0),
                    "maker": t.get("maker_address", ""),
                    "ts": ts,
                })

    if not recent:
        return None

    # Agregar por lado
    buy_usd = sum(t["usd"] for t in recent if t["side"] in ("BUY", "LONG"))
    sell_usd = sum(t["usd"] for t in recent if t["side"] in ("SELL", "SHORT"))
    total_usd = buy_usd + sell_usd

    if total_usd < WHALE_CLUSTER_USD:
        return None

    # Determinar direccion del smart money
    if buy_usd > sell_usd * 2:
        whale_direction = "BUY_YES"
    elif sell_usd > buy_usd * 2:
        whale_direction = "BUY_NO"
    else:
        return None  # flujo mixto, sin señal clara

    # Si tenemos un hint de direccion, verificar que coincide
    if direction_hint and whale_direction != direction_hint:
        # Smart money contradice nuestra señal → cancelar
        return {
            "source": "whale_clob",
            "edge": 0.0,
            "direction": whale_direction,
            "warning": f"Smart money va en contra de {direction_hint}",
            "buy_usd": round(buy_usd),
            "sell_usd": round(sell_usd),
            "n_trades": len(recent),
            "contradicts": True,
        }

    # Detectar whales conocidos
    unique_makers = set(t["maker"] for t in recent if t["maker"])
    known_in_trade = unique_makers & KNOWN_WHALES
    is_known_whale = len(known_in_trade) > 0

    # Edge proporcional al volumen y concentracion
    imbalance = abs(buy_usd - sell_usd) / total_usd  # 0-1
    edge = min(0.08, imbalance * 0.10)  # max 8% de edge adicional
    if is_known_whale:
        edge = min(0.12, edge * 1.5)  # boost si es whale conocido

    if edge < min_edge:
        return None

    return {
        "source": "whale_clob",
        "edge": round(edge, 4),
        "direction": whale_direction,
        "buy_usd": round(buy_usd),
        "sell_usd": round(sell_usd),
        "total_usd": round(total_usd),
        "n_whale_trades": len(recent),
        "unique_makers": len(unique_makers),
        "known_whale": is_known_whale,
        "imbalance": round(imbalance, 3),
        "contradicts": False,
    }


def update_known_whales(condition_id: str, threshold_usd: float = 10_000):
    """
    Actualiza la lista de whales conocidos basandose en trades historicos grandes.
    Llama ocasionalmente para mantener la lista actualizada.
    """
    trades = fetch_recent_trades(condition_id, limit=500)
    for t in trades:
        usd = _parse_trade_usd(t)
        maker = t.get("maker_address", "")
        if usd >= threshold_usd and maker:
            KNOWN_WHALES.add(maker)


def get_market_whale_summary(condition_id: str) -> dict:
    """Resumen de actividad de ballenas en un mercado para reporting."""
    trades = fetch_recent_trades(condition_id, limit=200)
    if not trades:
        return {"total_trades": 0}

    all_usd = [_parse_trade_usd(t) for t in trades]
    big_trades = [u for u in all_usd if u >= WHALE_TRADE_USD]

    return {
        "total_trades": len(trades),
        "whale_trades": len(big_trades),
        "whale_volume_usd": round(sum(big_trades)),
        "avg_trade_usd": round(mean(all_usd)) if all_usd else 0,
        "max_trade_usd": round(max(all_usd)) if all_usd else 0,
    }
