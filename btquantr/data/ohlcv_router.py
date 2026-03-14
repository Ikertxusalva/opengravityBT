"""Universal OHLCV router — sin dependencias moondev.

Routing automático por tipo de símbolo:
  BTCUSDT / ETHUSDT  → HyperLiquid candleSnapshot (capa 0, sin API key)
                       → Binance Klines (capa 1, sin API key, desde 2017)
                       → yfinance (capa 2, fallback universal)
  EUR-USD / EUR_USD  → yfinance("EURUSD=X")
  XAU-USD            → yfinance("GC=F")
  SPX500-USD         → yfinance("^GSPC")
  AAPL / SPY / GLD   → yfinance directo
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

from btquantr.data.cache_manager import CacheManager as _CacheManager

_default_cache = _CacheManager()

log = logging.getLogger("OHLCVRouter")

_OHLCV_COLS = ["Open", "High", "Low", "Close", "Volume"]


def _to_float32(df: pd.DataFrame) -> pd.DataFrame:
    """Convierte columnas OHLCV a float32 para reducir uso de RAM en ~50%."""
    for col in _OHLCV_COLS:
        if col in df.columns:
            df[col] = df[col].astype("float32")
    return df

# Mapeo símbolo RBI/Oanda → yfinance ticker
_SYMBOL_TO_YF: dict[str, str] = {
    "EUR-USD":    "EURUSD=X",
    "EUR_USD":    "EURUSD=X",
    "EURUSD":     "EURUSD=X",
    "GBP-USD":    "GBPUSD=X",
    "GBP_USD":    "GBPUSD=X",
    "GBPUSD":     "GBPUSD=X",
    "USD-JPY":    "USDJPY=X",
    "USD_JPY":    "USDJPY=X",
    "USDJPY":     "USDJPY=X",
    "USD-CAD":    "USDCAD=X",
    "USD_CAD":    "USDCAD=X",
    "USDCAD":     "USDCAD=X",
    "AUD-USD":    "AUDUSD=X",
    "AUD_USD":    "AUDUSD=X",
    "AUDUSD":     "AUDUSD=X",
    "USD-CHF":    "USDCHF=X",
    "USD_CHF":    "USDCHF=X",
    "USDCHF":     "USDCHF=X",
    "XAU-USD":    "GC=F",
    "XAU_USD":    "GC=F",
    "XAG-USD":    "SI=F",
    "XAG_USD":    "SI=F",
    "WTICO-USD":  "CL=F",
    "WTICO_USD":  "CL=F",
    "SPX500-USD": "^GSPC",
    "SPX500_USD": "^GSPC",
    "NAS100-USD": "^NDX",
    "NAS100_USD": "^NDX",
    # HIP3 — activos sintéticos HyperLiquid (prefijo xyz:)
    "xyz:CL":     "CL=F",
    "xyz:GOLD":   "GC=F",
    "xyz:NVDA":   "NVDA",
    "xyz:XYZ100": "^NDX",
}

# ── HyperLiquid Candles ──────────────────────────────────────────────────────

# Timeframe → intervalo HyperLiquid candleSnapshot
_TF_TO_HL: dict[str, str] = {
    "1m":  "1m",
    "5m":  "5m",
    "15m": "15m",
    "30m": "30m",
    "1h":  "1h",
    "4h":  "4h",
    "1d":  "1d",
    "1w":  "1w",
    # Oanda granularities
    "H1": "1h",
    "H4": "4h",
    "D":  "1d",
    "W":  "1w",
}


def _fetch_hl_candles(symbol: str, timeframe: str, days: int) -> pd.DataFrame:
    """Descarga OHLCV desde HyperLiquid candleSnapshot. Sin API key.

    Pagina automáticamente: HL devuelve hasta 5000 velas por request.
    Convierte símbolo BTCUSDT → coin "BTC" automáticamente.
    """
    from btquantr.data.sources.hyperliquid import HyperLiquidSource

    coin = symbol.upper().replace("USDT", "").replace("BUSD", "")
    interval = _TF_TO_HL.get(timeframe, "1h")

    end_ms = int(datetime.now().timestamp() * 1000)
    start_ms = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

    src = HyperLiquidSource()
    all_frames: list[pd.DataFrame] = []
    current_start = start_ms

    while current_start < end_ms:
        df = src.get_candles(coin, interval=interval, start_ms=current_start, end_ms=end_ms)
        if df is None or df.empty:
            break
        all_frames.append(df)
        if len(df) < 5000:
            break
        last_ts = int(df.index[-1].timestamp() * 1000)
        current_start = last_ts + 1

    if not all_frames:
        return pd.DataFrame()

    combined = pd.concat(all_frames)
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.sort_index()


# ── Binance Klines ───────────────────────────────────────────────────────────

_BINANCE_BASE = "https://api.binance.com/api/v3/klines"

# Timeframe → Binance interval (soporta 4h nativo, a diferencia de yfinance)
_TF_TO_BINANCE: dict[str, str] = {
    "1m":  "1m",
    "5m":  "5m",
    "15m": "15m",
    "30m": "30m",
    "1h":  "1h",
    "4h":  "4h",
    "1d":  "1d",
    "1w":  "1w",
    # Oanda granularities
    "H1": "1h",
    "H4": "4h",
    "D":  "1d",
    "W":  "1w",
}


def _is_usdt_symbol(symbol: str) -> bool:
    return symbol.upper().endswith("USDT")


def _fetch_binance_klines(symbol: str, timeframe: str, days: int) -> pd.DataFrame:
    """Descarga OHLCV desde Binance Klines API pública. Sin API key.

    Pagina automáticamente (1000 velas/request) hasta cubrir `days` días.
    Datos disponibles desde 2017 para BTCUSDT.
    """
    import requests

    interval = _TF_TO_BINANCE.get(timeframe, "1h")
    end_ms = int(datetime.now().timestamp() * 1000)
    start_ms = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

    all_klines: list = []
    current_start = start_ms

    try:
        while current_start < end_ms:
            params = {
                "symbol": symbol.upper(),
                "interval": interval,
                "startTime": current_start,
                "endTime": end_ms,
                "limit": 1000,
            }
            resp = requests.get(_BINANCE_BASE, params=params, timeout=10)
            resp.raise_for_status()
            klines = resp.json()

            if not klines:
                break

            all_klines.extend(klines)

            if len(klines) < 1000:
                break

            # Próxima página: close_time del último kline + 1ms
            current_start = klines[-1][6] + 1

    except Exception as e:
        log.warning("Binance klines error para %s: %s", symbol, e)
        if not all_klines:
            return pd.DataFrame()

    if not all_klines:
        return pd.DataFrame()

    cols = [
        "open_time", "Open", "High", "Low", "Close", "Volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ]
    df = pd.DataFrame(all_klines, columns=cols)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time")

    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = df[col].astype(float)

    return df[["Open", "High", "Low", "Close", "Volume"]]


# ── Timeframe → yfinance interval ────────────────────────────────────────────

# Timeframe → yfinance interval
_TF_TO_YF: dict[str, str] = {
    "1m":  "1m",
    "5m":  "5m",
    "15m": "15m",
    "30m": "30m",
    "1h":  "1h",
    "4h":  "1h",   # yfinance no tiene 4h nativo; usar 1h
    "1d":  "1d",
    "1w":  "1wk",
    # Oanda granularities
    "H1": "1h",
    "H4": "1h",
    "D":  "1d",
    "W":  "1wk",
    "M":  "1mo",
}

# Límites máximos de días que soporta yfinance por timeframe
# Ref: https://github.com/ranaroussi/yfinance — intraday data capped by Yahoo Finance
_YF_MAX_DAYS: dict[str, int] = {
    "1m":  7,
    "5m":  60,
    "15m": 60,
    "30m": 60,
    "1h":  730,
    "4h":  730,
    "H1":  730,
    "H4":  730,
    "1d":  36500,
    "1w":  36500,
    "1wk": 36500,
    "D":   36500,
    "W":   36500,
    "M":   36500,
}


def _is_hip3_symbol(symbol: str) -> bool:
    """Detecta activos sintéticos HIP3 HyperLiquid (prefijo xyz:)."""
    return symbol.lower().startswith("xyz:")


def _hip3_to_hl_coin(symbol: str) -> str:
    """Extrae el nombre de la coin HL desde un símbolo HIP3 (xyz:GOLD → GOLD)."""
    return symbol.split(":", 1)[1].upper()


def _to_yf_symbol(symbol: str) -> str:
    """Convierte cualquier formato de símbolo a ticker de yfinance."""
    if symbol in _SYMBOL_TO_YF:
        return _SYMBOL_TO_YF[symbol]

    s = symbol.upper()

    if s.endswith("USDT"):
        return s[:-4] + "-USD"
    if s.endswith("BUSD"):
        return s[:-4] + "-USD"

    return symbol


def _slice_days(df: pd.DataFrame, days: int) -> pd.DataFrame:
    """Retorna las últimas `days` días del DataFrame."""
    if df is None or df.empty:
        return pd.DataFrame()
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
    idx = df.index
    if isinstance(idx, pd.DatetimeIndex) and idx.tz is None:
        idx = idx.tz_localize("UTC")
        df = df.copy()
        df.index = idx
    return df[df.index >= cutoff]


def _merge_ohlcv(df_old: "pd.DataFrame | None", df_new: pd.DataFrame) -> pd.DataFrame:
    """Combina DataFrame antiguo con nuevas barras, sin duplicados."""
    if df_old is None or df_old.empty:
        return df_new
    combined = pd.concat([df_old, df_new])
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.sort_index()


def _download(
    symbol: str,
    timeframe: str,
    days: int,
    since: "pd.Timestamp | None" = None,
) -> pd.DataFrame:
    """Descarga OHLCV usando HL→Binance→yfinance routing.

    Si `since` está definido, solo descarga desde ese timestamp.
    """
    # Para append: calcular cuántos días desde `since`
    if since is not None:
        days_needed = max(1, int((pd.Timestamp.now(tz="UTC") - since).total_seconds() / 86400) + 1)
    else:
        days_needed = days

    # ── Capa HIP3: HyperLiquid sintéticos (xyz:COIN) ──────────────────────────
    if _is_hip3_symbol(symbol) and timeframe in _TF_TO_HL:
        try:
            coin = _hip3_to_hl_coin(symbol)
            df = _fetch_hl_candles(coin, timeframe, days_needed)
            if df is not None and not df.empty:
                if since is not None:
                    df = df[df.index > since]
                if not df.empty:
                    log.info("OHLCVRouter: HIP3/HL OK — %s %d barras", symbol, len(df))
                    return df
        except Exception as e:
            log.warning("OHLCVRouter: HIP3/HL falló para %s (%s), usando yfinance", symbol, e)

    # ── Capa 0: HyperLiquid ────────────────────────────────────────────────────
    if _is_usdt_symbol(symbol) and timeframe in _TF_TO_HL:
        try:
            df = _fetch_hl_candles(symbol, timeframe, days_needed)
            if df is not None and not df.empty:
                if since is not None:
                    df = df[df.index > since]
                if not df.empty:
                    log.info("OHLCVRouter: HyperLiquid OK — %s %d barras", symbol, len(df))
                    return df
            log.warning("OHLCVRouter: HyperLiquid vacío para %s, probando Binance", symbol)
        except Exception as e:
            log.warning("OHLCVRouter: HyperLiquid falló para %s (%s), probando Binance", symbol, e)

    # ── Capa 1: Binance ────────────────────────────────────────────────────────
    if _is_usdt_symbol(symbol) and timeframe in _TF_TO_BINANCE:
        try:
            df = _fetch_binance_klines(symbol, timeframe, days_needed)
            if df is not None and not df.empty:
                if since is not None:
                    df = df[df.index > since]
                if not df.empty:
                    log.info("OHLCVRouter: Binance OK — %s %d barras", symbol, len(df))
                    return df
            log.warning("OHLCVRouter: Binance vacío para %s, usando yfinance", symbol)
        except Exception as e:
            log.warning("OHLCVRouter: Binance falló para %s (%s), usando yfinance", symbol, e)

    # ── Capa 2: yfinance ───────────────────────────────────────────────────────
    import yfinance as yf

    yf_sym = _to_yf_symbol(symbol)
    interval = _TF_TO_YF.get(timeframe, "1d")
    if timeframe == "4h":
        log.warning("OHLCVRouter: yfinance no soporta 4h nativo — usando 1h")

    max_days = _YF_MAX_DAYS.get(timeframe, 36500)
    if days_needed > max_days:
        log.warning("OHLCVRouter: yfinance limita %s a %d días — ajustando.", timeframe, max_days)
        days_needed = max_days

    end = datetime.now()
    start = since.to_pydatetime() if since is not None else end - timedelta(days=days_needed)

    try:
        ticker = yf.Ticker(yf_sym)
        df = ticker.history(start=start, end=end, interval=interval)
        if df is None or df.empty:
            log.warning("yfinance returned empty for %s", yf_sym)
            return pd.DataFrame()
        needed = ["Open", "High", "Low", "Close", "Volume"]
        available = [c for c in needed if c in df.columns]
        return df[available]
    except Exception as e:
        log.warning("OHLCVRouter.get_ohlcv(%r, %r, %dd) error: %s", symbol, timeframe, days, e)
        return pd.DataFrame()


def get_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    days: int = 365,
    no_cache: bool = False,
    _cache_manager: "_CacheManager | None" = None,
) -> pd.DataFrame:
    """Descarga OHLCV para cualquier símbolo con caché en disco.

    Cache: data/cache/{symbol}_{timeframe}.parquet
    - Si caché fresco (<24h): retorna directamente sin descargar.
    - Si caché stale (>24h): descarga solo barras nuevas y hace append.
    - Si no_cache=True: ignora caché, descarga completo.

    Para crypto *USDT:
      1. HyperLiquid candles (primario, sin API key)
      2. Binance Klines (secundario)
      3. yfinance (fallback final)
    Para el resto (stocks, forex, commodities): yfinance directo.
    """
    cm = _cache_manager if _cache_manager is not None else _default_cache

    # ── Cache check ────────────────────────────────────────────────────────────
    if not no_cache:
        if cm.is_ohlcv_fresh(symbol, timeframe, stale_hours=24):
            df_cached = cm.get_ohlcv_cached(symbol, timeframe)
            if df_cached is not None and not df_cached.empty:
                log.info("Cache hit: %s %s", symbol, timeframe)
                return _to_float32(_slice_days(df_cached, days))

        # Stale: calcular desde cuándo descargar (append de barras nuevas)
        last_bar = cm.get_last_bar_time(symbol, timeframe)
        if last_bar is not None:
            log.info("Downloading new bars: %s %s desde %s", symbol, timeframe,
                     last_bar.strftime("%Y-%m-%d %H:%M"))
            df_new = _download(symbol, timeframe, days, since=last_bar)
            if df_new is not None and not df_new.empty:
                df_old = cm.get_ohlcv_cached(symbol, timeframe)
                df_merged = _merge_ohlcv(df_old, df_new)
                cm.set_ohlcv(symbol, timeframe, df_merged)
                return _to_float32(_slice_days(df_merged, days))
    else:
        log.info("Downloading: %s %s (no-cache)", symbol, timeframe)

    # ── Descarga completa ──────────────────────────────────────────────────────
    log.info("Downloading: %s %s (%dd)", symbol, timeframe, days)
    df = _download(symbol, timeframe, days)
    if df is not None and not df.empty:
        if not no_cache:
            cm.set_ohlcv(symbol, timeframe, df)
        return _to_float32(df)
    return pd.DataFrame()
