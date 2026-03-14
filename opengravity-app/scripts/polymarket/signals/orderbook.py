"""
Order Book Imbalance Signal
============================
Detecta presion de compra/venta en el order book del CLOB de Polymarket.

Logica:
- Si bid_liquidity >> ask_liquidity: presion compradora → precio subira
- Si ask_liquidity >> bid_liquidity: presion vendedora → precio bajara

Complementa otras señales como confirmacion de direccion.
"""

from typing import Optional


def check_orderbook_imbalance(ob: dict,
                              direction: str,
                              min_ratio: float = 1.5) -> Optional[dict]:
    """
    Valida que el order book confirma la direccion de la señal.

    ob: resultado de get_orderbook() con bid_liquidity y ask_liquidity
    direction: "BUY_YES" o "BUY_NO"
    min_ratio: ratio minimo para que la señal sea valida (1.5 = 50% mas liquidez)

    Retorna dict con confirmacion o None si el OB contradice la señal.
    """
    bid_liq = ob.get("bid_liquidity", 0)
    ask_liq = ob.get("ask_liquidity", 0)

    if bid_liq <= 0 or ask_liq <= 0:
        return None

    # Para BUY_YES queremos que haya mas liquidez compradora (bids)
    # Para BUY_NO (compramos NO, que equivale a vender YES) queremos mas asks
    if direction == "BUY_YES":
        ratio = bid_liq / ask_liq
        ob_direction = "bid_heavy"
        confirms = ratio >= min_ratio
    else:
        ratio = ask_liq / bid_liq
        ob_direction = "ask_heavy"
        confirms = ratio >= min_ratio

    if not confirms:
        return None

    edge_contribution = min(0.03, (ratio - 1.0) * 0.02)  # max 3% de edge adicional

    return {
        "source": "ob_imbalance",
        "edge": round(edge_contribution, 4),
        "direction": direction,
        "ob_direction": ob_direction,
        "ratio": round(ratio, 2),
        "bid_liq": round(bid_liq, 2),
        "ask_liq": round(ask_liq, 2),
    }


def get_ob_pressure_score(ob: dict) -> float:
    """
    Score de presion del OB de -1 (venta pura) a +1 (compra pura).
    Util para confirmar o desconfirmar otras señales.
    """
    bid_liq = ob.get("bid_liquidity", 0)
    ask_liq = ob.get("ask_liquidity", 0)
    total = bid_liq + ask_liq
    if total <= 0:
        return 0.0
    return round((bid_liq - ask_liq) / total, 3)
