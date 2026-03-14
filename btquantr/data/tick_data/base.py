"""Base class para tick data sources con caché parquet TTL 24h."""
from __future__ import annotations
import time
from pathlib import Path
import pandas as pd

TICK_COLUMNS = ["timestamp", "price", "size", "side"]


class BaseTickSource:
    source_prefix: str = "base"
    TTL_SECONDS: int = 24 * 3600

    def __init__(self, ticks_dir: Path):
        self.ticks_dir = ticks_dir
        self.ticks_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, symbol: str) -> Path:
        clean = symbol.replace("/", "_").replace(":", "_")
        return self.ticks_dir / f"{self.source_prefix}_{clean}.parquet"

    def _is_cache_valid(self, path: Path) -> bool:
        if not path.exists():
            return False
        return time.time() - path.stat().st_mtime < self.TTL_SECONDS

    def _load_cache(self, path: Path) -> pd.DataFrame | None:
        if self._is_cache_valid(path):
            return pd.read_parquet(path)
        return None

    def _save_cache(self, path: Path, df: pd.DataFrame) -> None:
        df.to_parquet(path, index=False)

    def _empty(self) -> pd.DataFrame:
        return pd.DataFrame(columns=TICK_COLUMNS)

    def download(self, symbol: str, **kwargs) -> pd.DataFrame:
        raise NotImplementedError
