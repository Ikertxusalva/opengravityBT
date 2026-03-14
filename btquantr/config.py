"""Configuración global de BTQUANTR."""
import os
from dataclasses import dataclass, field


@dataclass
class RedisConfig:
    host: str = field(default_factory=lambda: os.environ.get("REDIS_HOST", "localhost"))
    port: int = field(default_factory=lambda: int(os.environ.get("REDIS_PORT", "6379")))
    db: int = field(default_factory=lambda: int(os.environ.get("REDIS_DB", "0")))
    decode_responses: bool = True
    socket_timeout: float = 5.0


@dataclass
class HMMConfig:
    n_states: int = 3
    window: int = 500
    min_train: int = 100
    retrain_interval: int = 3600
    predict_interval: int = 60
    min_features: int = 3
    symbols: list = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])


@dataclass
class DataConfig:
    clean_threshold: float = 0.95
    fetch_interval: int = 60
    ohlcv_timeframes: list = field(default_factory=lambda: ["1m", "5m", "1h", "4h"])


@dataclass
class BTQUANTRConfig:
    redis: RedisConfig = field(default_factory=RedisConfig)
    hmm: HMMConfig = field(default_factory=HMMConfig)
    data: DataConfig = field(default_factory=DataConfig)


config = BTQUANTRConfig()
