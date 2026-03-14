"""
btquantr/engine/generator.py — StrategyGenerator combinatorio.

Spec: docs/biblia/autonomous_strategy_engine_v2.docx sección 7.

Genera estrategias combinando seeds reales + IndicatorLibrary con 6 templates:
  CROSSOVER            — cruce de dos indicadores de tendencia (fast/slow)
  THRESHOLD_CONFIRM    — indicador THRESHOLD con filtro confirmador
  BREAKOUT             — ruptura de canal (BB, Donchian, KC)
  MEAN_REVERSION       — toque de banda + reversión al medio
  MOMENTUM_FILTER      — indicador MOMENTUM + filtro de tendencia
  VOLATILITY_SQUEEZE   — BB dentro de KC → squeeze momentum

Cada estrategia generada es un dict con:
  name       : str   — identificador único
  template   : str   — uno de los 6 templates
  code       : str   — fragmento de código Python (template)
  params     : dict  — parámetros con valores dentro de los bounds del indicador
  origin     : str   — 'generated' | 'mutated'
  indicators : list  — nombres de indicadores usados
"""
from __future__ import annotations

import copy
import random as _random

from btquantr.engine.indicator_library import IndicatorLibrary

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

TEMPLATES = [
    "CROSSOVER",
    "THRESHOLD_CONFIRM",
    "BREAKOUT",
    "MEAN_REVERSION",
    "MOMENTUM_FILTER",
    "VOLATILITY_SQUEEZE",
]

# Conjunto para lookup O(1) — seeds con template key fuera de este set
# usan el código y template key originales sin regenerar con _render_code
_GENERATOR_TEMPLATES_SET: frozenset[str] = frozenset(TEMPLATES)

