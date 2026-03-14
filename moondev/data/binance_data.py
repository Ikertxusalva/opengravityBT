"""
binance_data.py — Fuente de verdad unica para TODOS los datos de Binance.

Centraliza: OHLCV spot, precios, tickers 24h, top movers, exchange info,
liquidaciones futures. Todos los demas modulos deben importar desde aqui.

Uso:
    from moondev.data.binance_data import (
        get_ohlcv, get_klines, get_price, get_24h_ticker,
        get_all_24h_tickers, get_top_movers, get_exchange_symbols,
        get_futures_liquidations, get_futures_liquidations_multi,
        SPOT_BASE, FUTURES_BASE,
    )
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────

SPOT_BASE = "https://api.binance.com/api/v3"
FUTURES_BASE = "https://fapi.binance.com/fapi/v1"

VALID_INTERVALS = {
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w",
}

_INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000,
    "4h": 14_400_000, "6h": 21_600_000, "8h": 28_800_000,
    "12h": 43_200_000, "1d": 86_400_000, "3d": 259_200_000,
    "1w": 604_800_000,
}

DEFAULT_FUTURES_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ARBUSDT"]


# ── Transporte ────────────────────────────────────────────────────────────────

def _get(url: str, params: dict | None = None,
         timeout: int = 15, retries: int = 2) -> requests.Response:
    """GET con retry basico."""
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    raise last_err  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. OHLCV Spot (con paginacion)
# ═══════════════════════════════════════════════════════════════════════════════

def get_ohlcv(
    symbol: str, interval: str = "1h", days: int = 365,
) -> Optional[pd.DataFrame]:
    """
    OHLCV desde Binance Spot con paginacion automatica.

    Args:
        symbol: formato Binance, e.g. "BTCUSDT", "ETHUSDT"
        interval: "1m" a "1w"
        days: dias de historia

    Returns:
        DataFrame con DatetimeIndex UTC y columnas Open, High, Low, Close, Volume.
        None si < 10 barras.
    """
    if interval not in _INTERVAL_MS:
        return None

    bar_ms = _INTERVAL_MS[interval]
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86_400_000

    all_rows: list[list] = []
    cursor = start_ms
    while cursor < end_ms:
        try:
            resp = _get(f"{SPOT_BASE}/klines", params={
                "symbol": symbol.upper(), "interval": interval,
                "startTime": cursor, "endTime": end_ms, "limit": 1000,
            })
            batch = resp.json()
        except Exception:
            break
        if not batch:
            break
        all_rows.extend(batch)
        cursor = batch[-1][0] + bar_ms
        if len(batch) < 1000:
            break

    if not all_rows or len(all_rows) < 10:
        return None

    df = pd.DataFrame(all_rows, columns=[
        "Open_time", "Open", "High", "Low", "Close", "Volume",
        "Close_time", "Quote_vol", "Trades", "Taker_base", "Taker_quote", "_",
    ])
    df["datetime"] = pd.to_datetime(df["Open_time"], unit="ms", utc=True)
    df = df.set_index("datetime")
    df = df[["Open", "High", "Low", "Close", "Volume"]].astype(float).dropna()
    return df if len(df) >= 10 else None


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Klines cortas (sin paginacion)
# ═══════════════════════════════════════════════════════════════════════════════

def get_klines(symbol: str, interval: str = "1h", limit: int = 100) -> dict:
    """Ultimas N velas. Retorna dict con metadata y closes recientes."""
    if interval not in VALID_INTERVALS:
        return {"error": f"Intervalo invalido: {interval}"}
    if limit <= 0 or limit > 1000:
        return {"error": "limit debe estar entre 1 y 1000"}
    try:
        resp = _get(f"{SPOT_BASE}/klines", params={
            "symbol": symbol.upper(), "interval": interval, "limit": limit,
        })
        klines = resp.json()
        recent = klines[-10:] if len(klines) >= 10 else klines
        return {
            "symbol": symbol.upper(),
            "interval": interval,
            "total_fetched": len(klines),
            "latest_close": float(klines[-1][4]) if klines else None,
            "latest_candle": {
                "open": float(klines[-1][1]),
                "high": float(klines[-1][2]),
                "low": float(klines[-1][3]),
                "close": float(klines[-1][4]),
                "volume": float(klines[-1][5]),
            } if klines else None,
            "recent_closes": [float(k[4]) for k in recent],
        }
    except Exception as e:
        logger.warning("get_klines(%s) error: %s", symbol, e)
        return {}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Precios
# ═══════════════════════════════════════════════════════════════════════════════

def get_price(symbol: str) -> dict:
    """Precio actual de un par. Retorna {symbol, price}."""
    try:
        resp = _get(f"{SPOT_BASE}/ticker/price", params={"symbol": symbol.upper()})
        return resp.json()
    except Exception as e:
        logger.warning("get_price(%s) error: %s", symbol, e)
        return {}


def get_24h_ticker(symbol: str) -> dict:
    """Stats 24h de un simbolo: precio, volumen, cambio %."""
    try:
        resp = _get(f"{SPOT_BASE}/ticker/24hr", params={"symbol": symbol.upper()})
        d = resp.json()
        return {
            "symbol": d.get("symbol"),
            "price": d.get("lastPrice"),
            "change_pct": d.get("priceChangePercent"),
            "high_24h": d.get("highPrice"),
            "low_24h": d.get("lowPrice"),
            "volume_24h": d.get("volume"),
            "quote_volume_24h": d.get("quoteVolume"),
            "trades_24h": d.get("count"),
        }
    except Exception as e:
        logger.warning("get_24h_ticker(%s) error: %s", symbol, e)
        return {}


def get_all_24h_tickers() -> list[dict]:
    """Todos los tickers 24h. Retorna lista cruda de la API."""
    try:
        resp = _get(f"{SPOT_BASE}/ticker/24hr")
        return resp.json()
    except Exception as e:
        logger.warning("get_all_24h_tickers error: %s", e)
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Top movers
# ═══════════════════════════════════════════════════════════════════════════════

def get_top_movers(limit: int = 20, min_volume: float = 0.0) -> list[dict]:
    """
    Top movers USDT por volumen o cambio absoluto.
    Retorna lista de {symbol, price, change_pct, volume_24h, ...}.
    """
    tickers = get_all_24h_tickers()
    usdt = []
    for t in tickers:
        if not t.get("symbol", "").endswith("USDT"):
            continue
        vol = float(t.get("quoteVolume", 0))
        if vol < min_volume:
            continue
        usdt.append({
            "symbol": t["symbol"],
            "price": float(t.get("lastPrice", 0)),
            "change_pct": float(t.get("priceChangePercent", 0)),
            "volume_24h": vol,
            "high_24h": float(t.get("highPrice", 0)),
            "low_24h": float(t.get("lowPrice", 0)),
        })
    usdt.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
    return usdt[:limit]


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Exchange info
# ═══════════════════════════════════════════════════════════════════════════════

def get_exchange_symbols(quote_asset: str = "USDT") -> set[str]:
    """Pares activos de trading filtrados por quote asset."""
    try:
        resp = _get(f"{SPOT_BASE}/exchangeInfo")
        data = resp.json()
        return {
            s["symbol"]
            for s in data.get("symbols", [])
            if s.get("quoteAsset") == quote_asset and s.get("status") == "TRADING"
        }
    except Exception as e:
        logger.warning("get_exchange_symbols error: %s", e)
        return set()


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Liquidaciones Futures
# ═══════════════════════════════════════════════════════════════════════════════

def get_futures_liquidations(symbol: str, limit: int = 100) -> list[dict]:
    """
    Liquidaciones recientes de Binance Futures (forceOrders).
    side=SELL -> LONG liquidado, side=BUY -> SHORT liquidado.
    """
    try:
        resp = _get(f"{FUTURES_BASE}/forceOrders", params={
            "symbol": symbol.upper(), "limit": limit,
        })
        orders = resp.json()
        if not isinstance(orders, list):
            return []
        result = []
        for o in orders:
            side_raw = o.get("side", "")
            side = "LONG" if side_raw == "SELL" else "SHORT"
            try:
                usd_size = float(o.get("price", 0)) * float(o.get("origQty", 0))
            except (TypeError, ValueError):
                usd_size = 0.0
            coin = symbol.upper().replace("USDT", "").replace("BUSD", "")
            result.append({
                "coin": coin,
                "side": side,
                "usd_size": usd_size,
                "px": str(o.get("price", "0")),
                "sz": str(o.get("origQty", "0")),
                "time_ms": int(o.get("time", 0)),
                "tid": int(o.get("orderId", 0)),
                "source": "binance",
            })
        return result
    except Exception as e:
        logger.warning("get_futures_liquidations(%s) error: %s", symbol, e)
        return []


def get_futures_liquidations_multi(
    symbols: list[str] | None = None,
) -> list[dict]:
    """Liquidaciones de multiples simbolos, ordenadas por tiempo descendente."""
    if symbols is None:
        symbols = DEFAULT_FUTURES_SYMBOLS
    all_liqs: list[dict] = []
    for sym in symbols:
        all_liqs.extend(get_futures_liquidations(sym))
    all_liqs.sort(key=lambda x: x["time_ms"], reverse=True)
    return all_liqs
