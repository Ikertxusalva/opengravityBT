"""
PortfolioTracker — log histórico de PnL en CSV.

Uso:
    tracker = PortfolioTracker()
    tracker.set_start(1000)
    tracker.log(current_balance=1050)
    print(tracker.get_pnl())
"""
from __future__ import annotations
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import moondev.config as cfg


class PortfolioTracker:
    COLUMNS = ["timestamp", "balance", "pnl_usd", "pnl_pct", "note"]

    def __init__(self, log_file: Path | None = None):
        self._file = log_file or (cfg.DATA_DIR / "portfolio_history.csv")
        self._file.parent.mkdir(parents=True, exist_ok=True)
        if self._file.exists():
            self._df = pd.read_csv(self._file)
        else:
            self._df = pd.DataFrame(columns=self.COLUMNS)
        self._start: float | None = None

    def set_start(self, balance: float) -> None:
        if self._start is None:
            self._start = balance

    def log(self, balance: float, note: str = "") -> dict:
        if self._start is None:
            self._start = balance
        pnl_usd = balance - self._start
        pnl_pct = (pnl_usd / self._start * 100) if self._start else 0.0
        row = {
            "timestamp": datetime.now().isoformat(),
            "balance": balance,
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "note": note,
        }
        self._df = pd.concat(
            [self._df, pd.DataFrame([row])], ignore_index=True
        )
        self._df.to_csv(self._file, index=False)
        return row

    def get_pnl(self) -> dict:
        if self._df.empty:
            return {"pnl_usd": 0.0, "pnl_pct": 0.0}
        last = self._df.iloc[-1]
        return {"pnl_usd": float(last["pnl_usd"]), "pnl_pct": float(last["pnl_pct"])}

    def get_24h_change(self) -> float:
        if len(self._df) < 2:
            return 0.0
        cutoff = (datetime.now() - timedelta(days=1)).isoformat()
        recent = self._df[self._df["timestamp"] >= cutoff]
        if len(recent) < 2:
            return 0.0
        return float(recent.iloc[-1]["balance"]) - float(recent.iloc[0]["balance"])
