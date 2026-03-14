"""BacktestEngineer — Fase 2.5C: análisis LLM de resultados de paper trading."""
from __future__ import annotations
import json, logging, time

from btquantr.agents.base import BaseAgent, MODEL_MAIN

log = logging.getLogger("BTQUANTRBacktestEngineer")

SYSTEM_PROMPT = """Eres el BacktestEngineer de BTQUANTR, un quant algorítmico senior inspirado en Renaissance Technologies.

Tu rol: analizar resultados de un sistema de paper trading algorítmico e identificar con precisión qué funciona, qué falla y qué cambiar.

RECIBES: informe de analytics institucional (Sharpe, Max DD, Win Rate, Monte Carlo VaR, stress por régimen de mercado).

GENERA un análisis completo con estos campos exactos:

1. verdict: "APROBADO" | "PRECAUCIÓN" | "RECHAZADO"
   - APROBADO: Sharpe ≥ 1.0 Y Win Rate ≥ 40% Y Max DD ≥ -20%
   - PRECAUCIÓN: Sharpe ≥ 0.5 Y Win Rate ≥ 35% Y Max DD ≥ -35%
   - RECHAZADO: cualquier condición peor que PRECAUCIÓN

2. insights: lista de 2-4 observaciones narrativas concretas. Ejemplos:
   - "El sistema tiene edge real en BULL (Sharpe 1.8) pero pierde consistentemente en BEAR."
   - "El Win Rate del 48% es sólido, pero la cola izquierda de pérdidas es larga (VaR -3.2%)."

3. recommendations: lista de 1-5 acciones concretas. Cada elemento:
   {"action": "REDUCE_SIZE|STOP_SYMBOL|ADJUST_KELLY|INCREASE_SIZE|NO_ACTION",
    "target": "<parámetro ConfigManager o símbolo>",
    "from": <valor_actual_o_null>,
    "to": <valor_sugerido_o_null>,
    "reason": "<una frase explicando el por qué>"}

4. suggested_params: dict con solo los parámetros ConfigManager que deben cambiar.
   Parámetros disponibles: sizing_kelly_fraction (0.1-1.0), regime_bull_max_size (5-25),
   regime_bear_max_size (2-15), regime_sideways_max_size (5-20), max_open_positions (1-5).
   Si no hay nada que cambiar: {}

REGLAS:
- Sé específico: usa los números del analytics, no generalidades.
- suggested_params no se aplican automáticamente — son sugerencias para el operador.
- Si el sistema lleva <20 trades, el veredicto debe ser PRECAUCIÓN por muestra insuficiente.

Responde SOLO con JSON válido, sin texto fuera del JSON:
{"verdict":"...","insights":["..."],"recommendations":[{"action":"...","target":"...","from":null,"to":null,"reason":"..."}],"suggested_params":{}}"""


class BacktestEngineer(BaseAgent):
    """Agente que analiza resultados de paper trading con LLM."""

    def __init__(self, r):
        super().__init__(r, MODEL_MAIN)

    def analyze(self, symbol: str) -> dict | None:
        """
        Analiza trades cerrados del paper portfolio.

        Args:
            symbol: Símbolo a analizar (ej: "BTCUSDT") o "ALL" para todos.

        Returns:
            Full report dict, o None si no hay suficientes trades.
        """
        from btquantr.paper_trading.portfolio import PaperPortfolio
        from btquantr.analytics.pipeline import AnalyticsPipeline
        from btquantr.config_manager import ConfigManager

        config = ConfigManager(self.r)
        min_trades = int(config.get("backtest_engineer_min_trades", 10))

        # Obtener historial completo del portfolio
        portfolio = PaperPortfolio(self.r)
        all_trades = portfolio.get_history(limit=500)

        # Filtrar por símbolo si no es "ALL"
        if symbol != "ALL":
            trades = [t for t in all_trades if t.get("symbol") == symbol]
        else:
            trades = all_trades

        if len(trades) < min_trades:
            log.info(
                f"[BacktestEngineer] {symbol}: {len(trades)} trades < {min_trades} mínimo — skip"
            )
            return None

        # Analytics pipeline (matemáticas puras — Fase 2.5B)
        try:
            pipeline = AnalyticsPipeline()
            analytics = pipeline.run(trades)
        except Exception as e:
            log.error(f"[BacktestEngineer] AnalyticsPipeline error para {symbol}: {e}")
            return None

        # Contexto para el LLM
        context = {
            "symbol": symbol,
            "total_trades": len(trades),
            "analytics": analytics,
        }

        result = self._call_claude(SYSTEM_PROMPT, json.dumps(context), max_tokens=1500)

        if "error" in result:
            log.warning(f"[BacktestEngineer] Claude error: {result['error']}")
            return None

        # Enriquecer con metadata
        result["symbol"] = symbol
        result["analyzed_at"] = int(time.time())
        result["total_trades"] = len(trades)
        result["analytics_summary"] = analytics.get("summary", {})

        # Publicar en Redis (TTL 24h)
        key = f"backtest_engineer:report:{symbol}"
        self._pub(key, result)
        self.r.expire(key, 86400)
        self.r.set(f"backtest_engineer:last_run:{symbol}", str(result["analyzed_at"]), ex=86400)

        log.info(
            f"[BacktestEngineer] {symbol}: {result.get('verdict','?')} "
            f"| {len(trades)} trades | report → {key}"
        )
        return result
