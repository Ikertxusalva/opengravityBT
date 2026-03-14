"""API usage statistics — escribe contadores en Redis, lectura bajo demanda."""
from __future__ import annotations
import logging, time
import redis as redis_lib

log = logging.getLogger("ApiStats")

# USD por 1M tokens — https://www.anthropic.com/pricing
CLAUDE_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6":          {"input": 3.0,  "output": 15.0},
    "claude-sonnet-4-5-20250514": {"input": 3.0,  "output": 15.0},
    "claude-haiku-4-5-20251001":  {"input": 0.80, "output": 4.0},
}


def track_source(r: redis_lib.Redis, name: str, success: bool, error: str = "") -> None:
    """Incrementa contadores para una fuente de datos gratuita."""
    try:
        key = f"stats:api:{name}"
        now = int(time.time())
        pipe = r.pipeline(transaction=False)
        pipe.hincrby(key, "requests", 1)
        if success:
            pipe.hset(key, "last_success_ts", now)
        else:
            pipe.hincrby(key, "errors", 1)
            pipe.hset(key, "last_error_ts", now)
            if error:
                pipe.hset(key, "last_error", str(error)[:200])
        pipe.execute()
    except Exception as e:
        log.debug(f"stats.track_source non-critical: {e}")


def track_claude(
    r: redis_lib.Redis,
    model: str,
    success: bool,
    tokens_in: int = 0,
    tokens_out: int = 0,
    error: str = "",
) -> None:
    """Incrementa contadores para Claude API con coste real por tokens."""
    try:
        key = "stats:api:claude"
        now = int(time.time())
        pricing = CLAUDE_PRICING.get(model, {"input": 3.0, "output": 15.0})
        cost_micro = int(
            (tokens_in * pricing["input"] + tokens_out * pricing["output"])
            / 1_000_000
            * 1_000_000
        )
        pipe = r.pipeline(transaction=False)
        pipe.hincrby(key, "calls_total", 1)
        if success:
            pipe.hincrby(key, "calls_ok", 1)
            pipe.hincrby(key, "tokens_in", tokens_in)
            pipe.hincrby(key, "tokens_out", tokens_out)
            pipe.hincrby(key, "cost_usd_micro", cost_micro)
            pipe.hset(key, "last_call_ts", now)
            pipe.hset(key, "last_model", model)
        else:
            pipe.hincrby(key, "calls_err", 1)
            pipe.hset(key, "last_error_ts", now)
            if error:
                pipe.hset(key, "last_error", str(error)[:200])
        pipe.execute()
    except Exception as e:
        log.debug(f"stats.track_claude non-critical: {e}")


def read_claude_stats(r: redis_lib.Redis) -> dict:
    """Lee stats:api:claude de Redis. Retorna dict normalizado para status_bar()."""
    raw = r.hgetall("stats:api:claude")
    if not raw:
        return {"calls": 0, "cost": 0.0, "tokens_in": 0, "tokens_out": 0}
    return {
        "calls":      int(raw.get("calls_total", 0)),
        "cost":       int(raw.get("cost_usd_micro", 0)) / 1_000_000,
        "tokens_in":  int(raw.get("tokens_in", 0)),
        "tokens_out": int(raw.get("tokens_out", 0)),
    }


def read_all(r: redis_lib.Redis) -> dict[str, dict]:
    """Lee todas las stats de Redis. Retorna dict {api_name: {field: value}}."""
    names = ["claude", "binance", "hyperliquid", "alternative_me", "yfinance"]
    result = {}
    for name in names:
        raw = r.hgetall(f"stats:api:{name}")
        result[name] = dict(raw) if raw else {}
    return result
