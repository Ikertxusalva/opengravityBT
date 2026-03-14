"""Dukascopy tick data — HTTP + bi5 (LZMA binary) parser."""
from __future__ import annotations
import lzma
import logging
import math
import struct
from datetime import datetime, timezone, timedelta
from pathlib import Path
import httpx
import pandas as pd
from .base import BaseTickSource, TICK_COLUMNS

logger = logging.getLogger(__name__)
DUKASCOPY_BASE = "https://datafeed.dukascopy.com/datafeed"

# bi5: each tick = 5 big-endian fields: uint32 ms_offset, uint32 ask, uint32 bid, float32 ask_vol, float32 bid_vol
_TICK_STRUCT = struct.Struct(">IIIff")
_TICK_SIZE = _TICK_STRUCT.size  # 20 bytes

# instrument → (name_in_url, decimal_places)
DUKASCOPY_INSTRUMENTS: dict[str, tuple[str, int]] = {
    "EURUSD": ("EURUSD", 5),
    "GBPUSD": ("GBPUSD", 5),
    "USDJPY": ("USDJPY", 3),
    "AUDUSD": ("AUDUSD", 5),
    "USDCAD": ("USDCAD", 5),
    "USDCHF": ("USDCHF", 5),
    "NZDUSD": ("NZDUSD", 5),
    "XAUUSD": ("XAUUSD", 3),
    "XAGUSD": ("XAGUSD", 3),
    "USOIL":  ("USOIL",  3),
    "SPXUSD": ("SPXUSD", 1),
    "NASUSD": ("NASUSD", 1),
    "GRXEUR": ("GRXEUR", 1),
}


def decimals_for(scale: int) -> int:
    return int(math.log10(scale))


class DukascopyTickSource(BaseTickSource):
    source_prefix = "dukascopy"

    def download(self, symbol: str, start: datetime = None, end: datetime = None,
                 **kwargs) -> pd.DataFrame:
        key = symbol.upper()
        if key not in DUKASCOPY_INSTRUMENTS:
            return self._empty()

        path = self._cache_path(symbol)
        if not kwargs.get("no_cache"):
            cached = self._load_cache(path)
            if cached is not None:
                return cached

        instrument, decimals = DUKASCOPY_INSTRUMENTS[key]
        scale = 10 ** decimals

        now = datetime.now(tz=timezone.utc)
        if end is None:
            end = now
        if start is None:
            start = end - timedelta(hours=1)

        rows: list[dict] = []
        current = start.replace(minute=0, second=0, microsecond=0)
        while current <= end:
            rows.extend(self._fetch_hour(instrument, current, scale))
            current += timedelta(hours=1)

        df = pd.DataFrame(rows, columns=TICK_COLUMNS) if rows else self._empty()
        if not df.empty:
            self._save_cache(path, df)
        return df

    def _fetch_hour(self, instrument: str, dt: datetime, scale: int) -> list[dict]:
        # Dukascopy months are 0-indexed
        url = (f"{DUKASCOPY_BASE}/{instrument}/"
               f"{dt.year}/{dt.month - 1:02d}/{dt.day:02d}/{dt.hour:02d}_ticks.bi5")
        try:
            resp = httpx.get(url, timeout=15.0)
            if resp.status_code != 200 or not resp.content:
                return []
            raw = lzma.decompress(resp.content)
        except Exception as exc:
            logger.debug("Dukascopy fetch error %s: %s", url, exc)
            return []

        hour_ms = int(dt.timestamp() * 1000)
        dec = decimals_for(scale)
        rows: list[dict] = []
        for i in range(0, len(raw) - _TICK_SIZE + 1, _TICK_SIZE):
            ms_off, ask_raw, bid_raw, ask_vol, bid_vol = _TICK_STRUCT.unpack_from(raw, i)
            mid = (ask_raw + bid_raw) / 2 / scale
            rows.append({
                "timestamp": pd.Timestamp(hour_ms + ms_off, unit="ms", tz="UTC"),
                "price": round(mid, dec),
                "size": round((ask_vol + bid_vol) / 2, 4),
                "side": "buy",  # Dukascopy quote data, no aggressor side
            })
        return rows
