"""
btquantr/engine/mutator.py — GeneticMutator evolutivo.

Spec: usuario + docs/biblia/autonomous_strategy_engine_v2.docx sección 8.

7 tipos de mutación con probabilidades:
  PARAM_SHIFT    40% — ajusta un parámetro ±10-30%
  SWAP_INDICATOR 15% — cambia un indicador por otro de la misma categoría
  ADD_FILTER     15% — añade un indicador filtro (ADX, ATR, Volume)
  CHANGE_EXIT    10% — modifica parámetros de salida (SL / TP)
  INVERT_SIGNAL   5% — invierte la lógica long↔short
  CROSSOVER_2P   10% — cruce de dos padres en dos puntos
  REMOVE_FILTER   5% — elimina un indicador secundario

Tournament selection k=3: de k candidatos aleatorios, selecciona el de mayor fitness.
"""
from __future__ import annotations

import copy
import random as _random
from itertools import islice

from btquantr.engine.indicator_library import IndicatorLibrary
from btquantr.optimizer.param_space import PARAM_REGISTRY

# ─────────────────────────────────────────────────────────────────────────────
# Constantes de salida
# ─────────────────────────────────────────────────────────────────────────────

_EXIT_STOP_KEY   = "exit_stop_loss_pct"
_EXIT_PROFIT_KEY = "exit_take_profit_pct"
_EXIT_DEFAULTS   = {_EXIT_STOP_KEY: 0.03, _EXIT_PROFIT_KEY: 0.06}

# Rango de variación para exit params
_EXIT_STOP_RANGE   = (0.01, 0.08)
_EXIT_PROFIT_RANGE = (0.02, 0.15)

# Cuánto se desplaza PARAM_SHIFT: fracción del rango [min, max]
_PARAM_SHIFT_FRAC = 0.15


# ─────────────────────────────────────────────────────────────────────────────
# GeneticMutator
# ─────────────────────────────────────────────────────────────────────────────

