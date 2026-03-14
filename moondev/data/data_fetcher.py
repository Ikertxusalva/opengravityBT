"""
data_fetcher.py — Fuente de datos unificada para backtesting.

Estrategia de datos (Jim Simons style — calidad institucional):
  • Crypto perps  → HyperLiquid API (gratis, sin API key, tick+liquidaciones)
  • Crypto spot   → Binance API (gratis, 2017-presente, más cobertura)
  • Stocks / ETF  → yfinance (Yahoo Finance)
  • Forex OHLCV   → yfinance (fallback rápido)
  • Forex tick    → Dukascopy (gratis, 98% calidad, desde 2003, bid/ask real)
  • Macro         → FRED API (gratis, key opcional, VIX/CPI/FEDFUNDS/DGS10)

Uso:
    from moondev.data.data_fetcher import get_ohlcv, get_macro, ALL_SYMBOLS

    df = get_ohlcv("BTC", interval="1h", days=365)        # HyperLiquid
    df = get_ohlcv("AAPL", interval="1h", days=365)       # yfinance
    df = get_ohlcv("EURUSD", interval="1d", days=730)     # Dukascopy (tick→OHLCV)
    df = get_macro("VIXCLS", days=365)                    # FRED VIX

Columnas OHLCV retornadas (compatibles con backtesting.py):
    Open, High, Low, Close, Volume  (DatetimeIndex UTC)
"""
from __future__ import annotations

import io
import lzma
import struct
import time
import warnings
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd
import requests

from moondev.data.hyperliquid_data import (
    get_ohlcv as _hl_get_ohlcv,
    get_funding_history as _hl_get_funding_history,
    HL_CRYPTO,
    VALID_INTERVALS as _HL_INTERVALS_SET,
)
from moondev.data.binance_data import get_ohlcv as _bn_get_ohlcv
from moondev.data.yfinance_data import get_ohlcv as _yf_get_ohlcv
from moondev.data.fred_data import get_series as _fred_get_series

warnings.filterwarnings("ignore", category=FutureWarning)

# ── Símbolos disponibles ─────────────────────────────────────────────────────
# HL_CRYPTO se importa desde hyperliquid_data (fuente de verdad unica)

STOCKS = [
    "AAPL", "MSFT", "GOOGL", "NVDA", "TSLA",
    "AMZN", "META", "AMD", "SPY", "QQQ",
]

# Forex: usar "EURUSD" (sin =X) para Dukascopy; el fetcher maneja ambos formatos
FOREX = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"]
FOREX_YF = [f"{p}=X" for p in FOREX]  # formato yfinance

# FRED macro series clave (Jim Simons usa macro como filtro de régimen)
MACRO_SERIES = {
    "VIX":   "VIXCLS",    # Volatilidad implícita S&P500
    "FED":   "FEDFUNDS",  # Federal Funds Rate
    "CPI":   "CPIAUCSL",  # Consumer Price Index
    "UST10": "DGS10",     # US Treasury 10Y
    "UNEMP": "UNRATE",    # Unemployment Rate
}

ALL_SYMBOLS = HL_CRYPTO[:10] + STOCKS + FOREX

_YF_TO_HL = {f"{c}-USD": c for c in HL_CRYPTO}
_YF_TO_HL.update({f"{c}USDT": c for c in HL_CRYPTO})
_FOREX_YF_MAP = {f"{p}=X": p for p in FOREX}  # "EURUSD=X" → "EURUSD"

# ── 1. HyperLiquid OHLCV (delegado a hyperliquid_data) ───────────────────────

def fetch_hyperliquid(
    coin: str, interval: str = "1h", days: int = 365,
) -> Optional[pd.DataFrame]:
    """OHLCV desde HyperLiquid. Delega a moondev.data.hyperliquid_data."""
    return _hl_get_ohlcv(coin, interval=interval, days=days)


def fetch_hl_funding(coin: str, days: int = 90) -> Optional[pd.DataFrame]:
    """Funding rates historicos. Delega a moondev.data.hyperliquid_data."""
    return _hl_get_funding_history(coin, days=days)


# ── 2. Binance OHLCV (delegado a binance_data) ───────────────────────────────

def fetch_binance(
    symbol: str, interval: str = "1h", days: int = 365,
) -> Optional[pd.DataFrame]:
    """OHLCV desde Binance. Delega a moondev.data.binance_data."""
    return _bn_get_ohlcv(symbol, interval=interval, days=days)


# ── 3. Dukascopy Tick → OHLCV (Forex institucional, gratis) ─────────────────

_DUKA_BASE = "https://www.dukascopy.com/datafeed"
_DUKA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.dukascopy.com/",
}
_DUKA_PAIRS = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
               "NZDUSD", "USDCHF", "EURGBP", "EURJPY", "GBPJPY"}


