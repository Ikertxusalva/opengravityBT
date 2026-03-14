"""Data Quality Auditor — Agente #1 (Fase 1). Gate de calidad de datos."""
from __future__ import annotations
import json, logging, time
from typing import Dict, List
import redis as redis_lib
from btquantr.agents.base import BaseAgent, MODEL_FAST

log = logging.getLogger("DataQualityAuditor")

SYSTEM_PROMPT = """Eres el Data Quality Auditor de BTQUANTR. Tu ÚNICA responsabilidad es evaluar la calidad de los datos de mercado y decidir si son aptos para uso.

RECIBES: Reportes de limpieza del pipeline (7 detectores) con pct_clean por activo y anomalías detectadas.

REGLAS ABSOLUTAS:
- Si pct_clean < 0.95 para un activo → BLOCKED ese activo.
- Si hay anomalías "critical" sin resolver → BLOCKED.
- Si gap temporal > 30 minutos en crypto → ALERTAR.
- Si pct_clean >= 0.95 y no hay críticos → CLEAN.
- Si pct_clean 0.90-0.95 → DEGRADED (funciona pero con warning).

Responde SOLO con JSON válido, sin texto adicional:
{
  "status": "CLEAN" | "DEGRADED" | "BLOCKED",
  "symbols_clean": ["BTCUSDT", ...],
  "symbols_blocked": [],
  "issues": ["descripción de problemas"],
  "recommendation": "texto breve",
  "timestamp": 0
}"""


class DataQualityAuditor(BaseAgent):
    """Agente #1: valida calidad de datos, publica data:quality_status."""

    def __init__(self, r: redis_lib.Redis):
        super().__init__(r, model=MODEL_FAST)
        self.symbols: List[str] = []

    def _build_context(self) -> Dict:
        reports = {}
        for sym in self.symbols:
            raw = self.r.get(f"market:{sym}:cleaning_report")
            if raw:
                reports[sym] = json.loads(raw)
        return reports

    def _fallback_from_redis(self) -> Dict:
        """Si Claude no está disponible, evalúa directamente los reportes."""
        reports = self._build_context()
        symbols_clean, symbols_blocked, issues = [], [], []

        for sym, report in reports.items():
            pct = report.get("pct_clean", 0)
            n_crit = report.get("n_critical", 0)
            if pct >= 0.95 and n_crit == 0:
                symbols_clean.append(sym)
            else:
                symbols_blocked.append(sym)
                issues.append(f"{sym}: pct_clean={pct:.2%}, critical={n_crit}")

        if not reports:
            return {"status": "CLEAN", "symbols_clean": self.symbols,
                    "symbols_blocked": [], "issues": [], "recommendation": "Sin datos de limpieza aún",
                    "timestamp": time.time()}

        status = "BLOCKED" if symbols_blocked else "CLEAN"
        return {"status": status, "symbols_clean": symbols_clean,
                "symbols_blocked": symbols_blocked, "issues": issues,
                "recommendation": "Verificar fuentes de datos" if symbols_blocked else "Datos OK",
                "timestamp": time.time()}

    def run(self, symbols: List[str]) -> Dict:
        """Evalúa calidad de datos para los símbolos dados."""
        self.symbols = symbols
        reports = self._build_context()

        if not reports:
            # Sin cleaning_report en Redis → pipeline aún no ha publicado métricas
            result = self._fallback_from_redis()
        else:
            try:
                result = self._call_claude(SYSTEM_PROMPT, json.dumps(reports), max_tokens=1500)
            except Exception as e:
                log.warning(f"Claude no disponible ({e}), usando fallback directo")
                result = self._fallback_from_redis()

        result["timestamp"] = time.time()
        self._pub("data:quality_status", result)
        self._pub("data:symbols_approved", result.get("symbols_clean", []))

        if result["status"] == "BLOCKED":
            self.r.publish("alerts", json.dumps(
                {"source": "data_quality", "status": "BLOCKED",
                 "issues": result.get("issues", []), "timestamp": time.time()}))
            log.warning(f"DATOS BLOQUEADOS: {result.get('issues')}")
        else:
            log.info(f"Data Quality: {result['status']} — {result.get('symbols_clean', [])} limpios")

        return result
