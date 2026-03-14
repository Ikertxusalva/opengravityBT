"""Agentes Claude de BTQUANTR — Fase 1 + Fase 2."""
from btquantr.agents.data_quality_auditor import DataQualityAuditor
from btquantr.agents.regime_interpreter import RegimeInterpreter
from btquantr.agents.technical_analyst import TechnicalAnalyst
from btquantr.agents.sentiment_analyst import SentimentAnalyst
from btquantr.agents.bull_advocate import BullAdvocate
from btquantr.agents.bear_advocate import BearAdvocate
from btquantr.agents.risk_manager import RiskManager
from btquantr.agents.orchestrator import Orchestrator

__all__ = [
    "DataQualityAuditor", "RegimeInterpreter",
    "TechnicalAnalyst", "SentimentAnalyst",
    "BullAdvocate", "BearAdvocate",
    "RiskManager", "Orchestrator",
]
