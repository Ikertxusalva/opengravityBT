"""Tardis.dev tick data — usa tardis-dev library."""
from __future__ import annotations
import logging
import os
from pathlib import Path
import pandas as pd
from .base import BaseTickSource, TICK_COLUMNS

logger = logging.getLogger(__name__)

try:
    from tardis_dev import datasets
except ImportError:
    datasets = None  # type: ignore

TARDIS_EXCHANGE_MAP: dict[str, str] = {
    "BTCUSDT":  "binance",
    "ETHUSDT":  "binance",
    "SOLUSDT":  "binance",
    "BNBUSDT":  "binance",
    "XBTUSD":   "bitmex",
    "ETHUSD":   "bitmex",
}


class TardisTickSource(BaseTickSource):
    source_prefix = "tardis"

    def download(self, symbol: str, exchange: str = None, date: str = None,
                 **kwargs) -> pd.DataFrame:
        # Check cache first (before any API key / library checks)
        path = self._cache_path(symbol)
        if not kwargs.get("no_cache"):
            cached = self._load_cache(path)
            if cached is not None:
                return cached

        api_key = os.environ.get("TARDIS_API_KEY", "")
        if not api_key:
            logger.debug("TARDIS_API_KEY not set — skipping tardis download")
            return self._empty()

        if datasets is None:
            logger.warning("tardis-dev not installed — pip install tardis-dev")
            return self._empty()

        if exchange is None:
            exchange = TARDIS_EXCHANGE_MAP.get(symbol.upper(), "binance")
        if date is None:
            from datetime import datetime, timezone
            date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

        out_dir = self.ticks_dir / f"tardis_{symbol}_raw"
        out_dir.mkdir(exist_ok=True)

        try:
            datasets.download(
                exchange=exchange,
                data_types=["trades"],
                from_date=date,
                to_date=date,
                symbols=[symbol],
                api_key=api_key,
                download_dir=str(out_dir),
            )
        except Exception as exc:
            logger.debug("Tardis download error: %s", exc)
            return self._empty()

        return self._parse_tardis_dir(out_dir, path)

    def _parse_tardis_dir(self, out_dir: Path, cache_path: Path) -> pd.DataFrame:
        csv_files = sorted(out_dir.glob("*.csv.gz")) + sorted(out_dir.glob("*.csv"))
        if not csv_files:
            return self._empty()

        dfs: list[pd.DataFrame] = []
        for f in csv_files:
            try:
                compression = "gzip" if str(f).endswith(".gz") else None
                raw = pd.read_csv(f, compression=compression)
                ts_col = next((c for c in ("timestamp", "localTimestamp") if c in raw.columns), None)
                if ts_col is None:
                    continue
                dfs.append(pd.DataFrame({
                    "timestamp": pd.to_datetime(raw[ts_col], utc=True),
                    "price":     raw["price"].astype(float),
                    "size":      raw["amount"].astype(float),
                    "side":      raw["side"].str.lower(),
                }))
            except Exception as exc:
                logger.debug("Tardis parse error %s: %s", f, exc)

        if not dfs:
            return self._empty()

        df = pd.concat(dfs, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
        self._save_cache(cache_path, df)
        return df
