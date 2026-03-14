"""Valida el HMM con walk-forward backtest + 4 tests estadísticos."""
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Dict
from scipy import stats
from hmmlearn import hmm


def walk_forward_backtest(prices: pd.Series, features_df: pd.DataFrame,
                          n_states: int = 3, train_window: int = 500, step: int = 60) -> pd.DataFrame:
    results = []
    for i in range(train_window, len(features_df), step):
        model = hmm.GaussianHMM(n_components=n_states, covariance_type="full",
                                 n_iter=500, random_state=42)
        train = features_df.iloc[i - train_window:i].values
        mean, std = train.mean(axis=0), train.std(axis=0)
        std[std == 0] = 1
        model.fit((train - mean) / std)
        end = min(i + step, len(features_df))
        test_norm = (features_df.iloc[i:end].values - mean) / std
        states = model.predict(test_norm)
        probs = model.predict_proba(test_norm)
        for j, (s, p) in enumerate(zip(states, probs)):
            idx = i + j
            if idx < len(prices) - 1:
                ret = float((prices.iloc[idx + 1] - prices.iloc[idx]) / prices.iloc[idx])
                results.append({"date": features_df.index[idx], "state": int(s),
                                 "confidence": float(max(p)), "return_next": ret,
                                 "price": float(prices.iloc[idx])})
    return pd.DataFrame(results).set_index("date") if results else pd.DataFrame()


def validate_detector(df: pd.DataFrame) -> Dict:
    if df.empty:
        return {"VERDICT": "FAIL", "reason": "Sin datos"}
    report: Dict = {}
    states = sorted(df["state"].unique())
    groups = [df.loc[df["state"] == s, "return_next"] for s in states]
    if len(groups) >= 2:
        _, p = stats.f_oneway(*groups)
        report["anova_p"] = round(p, 6)
        report["states_different"] = bool(p < 0.05)
    else:
        report["states_different"] = False
    bull = df.groupby("state")["return_next"].mean().idxmax()
    bear = df.groupby("state")["return_next"].mean().idxmin()
    strat = df["return_next"].copy()
    strat[df["state"] == bear] = 0
    bnh, s = df["return_next"], strat
    bnh_sh = float(bnh.mean() / bnh.std() * 252**0.5) if bnh.std() > 0 else 0
    s_sh = float(s.mean() / s.std() * 252**0.5) if s.std() > 0 else 0
    report.update({"bnh_sharpe": round(bnh_sh, 2), "regime_sharpe": round(s_sh, 2),
                   "sharpe_improves": bool(s_sh > bnh_sh)})
    changes = (df["state"] != df["state"].shift()).cumsum()
    dur = df.groupby(changes)["state"].count()
    avg_dur = float(dur.mean())
    report.update({"avg_state_duration": round(avg_dur, 1), "duration_ok": bool(avg_dur > 20)})
    eq_b = (1 + df["return_next"]).cumprod()
    eq_s = (1 + strat).cumprod()
    bnh_dd = float((eq_b / eq_b.cummax() - 1).min()) * 100
    s_dd = float((eq_s / eq_s.cummax() - 1).min()) * 100
    report.update({"bnh_max_dd": round(bnh_dd, 2), "strat_max_dd": round(s_dd, 2),
                   "dd_improves": bool(abs(s_dd) < abs(bnh_dd))})
    passing = [report["states_different"], report["sharpe_improves"],
               report["duration_ok"], report["dd_improves"]]
    report["tests_passed"] = sum(passing)
    report["VERDICT"] = "PASS" if sum(passing) >= 3 else "NEEDS_WORK"
    return report


class WalkForwardValidator:
    """OOP interface para walk-forward validation del HMM de régimen.

    Wraps walk_forward_backtest() y validate_detector() en una interfaz
    unificada consistente con WalkForwardOptimizer (btquantr/analytics/).
    """

    def __init__(self, train_window: int = 500, step: int = 60, n_states: int = 3):
        self.train_window = train_window
        self.step = step
        self.n_states = n_states

    def run(self, prices: pd.Series, features_df: pd.DataFrame) -> pd.DataFrame:
        """Ejecuta walk-forward backtest. Retorna DataFrame con resultados por estado."""
        return walk_forward_backtest(
            prices, features_df,
            n_states=self.n_states,
            train_window=self.train_window,
            step=self.step,
        )

    def validate(self, results: pd.DataFrame) -> Dict:
        """Valida resultados del walk-forward con 4 tests estadísticos."""
        return validate_detector(results)
