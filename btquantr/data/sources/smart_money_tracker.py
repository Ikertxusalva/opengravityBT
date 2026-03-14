"""SmartMoneyTracker — Trackea posiciones de top traders HL y genera señales.

Monitorea las posiciones abiertas de los top_n traders del leaderboard de
HyperLiquid para un símbolo dado. Genera una señal de dirección cuando más de
`threshold` smart money traders están alineados en la misma dirección.

Publica en Redis:
    smart_money:{symbol}:signal    → dict con dirección, conteos y timestamp
    smart_money:{symbol}:positions → lista de posiciones raw de smart money
"""
from __future__ import annotations

import json
import logging
import time
from typing import List, Dict, Optional

log = logging.getLogger("SmartMoneyTracker")


class SmartMoneyTracker:
    """Trackea posiciones de top 100 traders HL. Genera señal cuando >threshold
    smart money abren en la misma dirección para un símbolo.

    Publica en Redis:
        smart_money:{symbol}:signal  → {"direction": "long"|"short"|"neutral",
                                        "count": int, "threshold": int,
                                        "long_count": int, "short_count": int,
                                        "ts": float}
        smart_money:{symbol}:positions → lista de posiciones raw de smart money
    """

    def __init__(
        self,
        r=None,
        threshold: int = 3,
        top_n: int = 100,
        _hl_source=None,
    ):
        self.r = r
        self.threshold = threshold
        self.top_n = top_n
        self._hl = _hl_source

    def _hl_or_default(self):
        if self._hl is not None:
            return self._hl
        from btquantr.data.sources.hyperliquid import HyperLiquidSource
        return HyperLiquidSource()

    def get_smart_money_positions(self, coin: str) -> List[Dict]:
        """Obtiene posiciones de top_n traders para una coin.

        Cada dict: {"address", "szi", "side": "long"|"short", "notional", "entry_px"}

        Filtra posiciones con szi == 0.
        """
        hl = self._hl_or_default()

        mark_price = hl.get_mark_price(coin)
        if mark_price is None or mark_price <= 0:
            log.warning("mark_price no disponible para %s", coin)
            return []

        traders = hl.get_leaderboard(top_n=self.top_n)
        if not traders:
            log.debug("get_leaderboard retornó vacío para %s", coin)
            return []

        positions: List[Dict] = []
        for trader in traders:
            addr = trader.get("address", "")
            if not addr:
                continue

            try:
                state = hl._post({"type": "clearinghouseState", "user": addr})
            except Exception as exc:
                log.debug("clearinghouseState error para %s: %s", addr, exc)
                continue

            if not isinstance(state, dict):
                continue

            for ap in state.get("assetPositions", []):
                pos = ap.get("position", {})
                if pos.get("coin") != coin:
                    continue

                szi = float(pos.get("szi", 0))
                if szi == 0:
                    continue

                entry_px_raw = pos.get("entryPx")
                entry_px = float(entry_px_raw) if entry_px_raw is not None else 0.0
                notional = abs(szi) * mark_price

                positions.append({
                    "address":   addr,
                    "szi":       szi,
                    "side":      "long" if szi > 0 else "short",
                    "notional":  round(notional, 2),
                    "entry_px":  entry_px,
                })

        return positions

    def compute_signal(self, coin: str) -> Dict:
        """Calcula señal de smart money para una coin.

        Returns:
            {
                "direction":   "long" | "short" | "neutral",
                "count":       int,   # max(long_count, short_count)
                "threshold":   int,
                "long_count":  int,
                "short_count": int,
                "ts":          float,
            }

        Lógica:
            - "long"  si long_count  > threshold
            - "short" si short_count > threshold
            - "neutral" en cualquier otro caso (incluyendo empate)
        """
        try:
            positions = self.get_smart_money_positions(coin)
        except Exception as exc:
            log.warning("compute_signal error obteniendo posiciones para %s: %s", coin, exc)
            positions = []

        long_count  = sum(1 for p in positions if p["side"] == "long")
        short_count = sum(1 for p in positions if p["side"] == "short")

        if long_count > self.threshold:
            direction = "long"
            count = long_count
        elif short_count > self.threshold:
            direction = "short"
            count = short_count
        else:
            direction = "neutral"
            count = max(long_count, short_count)

        return {
            "direction":   direction,
            "count":       count,
            "threshold":   self.threshold,
            "long_count":  long_count,
            "short_count": short_count,
            "ts":          time.time(),
        }

    def publish(self, symbol: str) -> Dict:
        """Calcula señal y publica en Redis las keys signal y positions.

        Publica:
            smart_money:{symbol}:signal    → signal dict
            smart_money:{symbol}:positions → lista de posiciones raw

        Returns:
            signal dict
        """
        # Para get_smart_money_positions usamos el coin sin sufijo USDT si es cripto,
        # pero el caller puede pasar cualquier identificador; usamos symbol directo
        # en las keys Redis y como coin en las llamadas HL.
        signal = self.compute_signal(symbol)

        try:
            positions = self.get_smart_money_positions(symbol)
        except Exception as exc:
            log.warning("publish: error obteniendo posiciones para %s: %s", symbol, exc)
            positions = []

        if self.r is not None:
            try:
                self.r.set(
                    f"smart_money:{symbol}:signal",
                    json.dumps(signal),
                )
                self.r.set(
                    f"smart_money:{symbol}:positions",
                    json.dumps(positions),
                )
            except Exception as exc:
                log.warning("publish: error escribiendo Redis para %s: %s", symbol, exc)

        return signal

    def run_loop(self, symbols: List[str], interval_s: int = 300) -> None:
        """Loop cada interval_s segundos publicando señales para todos los símbolos.

        Se detiene con Ctrl+C (KeyboardInterrupt).
        """
        log.info(
            "SmartMoneyTracker loop iniciado — símbolos=%s interval=%ds threshold=%d",
            symbols, interval_s, self.threshold,
        )
        try:
            while True:
                for symbol in symbols:
                    try:
                        signal = self.publish(symbol)
                        log.info(
                            "[%s] direction=%s long=%d short=%d",
                            symbol,
                            signal["direction"],
                            signal["long_count"],
                            signal["short_count"],
                        )
                    except Exception as exc:
                        log.warning("run_loop error para %s: %s", symbol, exc)
                time.sleep(interval_s)
        except KeyboardInterrupt:
            log.info("SmartMoneyTracker loop detenido por el usuario.")
