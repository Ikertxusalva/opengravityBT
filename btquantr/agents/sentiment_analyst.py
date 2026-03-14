"""Sentiment Analyst — interpreta estado emocional del mercado."""
from __future__ import annotations
import json, time
from btquantr.agents.base import BaseAgent, MODEL_MAIN

SYSTEM_PROMPT = """Eres el Sentiment Analyst de BTQUANTR. Interpretas el estado emocional del mercado.
Tu edge es detectar EXTREMOS de sentimiento que preceden reversiones.

ANALIZA:
1. Fear & Greed: <20 = extreme fear (contrarian bullish), >80 = extreme greed (contrarian bearish).
2. Funding: rate > 0.05% = longs sobreextendidos. < -0.03% = shorts squeeze potencial.
3. L/S ratio: extremos = crowding peligroso.
4. Social volume: spikes = FOMO o pánico. Divergencia precio-sentimiento = señal fuerte.

REGLAS:
- Busca DIVERGENCIAS entre precio y sentimiento (la señal más valiosa).
- Extremos de sentimiento son contrarian.
- Nunca trades solo por sentimiento. Es confirmación, no señal primaria.

Responde SOLO con JSON válido:
{"sentiment":"EXTREME_FEAR"|"FEAR"|"NEUTRAL"|"GREED"|"EXTREME_GREED",
"contrarian_signal":"LONG"|"SHORT"|"NONE","confidence":0-100,
"divergences":["lista de strings"],"funding_alert":true|false,
"crowd_position":"LONG"|"SHORT"|"BALANCED"}"""


class SentimentAnalyst(BaseAgent):
    def __init__(self, r):
        super().__init__(r, MODEL_MAIN)

    def run(self, symbol: str) -> dict:
        fear_greed = self._get_json("sentiment:fear_greed")
        funding = self._get_json(f"derivatives:{symbol}:funding")
        long_short = self._get_json(f"derivatives:{symbol}:long_short")

        context = {
            "symbol": symbol,
            "fear_greed": fear_greed,
            "funding_last": funding[-1] if isinstance(funding, list) and funding else None,
            "long_short": long_short[-1] if isinstance(long_short, list) and long_short else None,
        }

        result = self._call_claude(SYSTEM_PROMPT, json.dumps(context), max_tokens=1500)
        self._pub(f"agent:sentiment:{symbol}", result)
        self.r.expire(f"agent:sentiment:{symbol}", 900)

        if result.get("sentiment") in ("EXTREME_FEAR", "EXTREME_GREED"):
            self.r.publish("alerts", json.dumps({
                "source": "sentiment_analyst", "symbol": symbol,
                "sentiment": result["sentiment"], "ts": time.time(),
            }))
        return result
