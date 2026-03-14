"""DataService — orquesta fuentes y publica en Redis."""
from __future__ import annotations
import json, logging, time
from typing import Optional, List, Dict
import numpy as np
import redis as redis_lib

from btquantr.config import config
from btquantr.redis_client import get_redis
from btquantr.data.sources.binance import BinanceSource
from btquantr.data.sources.yfinance_src import YFinanceSource
from btquantr.data.sources.alternative_me import FearGreedSource
from btquantr.data.sources.hyperliquid import HyperLiquidSource
from btquantr.data.sources.okx_liq import OKXLiqSource
from btquantr.monitoring import stats as _stats

log = logging.getLogger("DataService")


class DataService:
    def __init__(self, r: Optional[redis_lib.Redis] = None):
        self.r = r or get_redis()
        self.binance = BinanceSource()
        self.yfinance = YFinanceSource()
        self.fear_greed = FearGreedSource()
        self.hyperliquid = HyperLiquidSource()
        self.okx_liq = OKXLiqSource()

    def _pub(self, key: str, value) -> None:
        self.r.set(key, json.dumps(value) if isinstance(value, (dict, list)) else str(value))

    def fetch_once(self, symbol: str) -> dict:
        published, errors = [], []
        hl_coin = symbol.replace("USDT", "").replace("BUSD", "")

        # ── Primario: HyperLiquid (una sola llamada → precio + funding + OI) ──
        hl_ctx = self.hyperliquid.get_asset_ctx(hl_coin)
        if hl_ctx:
            # Precio principal
            self._pub(f"market:{symbol}:price", hl_ctx["markPrice"])
            published.append(f"market:{symbol}:price")
            # Funding principal (formato lista para compatibilidad con FeatureCollector)
            self._pub(f"derivatives:{symbol}:funding",
                      [{"fundingRate": hl_ctx["funding"]}])
            published.append(f"derivatives:{symbol}:funding")
            # OI principal
            self._pub(f"derivatives:{symbol}:oi",
                      {"openInterest": hl_ctx["openInterest"]})
            published.append(f"derivatives:{symbol}:oi")
            # Snapshot de OI al stream para calcular oi_change en FeatureCollector
            oi_val = hl_ctx.get("openInterest", 0)
            if oi_val:
                self.r.xadd(
                    f"derivatives:{symbol}:oi_stream",
                    {"oi": str(oi_val)},
                    maxlen=500,
                    approximate=True,
                )
            _stats.track_source(self.r, "hyperliquid", True)
        else:
            errors.extend(["price", "funding", "oi"])
            _stats.track_source(self.r, "hyperliquid", False, "get_asset_ctx returned None")

        # ── Secundario: Binance (cross-validation features) ───────────────────
        bn_funding = self.binance.get_funding_rate(symbol, limit=3)
        if bn_funding:
            self._pub(f"derivatives:{symbol}:funding_bn", bn_funding)
            published.append(f"derivatives:{symbol}:funding_bn")
            # Divergencia: HL − Binance (HL es primario)
            if hl_ctx:
                bn_rate = float(bn_funding[0].get("fundingRate", 0))
                divergence = round(hl_ctx["funding"] - bn_rate, 8)
                self._pub(f"derivatives:{symbol}:funding_divergence", divergence)
                published.append(f"derivatives:{symbol}:funding_divergence")
            _stats.track_source(self.r, "binance", True)
        else:
            errors.append("funding_bn")
            _stats.track_source(self.r, "binance", False, "funding_rate returned None")

        bn_oi = self.binance.get_open_interest(symbol)
        if bn_oi:
            self._pub(f"derivatives:{symbol}:oi_bn", bn_oi)
            published.append(f"derivatives:{symbol}:oi_bn")
            _stats.track_source(self.r, "binance", True)
        else:
            errors.append("oi_bn")
            _stats.track_source(self.r, "binance", False, "open_interest returned None")

        # Long/Short ratio — solo disponible en Binance
        ls = self.binance.get_long_short_ratio(symbol)
        if ls:
            self._pub(f"derivatives:{symbol}:long_short", ls)
            published.append(f"derivatives:{symbol}:long_short")
            _stats.track_source(self.r, "binance", True)
        else:
            errors.append("long_short")
            _stats.track_source(self.r, "binance", False, "long_short returned None")

        # ── HyperLiquid Orderbook — imbalance como feature HMM ───────────────
        ob = self.hyperliquid.get_orderbook(hl_coin, depth=10)
        if ob:
            self._pub(f"derivatives:{symbol}:orderbook", ob)
            self.r.expire(f"derivatives:{symbol}:orderbook", 120)  # TTL 2min
            published.append(f"derivatives:{symbol}:orderbook")
        else:
            errors.append("orderbook")

        # ── Top positions — sentimiento institucional ─────────────────────────
        try:
            top_pos = self.hyperliquid.get_top_positions(hl_coin, top_n=5)
            if top_pos:
                net = sum(p["net_exposure"] for p in top_pos)
                self._pub(f"derivatives:{symbol}:top_positions", {
                    "positions": top_pos,
                    "net_exposure": round(net, 4),
                    "count": len(top_pos),
                })
                self.r.expire(f"derivatives:{symbol}:top_positions", 300)  # TTL 5min
                published.append(f"derivatives:{symbol}:top_positions")
        except Exception as e:
            log.debug("top_positions error para %s: %s", symbol, e)
            errors.append("top_positions")

        # ── OKX liquidations — señal de cascada (sin API key) ─────────────────
        liq = self.okx_liq.get_liq_summary(hl_coin)
        if liq:
            self._pub(f"derivatives:{symbol}:okx_liq", liq)
            published.append(f"derivatives:{symbol}:okx_liq")
            _stats.track_source(self.r, "okx", True)
        else:
            errors.append("okx_liq")
            _stats.track_source(self.r, "okx", False, "okx_liq returned None")

        # ── OHLCV: velas 1h y 4h para TechnicalAnalyst ───────────────────
        try:
            klines_1h = self.binance.get_klines(symbol, interval="1h", limit=50)
            klines_4h = self.binance.get_klines(symbol, interval="4h", limit=30)
            if klines_1h and len(klines_1h) >= 2:
                self._pub(f"market:{symbol}:ohlcv_1h", self._klines_to_candles(klines_1h))
                self.r.expire(f"market:{symbol}:ohlcv_1h", 7200)
                published.append(f"market:{symbol}:ohlcv_1h")
            if klines_4h and len(klines_4h) >= 2:
                self._pub(f"market:{symbol}:ohlcv_4h", self._klines_to_candles(klines_4h))
                self.r.expire(f"market:{symbol}:ohlcv_4h", 18000)
                published.append(f"market:{symbol}:ohlcv_4h")
        except Exception as e:
            log.warning(f"OHLCV fetch failed for {symbol}: {e}")
            errors.extend(["ohlcv_1h", "ohlcv_4h"])

        return {"symbol": symbol, "published": published, "errors": errors}

    def fetch_macro_once(self) -> dict:
        published = []
        try:
            self._pub("macro:markets", self.yfinance.get_all_macro())
            published.append("macro:markets")
            _stats.track_source(self.r, "yfinance", True)
        except Exception as e:
            _stats.track_source(self.r, "yfinance", False, str(e))
        fg = self.fear_greed.get_latest()
        if fg:
            self._pub("sentiment:fear_greed", fg)
            published.append("sentiment:fear_greed")
            _stats.track_source(self.r, "alternative_me", True)
        else:
            _stats.track_source(self.r, "alternative_me", False, "get_latest returned None")
        return {"published": published}

    def fetch_social_once(self) -> dict:
        """Fetch datos sociales: leaderboard HL."""
        published = []
        lb = self.hyperliquid.get_leaderboard(time_window="allTime", top_n=20)
        if lb:
            self._pub("social:leaderboard", lb)
            self.r.expire("social:leaderboard", 3600)  # TTL 1h
            published.append("social:leaderboard")
            _stats.track_source(self.r, "hyperliquid", True)
        else:
            _stats.track_source(self.r, "hyperliquid", False, "leaderboard returned empty")
        return {"published": published}

    def bootstrap_history(self, symbol: str, period: str = "1h", limit: int = 500) -> List[Dict]:
        """Descarga histórico de las 7 features y las alinea temporalmente por hora.

        Retorna lista de dicts con keys: returns, volatility, funding,
        open_interest, long_short, fear_greed, vix — listos para el HMM.
        """
        # Descargar datasets históricos
        hl_coin = symbol.replace("USDT", "").replace("BUSD", "")
        klines = self.binance.get_klines(symbol, interval=period, limit=limit + 1)
        # Funding primario: HyperLiquid (key "time" en ms, "fundingRate")
        funding_hist = self.hyperliquid.get_funding_history(hl_coin, limit=1000)
        # OI histórico: Binance openInterestHist (HL no tiene histórico de OI)
        oi_hist = self.binance.get_open_interest_history(symbol, period=period, limit=limit)
        # L/S ratio: solo Binance
        ls_hist = self.binance.get_long_short_ratio_history(symbol, period=period, limit=limit)
        fg_hist = self.fear_greed.get_history(limit=365)
        vix_hist = self.yfinance.get_vix_history(days=limit // 24 + 30)

        if len(klines) < 2:
            return []

        # Indexar por timestamp (ms) para join rápido
        def _ts_index(rows, ts_key, val_key):
            return {int(r[ts_key]): float(r[val_key]) for r in rows if r}

        # HL funding usa "time" (ms) y "fundingRate"
        funding_idx = _ts_index(funding_hist, "time", "fundingRate") if funding_hist else {}
        oi_idx = _ts_index(oi_hist, "timestamp", "openInterest") if oi_hist else {}
        ls_idx = _ts_index(ls_hist, "timestamp", "longShortRatio") if ls_hist else {}

        # Fear & Greed — diario → propagar al bloque horario del día
        fg_daily: Dict[int, float] = {}
        for d in fg_hist:
            day_ts = (int(d["timestamp"]) // 86400) * 86400 * 1000
            fg_daily[day_ts] = float(d["value"]) / 100.0

        # VIX — diario → propagar
        vix_daily: Dict[int, float] = {}
        for d in vix_hist:
            day_ts = (int(d["timestamp"]) // (86400 * 1000)) * 86400 * 1000
            vix_daily[day_ts] = float(d["close"]) / 100.0

        # Construir feature vectors alineados por vela
        rows = []
        closes = [float(k[4]) for k in klines]
        for i in range(1, len(klines)):
            ts_ms = int(klines[i][0])
            close = closes[i]
            prev_close = closes[i - 1]

            ret = float(np.log(close / prev_close)) if prev_close > 0 else 0.0
            # Volatilidad: std de últimos 21 retornos
            window = closes[max(0, i - 20): i + 1]
            vol = float(np.std(np.diff(np.log(window)))) if len(window) >= 3 else 0.0

            # Funding: buscar el periodo 8h más cercano (anterior)
            funding_val = self._nearest(funding_idx, ts_ms, window_ms=8 * 3600 * 1000)
            oi_val = oi_idx.get(ts_ms)
            ls_val = ls_idx.get(ts_ms)

            day_ts = (ts_ms // (86400 * 1000)) * 86400 * 1000
            fg_val = fg_daily.get(day_ts)
            vix_val = vix_daily.get(day_ts)

            feat: Dict[str, float] = {"returns": ret, "volatility": vol}
            if funding_val is not None:
                feat["funding"] = funding_val
            if oi_val is not None:
                feat["open_interest"] = oi_val
            if ls_val is not None:
                feat["long_short"] = ls_val
            if fg_val is not None:
                feat["fear_greed"] = fg_val
            if vix_val is not None:
                feat["vix"] = vix_val

            rows.append(feat)

        return rows

    @staticmethod
    def _klines_to_candles(klines: list) -> list:
        """Convierte klines Binance [open_time,o,h,l,c,v,...] a lista de dicts {t,o,h,l,c,v}."""
        return [
            {
                "t": int(k[0]),
                "o": float(k[1]),
                "h": float(k[2]),
                "l": float(k[3]),
                "c": float(k[4]),
                "v": float(k[5]),
            }
            for k in klines
        ]

    @staticmethod
    def _nearest(idx: Dict[int, float], ts_ms: int, window_ms: int) -> Optional[float]:
        """Retorna el valor más reciente dentro de window_ms anterior a ts_ms."""
        best_ts = None
        for t in idx:
            if ts_ms - window_ms <= t <= ts_ms:
                if best_ts is None or t > best_ts:
                    best_ts = t
        return idx[best_ts] if best_ts is not None else None

    def heartbeat(self) -> None:
        self.r.set("health:data_service", json.dumps({
            "status": "ok", "timestamp": time.time(), "symbols": config.hmm.symbols}))

    def run(self) -> None:
        log.info(f"DataService iniciado — {config.hmm.symbols}")
        cycle = 0
        while True:
            for sym in config.hmm.symbols:
                try:
                    self.fetch_once(sym)
                except Exception as e:
                    log.error(f"Error fetch_once({sym}): {e}")
            try:
                self.fetch_macro_once()
                if cycle % 10 == 0:
                    self.fetch_social_once()
            except Exception as e:
                log.error(f"Error fetch_macro/social: {e}")
            self.heartbeat()
            cycle += 1
            time.sleep(config.data.fetch_interval)
