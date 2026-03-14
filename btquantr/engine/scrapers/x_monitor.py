"""
btquantr/engine/scrapers/x_monitor.py — XMonitor.

Monitorea #algotrading y #quanttrading en X (Twitter) via API v2.

IMPORTANTE: Sin X_BEARER_TOKEN en .env → no conecta a X real.
  Requiere: X_BEARER_TOKEN en .env o pasado explícitamente.
  Obtener en: https://developer.twitter.com/

Redis key: engine:x_monitor (TTL 1h).
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

import requests

log = logging.getLogger("BTQUANTRxmonitor")

_X_API_SEARCH = "https://api.twitter.com/2/tweets/search/recent"
_GITHUB_RE    = re.compile(r"https?://github\.com/[\w\-]+/[\w\-\.]+", re.IGNORECASE)
_CODE_RE      = re.compile(r"```[\s\S]*?```|`[^`]+`", re.IGNORECASE)


class XMonitor:
    """Monitor de X (Twitter) para señales de trading algorítmico.

    Extrae tweets de #algotrading y #quanttrading que contengan:
      - Links a repos GitHub
      - Bloques de código Python

    Sin X_BEARER_TOKEN → fetch() retorna [] sin hacer peticiones HTTP.

    Uso:
        monitor = XMonitor()                    # lee X_BEARER_TOKEN de .env
        tweets  = monitor.fetch_relevant()       # solo tweets con código/GitHub
        all_tw  = monitor.run()                  # con caché Redis
    """

    DEFAULT_HASHTAGS: list[str] = ["algotrading", "quanttrading"]
    CACHE_KEY  = "engine:x_monitor"
    CACHE_TTL  = 3_600   # 1h
    MAX_RESULTS = 20

    def __init__(
        self,
        bearer_token: Optional[str] = None,
        r=None,
        max_results: int = MAX_RESULTS,
    ) -> None:
        # Token: parámetro explícito > env X_BEARER_TOKEN
        self._token = (
            bearer_token
            if bearer_token is not None
            else os.environ.get("X_BEARER_TOKEN")
        )
        self._r = r
        self._max_results = max_results
        self._session = requests.Session()
        if self._token:
            self._session.headers["Authorization"] = f"Bearer {self._token}"

    @property
    def is_configured(self) -> bool:
        """True si hay token configurado."""
        return bool(self._token)

    # ── API pública ───────────────────────────────────────────────────────────

    def fetch(self, hashtags: Optional[list[str]] = None) -> list[dict]:
        """Descarga tweets recientes de los hashtags especificados.

        Sin token → retorna [] sin hacer petición.
        HTTP 4xx → retorna [].

        Returns:
            Lista de dicts con id, text, created_at, github_urls, has_code.
        """
        if not self._token:
            log.info("XMonitor: sin X_BEARER_TOKEN — configura en .env para activar")
            return []

        tags = hashtags or self.DEFAULT_HASHTAGS
        query = " OR ".join(f"#{t}" for t in tags) + " lang:en -is:retweet"

        params = {
            "query":       query,
            "max_results": self._max_results,
            "tweet.fields": "created_at,public_metrics",
        }
        try:
            resp = self._session.get(_X_API_SEARCH, params=params, timeout=10)
        except Exception as exc:
            log.debug("X API request error: %s", exc)
            return []

        if resp.status_code != 200:
            log.debug("X API HTTP %s", resp.status_code)
            return []

        data = resp.json()
        raw_tweets = data.get("data") or []
        return [self._enrich(t) for t in raw_tweets]

    def fetch_relevant(self, hashtags: Optional[list[str]] = None) -> list[dict]:
        """Como fetch() pero filtra solo tweets con código o GitHub URLs."""
        return [t for t in self.fetch(hashtags) if t["has_code"] or t["github_urls"]]

    def run(self, use_cache: bool = True) -> list[dict]:
        """Pipeline completo con caché Redis.

        Returns:
            Lista de tweets (todos, sin filtrar).
        """
        if not self._token:
            return []

        if use_cache:
            cached = self._load_cache()
            if cached is not None:
                return cached

        tweets = self.fetch()
        self._save_cache(tweets)
        return tweets

    # ── Enriquecimiento ───────────────────────────────────────────────────────

    def _enrich(self, raw: dict) -> dict:
        """Añade github_urls y has_code a un tweet raw."""
        text = raw.get("text", "")
        github_urls = list(dict.fromkeys(_GITHUB_RE.findall(text)))
        has_code    = bool(_CODE_RE.search(text))
        return {
            "id":          raw.get("id", ""),
            "text":        text,
            "created_at":  raw.get("created_at", ""),
            "github_urls": github_urls,
            "has_code":    has_code,
        }

    # ── Cache Redis ───────────────────────────────────────────────────────────

    def _load_cache(self) -> Optional[list[dict]]:
        if self._r is None:
            return None
        try:
            raw = self._r.get(self.CACHE_KEY)
            if raw is None:
                return None
            if self._r.ttl(self.CACHE_KEY) == -2:
                return None
            data = json.loads(raw)
            return data if isinstance(data, list) else None
        except Exception as exc:
            log.debug("X monitor cache load error: %s", exc)
            return None

    def _save_cache(self, tweets: list[dict]) -> None:
        if self._r is None:
            return
        try:
            self._r.set(self.CACHE_KEY, json.dumps(tweets), ex=self.CACHE_TTL)
        except Exception as exc:
            log.debug("X monitor cache save error: %s", exc)
