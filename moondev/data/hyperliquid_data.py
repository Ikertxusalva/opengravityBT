"""
hyperliquid_data.py — Fuente de verdad unica para TODOS los datos de HyperLiquid.

Centraliza: OHLCV, funding, liquidaciones, orderbook, posiciones, precios, metadata.
Todos los demas modulos del proyecto deben importar desde aqui en vez de llamar a la API
directamente.

Uso:
    from moondev.data.hyperliquid_data import (
        get_ohlcv, get_funding_history, get_funding_snapshot,
        get_mid_prices, get_mark_prices, get_markets_meta,
        get_orderbook, get_recent_liquidations, get_liquidations_multi,
        get_user_positions, get_account_state,
        get_leaderboard, get_top_leveraged,
        HL_CRYPTO, BASE_URL, WS_URL,
    )
"""
from __future__ import annotations

import concurrent.futures
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────

BASE_URL = "https://api.hyperliquid.xyz/info"
WS_URL = "wss://api.hyperliquid.xyz/ws"
_HEADERS = {"Content-Type": "application/json"}

HL_CRYPTO = [
    "BTC", "ETH", "SOL", "BNB", "AVAX",
    "LINK", "DOT", "ADA", "DOGE", "ARB",   # MATIC eliminado: delisted de yfinance (2026-03)
    "OP", "SUI", "APT", "INJ", "WIF",
    "PEPE", "HYPE", "TIA", "SEI", "TON",
]

VALID_INTERVALS = {"1m", "5m", "15m", "1h", "4h", "1d"}

_INTERVAL_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}

TOP_COINS = ["BTC", "ETH", "SOL", "ARB", "AVAX", "DOGE", "LINK", "OP"]


# ── Transporte ────────────────────────────────────────────────────────────────

