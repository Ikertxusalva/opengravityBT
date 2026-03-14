"""Cliente Redis singleton para BTQUANTR."""
import redis
from btquantr.config import config


def get_redis() -> redis.Redis:
    """Devuelve una conexión Redis. Lanza ConnectionError si no está disponible."""
    r = redis.Redis(
        host=config.redis.host,
        port=config.redis.port,
        db=config.redis.db,
        decode_responses=config.redis.decode_responses,
        socket_timeout=config.redis.socket_timeout,
    )
    r.ping()
    return r


def is_redis_available() -> bool:
    """Comprueba si Redis está disponible sin lanzar excepción."""
    try:
        get_redis()
        return True
    except Exception:
        return False
