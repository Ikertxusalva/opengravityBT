"""HyperLiquid Positions Source — posiciones abiertas con distancia a liquidación.

Usa clearinghouseState + leaderboard para detectar posiciones cercanas a liquidación.
Útil para la estrategia Liquidation Cascade en HIP3.
"""
from __future__ import annotations
import logging
from typing import Dict, List, Optional

log = logging.getLogger("HLPositionsSource")


class HLPositionsSource:
    """Posiciones abiertas en HyperLiquid filtradas por distancia a liquidación.

    Combina leaderboard (top N addresses) + clearinghouseState por address.
    La señal cascade se activa cuando el notional acumulado near-liq >= threshold.
    """

    def __init__(self, timeout: float = 10.0, _hl_source=None):
        self.timeout = timeout
        self._hl = _hl_source

    def _hl_or_default(self):
        if self._hl is not None:
            return self._hl
        from btquantr.data.sources.hyperliquid import HyperLiquidSource
        return HyperLiquidSource(timeout=self.timeout)

    def get_positions_raw(self, coin: str, top_n: int = 20) -> List[Dict]:
        """Posiciones brutas de los top N traders para una coin.

        Cada dict incluye: szi, liq_px, mark_px, notional, distance_to_liq_pct, side.
        """
        hl = self._hl_or_default()

        mark_price = hl.get_mark_price(coin)
        if mark_price is None or mark_price <= 0:
            return []

        traders = hl.get_leaderboard(top_n=top_n)
        if not traders:
            return []

        positions: List[Dict] = []
        for trader in traders:
            addr = trader.get("address", "")
            if not addr:
                continue
            state = hl._post({"type": "clearinghouseState", "user": addr})
            if not isinstance(state, dict):
                continue
            for ap in state.get("assetPositions", []):
                pos = ap.get("position", {})
                if pos.get("coin") != coin:
                    continue
                szi = float(pos.get("szi", 0))
                if szi == 0:
                    continue
                liq_px_raw = pos.get("liquidationPx")
                if liq_px_raw is None:
                    continue
                liq_px = float(liq_px_raw)
                if liq_px <= 0:
                    continue

                notional = abs(szi) * mark_price
                distance_to_liq = abs(mark_price - liq_px) / mark_price

                positions.append({
                    "address":            addr,
                    "szi":                szi,
                    "liq_px":             liq_px,
                    "mark_px":            mark_price,
                    "notional":           round(notional, 2),
                    "distance_to_liq_pct": round(distance_to_liq * 100, 4),
                    "side":               "long" if szi > 0 else "short",
                })

        return positions

    def get_positions_near_liq(
        self, coin: str, distance_pct: float = 2.5, top_n: int = 20
    ) -> List[Dict]:
        """Posiciones con distance_to_liq_pct <= distance_pct%."""
        try:
            all_pos = self.get_positions_raw(coin, top_n=top_n)
            return [p for p in all_pos if p["distance_to_liq_pct"] <= distance_pct]
        except Exception as exc:
            log.warning("get_positions_near_liq error para %s: %s", coin, exc)
            return []

    def get_cascade_signal(
        self,
        coin: str,
        distance_pct: float = 2.5,
        min_notional_usd: float = 250_000,
        top_n: int = 20,
    ) -> Dict:
        """Señal de liquidation cascade.

        Returns:
            {
                "long_notional":  float,  # notional de longs near liq
                "short_notional": float,  # notional de shorts near liq
                "long_cascade":   bool,   # long_notional >= min_notional_usd
                "short_cascade":  bool,   # short_notional >= min_notional_usd
            }
        """
        try:
            positions = self.get_positions_near_liq(coin, distance_pct=distance_pct, top_n=top_n)
            long_notional  = sum(p["notional"] for p in positions if p["side"] == "long")
            short_notional = sum(p["notional"] for p in positions if p["side"] == "short")
            return {
                "long_notional":  round(long_notional, 2),
                "short_notional": round(short_notional, 2),
                "long_cascade":   long_notional  >= min_notional_usd,
                "short_cascade":  short_notional >= min_notional_usd,
            }
        except Exception as exc:
            log.warning("get_cascade_signal error para %s: %s", coin, exc)
            return {
                "long_notional": 0.0, "short_notional": 0.0,
                "long_cascade": False, "short_cascade": False,
            }
