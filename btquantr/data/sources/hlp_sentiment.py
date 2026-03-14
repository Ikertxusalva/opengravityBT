"""HLPSentimentTracker — Rastrea el sentimiento del HLP (HyperLiquid Protocol) vault.

Endpoint: POST https://api.hyperliquid.xyz/info
Payload:  {"type": "clearinghouseState", "user": "<HLP_VAULT_ADDRESS>"}

Métricas:
- net_delta:      suma de posiciones en USD (long positivo, short negativo)
- z_score_24h:    (net_delta - media_24h) / std_24h (rolling 24h)
- sentiment:      "BULLISH" | "BEARISH" | "NEUTRAL"
- largest_position: símbolo con mayor exposición absoluta

Redis:
- hlp:sentiment          → JSON snapshot (set)
- hlp:net_delta_history  → list de floats, máx 24 entradas
"""
from __future__ import annotations

import asyncio
import json
import logging
import statistics
import time
from typing import Optional

log = logging.getLogger("HLPSentimentTracker")

_HL_API = "https://api.hyperliquid.xyz/info"


class HLPSentimentTracker:
    HLP_VAULT = "0x010461c14e146ac35fe42271bdc1134ee31c703a"

    def __init__(self, redis_client=None, http_client=None):
        self.redis = redis_client
        self._http = http_client  # httpx.AsyncClient

    # ── HTTP helper ──────────────────────────────────────────────────────────

    async def _post(self, payload: dict) -> Optional[dict]:
        """POST al endpoint de HyperLiquid. Devuelve JSON o None en error."""
        try:
            if self._http is not None:
                resp = await self._http.post(_HL_API, json=payload)
                resp.raise_for_status()
                return resp.json()
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(_HL_API, json=payload)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            log.debug("HLP API error: %s", exc)
            return None

    # ── Parseo ───────────────────────────────────────────────────────────────

    def _parse_positions(self, state: dict) -> list[dict]:
        """Extrae posiciones del clearinghouseState.

        Formato HL:
            {"assetPositions": [
                {"position": {"coin": "BTC", "szi": "0.5", "entryPx": "50000"},
                 "type": "oneWay"},
                ...
            ]}

        szi positivo → long, negativo → short
        size_usd ≈ abs(szi) * entryPx
        """
        result: list[dict] = []
        for item in state.get("assetPositions", []):
            pos = item.get("position", {})
            coin = pos.get("coin", "")
            try:
                szi = float(pos.get("szi", "0"))
                entry_px = float(pos.get("entryPx", "0"))
            except (ValueError, TypeError):
                continue
            size_usd = abs(szi) * entry_px
            side = "long" if szi >= 0 else "short"
            result.append({"symbol": coin, "size_usd": size_usd, "side": side})
        return result

    # ── Cálculos ─────────────────────────────────────────────────────────────

    def _calculate_net_delta(self, positions: list[dict]) -> float:
        """Suma size_usd positivo para longs, negativo para shorts."""
        total = 0.0
        for p in positions:
            if p["side"] == "long":
                total += p["size_usd"]
            else:
                total -= p["size_usd"]
        return total

    def _calculate_z_score(self, current: float, history: list[float]) -> float:
        """z = (current - mean) / std.

        Retorna 0.0 si history < 2 o std == 0.
        Usa desviación estándar muestral (ddof=1, statistics.stdev).
        """
        if len(history) < 2:
            return 0.0
        mean = statistics.mean(history)
        try:
            std = statistics.stdev(history)
        except statistics.StatisticsError:
            return 0.0
        if std == 0.0:
            return 0.0
        return (current - mean) / std

    def _classify_sentiment(self, z_score: float) -> str:
        """BULLISH si z > 1, BEARISH si z < -1, NEUTRAL en otro caso."""
        if z_score > 1.0:
            return "BULLISH"
        if z_score < -1.0:
            return "BEARISH"
        return "NEUTRAL"

    # ── Redis helpers ────────────────────────────────────────────────────────

    def _get_history(self) -> list[float]:
        """Lee hlp:net_delta_history desde Redis (más recientes al final)."""
        if self.redis is None:
            return []
        try:
            raw = self.redis.lrange("hlp:net_delta_history", 0, -1)
            return [float(x) for x in raw]
        except Exception:
            return []

    def _append_history(self, value: float) -> None:
        """Añade value a hlp:net_delta_history y recorta a 24 entradas."""
        if self.redis is None:
            return
        try:
            self.redis.rpush("hlp:net_delta_history", str(value))
            self.redis.ltrim("hlp:net_delta_history", -24, -1)
        except Exception as exc:
            log.debug("Redis append history error: %s", exc)

    def _publish_snapshot(self, snapshot: dict) -> None:
        """Publica snapshot en hlp:sentiment como JSON."""
        if self.redis is None:
            return
        try:
            self.redis.set("hlp:sentiment", json.dumps(snapshot))
        except Exception as exc:
            log.debug("Redis publish error: %s", exc)

    # ── Interfaz pública ─────────────────────────────────────────────────────

    async def fetch(self) -> dict:
        """Llama API, calcula métricas, publica en Redis y retorna snapshot."""
        payload = {"type": "clearinghouseState", "user": self.HLP_VAULT}
        state = await self._post(payload) or {}

        positions = self._parse_positions(state)
        net_delta = self._calculate_net_delta(positions)

        history = self._get_history()
        z_score = self._calculate_z_score(net_delta, history)
        sentiment = self._classify_sentiment(z_score)

        # Posición con mayor exposición absoluta
        largest: dict = {}
        if positions:
            largest_pos = max(positions, key=lambda p: p["size_usd"])
            largest = largest_pos.copy()

        snapshot = {
            "ts": int(time.time() * 1000),
            "net_delta": net_delta,
            "z_score_24h": z_score,
            "sentiment": sentiment,
            "largest_position": largest,
            "position_count": len(positions),
        }

        self._append_history(net_delta)
        self._publish_snapshot(snapshot)

        return snapshot

    async def run_loop(self, interval_seconds: int = 3600) -> None:
        """Llama fetch() cada interval_seconds indefinidamente."""
        while True:
            try:
                snapshot = await self.fetch()
                log.info(
                    "HLP sentiment: %s | net_delta=%.0f | z=%.2f",
                    snapshot["sentiment"],
                    snapshot["net_delta"],
                    snapshot["z_score_24h"],
                )
            except Exception as exc:
                log.error("HLP fetch error: %s", exc)
            await asyncio.sleep(interval_seconds)
