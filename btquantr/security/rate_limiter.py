"""Capa 6 de Seguridad — Rate Limiting de Claude API."""
from __future__ import annotations
import json, logging, time, uuid
from collections import defaultdict

log = logging.getLogger("BTQUANTRSecurity")

# Redis keys
_K_CALLS = "security:rate_limiter:calls_log"
_K_RETRIES = "security:rate_limiter:agent_retries"
_K_FAILURES = "security:rate_limiter:consecutive_failures"
_K_COST_TODAY = "security:rate_limiter:cost_today"
_K_DAY_START = "security:rate_limiter:day_start"
_K_PAUSED = "security:rate_limiter:paused"


class ClaudeRateLimiter:
    """
    Controla consumo de Claude API:
    - Frecuencia: max 20 calls/min, 200 calls/hora
    - Coste: max $5/hora, $50/día
    - Retries: max 3 por agente
    - Fallos: pausa sistema si 5 fallos consecutivos

    Si se proporciona redis_client, los contadores se persisten en Redis
    con TTL para sobrevivir reinicios del proceso.
    """

    MAX_CALLS_PER_MINUTE = 20
    MAX_CALLS_PER_HOUR = 200
    MAX_COST_PER_HOUR_USD = 5.0
    MAX_COST_PER_DAY_USD = 50.0
    MAX_RETRIES_PER_AGENT = 3
    MAX_CONSECUTIVE_FAILURES = 5

    COST_PER_CALL: dict[str, float] = {
        "claude-sonnet-4-6": 0.005,
        "claude-sonnet-4-5-20250514": 0.005,
        "claude-haiku-4-5-20251001": 0.001,
    }

    def __init__(self, redis_client=None):
        self._redis = redis_client
        self.calls_log: list[tuple[float, str, float]] = []  # (ts, model, cost)
        self.agent_retries: dict[str, int] = defaultdict(int)
        self.consecutive_failures: int = 0
        self.total_cost_today: float = 0.0
        self.day_start: float = time.time()
        self._paused: bool = False

        if self._redis:
            self._load_from_redis()

    # ── Redis persistence ─────────────────────────────────────────────────────

    def _load_from_redis(self) -> None:
        """Carga estado persistido desde Redis al inicializar."""
        r = self._redis
        try:
            now = time.time()
            # calls_log — sorted set: score=timestamp, member=json
            raw = r.zrangebyscore(_K_CALLS, now - 86400, "+inf", withscores=True)
            self.calls_log = []
            for member, score in raw:
                try:
                    data = json.loads(member)
                    self.calls_log.append((score, data["model"], data["cost"]))
                except (json.JSONDecodeError, KeyError):
                    pass

            # agent_retries — hash
            raw_retries = r.hgetall(_K_RETRIES)
            self.agent_retries = defaultdict(int, {k: int(v) for k, v in raw_retries.items()})

            # consecutive_failures
            val = r.get(_K_FAILURES)
            self.consecutive_failures = int(val) if val else 0

            # cost_today + day_start
            cost_val = r.get(_K_COST_TODAY)
            day_val = r.get(_K_DAY_START)
            self.total_cost_today = float(cost_val) if cost_val else 0.0
            self.day_start = float(day_val) if day_val else now

            # paused
            paused_val = r.get(_K_PAUSED)
            self._paused = (paused_val == "1") if paused_val else False

        except Exception as e:
            log.warning(f"[RateLimiter] Failed to load from Redis: {e}")

    def _sync_to_redis(
        self,
        *,
        new_call: tuple[float, str, float] | None = None,
        agent_name: str | None = None,
    ) -> None:
        """Sincroniza estado a Redis. new_call=(ts, model, cost) si hay llamada nueva."""
        r = self._redis
        if r is None:
            return
        try:
            now = time.time()

            if new_call is not None:
                ts, model, cost = new_call
                member = json.dumps({"model": model, "cost": cost, "id": uuid.uuid4().hex})
                r.zadd(_K_CALLS, {member: ts})
                # Limpiar entradas > 24h y renovar TTL
                r.zremrangebyscore(_K_CALLS, "-inf", now - 86400)
                r.expire(_K_CALLS, 86400)

            if agent_name is not None:
                r.hset(_K_RETRIES, agent_name, self.agent_retries[agent_name])
                r.expire(_K_RETRIES, 3600)

            r.set(_K_FAILURES, self.consecutive_failures)
            r.set(_K_COST_TODAY, self.total_cost_today, ex=86400)
            r.set(_K_DAY_START, self.day_start, ex=86400)
            r.set(_K_PAUSED, "1" if self._paused else "0")

        except Exception as e:
            log.warning(f"[RateLimiter] Failed to sync to Redis: {e}")

    # ── Core logic ────────────────────────────────────────────────────────────

    def _reset_daily_if_needed(self) -> None:
        if time.time() - self.day_start > 86400:
            self.total_cost_today = 0.0
            self.day_start = time.time()
            self._sync_to_redis()

    def _estimated_cost(self, model: str) -> float:
        return self.COST_PER_CALL.get(model, 0.005)

    def check(self, agent_name: str, model: str) -> dict:
        """Verifica si se permite la llamada. Retorna {"allowed": bool, "reason": str, "estimated_cost": float}."""
        self._reset_daily_if_needed()
        now = time.time()
        cost = self._estimated_cost(model)

        if self._paused:
            return {"allowed": False, "reason": "SYSTEM_PAUSED", "estimated_cost": cost}

        # Frecuencia por minuto
        calls_last_min = sum(1 for ts, _, _ in self.calls_log if now - ts < 60)
        if calls_last_min >= self.MAX_CALLS_PER_MINUTE:
            return {"allowed": False, "reason": "MINUTE_LIMIT", "estimated_cost": cost}

        # Frecuencia por hora
        calls_last_hour = sum(1 for ts, _, _ in self.calls_log if now - ts < 3600)
        if calls_last_hour >= self.MAX_CALLS_PER_HOUR:
            return {"allowed": False, "reason": "HOUR_LIMIT", "estimated_cost": cost}

        # Coste por hora
        cost_last_hour = sum(c for ts, _, c in self.calls_log if now - ts < 3600)
        if round(cost_last_hour + cost, 2) >= self.MAX_COST_PER_HOUR_USD:
            return {"allowed": False, "reason": "HOUR_COST_LIMIT", "estimated_cost": cost}

        # Coste diario
        if self.total_cost_today + cost > self.MAX_COST_PER_DAY_USD:
            self._paused = True
            log.critical(f"Daily cost limit ${self.MAX_COST_PER_DAY_USD} reached — system PAUSED")
            self._sync_to_redis()
            return {"allowed": False, "reason": "DAY_COST_LIMIT", "estimated_cost": cost}

        # Retries por agente
        if self.agent_retries[agent_name] >= self.MAX_RETRIES_PER_AGENT:
            return {"allowed": False, "reason": "AGENT_RETRY_LIMIT", "estimated_cost": cost}

        # Fallos consecutivos globales
        if self.consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
            self._paused = True
            log.critical(f"{self.MAX_CONSECUTIVE_FAILURES} consecutive failures — system PAUSED")
            self._sync_to_redis()
            return {"allowed": False, "reason": "CONSECUTIVE_FAILURES", "estimated_cost": cost}

        return {"allowed": True, "reason": "OK", "estimated_cost": cost}

    def record_call(self, model: str, success: bool, agent_name: str) -> None:
        """Registra resultado de una llamada."""
        now = time.time()
        cost = self._estimated_cost(model)
        self.calls_log.append((now, model, cost))
        self.total_cost_today += cost

        if success:
            self.consecutive_failures = 0
            self.agent_retries[agent_name] = 0
        else:
            self.consecutive_failures += 1
            self.agent_retries[agent_name] += 1

        # Limpiar log > 24h
        self.calls_log = [(ts, m, c) for ts, m, c in self.calls_log if now - ts < 86400]

        self._sync_to_redis(new_call=(now, model, cost), agent_name=agent_name)

    def get_stats(self) -> dict:
        """Estadísticas actuales del rate limiter."""
        now = time.time()
        return {
            "calls_last_minute": sum(1 for ts, _, _ in self.calls_log if now - ts < 60),
            "calls_last_hour": sum(1 for ts, _, _ in self.calls_log if now - ts < 3600),
            "cost_last_hour": round(sum(c for ts, _, c in self.calls_log if now - ts < 3600), 4),
            "cost_today": round(self.total_cost_today, 4),
            "consecutive_failures": self.consecutive_failures,
            "paused": self._paused,
            "agent_retries": dict(self.agent_retries),
        }

    def unpause(self) -> None:
        """Despausa manualmente el sistema."""
        self._paused = False
        self.consecutive_failures = 0
        log.info("Rate limiter unpaused manually")
        self._sync_to_redis()
