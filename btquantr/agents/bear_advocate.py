"""Bear Advocate — construye el mejor caso SHORT/HOLD posible (debate ciego)."""
from __future__ import annotations
import json
from btquantr.agents.base import BaseAgent, MODEL_MAIN

SYSTEM_PROMPT = """Eres el Bear Advocate de BTQUANTR. Tu ÚNICO trabajo es argumentar EN CONTRA de
comprar y A FAVOR de vender/no operar. Eres deliberadamente escéptico.

RECIBES: Análisis técnico, sentimiento, régimen, macro.

TU TRABAJO:
1. Encontrar TODOS los riesgos que el Bull ignora.
2. Identificar señales de agotamiento, distribución, o reversión.
3. Proponer entry para short o argumentar cash/HOLD.
4. Ser HONESTO — si el bull case es fuerte, admite confidence bajo.

REGLAS:
- Incluso en régimen BULL, busca riesgos de corrección.
- Si genuinamente NO hay riesgo, di confidence=0.
- Prioriza PRESERVAR CAPITAL sobre ganar dinero.
- NUNCA leas ni references output del Bull Advocate (debate ciego).

Responde SOLO con JSON válido:
{"bear_case":"argumento principal string","confidence":0-100,
"risks":["lista de riesgos especificos"],"short_entry":precio_float_o_null,
"short_stop":precio_float_o_null,
"recommendation":"SHORT"|"HOLD"|"REDUCE_SIZE",
"timeframe":"horas"|"dias"|"semanas"}"""


class BearAdvocate(BaseAgent):
    def __init__(self, r):
        super().__init__(r, MODEL_MAIN)

    def run(self, symbol: str) -> dict:
        technical = self._get_json(f"agent:technical:{symbol}")
        sentiment = self._get_json(f"agent:sentiment:{symbol}")
        regime = self._get_json(f"regime:{symbol}:interpreted")
        macro = self._get_json("macro:markets")

        # ⚠️ DEBATE CIEGO: solo lee inputs propios, nunca el output del adversario

        context = {
            "symbol": symbol,
            "technical": technical,
            "sentiment": sentiment,
            "regime": regime,
            "macro": macro,
        }

        result = self._call_claude(SYSTEM_PROMPT, json.dumps(context), max_tokens=1500)
        self._pub(f"agent:bear:{symbol}", result)
        self.r.expire(f"agent:bear:{symbol}", 3600)
        return result
