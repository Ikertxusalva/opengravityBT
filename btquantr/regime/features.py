"""FeatureCollector: lee features de Redis para el HMM."""
from __future__ import annotations
import json, logging
import numpy as np
from typing import Dict, List
import redis as redis_lib

log = logging.getLogger("FeatureCollector")


class FeatureCollector:
    def __init__(self, r: redis_lib.Redis):
        self.r = r
        self._buf: Dict[str, List[float]] = {}

    def collect(self, symbol: str) -> Dict[str, float]:
        f: Dict[str, float] = {}
        raw = self.r.get(f"market:{symbol}:price")
        if raw:
            p = float(raw)
            buf = self._buf.setdefault(symbol, [])
            buf.append(p)
            if len(buf) > 60:
                buf[:] = buf[-60:]
            if len(buf) >= 2:
                f["returns"] = float(np.log(buf[-1] / buf[-2]))
            if len(buf) >= 21:
                f["volatility"] = float(np.std(np.diff(np.log(buf[-21:]))))
        for key_t, redis_key, path in [
            ("funding", f"derivatives:{symbol}:funding", "[-1].fundingRate"),
            ("open_interest", f"derivatives:{symbol}:oi", "openInterest"),
            ("long_short", f"derivatives:{symbol}:long_short", "[-1].longShortRatio"),
        ]:
            try:
                raw = self.r.get(redis_key)
                if raw:
                    data = json.loads(raw)
                    val = self._extract(data, path)
                    if val is not None:
                        f[key_t] = float(val)
            except Exception:
                pass
        for key_t, redis_key, path, norm in [
            ("fear_greed", "sentiment:fear_greed", "value", lambda x: x / 100),
            ("vix", "macro:markets", "VIX.price", lambda x: x / 100),
        ]:
            try:
                raw = self.r.get(redis_key)
                if raw:
                    data = json.loads(raw)
                    val = self._extract(data, path)
                    if val is not None:
                        f[key_t] = norm(float(val))
            except Exception:
                pass
        # ── OI change rate desde stream ──────────────────────────────────────
        try:
            entries = self.r.xrevrange(f"derivatives:{symbol}:oi_stream", count=2)
            if len(entries) >= 2:
                oi_now  = float(entries[0][1][b"oi"])
                oi_prev = float(entries[1][1][b"oi"])
                if oi_prev > 0:
                    f["oi_change"] = (oi_now - oi_prev) / oi_prev
        except Exception:
            pass
        # ── Orderbook imbalance (HL) ─────────────────────────────────────────
        try:
            raw = self.r.get(f"derivatives:{symbol}:orderbook")
            if raw:
                ob = json.loads(raw)
                imbalance = ob.get("imbalance")
                if imbalance is not None:
                    f["orderbook_imbalance"] = float(imbalance)
        except Exception:
            pass
        # ── Top traders net exposure ─────────────────────────────────────────
        try:
            raw = self.r.get(f"derivatives:{symbol}:top_positions")
            if raw:
                top = json.loads(raw)
                net = top.get("net_exposure")
                if net is not None:
                    f["top_traders_exposure"] = float(net)
        except Exception:
            pass
        # ── OKX liquidation intensity ────────────────────────────────────────
        try:
            raw = self.r.get(f"derivatives:{symbol}:okx_liq")
            if raw:
                liq = json.loads(raw)
                net = float(liq.get("net_liq", 0))
                count = int(liq.get("count", 0))
                if count > 0:
                    # net_liq / (count * avg_usd_per_liq) → acotado [-1, 1]
                    raw_intensity = net / (count * 1_000.0)
                    f["liq_intensity"] = max(-1.0, min(1.0, raw_intensity))
        except Exception:
            pass
        # ── Smart Money bias (top traders HL) ───────────────────────────────
        try:
            raw = self.r.get(f"smart_money:{symbol}:signal")
            if raw:
                sig = json.loads(raw)
                direction = sig.get("direction", "neutral")
                f["smart_money_bias"] = 1.0 if direction == "long" else (-1.0 if direction == "short" else 0.0)
        except Exception:
            pass
        # ── Order Flow imbalance (HyperLiquid WebSocket, ventana 1h) ────────
        try:
            raw = self.r.get(f"orderflow:{symbol}:imbalance")
            if raw:
                imb = json.loads(raw)
                val = imb.get("1h")
                if val is not None:
                    f["orderflow_imbalance"] = float(val)
        except Exception:
            pass
        # ── Multi-exchange liquidation intensity (Binance + Bybit) ──────────
        try:
            raw = self.r.get(f"liq:combined:{symbol}")
            if raw:
                combined = json.loads(raw)
                vol = float(combined.get("total_volume_usd", 0))
                if vol > 0:
                    # Normalizar: $10M de liquidaciones → ±1.0
                    buy_vol = float(combined.get("buy_liq_usd", 0))
                    sell_vol = float(combined.get("sell_liq_usd", 0))
                    net_liq = (buy_vol - sell_vol) / 10_000_000.0
                    f["liq_multi_intensity"] = max(-1.0, min(1.0, net_liq))
        except Exception:
            pass
        # ── HLP vault sentiment z-score ──────────────────────────────────────
        try:
            raw = self.r.get("hlp:sentiment")
            if raw:
                hlp = json.loads(raw)
                z = hlp.get("z_score_24h")
                if z is not None:
                    # Acotar a [-3, 3] y normalizar
                    f["hlp_sentiment"] = max(-1.0, min(1.0, float(z) / 3.0))
        except Exception:
            pass
        return f

    @staticmethod
    def _extract(data, path: str):
        for part in path.split("."):
            if part.startswith("[") and part.endswith("]"):
                idx = int(part[1:-1])
                data = data[idx] if isinstance(data, list) and len(data) > abs(idx) else None
            else:
                data = data.get(part) if isinstance(data, dict) else None
            if data is None:
                return None
        return data
