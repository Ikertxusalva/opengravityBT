"""HyperLiquid WebSocket — tick data en tiempo real."""
from __future__ import annotations
import asyncio
import json
import logging
from pathlib import Path
import pandas as pd
from .base import BaseTickSource, TICK_COLUMNS

logger = logging.getLogger(__name__)
HL_WS_URL = "wss://api.hyperliquid.xyz/ws"


def _coin_from_symbol(symbol: str) -> str:
    """BTCUSDT → BTC, xyz:CL → CL, BTC → BTC."""
    if ":" in symbol:
        return symbol.split(":")[-1]
    if symbol.upper().endswith("USDT"):
        return symbol[:-4].upper()
    return symbol.upper()


def _build_subscribe_msg(coin: str) -> dict:
    return {"method": "subscribe", "subscription": {"type": "trades", "coin": coin}}


class HLWebSocketTickSource(BaseTickSource):
    source_prefix = "hl"

    def _parse_trades_msg(self, msg: dict) -> list[dict]:
        rows = []
        if msg.get("channel") != "trades":
            return rows
        for t in msg.get("data", []):
            rows.append({
                "timestamp": pd.Timestamp(int(t["time"]), unit="ms", tz="UTC"),
                "price": float(t["px"]),
                "size": float(t["sz"]),
                "side": "buy" if t["side"] == "B" else "sell",
            })
        return rows

    async def _collect(self, symbol: str, duration_seconds: int) -> pd.DataFrame:
        try:
            import websockets  # optional dep
        except ImportError:
            logger.warning("websockets not installed — pip install websockets")
            return self._empty()

        coin = _coin_from_symbol(symbol)
        rows: list[dict] = []
        try:
            async with websockets.connect(HL_WS_URL) as ws:
                await ws.send(json.dumps(_build_subscribe_msg(coin)))
                deadline = asyncio.get_event_loop().time() + duration_seconds
                while asyncio.get_event_loop().time() < deadline:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        rows.extend(self._parse_trades_msg(json.loads(raw)))
                    except asyncio.TimeoutError:
                        break
        except Exception as exc:
            logger.debug("HL WebSocket error: %s", exc)

        return pd.DataFrame(rows, columns=TICK_COLUMNS) if rows else self._empty()

    def download(self, symbol: str, duration_seconds: int = 30, **kwargs) -> pd.DataFrame:
        path = self._cache_path(symbol)
        if not kwargs.get("no_cache"):
            cached = self._load_cache(path)
            if cached is not None:
                return cached
        df = asyncio.run(self._collect(symbol, duration_seconds))
        if not df.empty:
            self._save_cache(path, df)
        return df
