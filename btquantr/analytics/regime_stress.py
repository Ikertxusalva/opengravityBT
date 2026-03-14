"""RegimeStress — métricas de performance por régimen HMM."""
from __future__ import annotations
import math
from collections import defaultdict
import numpy as np


def _regime_sharpe(arr: np.ndarray, annualize: int = 252) -> float:
    if len(arr) < 2:
        return 0.0
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))
    return (mean / std * math.sqrt(annualize)) if std > 0 else 0.0


class RegimeStress:
    """Analiza performance de una estrategia desagregada por régimen HMM."""

    def analyze(
        self,
        returns: list[float],
        regimes: list[str],
        annualize: int = 252,
    ) -> dict:
        """Desagrega retornos por régimen y calcula métricas por grupo.

        Args:
            returns: Retornos periódicos.
            regimes: Etiqueta de régimen para cada período (misma longitud).
            annualize: Factor de annualización para Sharpe.

        Returns:
            Dict con: by_regime (dict régimen→métricas), summary, stress_score.
        """
        if not returns:
            raise ValueError("returns no puede estar vacío")
        if len(returns) != len(regimes):
            raise AssertionError(f"returns ({len(returns)}) y regimes ({len(regimes)}) deben tener la misma longitud")

        arr = np.array(returns, dtype=float)

        # Agrupar índices por régimen
        groups: dict[str, list[int]] = defaultdict(list)
        for i, r in enumerate(regimes):
            groups[r].append(i)

        by_regime: dict[str, dict] = {}
        for regime, indices in groups.items():
            subset = arr[indices]
            mean_ret = float(np.mean(subset))
            vol = float(np.std(subset, ddof=1)) if len(subset) > 1 else 0.0
            sharpe = _regime_sharpe(subset, annualize)
            by_regime[regime] = {
                "sharpe": round(sharpe, 4),
                "mean_return": round(mean_ret, 6),
                "volatility": round(vol, 6),
                "n_periods": len(indices),
            }

        # ── Summary ────────────────────────────────────────────────────────────
        if by_regime:
            best_regime = max(by_regime, key=lambda r: by_regime[r]["mean_return"])
            worst_regime = min(by_regime, key=lambda r: by_regime[r]["mean_return"])
        else:
            best_regime = worst_regime = None

        summary = {
            "best_regime": best_regime,
            "worst_regime": worst_regime,
            "n_regimes": len(by_regime),
        }

        # ── Stress score (0=sin estrés, 1=máximo estrés) ───────────────────────
        # Comparar BEAR_HIGH vs BULL_HIGH. Si BEAR es muy negativo → estrés alto.
        bull_mean = by_regime.get("BULL_HIGH", {}).get("mean_return", 0.0)
        bear_mean = by_regime.get("BEAR_HIGH", {}).get("mean_return", 0.0)
        spread = bull_mean - bear_mean  # cuánto mejor es BULL vs BEAR
        # Normalizar: si spread=0 → 0.5, si spread muy positivo → 0 (sin estrés en BEAR)
        stress_score = float(min(max(0.5 - spread * 10, 0.0), 1.0))

        return {
            "by_regime": by_regime,
            "summary": summary,
            "stress_score": round(stress_score, 4),
        }