def _fetch_duka_hour(pair: str, dt: datetime) -> list[dict]:
    """Descarga 1 hora de tick data de Dukascopy (formato bi5/lzma)."""
    url = (f"{_DUKA_BASE}/{pair.upper()}/"
           f"{dt.year}/{dt.month - 1:02d}/{dt.day:02d}/{dt.hour:02d}h_ticks.bi5")
    try:
        resp = requests.get(url, headers=_DUKA_HEADERS, timeout=10)
        if resp.status_code != 200 or len(resp.content) < 20:
            return []
        raw = lzma.decompress(resp.content)
    except Exception:
        return []

    ticks = []
    for i in range(0, len(raw) - 19, 20):
        chunk = raw[i:i + 20]
        try:
            ts_ms, ask_raw, bid_raw, ask_vol, bid_vol = struct.unpack(">IIIff", chunk)
        except struct.error:
            continue
        base_ms = int(dt.replace(minute=0, second=0, microsecond=0,
                                 tzinfo=timezone.utc).timestamp() * 1000)
        mid_price = ((ask_raw + bid_raw) / 2) / 100_000
        ticks.append({
            "ts": base_ms + ts_ms,
            "price": mid_price,
            "volume": float(ask_vol + bid_vol),
        })
    return ticks


def fetch_dukascopy(
    pair: str, interval: str = "1d", days: int = 365,
) -> Optional[pd.DataFrame]:
    """
    OHLCV desde Dukascopy tick data (calidad institucional, gratis).

    pair:     "EURUSD", "GBPUSD", "USDJPY"... (sin =X)
    interval: "1h" | "4h" | "1d"  (tick data agregado a OHLCV)
    days:     Días de historia (máximo recomendado: 730)

    Nota: Descarga lenta (1 request/hora). Para backtests rápidos usar yfinance.
    Para backtests finales o validación, usar Dukascopy.
    """
    pair = pair.upper().replace("=X", "").replace("/", "")
    if pair not in _DUKA_PAIRS:
        return None

    freq_map = {"1h": "1h", "4h": "4h", "1d": "1D"}
    freq = freq_map.get(interval, "1D")

    end_dt = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=days)

    all_ticks: list[dict] = []
    current = start_dt
    hours_total = int((end_dt - start_dt).total_seconds() / 3600)

    # Límite práctico: máximo 90 días en modo rápido (90*24=2160 requests)
    max_hours = min(hours_total, 90 * 24)
    fetched = 0

    while current < end_dt and fetched < max_hours:
        ticks = _fetch_duka_hour(pair, current)
        all_ticks.extend(ticks)
        current += timedelta(hours=1)
        fetched += 1
        # Rate limit suave
        if fetched % 50 == 0:
            time.sleep(0.1)

    if not all_ticks or len(all_ticks) < 2:
        return None

    df_ticks = pd.DataFrame(all_ticks)
    df_ticks["datetime"] = pd.to_datetime(df_ticks["ts"], unit="ms", utc=True)
    df_ticks = df_ticks.set_index("datetime").sort_index()

    # Agregar ticks → OHLCV
    ohlcv = df_ticks["price"].resample(freq).ohlc()
    ohlcv.columns = ["Open", "High", "Low", "Close"]
    ohlcv["Volume"] = df_ticks["volume"].resample(freq).sum()
    ohlcv = ohlcv.dropna()
    return ohlcv if len(ohlcv) >= 10 else None


# ── 4. FRED Macro Data (delegado a fred_data) ────────────────────────────────

def get_macro(
    series: str = "VIXCLS",
    days: int = 365,
) -> Optional[pd.Series]:
    """Serie macro desde FRED. Delega a moondev.data.fred_data."""
    return _fred_get_series(series, days=days)


# ── 5. yfinance OHLCV (delegado a yfinance_data) ─────────────────────────────

def fetch_yfinance(
    symbol: str, interval: str = "1h", days: int = 365,
) -> Optional[pd.DataFrame]:
    """OHLCV desde yfinance. Delega a moondev.data.yfinance_data."""
    return _yf_get_ohlcv(symbol, interval=interval, days=days)


# ── 6. Fetcher unificado ─────────────────────────────────────────────────────

def _is_hl_symbol(symbol: str) -> bool:
    s = symbol.upper()
    return s in {c.upper() for c in HL_CRYPTO} or s in _YF_TO_HL


def _normalize_hl_name(symbol: str) -> str:
    s = symbol.upper()
    return _YF_TO_HL.get(s, s)


def _is_forex(symbol: str) -> bool:
    s = symbol.upper().replace("=X", "").replace("/", "")
    return s in _DUKA_PAIRS or symbol.upper() in {f"{p}=X" for p in FOREX}


def _normalize_forex(symbol: str) -> str:
    """'EURUSD=X' → 'EURUSD', 'EUR/USD' → 'EURUSD'"""
    return symbol.upper().replace("=X", "").replace("/", "")


