"""HyperLiquid Info API — datos de mercado sin clave, base para ejecución en Fase 3.

Endpoints: POST https://api.hyperliquid.xyz/info
Docs: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
"""
from __future__ import annotations
import httpx, time, logging
from typing import Optional, Dict, List

log = logging.getLogger("HyperLiquidSource")
BASE = "https://api.hyperliquid.xyz/info"


class HyperLiquidSource:
    def __init__(self, timeout: float = 10.0, _cache_manager=None):
        self.timeout = timeout
        self._cm = _cache_manager

    def _cm_or_default(self):
        if self._cm is not None:
            return self._cm
        from btquantr.data.cache_manager import CacheManager
        return CacheManager()

    def _post(self, payload: dict) -> Optional[dict | list]:
        try:
            r = httpx.post(BASE, json=payload, timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.debug(f"HyperLiquid API error: {e}")
            return None

    def get_meta_and_asset_ctxs(self, dex: Optional[str] = None,
                                cursor: Optional[str] = None) -> dict:
        """Retorna meta + asset contexts (OI, funding, mark price, etc.) en una llamada.

        Args:
            dex:    Si se especifica (ej. "xyz"), obtiene activos HIP3 tokenizados.
                    Sin dex retorna los crypto perps estándar.
            cursor: Token de paginación para obtener la siguiente página de activos.

        Returns:
            Dict con "meta", "ctxs" y "nextCursor" (None si no hay más páginas).
        """
        payload: dict = {"type": "metaAndAssetCtxs"}
        if dex is not None:
            payload["dex"] = dex
        if cursor is not None:
            payload["cursor"] = cursor
        result = self._post(payload)
        if isinstance(result, list) and len(result) == 2:
            meta, ctxs = result
            return {
                "meta": meta,
                "ctxs": ctxs,
                "nextCursor": meta.get("nextCursor"),
            }
        return {"meta": {}, "ctxs": [], "nextCursor": None}

    def get_asset_ctx(self, coin: str) -> Optional[Dict]:
        """Retorna el asset context de una coin específica: OI, funding, mark price."""
        data = self.get_meta_and_asset_ctxs()
        meta = data.get("meta", {})
        ctxs = data.get("ctxs", [])
        universe = meta.get("universe", [])
        for i, asset in enumerate(universe):
            if asset.get("name") == coin and i < len(ctxs):
                ctx = ctxs[i]
                return {
                    "coin": coin,
                    "openInterest": float(ctx.get("openInterest", 0)),
                    "funding": float(ctx.get("funding", 0)),
                    "markPrice": float(ctx.get("markPx", 0)),
                    "oraclePx": float(ctx.get("oraclePx", 0)),
                }
        return None

    def get_funding_history(self, coin: str, limit: int = 500) -> List[Dict]:
        """Historial de funding rates. startTime = hace limit horas (HL actualiza c/hora)."""
        start_ms = int((time.time() - limit * 3600) * 1000)
        result = self._post({"type": "fundingHistory", "coin": coin, "startTime": start_ms})
        if not isinstance(result, list):
            return []
        return [
            {"time": int(d["time"]), "fundingRate": float(d["fundingRate"]),
             "premium": float(d.get("premium", 0))}
            for d in result
        ]

    def get_mark_price(self, coin: str) -> Optional[float]:
        ctx = self.get_asset_ctx(coin)
        return ctx["markPrice"] if ctx else None

    def get_funding_divergence(self, coin: str, binance_rate: float) -> float:
        """Divergencia entre Binance y HyperLiquid (útil como feature HMM)."""
        ctx = self.get_asset_ctx(coin)
        if ctx is None:
            return 0.0
        hl_rate = ctx["funding"]
        return round(binance_rate - hl_rate, 8)

    def get_orderbook(self, coin: str, depth: int = 10) -> Optional[Dict]:
        """Orderbook snapshot via l2Book endpoint.

        Args:
            coin:  Nombre sin USDT (ej. "BTC")
            depth: Niveles a considerar para el cálculo de imbalance

        Returns:
            Dict con: bid_volume, ask_volume, imbalance, spread, best_bid, best_ask
            None si falla.
        """
        cm = self._cm_or_default()
        cached = cm.get_json(f"orderbook_{coin}", ttl_hours=24)
        if cached is not None:
            return cached
        try:
            result = self._post({"type": "l2Book", "coin": coin, "nSigFigs": 5})
            if not isinstance(result, dict):
                return None

            levels = result.get("levels", [[], []])
            if len(levels) < 2:
                return None

            bids = levels[0][:depth]  # desc: mejor bid primero
            asks = levels[1][:depth]  # asc: mejor ask primero

            bid_vol = sum(float(b["sz"]) for b in bids)
            ask_vol = sum(float(a["sz"]) for a in asks)
            total = bid_vol + ask_vol

            imbalance = (bid_vol - ask_vol) / total if total > 0 else 0.0

            best_bid = float(bids[0]["px"]) if bids else 0.0
            best_ask = float(asks[0]["px"]) if asks else 0.0
            spread = best_ask - best_bid if best_bid > 0 and best_ask > 0 else 0.0

            ob = {
                "bid_volume": bid_vol,
                "ask_volume": ask_vol,
                "imbalance": round(imbalance, 6),
                "spread": round(spread, 6),
                "best_bid": best_bid,
                "best_ask": best_ask,
            }
            cm.set_json(f"orderbook_{coin}", ob, ttl_hours=24)
            return ob
        except Exception as exc:
            log.warning("get_orderbook error para %s: %s", coin, exc)
            return None

    def get_leaderboard(self, time_window: str = "allTime", top_n: int = 20) -> List[Dict]:
        """Top traders del leaderboard de HyperLiquid.

        Args:
            time_window: "allTime" | "day" | "week" | "month"
            top_n:       Número máximo de traders a retornar

        Returns:
            Lista de dicts con: address, account_value, pnl
            [] si falla.
        """
        cm = self._cm_or_default()
        cache_key = f"leaderboard_{time_window}_{top_n}"
        cached = cm.get_json(cache_key, ttl_hours=24)
        if cached is not None:
            return cached
        try:
            result = self._post({"type": "leaderboard", "req": {"timeWindow": time_window}})
            if not isinstance(result, dict):
                return []

            rows = result.get("leaderboardRows", [])[:top_n]
            traders: List[Dict] = []
            for row in rows:
                pnl = 0.0
                window_pnl = row.get("windowPnl", [])
                for wp in window_pnl:
                    if wp.get("timeWindow") == time_window:
                        pnl = float(wp.get("pnl", 0))
                        break

                traders.append({
                    "address":       row.get("ethAddress", ""),
                    "account_value": float(row.get("accountValue", 0)),
                    "pnl":           pnl,
                })
            cm.set_json(cache_key, traders, ttl_hours=24)
            return traders
        except Exception as exc:
            log.warning("get_leaderboard error: %s", exc)
            return []

    def get_top_positions(self, coin: str, top_n: int = 10) -> List[Dict]:
        """Posiciones abiertas de los top traders del leaderboard para una coin.

        Combina leaderboard (addresses) + clearinghouseState por address.

        Args:
            coin:  Nombre sin USDT (ej. "BTC")
            top_n: Número de top traders a consultar

        Returns:
            Lista de dicts con: address, szi, entry_px, net_exposure
            [] si falla.
        """
        cm = self._cm_or_default()
        cache_key = f"top_positions_{coin}_{top_n}"
        cached = cm.get_json(cache_key, ttl_hours=24)
        if cached is not None:
            return cached
        try:
            traders = self.get_leaderboard(top_n=top_n)
            if not traders:
                return []

            positions: List[Dict] = []
            for trader in traders[:top_n]:
                addr = trader["address"]
                if not addr:
                    continue
                state = self._post({"type": "clearinghouseState", "user": addr})
                if not isinstance(state, dict):
                    continue
                for ap in state.get("assetPositions", []):
                    pos = ap.get("position", {})
                    if pos.get("coin") != coin:
                        continue
                    szi = float(pos.get("szi", 0))
                    if szi == 0:
                        continue
                    positions.append({
                        "address":      addr,
                        "szi":          szi,
                        "entry_px":     float(pos.get("entryPx", 0)),
                        "net_exposure": szi,  # positivo=long, negativo=short
                    })

            cm.set_json(cache_key, positions, ttl_hours=24)
            return positions
        except Exception as exc:
            log.warning("get_top_positions error: %s", exc)
            return []

    def get_candles(self, coin: str, interval: str, start_ms: int, end_ms: int) -> "pd.DataFrame":
        """Candle snapshot de HyperLiquid. Sin API key. Paginable por startTime/endTime.

        Args:
            coin:     Nombre de la coin sin USDT (ej. "BTC", "ETH")
            interval: Intervalo HL (ej. "1h", "4h", "1d", "15m")
            start_ms: Timestamp inicio en milisegundos
            end_ms:   Timestamp fin en milisegundos

        Returns:
            DataFrame con columnas Open/High/Low/Close/Volume e índice datetime UTC.
            DataFrame vacío si falla o no hay datos.
        """
        import pandas as pd

        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": start_ms,
                "endTime": end_ms,
            },
        }
        result = self._post(payload)
        if not isinstance(result, list) or not result:
            return pd.DataFrame()

        try:
            df = pd.DataFrame(result)
            df["open_time"] = pd.to_datetime(df["t"], unit="ms", utc=True)
            df = df.set_index("open_time")
            df = df.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
            for col in ["Open", "High", "Low", "Close", "Volume"]:
                df[col] = df[col].astype(float)
            return df[["Open", "High", "Low", "Close", "Volume"]]
        except Exception as exc:
            log.warning("get_candles parse error para %s: %s", coin, exc)
            return pd.DataFrame()
