"""Risk Manager — gate final con veto absoluto y circuit breakers."""
from __future__ import annotations
import json, time
from btquantr.agents.base import BaseAgent, MODEL_MAIN

SYSTEM_PROMPT = """Eres el Risk Manager de BTQUANTR. Tienes la ÚLTIMA PALABRA sobre cada trade.
Tu prioridad #1 es PRESERVAR CAPITAL. Eres conservador por diseño.

RECIBES: Caso Bull, caso Bear, régimen interpretado, estado del portfolio.

REGLAS DE RIESGO ABSOLUTAS (no negociables):
- Max riesgo por trade: BULL=2%, SIDEWAYS=1%, BEAR=0.5%.
- Max posiciones abiertas simultáneas: 3.
- Max drawdown diario: 5%. Si se alcanza, STOP ALL.
- Régimen TRANSITIONING => VETO automático.
- Confianza del régimen < 0.5 => reducir size 50%.
- Si Bull Y Bear tienen confidence > 70 => HOLD (mercado confuso).

Responde SOLO con JSON válido:
{"decision":"APPROVE"|"VETO"|"APPROVE_REDUCED","approved_size_pct":0-100,
"max_risk_pct":float,"reasoning":"string explicando decision",
"conditions":["lista strings"],"portfolio_risk_after":float,
"veto_reason":"string si aplica o null"}"""

MAX_RISK = {"BULL": 2.0, "SIDEWAYS": 1.0, "BEAR": 0.5, "TRANSITIONING": 0.0}


class RiskManager(BaseAgent):
    def __init__(self, r):
        super().__init__(r, MODEL_MAIN)

    def run(self, symbol: str) -> dict:
        bull = self._get_json(f"agent:bull:{symbol}")
        bear = self._get_json(f"agent:bear:{symbol}")
        regime = self._get_json(f"regime:{symbol}:interpreted")
        portfolio = self._get_json("risk:status")
        open_orders = self.r.hgetall("execution:orders") or {}

        # ── VETOS AUTOMÁTICOS (sin llamar a Claude) ──────────────────────────
        if regime.get("regime") == "TRANSITIONING":
            return self._veto("regime TRANSITIONING — no operar", symbol)

        daily_dd = portfolio.get("daily_dd_pct", 0)
        if isinstance(daily_dd, (int, float)) and daily_dd >= 5.0:
            self.r.publish("execution:commands",
                           json.dumps({"action": "STOP_ALL", "reason": "daily DD 5% hit"}))
            return self._veto("daily drawdown 5% alcanzado — STOP ALL", symbol)

        if len(open_orders) >= 3:
            return self._veto("max 3 posiciones abiertas simultáneas", symbol)

        bull_conf = bull.get("confidence", 0) if isinstance(bull, dict) else 0
        bear_conf = bear.get("confidence", 0) if isinstance(bear, dict) else 0
        if bull_conf > 70 and bear_conf > 70:
            return self._veto("bull y bear ambos >70% — mercado confuso, HOLD", symbol)

        # ── DECISIÓN CLAUDE ──────────────────────────────────────────────────
        context = {
            "bull": bull,
            "bear": bear,
            "regime": regime,
            "portfolio": portfolio,
            "open_positions": len(open_orders),
        }

        result = self._call_claude(SYSTEM_PROMPT, json.dumps(context), max_tokens=1500)
        self._pub(f"agent:risk_decision:{symbol}", result)
        self.r.expire(f"agent:risk_decision:{symbol}", 3600)

        if result.get("decision") == "APPROVE":
            self.r.publish("agent:signals",
                           json.dumps({"symbol": symbol, "decision": result, "ts": time.time()}))
        return result

    def _veto(self, reason: str, symbol: str) -> dict:
        result = {
            "decision": "VETO",
            "veto_reason": reason,
            "approved_size_pct": 0,
            "max_risk_pct": 0.0,
            "reasoning": reason,
            "conditions": [],
            "portfolio_risk_after": 0.0,
        }
        self._pub(f"agent:risk_decision:{symbol}", result)
        self.r.expire(f"agent:risk_decision:{symbol}", 3600)
        return result
