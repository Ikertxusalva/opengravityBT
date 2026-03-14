"""PaperPortfolio — posiciones virtuales con comisión + slippage reales."""
from __future__ import annotations
import json, logging, time
from datetime import datetime
from typing import Optional

from btquantr.config_manager import ConfigManager

log = logging.getLogger("BTQUANTRPaper")

STATE_KEY = "paper:portfolio:state"
HISTORY_STREAM = "paper:trades:history"
BALANCE_KEY = "paper:portfolio:balance"


class PaperPortfolio:
    """Portfolio virtual. Simula comisión (0.04%) + slippage (2bps) por trade."""

    def __init__(self, r):
        self.r = r
        self.config = ConfigManager(r)

    # ─── Balance ──────────────────────────────────────────────────────────────

    def get_balance(self) -> float:
        raw = self.r.get(BALANCE_KEY)
        if raw:
            return float(raw)
        initial = self.config.get("initial_balance", 10_000.0)
        self.r.set(BALANCE_KEY, str(initial))
        return initial

    def _update_balance(self, delta: float) -> float:
        new_balance = self.get_balance() + delta
        self.r.set(BALANCE_KEY, str(new_balance))
        return new_balance

    # ─── Positions ────────────────────────────────────────────────────────────

    def get_state(self) -> dict:
        """Devuelve todas las posiciones abiertas como {symbol: position_dict}."""
        raw = self.r.get(STATE_KEY)
        return json.loads(raw) if raw else {}

    def _save_state(self, state: dict) -> None:
        self.r.set(STATE_KEY, json.dumps(state))

    def open_position(
        self,
        symbol: str,
        side: str,
        size_pct: float,
        leverage: float,
        entry_price: float,
        regime: str,
    ) -> Optional[dict]:
        """Abre una posición paper. Retorna la posición o None si ya existe."""
        state = self.get_state()
        if symbol in state:
            log.warning(f"[{symbol}] Ya hay posición abierta — ignorando señal")
            return None

        balance = self.get_balance()
        size_usd = balance * size_pct

        pos = {
            "symbol": symbol,
            "side": side,
            "size_pct": size_pct,
            "size_usd": round(size_usd, 2),
            "leverage": leverage,
            "entry_price": entry_price,
            "regime_at_entry": regime,
            "opened_at": int(time.time()),
        }
        state[symbol] = pos
        self._save_state(state)
        log.info(f"[{symbol}] Posición abierta: {side} ${size_usd:.0f} @ {entry_price}")
        return pos

    def close_position(
        self,
        symbol: str,
        exit_price: float,
        reason: str,
    ) -> Optional[dict]:
        """Cierra una posición. Calcula PnL neto (comisión + slippage). Retorna trade dict."""
        state = self.get_state()
        pos = state.pop(symbol, None)
        if pos is None:
            return None

        commission_pct = self.config.get("commission_pct", 0.04) / 100
        slippage_bps = self.config.get("slippage_bps", 2)
        size_usd = pos["size_usd"]

        # PnL bruto
        price_change_pct = (exit_price - pos["entry_price"]) / pos["entry_price"]
        if pos["side"] == "SHORT":
            price_change_pct = -price_change_pct
        gross_pnl_usd = size_usd * price_change_pct * pos["leverage"]

        # Costes (round-trip: entry + exit)
        commission_usd = size_usd * commission_pct * 2   # entry + exit
        slippage_usd = size_usd * (slippage_bps / 10_000) * 2   # entry + exit
        net_pnl_usd = gross_pnl_usd - commission_usd - slippage_usd

        # PnL % sobre el capital asignado a la posición (retorno sobre posición, no sobre balance)
        pnl_pct = (net_pnl_usd / size_usd) * 100 if size_usd else 0

        now = int(time.time())
        trade = {
            **pos,
            "exit_price": exit_price,
            "gross_pnl_usd": round(gross_pnl_usd, 4),
            "commission_usd": round(commission_usd, 4),
            "slippage_usd": round(slippage_usd, 4),
            "net_pnl_usd": round(net_pnl_usd, 4),
            "pnl_pct": round(pnl_pct, 4),
            "closed_at": now,
            "closed_at_str": datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M"),
            "reason": reason,
        }

        # Persistir
        self._save_state(state)
        self._update_balance(net_pnl_usd)
        self.r.xadd(HISTORY_STREAM, {k: json.dumps(v) for k, v in trade.items()})
        log.info(f"[{symbol}] Posición cerrada: {reason} | PnL ${net_pnl_usd:.2f}")
        return trade

    # ─── History & Metrics ────────────────────────────────────────────────────

    def get_history(self, limit: int = 100) -> list[dict]:
        """Devuelve los últimos `limit` trades cerrados."""
        entries = self.r.xrevrange(HISTORY_STREAM, "+", "-", count=limit)
        trades = []
        for _id, fields in entries:
            trade = {k: json.loads(v) for k, v in fields.items()}
            trades.append(trade)
        return list(reversed(trades))

    def get_metrics(self) -> dict:
        """Métricas básicas sobre el historial de trades."""
        import numpy as np
        trades = self.get_history(limit=10_000)
        if not trades:
            return {"status": "NO_TRADES", "total_trades": 0}

        net_pnls = [t["net_pnl_usd"] for t in trades]
        pnl_pcts = [t["pnl_pct"] / 100 for t in trades]  # como fracción
        wins = [p for p in net_pnls if p > 0]
        losses = [p for p in net_pnls if p <= 0]

        arr = np.array(pnl_pcts)
        # Sharpe anualizado asumiendo trades de frecuencia diaria (252 días/año).
        # Sobreestima si los trades son intraday, subestima si son semanales/mensuales.
        sharpe = float(np.mean(arr) / np.std(arr) * np.sqrt(252)) if np.std(arr) > 0 else 0.0

        # Max DD
        cumulative = np.cumprod(1 + arr)
        peak = np.maximum.accumulate(cumulative)
        dd = (cumulative - peak) / peak
        max_dd = float(np.min(dd)) * 100

        profit_factor = (
            abs(sum(wins)) / abs(sum(losses))
            if losses and sum(losses) != 0 else float("inf")
        )

        return {
            "total_trades": len(trades),
            "win_rate": round(len(wins) / len(trades) * 100, 1),
            "profit_factor": round(profit_factor, 2),
            "sharpe": round(sharpe, 2),
            "max_dd_pct": round(max_dd, 2),
            "total_pnl_usd": round(sum(net_pnls), 2),
            "current_balance": round(self.get_balance(), 2),
        }

    def get_analytics(self) -> dict:
        """Informe institucional completo usando AnalyticsPipeline (2.5B)."""
        from btquantr.analytics.pipeline import AnalyticsPipeline
        trades = self.get_history(limit=10_000)
        if not trades:
            return {"status": "NO_TRADES", "total_trades": 0}
        return AnalyticsPipeline().run(trades)

    def reset(self, initial_balance: float) -> None:
        """Resetea portfolio: elimina posiciones abiertas, historial y restaura balance."""
        self.r.delete(STATE_KEY)
        self.r.delete(HISTORY_STREAM)
        self.r.set(BALANCE_KEY, str(initial_balance))
        log.warning(f"Portfolio reseteado — balance inicial: ${initial_balance:,.0f}")
