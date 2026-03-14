"""Orchestrator — coordina el ciclo completo de debate Fase 2."""
from __future__ import annotations
import asyncio, json, logging, time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

log = logging.getLogger("BTQUANTROrchestrator")
SYMBOLS = ["BTCUSDT", "ETHUSDT"]


class Orchestrator:
    """Coordina el debate multi-agente completo.

    Flujo:
        Gate 1: DataQualityAuditor (data:quality_status)
        Gate 2: RegimeInterpreter (regime:{SYM}:interpreted != TRANSITIONING)
        Paralelo: TechnicalAnalyst + SentimentAnalyst
        Paralelo ciego: BullAdvocate + BearAdvocate
        Gate 3: RiskManager (APPROVE / VETO / APPROVE_REDUCED)
    """

    def __init__(self, r):
        from btquantr.agents.technical_analyst import TechnicalAnalyst
        from btquantr.agents.sentiment_analyst import SentimentAnalyst
        from btquantr.agents.bull_advocate import BullAdvocate
        from btquantr.agents.bear_advocate import BearAdvocate
        from btquantr.agents.risk_manager import RiskManager
        self.r = r
        self.technical = TechnicalAnalyst(r)
        self.sentiment = SentimentAnalyst(r)
        self.bull = BullAdvocate(r)
        self.bear = BearAdvocate(r)
        self.risk_manager = RiskManager(r)

    def _gate1_data_quality(self, symbol: str) -> bool:
        """Gate 1: calidad de datos aprobada."""
        raw = self.r.get("data:quality_status")
        if not raw:
            return True  # sistema arrancando — permitir
        quality = json.loads(raw)
        if quality.get("status") == "BLOCKED":
            log.warning(f"[{symbol}] Gate 1 BLOCKED: calidad de datos insuficiente")
            return False
        approved = json.loads(self.r.get("data:symbols_approved") or "[]")
        if approved and symbol not in approved:
            log.warning(f"[{symbol}] Gate 1: símbolo no aprobado")
            return False
        return True

    def _gate2_regime(self, symbol: str) -> bool:
        """Gate 2: régimen no es TRANSITIONING."""
        raw = self.r.get(f"regime:{symbol}:interpreted")
        if not raw:
            return True  # sin datos HMM — permitir
        regime = json.loads(raw)
        if regime.get("regime") == "TRANSITIONING":
            log.info(f"[{symbol}] Gate 2: TRANSITIONING — skip ciclo")
            return False
        return True

    async def trading_cycle(self, symbol: str) -> Optional[dict]:
        """Ejecuta un ciclo completo de debate para un símbolo."""
        if not self._gate1_data_quality(symbol):
            return None
        if not self._gate2_regime(symbol):
            return None

        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor(max_workers=2)

        # Análisis en paralelo
        technical, sentiment = await asyncio.gather(
            loop.run_in_executor(executor, self.technical.run, symbol),
            loop.run_in_executor(executor, self.sentiment.run, symbol),
        )
        log.info(f"[{symbol}] Technical: {technical.get('signal')} ({technical.get('confidence')}%)")
        log.info(f"[{symbol}] Sentiment: {sentiment.get('sentiment')}")

        # Debate ciego en paralelo
        bull, bear = await asyncio.gather(
            loop.run_in_executor(executor, self.bull.run, symbol),
            loop.run_in_executor(executor, self.bear.run, symbol),
        )
        log.info(f"[{symbol}] Bull: {bull.get('confidence')}% | Bear: {bear.get('confidence')}%")

        # Gate 3: Risk Manager (secuencial — necesita outputs de ambos)
        risk = self.risk_manager.run(symbol)
        log.info(f"[{symbol}] Risk: {risk.get('decision')} — {str(risk.get('reasoning',''))[:60]}")

        return risk

    async def run_once(self, symbols=None) -> dict:
        """Corre un ciclo para todos los símbolos. Retorna resultados por símbolo."""
        targets = symbols or SYMBOLS

        # Auditar calidad de datos con TODOS los símbolos de una vez,
        # para que data:symbols_approved refleje la lista completa.
        try:
            from btquantr.agents.data_quality_auditor import DataQualityAuditor
            await asyncio.to_thread(DataQualityAuditor(self.r).run, targets)
        except Exception as e:
            log.warning(f"DataQualityAuditor pre-ciclo falló: {e}")

        results = {}
        for symbol in targets:
            try:
                results[symbol] = await self.trading_cycle(symbol)
            except Exception as e:
                log.error(f"[{symbol}] Error en ciclo: {e}", exc_info=True)
                results[symbol] = {"_error": str(e)}
        return results

    async def run(self, symbols=None, interval: int = 3600) -> None:
        """Loop infinito — corre ciclos cada `interval` segundos."""
        log.info("Orchestrator Fase 2 iniciado")
        while True:
            await self.run_once(symbols)
            await asyncio.sleep(interval)
