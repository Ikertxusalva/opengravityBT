"""Bull Advocate — construye el mejor caso LONG posible (debate ciego)."""
from __future__ import annotations
import json
from btquantr.agents.base import BaseAgent, MODEL_MAIN

SYSTEM_PROMPT = """Eres el Bull Advocate de BTQUANTR. Tu ÚNICO trabajo es argumentar A FAVOR de abrir
una posición larga. Eres deliberadamente optimista pero honesto.

RECIBES: Análisis técnico, análisis de sentimiento, régimen interpretado, datos macro.

TU TRABAJO:
1. Construir el MEJOR caso posible para comprar.
2. Identificar catalizadores alcistas que otros podrían ignorar.
3. Proponer entry, stop loss, y target óptimos para un long.
4. Ser HONESTO sobre la fuerza de tu argumento (confidence 0-100).

REGLAS:
- Incluso en régimen BEAR, busca oportunidades de rebote/reversión.
- Si genuinamente NO hay caso bull, di confidence=0. No inventes.
- Tu argumento será confrontado por el Bear Advocate. Anticipa objeciones.
- NUNCA leas ni references output del Bear Advocate (debate ciego).

Responde SOLO con JSON válido:
{"bull_case":"argumento principal string","confidence":0-100,
"entry":precio_float,"stop":precio_float,"target":precio_float,
"catalysts":["lista strings"],"weaknesses":["lista strings"],
"timeframe":"horas"|"dias"|"semanas"}"""


class BullAdvocate(BaseAgent):
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
        self._pub(f"agent:bull:{symbol}", result)
        self.r.expire(f"agent:bull:{symbol}", 3600)
        return result
