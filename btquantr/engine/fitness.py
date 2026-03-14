"""
btquantr/engine/fitness.py — Fitness Multi-Objetivo + Regime-Aware.

Spec: docs/biblia/autonomous_strategy_engine_v2.docx secciones 4 y 5.

MultiFitness:
    Función de fitness compuesta (7 métricas ponderadas).
    Evita seleccionar estrategias con Sharpe alto pero DD destructivo o pocos trades.

RegimeAwareFitness:
    Evalúa por régimen HMM y premia estrategias especialistas.
    Mantiene poblaciones separadas BULL / BEAR / SIDEWAYS.
"""
from __future__ import annotations

import numpy as np

from btquantr.analytics.consistency import ConsistencyAnalyzer


# ─────────────────────────────────────────────────────────────────────────────
# MultiFitness
# ─────────────────────────────────────────────────────────────────────────────

class MultiFitness:
    """Fitness multi-objetivo para selección de estrategias evolutivas.

    Pondera 7 métricas para evitar estrategias con Sharpe alto pero peligrosas:
    - Sharpe alto + DD -30% + 8 trades  → score ~0.35
    - Sharpe medio + DD -8%  + 60 trades → score ~0.72  (preferida)
    """

    WEIGHTS: dict[str, float] = {
        "sharpe":        0.30,
        "sortino":       0.15,
        "calmar":        0.15,
        "consistency":   0.15,
        "trade_count":   0.10,
        "profit_factor": 0.10,
        "dd_penalty":    0.05,
    }

    def score(self, stats: dict | None, returns: list[float]) -> float:
        """Calcula el fitness compuesto de una estrategia.

        Args:
            stats:   Dict de stats de backtesting.py (opcional, no usado en cálculo
                     central — mantenido por compatibilidad con el spec).
            returns: Lista de retornos por trade (floats decimales, ej. 0.01 = 1%).
                     También acepta lista de dicts con clave 'return_pct'.

        Returns:
            float en [0.0, 1.0] redondeado a 4 decimales.
        """
        if not returns:
            return 0.0

        # Extraer floats si se pasan trade dicts
        float_returns = self._extract_returns(returns)
        if not float_returns:
            return 0.0

        try:
            metrics = ConsistencyAnalyzer().analyze(float_returns)
        except (ValueError, ZeroDivisionError):
            return 0.0

        max_dd = metrics["max_drawdown"]  # valor negativo, ej. -0.20

        # Penalización por drawdown (spec: umbral 15% y 25%)
        abs_dd = abs(max_dd)
        if abs_dd < 0.15:
            dd_penalty = 1.0
        elif abs_dd < 0.25:
            dd_penalty = 0.5
        else:
            dd_penalty = 0.0

        pf = metrics["profit_factor"]
        pf_val = pf if np.isfinite(pf) else 3.0  # cap al máximo de normalización

        sortino = metrics["sortino"]
        sortino_val = sortino if np.isfinite(sortino) else 4.0

        calmar = metrics["calmar"]
        calmar_val = calmar if np.isfinite(calmar) else 5.0

        scores: dict[str, float] = {
            "sharpe":        self._norm(metrics["sharpe"],   -1, 3),
            "sortino":       self._norm(sortino_val,          -1, 4),
            "calmar":        self._norm(calmar_val,           -1, 5),
            "consistency":   metrics["consistency_score"],
            "trade_count":   min(1.0, len(float_returns) / 50),
            "profit_factor": self._norm(pf_val,               0, 3),
            "dd_penalty":    dd_penalty,
        }

        total = sum(scores[k] * self.WEIGHTS[k] for k in self.WEIGHTS)
        return round(total, 4)

    def _norm(self, val: float, min_v: float, max_v: float) -> float:
        """Normaliza val a [0, 1] dado el rango [min_v, max_v]."""
        return max(0.0, min(1.0, (val - min_v) / (max_v - min_v)))

    def _extract_returns(self, returns: list) -> list[float]:
        """Acepta lista de floats o lista de dicts con clave 'return_pct'."""
        if not returns:
            return []
        if isinstance(returns[0], dict):
            return [t.get("return_pct", 0.0) for t in returns]
        return [float(r) for r in returns]


# ─────────────────────────────────────────────────────────────────────────────
# RegimeAwareFitness
# ─────────────────────────────────────────────────────────────────────────────