def get_ohlcv(
    symbol: str,
    interval: str = "1h",
    days: int = 365,
    prefer_hl: bool = True,
    use_dukascopy: bool = False,
) -> Optional[pd.DataFrame]:
    """
    Fetcher unificado — routing automático por tipo de activo.

    Crypto  → HyperLiquid (mejor historial) → fallback Binance → fallback yfinance
    Forex   → yfinance rápido (default) | Dukascopy tick (use_dukascopy=True)
    Stocks  → yfinance

    Args:
        symbol:        "BTC", "BTC-USD", "AAPL", "EURUSD", "EURUSD=X"
        interval:      "1m" | "5m" | "15m" | "1h" | "4h" | "1d"
        days:          Días de historia
        prefer_hl:     Si True, usa HyperLiquid primero para crypto
        use_dukascopy: Si True, usa Dukascopy (tick data real) para forex
                       Más lento pero mucho más preciso para backtesting final

    Returns:
        DataFrame OHLCV con columnas Open, High, Low, Close, Volume.
    """
    # ── Crypto → HyperLiquid primero
    if prefer_hl and _is_hl_symbol(symbol):
        hl_coin = _normalize_hl_name(symbol)
        df = fetch_hyperliquid(hl_coin, interval=interval, days=days)
        if df is not None and len(df) >= 10:
            return df
        # Fallback: Binance
        bn_sym = f"{hl_coin}USDT"
        df = fetch_binance(bn_sym, interval=interval, days=days)
        if df is not None and len(df) >= 10:
            return df
        # Fallback final: yfinance
        yf_sym = symbol if "-USD" in symbol.upper() else f"{symbol}-USD"
        return fetch_yfinance(yf_sym, interval=interval, days=days)

    # ── Forex
    if _is_forex(symbol):
        if use_dukascopy and interval in ("1h", "4h", "1d"):
            pair = _normalize_forex(symbol)
            df = fetch_dukascopy(pair, interval=interval, days=min(days, 90))
            if df is not None and len(df) >= 10:
                return df
        # Fallback/default: yfinance
        yf_sym = symbol if "=X" in symbol else f"{_normalize_forex(symbol)}=X"
        return fetch_yfinance(yf_sym, interval=interval, days=days)

    # ── Stocks / ETFs → yfinance
    return fetch_yfinance(symbol, interval=interval, days=days)


# ── 7. Descarga masiva ───────────────────────────────────────────────────────

def download_all(
    symbols: list[str] | None = None,
    interval: str = "1h",
    days: int = 365,
    verbose: bool = True,
) -> dict[str, pd.DataFrame]:
    """Descarga OHLCV para todos los símbolos. Retorna {symbol: DataFrame}."""
    if symbols is None:
        symbols = ALL_SYMBOLS

    results = {}
    for i, sym in enumerate(symbols, 1):
        if verbose:
            print(f"  [{i:>2}/{len(symbols)}] {sym:<14}", end="\r")
        df = get_ohlcv(sym, interval=interval, days=days)
        if df is not None:
            results[sym] = df
    if verbose:
        print(f"  Descargados: {len(results)}/{len(symbols)} símbolos        ")
    return results


# ── 8. CLI ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    symbol   = sys.argv[1] if len(sys.argv) > 1 else "BTC"
    interval = sys.argv[2] if len(sys.argv) > 2 else "1h"
    days     = int(sys.argv[3]) if len(sys.argv) > 3 else 365
    mode     = sys.argv[4] if len(sys.argv) > 4 else "ohlcv"  # ohlcv | macro | funding

    print(f"\nDescargando {symbol} ({interval}, {days}d) [mode={mode}]...")

    if mode == "macro":
        s = get_macro(symbol, days=days)
        if s is None:
            print("ERROR: no se pudo obtener macro data.")
            sys.exit(1)
        print(f"Serie: {symbol} | Registros: {len(s)}")
        print(s.tail(10))
    elif mode == "funding":
        df = fetch_hl_funding(symbol, days=days)
        if df is None:
            print("ERROR: no se pudo obtener funding rates.")
            sys.exit(1)
        print(f"Funding rates: {len(df)} registros")
        print(df.tail(10))
    else:
        use_duka = "--dukascopy" in sys.argv
        df = get_ohlcv(symbol, interval=interval, days=days, use_dukascopy=use_duka)
        if df is None:
            print("ERROR: no se pudo obtener datos.")
            sys.exit(1)
        source = "HyperLiquid" if _is_hl_symbol(symbol) else (
            "Dukascopy" if (use_duka and _is_forex(symbol)) else "yfinance"
        )
        print(f"Fuente: {source} | Registros: {len(df)}")
        print(f"Desde: {df.index[0]}")
        print(f"Hasta: {df.index[-1]}")
        print(f"\nÚltimas 5 filas:")
        print(df.tail())
