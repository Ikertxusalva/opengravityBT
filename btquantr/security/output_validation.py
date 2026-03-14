"""Capa 2 de Seguridad — Validación de outputs de agentes Claude."""
from __future__ import annotations
import json, logging, time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("BTQUANTRSecurity")


@dataclass
class ValidationRule:
    field: str
    type: type
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    allowed_values: Optional[list] = None
    required: bool = True


class AgentOutputValidator:
    """Valida outputs de agentes contra schemas estrictos. Output inválido = DESCARTADO."""

    SCHEMAS: dict[str, list[ValidationRule]] = {
        "dataqualityauditor": [
            ValidationRule("status", str, allowed_values=["CLEAN", "DEGRADED", "BLOCKED"]),
            ValidationRule("symbols_clean", list),
            ValidationRule("symbols_blocked", list),
        ],
        "regimeinterpreter": [
            ValidationRule("regime", str, allowed_values=["BULL", "SIDEWAYS", "BEAR", "TRANSITIONING"]),
            ValidationRule("conviction", str, allowed_values=["HIGH", "MEDIUM", "LOW"]),
            ValidationRule("transition_risk", float, 0.0, 1.0),
            ValidationRule("max_size_pct", float, 0.0, 100.0),
            ValidationRule("max_risk_per_trade", float, 0.0, 2.0),
        ],
        "technicalanalyst": [
            ValidationRule("signal", str, allowed_values=["LONG", "SHORT", "NEUTRAL"]),
            ValidationRule("confidence", float, 0.0, 100.0),
        ],
        "sentimentanalyst": [
            ValidationRule("sentiment", str, allowed_values=[
                "EXTREME_FEAR", "FEAR", "NEUTRAL", "GREED", "EXTREME_GREED"]),
            ValidationRule("confidence", float, 0.0, 100.0),
            ValidationRule("funding_alert", bool),
        ],
        "bulladvocate": [
            ValidationRule("confidence", float, 0.0, 100.0),
            ValidationRule("entry", float, 100.0, 1_000_000.0),
            ValidationRule("stop", float, 100.0, 1_000_000.0),
            ValidationRule("target", float, 100.0, 1_000_000.0),
        ],
        "bearadvocate": [
            ValidationRule("confidence", float, 0.0, 100.0),
            ValidationRule("recommendation", str, allowed_values=["SHORT", "HOLD", "REDUCE_SIZE"]),
        ],
        "riskmanager": [
            ValidationRule("decision", str, allowed_values=["APPROVE", "VETO", "APPROVE_REDUCED"]),
            ValidationRule("approved_size_pct", float, 0.0, 100.0),
            ValidationRule("max_risk_pct", float, 0.0, 2.0),
        ],
        "backtestengineer": [
            ValidationRule("verdict", str, allowed_values=["APROBADO", "PRECAUCIÓN", "RECHAZADO"]),
            ValidationRule("insights", list),
            ValidationRule("recommendations", list),
            ValidationRule("suggested_params", dict),
        ],
    }

    def __init__(self, r=None):
        self.r = r  # Redis opcional para logging

    def validate(self, agent_name: str, output: dict) -> dict:
        """Valida output contra schema. Retorna {"valid": bool, "errors": list}."""
        key = agent_name.lower().replace("_", "")
        schema = self.SCHEMAS.get(key)
        if not schema:
            # Agente sin schema → pass (no bloqueamos agentes no registrados)
            return {"valid": True, "errors": []}

        errors = []
        for rule in schema:
            value = output.get(rule.field)
            if value is None:
                if rule.required:
                    errors.append(f"Missing required field: {rule.field}")
                continue
            # Validar tipo (float acepta int también)
            if rule.type == float:
                if not isinstance(value, (int, float)):
                    errors.append(f"{rule.field}: expected float, got {type(value).__name__}")
                    continue
                v = float(value)
            elif not isinstance(value, rule.type):
                errors.append(f"{rule.field}: expected {rule.type.__name__}, got {type(value).__name__}")
                continue
            else:
                v = value
            # Rango numérico
            if rule.min_val is not None and isinstance(v, (int, float)):
                if v < rule.min_val or v > rule.max_val:
                    errors.append(f"{rule.field}: {v} outside [{rule.min_val}, {rule.max_val}]")
            # Valores permitidos
            if rule.allowed_values is not None and v not in rule.allowed_values:
                errors.append(f"{rule.field}: '{v}' not in {rule.allowed_values}")

        if errors:
            log.error(f"Agent {agent_name} output FAILED validation: {errors}")
            if self.r:
                try:
                    self.r.xadd("security:output_validation_log", {
                        "agent": agent_name,
                        "errors": json.dumps(errors),
                        "output": json.dumps(output)[:500],
                        "timestamp": str(time.time()),
                    })
                except Exception:
                    pass

        return {"valid": len(errors) == 0, "errors": errors}
