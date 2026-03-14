"""ConsistencyAnalyzer — métricas de consistencia para una serie de retornos."""
from __future__ import annotations
import math
import numpy as np


class ConsistencyAnalyzer:
    """Calcula métricas de consistencia institucional sobre retornos diarios."""

    def analyze(self, returns: list[float], annualize_factor: int = 252) -> dict:
        """Analiza retornos y devuelve métricas de consistencia.

        Args:
            returns: Lista de retornos periódicos (decimales, ej: 0.01 = 1%).
            annualize_factor: Períodos por año (252 trading days, 365, 8760h...).

        Returns:
            Dict con: sharpe, sortino, win_rate, profit_factor, max_drawdown,
                      calmar, consistency_score.
        """
        if not returns:
            raise ValueError("returns no puede estar vacío")

        arr = np.array(returns, dtype=float)
        n = len(arr)

        mean = float(np.mean(arr))
        std = float(np.std(arr, ddof=1)) if n > 1 else 0.0
        sqrt_af = math.sqrt(annualize_factor)

        # ── Sharpe ────────────────────────────────────────────────────────────
        sharpe = (mean / std * sqrt_af) if std > 0 else 0.0

        # ── Sortino (downside deviation) ──────────────────────────────────────
        downside = arr[arr < 0]
        downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
        sortino = (mean / downside_std * sqrt_af) if downside_std > 0 else (
            float("inf") if mean > 0 else 0.0
        )

        # ── Win rate ──────────────────────────────────────────────────────────
        win_rate = float(np.sum(arr > 0) / n)

        # ── Profit factor ─────────────────────────────────────────────────────
        gross_profit = float(np.sum(arr[arr > 0]))
        gross_loss = float(abs(np.sum(arr[arr < 0])))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

        # ── Max drawdown ──────────────────────────────────────────────────────
        equity = np.cumprod(1 + arr)
        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / peak
        max_drawdown = float(np.min(drawdown))

        # ── Calmar ────────────────────────────────────────────────────────────
        annualized_return = (1 + mean) ** annualize_factor - 1
        calmar = (
            annualized_return / abs(max_drawdown)
            if max_drawdown < 0
            else float("inf")
        )

        # ── Consistency score (compuesto 0-1) ─────────────────────────────────
        # Combina Sharpe normalizado, win_rate y profit_factor normalizado
        sharpe_norm = min(max(sharpe / 3.0, 0.0), 1.0)     # 3.0 = benchmark excelente
        pf_norm = min(max((profit_factor - 1.0) / 2.0, 0.0), 1.0) if profit_factor != float("inf") else 1.0
        dd_norm = min(max(1.0 + max_drawdown, 0.0), 1.0)    # drawdown negativo penaliza
        consistency_score = float((sharpe_norm + win_rate + pf_norm + dd_norm) / 4.0)

        return {
            "sharpe": round(sharpe, 6),
            "sortino": round(sortino, 6) if math.isfinite(sortino) else sortino,
            "win_rate": round(win_rate, 6),
            "profit_factor": round(profit_factor, 6) if math.isfinite(profit_factor) else profit_factor,
            "max_drawdown": round(max_drawdown, 6),
            "calmar": round(calmar, 6) if math.isfinite(calmar) else calmar,
            "consistency_score": round(consistency_score, 6),
        }
