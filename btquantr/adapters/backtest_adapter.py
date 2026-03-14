"""
backtest_adapter.py
===================
TradeAdapter   — convierte stats._trades de backtesting.py al formato BTQUANTR.
HMMHistoryBuilder — entrena HMM sobre OHLCV histórico y devuelve serie de regímenes.

Ambas clases usan ÚNICAMENTE las mismas clases HMM del RegimeService para
garantizar que los regímenes históricos son consistentes con los del sistema en vivo.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

import numpy as np
import pandas as pd

from btquantr.data.sources.alternative_me import FearGreedSource
from btquantr.data.sources.hyperliquid import HyperLiquidSource
from btquantr.data.sources.okx_liq import OKXLiqSource

log = logging.getLogger("TradeAdapter")


# ─── alignment helpers (module-level para ser importables en tests) ──────────

def _align_daily_to_bars(
    series_s: dict[int, float],
    bar_index: pd.DatetimeIndex,
    default: float = 0.5,
) -> list[float]:
    """Alinea una serie con timestamps en segundos (diaria) a barras horarias.

    Usa forward-fill: cada barra toma el valor del último registro anterior.
    """
    if not series_s:
        return [default] * len(bar_index)

    sorted_ts = sorted(series_s.keys())
    result: list[float] = []
    for bar_ts in bar_index:
        ts_s = int(bar_ts.timestamp())
        # Último registro <= ts_s
        val = default
        for key in sorted_ts:
            if key <= ts_s:
                val = series_s[key]
            else:
                break
        result.append(val)
    return result


def _align_ms_to_bars(
    series_ms: dict[int, float],
    bar_index: pd.DatetimeIndex,
    default: float = 0.0,
) -> list[float]:
    """Alinea una serie con timestamps en milisegundos a barras horarias.

    Usa forward-fill: cada barra toma el valor del último registro anterior.
    """
    if not series_ms:
        return [default] * len(bar_index)

    sorted_ts = sorted(series_ms.keys())
    result: list[float] = []
    for bar_ts in bar_index:
        ts_ms = int(bar_ts.timestamp() * 1000)
        val = default
        for key in sorted_ts:
            if key <= ts_ms:
                val = series_ms[key]
            else:
                break
        result.append(val)
    return result

COMMISSION_PCT = 0.0004   # 0.04% taker HyperLiquid (por side)
SLIPPAGE_BPS   = 0.0002   # 2 bps por side


# ── HMMHistoryBuilder ─────────────────────────────────────────────────────────

class HMMHistoryBuilder:
    """
    Entrena el mismo GaussianHMM del RegimeDetector sobre OHLCV histórico
    y devuelve un dict {timestamp_float: 'BULL'|'SIDEWAYS'|'BEAR'} para
    enriquecer cada trade con el régimen del momento de entrada/salida.

    Features base: returns + volatility.
    Features opcionales: fear_greed, funding, liq_intensity.
    """

    def __init__(self, window: int = 500):
        self.window = window

    def build(
        self,
        ohlcv_df: pd.DataFrame,
        fear_greed_series: dict[int, float] | None = None,
        funding_series: dict[int, float] | None = None,
        liq_intensity_series: dict[int, float] | None = None,
    ) -> dict[float, str]:
        """Entrena HMM y etiqueta barras con régimen.

        Args:
            ohlcv_df: DataFrame OHLCV con índice DatetimeIndex.
            fear_greed_series: {unix_ts_s: value/100} — datos diarios Alternative.me.
            funding_series: {unix_ts_ms: fundingRate} — datos HL (cada ~8h).
            liq_intensity_series: {unix_ts_ms: intensity [-1,1]} — snapshot OKX.

        Returns:
            {timestamp_float: 'BULL'|'SIDEWAYS'|'BEAR'|'UNKNOWN'}
        """
        from btquantr.regime.detector import RegimeDetector

        closes = ohlcv_df["Close"].values.astype(float)
        log_ret = np.diff(np.log(closes + 1e-10))
        idx = ohlcv_df.index  # una barra más que log_ret

        # Alinear series opcionales a las barras del OHLCV
        fg_vals = _align_daily_to_bars(fear_greed_series or {}, idx, default=0.5)
        fund_vals = _align_ms_to_bars(funding_series or {}, idx, default=0.0)
        liq_vals = _align_ms_to_bars(liq_intensity_series or {}, idx, default=0.0)

        use_extra = bool(fear_greed_series or funding_series or liq_intensity_series)

        # Construir feature vectors (base + opcionales)
        feature_vectors = []
        feature_names = ["returns", "volatility"]
        if use_extra:
            feature_names += ["fear_greed", "funding", "liq_intensity"]

        for i in range(len(log_ret)):
            ret = log_ret[i]
            start = max(0, i - 20)
            vol = float(np.std(log_ret[start : i + 1])) if i >= 1 else 0.0
            bar_idx = i + 1  # barra OHLCV correspondiente a log_ret[i]
            vec: list[float] = [ret, vol]
            if use_extra:
                vec.append(float(fg_vals[bar_idx]) if bar_idx < len(fg_vals) else 0.5)
                vec.append(float(fund_vals[bar_idx]) if bar_idx < len(fund_vals) else 0.0)
                vec.append(float(liq_vals[bar_idx]) if bar_idx < len(liq_vals) else 0.0)
            feature_vectors.append(vec)

        if len(feature_vectors) < 100:
            log.warning("Muy pocos datos para entrenar HMM histórico")
            return {}

        # Filtrar features degeneradas: varianza casi nula O cobertura insuficiente.
        # Cobertura: % de barras con valor distinto al más frecuente (el "default").
        # Features muy escasas (como un snapshot OKX único en 43k barras) corrompen
        # el GaussianHMM aunque su varianza no sea cero.
        MIN_COVERAGE = 0.05  # al menos 5% de barras deben tener valores variados
        arr = np.array(feature_vectors, dtype=float)
        keep_cols: list[int] = []
        for col_i in range(arr.shape[1]):
            col = arr[:, col_i]
            if np.var(col) < 1e-10:
                continue  # varianza casi nula → descartar
            # Cobertura: fracción de barras cuyo valor difiere del valor modal
            most_common = float(np.bincount(np.searchsorted(np.unique(col), col)).argmax())
            unique_vals, counts = np.unique(col, return_counts=True)
            modal_val = unique_vals[np.argmax(counts)]
            coverage = float(np.sum(col != modal_val)) / len(col)
            if coverage < MIN_COVERAGE:
                continue  # feature esparsa → descartar
            keep_cols.append(col_i)
        if len(keep_cols) < arr.shape[1]:
            dropped = [feature_names[i] for i in range(len(feature_names)) if i not in keep_cols]
            log.info("HMM: features descartadas (varianza/cobertura): %s", dropped)
            feature_vectors = arr[:, keep_cols].tolist()
            feature_names = [feature_names[i] for i in keep_cols]

        detector = RegimeDetector()
        ok = detector.train(feature_vectors, feature_names=feature_names)
        if not ok:
            log.warning("HMM histórico no pudo entrenarse")
            return {}

        regime_series: dict[float, str] = {}
        for i, vec in enumerate(feature_vectors):
            start = max(0, i - self.window + 1)
            window_vecs = feature_vectors[start : i + 1]
            result = detector.predict(window_vecs)
            regime = result["state_name"] if result else "UNKNOWN"
            bar_idx = i + 1
            if bar_idx < len(idx):
                ts = idx[bar_idx]
                timestamp = ts.timestamp() if hasattr(ts, "timestamp") else float(ts)
                regime_series[timestamp] = regime

        log.info("HMM histórico: %d barras etiquetadas (%d features)", len(regime_series), len(feature_names))
        return regime_series

    def build_with_enrichment(
        self,
        ohlcv_df: pd.DataFrame,
        symbol: str | None = None,
    ) -> dict[float, str]:
        """Fetcha datos complementarios y llama a build() con series enriquecidas.

        Args:
            ohlcv_df: DataFrame OHLCV.
            symbol: Símbolo de mercado (ej: 'BTCUSDT', 'SPY'). Si termina en
                    'USDT' se fetchan HL funding + OKX liq. Fear & Greed siempre.

        Returns:
            {timestamp_float: 'BULL'|'SIDEWAYS'|'BEAR'|'UNKNOWN'}
        """
        n_bars = len(ohlcv_df)
        is_crypto = symbol is not None and symbol.upper().endswith("USDT")

        # Fear & Greed (siempre, todas las clases de activos)
        fg_series: dict[int, float] = {}
        try:
            fg_raw = FearGreedSource().get_history(limit=max(30, n_bars // 24 + 5))
            for entry in fg_raw:
                fg_series[int(entry["timestamp"])] = int(entry["value"]) / 100.0
        except Exception as exc:
            log.warning("FearGreedSource error: %s", exc)

        # HL Funding (solo crypto USDT)
        fund_series: dict[int, float] = {}
        if is_crypto:
            try:
                coin = symbol.replace("USDT", "")
                hl_raw = HyperLiquidSource().get_funding_history(coin, limit=min(n_bars, 500))
                for entry in hl_raw:
                    fund_series[int(entry["time"])] = float(entry["fundingRate"])
            except Exception as exc:
                log.warning("HyperLiquidSource funding error: %s", exc)

        # OKX Liq (solo crypto USDT — snapshot aplicado como intensidad reciente)
        liq_series: dict[int, float] = {}
        if is_crypto:
            try:
                coin = symbol.replace("USDT", "")
                liq = OKXLiqSource().get_liq_summary(coin)
                if liq and liq.get("count", 0) > 0:
                    # Calcular liq_intensity normalizada [-1, 1]
                    net = liq["net_liq"]
                    total = liq["long_liq_usd"] + liq["short_liq_usd"]
                    intensity = float(net / total) if total > 0 else 0.0
                    intensity = max(-1.0, min(1.0, intensity))
                    # Aplicar a la última barra disponible
                    last_ts = ohlcv_df.index[-1]
                    liq_series[int(last_ts.timestamp() * 1000)] = intensity
            except Exception as exc:
                log.warning("OKXLiqSource error: %s", exc)

        return self.build(
            ohlcv_df,
            fear_greed_series=fg_series or None,
            funding_series=fund_series or None,
            liq_intensity_series=liq_series or None,
        )

    def build_cached(self, ohlcv_df: pd.DataFrame, r, cache_key: str,
                     ttl: int = 86400 * 7) -> dict[float, str]:
        """Como build() pero cachea en Redis para no recalcular."""
        raw = r.get(cache_key)
        if raw:
            log.info(f"HMM history cache HIT: {cache_key}")
            return {float(k): v for k, v in json.loads(raw).items()}

        history = self.build(ohlcv_df)
        if history:
            r.set(cache_key, json.dumps({str(k): v for k, v in history.items()}), ex=ttl)
            log.info(f"HMM history guardado en Redis: {cache_key}")
        return history


# ── TradeAdapter ──────────────────────────────────────────────────────────────

class TradeAdapter:
    """
    Convierte trades de backtesting.py al formato BTQUANTR compatible con
    paper:trades:history y el AnalyticsPipeline.
    """

    def __init__(self, r, hmm_history: dict[float, str] | None = None):
        self.r = r
        self.hmm_history = hmm_history or {}

    def _get_regime(self, timestamp: float) -> str:
        if not self.hmm_history:
            return "UNKNOWN"
        closest_ts = min(self.hmm_history.keys(), key=lambda ts: abs(ts - timestamp))
        # Solo usar si está dentro de 4 horas (14400s)
        if abs(closest_ts - timestamp) > 14400:
            return "UNKNOWN"
        return self.hmm_history[closest_ts]

    def convert(self, stats, strategy_name: str, symbol: str) -> list[dict]:
        """
        Convierte Stats de backtesting.py a lista de trades BTQUANTR.

        Args:
            stats: objeto retornado por Backtest.run()
            strategy_name: clave de la estrategia (ej: 'trend-capture-pro')
            symbol: símbolo en formato BTQUANTR (ej: 'BTCUSDT')
        Returns:
            Lista de dicts con el schema completo de paper:trades:history.
        """
        trades_df = stats._trades
        if trades_df is None or len(trades_df) == 0:
            return []

        trades = []
        for _, row in trades_df.iterrows():
            size      = float(row.get("Size", 1))
            entry_p   = float(row.get("EntryPrice", row.get("Entry Price", 0)))
            exit_p    = float(row.get("ExitPrice",  row.get("Exit Price",  0)))
            pnl_abs   = float(row.get("PnL", 0))
            ret_pct   = float(row.get("ReturnPct", row.get("Return [%]", 0)))

            entry_t = row.get("EntryTime", row.get("Entry Time", None))
            exit_t  = row.get("ExitTime",  row.get("Exit Time",  None))
            opened_at = entry_t.timestamp() if hasattr(entry_t, "timestamp") else time.time()
            closed_at = exit_t.timestamp()  if hasattr(exit_t,  "timestamp") else time.time()

            side       = "LONG" if size > 0 else "SHORT"
            size_usd   = abs(size * entry_p)
            commission = size_usd * COMMISSION_PCT * 2
            slippage   = size_usd * SLIPPAGE_BPS * 2
            net_pnl    = pnl_abs - commission - slippage
            pnl_pct    = (net_pnl / size_usd * 100) if size_usd > 0 else ret_pct

            trade = {
                "symbol":           symbol,
                "strategy":         strategy_name,
                "side":             side,
                "entry_price":      round(entry_p, 4),
                "exit_price":       round(exit_p, 4),
                "size_usd":         round(size_usd, 2),
                "size_pct":         round(size_usd / 10_000, 4),
                "leverage":         1.0,
                "gross_pnl_usd":    round(pnl_abs, 4),
                "commission_usd":   round(commission, 4),
                "slippage_usd":     round(slippage, 4),
                "net_pnl_usd":      round(net_pnl, 4),
                "pnl_pct":          round(pnl_pct, 4),
                "regime_at_entry":  self._get_regime(opened_at),
                "regime_at_exit":   self._get_regime(closed_at),
                "opened_at":        opened_at,
                "closed_at":        closed_at,
                "closed_at_str":    _ts_str(closed_at),
                "reason":           "backtest_exit",
                "source":           "backtest",
            }
            trades.append(trade)
        return trades

    def publish_to_redis(self, trades: list[dict], strategy: str, symbol: str,
                         ttl: int = 86400 * 7) -> int:
        """
        Publica trades en Redis Stream backtest:trades:{strategy}:{symbol}.
        Fallback a List si Streams no están disponibles.
        Devuelve número de trades guardados.
        """
        key = f"backtest:trades:{strategy}:{symbol}"
        # Limpiar antes de escribir nuevo batch
        self.r.delete(key, key + ":list")

        saved = 0
        for trade in trades:
            payload = {k: json.dumps(v) for k, v in trade.items()}
            try:
                self.r.xadd(key, payload)
            except Exception:
                self.r.rpush(key + ":list", json.dumps(trade))
            saved += 1

        log.info(f"[{strategy}/{symbol}] {saved} trades → Redis {key}")
        return saved

    @staticmethod
    def read_from_redis(r, strategy: str, symbol: str, limit: int = 5000) -> list[dict]:
        """Lee trades guardados por publish_to_redis."""
        key = f"backtest:trades:{strategy}:{symbol}"
        trades = []
        # Intentar Stream
        try:
            entries = r.xrevrange(key, "+", "-", count=limit)
            for _id, fields in entries:
                trades.append({k: json.loads(v) for k, v in fields.items()})
            return list(reversed(trades))
        except Exception:
            pass
        # Fallback List
        try:
            raw_list = r.lrange(key + ":list", 0, limit - 1)
            return [json.loads(x) for x in raw_list]
        except Exception:
            return []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts_str(ts: float) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def run_strategy_test(
    strategy_key: str,
    symbol_yf: str,
    symbol_btq: str,
    months: int,
    r,
    timeframe: str = "1h",
) -> dict:
    """
    Flujo completo según el doc:
    OHLCV → HMM history → backtest → TradeAdapter → Redis → AnalyticsPipeline → report.

    Returns: dict con 'trades', 'report', 'backtest_result'.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

    from btquantr.data.ohlcv_router import get_ohlcv as _get_ohlcv
    from rbi.backtest.engine import run_backtest
    from btquantr.analytics.pipeline import AnalyticsPipeline

    days = months * 30

    # 1. Datos históricos
    log.info(f"Descargando {symbol_yf} ({days}d {timeframe})…")
    ohlcv = _get_ohlcv(symbol_yf, timeframe, days)

    # 2. HMM histórico (cacheado)
    cache_key = f"backtest:hmm_history:{symbol_btq}:{months}"
    builder = HMMHistoryBuilder()
    hmm_history = builder.build_cached(ohlcv, r, cache_key)

    # 3. Backtest
    log.info(f"Backtest {strategy_key} sobre {symbol_btq}…")
    result, stats, _ = run_backtest(
        strategy_name=strategy_key,
        symbol=symbol_yf,
        timeframe=timeframe,
        days=days,
        data=ohlcv,
    )

    # 4. Adaptar y publicar trades
    adapter = TradeAdapter(r, hmm_history)
    trades = adapter.convert(stats, strategy_key, symbol_btq)
    adapter.publish_to_redis(trades, strategy_key, symbol_btq)

    # 5. Analytics
    analytics = None
    if trades:
        try:
            analytics = AnalyticsPipeline(mc_n_sims=500, mc_seed=42).run(trades)
        except Exception as e:
            log.warning(f"AnalyticsPipeline error: {e}")

    # 6. Guardar reporte
    report = {
        "strategy": strategy_key,
        "symbol": symbol_btq,
        "months": months,
        "timeframe": timeframe,
        "backtest": result,
        "analytics": analytics,
        "total_trades": len(trades),
        "saved_at": time.time(),
    }
    r.set(f"backtest:report:{strategy_key}:{symbol_btq}", json.dumps(report), ex=86400)

    # 7. Regime matrix cache
    _update_regime_matrix(r, strategy_key, symbol_btq, trades)

    return {"trades": trades, "report": report, "backtest_result": result}


def _update_regime_matrix(r, strategy: str, symbol: str, trades: list[dict]) -> None:
    """Actualiza backtest:regime_matrix:{symbol} con Sharpe por régimen."""
    if not trades:
        return
    key = f"backtest:regime_matrix:{symbol}"
    matrix = json.loads(r.get(key) or "{}")
    if strategy not in matrix:
        matrix[strategy] = {}

    by_regime: dict[str, list[float]] = {}
    for t in trades:
        regime = t.get("regime_at_entry", "UNKNOWN")
        by_regime.setdefault(regime, []).append(t["pnl_pct"] / 100.0)

    for regime, rets in by_regime.items():
        arr = np.array(rets)
        std = arr.std()
        sharpe = float(arr.mean() / std * (252 ** 0.5)) if std > 0 else 0.0
        matrix[strategy][regime] = round(sharpe, 3)

    r.set(key, json.dumps(matrix), ex=86400 * 7)
