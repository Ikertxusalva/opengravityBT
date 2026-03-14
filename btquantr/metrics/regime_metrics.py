"""Métricas descompuestas por régimen de mercado."""
from __future__ import annotations
import pandas as pd
from typing import Dict, List, Optional
from btquantr.metrics.engine import BacktestMetrics
from btquantr.metrics.cost_model import TradeResult


class RegimeMetrics:
    def __init__(self, returns: pd.Series, regimes: pd.Series,
                 trades: Optional[List[TradeResult]] = None):
        self.returns = returns
        self.regimes = regimes.reindex(returns.index).fillna("UNKNOWN")
        self.trades = trades or []

    def compute_by_regime(self) -> Dict[str, Dict]:
        results = {}
        for name in self.regimes.unique():
            mask = self.regimes == name
            reg_rets = self.returns[mask]
            if len(reg_rets) < 10:
                continue
            reg_trades = [t for t in self.trades if getattr(t, "regime", "") == name]
            m = BacktestMetrics(reg_rets, reg_trades).compute_all()
            m["regime"] = name
            m["pct_time_in_regime"] = round(float(mask.mean()) * 100, 1)
            m["n_periods"] = int(mask.sum())
            results[name] = m
        return results

    def best_regime(self) -> Dict:
        by_r = self.compute_by_regime()
        sharpes = {k: (v["sharpe"] or 0) for k, v in by_r.items()}
        if not sharpes:
            return {"best_regime": None, "worst_regime": None, "recommendation": "Sin datos"}
        best = max(sharpes, key=sharpes.get)
        worst = min(sharpes, key=sharpes.get)
        return {
            "best_regime": best, "best_sharpe": sharpes[best],
            "worst_regime": worst, "worst_sharpe": sharpes[worst],
            "recommendation": (f"Activar en {best}, desactivar en {worst}"
                               if sharpes[worst] < 0 else "Robusto en todos los regímenes"),
        }

    def passes_production_criteria(self) -> bool:
        """True si Sharpe > 0 en al menos 2 de 3 regímenes."""
        by_r = self.compute_by_regime()
        return sum(1 for v in by_r.values() if (v.get("sharpe") or 0) > 0) >= 2