class GeneticMutator:
    """Motor genético para evolucionar poblaciones de estrategias.

    Args:
        random_state: semilla para reproducibilidad (None = no determinista).
    """

    MUTATION_PROBABILITIES: dict[str, float] = {
        "PARAM_SHIFT":    0.40,
        "SWAP_INDICATOR": 0.15,
        "ADD_FILTER":     0.15,
        "CHANGE_EXIT":    0.10,
        "INVERT_SIGNAL":  0.05,
        "CROSSOVER_2P":   0.10,
        "REMOVE_FILTER":  0.05,
    }

    _TOURNAMENT_K = 3

    def __init__(self, random_state: int | None = None) -> None:
        self._lib = IndicatorLibrary()
        self._rng = _random.Random(random_state)
        self._counter = 0

    # ── API pública ────────────────────────────────────────────────────────────

    def evolve(self, top_strategies: list[dict], n_offspring: int = 50) -> list[dict]:
        """Genera n_offspring variantes a partir del pool de estrategias elite.

        Usa tournament selection k=3 para elegir padres y aplica mutaciones
        con las probabilidades del spec.

        Args:
            top_strategies: Lista de dicts de estrategia con clave 'fitness'.
            n_offspring:    Número de hijos a generar.

        Returns:
            Lista de n_offspring dicts de estrategia mutados/cruzados.
        """
        if not top_strategies or n_offspring == 0:
            return []

        offspring: list[dict] = []
        mutation_types = list(self.MUTATION_PROBABILITIES.keys())
        weights        = list(self.MUTATION_PROBABILITIES.values())

        while len(offspring) < n_offspring:
            mut_type = self._rng.choices(mutation_types, weights=weights, k=1)[0]

            if mut_type == "CROSSOVER_2P":
                parent_a = self.tournament_select(top_strategies)
                parent_b = self.tournament_select(top_strategies)
                child = self._crossover_2p(parent_a, parent_b)
            else:
                parent = self.tournament_select(top_strategies)
                child = self._apply_mutation(mut_type, parent)

            offspring.append(child)

        return offspring

    def tournament_select(self, pool: list[dict], k: int | None = None) -> dict:
        """Selecciona el mejor candidato de k elegidos aleatoriamente.

        Args:
            pool: Lista de estrategias candidatas.
            k:    Tamaño del torneo (default: _TOURNAMENT_K = 3).

        Returns:
            Copia profunda del candidato con mayor fitness entre los k elegidos.
        """
        k = k or self._TOURNAMENT_K
        sample_k = min(k, len(pool))
        contestants = self._rng.sample(pool, sample_k)
        best = max(contestants, key=lambda s: s.get("fitness", 0.0))
        return copy.deepcopy(best)

    # ── Dispatcher de mutaciones ───────────────────────────────────────────────

    def _apply_mutation(self, mut_type: str, strategy: dict) -> dict:
        dispatch = {
            "PARAM_SHIFT":    self._param_shift,
            "SWAP_INDICATOR": self._swap_indicator,
            "ADD_FILTER":     self._add_filter,
            "CHANGE_EXIT":    self._change_exit,
            "INVERT_SIGNAL":  self._invert_signal,
            "REMOVE_FILTER":  self._remove_filter,
        }
        return dispatch[mut_type](strategy)

    # ── Mutaciones individuales ────────────────────────────────────────────────

    def _param_shift(self, strategy: dict) -> dict:
        """PARAM_SHIFT: ajusta un parámetro numérico ±10-30%."""
        child = self._clone(strategy, "PARAM_SHIFT")
        params = child["params"]
        if not params:
            return child

        key = self._rng.choice(list(params.keys()))
        val = params[key]
        if not isinstance(val, (int, float)):
            return child

        # Intentar respetar los bounds del indicador; fallback al PARAM_REGISTRY
        bounds = self._find_bounds_for_param(key, strategy.get("indicators", []))
        if bounds is None:
            bounds = self._find_bounds_from_registry(key, strategy.get("template", ""))
        if bounds:
            lo, hi, step = bounds["min"], bounds["max"], bounds["step"]
            n_steps = max(1, (hi - lo) // step)
            delta   = max(1, int(n_steps * _PARAM_SHIFT_FRAC))
            direction = self._rng.choice([-1, 1])
            cur_step  = max(0, (int(val) - lo) // step)
            new_step  = max(0, min(n_steps, cur_step + direction * delta))
            params[key] = int(lo + new_step * step)
        else:
            delta = max(1, int(abs(val) * self._rng.uniform(0.10, 0.30)))
            params[key] = max(1, int(val) + self._rng.choice([-1, 1]) * delta)

        child["params"] = params
        return child

    def _swap_indicator(self, strategy: dict) -> dict:
        """SWAP_INDICATOR: reemplaza un indicador por otro de la misma categoría."""
        child = self._clone(strategy, "SWAP_INDICATOR")
        indicators = list(child["indicators"])
        if not indicators:
            return child

        idx = self._rng.randrange(len(indicators))
        old_ind_name = indicators[idx]

        # Buscar alternativas de la misma categoría
        try:
            old_ind = self._lib.get(old_ind_name)
            alternatives = self._lib.same_type_swap(old_ind)
        except KeyError:
            alternatives = []

        if alternatives:
            new_ind = self._rng.choice(alternatives)
            indicators[idx] = new_ind["name"]
            # Actualizar params: eliminar los del indicador viejo, añadir nuevos
            params = dict(child["params"])
            for k in list(params.keys()):
                if k.startswith(f"{old_ind_name}_"):
                    del params[k]
            for p_name, p_bounds in new_ind["params"].items():
                ns_key = f"{new_ind['name']}_{p_name}"
                lo, hi, step = p_bounds["min"], p_bounds["max"], p_bounds["step"]
                n_steps = max(0, (hi - lo) // step)
                params[ns_key] = int(lo + self._rng.randint(0, n_steps) * step)
            child["params"] = params

        child["indicators"] = indicators
        return child

    def _add_filter(self, strategy: dict) -> dict:
        """ADD_FILTER: añade un indicador filtro (preferiblemente FILTER o TREND)."""
        child = self._clone(strategy, "ADD_FILTER")
        # Candidatos: indicadores FILTER o TREND que no estén ya en la lista
        existing = set(child["indicators"])
        candidates = [
            ind for ind in (
                self._lib.get_by_signal_type("FILTER")
                + self._lib.get_by_category("TREND")
                + self._lib.get_by_category("VOLUME")
            )
            if ind["name"] not in existing
        ]
        if not candidates:
            return child

        new_ind = self._rng.choice(candidates)
        child["indicators"] = list(child["indicators"]) + [new_ind["name"]]

        # Añadir sus params al dict
        params = dict(child["params"])
        for p_name, p_bounds in new_ind["params"].items():
            ns_key = f"{new_ind['name']}_{p_name}"
            lo, hi, step = p_bounds["min"], p_bounds["max"], p_bounds["step"]
            n_steps = max(0, (hi - lo) // step)
            params[ns_key] = int(lo + self._rng.randint(0, n_steps) * step)
        child["params"] = params
        return child

    def _change_exit(self, strategy: dict) -> dict:
        """CHANGE_EXIT: modifica parámetros de salida (stop_loss y take_profit)."""
        child = self._clone(strategy, "CHANGE_EXIT")
        params = dict(child["params"])

        # Generar nuevos valores de SL y TP dentro de sus rangos
        sl_lo, sl_hi = _EXIT_STOP_RANGE
        tp_lo, tp_hi = _EXIT_PROFIT_RANGE
        params[_EXIT_STOP_KEY]   = round(self._rng.uniform(sl_lo, sl_hi), 3)
        params[_EXIT_PROFIT_KEY] = round(self._rng.uniform(tp_lo, tp_hi), 3)

        child["params"] = params
        return child

    def _invert_signal(self, strategy: dict) -> dict:
        """INVERT_SIGNAL: invierte la lógica long↔short (toggle del flag 'inverted')."""
        child = self._clone(strategy, "INVERT_SIGNAL")
        child["inverted"] = not child.get("inverted", False)
        return child

    def _crossover_2p(self, parent_a: dict, parent_b: dict) -> dict:
        """CROSSOVER_2P: cruce de dos puntos entre los params de dos padres.

        Divide la lista de claves de params en 3 segmentos; el hijo hereda
        segmentos alternos de cada padre.
        """
        self._counter += 1

        # Combinar conjuntos de claves de ambos padres
        all_keys = list(dict.fromkeys(
            list(parent_a["params"].keys()) + list(parent_b["params"].keys())
        ))
        n = len(all_keys)
        params: dict = {}

        if n == 0:
            params = {}
        elif n == 1:
            # Un solo parámetro: elegir aleatoriamente de cuál padre
            key0 = all_keys[0]
            src = parent_a if self._rng.random() < 0.5 else parent_b
            params[key0] = src["params"].get(key0, parent_a["params"].get(key0, 0))
        elif n == 2:
            # Un único punto de corte aleatorio: mitad A/B o B/A
            flip = self._rng.random() < 0.5
            pa, pb = (parent_a, parent_b) if flip else (parent_b, parent_a)
            params[all_keys[0]] = pa["params"].get(all_keys[0],
                                   pb["params"].get(all_keys[0], 0))
            params[all_keys[1]] = pb["params"].get(all_keys[1],
                                   pa["params"].get(all_keys[1], 0))
        else:
            # Dos puntos de corte dentro de [1, n-1] + flip aleatorio de roles
            pts = sorted(self._rng.sample(range(1, n), 2))
            p1, p2 = pts[0], pts[1]
            flip = self._rng.random() < 0.5  # randomiza qué padre inicia
            pa, pb = (parent_a, parent_b) if flip else (parent_b, parent_a)
            for i, k in enumerate(all_keys):
                if i < p1 or i >= p2:
                    params[k] = pa["params"].get(k, pb["params"].get(k, 0))
                else:
                    params[k] = pb["params"].get(k, pa["params"].get(k, 0))

        # El template y los indicadores vienen del padre A
        name = f"XOVER_{parent_a['name']}x{parent_b['name']}_{self._counter:04d}"
        return {
            "name":          name,
            "template":      parent_a.get("template", "CROSSOVER"),
            "code":          parent_a.get("code", ""),
            "params":        params,
            "origin":        "crossed",
            "indicators":    list(parent_a.get("indicators", [])),
            "mutation_type": "CROSSOVER_2P",
        }

    def _remove_filter(self, strategy: dict) -> dict:
        """REMOVE_FILTER: elimina un indicador secundario (deja mínimo 1)."""
        child = self._clone(strategy, "REMOVE_FILTER")
        indicators = list(child["indicators"])
        if len(indicators) <= 1:
            return child

        # Eliminar un indicador aleatorio
        idx = self._rng.randrange(len(indicators))
        removed = indicators.pop(idx)

        # Limpiar sus params del dict
        params = dict(child["params"])
        for k in list(params.keys()):
            if k.startswith(f"{removed}_"):
                del params[k]

        child["indicators"] = indicators
        child["params"]     = params
        return child

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _clone(self, strategy: dict, mutation_type: str) -> dict:
        """Deep-copy + nuevo nombre + mutation_type tag."""
        self._counter += 1
        child = copy.deepcopy(strategy)
        child["name"]          = f"{strategy['name']}_m{self._counter:04d}"
        child["origin"]        = "mutated"
        child["mutation_type"] = mutation_type
        # Limpiar fitness anterior para que se recalcule
        child.pop("fitness", None)
        return child

    def _find_bounds_from_registry(self, param_key: str, strategy_name: str) -> dict | None:
        """Busca bounds en PARAM_REGISTRY dado el nombre de estrategia y el param."""
        params = PARAM_REGISTRY.get(strategy_name.lower(), None)
        if params is None:
            return None
        for pr in params:
            if pr.name == param_key:
                return {"min": pr.min_val, "max": pr.max_val, "step": pr.step}
        return None

    def _find_bounds_for_param(self, param_key: str, indicators: list[str]) -> dict | None:
        """Busca los bounds de un param namespacado en los indicadores de la estrategia."""
        for ind_name in indicators:
            try:
                ind = self._lib.get(ind_name)
            except KeyError:
                continue
            # Buscar con namespace exacto
            suffix = param_key.removeprefix(f"{ind_name}_")
            if suffix in ind["params"]:
                return ind["params"][suffix]
            if param_key in ind["params"]:
                return ind["params"][param_key]
        return None
