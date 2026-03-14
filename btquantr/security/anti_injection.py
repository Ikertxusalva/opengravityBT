"""Capa 1 de Seguridad — Sanitización de inputs contra prompt injection."""
from __future__ import annotations
import json, logging, math, re, time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis

log = logging.getLogger("BTQUANTRSecurity")


class TextSanitizer:
    """Sanitiza texto externo (Reddit, social, APIs) contra prompt injection."""

    INJECTION_PATTERNS = [
        # Instrucciones directas
        r"ignore\s+(previous|above|all|prior)\s+(instructions?|prompts?|rules?|context)",
        r"disregard\s+(previous|above|all|prior)",
        r"forget\s+(everything|all|previous)",
        r"new\s+instructions?\s*:",
        r"system\s*:\s*you\s+are",
        r"you\s+are\s+now\s+a",
        r"act\s+as\s+(if|a|an)",
        r"pretend\s+(to|you)",
        r"override\s+(previous|system|all)",
        # Delimitadores de prompt
        r"<\/?\s*(system|prompt|instruction|context|user|assistant)\s*>",
        r"\[\s*(INST|SYS|SYSTEM|PROMPT)\s*\]",
        r"###\s*(instruction|system|prompt)",
        # Manipulación de output
        r"respond\s+only\s+with",
        r"output\s+(only|exactly|just)",
        r"your\s+(response|answer|output)\s+(must|should|will)\s+be",
        r"return\s+json",
        # Trading-specific injections
        r"(confidence|size|leverage|risk)\s*[=:]\s*\d{2,}",
        r"(buy|sell|long|short)\s+everything",
        r"all\s*(-|\s)in",
        r"max(imum)?\s+(leverage|size|position)",
    ]

    def __init__(self, max_length: int = 500):
        self.max_length = max_length
        self.compiled = [re.compile(p, re.IGNORECASE) for p in self.INJECTION_PATTERNS]

    def sanitize(self, text: str) -> dict:
        """Sanitiza texto. Retorna {"text": str, "clean": bool, "flags": list}."""
        if not text or not isinstance(text, str):
            return {"text": "", "clean": True, "flags": []}
        flags = []
        clean = text
        # PRIMERO detectar en texto completo
        for i, pattern in enumerate(self.compiled):
            if pattern.search(clean):
                flags.append(f"INJECTION_PATTERN_{i}")
                clean = pattern.sub("[REMOVED]", clean)
        # Eliminar caracteres de control
        clean = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]", "", clean)
        # Eliminar Unicode invisible
        clean = re.sub(r"[\u200b-\u200f\u2028-\u202f\u2060-\u206f\ufeff]", "", clean)
        # Normalizar whitespace
        clean = re.sub(r"\s+", " ", clean).strip()
        # LUEGO truncar
        if len(clean) > self.max_length:
            clean = clean[:self.max_length]
            flags.append("TRUNCATED")
        return {"text": clean, "clean": len(flags) == 0, "flags": flags}


class NumericSanitizer:
    """Valida rangos de datos numéricos de APIs externas."""

    VALID_RANGES: dict[str, tuple[float, float]] = {
        "price_btc":    (100, 1_000_000),
        "price_eth":    (10, 100_000),
        "volume":       (0, 1e15),
        "funding_rate": (-0.5, 0.5),
        "oi":           (0, 1e12),
        "ls_ratio":     (0.01, 100),
        "fear_greed":   (0, 100),
        "vix":          (0, 150),
    }

    def validate(self, value, data_type: str) -> dict:
        """Valida un valor numérico. Retorna {"valid": bool, "reason": str|None, "value": float|None}."""
        if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
            return {"valid": False, "reason": "NaN/Inf/None", "value": None}
        try:
            v = float(value)
        except (TypeError, ValueError):
            return {"valid": False, "reason": "not_numeric", "value": None}
        if data_type in self.VALID_RANGES:
            lo, hi = self.VALID_RANGES[data_type]
            if v < lo or v > hi:
                return {"valid": False, "reason": f"out_of_range [{lo}, {hi}]", "value": v}
        return {"valid": True, "reason": None, "value": v}


class ContextSanitizer:
    """Filtro final antes de enviar contexto a Claude API."""

    CONTEXT_INJECTION_PATTERNS = [
        r"ignore.*instructions",
        r"system\s*prompt",
        r"you\s+are\s+now",
        r"<\/?system>",
        r"\[INST\]",
        r"human\s*:",
        r"assistant\s*:",
    ]

    def __init__(self, r=None):
        self.r = r  # Redis opcional para logging
        self.compiled = [re.compile(p, re.IGNORECASE) for p in self.CONTEXT_INJECTION_PATTERNS]

    def sanitize_context(self, context: str) -> dict:
        """Filtra contexto antes de Claude. Retorna {"context": str, "clean": bool, "flags": list}."""
        flags = []
        clean = context
        for i, pattern in enumerate(self.compiled):
            if pattern.search(clean):
                flags.append(f"CONTEXT_INJECTION_{i}")
                clean = pattern.sub("[FILTERED]", clean)
        if flags:
            log.warning(f"Context injection detected: {flags}")
            if self.r:
                try:
                    self.r.xadd("security:context_injection_log", {
                        "flags": json.dumps(flags),
                        "context_length": len(context),
                        "timestamp": str(time.time()),
                    })
                except Exception:
                    pass
        return {"context": clean, "clean": len(flags) == 0, "flags": flags}
