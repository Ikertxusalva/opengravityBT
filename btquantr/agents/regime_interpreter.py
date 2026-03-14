"""Regime Interpreter — Agente #2 (Fase 1). Traduce HMM en contexto accionable."""
from __future__ import annotations
import json, logging, time
from typing import Optional, Dict
import redis as redis_lib
from btquantr.agents.base import BaseAgent, MODEL_FAST

log = logging.getLogger("RegimeInterpreter")

SYSTEM_PROMPT = """Eres el Regime Interpreter de BTQUANTR. Traduces la salida numérica del HMM en análisis contextualizado accionable para los agentes de trading.

RECIBES: Estado HMM (BULL/SIDEWAYS/BEAR), probabilidades, confianza, estabilidad, matriz de transición, VIX, DXY, Fear & Greed, y funding rate.

TU TRABAJO:
1. Confirmar o cuestionar la etiqueta del HMM con contexto de mercado.
2. Evaluar la fuerza y madurez del régimen actual.
3. Predecir la probabilidad de transición próxima.
4. Definir reglas de operación para este régimen.

REGLAS:
- Si confianza HMM < 0.6 → conviction: "LOW".
- Si estabilidad < 0.5 → regime: "TRANSITIONING", recomendar no operar.
- Si VIX sube >20% intradía, cuestionar régimen BULL.
- Si funding > 0.05%, alertar squeeze potencial.
- En TRANSITIONING → allowed_actions: ["HOLD"], max_size_pct: 0.

Responde SOLO con JSON válido, sin texto adicional:
{
  "regime": "BULL" | "SIDEWAYS" | "BEAR" | "TRANSITIONING",
  "conviction": "HIGH" | "MEDIUM" | "LOW",
  "maturity": "EARLY" | "MID" | "LATE" | "EXHAUSTION",
  "transition_risk": 0.0,
  "allowed_actions": ["LONG", "SHORT", "HOLD"],
  "max_size_pct": 80,
  "max_risk_per_trade": 2.0,
  "reasoning": "texto breve",
  "warnings": []
}"""


class RegimeInterpreter(BaseAgent):
    """Agente #2: interpreta HMM con contexto macro, publica regime:{SYM}:interpreted."""

    def __init__(self, r: redis_lib.Redis):
        super().__init__(r, model=MODEL_FAST)

    def _is_data_clean(self, symbol: str) -> bool:
        """Gate: verifica que Data Quality Auditor aprobó este símbolo."""
        quality = self._get_json("data:quality_status")
        if not quality:
            return True  # Sin gate aún (sistema arrancando)
        if quality.get("status") == "BLOCKED":
            return False
        approved = self.r.get("data:symbols_approved")
        if approved:
            symbols = json.loads(approved)
            if symbols and symbol not in symbols:
                return False
        return True

    def _build_context(self, symbol: str) -> Dict:
        hmm_raw = self._get_json(f"regime:{symbol}")
        vix_regime = self.r.get("regime:macro:vix") or "UNKNOWN"
        dxy = self.r.get("regime:macro:dxy") or "UNKNOWN"
        yield_curve = self.r.get("regime:macro:yield_curve") or "UNKNOWN"
        fg = self._get_json("sentiment:fear_greed")
        funding = self._get_json(f"derivatives:{symbol}:funding")
        macro = self._get_json("macro:markets")
        return {
            "hmm": hmm_raw, "vix_regime": vix_regime, "dxy": dxy,
            "yield_curve": yield_curve, "fear_greed": fg,
            "funding_last": funding[-1] if isinstance(funding, list) and funding else funding,
            "vix_price": macro.get("VIX", {}).get("price") if macro else None,
        }

    def _fallback_from_hmm(self, symbol: str) -> Dict:
        """Si Claude no disponible, interpreta directamente desde la salida HMM."""
        hmm_raw = self._get_json(f"regime:{symbol}")
        if not hmm_raw:
            return {"regime": "UNKNOWN", "conviction": "LOW", "maturity": "EARLY",
                    "transition_risk": 1.0, "allowed_actions": ["HOLD"],
                    "max_size_pct": 0, "max_risk_per_trade": 0.0,
                    "reasoning": "Sin datos HMM disponibles", "warnings": ["NO_HMM_DATA"]}

        state_name = hmm_raw.get("state_name", "UNKNOWN")
        confidence = float(hmm_raw.get("confidence", 0))
        stability = float(hmm_raw.get("stability", 0))

        if stability < 0.5:
            return {"regime": "TRANSITIONING", "conviction": "LOW", "maturity": "EARLY",
                    "transition_risk": 1 - stability, "allowed_actions": ["HOLD"],
                    "max_size_pct": 0, "max_risk_per_trade": 0.0,
                    "reasoning": f"Régimen inestable (stability={stability:.2f})",
                    "warnings": ["UNSTABLE_REGIME"]}

        SIZE_MAP = {"BULL": 80, "SIDEWAYS": 50, "BEAR": 30}
        RISK_MAP = {"BULL": 2.0, "SIDEWAYS": 1.0, "BEAR": 0.5}
        ACTIONS_MAP = {"BULL": ["LONG", "HOLD"], "SIDEWAYS": ["LONG", "SHORT", "HOLD"], "BEAR": ["SHORT", "HOLD"]}

        conviction = "HIGH" if confidence > 0.8 else ("MEDIUM" if confidence > 0.6 else "LOW")
        return {
            "regime": state_name, "conviction": conviction, "maturity": "MID",
            "transition_risk": round(1 - stability, 3),
            "allowed_actions": ACTIONS_MAP.get(state_name, ["HOLD"]),
            "max_size_pct": SIZE_MAP.get(state_name, 40),
            "max_risk_per_trade": RISK_MAP.get(state_name, 0.5),
            "reasoning": f"HMM: {state_name} conf={confidence:.2f} stab={stability:.2f}",
            "warnings": [] if confidence > 0.6 else ["LOW_CONFIDENCE"],
        }

    def run(self, symbol: str) -> Optional[Dict]:
        """Interpreta régimen para un símbolo. Gate: datos deben estar CLEAN."""
        if not self._is_data_clean(symbol):
            log.warning(f"Gate bloqueado para {symbol}: datos no limpios")
            return None

        if not self._get_json(f"regime:{symbol}"):
            log.debug(f"Sin datos HMM para {symbol} aún")
            return None

        context = self._build_context(symbol)

        try:
            result = self._call_claude(SYSTEM_PROMPT, json.dumps(context), max_tokens=1500)
        except Exception as e:
            log.warning(f"Claude no disponible ({e}), usando fallback directo")
            result = self._fallback_from_hmm(symbol)

        result["timestamp"] = time.time()
        result["symbol"] = symbol
        self._pub(f"regime:{symbol}:interpreted", result)
        self.r.publish("regime_interpreted",
                       json.dumps({"symbol": symbol, "regime": result.get("regime"),
                                   "conviction": result.get("conviction"), "timestamp": result["timestamp"]}))

        if result.get("regime") == "TRANSITIONING":
            log.warning(f"TRANSITIONING detectado para {symbol}: {result.get('reasoning')}")

        return result
