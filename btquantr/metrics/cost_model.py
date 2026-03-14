"""Modelo de costes reales: comisiones + slippage + funding."""
from dataclasses import dataclass
from typing import Dict


@dataclass
class TradeResult:
    entry_price: float
    exit_price: float
    size_usd: float
    holding_hours: float = 0.0
    is_maker: bool = False
    direction: str = "LONG"
    regime: str = "UNKNOWN"
    commission: float = 0.0
    slippage: float = 0.0
    funding: float = 0.0

    @property
    def pnl_pct(self) -> float:
        if self.direction == "LONG":
            return (self.exit_price - self.entry_price) / self.entry_price
        return (self.entry_price - self.exit_price) / self.entry_price


class CostModel:
    CONFIGS = {
        "crypto": {"maker_fee": 0.0002, "taker_fee": 0.0004,
                   "slippage_base": 0.0001, "slippage_impact": 0.00005, "funding_avg": 0.0001},
        "stocks": {"maker_fee": 0.0, "taker_fee": 0.0001,
                   "slippage_base": 0.0002, "slippage_impact": 0.0001, "funding_avg": 0.0},
    }

    def __init__(self, market: str = "crypto"):
        self.cfg = self.CONFIGS.get(market, self.CONFIGS["crypto"])

    def calculate(self, trade: TradeResult) -> Dict[str, float]:
        fee = self.cfg["maker_fee"] if trade.is_maker else self.cfg["taker_fee"]
        commission = trade.size_usd * fee * 2
        slip_pct = self.cfg["slippage_base"] + self.cfg["slippage_impact"] * (trade.size_usd / 10_000)
        slippage = trade.size_usd * slip_pct * 2
        funding = trade.size_usd * self.cfg["funding_avg"] * (trade.holding_hours / 8)
        total = commission + slippage + abs(funding)
        return {
            "commission": round(commission, 6),
            "slippage": round(slippage, 6),
            "funding": round(funding, 6),
            "total_cost": round(total, 6),
            "cost_pct": round(total / trade.size_usd * 100, 4) if trade.size_usd > 0 else 0,
        }
