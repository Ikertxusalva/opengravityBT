"""Base class para agentes Claude de BTQUANTR."""
from __future__ import annotations
import json, logging, time
import anthropic
import redis as redis_lib
from dotenv import load_dotenv

# Carga ANTHROPIC_API_KEY (y demás vars) desde .env si aún no está en el entorno
load_dotenv(override=False)
from btquantr.security.anti_injection import ContextSanitizer
from btquantr.security.output_validation import AgentOutputValidator
from btquantr.security.rate_limiter import ClaudeRateLimiter

from btquantr.monitoring import stats as _stats

log = logging.getLogger("BTQUANTRAgent")
MODEL_FAST = "claude-haiku-4-5-20251001"
MODEL_MAIN = "claude-sonnet-4-6"

# Instancias globales de seguridad (compartidas entre todos los agentes)
_ctx_sanitizer = ContextSanitizer()
_output_validator = AgentOutputValidator()
_rate_limiter = ClaudeRateLimiter()


def init_rate_limiter_redis(r: redis_lib.Redis) -> None:
    """Inyecta Redis en el rate limiter global para persistir contadores entre reinicios."""
    global _rate_limiter
    _rate_limiter = ClaudeRateLimiter(redis_client=r)
    log.info("[RateLimiter] Redis persistence enabled")


class BaseAgent:
    """Agente Claude base: lee de Redis, llama API, escribe en Redis."""

    def __init__(self, r: redis_lib.Redis, model: str = MODEL_FAST):
        self.r = r
        self.model = model
        self._client = None  # lazy init
        self.name = self.__class__.__name__

    @property
    def client(self):
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def _call_claude(self, system: str, user_content: str, max_tokens: int = 500,
                     _truncation_retry: bool = False) -> dict:
        """Llama a Claude con defensa en profundidad: rate limit → sanitización → validación.

        Si Claude trunca el JSON (stop_reason=max_tokens), reintenta una sola vez
        con max_tokens duplicado antes de propagar el error.
        """
        # Capa 6: Rate limit check
        check = _rate_limiter.check(self.name, self.model)
        if not check["allowed"]:
            log.warning(f"[{self.name}] Rate limit: {check['reason']}")
            return {"error": check["reason"]}

        # Capa 1: Sanitizar contexto
        sanitized = _ctx_sanitizer.sanitize_context(user_content)
        if not sanitized["clean"]:
            log.warning(f"[{self.name}] Context injection detected: {sanitized['flags']}")

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": sanitized["context"]}],
            )
            text = response.content[0].text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            try:
                output = json.loads(text)
            except json.JSONDecodeError:
                # JSON truncado: si stop_reason indica que se agotaron los tokens,
                # reintentar una vez con el doble de espacio (solo 1 reintento)
                if response.stop_reason == "max_tokens" and not _truncation_retry:
                    log.warning(
                        f"[{self.name}] JSON truncado (max_tokens={max_tokens}, "
                        f"stop=max_tokens) — reintentando con {max_tokens * 2}"
                    )
                    _rate_limiter.record_call(self.model, False, self.name)
                    _stats.track_claude(self.r, self.model, False, error="JSON_TRUNCATED")
                    return self._call_claude(
                        system, user_content,
                        max_tokens=max_tokens * 2,
                        _truncation_retry=True,
                    )
                raise

            # Capa 2: Validar output
            validation = _output_validator.validate(self.name, output)
            if not validation["valid"]:
                log.error(f"[{self.name}] Invalid output: {validation['errors']}")
                _rate_limiter.record_call(self.model, False, self.name)
                return {"error": "INVALID_OUTPUT", "errors": validation["errors"]}

            # Capa 6: Registrar éxito
            _rate_limiter.record_call(self.model, True, self.name)
            _stats.track_claude(
                self.r, self.model, True,
                tokens_in=response.usage.input_tokens,
                tokens_out=response.usage.output_tokens,
            )
            return output

        except Exception as e:
            log.error(f"[{self.name}] Error calling Claude: {e}")
            _rate_limiter.record_call(self.model, False, self.name)
            _stats.track_claude(self.r, self.model, False, error=str(e))
            raise

    def _pub(self, key: str, value) -> None:
        self.r.set(key, json.dumps(value) if isinstance(value, (dict, list)) else str(value))

    def _get_json(self, key: str) -> dict:
        raw = self.r.get(key)
        return json.loads(raw) if raw else {}
