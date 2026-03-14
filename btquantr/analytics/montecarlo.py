"""MonteCarloSimulator — Bootstrap Monte Carlo para riesgo de portfolio.

También incluye MonteCarloVarianceTest: resampleo de trades con IC 95%
de Sharpe y max drawdown.
"""
from __future__ import annotations
import math
import numpy as np


def _sharpe(arr: np.ndarray, annualize: int = 252) -> float:
    """Sharpe anualizado sobre una serie de retornos."""
    if len(arr) < 2:
        return 0.0
    std = float(arr.std(ddof=1))
    if std == 0.0:
        return 0.0
    return float(arr.mean() / std * math.sqrt(annualize))


def _max_drawdown(arr: np.ndarray) -> float:
    """Max drawdown de una serie de retornos (valor ≤ 0)."""
    cumulative = np.cumprod(1.0 + arr)
    peak = np.maximum.accumulate(cumulative)
    dd = (cumulative - peak) / peak
    return float(dd.min()) if len(dd) else 0.0


class MonteCarloSimulator:
    """Bootstrap Monte Carlo para estimación de VaR, CVaR y probabilidad de ruina."""

    def __init__(self, n_sims: int = 1000, seed: int | None = None):
        self.n_sims = n_sims
        self.rng = np.random.default_rng(seed)

    def simulate(
        self,
        returns: list[float],
        ruin_threshold: float = 0.0,
    ) -> dict:
        """Simula n_sims paths bootstrap a partir de los retornos históricos.

        Args:
            returns: Serie histórica de retornos (decimales).
            ruin_threshold: Valor del portfolio debajo del cual se considera ruina
                           (como fracción del capital inicial, ej: 0.5 = -50%).

        Returns:
            Dict con: var_95, var_99, cvar_95, cvar_99, prob_ruin, median_final,
                      drawdown_dist (percentiles p10/p50/p90).
        """
        if not returns:
            raise ValueError("returns no puede estar vacío")

        arr = np.array(returns, dtype=float)
        n = len(arr)

        # Bootstrap: resamplear con reemplazo para crear n_sims paths
        idx = self.rng.integers(0, n, size=(self.n_sims, n))
        paths = arr[idx]  # shape (n_sims, n)

        # Retorno acumulado final de cada path
        cumulative = np.cumprod(1 + paths, axis=1)  # shape (n_sims, n)
        final = cumulative[:, -1]  # valor final relativo al capital inicial

        # ── VaR / CVaR ────────────────────────────────────────────────────────
        # Expresados como retorno (ej: -0.15 = -15%)
        final_returns = final - 1.0

        var_95 = float(np.percentile(final_returns, 5))    # 5° percentil = VaR 95%
        var_99 = float(np.percentile(final_returns, 1))    # 1° percentil = VaR 99%
        cvar_95 = float(np.mean(final_returns[final_returns <= var_95]))
        cvar_99 = float(np.mean(final_returns[final_returns <= var_99]))

        # ── Probabilidad de ruina ──────────────────────────────────────────────
        # Ruina = algún momento el portfolio cae por debajo del threshold
        ruin_mask = np.any(cumulative < (1.0 + ruin_threshold), axis=1)
        prob_ruin = float(np.mean(ruin_mask))

        # ── Mediana del valor final ────────────────────────────────────────────
        median_final = float(np.median(final))

        # ── Distribución de drawdown máximo ───────────────────────────────────
        peak = np.maximum.accumulate(cumulative, axis=1)
        drawdowns = np.min((cumulative - peak) / peak, axis=1)
        drawdown_dist = {
            "p10": float(np.percentile(drawdowns, 10)),
            "p50": float(np.percentile(drawdowns, 50)),
            "p90": float(np.percentile(drawdowns, 90)),
        }

        return {
            "var_95": round(var_95, 6),
            "var_99": round(var_99, 6),
            "cvar_95": round(cvar_95, 6),
            "cvar_99": round(cvar_99, 6),
            "prob_ruin": round(prob_ruin, 6),
            "median_final": round(median_final, 6),
            "drawdown_dist": drawdown_dist,
        }


class MonteCarloVarianceTest:
    """Resampleo bootstrap de trades para obtener CI 95% de Sharpe y max drawdown.

    Diferencia vs MonteCarloSimulator:
      - MonteCarloSimulator: paths de retornos, VaR/CVaR/prob_ruin.
      - MonteCarloVarianceTest: resamplea la lista de trades con reemplazo,
        calcula Sharpe y max drawdown en cada resampleo, retorna IC 95%.

    Uso:
        result = MonteCarloVarianceTest(n_sims=1000, seed=42).run(trade_returns)
        print(result["sharpe_ci_low"], result["sharpe_ci_high"])
    """

    def __init__(
        self,
        n_sims: int = 1000,
        seed: int | None = None,
        confidence: float = 0.95,
        annualize: int = 252,
    ) -> None:
        if n_sims <= 0:
            raise ValueError("n_sims debe ser > 0")
        if not 0 < confidence < 1:
            raise ValueError("confidence debe ser en (0, 1)")
        self.n_sims = n_sims
        self.rng = np.random.default_rng(seed)
        self.confidence = confidence
        self.annualize = annualize

    def run(self, trade_returns: list[float]) -> dict:
        """Resamplea los trades y calcula IC de Sharpe y max drawdown.

        Args:
            trade_returns: Lista de retornos por trade (decimales).

        Returns:
            Dict con:
              - sharpe_ci_low, sharpe_ci_high: IC al confidence% de Sharpe
              - drawdown_ci_low, drawdown_ci_high: IC al confidence% de max DD
              - sharpe_median, drawdown_median: medianas de las distribuciones
              - n_sims: número de simulaciones usadas
        """
        if not trade_returns:
            raise ValueError("trade_returns no puede estar vacío")

        arr = np.array(trade_returns, dtype=float)
        n = len(arr)

        # Bootstrap: resamplear con reemplazo n_sims veces
        idx = self.rng.integers(0, n, size=(self.n_sims, n))
        samples = arr[idx]  # shape (n_sims, n)

        # Calcular Sharpe y max drawdown por cada resampleo
        sharpes = np.array([_sharpe(samples[i], self.annualize) for i in range(self.n_sims)])
        drawdowns = np.array([_max_drawdown(samples[i]) for i in range(self.n_sims)])

        # Percentiles para IC
        alpha = (1.0 - self.confidence) / 2.0
        lo_pct = alpha * 100.0
        hi_pct = (1.0 - alpha) * 100.0

        return {
            "sharpe_ci_low":   float(np.percentile(sharpes, lo_pct)),
            "sharpe_ci_high":  float(np.percentile(sharpes, hi_pct)),
            "sharpe_median":   float(np.median(sharpes)),
            "drawdown_ci_low":  float(np.percentile(drawdowns, lo_pct)),
            "drawdown_ci_high": float(np.percentile(drawdowns, hi_pct)),
            "drawdown_median":  float(np.median(drawdowns)),
            "n_sims": self.n_sims,
        }
