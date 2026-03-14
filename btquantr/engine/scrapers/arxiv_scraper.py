"""
btquantr/engine/scrapers/arxiv_scraper.py — ArXivScraper.

Busca papers de trading en arXiv, extrae abstracts y GitHub URLs.
Si encuentra código Python en un repo GitHub, lo descarga como seed
reutilizando GitHubScraper.

API pública de arXiv: https://export.arxiv.org/api/query (Atom XML, sin autenticación)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional
from xml.etree import ElementTree as ET

import requests

log = logging.getLogger("BTQUANTRarxiv")

_ARXIV_API = "https://export.arxiv.org/api/query"
_ATOM_NS   = "http://www.w3.org/2005/Atom"
_GITHUB_RE = re.compile(r"https?://github\.com/[\w\-]+/[\w\-\.]+", re.IGNORECASE)


class ArXivScraper:
    """Scraper de papers de trading en arXiv.

    Flujo:
      run() → search(keyword) × DEFAULT_KEYWORDS → deduplica → _scrape_github_repo()
              → lista de papers con campo "seeds" opcional

    Redis key: engine:arxiv_papers (TTL 24h).
    """

    DEFAULT_KEYWORDS: list[str] = [
        "trading strategy",
        "algorithmic trading",
        "mean reversion",
        "momentum trading",
    ]

    CACHE_KEY = "engine:arxiv_papers"
    CACHE_TTL = 86_400  # 24h
    MAX_RESULTS = 10    # por keyword

    def __init__(self, r=None, max_results: int = MAX_RESULTS) -> None:
        self._r = r
        self._max_results = max_results
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "btquantr/1.0 (research scraper)"

    # ── API pública ───────────────────────────────────────────────────────────

    def search(self, keyword: str) -> list[dict]:
        """Busca papers en arXiv por keyword.

        Returns:
            Lista de dicts con arxiv_id, title, abstract, authors,
            arxiv_url, github_urls.
        """
        params = {
            "search_query": f'ti:"{keyword}" OR abs:"{keyword}"',
            "max_results":  self._max_results,
            "sortBy":       "relevance",
        }
        try:
            resp = self._session.get(_ARXIV_API, params=params, timeout=15)
        except Exception as exc:
            log.debug("arXiv request error: %s", exc)
            return []

        if resp.status_code != 200:
            log.debug("arXiv HTTP %s", resp.status_code)
            return []

        return self._parse_atom(resp.content)

    def run(self, use_cache: bool = True) -> list[dict]:
        """Pipeline completo: caché → search × keywords → dedup → GitHub scrape.

        Returns:
            Lista deduplicada de papers (por arxiv_id).
        """
        if use_cache:
            cached = self._load_cache()
            if cached is not None:
                return cached

        seen: dict[str, dict] = {}
        for keyword in self.DEFAULT_KEYWORDS:
            for paper in self.search(keyword):
                if paper["arxiv_id"] not in seen:
                    # Intentar scrapear seeds del repo GitHub si existe
                    for gh_url in paper.get("github_urls", []):
                        seeds = self._scrape_github_repo(gh_url)
                        paper.setdefault("seeds", []).extend(seeds)
                    seen[paper["arxiv_id"]] = paper

        papers = list(seen.values())
        self._save_cache(papers)
        return papers

    def _scrape_github_repo(self, github_url: str) -> list[dict]:
        """Descarga código Python de un repo GitHub y extrae seeds.

        Solo actúa sobre URLs de github.com. Retorna lista de seeds.
        """
        if "github.com" not in github_url.lower():
            return []

        # Extraer owner/repo de la URL
        match = re.search(r"github\.com/([\w\-]+)/([\w\-\.]+)", github_url)
        if not match:
            return []

        owner = match.group(1)
        repo  = match.group(2).rstrip("/")

        try:
            from btquantr.engine.scraper import GitHubScraper
            scraper = GitHubScraper()
            return scraper.fetch_repo(owner=owner, repo=repo, paths=[""])
        except Exception as exc:
            log.debug("GitHub scrape error %s/%s: %s", owner, repo, exc)
            return []

    # ── Parsing Atom XML ──────────────────────────────────────────────────────

    def _parse_atom(self, content: bytes) -> list[dict]:
        """Parsea el XML Atom de arXiv y retorna lista de papers."""
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            log.debug("arXiv XML parse error: %s", exc)
            return []

        papers = []
        for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
            arxiv_id = self._text(entry, f"{{{_ATOM_NS}}}id") or ""
            # Normalizar ID: extraer solo el número
            id_match = re.search(r"(\d{4}\.\d+)", arxiv_id)
            arxiv_id_norm = id_match.group(1) if id_match else arxiv_id

            title    = (self._text(entry, f"{{{_ATOM_NS}}}title") or "").strip()
            abstract = (self._text(entry, f"{{{_ATOM_NS}}}summary") or "").strip()

            authors = [
                a.findtext(f"{{{_ATOM_NS}}}name") or ""
                for a in entry.findall(f"{{{_ATOM_NS}}}author")
            ]

            # URL del paper en arxiv.org
            arxiv_url = ""
            for link in entry.findall(f"{{{_ATOM_NS}}}link"):
                if link.get("rel") == "alternate":
                    arxiv_url = link.get("href", "")
                    break
            if not arxiv_url and arxiv_id:
                arxiv_url = f"https://arxiv.org/abs/{arxiv_id_norm}"

            # Extraer GitHub URLs del abstract
            github_urls = _GITHUB_RE.findall(abstract)

            papers.append({
                "arxiv_id":   arxiv_id_norm,
                "title":      title,
                "abstract":   abstract,
                "authors":    [a for a in authors if a],
                "arxiv_url":  arxiv_url,
                "github_urls": list(dict.fromkeys(github_urls)),  # dedup orden
            })

        return papers

    @staticmethod
    def _text(element, tag: str) -> Optional[str]:
        child = element.find(tag)
        return child.text if child is not None else None

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
            log.debug("arXiv cache load error: %s", exc)
            return None

    def _save_cache(self, papers: list[dict]) -> None:
        if self._r is None:
            return
        try:
            self._r.set(self.CACHE_KEY, json.dumps(papers), ex=self.CACHE_TTL)
        except Exception as exc:
            log.debug("arXiv cache save error: %s", exc)
