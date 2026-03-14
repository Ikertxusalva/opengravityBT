"""VenueAdapter — adapta parámetros de estrategia para brokers distintos.

HyperLiquid (original):
  - Sin spread, sin comisiones por trade
  - Funding cada 1h, tamaño en USDT

MT5 (adaptado):
  - Spread añadido al SL y TP (en pips)
  - Lot size mínimo 0.01 (forex/crypto CFD)
"""
from __future__ import annotations

import copy

# ─── Tabla de spread estimado por símbolo (en pips) ──────────────────────────
_SPREAD_PIPS: dict[str, int] = {
    # Forex majors
    "EURUSD": 1, "GBPUSD": 1, "USDJPY": 1, "USDCAD": 1,
    "AUDUSD": 1, "NZDUSD": 1, "USDCHF": 1,
    # Forex minors
    "EURGBP": 2, "EURJPY": 2, "GBPJPY": 2,
    # Metales
    "XAUUSD": 30, "GOLD": 30, "XAGUSD": 10, "SILVER": 10,
    # Energía
    "CL": 5, "NG": 10,
    # Crypto CFDs
    "BTCUSDT": 50, "ETHUSDT": 30,
    "SOLUSDT": 30, "ADAUSDT": 30, "LINKUSDT": 30,
    "AVAXUSDT": 30, "DOGEUSDT": 30, "DOTUSDT": 30,
    # Equities CFDs (spread ~0, comisión flat)
    "SPY": 0, "AAPL": 0, "NVDA": 0, "GLD": 0,
}

# Tamaño de un pip en precio del activo
_PIP_SIZE: dict[str, float] = {
    "USDJPY": 0.01, "EURJPY": 0.01, "GBPJPY": 0.01,
    "XAUUSD": 0.1, "GOLD": 0.1, "XAGUSD": 0.001, "SILVER": 0.001,
    "BTCUSDT": 1.0, "ETHUSDT": 1.0,
    "SOLUSDT": 0.01, "ADAUSDT": 0.0001, "DOGEUSDT": 0.0001,
    "LINKUSDT": 0.01, "AVAXUSDT": 0.01, "DOTUSDT": 0.01,
    "CL": 0.01, "NG": 0.001,
}
_DEFAULT_PIP_SIZE = 0.0001  # forex standard

# Precio de referencia aproximado (estático) para convertir spread en %.
# Nota: estos valores son estimaciones para cálculo de buffers, no precios en tiempo real.
_REF_PRICE: dict[str, float] = {
    "BTCUSDT": 80_000.0, "ETHUSDT": 3_000.0,
    "SOLUSDT": 150.0, "ADAUSDT": 0.5, "DOGEUSDT": 0.1,
    "LINKUSDT": 15.0, "AVAXUSDT": 30.0, "DOTUSDT": 6.0,
    "XAUUSD": 2_000.0, "GOLD": 2_000.0, "XAGUSD": 25.0, "SILVER": 25.0,
    "EURUSD": 1.10, "GBPUSD": 1.28, "USDJPY": 150.0,
    "USDCAD": 1.35, "AUDUSD": 0.65, "NZDUSD": 0.60,
    "CL": 75.0, "NG": 2.5,
}
_DEFAULT_REF_PRICE = 100.0  # precio genérico razonable para instrumentos desconocidos

_CRYPTO_KEYWORDS = {"BTC", "ETH", "SOL", "AVAX", "ADA", "DOT", "LINK", "DOGE"}


class VenueAdapter:
    """Adapta parámetros de estrategia según broker destino."""

    @classmethod
    def get_spread_pips(cls, symbol: str) -> int:
        """Retorna spread estimado en pips para el símbolo."""
        sym = symbol.upper().replace("-", "").replace("_", "")
        if sym in _SPREAD_PIPS:
            return _SPREAD_PIPS[sym]
        for k, v in _SPREAD_PIPS.items():
            if k in sym or sym in k:
                return v
        return 2

    @classmethod
    def adapt_for_mt5(cls, strategy: dict) -> dict:
        """Devuelve copia de strategy con parámetros ajustados para MT5.

        Ajustes:
        - sl_pct: aumentado por el spread (en %)
        - mt5_tp_pips: TP base + spread (en pips)
        - mt5_lot_size: 0.01 (mínimo MT5 estándar)
        - venue: "mt5"

        El dict original no se modifica.
        """
        adapted = copy.deepcopy(strategy)
        symbol = strategy.get("symbol", "")
        params = adapted.setdefault("params", {})

        spread_pips = cls.get_spread_pips(symbol)
        # Normalizar igual que get_spread_pips para coherencia
        sym_norm = symbol.upper().replace("-", "").replace("_", "")
        pip_size = _PIP_SIZE.get(sym_norm, _DEFAULT_PIP_SIZE)
        ref_price = _REF_PRICE.get(sym_norm, _DEFAULT_REF_PRICE)

        # 1. Ajustar SL: añadir spread como % del precio de referencia
        spread_value = spread_pips * pip_size
        spread_pct = (spread_value / ref_price) * 100.0 if ref_price > 0 else 0.0
        original_sl = float(params.get("sl_pct", 2.0))
        params["sl_pct"] = round(original_sl + spread_pct, 6)

        # 2. TP en pips: base según tipo de instrumento + spread
        base_tp = 200 if any(k in sym_norm for k in _CRYPTO_KEYWORDS) else 30
        params["mt5_tp_pips"] = base_tp + spread_pips

        # 3. Lot size mínimo MT5
        params["mt5_lot_size"] = 0.01

        # 4. Marcar venue
        adapted["venue"] = "mt5"

        return adapted
