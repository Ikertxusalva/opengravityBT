"""AnalyticsPipeline — orquesta los módulos analytics sobre trades paper."""
from __future__ import annotations
from btquantr.analytics.consistency import ConsistencyAnalyzer
from btquantr.analytics.montecarlo import MonteCarloSimulator, MonteCarloVarianceTest
from btquantr.analytics.noise_test import NoiseTest
from btquantr.analytics.permutation_test import PermutationTest
from btquantr.analytics.regime_stress import RegimeStress


class AnalyticsPipeline:
    """Corre Consistency + MonteCarlo + RegimeStress sobre una lista de trades
    y produce un informe unificado con veredicto institucional.

    Args:
        mc_n_sims: Número de simulaciones Monte Carlo (default 500).
        mc_seed: Semilla para reproducibilidad (default None = aleatorio).
        annualize: Factor de annualización para Sharpe (default 252).
    """

    VERDICT_THRESHOLDS = {
        "APROBADO":   {"sharpe": 1.0, "win_rate": 0.40, "max_dd": -0.20},
        "PRECAUCIÓN": {"sharpe": 0.5, "win_rate": 0.35, "max_dd": -0.35},
        # Bajo PRECAUCIÓN → RECHAZADO
    }

    def __init__(
        self,
        mc_n_sims: int = 500,
        mc_seed: int | None = None,
        annualize: int = 252,
        n_noise_series: int = 500,
        n_variance_sims: int = 500,
        n_permutations: int = 500,
    ):
        self._consistency = ConsistencyAnalyzer()
        self._mc = MonteCarloSimulator(n_sims=mc_n_sims, seed=mc_seed)
        self._regime = RegimeStress()
        self._noise = NoiseTest(n_series=n_noise_series, seed=mc_seed, annualize=annualize)
        self._variance = MonteCarloVarianceTest(n_sims=n_variance_sims, seed=mc_seed, annualize=annualize)
        self._permutation = PermutationTest(n_permutations=n_permutations, seed=mc_seed, annualize=annualize)
        self._annualize = annualize

    def run(self, trades: list[dict]) -> dict:
        """Analiza una lista de trades cerrados y retorna informe completo.

        Args:
            trades: Lista de dicts con al menos `pnl_pct` (en %, ej: 1.5 = 1.5%)
                    y `regime_at_entry` (str, opcional).

        Returns:
            Dict con claves: consistency, montecarlo, regime_stress, summary.
        """
        if not trades:
            raise ValueError("trades no puede estar vacío")

        # Extraer retornos como fracción decimal (pnl_pct está en %)
        returns = [t["pnl_pct"] / 100.0 for t in trades]
        regimes = [t.get("regime_at_entry", "UNKNOWN") for t in trades]

        consistency = self._consistency.analyze(returns, annualize_factor=self._annualize)
        montecarlo = self._mc.simulate(returns)
        regime_stress = self._regime.analyze(returns, regimes)
        noise_test = self._noise.run(returns)
        variance_test = self._variance.run(returns)
        permutation_test = self._permutation.run(returns)

        verdict = self._verdict(consistency)
        score = consistency.get("consistency_score", 0.0)

        summary = {
            "total_trades": len(trades),
            "verdict": verdict,
            "score": round(score, 4),
            "sharpe": consistency.get("sharpe"),
            "max_drawdown": consistency.get("max_drawdown"),
            "win_rate": consistency.get("win_rate"),
            "var_95": montecarlo.get("var_95"),
            "prob_ruin": montecarlo.get("prob_ruin"),
        }

        return {
            "consistency": consistency,
            "montecarlo": montecarlo,
            "regime_stress": regime_stress,
            "noise_test": noise_test,
            "variance_test": variance_test,
            "permutation_test": permutation_test,
            "summary": summary,
        }

    def _verdict(self, c: dict) -> str:
        sharpe = c.get("sharpe", 0.0)
        win_rate = c.get("win_rate", 0.0)
        max_dd = c.get("max_drawdown", -1.0)

        t = self.VERDICT_THRESHOLDS
        if (
            sharpe >= t["APROBADO"]["sharpe"]
            and win_rate >= t["APROBADO"]["win_rate"]
            and max_dd >= t["APROBADO"]["max_dd"]
        ):
            return "APROBADO"
        elif (
            sharpe >= t["PRECAUCIÓN"]["sharpe"]
            and win_rate >= t["PRECAUCIÓN"]["win_rate"]
            and max_dd >= t["PRECAUCIÓN"]["max_dd"]
        ):
            return "PRECAUCIÓN"
        else:
            return "RECHAZADO"
