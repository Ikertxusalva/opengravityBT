"""
yfinance_data.py — Fuente de verdad unica para TODOS los datos via yfinance.

Centraliza: OHLCV (stocks, ETFs, crypto, forex), precios actuales,
series macro (VIX, DXY, bonos), cache local.

Uso:
    from moondev.data.yfinance_data import (
        get_ohlcv, get_ohlcv_cached, get_price,
        get_macro_series, days_to_period,
        YF_INTERVAL_MAP, MACRO_SYMBOLS,
    )
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────

YF_INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "4h",
    "1d": "1d", "1w": "1wk",
}

MACRO_SYMBOLS = {
    "vix":     "^VIX",
    "10y":     "^TNX",
    "2y":      "^IRX",
    "30y":     "^TYX",
    "dxy":     "DX-Y.NYB",
    "gold":    "GC=F",
    "oil":     "CL=F",
    "sp500":   "^GSPC",
    "nasdaq":  "^IXIC",
    "russell": "^RUT",
    "eurusd":  "EURUSD=X",
    "usdjpy":  "USDJPY=X",
    "btc":     "BTC-USD",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def days_to_period(days: int) -> str:
    """Convierte dias a string de periodo yfinance."""
    if days <= 1:   return "1d"
    if days <= 5:   return "5d"
    if days <= 30:  return "1mo"
    if days <= 90:  return "3mo"
    if days <= 180: return "6mo"
    if days <= 365: return "1y"
    if days <= 730: return "2y"
    return "5y"


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza columnas yfinance a formato OHLCV estandar (capitalized)."""
    if hasattr(df.columns, "levels"):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.capitalize() for c in df.columns]
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 1. OHLCV
# ═══════════════════════════════════════════════════════════════════════════════

def get_ohlcv(
    symbol: str, interval: str = "1h", days: int = 365,
) -> Optional[pd.DataFrame]:
    """
    OHLCV desde yfinance (stocks, ETFs, crypto, forex).

    Returns:
        DataFrame con columnas Open, High, Low, Close, Volume.
        None si < 10 barras.
    """
    yf_interval = YF_INTERVAL_MAP.get(interval, interval)
    period = days_to_period(days)
    try:
        df = yf.download(symbol, period=period, interval=yf_interval,
                         auto_adjust=True, progress=False)
    except Exception:
        return None

    if df is None or df.empty or len(df) < 10:
        return None

    df = normalize_columns(df)
    needed = ["Open", "High", "Low", "Close", "Volume"]
    if not all(c in df.columns for c in needed):
        return None

    df = df[needed].dropna()
    return df if len(df) >= 10 else None


def get_ohlcv_cached(
    symbol: str,
    interval: str = "1h",
    days: int = 365,
    cache_dir: Path | str | None = None,
) -> pd.DataFrame:
    """
    OHLCV con cache local en CSV. Lanza ValueError si no hay datos.

    Args:
        cache_dir: directorio para CSVs. Si None, no cachea.
    """
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        safe = symbol.replace("/", "-")
        cache_path = cache_dir / f"{safe}_{interval}_{start}_{end}.csv"
        if cache_path.exists():
            return pd.read_csv(cache_path, parse_dates=["datetime"], index_col="datetime")
    else:
        cache_path = None

    yf_interval = YF_INTERVAL_MAP.get(interval, interval)
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    data = yf.download(symbol, start=start_date, end=end_date,
                       interval=yf_interval, progress=False)
    if data.empty:
        raise ValueError(f"No se obtuvieron datos para {symbol}")

    data = normalize_columns(data)
    col_map = {}
    for col in data.columns:
        lower = col.lower()
        if "open" in lower:
            col_map[col] = "Open"
        elif "high" in lower:
            col_map[col] = "High"
        elif "low" in lower:
            col_map[col] = "Low"
        elif "close" in lower and "adj" not in lower:
            col_map[col] = "Close"
        elif "volume" in lower:
            col_map[col] = "Volume"
    data = data.rename(columns=col_map)
    data = data[["Open", "High", "Low", "Close", "Volume"]].copy().dropna()

    if cache_path is not None:
        data.index.name = "datetime"
        data.to_csv(cache_path)

    return data


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Precio actual
# ═══════════════════════════════════════════════════════════════════════════════

def get_price(symbol: str) -> dict:
    """Precio actual via Ticker.fast_info. Retorna {ticker, price, volume_24h, source}."""
    try:
        t = yf.Ticker(symbol)
        info = t.fast_info
        price = getattr(info, "last_price", None) or getattr(info, "regular_market_price", None)
        volume = (getattr(info, "three_month_average_volume", None)
                  or getattr(info, "regular_market_volume", None))
        return {
            "ticker": symbol,
            "price": float(price) if price else None,
            "change_24h": None,
            "volume_24h": float(volume) if volume else None,
            "source": "yfinance",
        }
    except Exception as e:
        logger.warning("get_price(%s) error: %s", symbol, e)
        return {"ticker": symbol, "price": None, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Series macro (VIX, bonos, DXY, commodities)
# ═══════════════════════════════════════════════════════════════════════════════

def get_macro_series(alias: str, days: int = 30) -> list[dict]:
    """
    Serie macro via yfinance sin API key.

    Args:
        alias: "vix", "10y", "dxy", "gold", "oil", "sp500", etc.
        days: dias de historial

    Retorna lista de {date: "YYYY-MM-DD", value: float}
    """
    symbol = MACRO_SYMBOLS.get(alias.lower())
    if not symbol:
        return [{"error": f"Alias '{alias}' no encontrado. Disponibles: {list(MACRO_SYMBOLS)}"}]

    period = f"{days}d" if days <= 730 else "max"
    df = yf.download(symbol, period=period, auto_adjust=True, progress=False)
    if df.empty:
        return []

    close = df["Close"]
    if hasattr(close, "squeeze"):
        close = close.squeeze()
    close = close.dropna()
    return [
        {"date": str(ts.date()), "value": round(float(v), 4)}
        for ts, v in close.items()
    ]


def get_macro_latest(alias: str) -> dict:
    """Valor mas reciente de un indicador macro."""
    obs = get_macro_series(alias, days=5)
    if not obs or "error" in obs[0]:
        return obs[0] if obs else {"error": "Sin datos"}
    latest = obs[-1]
    latest["symbol"] = MACRO_SYMBOLS.get(alias.lower(), alias)
    latest["alias"] = alias
    return latest
