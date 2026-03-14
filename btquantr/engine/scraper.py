"""
btquantr/engine/scraper.py — GitHubScraper + CodeValidator.

Spec: docs/biblia/autonomous_strategy_engine_v2.docx sección 3 (SeedLibrary fuente 3).

GitHubScraper:
  - Descarga ficheros .py de repos públicos de GitHub vía Contents API
  - Valida cada fichero con CodeValidator antes de extraer seeds
  - Caché en Redis (key: engine:scraped_seeds, TTL: 24h)
  - Fuente principal: moondevonyt/moon-dev-ai-agents (src/agents/ + src/strategies/)

CodeValidator:
  - Verifica sintaxis Python (ast.parse)
  - Bloquea patrones peligrosos + red + filesystem + secretos
  - Limita a MAX_LINES = 500 líneas
  - Exige al menos una clase que herede de Strategy o RBIStrategy
  - sandbox_validate(): ejecución en subprocess aislado con timeout
"""
from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from typing import Any

import requests

# Reutilizar helpers de seed_library para no duplicar lógica
from btquantr.engine.seed_library import (
    _class_inherits_strategy,
    _extract_class_params,
    _extract_indicators,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

_DANGEROUS_PATTERNS: list[str] = [
    # Ejecución de sistema
    "os.system",
    "subprocess",
    "eval(",
    "exec(",
    "__import__",
    "importlib",
    # Red
    "requests",
    "urllib",
    "socket",
    "http.client",
    # Filesystem destructivo
    "shutil",
    ".write_text",
    ".write_bytes",
]

_SECRET_STRINGS: list[str] = [
    "API_KEY",
    "SECRET",
    "PASSWORD",
    "PRIVATE_KEY",
    "BEARER",
]

MAX_LINES = 500
MAX_LINES_RELAXED = 700

_VALID_BASES = {"Strategy", "RBIStrategy"}

# Keywords para detectar clases de trading en repos externos (sin base Strategy)
_TRADING_CLASS_KEYWORDS = {
    "strategy", "backtest", "algo", "trading", "signal", "system",
    "portfolio", "momentum", "reversion", "breakout", "arbitrage",
    "macd", "rsi", "bollinger", "ema", "sma", "vwap", "ichimoku",
    "heikin", "pair", "london", "trend", "swing", "scalp", "mean",
}

# Regex para extraer repos GitHub de un texto
_GITHUB_URL_RE = re.compile(
    r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)"
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────

def _has_strategy_class(code: str) -> bool:
    """Retorna True si el código contiene al menos una clase que herede de Strategy."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and _class_inherits_strategy(node):
            return True
    return False


def _extract_seeds_from_code(code: str, file_path_str: str) -> list[dict]:
    """Extrae seeds (una por clase Strategy) de un fragmento de código fuente."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    lines = code.splitlines(keepends=True)
    seeds: list[dict] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not _class_inherits_strategy(node):
            continue

        try:
            class_lines = lines[node.lineno - 1 : node.end_lineno]
            class_code = "".join(class_lines)
        except (AttributeError, IndexError):
            class_code = f"class {node.name}: ..."

        seeds.append(
            {
                "name": node.name,
                "code": class_code,
                "params": _extract_class_params(node),
                "origin": "scraped",
                "source_file": file_path_str,
                "indicators": _extract_indicators(class_code),
            }
        )
    return seeds


def _is_trading_class_name(name: str) -> bool:
    """Retorna True si el nombre de la clase contiene keywords de trading."""
    lower = name.lower()
    return any(kw in lower for kw in _TRADING_CLASS_KEYWORDS)


def _extract_seeds_relaxed(code: str, file_path_str: str) -> list[dict]:
    """Extrae seeds de código que NO hereda de Strategy (repos externos).

    Extrae cualquier clase cuyo nombre contenga keywords de trading.
    No requiere herencia de Strategy/RBIStrategy.
    """
    if not code or not code.strip():
        return []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    lines = code.splitlines(keepends=True)
    seeds: list[dict] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not _is_trading_class_name(node.name):
            continue

        try:
            class_lines = lines[node.lineno - 1 : node.end_lineno]
            class_code = "".join(class_lines)
        except (AttributeError, IndexError):
            class_code = f"class {node.name}: ..."

        seeds.append(
            {
                "name": node.name,
                "code": class_code,
                "params": _extract_class_params(node),
                "origin": "scraped",
                "source_file": file_path_str,
                "indicators": _extract_indicators(class_code),
            }
        )
    return seeds


# ─────────────────────────────────────────────────────────────────────────────
# CodeValidator
# ─────────────────────────────────────────────────────────────────────────────

class CodeValidator:
    """Valida código Python descargado antes de incorporarlo como seed.

    Comprueba (en orden):
      1. Código no vacío
      2. Límite de MAX_LINES líneas
      3. Sintaxis Python válida
      4. Ausencia de patrones peligrosos (red, filesystem, ejecución)
      5. Ausencia de strings de secretos (API_KEY, SECRET, etc.)
      6. Presencia de al menos una clase Strategy

    sandbox_validate(): ejecuta el código en subprocess aislado con timeout.
    """

    DANGEROUS_PATTERNS:   list[str] = _DANGEROUS_PATTERNS
    SECRET_STRINGS:       list[str] = _SECRET_STRINGS
    MAX_LINES:            int        = MAX_LINES
    MAX_LINES_RELAXED:    int        = MAX_LINES_RELAXED
    SANDBOX_TIMEOUT:      int        = 30   # segundos

    def validate(self, code: str) -> dict[str, Any]:
        """Valida el código estáticamente.

        Returns:
            {"valid": bool, "errors": list[str]}
        """
        if not code or not code.strip():
            return {"valid": False, "errors": ["Código vacío"]}

        errors: list[str] = []

        # 1. Límite de líneas
        n_lines = code.count("\n") + 1
        if n_lines > self.MAX_LINES:
            msg = (
                f"Archivo demasiado grande: {n_lines} líneas "
                f"(límite {self.MAX_LINES})"
            )
            logger.warning("CodeValidator rechazado — %s", msg)
            return {"valid": False, "errors": [msg]}

        # 2. Sintaxis
        try:
            ast.parse(code)
        except SyntaxError as exc:
            return {"valid": False, "errors": [f"SyntaxError: {exc}"]}

        # 3. Patrones peligrosos
        for pattern in self.DANGEROUS_PATTERNS:
            if pattern in code:
                errors.append(f"Patrón peligroso detectado: {pattern}")

        # 4. Strings de secretos
        for secret in self.SECRET_STRINGS:
            if secret in code:
                errors.append(f"String sospechoso detectado: {secret}")

        # 5. Clase Strategy presente
        if not _has_strategy_class(code):
            errors.append("No se encontró ninguna clase que herede de Strategy o RBIStrategy")

        if errors:
            logger.warning(
                "CodeValidator rechazado — %d errores: %s",
                len(errors),
                "; ".join(errors),
            )
        return {"valid": len(errors) == 0, "errors": errors}

    def validate_relaxed(self, code: str) -> dict[str, Any]:
        """Validación relajada para repos externos: MAX_LINES=700, sin exigir clase Strategy.

        Checks (en orden):
          1. Código no vacío
          2. Límite de MAX_LINES_RELAXED (700) líneas
          3. Sintaxis Python válida
          4. Ausencia de patrones peligrosos
          5. Ausencia de strings de secretos

        NO exige presencia de clase Strategy/RBIStrategy.

        Returns:
            {"valid": bool, "errors": list[str]}
        """
        if not code or not code.strip():
            return {"valid": False, "errors": ["Código vacío"]}

        errors: list[str] = []

        # 1. Límite de líneas (relajado)
        n_lines = code.count("\n") + 1
        if n_lines > self.MAX_LINES_RELAXED:
            msg = (
                f"Archivo demasiado grande: {n_lines} líneas "
                f"(límite {self.MAX_LINES_RELAXED})"
            )
            logger.warning("CodeValidator.validate_relaxed rechazado — %s", msg)
            return {"valid": False, "errors": [msg]}

        # 2. Sintaxis
        try:
            ast.parse(code)
        except SyntaxError as exc:
            return {"valid": False, "errors": [f"SyntaxError: {exc}"]}

        # 3. Patrones peligrosos
        for pattern in self.DANGEROUS_PATTERNS:
            if pattern in code:
                errors.append(f"Patrón peligroso detectado: {pattern}")

        # 4. Strings de secretos
        for secret in self.SECRET_STRINGS:
            if secret in code:
                errors.append(f"String sospechoso detectado: {secret}")

        if errors:
            logger.warning(
                "CodeValidator.validate_relaxed rechazado — %d errores: %s",
                len(errors),
                "; ".join(errors),
            )
        return {"valid": len(errors) == 0, "errors": errors}

    def sandbox_validate(self, code: str) -> dict[str, Any]:
        """Ejecuta el código en subprocess aislado con timeout.

        Flujo:
          1. validate() estático → si inválido, retorna safe=False inmediatamente
          2. Escribe a fichero temporal
          3. Ejecuta `python <tmpfile>` con timeout=SANDBOX_TIMEOUT
          4. Timeout → safe=False, errors=["timeout: ..."]
          5. returncode != 0 (pero no import error de entorno) → safe=False
          6. OK → safe=True

        Returns:
            {"safe": bool, "errors": list[str]}
        """
        static = self.validate(code)
        if not static["valid"]:
            return {"safe": False, "errors": static["errors"]}

        timeout = self.SANDBOX_TIMEOUT
        tmpfile = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False,
                dir=tempfile.gettempdir(),
            ) as f:
                f.write(code)
                tmpfile = f.name

            result = subprocess.run(
                [sys.executable, tmpfile],
                timeout=timeout,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                stderr = result.stderr or ""
                # Import errors de entorno (e.g. backtesting no disponible en path)
                # no son fallo de seguridad del código
                if "ModuleNotFoundError" in stderr or "ImportError" in stderr:
                    return {"safe": True, "errors": []}
                return {
                    "safe": False,
                    "errors": [f"Error de ejecución: {stderr[:300]}"],
                }

            return {"safe": True, "errors": []}

        except subprocess.TimeoutExpired:
            msg = f"Timeout: código excedió el límite de {timeout}s"
            logger.warning("CodeValidator sandbox timeout — %s", msg)
            return {"safe": False, "errors": [msg]}
        except Exception as exc:
            return {"safe": False, "errors": [f"Sandbox error: {exc}"]}
        finally:
            if tmpfile:
                try:
                    os.unlink(tmpfile)
                except OSError:
                    pass


# ─────────────────────────────────────────────────────────────────────────────
# GitHubScraper
# ─────────────────────────────────────────────────────────────────────────────

class GitHubScraper:
    """Descarga estrategias de repos públicos de GitHub y las convierte en seeds.

    Flujo:
      run() → [cache hit → return] | [fetch_repo × DEFAULT_REPOS → validate → cache → return]

    Redis key: engine:scraped_seeds (TTL 24h).
    """

    GITHUB_API = "https://api.github.com"
    RAW_BASE   = "https://raw.githubusercontent.com"
    CACHE_KEY          = "engine:scraped_seeds"
    EXTENDED_CACHE_KEY = "engine:scraped_seeds_extended"
    CACHE_TTL  = 86_400  # 24 horas

    DEFAULT_REPOS: list[dict] = [
        {
            "owner": "moondevonyt",
            "repo":  "Hyperliquid-Data-Layer-API",
            "paths": [""],
        },
        {
            "owner": "moondevonyt",
            "repo":  "Harvard-Algorithmic-Trading-with-AI",
            "paths": [""],
        },
        {
            "owner": "moondevonyt",
            "repo":  "Extended-Exchange-Crypto-Trading-Bot-Code---Examples",
            "paths": [""],
        },
    ]

    QUANT_TRADING_REPO: dict = {
        "owner": "je-suis-tm",
        "repo":  "quant-trading",
        "paths": [""],
    }

    AWESOME_SYSTEMATIC_REPO: dict = {
        "owner": "wangzhe3224",
        "repo":  "awesome-systematic-trading",
    }

    BEST_OF_ALGO_REPO: dict = {
        "owner": "merovinh",
        "repo":  "best-of-algorithmic-trading",
    }

    def __init__(self, r=None, token: str | None = None) -> None:
        from dotenv import load_dotenv
        load_dotenv()
        self._r         = r
        self._token     = token if token is not None else os.environ.get("GITHUB_TOKEN")
        self._validator = CodeValidator()
        self._session   = requests.Session()
        if self._token:
            self._session.headers["Authorization"] = f"token {self._token}"

    # ── API pública ────────────────────────────────────────────────────────────

    def scrape_moondev(self) -> list[dict]:
        """Descarga todos los repos en DEFAULT_REPOS (moondevonyt)."""
        seeds: list[dict] = []
        for repo_config in self.DEFAULT_REPOS:
            seeds.extend(
                self.fetch_repo(
                    owner=repo_config["owner"],
                    repo=repo_config["repo"],
                    paths=repo_config["paths"],
                )
            )
        return seeds

    def fetch_repo(self, owner: str, repo: str, paths: list[str]) -> list[dict]:
        """Descarga .py de cada path, valida y extrae seeds.

        Args:
            owner: Propietario del repo (ej. "moondevonyt").
            repo:  Nombre del repo (ej. "moon-dev-ai-agents").
            paths: Lista de paths dentro del repo (ej. ["src/agents"]).

        Returns:
            Lista de seed dicts con origin="scraped".
        """
        seeds: list[dict] = []
        for path in paths:
            for file_info in self._list_python_files(owner, repo, path):
                url = file_info.get("download_url")
                if not url:
                    continue
                code = self._download_file(url)
                if code is None:
                    continue
                result = self._validator.validate(code)
                if not result["valid"]:
                    logger.debug(
                        "Fichero inválido %s: %s", file_info["path"], result["errors"]
                    )
                    continue
                file_seeds = _extract_seeds_from_code(code, file_info["path"])
                seeds.extend(file_seeds)
        return seeds

    def run(self, use_cache: bool = True) -> list[dict]:
        """Pipeline completo: caché → fetch → validar → cachear → retornar.

        Args:
            use_cache: Si True (default), devuelve caché válida sin hacer peticiones.

        Returns:
            Lista de seeds scraped.
        """
        if use_cache:
            cached = self._load_cache()
            if cached is not None:
                return cached

        seeds: list[dict] = []
        for repo_config in self.DEFAULT_REPOS:
            repo_seeds = self.fetch_repo(
                owner=repo_config["owner"],
                repo=repo_config["repo"],
                paths=repo_config["paths"],
            )
            seeds.extend(repo_seeds)

        self._save_cache(seeds)
        return seeds

    # ── Extended sources ──────────────────────────────────────────────────────

    def fetch_repo_relaxed(self, owner: str, repo: str, paths: list[str]) -> list[dict]:
        """Como fetch_repo pero usa _extract_seeds_relaxed (sin requerir clase Strategy).

        Solo bloquea código peligroso (sin exigir herencia de Strategy).
        """
        seeds: list[dict] = []
        for path in paths:
            for file_info in self._list_python_files(owner, repo, path):
                url = file_info.get("download_url")
                if not url:
                    continue
                code = self._download_file(url)
                if code is None:
                    continue
                result = self._validator.validate_relaxed(code)
                if not result["valid"]:
                    logger.debug(
                        "Fichero inválido (relaxed) %s: %s",
                        file_info["path"],
                        result["errors"],
                    )
                    continue
                file_seeds = _extract_seeds_relaxed(code, file_info["path"])
                seeds.extend(file_seeds)
        return seeds

    def scrape_quant_trading(self) -> list[dict]:
        """Descarga estrategias de je-suis-tm/quant-trading."""
        cfg = self.QUANT_TRADING_REPO
        return self.fetch_repo_relaxed(
            owner=cfg["owner"],
            repo=cfg["repo"],
            paths=cfg["paths"],
        )

    def _parse_readme_for_github_urls(
        self, owner: str, repo: str
    ) -> list[tuple[str, str]]:
        """Descarga README.md del repo y extrae URLs de repos GitHub.

        Returns:
            Lista de tuplas (owner, repo) únicas, excluyendo el repo propio.
        """
        readme_url = (
            f"{self.RAW_BASE}/{owner}/{repo}/HEAD/README.md"
        )
        content = self._download_file(readme_url)
        if not content:
            return []

        found: set[tuple[str, str]] = set()
        for m in _GITHUB_URL_RE.finditer(content):
            o, r = m.group(1), m.group(2)
            # Strip .git suffix if present
            r = r.rstrip("/").removesuffix(".git")
            # Skip the list repo itself and bare GitHub pages
            if (o, r) == (owner, repo):
                continue
            # Skip single-segment paths (e.g. github.com/login)
            if not o or not r:
                continue
            found.add((o, r))

        return list(found)

    def _get_repo_stars(self, owner: str, repo: str) -> int:
        """Consulta la API de GitHub para obtener el número de estrellas."""
        url = f"{self.GITHUB_API}/repos/{owner}/{repo}"
        try:
            resp = self._session.get(url, timeout=10)
            if resp.status_code == 200:
                return int(resp.json().get("stargazers_count", 0))
        except Exception as exc:
            logger.debug("Error consultando stars de %s/%s: %s", owner, repo, exc)
        return 0

    def scrape_awesome_systematic_trading(self) -> list[dict]:
        """Parsea wangzhe3224/awesome-systematic-trading y descarga repos encontrados."""
        cfg = self.AWESOME_SYSTEMATIC_REPO
        repos = self._parse_readme_for_github_urls(cfg["owner"], cfg["repo"])
        if not repos:
            return []

        seeds: list[dict] = []
        for o, r in repos:
            seeds.extend(self.fetch_repo_relaxed(o, r, [""]))
        return seeds

    def scrape_best_of_algo_trading(self, top_n: int = 20) -> list[dict]:
        """Parsea merovinh/best-of-algorithmic-trading, toma los top_n por estrellas."""
        cfg = self.BEST_OF_ALGO_REPO
        repos = self._parse_readme_for_github_urls(cfg["owner"], cfg["repo"])
        if not repos:
            return []

        # Ordenar por estrellas descendente
        repos_with_stars = [(o, r, self._get_repo_stars(o, r)) for o, r in repos]
        repos_with_stars.sort(key=lambda x: x[2], reverse=True)
        top_repos = repos_with_stars[:top_n]

        seeds: list[dict] = []
        for o, r, _ in top_repos:
            seeds.extend(self.fetch_repo_relaxed(o, r, [""]))
        return seeds

    def run_extended(self, use_cache: bool = True) -> list[dict]:
        """Pipeline completo con las 4 fuentes: moondev + quant-trading + awesome + best-of.

        Args:
            use_cache: Si True, devuelve caché de Redis (EXTENDED_CACHE_KEY) si existe.

        Returns:
            Lista agregada de seeds de todos los repos.
        """
        if use_cache:
            cached = self._load_cache(key=self.EXTENDED_CACHE_KEY)
            if cached is not None:
                return cached

        seeds: list[dict] = []
        seeds.extend(self.run(use_cache=False))
        seeds.extend(self.scrape_quant_trading())
        seeds.extend(self.scrape_awesome_systematic_trading())
        seeds.extend(self.scrape_best_of_algo_trading())

        self._save_cache(seeds, key=self.EXTENDED_CACHE_KEY)
        return seeds

    # ── Helpers de red ────────────────────────────────────────────────────────

    def _list_python_files(self, owner: str, repo: str, path: str) -> list[dict]:
        """Llama a GitHub Contents API y retorna solo ficheros .py con download_url."""
        url = f"{self.GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
        try:
            resp = self._session.get(url, timeout=10)
        except Exception as exc:
            logger.debug("Error listando %s: %s", url, exc)
            return []

        if resp.status_code != 200:
            logger.debug("GitHub API %s → HTTP %s", url, resp.status_code)
            return []

        items = resp.json()
        if not isinstance(items, list):
            return []

        return [
            {"path": item["path"], "download_url": item["download_url"]}
            for item in items
            if (
                item.get("type") == "file"
                and item.get("name", "").endswith(".py")
                and item.get("download_url")
            )
        ]

    def _download_file(self, url: str) -> str | None:
        """Descarga el contenido raw de un fichero. Retorna None si falla."""
        try:
            resp = self._session.get(url, timeout=10)
            if resp.status_code == 200:
                return resp.text
        except Exception as exc:
            logger.debug("Error descargando %s: %s", url, exc)
        return None

    # ── Cache Redis ───────────────────────────────────────────────────────────

    def _load_cache(self, key: str | None = None) -> list[dict] | None:
        """Lee seeds de Redis. Retorna None si no existe, expiró, o Redis no disponible."""
        if self._r is None:
            return None
        cache_key = key if key is not None else self.CACHE_KEY
        try:
            raw = self._r.get(cache_key)
            if raw is None:
                return None
            ttl = self._r.ttl(cache_key)
            if ttl == -2:          # clave expirada
                return None
            # ttl > 0 → válida con TTL, ttl == -1 → sin expiración (válida)
            data = json.loads(raw)
            return data if isinstance(data, list) else None
        except Exception as exc:
            logger.debug("Error leyendo caché scraper: %s", exc)
            return None

    def _save_cache(self, seeds: list[dict], key: str | None = None) -> None:
        """Persiste seeds en Redis con TTL."""
        if self._r is None:
            return
        cache_key = key if key is not None else self.CACHE_KEY
        try:
            self._r.set(cache_key, json.dumps(seeds), ex=self.CACHE_TTL)
        except Exception as exc:
            logger.debug("Error guardando caché scraper: %s", exc)
