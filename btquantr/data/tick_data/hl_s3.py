"""HyperLiquid S3 Archive — fills históricos por bloque."""
from __future__ import annotations
import gzip
import json
import logging
from pathlib import Path
import httpx
import pandas as pd
from .base import BaseTickSource, TICK_COLUMNS

logger = logging.getLogger(__name__)
HL_S3_BASE = "https://hl-mainnet-node-data.s3.us-east-2.amazonaws.com"


class HLS3TickSource(BaseTickSource):
    source_prefix = "hl_s3"

    def _coin_matches(self, fill_coin: str, symbol: str) -> bool:
        """Compara coin del fill con el símbolo pedido."""
        base = symbol.upper().replace("USDT", "").replace("@", "")
        return fill_coin.upper().replace("@", "").startswith(base)

    def download(self, symbol: str, start_block: int = None, n_blocks: int = 10,
                 **kwargs) -> pd.DataFrame:
        if start_block is None:
            return self._empty()

        path = self._cache_path(symbol)
        if not kwargs.get("no_cache"):
            cached = self._load_cache(path)
            if cached is not None:
                return cached

        rows: list[dict] = []
        for block in range(start_block, start_block + n_blocks):
            url = f"{HL_S3_BASE}/node_fills_by_block/{block}.json.gz"
            try:
                resp = httpx.get(url, timeout=10.0)
                if resp.status_code != 200:
                    continue
                fills = json.loads(gzip.decompress(resp.content))
                for fill in fills:
                    if self._coin_matches(fill.get("coin", ""), symbol):
                        rows.append({
                            "timestamp": pd.Timestamp(int(fill["time"]), unit="ms", tz="UTC"),
                            "price": float(fill["px"]),
                            "size": float(fill["sz"]),
                            "side": "buy" if fill.get("side", "B") == "B" else "sell",
                        })
            except Exception as exc:
                logger.debug("HL S3 block %d error: %s", block, exc)

        df = pd.DataFrame(rows, columns=TICK_COLUMNS) if rows else self._empty()
        if not df.empty:
            self._save_cache(path, df)
        return df