_REGIMES = ("BULL", "BEAR", "SIDEWAYS")
_MIN_TRADES = 5          # mínimo de trades para calcular fitness por régimen
_QUOTAS = {"BULL": 4, "BEAR": 3, "SIDEWAYS": 3}   # total = 10


class RegimeAwareFitness:
    """Fitness regime-aware: evalúa por régimen HMM y premia especialistas.

    En vez de evaluar mezclando todos los datos, separa los trades por el régimen
    HMM activo al momento de apertura. Identifica en qué régimen destaca la estrategia.

    El EvolutionLoop mantiene poblaciones separadas (4 BULL + 3 BEAR + 3 SIDEWAYS)
    en lugar de seleccionar 10 mediocres globales.
    """

    def score(self, trades: list[dict], hmm_history: dict) -> dict:
        """Evalúa la estrategia por régimen HMM.

        Args:
            trades: Lista de trade dicts con claves:
                    - 'opened_at': key para buscar en hmm_history
                    - 'return_pct': retorno del trade (float decimal)
            hmm_history: Dict {key → 'BULL'|'BEAR'|'SIDEWAYS'}.

        Returns:
            Dict con:
                BULL / BEAR / SIDEWAYS: {score, trades, sharpe}
                best_regime: str
                specialist_score: float
        """
        # Separar trades por régimen
        # Soporta claves float (timestamp) con búsqueda directa o closest-match
        hmm_keys = sorted(hmm_history.keys()) if hmm_history else []
        by_regime: dict[str, list[dict]] = {r: [] for r in _REGIMES}
        for t in trades:
            opened_at = t.get("opened_at")
            regime = hmm_history.get(opened_at, "UNKNOWN")
            # Si no hay coincidencia exacta y la clave es numérica, buscar el más cercano
            if regime == "UNKNOWN" and isinstance(opened_at, (int, float)) and hmm_keys:
                import bisect
                idx = bisect.bisect_left(hmm_keys, opened_at)
                candidates = []
                if idx < len(hmm_keys):
                    candidates.append(hmm_keys[idx])
                if idx > 0:
                    candidates.append(hmm_keys[idx - 1])
                closest = min(candidates, key=lambda k: abs(k - opened_at))
                if abs(closest - opened_at) <= 14400:  # dentro de 4 horas
                    regime = hmm_history[closest]
            if regime in by_regime:
                by_regime[regime].append(t)

        fitness = MultiFitness()
        analyzer = ConsistencyAnalyzer()
        results: dict = {}

        for regime in _REGIMES:
            regime_trades = by_regime[regime]
            n = len(regime_trades)
            if n >= _MIN_TRADES:
                returns = [t.get("return_pct", 0.0) for t in regime_trades]
                try:
                    metrics = analyzer.analyze(returns)
                    sharpe = metrics["sharpe"]
                except (ValueError, ZeroDivisionError):
                    sharpe = 0.0
                results[regime] = {
                    "score":  fitness.score(None, regime_trades),
                    "trades": n,
                    "sharpe": sharpe,
                }
            else:
                results[regime] = {"score": 0, "trades": n, "sharpe": 0}

        # Identificar régimen donde la estrategia destaca
        best_regime = max(_REGIMES, key=lambda r: results[r]["score"])
        results["best_regime"] = best_regime
        results["specialist_score"] = results[best_regime]["score"]

        return results

    def _select_by_regime(self, evaluated: list[dict]) -> list[dict]:
        """Selecciona las mejores estrategias por régimen con cuotas fijas.

        Cuotas: BULL=4, BEAR=3, SIDEWAYS=3 (total=10).
        Garantiza diversidad de especialistas en vez de selección global.

        Args:
            evaluated: Lista de estrategias con clave 'regime_fitness' que contiene
                       el resultado de RegimeAwareFitness.score().

        Returns:
            Lista de hasta 10 estrategias seleccionadas.
        """
        if not evaluated:
            return []

        # Agrupar por mejor régimen
        by_regime: dict[str, list[dict]] = {r: [] for r in _REGIMES}
        for s in evaluated:
            best = s.get("regime_fitness", {}).get("best_regime", "BULL")
            if best in by_regime:
                by_regime[best].append(s)

        selected: list[dict] = []
        for regime, quota in _QUOTAS.items():
            # Ordenar descendente por score en ese régimen
            sorted_candidates = sorted(
                by_regime[regime],
                key=lambda s: s["regime_fitness"].get(regime, {}).get("score", 0.0),
                reverse=True,
            )
            selected.extend(sorted_candidates[:quota])

        return selected
