"""IndicatorLibrary — catálogo de indicadores técnicos con metadata.

Cada indicador es un dict con:
  name          : str  — identificador único
  category      : str  — TREND | MOMENTUM | VOLATILITY | VOLUME
  signal_type   : str  — THRESHOLD | CROSSOVER | LEVEL | FILTER
  params        : dict — {param_name: {min, max, default, step}}
  code_template : str  — string con {param_name} como placeholders para .format()
"""

from __future__ import annotations


class IndicatorLibrary:
    """Catálogo central de indicadores técnicos para el motor de estrategias."""

    INDICATORS: list[dict] = [
        # ── TREND ──────────────────────────────────────────────────────────────
        {
            "name": "SMA",
            "category": "TREND",
            "signal_type": "CROSSOVER",
            "params": {
                "length": {"min": 5, "max": 200, "default": 20, "step": 5},
            },
            "code_template": "ta.sma(close, length={length})",
        },
        {
            "name": "EMA",
            "category": "TREND",
            "signal_type": "CROSSOVER",
            "params": {
                "length": {"min": 5, "max": 200, "default": 20, "step": 5},
            },
            "code_template": "ta.ema(close, length={length})",
        },
        {
            "name": "MACD",
            "category": "TREND",
            "signal_type": "CROSSOVER",
            "params": {
                "fast": {"min": 5, "max": 15, "default": 12, "step": 1},
                "slow": {"min": 20, "max": 50, "default": 26, "step": 1},
                "signal": {"min": 5, "max": 15, "default": 9, "step": 1},
            },
            "code_template": "ta.macd(close, fast={fast}, slow={slow}, signal={signal})",
        },
        {
            "name": "ADX",
            "category": "TREND",
            "signal_type": "LEVEL",
            "params": {
                "length": {"min": 7, "max": 28, "default": 14, "step": 2},
            },
            "code_template": "ta.adx(high, low, close, length={length})",
        },
        # ── MOMENTUM ───────────────────────────────────────────────────────────
        {
            "name": "RSI",
            "category": "MOMENTUM",
            "signal_type": "THRESHOLD",
            "params": {
                "length": {"min": 7, "max": 28, "default": 14, "step": 2},
            },
            "code_template": "ta.rsi(close, length={length})",
        },
        {
            "name": "Stochastic",
            "category": "MOMENTUM",
            "signal_type": "THRESHOLD",
            "params": {
                "k": {"min": 5, "max": 21, "default": 14, "step": 1},
                "d": {"min": 3, "max": 9, "default": 3, "step": 1},
                "smooth_k": {"min": 1, "max": 5, "default": 3, "step": 1},
            },
            "code_template": "ta.stoch(high, low, close, k={k}, d={d}, smooth_k={smooth_k})",
        },
        {
            "name": "CCI",
            "category": "MOMENTUM",
            "signal_type": "THRESHOLD",
            "params": {
                "length": {"min": 10, "max": 40, "default": 20, "step": 5},
                "c": {"min": 1, "max": 2, "default": 1, "step": 1},
            },
            "code_template": "ta.cci(high, low, close, length={length}, c={c})",
        },
        {
            "name": "WilliamsR",
            "category": "MOMENTUM",
            "signal_type": "THRESHOLD",
            "params": {
                "length": {"min": 7, "max": 28, "default": 14, "step": 2},
            },
            "code_template": "ta.willr(high, low, close, length={length})",
        },
        # ── VOLATILITY ─────────────────────────────────────────────────────────
        {
            "name": "BollingerBands",
            "category": "VOLATILITY",
            "signal_type": "LEVEL",
            "params": {
                "length": {"min": 10, "max": 50, "default": 20, "step": 5},
                "std": {"min": 1, "max": 3, "default": 2, "step": 1},
            },
            "code_template": "ta.bbands(close, length={length}, std={std})",
        },
        {
            "name": "ATR",
            "category": "VOLATILITY",
            "signal_type": "FILTER",
            "params": {
                "length": {"min": 7, "max": 28, "default": 14, "step": 2},
            },
            "code_template": "ta.atr(high, low, close, length={length})",
        },
        {
            "name": "KeltnerChannel",
            "category": "VOLATILITY",
            "signal_type": "LEVEL",
            "params": {
                "length": {"min": 10, "max": 50, "default": 20, "step": 5},
                "scalar": {"min": 1, "max": 3, "default": 2, "step": 1},
            },
            "code_template": "ta.kc(high, low, close, length={length}, scalar={scalar})",
        },
        # ── VOLUME ─────────────────────────────────────────────────────────────
        {
            "name": "OBV",
            "category": "VOLUME",
            "signal_type": "CROSSOVER",
            "params": {},
            "code_template": "ta.obv(close, volume)",
        },
        {
            "name": "VWAP",
            "category": "VOLUME",
            "signal_type": "LEVEL",
            "params": {},
            "code_template": "ta.vwap(high, low, close, volume)",
        },
        # ── Extra (TREND) ──────────────────────────────────────────────────────
        {
            "name": "DEMA",
            "category": "TREND",
            "signal_type": "CROSSOVER",
            "params": {
                "length": {"min": 5, "max": 100, "default": 20, "step": 5},
            },
            "code_template": "ta.dema(close, length={length})",
        },
        # ── Extra (MOMENTUM) ───────────────────────────────────────────────────
        {
            "name": "MFI",
            "category": "MOMENTUM",
            "signal_type": "THRESHOLD",
            "params": {
                "length": {"min": 7, "max": 28, "default": 14, "step": 2},
            },
            "code_template": "ta.mfi(high, low, close, volume, length={length})",
        },
        # ── Extra (VOLATILITY) ─────────────────────────────────────────────────
        {
            "name": "DonchianChannel",
            "category": "VOLATILITY",
            "signal_type": "LEVEL",
            "params": {
                "lower_length": {"min": 10, "max": 50, "default": 20, "step": 5},
                "upper_length": {"min": 10, "max": 50, "default": 20, "step": 5},
            },
            "code_template": "ta.donchian(high, low, lower_length={lower_length}, upper_length={upper_length})",
        },
    ]

    # ── Índice interno por nombre ───────────────────────────────────────────────
    def __init__(self) -> None:
        self._index: dict[str, dict] = {ind["name"]: ind for ind in self.INDICATORS}

    # ── Métodos de consulta ────────────────────────────────────────────────────
    def get(self, name: str) -> dict:
        """Devuelve el indicador por nombre. Lanza KeyError si no existe."""
        if name not in self._index:
            raise KeyError(f"Indicador '{name}' no encontrado en la librería.")
        return self._index[name]

    def get_by_category(self, category: str) -> list[dict]:
        """Devuelve todos los indicadores de una categoría dada."""
        return [ind for ind in self.INDICATORS if ind["category"] == category]

    def get_by_signal_type(self, signal_type: str) -> list[dict]:
        """Devuelve todos los indicadores de un signal_type dado."""
        return [ind for ind in self.INDICATORS if ind["signal_type"] == signal_type]

    def all_names(self) -> list[str]:
        """Devuelve lista de todos los nombres de indicadores."""
        return [ind["name"] for ind in self.INDICATORS]

    def same_type_swap(self, indicator: dict) -> list[dict]:
        """Devuelve indicadores de la misma categoría, excluyendo el indicador dado."""
        return [
            ind
            for ind in self.INDICATORS
            if ind["category"] == indicator["category"] and ind["name"] != indicator["name"]
        ]
