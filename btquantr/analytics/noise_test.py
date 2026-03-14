"""NoiseTest — Edge estadístico vs ruido gaussiano puro.

Genera N series sintéticas con la misma longitud y volatilidad que los
retornos originales pero media=0 (ruido puro). Compara el Sharpe real
contra la distribución nula de Sharpe sintético.

p_value = fracción de series sintéticas con Sharpe >= Sharpe real.
has_edge = p_value < alpha (default 0.05).

Diferencia vs PermutationTest:
  - PermutationTest: shufflea los retornos reales (sign-randomization).
  - NoiseTest: genera series NUEVAS con ruido gaussiano (std=std(original)).

Uso:
    result = NoiseTest(n_series=1000, seed=42).run(returns)
    if result["has_edge"]:
        # La estrategia supera ruido puro
"""
from __future__ import annotations

import math
import numpy as np


def _sharpe(arr: np.ndarray, annualize: int = 252) -> float:
    if len(arr) < 2:
        return 0.0
    std = float(arr.std(ddof=1))
    if std == 0.0:
        return 0.0
    return float(arr.mean() / std * math.sqrt(annualize))


class NoiseTest:
    """Test de ruido gaussiano para validar edge de una estrategia.

    Args:
        n_series:   Número de series sintéticas (default 1000).
        seed:       Semilla RNG (default None).
        alpha:      Umbral de significancia (default 0.05).
        annualize:  Factor de annualización del Sharpe (default 252).
    """

    def __init__(
        self,
        n_series: int = 1000,
        seed: int | None = None,
        alpha: float = 0.05,
        annualize: int = 252,
    ) -> None:
        if n_series <= 0:
            raise ValueError("n_series debe ser > 0")
        self.n_series = n_series
        self.seed = seed
        self.alpha = alpha
        self.annualize = annualize

    def run(self, returns: list[float]) -> dict:
        """Ejecuta el noise test sobre una lista de retornos.

        Args:
            returns: Retornos por trade/período (decimales).

        Returns:
            Dict con:
              - p_value:      fracción de series sintéticas con Sharpe >= real
              - has_edge:     p_value < alpha
              - real_sharpe:  Sharpe de los retornos originales
              - n_series:     N usado
              - synth_sharpes: lista de Sharpes sintéticos (para diagnóstico)
        """
        if not returns:
            raise ValueError("returns no puede estar vacío")

        arr = np.array(returns, dtype=float)
        n = len(arr)

        real_sharpe = _sharpe(arr, self.annualize)

        if n < 2:
            return {
                "p_value": 1.0,
                "has_edge": False,
                "real_sharpe": real_sharpe,
                "n_series": self.n_series,
                "synth_sharpes": [],
            }

        # Parámetros de la distribución nula: media=0, std=std(original)
        std = float(arr.std(ddof=1))
        rng = np.random.default_rng(self.seed)

        # Generar n_series series sintéticas de longitud n con media=0
        synth = rng.normal(0.0, std, size=(self.n_series, n))  # (N, n)
        synth_sharpes = [
            _sharpe(synth[i], self.annualize) for i in range(self.n_series)
        ]

        p_value = float(
            sum(1 for s in synth_sharpes if s >= real_sharpe) / self.n_series
        )
        has_edge = p_value < self.alpha

        return {
            "p_value": p_value,
            "has_edge": has_edge,
            "real_sharpe": real_sharpe,
            "n_series": self.n_series,
            "synth_sharpes": synth_sharpes,
        }