# Plantillas de código Python para cada template
# {ind_X_param} se reemplaza al generar los params concretos
_CODE_TEMPLATES: dict[str, str] = {
    "CROSSOVER": (
        "# CROSSOVER: {ind0} fast × {ind1} slow\n"
        "fast = self.I(lambda: {code0}, name='{ind0}_fast')\n"
        "slow = self.I(lambda: {code1}, name='{ind1}_slow')\n"
        "# Long when fast crosses above slow, Short when crosses below"
    ),
    "THRESHOLD_CONFIRM": (
        "# THRESHOLD_CONFIRM: {ind0} signal + {ind1} filter\n"
        "signal = self.I(lambda: {code0}, name='{ind0}')\n"
        "confirm = self.I(lambda: {code1}, name='{ind1}')\n"
        "# Enter when signal crosses threshold and confirm validates"
    ),
    "BREAKOUT": (
        "# BREAKOUT: {ind0} channel\n"
        "channel = self.I(lambda: {code0}, name='{ind0}')\n"
        "# Long when price breaks upper band, Short when breaks lower"
    ),
    "MEAN_REVERSION": (
        "# MEAN_REVERSION: {ind0} bands\n"
        "bands = self.I(lambda: {code0}, name='{ind0}')\n"
        "# Long at lower band, Short at upper band, exit at mid"
    ),
    "MOMENTUM_FILTER": (
        "# MOMENTUM_FILTER: {ind0} momentum + {ind1} trend filter\n"
        "momentum = self.I(lambda: {code0}, name='{ind0}')\n"
        "trend = self.I(lambda: {code1}, name='{ind1}')\n"
        "# Enter when momentum extreme + trend aligned"
    ),
    "VOLATILITY_SQUEEZE": (
        "# VOLATILITY_SQUEEZE: BB inside KC\n"
        "bb = self.I(lambda: {code0}, name='BB')\n"
        "kc = self.I(lambda: {code1}, name='KC')\n"
        "# Long/Short when squeeze releases in direction of momentum"
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# StrategyGenerator
# ─────────────────────────────────────────────────────────────────────────────

class StrategyGenerator:
    """Genera poblaciones de estrategias combinando seeds + IndicatorLibrary.

    Args:
        random_state: Semilla para reproducibilidad. None = no determinista.
    """

    def __init__(self, random_state: int | None = None) -> None:
        self._lib = IndicatorLibrary()
        self._rng = _random.Random(random_state)
        self._counter = 0  # para nombres únicos

    # ── API pública ────────────────────────────────────────────────────────────

    def generate(self, n: int = 100, seeds: list[dict] | None = None) -> list[dict]:
        """Genera una población de n estrategias.

        Si se proveen seeds:
          - Hasta n//2 seeds son mutadas ligeramente (_slight_mutation)
          - El resto se genera con _random_combination

        Args:
            n:     Tamaño de la población a generar.
            seeds: Estrategias base (dicts con estructura de seed).

        Returns:
            Lista de n dicts con claves: name, template, code, params, origin, indicators.
        """
        if n == 0:
            return []

        population: list[dict] = []

        effective_seeds = seeds or []
        if effective_seeds:
            # Hasta n//2 mutaciones
            for seed in effective_seeds[: n // 2]:
                population.append(self._slight_mutation(seed))

        # Rellenar con combinaciones nuevas hasta n
        while len(population) < n:
            population.append(self._random_combination())

        return population

    # ── Generación aleatoria ───────────────────────────────────────────────────

    def _random_combination(self) -> dict:
        """Genera una estrategia nueva combinando indicadores aleatoriamente."""
        template = self._rng.choice(TEMPLATES)
        return self._build_from_template(template, origin="generated")

    # ── Mutación ───────────────────────────────────────────────────────────────

    def _slight_mutation(self, seed: dict) -> dict:
        """Muta ligeramente una seed: ajusta 1-2 params en ±10-20%.

        No modifica el dict original.
        """
        mutated = copy.deepcopy(seed)
        mutated["origin"] = "mutated"

        params = dict(mutated["params"])

        # Seleccionar 1-2 params a mutar
        param_keys = list(params.keys())
        if param_keys:
            n_to_mutate = min(2, len(param_keys))
            keys_to_mutate = self._rng.sample(param_keys, n_to_mutate)
            for key in keys_to_mutate:
                params[key] = self._mutate_param(
                    key, params[key], mutated.get("indicators", [])
                )

        mutated["params"] = params
        self._counter += 1
        base_name = seed.get("name", "seed")
        mutated["name"] = f"{base_name}_mut{self._counter}"

        seed_template = seed.get("template", "")
        if seed_template and seed_template not in _GENERATOR_TEMPLATES_SET:
            # Seed de TEMPLATE_REGISTRY (e.g. equity templates): preservar código y
            # template key originales. _resolve_strategy_class usará el path de
            # TEMPLATE_REGISTRY + _parameterize_class para aplicar los params mutados.
            mutated["code"] = seed.get("code", "")
            mutated["template"] = seed_template
        else:
            # Seed del generador combinatorio o moondev: regenerar snippet de código
            mutated["code"] = self._render_code(
                seed_template or "CROSSOVER",
                mutated.get("indicators", []),
                params,
            )
        return mutated

    # ── Helpers internos ───────────────────────────────────────────────────────

    def _build_from_template(self, template: str, origin: str) -> dict:
        """Construye una seed con el template dado, eligiendo indicadores apropiados."""
        self._counter += 1

        if template == "CROSSOVER":
            inds = self._pick_crossover_indicators()
        elif template == "THRESHOLD_CONFIRM":
            inds = self._pick_threshold_confirm_indicators()
        elif template == "BREAKOUT":
            inds = self._pick_breakout_indicators()
        elif template == "MEAN_REVERSION":
            inds = self._pick_mean_reversion_indicators()
        elif template == "MOMENTUM_FILTER":
            inds = self._pick_momentum_filter_indicators()
        else:  # VOLATILITY_SQUEEZE
            inds = self._pick_squeeze_indicators()

        params = self._sample_params(inds)
        code = self._render_code(template, [ind["name"] for ind in inds], params)

        return {
            "name": f"{template}_{self._counter:04d}",
            "template": template,
            "code": code,
            "params": params,
            "origin": origin,
            "indicators": [ind["name"] for ind in inds],
        }

    # ── Selección de indicadores por template ─────────────────────────────────

    def _pick_crossover_indicators(self) -> list[dict]:
        """Dos indicadores CROSSOVER (ej. EMA fast, EMA slow)."""
        crossover_inds = self._lib.get_by_signal_type("CROSSOVER")
        ind = self._rng.choice(crossover_inds)
        # El segundo puede ser el mismo tipo u otro CROSSOVER
        second = self._rng.choice(crossover_inds)
        return [ind, second]

    def _pick_threshold_confirm_indicators(self) -> list[dict]:
        """Un indicador THRESHOLD + un confirmador (FILTER o LEVEL)."""
        threshold_inds = self._lib.get_by_signal_type("THRESHOLD")
        confirm_inds = (
            self._lib.get_by_signal_type("FILTER")
            + self._lib.get_by_signal_type("LEVEL")
        )
        signal = self._rng.choice(threshold_inds)
        confirm = self._rng.choice(confirm_inds)
        return [signal, confirm]

    def _pick_breakout_indicators(self) -> list[dict]:
        """Un indicador de canal LEVEL o VOLATILITY."""
        level_inds = self._lib.get_by_signal_type("LEVEL")
        volatility_inds = self._lib.get_by_category("VOLATILITY")
        # Unión única por nombre
        pool = {ind["name"]: ind for ind in (level_inds + volatility_inds)}
        return [self._rng.choice(list(pool.values()))]

    def _pick_mean_reversion_indicators(self) -> list[dict]:
        """Un indicador LEVEL (BB, KC, Donchian)."""
        level_inds = self._lib.get_by_signal_type("LEVEL")
        return [self._rng.choice(level_inds)]

    def _pick_momentum_filter_indicators(self) -> list[dict]:
        """Un indicador MOMENTUM + un indicador TREND como filtro."""
        momentum_inds = self._lib.get_by_category("MOMENTUM")
        trend_inds = self._lib.get_by_category("TREND")
        mom = self._rng.choice(momentum_inds)
        trend = self._rng.choice(trend_inds)
        return [mom, trend]

    def _pick_squeeze_indicators(self) -> list[dict]:
        """BollingerBands + KeltnerChannel (fijos para squeeze)."""
        return [
            self._lib.get("BollingerBands"),
            self._lib.get("KeltnerChannel"),
        ]

    # ── Sampling de params ─────────────────────────────────────────────────────

    def _sample_params(self, indicators: list[dict]) -> dict:
        """Samplea params aleatorios dentro de bounds para cada indicador.

        Todos los params se namespace como '{IndName}_{param}' para evitar
        colisiones entre indicadores con el mismo nombre de param (ej: 'length').
        """
        params: dict = {}
        for ind in indicators:
            for param_name, bounds in ind["params"].items():
                lo, hi, step = bounds["min"], bounds["max"], bounds["step"]
                n_steps = max(0, (hi - lo) // step)
                chosen = lo + self._rng.randint(0, n_steps) * step
                # Siempre namespace para evitar colisiones cross-indicador
                ns_key = f"{ind['name']}_{param_name}"
                params[ns_key] = int(chosen)
        return params

    def _mutate_param(self, key: str, value: int | float, indicators: list[str]) -> int | float:
        """Muta un único param en ±10-20%, respetando los bounds del indicador."""
        bounds = self._find_bounds(key, indicators)
        if bounds is None:
            delta = max(1, int(abs(value) * self._rng.uniform(0.10, 0.20)))
            direction = self._rng.choice([-1, 1])
            return max(1, int(value) + direction * delta)

        lo, hi, step = bounds["min"], bounds["max"], bounds["step"]
        delta_steps = max(1, int(((hi - lo) // step) * 0.15))
        direction = self._rng.choice([-1, 1])
        n_steps = max(0, (int(value) - lo) // step)
        new_steps = max(0, min((hi - lo) // step, n_steps + direction * delta_steps))
        return int(lo + new_steps * step)

    def _find_bounds(self, param_key: str, indicator_names: list[str]) -> dict | None:
        """Busca los bounds de un param (namespace o plano) en los indicadores dados.

        Soporta claves con namespace '{IndName}_{param}' y planas '{param}'.
        """
        for ind_name in indicator_names:
            try:
                ind = self._lib.get(ind_name)
            except KeyError:
                continue
            ns_key = f"{ind_name}_{param_key}"
            # Buscar con namespace exacto
            for stored in (param_key, ns_key):
                if stored in ind["params"]:
                    return ind["params"][stored]
            # Buscar la parte sin prefijo (quitar 'IndName_')
            suffix = param_key.removeprefix(f"{ind_name}_")
            if suffix in ind["params"]:
                return ind["params"][suffix]
        return None

    # ── Render de código ───────────────────────────────────────────────────────

    def _render_code(
        self, template: str, indicator_names: list[str], params: dict
    ) -> str:
        """Rellena la plantilla de código con indicadores y params concretos.

        Los params están namespacados como '{IndName}_{param}'; se mapean al
        template de código de cada indicador.
        """
        tpl = _CODE_TEMPLATES.get(template, "# {template} strategy")

        codes = []
        for ind_name in indicator_names:
            try:
                ind = self._lib.get(ind_name)
                # Construir mapping local: param_name → valor (desde namespace)
                param_map = {}
                for k, v in ind["params"].items():
                    ns_key = f"{ind_name}_{k}"
                    param_map[k] = params.get(ns_key, params.get(k, v["default"]))
                filled = ind["code_template"].format(**param_map)
                codes.append(filled)
            except (KeyError, IndexError):
                codes.append(f"# {ind_name}")

        while len(codes) < 2:
            codes.append(f"# indicator_{len(codes)}")

        try:
            return tpl.format(
                ind0=indicator_names[0] if indicator_names else "IND0",
                ind1=indicator_names[1] if len(indicator_names) > 1 else "IND1",
                code0=codes[0],
                code1=codes[1],
                template=template,
            )
        except (KeyError, IndexError):
            return f"# {template} strategy\n# indicators: {indicator_names}"
