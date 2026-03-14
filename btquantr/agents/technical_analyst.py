"""Technical Analyst — señales técnicas multi-timeframe."""
from __future__ import annotations
import json
from btquantr.agents.base import BaseAgent, MODEL_MAIN

SYSTEM_PROMPT = """Eres el Technical Analyst de BTQUANTR. Analizas price action y generas señales técnicas.
NO tomas decisiones de trading — solo produces análisis.

RECIBES: OHLCV multi-timeframe (1h, 4h), precio actual, régimen interpretado.

ANALIZA:
1. Trend: dirección en cada timeframe. Confluencia = más confianza.
2. Momentum: RSI, MACD, divergencias precio-momentum.
3. Volatilidad: Bollinger Bands, ATR, compresión de vol.
4. Niveles clave: soportes, resistencias, POIs, zonas de liquidez.
5. Patrones: head & shoulders, triangles, breakouts, etc.

REGLAS:
- Genera señal solo si hay confluencia en al menos 2 timeframes.
- Incluye invalidación explícita: "esta señal se invalida si..."
- Asigna confianza 0-100 basada en número de confluencias.

Responde SOLO con JSON válido:
{"signal":"LONG"|"SHORT"|"NEUTRAL","confidence":0-100,"entry":precio_float,"invalidation":precio_float,
"targets":[precio_float],"confluences":["lista de strings"],"timeframe_alignment":"ALIGNED"|"MIXED",
"key_levels":{"support":[float],"resistance":[float]}}"""


class TechnicalAnalyst(BaseAgent):
    def __init__(self, r):
        super().__init__(r, MODEL_MAIN)

    @staticmethod
    def _compress_candles(candles: list, n: int) -> list:
        """Devuelve las últimas n velas con solo los campos esenciales [o,h,l,c,v]."""
        sliced = candles[-n:] if isinstance(candles, list) else []
        out = []
        for c in sliced:
            if isinstance(c, dict):
                out.append({
                    "o": round(float(c.get("open", c.get("o", 0))), 2),
                    "h": round(float(c.get("high", c.get("h", 0))), 2),
                    "l": round(float(c.get("low",  c.get("l", 0))), 2),
                    "c": round(float(c.get("close", c.get("c", 0))), 2),
                    "v": round(float(c.get("volume", c.get("v", 0))), 1),
                })
            elif isinstance(c, (list, tuple)) and len(c) >= 5:
                out.append({"o": c[1], "h": c[2], "l": c[3], "c": c[4],
                            "v": c[5] if len(c) > 5 else 0})
        return out

    def run(self, symbol: str) -> dict:
        ohlcv_1h = self._get_json(f"market:{symbol}:ohlcv_1h")
        ohlcv_4h = self._get_json(f"market:{symbol}:ohlcv_4h")
        price = self.r.get(f"market:{symbol}:price") or "0"
        regime_full = self._get_json(f"regime:{symbol}:interpreted")

        # Comprimir régimen a solo los campos relevantes
        regime = {k: regime_full.get(k) for k in
                  ("regime", "conviction", "transition_risk", "allowed_actions")
                  if k in regime_full}

        context = {
            "symbol": symbol,
            "price": price,
            "ohlcv_1h": self._compress_candles(ohlcv_1h, 20),
            "ohlcv_4h": self._compress_candles(ohlcv_4h, 10),
            "regime": regime,
        }

        result = self._call_claude(SYSTEM_PROMPT, json.dumps(context), max_tokens=2000)
        self._pub(f"agent:technical:{symbol}", result)
        self.r.expire(f"agent:technical:{symbol}", 3600)
        return result