def _post(payload: dict, timeout: int = 15, retries: int = 2) -> dict | list:
    """POST a la API REST de HyperLiquid con retry basico."""
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(BASE_URL, json=payload, headers=_HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    raise last_err  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. OHLCV
# ═══════════════════════════════════════════════════════════════════════════════

def _fetch_candle_batch(coin: str, interval: str, start_ms: int, end_ms: int) -> list[dict]:
    payload = {
        "type": "candleSnapshot",
        "req": {"coin": coin.upper(), "interval": interval,
                "startTime": start_ms, "endTime": end_ms},
    }
    data = _post(payload)
    return data if isinstance(data, list) else []


def get_ohlcv(
    coin: str, interval: str = "1h", days: int = 365,
) -> Optional[pd.DataFrame]:
    """
    OHLCV desde HyperLiquid con paginacion automatica.

    Returns:
        DataFrame con DatetimeIndex UTC y columnas Open, High, Low, Close, Volume.
        None si no hay datos suficientes (< 10 barras).
    """
    if interval not in VALID_INTERVALS:
        return None

    bar_ms = _INTERVAL_MS[interval]
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86_400_000
    block_ms = bar_ms * 4000

    all_candles: list[dict] = []
    cursor = start_ms
    while cursor < end_ms:
        chunk_end = min(cursor + block_ms, end_ms)
        try:
            batch = _fetch_candle_batch(coin, interval, cursor, chunk_end)
        except Exception:
            break
        if batch:
            all_candles.extend(batch)
        cursor = chunk_end + bar_ms
        if cursor >= end_ms:
            break

    if not all_candles or len(all_candles) < 10:
        return None

    df = pd.DataFrame(all_candles).drop_duplicates(subset=["t"])
    df["datetime"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df.set_index("datetime")
    df = df.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
    df = df[["Open", "High", "Low", "Close", "Volume"]].astype(float).sort_index().dropna()
    return df if len(df) >= 10 else None


def get_candles_short(coin: str, interval: str = "1h", count: int = 100) -> dict:
    """Ultimas N velas (sin paginacion). Retorna dict con metadata."""
    if interval not in _INTERVAL_MS:
        return {"error": f"Intervalo invalido: {interval}"}
    bar_ms = _INTERVAL_MS[interval]
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - bar_ms * count
    try:
        data = _post({
            "type": "candleSnapshot",
            "req": {"coin": coin.upper(), "interval": interval,
                    "startTime": start_ms, "endTime": end_ms},
        })
        candles = data if isinstance(data, list) else []
        return {
            "coin": coin.upper(),
            "interval": interval,
            "count": len(candles),
            "candles": [
                {"t": c.get("t"), "o": c.get("o"), "h": c.get("h"),
                 "l": c.get("l"), "c": c.get("c"), "v": c.get("v")}
                for c in candles[-10:]
            ],
            "latest_close": candles[-1].get("c") if candles else None,
        }
    except Exception as e:
        logger.warning("get_candles_short(%s) error: %s", coin, e)
        return {"coin": coin.upper(), "interval": interval,
                "count": 0, "candles": [], "latest_close": None}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Funding
# ═══════════════════════════════════════════════════════════════════════════════

def get_funding_history(coin: str, days: int = 90) -> Optional[pd.DataFrame]:
    """
    Funding rates historicos desde HyperLiquid.
    Retorna DataFrame con columna 'funding_rate' y DatetimeIndex UTC.
    """
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86_400_000
    try:
        data = _post({"type": "fundingHistory", "coin": coin.upper(), "startTime": start_ms})
    except Exception:
        return None

    if not data or not isinstance(data, list):
        return None

    df = pd.DataFrame(data)
    df["datetime"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df = df.set_index("datetime")
    df["funding_rate"] = df["fundingRate"].astype(float)
    return df[["funding_rate"]].sort_index()


def get_funding_snapshot(tokens: list[str] | None = None) -> dict[str, dict]:
    """
    Funding rates actuales de todos los coins (o filtrado por tokens).

    Returns:
        {coin: {"hourly": float, "annual": float, "open_interest": str, ...}}
    """
    try:
        data = _post({"type": "metaAndAssetCtxs"})
        if not isinstance(data, list) or len(data) < 2:
            return {}
        universe = data[0].get("universe", [])
        ctxs = data[1]

        rates: dict[str, dict] = {}
        for i, asset in enumerate(universe):
            name = asset.get("name", "")
            if tokens and name not in tokens:
                continue
            if i >= len(ctxs):
                break
            ctx = ctxs[i]
            funding = float(ctx.get("funding", 0))
            rates[name] = {
                "hourly": funding,
                "annual": funding * 24 * 365 * 100,
                "open_interest": ctx.get("openInterest"),
                "prev_day_px": ctx.get("prevDayPx"),
                "day_ntl_vlm": ctx.get("dayNtlVlm"),
                "premium": ctx.get("premium"),
                "mark_px": ctx.get("markPx"),
                "mid_px": ctx.get("midPx"),
            }
        return rates
    except Exception as e:
        logger.warning("get_funding_snapshot error: %s", e)
        return {}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Precios
# ═══════════════════════════════════════════════════════════════════════════════

def get_mid_prices() -> dict[str, float]:
    """Precios mid de todos los perpetuals. Retorna {coin: price}."""
    try:
        data = _post({"type": "allMids"})
        if isinstance(data, dict):
            return {k: float(v) for k, v in data.items() if v}
        return {}
    except Exception as e:
        logger.warning("get_mid_prices error: %s", e)
        return {}


def get_mark_prices() -> dict[str, float]:
    """Precios mark de todos los perpetuals. Retorna {coin: markPx}."""
    try:
        data = _post({"type": "metaAndAssetCtxs"})
        if not isinstance(data, list) or len(data) < 2:
            return {}
        universe = data[0].get("universe", [])
        ctxs = data[1]
        return {
            name: float(ctxs[i]["markPx"])
            for i, m in enumerate(universe)
            if i < len(ctxs) and ctxs[i].get("markPx") and (name := m.get("name"))
        }
    except Exception as e:
        logger.warning("get_mark_prices error: %s", e)
        return {}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Metadata
# ═══════════════════════════════════════════════════════════════════════════════

def get_markets_meta() -> dict:
    """Metadata de todos los mercados. Retorna {markets: [{name, sz_decimals, max_leverage}]}."""
    try:
        data = _post({"type": "meta"})
        universe = data.get("universe", [])
        return {
            "markets": [
                {
                    "name": m.get("name"),
                    "sz_decimals": m.get("szDecimals"),
                    "max_leverage": m.get("maxLeverage"),
                }
                for m in universe
            ]
        }
    except Exception as e:
        logger.warning("get_markets_meta error: %s", e)
        return {"markets": []}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Orderbook
# ═══════════════════════════════════════════════════════════════════════════════

def get_orderbook(coin: str, depth: int = 5) -> dict:
    """Orderbook L2. Retorna {coin, bids: [{px, sz}], asks: [{px, sz}]}."""
    try:
        data = _post({"type": "l2Book", "coin": coin.upper()})
        levels = data.get("levels", [[], []])
        bids = levels[0][:depth] if levels else []
        asks = levels[1][:depth] if len(levels) > 1 else []
        return {
            "coin": coin.upper(),
            "bids": [{"px": b["px"], "sz": b["sz"]} for b in bids],
            "asks": [{"px": a["px"], "sz": a["sz"]} for a in asks],
        }
    except Exception as e:
        logger.warning("get_orderbook(%s) error: %s", coin, e)
        return {"coin": coin.upper(), "bids": [], "asks": []}


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Liquidaciones
# ═══════════════════════════════════════════════════════════════════════════════

def get_recent_liquidations(coin: str) -> list[dict]:
    """
    Liquidaciones recientes para un coin (via recentTrades).
    Retorna lista de {coin, side, usd_size, px, sz, time_ms, tid, source}.
    """
    try:
        trades = _post({"type": "recentTrades", "coin": coin.upper()})
        if not isinstance(trades, list):
            return []
        result = []
        for t in trades:
            if "liquidation" not in t:
                continue
            side_raw = t.get("side", "")
            side = "LONG" if side_raw == "A" else "SHORT"
            try:
                usd_size = float(t.get("px", 0)) * float(t.get("sz", 0))
            except (TypeError, ValueError):
                usd_size = 0.0
            result.append({
                "coin": coin.upper(),
                "side": side,
                "usd_size": usd_size,
                "px": t.get("px", "0"),
                "sz": t.get("sz", "0"),
                "time_ms": t.get("time", 0),
                "tid": t.get("tid", 0),
                "source": "hyperliquid",
            })
        return result
    except Exception as e:
        logger.warning("get_recent_liquidations(%s) error: %s", coin, e)
        return []


def get_liquidations_multi(coins: list[str] | None = None) -> list[dict]:
    """Liquidaciones de multiples coins, ordenadas por tiempo descendente."""
    if coins is None:
        coins = TOP_COINS
    all_liqs: list[dict] = []
    for coin in coins:
        all_liqs.extend(get_recent_liquidations(coin))
    all_liqs.sort(key=lambda x: x["time_ms"], reverse=True)
    return all_liqs


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Posiciones de usuario / Account state
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_clearinghouse(data: dict, address: str) -> list[dict]:
    """Parsea clearinghouseState -> lista de posiciones normalizadas."""
    result = []
    for ap in data.get("assetPositions", []):
        pos = ap.get("position", {})
        try:
            szi = float(pos.get("szi", "0") or "0")
        except (TypeError, ValueError):
            continue
        if szi == 0:
            continue
        lev_obj = pos.get("leverage", {})
        try:
            leverage = float(lev_obj.get("value", 1) or 1)
        except (TypeError, ValueError):
            leverage = 1.0
        liq_raw = pos.get("liquidationPx")
        liq_px = float(liq_raw) if liq_raw else None
        entry_raw = pos.get("entryPx") or "0"
        try:
            entry_px = float(entry_raw)
        except (TypeError, ValueError):
            entry_px = 0.0
        result.append({
            "coin":     pos.get("coin", "???"),
            "side":     "LONG" if szi > 0 else "SHORT",
            "szi":      abs(szi),
            "entry_px": entry_px,
            "liq_px":   liq_px,
            "leverage": leverage,
            "lev_type": lev_obj.get("type", "cross"),
            "trader":   address[:10] + "...",
        })
    return result


def get_user_positions(address: str) -> list[dict]:
    """Posiciones abiertas de un usuario."""
    try:
        data = _post({"type": "clearinghouseState", "user": address})
        return _parse_clearinghouse(data, address)
    except Exception as e:
        logger.debug("get_user_positions(%s...) error: %s", address[:8], e)
        return []


def get_account_state(address: str) -> dict:
    """
    Estado completo de cuenta: posiciones + account value.
    Retorna {positions: [...], account_value: float}.
    """
    try:
        data = _post({"type": "clearinghouseState", "user": address})
        positions = _parse_clearinghouse(data, address)
        account_value = float(
            data.get("marginSummary", {}).get("accountValue", 0)
        )
        return {"positions": positions, "account_value": account_value}
    except Exception as e:
        logger.warning("get_account_state(%s...) error: %s", address[:8], e)
        return {"positions": [], "account_value": 0.0}


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Leaderboard / Top traders
# ═══════════════════════════════════════════════════════════════════════════════

def get_leaderboard(top_n: int = 30) -> list[str]:
    """Top N traders por accountValue. Retorna lista de direcciones ETH."""
    try:
        data = _post({"type": "leaderboard"})
        rows = data.get("leaderboardRows", [])
        rows = sorted(rows, key=lambda r: float(r.get("accountValue", 0) or 0), reverse=True)
        return [r["ethAddress"] for r in rows[:top_n] if r.get("ethAddress")]
    except Exception as e:
        logger.warning("get_leaderboard error: %s", e)
        return []


def _compute_dist_pct(side: str, mark_px: float, liq_px: float | None) -> float | None:
    if liq_px is None:
        return None
    if side == "LONG":
        return (mark_px - liq_px) / mark_px * 100
    return (liq_px - mark_px) / mark_px * 100


def _compute_danger_score(size_usd: float, leverage: float, dist_pct: float | None) -> float:
    if dist_pct is None:
        return size_usd * leverage
    return size_usd * leverage / max(abs(dist_pct), 0.1)


def get_top_leveraged(
    top_n: int = 30,
    min_leverage: float = 5.0,
    min_size_usd: float = 100_000.0,
    max_workers: int = 5,
) -> dict:
    """
    Posiciones mas apalancadas de los top traders.
    Returns: {"longs": [...top 15...], "shorts": [...top 15...]}
    """
    mark_prices = get_mark_prices()
    addresses = get_leaderboard(top_n)
    if not addresses or not mark_prices:
        return {"longs": [], "shorts": []}

    all_positions: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(get_user_positions, addr): addr for addr in addresses}
        for future in concurrent.futures.as_completed(futures):
            try:
                all_positions.extend(future.result())
            except Exception:
                pass

    enriched = []
    for pos in all_positions:
        mark_px = mark_prices.get(pos["coin"])
        if not mark_px:
            continue
        size_usd = pos["szi"] * mark_px
        if size_usd < min_size_usd or pos["leverage"] < min_leverage:
            continue
        dist_pct = _compute_dist_pct(pos["side"], mark_px, pos["liq_px"])
        danger = _compute_danger_score(size_usd, pos["leverage"], dist_pct)
        enriched.append({**pos, "size_usd": size_usd, "mark_px": mark_px,
                         "dist_pct": dist_pct, "danger_score": danger})

    longs = sorted([p for p in enriched if p["side"] == "LONG"],
                   key=lambda x: x["danger_score"], reverse=True)[:15]
    shorts = sorted([p for p in enriched if p["side"] == "SHORT"],
                    key=lambda x: x["danger_score"], reverse=True)[:15]
    return {"longs": longs, "shorts": shorts}
