"""SeedLibrary — catálogo de estrategias semilla para el motor generativo.

Fuentes de seeds:
  1. MoonDev / RBI strategies  → src/rbi/strategies/
  2. Proven templates          → btquantr/engine/templates/
  3. Scraped cache             → Redis key engine:scraped_seeds

Formato de cada seed:
  {
    "name":        str   — nombre único de la clase
    "code":        str   — código fuente Python completo de la clase
    "params":      dict  — {attr: valor} para atributos int/float de clase
    "origin":      str   — "moondev" | "template" | "scraped"
    "source_file": str   — path relativo al archivo fuente
    "indicators":  list  — indicadores detectados (heurística por keywords)
  }
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import logging
import pathlib
import sys
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes de ruta (relativas a la raíz del proyecto)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = pathlib.Path(__file__).parent.parent.parent  # RBI-Backtester/
_MOONDEV_DIR = _PROJECT_ROOT / "src" / "rbi" / "strategies"
_MOONDEV_ARCHIVE_DIR = _PROJECT_ROOT / "research" / "moondev_archive"
_TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"

# Archivos a omitir en src/rbi/strategies/
_MOONDEV_SKIP = {"__init__.py", "base.py", "registry.py"}

# Bases válidas para considerar una clase como estrategia
_VALID_BASES = {"Strategy", "RBIStrategy"}

# Keywords para detección heurística de indicadores
_INDICATOR_KEYWORDS = [
    "RSI", "MACD", "EMA", "SMA", "VWAP", "BB", "bollinger",
    "ATR", "ADX", "CCI", "OBV", "MFI", "stoch", "donchian",
    "keltner", "ichimoku", "supertrend", "DEMA", "momentum",
    "funding", "volume",
]

# Importación diferida de redis (no en nivel de módulo)
try:
    import redis
except ImportError:
    redis = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Helpers de AST
# ---------------------------------------------------------------------------

def _extract_class_params(node: ast.ClassDef) -> dict[str, Any]:
    """Extrae atributos de clase que sean literales int o float."""
    params: dict[str, Any] = {}
    for item in node.body:
        if isinstance(item, ast.Assign):
            # Asignaciones simples: x = valor
            for target in item.targets:
                if isinstance(target, ast.Name):
                    val = item.value
                    if isinstance(val, ast.Constant) and isinstance(val.value, (int, float)):
                        params[target.id] = val.value
                    elif isinstance(val, ast.UnaryOp) and isinstance(val.op, ast.USub):
                        if isinstance(val.operand, ast.Constant) and isinstance(val.operand.value, (int, float)):
                            params[target.id] = -val.operand.value
        elif isinstance(item, ast.AnnAssign):
            # Anotaciones: x: int = valor
            if isinstance(item.target, ast.Name) and item.value is not None:
                val = item.value
                if isinstance(val, ast.Constant) and isinstance(val.value, (int, float)):
                    params[item.target.id] = val.value
    return params


def _extract_indicators(code: str) -> list[str]:
    """Detección heurística de indicadores por keywords en el código fuente."""
    found: list[str] = []
    code_upper = code.upper()
    for kw in _INDICATOR_KEYWORDS:
        if kw.upper() in code_upper and kw not in found:
            found.append(kw)
    return found


def _class_inherits_strategy(node: ast.ClassDef) -> bool:
    """Retorna True si la clase hereda de Strategy o RBIStrategy (directo)."""
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id in _VALID_BASES:
            return True
        if isinstance(base, ast.Attribute) and base.attr in _VALID_BASES:
            return True
    return False


def _extract_seeds_from_source(
    source: str,
    file_path: pathlib.Path,
    origin: str,
    project_root: pathlib.Path,
) -> list[dict]:
    """Parsea el source de un archivo .py y extrae todas las clases de estrategia."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.warning("ast.parse falló en %s: %s", file_path, exc)
        return []

    seeds: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not _class_inherits_strategy(node):
            continue

        # Extraer código fuente de la clase usando líneas
        lines = source.splitlines(keepends=True)
        try:
            class_lines = lines[node.lineno - 1 : node.end_lineno]
            class_code = "".join(class_lines)
        except (AttributeError, IndexError):
            class_code = f"class {node.name}: ..."

        params = _extract_class_params(node)
        indicators = _extract_indicators(class_code)

        # Calcular path relativo al proyecto
        try:
            rel_path = file_path.relative_to(project_root).as_posix()
        except ValueError:
            rel_path = file_path.as_posix()

        seeds.append(
            {
                "name": node.name,
                "code": class_code,
                "params": params,
                "origin": origin,
                "source_file": rel_path,
                "indicators": indicators,
            }
        )
    return seeds


