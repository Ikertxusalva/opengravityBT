"""CacheManager — caché en disco para data del proyecto BTQUANTR.

Parquet para OHLCV (append inteligente), JSON para datos suplementarios (TTL).
Cache dir por defecto: data/cache/ (relativo a la raíz del proyecto).
"""
from __future__ import annotations

import json
import logging
import pathlib
import time
from typing import Any

import pandas as pd

from btquantr.data.versioning import compute_sha256

log = logging.getLogger("CacheManager")

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent.parent
_DEFAULT_CACHE_DIR = _PROJECT_ROOT / "data" / "cache"


class CacheManager:
    """Gestiona caché en disco para OHLCV (parquet) y datos suplementarios (JSON)."""

    def __init__(self, cache_dir: pathlib.Path | str | None = None):
        self.cache_dir = pathlib.Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ── OHLCV (parquet) ────────────────────────────────────────────────────────

    def _ohlcv_path(self, symbol: str, timeframe: str) -> pathlib.Path:
        return self.cache_dir / f"{symbol}_{timeframe}.parquet"

    def get_ohlcv_cached(self, symbol: str, timeframe: str) -> pd.DataFrame | None:
        """Lee DataFrame del caché parquet. Retorna None si no existe."""
        path = self._ohlcv_path(symbol, timeframe)
        if not path.exists():
            return None
        try:
            return pd.read_parquet(path)
        except Exception as exc:
            log.warning("CacheManager: error leyendo parquet %s: %s", path.name, exc)
            return None

    def set_ohlcv(self, symbol: str, timeframe: str, df: pd.DataFrame) -> None:
        """Guarda DataFrame en parquet. Sobrescribe si ya existe."""
        if df is None or df.empty:
            return
        path = self._ohlcv_path(symbol, timeframe)
        try:
            df.to_parquet(path)
            log.debug("CacheManager: guardado %s (%d barras)", path.name, len(df))
        except Exception as exc:
            log.warning("CacheManager: error guardando parquet %s: %s", path.name, exc)

    def is_ohlcv_fresh(self, symbol: str, timeframe: str, stale_hours: float = 24.0) -> bool:
        """True si la última barra del caché es más reciente que stale_hours."""
        df = self.get_ohlcv_cached(symbol, timeframe)
        if df is None or df.empty:
            return False
        try:
            last_bar = df.index[-1]
            if last_bar.tzinfo is None:
                last_bar = last_bar.tz_localize("UTC")
            cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=stale_hours)
            return last_bar >= cutoff
        except Exception:
            return False

    def get_last_bar_time(self, symbol: str, timeframe: str) -> pd.Timestamp | None:
        """Retorna el timestamp de la última barra cacheada, o None."""
        df = self.get_ohlcv_cached(symbol, timeframe)
        if df is None or df.empty:
            return None
        last = df.index[-1]
        if last.tzinfo is None:
            last = last.tz_localize("UTC")
        return last

    # ── Versioning SHA-256 ─────────────────────────────────────────────────────

    def _sha_path(self, symbol: str, timeframe: str) -> pathlib.Path:
        return self.cache_dir / f"{symbol}_{timeframe}.sha256"

    def get_cached_sha(self, symbol: str, timeframe: str) -> str | None:
        """Lee el SHA-256 guardado del sidecar. Retorna None si no existe."""
        path = self._sha_path(symbol, timeframe)
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8").strip()
        except Exception:
            return None

    def set_ohlcv_with_hash(self, symbol: str, timeframe: str, df: pd.DataFrame) -> None:
        """Guarda DataFrame en parquet y crea sidecar .sha256."""
        self.set_ohlcv(symbol, timeframe, df)
        try:
            sha = compute_sha256(df)
            self._sha_path(symbol, timeframe).write_text(sha, encoding="utf-8")
        except Exception as exc:
            log.warning("CacheManager: error guardando SHA %s_%s: %s", symbol, timeframe, exc)

    def is_data_changed(self, symbol: str, timeframe: str, new_df: pd.DataFrame) -> bool:
        """True si new_df tiene SHA distinto al cacheado (o no hay sidecar)."""
        stored = self.get_cached_sha(symbol, timeframe)
        if stored is None:
            return True
        return stored != compute_sha256(new_df)

    def invalidate_ohlcv(self, symbol: str, timeframe: str) -> None:
        """Elimina parquet + sidecar SHA (invalida el caché completo)."""
        for path in (self._ohlcv_path(symbol, timeframe), self._sha_path(symbol, timeframe)):
            try:
                path.unlink(missing_ok=True)
            except Exception as exc:
                log.warning("CacheManager: error eliminando %s: %s", path.name, exc)

    # ── JSON suplementario ─────────────────────────────────────────────────────

    def _json_path(self, key: str) -> pathlib.Path:
        return self.cache_dir / f"{key}.json"

    def get_json(self, key: str, ttl_hours: float = 24.0) -> Any | None:
        """Lee dato JSON del caché. Retorna None si no existe o expiró."""
        path = self._json_path(key)
        if not path.exists():
            return None
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
            if content.get("expires", 0) < time.time():
                return None
            log.info("Cache hit: %s", key)
            return content.get("data")
        except Exception as exc:
            log.warning("CacheManager: error leyendo JSON %s: %s", key, exc)
            return None

    def set_json(self, key: str, data: Any, ttl_hours: float = 24.0) -> None:
        """Guarda dato JSON con TTL."""
        path = self._json_path(key)
        try:
            content = {"expires": time.time() + ttl_hours * 3600, "data": data}
            path.write_text(json.dumps(content, default=str), encoding="utf-8")
            log.debug("CacheManager: guardado JSON %s (TTL %.0fh)", key, ttl_hours)
        except Exception as exc:
            log.warning("CacheManager: error guardando JSON %s: %s", key, exc)
