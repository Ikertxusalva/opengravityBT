"""22 métricas robustas de backtesting — metodología Renaissance Technologies."""
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Optional, List, Dict
from btquantr.metrics.cost_model import TradeResult


class BacktestMetrics:
    """22 métricas en 4 categorías: rendimiento, riesgo, edge, costes."""

    def __init__(self, returns: pd.Series, trades: Optional[List[TradeResult]] = None,
                 benchmark: Optional[pd.Series] = None,
                 risk_free_rate: float = 0.04, periods_per_year: int = 252):
        self.returns = returns.dropna()
        self.trades = trades or []
        self.benchmark = benchmark
        self.rf = risk_free_rate
        self.ann = periods_per_year

    def compute_all(self) -> Dict:
        r = self.returns
        m: Dict = {}

        # ── RENDIMIENTO ──
        excess = r - self.rf / self.ann
        m["sharpe"] = round(float(excess.mean() / r.std() * np.sqrt(self.ann)) if r.std() > 0 else 0, 3)
        downside = r[r < 0]
        down_std = float(np.sqrt((downside**2).mean())) if len(downside) > 0 else 1e-10
        m["sortino"] = round(float(excess.mean() / down_std * np.sqrt(self.ann)), 3)
        equity = (1 + r).cumprod()
        total_ret = float(equity.iloc[-1] - 1)
        cagr = float(equity.iloc[-1] ** (self.ann / max(len(r), 1)) - 1)
        dd = equity / equity.cummax() - 1
        max_dd = float(dd.min())
        m["calmar"] = round(float(cagr / abs(max_dd)) if max_dd != 0 else 0, 3)
        gains = r[r > 0].sum()
        losses = abs(r[r < 0].sum())
        m["omega"] = round(float(gains / losses) if losses > 0 else 99.0, 3)
        if self.benchmark is not None and len(self.benchmark) == len(r):
            te = (r - self.benchmark).std() * np.sqrt(self.ann)
            m["info_ratio"] = round(float((r.mean() - self.benchmark.mean()) * self.ann / te) if te > 0 else 0, 3)
        else:
            m["info_ratio"] = None

        # ── RIESGO ──
        m["max_drawdown_pct"] = round(max_dd * 100, 2)
        underwater = dd < 0
        m["max_dd_duration"] = int(underwater.groupby((~underwater).cumsum()).sum().max()) if underwater.any() else 0
        m["avg_drawdown_pct"] = round(float(dd[dd < 0].mean()) * 100, 2) if (dd < 0).any() else 0.0
        m["annual_volatility"] = round(float(r.std() * np.sqrt(self.ann)) * 100, 2)
        m["downside_deviation"] = round(float(down_std * np.sqrt(self.ann)) * 100, 2)
        m["var_95"] = round(float(np.percentile(r, 5)) * 100, 3)

        # ── EDGE ──
        if self.trades:
            pnls = [t.pnl_pct for t in self.trades]
            wins = [p for p in pnls if p > 0]
            losses_t = [p for p in pnls if p <= 0]
            m["profit_factor"] = round(sum(wins) / abs(sum(losses_t)) if losses_t and sum(losses_t) != 0 else 99.0, 3)
            m["ev_per_trade"] = round(float(np.mean(pnls)), 5)
            m["win_rate"] = round(len(wins) / len(pnls) * 100, 1) if pnls else 0.0
            avg_w = float(np.mean(wins)) if wins else 0.0
            avg_l = float(abs(np.mean(losses_t))) if losses_t else 1e-10
            m["avg_win_loss_ratio"] = round(avg_w / avg_l, 3)
            m["n_trades"] = len(pnls)
            m["recovery_factor"] = round(total_ret / abs(max_dd), 2) if max_dd != 0 else 0.0
            wr = m["win_rate"] / 100
            m["payoff"] = round(float(wr * avg_w - (1 - wr) * avg_l), 5)
            m["total_commissions"] = round(sum(t.commission for t in self.trades), 4)
            m["total_slippage"] = round(sum(t.slippage for t in self.trades), 4)
            m["total_funding"] = round(sum(t.funding for t in self.trades), 4)
            pnls_post = [t.pnl_pct - (t.commission + t.slippage) / (t.size_usd if t.size_usd > 0 else 1)
                         for t in self.trades]
            r_post = pd.Series(pnls_post)
            m["sharpe_post_costs"] = round(float(r_post.mean() / r_post.std() * np.sqrt(self.ann))
                                           if r_post.std() > 0 else 0, 3)
            m["cost_drag_pct"] = round((1 - m["sharpe_post_costs"] / m["sharpe"]) * 100
                                       if m["sharpe"] > 0 else 0, 1)
        else:
            for k in ["profit_factor", "ev_per_trade", "win_rate", "avg_win_loss_ratio",
                      "n_trades", "recovery_factor", "payoff", "total_commissions",
                      "total_slippage", "total_funding", "sharpe_post_costs", "cost_drag_pct"]:
                m[k] = None

        m["total_return_pct"] = round(total_ret * 100, 2)
        m["cagr_pct"] = round(cagr * 100, 2)
        return m

    def production_verdict(self, m: Optional[Dict] = None) -> str:
        """PASS / MARGINAL / FAIL según criterios Renaissance."""
        if m is None:
            m = self.compute_all()
        sharpe = m.get("sharpe") or 0
        n = m.get("n_trades") or 0
        if sharpe > 1.0 and n > 100:
            return "PASS"
        if sharpe > 0.5 and n > 50:
            return "MARGINAL"
        return "FAIL"
