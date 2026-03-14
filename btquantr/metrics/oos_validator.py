"""Validación out-of-sample con split temporal 70/30."""
from __future__ import annotations
import pandas as pd
from typing import Dict, List, Optional, Tuple
from btquantr.metrics.engine import BacktestMetrics
from btquantr.metrics.cost_model import TradeResult


class OOSValidator:
    VERDICTS = {
        "PASS": "Estrategia robusta — Sharpe OOS > 0.5 y degradación < 30%",
        "MARGINAL": "Degradación aceptable — monitorear con capital reducido",
        "FAIL": "Overfitting detectado — no apta para producción",
    }

    def __init__(self, train_pct: float = 0.7):
        self.train_pct = train_pct

    def split(self, returns: pd.Series) -> Tuple[pd.Series, pd.Series]:
        idx = int(len(returns) * self.train_pct)
        return returns.iloc[:idx], returns.iloc[idx:]

    def validate(self, returns_in: pd.Series, returns_out: pd.Series,
                 trades_in: Optional[List[TradeResult]] = None,
                 trades_out: Optional[List[TradeResult]] = None) -> Dict:
        bm_in = BacktestMetrics(returns_in, trades_in).compute_all()
        bm_out = BacktestMetrics(returns_out, trades_out).compute_all()
        degradation: Dict = {}
        for k in ["sharpe", "sortino", "calmar", "win_rate", "max_drawdown_pct"]:
            vi, vo = bm_in.get(k), bm_out.get(k)
            if vi is not None and vo is not None and vi != 0:
                deg = (abs(vo) - abs(vi)) / abs(vi) * 100 if k == "max_drawdown_pct" else (vo - vi) / abs(vi) * 100
                degradation[k] = round(deg, 1)
        sharpe_out = bm_out.get("sharpe") or 0
        sharpe_deg = degradation.get("sharpe", -100)
        if sharpe_out > 0.5 and sharpe_deg > -30:
            verdict = "PASS"
        elif sharpe_out > 0 and sharpe_deg > -50:
            verdict = "MARGINAL"
        else:
            verdict = "FAIL"
        return {"in_sample": bm_in, "out_of_sample": bm_out,
                "degradation": degradation, "verdict": verdict,
                "verdict_detail": self.VERDICTS[verdict]}
