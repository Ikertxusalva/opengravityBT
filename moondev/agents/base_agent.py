"""
Base Agent — Clase padre para todos los agentes de trading.
Provee exchange manager unificado, logging y ciclo de vida estándar.
"""

from datetime import datetime
from termcolor import cprint


class BaseAgent:
    def __init__(self, agent_type: str, use_exchange_manager: bool = False):
        self.type = agent_type
        self.start_time = datetime.now()
        self.em = None

        if use_exchange_manager:
            try:
                from moondev.core.exchange_manager import ExchangeManager
                import moondev.config as cfg

                self.em = ExchangeManager()
                self.exchange = cfg.EXCHANGE
                cprint(f"✅ {agent_type} agent initialized with {self.exchange}", "green")
            except Exception as e:
                cprint(f"⚠️ ExchangeManager init failed: {e}", "yellow")
                self.exchange = "hyperliquid"

    def get_active_tokens(self) -> list[str]:
        try:
            from moondev.config import MONITORED_TOKENS
            return MONITORED_TOKENS
        except ImportError:
            return ["BTC", "ETH", "SOL"]

    def run(self):
        """Sobrescribir en cada agente hijo."""
        raise NotImplementedError("Cada agente debe implementar su propio run()")

    def log(self, msg: str, color: str = "white"):
        cprint(f"[{self.type}] {msg}", color)