# ---------------------------------------------------------------------------
# SeedLibrary
# ---------------------------------------------------------------------------

class SeedLibrary:
    """Catálogo de estrategias semilla para el motor generativo de estrategias."""

    # ------------------------------------------------------------------
    # Interfaz pública
    # ------------------------------------------------------------------

    def load_all_seeds(self) -> list[dict]:
        """Carga y combina todas las fuentes de seeds.

        Orden de prioridad:
          1. Equity templates (3 — calibrados para baja volatilidad)
          2. Forex templates (4 — ATR-based, sin volumen, calibrados para pips)
          3. MoonDev / RBI strategies
          4. Proven templates
          5. Scraped (Redis)

        Garantiza unicidad por 'name': si hay duplicados entre fuentes,
        mantiene la primera aparición.
        """
        seeds: list[dict] = []
        seen_names: set[str] = set()

        for seed in (
            self._load_equity_template_seeds()
            + self._load_forex_template_seeds()
            + self._load_moondev_strategies()
            + self._load_moondev_archive()
            + self._load_proven_templates()
            + self._load_scraped()
        ):
            if seed["name"] not in seen_names:
                seeds.append(seed)
                seen_names.add(seed["name"])

        return seeds

    # ------------------------------------------------------------------
    # Fuente 0: Equity templates (alta prioridad — siempre en pool)
    # ------------------------------------------------------------------

    def _load_equity_template_seeds(self) -> list[dict]:
        """Retorna las 3 equity template seeds con template key correcto.

        A diferencia de _load_proven_templates() (que parsea via AST y no añade
        la clave 'template'), este método construye cada seed directamente con:
        - template: clave en TEMPLATE_REGISTRY (e.g. 'ema-crossover-equity')
        - params: atributos de clase calibrados para equity
        - origin: 'template'

        Esto garantiza que _slight_mutation preserve el código original en lugar
        de reemplazarlo con un snippet CROSSOVER genérico, y que _parameterize_class
        se aplique correctamente en _resolve_strategy_class.
        """
        try:
            import inspect as _inspect
            from btquantr.engine.templates.equity_templates import (
                EMACrossoverEquity,
                RSIEquity,
                BollingerEquity,
            )
        except ImportError as exc:
            logger.warning("No se pudieron importar equity templates: %s", exc)
            return []

        _EQUITY_REGISTRY_KEYS = {
            "EMACrossoverEquity": "ema-crossover-equity",
            "RSIEquity":          "rsi-equity",
            "BollingerEquity":    "bollinger-equity",
        }

        seeds: list[dict] = []
        for cls in (EMACrossoverEquity, RSIEquity, BollingerEquity):
            try:
                source = _inspect.getsource(cls)
            except (OSError, TypeError):
                source = f"class {cls.__name__}: ..."

            params = {
                k: v
                for k, v in vars(cls).items()
                if not k.startswith("_") and isinstance(v, (int, float))
            }

            seeds.append(
                {
                    "name":        cls.__name__,
                    "code":        source,
                    "params":      params,
                    "origin":      "template",
                    "source_file": "btquantr/engine/templates/equity_templates.py",
                    "indicators":  _extract_indicators(source),
                    "template":    _EQUITY_REGISTRY_KEYS[cls.__name__],
                }
            )
        return seeds

    # ------------------------------------------------------------------
    # Fuente 0b: Forex templates (alta prioridad — ATR-based, sin volumen)
    # ------------------------------------------------------------------

    def _load_forex_template_seeds(self) -> list[dict]:
        """Retorna las 4 forex template seeds con template key correcto.

        Templates calibrados para pares de divisas y activos de baja volatilidad:
        SL/TP via ATR (auto-calibra a cualquier escala de precio),
        sin dependencia de volumen (yfinance forex = volumen irreal).
        """
        try:
            import inspect as _inspect
            from btquantr.engine.templates.forex_templates import (
                ForexEMACrossATR,
                ForexBBReversionATR,
                ForexRSIRangeATR,
                ForexMACDATR,
            )
        except ImportError as exc:
            logger.warning("No se pudieron importar forex templates: %s", exc)
            return []

        _FOREX_REGISTRY_KEYS = {
            "ForexEMACrossATR":    "forex-ema-cross-atr",
            "ForexBBReversionATR": "forex-bb-reversion-atr",
            "ForexRSIRangeATR":    "forex-rsi-range-atr",
            "ForexMACDATR":        "forex-macd-atr",
        }

        seeds: list[dict] = []
        for cls in (ForexEMACrossATR, ForexBBReversionATR, ForexRSIRangeATR, ForexMACDATR):
            try:
                source = _inspect.getsource(cls)
            except (OSError, TypeError):
                source = f"class {cls.__name__}: ..."

            params = {
                k: v
                for k, v in vars(cls).items()
                if not k.startswith("_") and isinstance(v, (int, float))
            }

            seeds.append(
                {
                    "name":        cls.__name__,
                    "code":        source,
                    "params":      params,
                    "origin":      "template",
                    "source_file": "btquantr/engine/templates/forex_templates.py",
                    "indicators":  _extract_indicators(source),
                    "template":    _FOREX_REGISTRY_KEYS[cls.__name__],
                }
            )
        return seeds

    # ------------------------------------------------------------------
    # Fuente 1: MoonDev / RBI strategies
    # ------------------------------------------------------------------

    def _load_moondev_strategies(self) -> list[dict]:
        """Lee todos los .py en src/rbi/strategies/ y extrae clases Strategy."""
        seeds: list[dict] = []

        if not _MOONDEV_DIR.is_dir():
            logger.warning("Directorio MoonDev no encontrado: %s", _MOONDEV_DIR)
            return seeds

        for py_file in sorted(_MOONDEV_DIR.glob("*.py")):
            if py_file.name in _MOONDEV_SKIP:
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning("No se pudo leer %s: %s", py_file, exc)
                continue

            file_seeds = _extract_seeds_from_source(
                source=source,
                file_path=py_file,
                origin="moondev",
                project_root=_PROJECT_ROOT,
            )
            seeds.extend(file_seeds)

        return seeds

    # ------------------------------------------------------------------
    # Fuente 1b: MoonDev Archive (research/moondev_archive/)
    # ------------------------------------------------------------------

    def _load_moondev_archive(self) -> list[dict]:
        """Lee todos los .py en research/moondev_archive/ recursivamente.

        Usa rglob para capturar subdirectorios (03_14_AI_results/, FINAL_WINNING/, etc.).
        Archivos con SyntaxError o sin clases Strategy se omiten silenciosamente.
        """
        seeds: list[dict] = []

        if not _MOONDEV_ARCHIVE_DIR.is_dir():
            logger.warning("Directorio moondev_archive no encontrado: %s", _MOONDEV_ARCHIVE_DIR)
            return seeds

        for py_file in sorted(_MOONDEV_ARCHIVE_DIR.rglob("*.py")):
            try:
                source = py_file.read_text(encoding="utf-8", errors="ignore")
            except OSError as exc:
                logger.debug("No se pudo leer %s: %s", py_file, exc)
                continue

            file_seeds = _extract_seeds_from_source(
                source=source,
                file_path=py_file,
                origin="moondev",
                project_root=_PROJECT_ROOT,
            )
            seeds.extend(file_seeds)

        logger.info("moondev_archive: %d seeds cargadas", len(seeds))
        return seeds

    # ------------------------------------------------------------------
    # Fuente 2: Proven templates
    # ------------------------------------------------------------------

    def _load_proven_templates(self) -> list[dict]:
        """Lee todos los .py en btquantr/engine/templates/ si existe y no está vacío."""
        seeds: list[dict] = []

        if not _TEMPLATES_DIR.is_dir():
            return seeds

        for py_file in sorted(_TEMPLATES_DIR.glob("*.py")):
            if py_file.name.startswith("__"):
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning("No se pudo leer template %s: %s", py_file, exc)
                continue

            file_seeds = _extract_seeds_from_source(
                source=source,
                file_path=py_file,
                origin="template",
                project_root=_PROJECT_ROOT,
            )
            seeds.extend(file_seeds)

        return seeds

    # ------------------------------------------------------------------
    # Fuente 3: Scraped (Redis cache)
    # ------------------------------------------------------------------

    def _load_scraped(self) -> list[dict]:
        """Intenta leer Redis key 'engine:scraped_seeds'.

        - Si existe y TTL > 0: deserializa y retorna la lista.
        - Si no existe, TTL <= 0, o Redis no disponible: retorna [].
        """
        if redis is None:
            return []

        try:
            client = redis.Redis(host="localhost", port=6379, db=0)
            raw = client.get("engine:scraped_seeds")
            if raw is None:
                return []

            ttl = client.ttl("engine:scraped_seeds")
            # ttl == -1 → sin expiración (válido), ttl > 0 → válido, ttl == -2 → expirado
            if ttl == -2:
                return []

            data = json.loads(raw)
            if isinstance(data, list):
                return data
            return []

        except Exception as exc:  # noqa: BLE001
            logger.debug("Redis no disponible para scraped seeds: %s", exc)
            return []
