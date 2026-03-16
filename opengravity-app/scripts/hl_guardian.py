"""
hl_guardian.py — SL/TP Guardian for HyperLiquid positions.

Ensures every open position has active SL and TP orders.
Called by pty-manager.ts at startup and every 5 minutes.

Two modes:
  1. Startup check: Scan all open positions, place missing SL/TP
  2. Health check: Verify existing SL/TP orders haven't been cancelled

Default SL/TP when strategy info is unavailable:
  - SL: 2% from entry price (opposite direction)
  - TP: 3% from entry price (same direction)

Usage:
    python hl_guardian.py                    # testnet (default)
    python hl_guardian.py --mainnet          # mainnet
    python hl_guardian.py --sl-pct 2.5       # custom SL %
    python hl_guardian.py --tp-pct 4.0       # custom TP %

Output: JSON to stdout with actions taken.
"""
import argparse
import json
import os
import sys
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

TESTNET_URL = "https://api.hyperliquid-testnet.xyz"
MAINNET_URL = "https://api.hyperliquid.xyz"

# Default SL/TP percentages from entry price
DEFAULT_SL_PCT = 2.0
DEFAULT_TP_PCT = 3.0


def hl_post(base_url: str, payload: dict) -> dict:
    resp = requests.post(f"{base_url}/info", json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


def round_price(px: float) -> float:
    if px > 1000:
        return int(round(px))
    elif px > 10:
        return round(px, 1)
    else:
        return round(px, 2)


def get_open_positions(base_url: str, address: str) -> list[dict]:
    """Get all open positions with their details."""
    state = hl_post(base_url, {"type": "clearinghouseState", "user": address})
    positions = []
    for p in state.get("assetPositions", []):
        pos = p.get("position", {})
        szi = float(pos.get("szi", 0))
        if szi == 0:
            continue
        positions.append({
            "coin": pos.get("coin"),
            "szi": szi,
            "entry_px": float(pos.get("entryPx", 0)),
            "is_long": szi > 0,
            "size": abs(szi),
            "unrealized_pnl": float(pos.get("unrealizedPnl", 0)),
            "leverage": float(pos.get("leverage", {}).get("value", 10)),
        })
    return positions


def get_open_orders(base_url: str, address: str) -> list[dict]:
    """Get all open orders (including trigger/SL/TP orders)."""
    return hl_post(base_url, {"type": "openOrders", "user": address})


def get_trigger_orders(base_url: str, address: str) -> list[dict]:
    """Get all open trigger orders (SL/TP specifically)."""
    # frontendOpenOrders includes trigger orders
    try:
        result = hl_post(base_url, {"type": "frontendOpenOrders", "user": address})
        return result if isinstance(result, list) else []
    except Exception:
        return []


def find_position_protections(coin: str, is_long: bool, trigger_orders: list[dict]) -> dict:
    """Check if a position has SL and TP trigger orders."""
    has_sl = False
    has_tp = False
    sl_price = 0.0
    tp_price = 0.0

    for order in trigger_orders:
        if order.get("coin") != coin:
            continue

        # Trigger orders for a LONG position are SELL (close side)
        # For a SHORT position, close orders are BUY
        order_side = order.get("side", "").upper()
        close_side = "A" if is_long else "B"  # A=sell, B=buy in HL format

        # Also check via isTrigger and orderType
        is_trigger = order.get("orderType", "") in ["Stop Market", "Take Profit Market"]
        if not is_trigger:
            # Check if it's a trigger via other fields
            trigger_info = order.get("trigger", {})
            if not trigger_info:
                continue

        if order.get("side") == close_side or order.get("reduceOnly"):
            trigger_px = float(order.get("triggerPx", 0))
            if trigger_px <= 0:
                continue

            if is_long:
                if trigger_px < float(order.get("limitPx", trigger_px)) or "sl" in str(order).lower():
                    has_sl = True
                    sl_price = trigger_px
                else:
                    has_tp = True
                    tp_price = trigger_px
            else:
                if trigger_px > float(order.get("limitPx", trigger_px)) or "sl" in str(order).lower():
                    has_sl = True
                    sl_price = trigger_px
                else:
                    has_tp = True
                    tp_price = trigger_px

    return {
        "has_sl": has_sl, "has_tp": has_tp,
        "sl_price": sl_price, "tp_price": tp_price,
    }


def place_protection(exchange, coin: str, is_long: bool, size: float,
                     entry_px: float, sl_pct: float, tp_pct: float,
                     need_sl: bool, need_tp: bool) -> dict:
    """Place missing SL and/or TP using bulk_orders with positionTpsl grouping.

    - SL uses isMarket=True (market close on trigger — avoids unfilled limit in fast moves)
    - TP uses isMarket=False (limit close — better exit price)
    - Both use reduce_only=True (only close existing position)
    """
    result = {"coin": coin, "actions": []}
    close_side = not is_long

    orders = []
    order_labels = []

    if need_sl:
        sl_price = round_price(entry_px * (1 - sl_pct / 100) if is_long else entry_px * (1 + sl_pct / 100))
        orders.append({
            'coin': coin,
            'is_buy': close_side,
            'sz': size,
            'limit_px': sl_price,
            'order_type': {'trigger': {'triggerPx': float(sl_price), 'isMarket': True, 'tpsl': 'sl'}},
            'reduce_only': True,
        })
        order_labels.append(('SL', sl_price, sl_pct))

    if need_tp:
        tp_price = round_price(entry_px * (1 + tp_pct / 100) if is_long else entry_px * (1 - tp_pct / 100))
        orders.append({
            'coin': coin,
            'is_buy': close_side,
            'sz': size,
            'limit_px': tp_price,
            'order_type': {'trigger': {'triggerPx': float(tp_price), 'isMarket': False, 'tpsl': 'tp'}},
            'reduce_only': True,
        })
        order_labels.append(('TP', tp_price, tp_pct))

    if not orders:
        return result

    # Try atomic bulk placement first
    try:
        resp = exchange.bulk_orders(orders, grouping='positionTpsl')
        if resp.get("status") == "ok":
            statuses = resp.get("response", {}).get("data", {}).get("statuses", [])
            for i, (label, price, pct) in enumerate(order_labels):
                if i < len(statuses):
                    s = statuses[i]
                    oid = s.get("resting", s.get("filled", {})).get("oid")
                    result["actions"].append({"type": f"{label}_PLACED", "price": price, "pct": pct, "oid": oid})
                    print(f"  [{coin}] {label} placed at {price} ({pct}% from entry {entry_px})", file=sys.stderr)
                else:
                    result["actions"].append({"type": f"{label}_FAILED", "error": "No status returned"})
            return result
        else:
            print(f"  [{coin}] bulk_orders failed, trying individual fallback", file=sys.stderr)
    except Exception as e:
        print(f"  [{coin}] bulk_orders error: {e}, trying individual fallback", file=sys.stderr)

    # Fallback: place individually
    for req, (label, price, pct) in zip(orders, order_labels):
        try:
            resp = exchange.order(
                req['coin'], req['is_buy'], req['sz'], req['limit_px'],
                req['order_type'], reduce_only=True)
            if resp.get("status") == "ok":
                result["actions"].append({"type": f"{label}_PLACED", "price": price, "pct": pct})
                print(f"  [{coin}] {label} placed at {price} (fallback)", file=sys.stderr)
            else:
                result["actions"].append({"type": f"{label}_FAILED", "error": str(resp)})
        except Exception as e:
            result["actions"].append({"type": f"{label}_FAILED", "error": str(e)})

    return result


def run_guardian(testnet: bool = True, sl_pct: float = DEFAULT_SL_PCT,
                 tp_pct: float = DEFAULT_TP_PCT) -> dict:
    """Main guardian loop: check all positions, place missing SL/TP."""
    key_env = 'HL_TESTNET_PRIVATE_KEY' if testnet else 'HL_PRIVATE_KEY'
    private_key = os.environ.get(key_env) or os.environ.get('HYPERLIQUID_PRIVATE_KEY', '')
    network = 'testnet' if testnet else 'mainnet'

    if not private_key:
        return {'success': False, 'error': f'No key in {key_env}', 'network': network}
    if not private_key.startswith('0x'):
        private_key = '0x' + private_key

    base_url = TESTNET_URL if testnet else MAINNET_URL

    try:
        from eth_account import Account
        account = Account.from_key(private_key)
        address = account.address
    except Exception as e:
        return {'success': False, 'error': f'Invalid key: {e}', 'network': network}

    # Get positions
    try:
        positions = get_open_positions(base_url, address)
    except Exception as e:
        return {'success': False, 'error': f'Failed to get positions: {e}', 'network': network}

    if not positions:
        return {
            'success': True, 'network': network,
            'positions': 0, 'actions': [],
            'message': 'No open positions',
        }

    # Get trigger orders
    try:
        trigger_orders = get_trigger_orders(base_url, address)
    except Exception:
        trigger_orders = []

    # Also get regular open orders as fallback
    try:
        open_orders = get_open_orders(base_url, address)
        all_orders = trigger_orders + open_orders
    except Exception:
        all_orders = trigger_orders

    # Init exchange for placing orders
    exchange = None
    try:
        import hyperliquid.info as _hl_info
        _orig_init = _hl_info.Info.__init__

        def _patched_init(self, base_url, skip_ws=False, meta=None, spot_meta=None, perp_dexs=None, timeout=None):
            self.base_url = base_url
            self.session = requests.Session()
            self.session.headers.update({"Content-Type": "application/json"})
            self.timeout = timeout or 10
            self._logger = __import__('logging').getLogger(__name__)
            self.ws_manager = None
            _meta = meta or requests.post(base_url + "/info", json={"type": "meta"}, timeout=10).json()
            self.coin_to_asset = {}
            self.name_to_coin = {}
            self.asset_to_sz_decimals = {}
            for i, asset_info in enumerate(_meta.get("universe", [])):
                name = asset_info["name"]
                self.coin_to_asset[name] = i
                self.name_to_coin[name] = name
                self.asset_to_sz_decimals[i] = asset_info.get("szDecimals", 6)

        _hl_info.Info.__init__ = _patched_init
        try:
            from hyperliquid.exchange import Exchange
            exchange = Exchange(account, base_url)
        finally:
            _hl_info.Info.__init__ = _orig_init
    except Exception as e:
        return {'success': False, 'error': f'Exchange init failed: {e}', 'network': network}

    # Check each position
    actions = []
    for pos in positions:
        coin = pos["coin"]
        direction = "LONG" if pos["is_long"] else "SHORT"
        protection = find_position_protections(coin, pos["is_long"], all_orders)

        status = "PROTECTED" if (protection["has_sl"] and protection["has_tp"]) else "UNPROTECTED"
        need_sl = not protection["has_sl"]
        need_tp = not protection["has_tp"]

        print(f"  [{coin}] {direction} entry={pos['entry_px']:.2f} size={pos['size']} "
              f"SL={'OK' if protection['has_sl'] else 'MISSING'} "
              f"TP={'OK' if protection['has_tp'] else 'MISSING'}",
              file=sys.stderr)

        if need_sl or need_tp:
            result = place_protection(
                exchange, coin, pos["is_long"], pos["size"],
                pos["entry_px"], sl_pct, tp_pct,
                need_sl=need_sl, need_tp=need_tp,
            )
            actions.append(result)

    return {
        'success': True,
        'network': network,
        'positions': len(positions),
        'protected': sum(1 for p in positions
                         for prot in [find_position_protections(p["coin"], p["is_long"], all_orders)]
                         if prot["has_sl"] and prot["has_tp"]),
        'actions': actions,
        'sl_pct': sl_pct,
        'tp_pct': tp_pct,
    }


def main():
    parser = argparse.ArgumentParser(description='SL/TP Guardian — protect open positions')
    parser.add_argument('--mainnet', action='store_true')
    parser.add_argument('--sl-pct', type=float, default=DEFAULT_SL_PCT,
                        help=f'Stop loss %% from entry (default: {DEFAULT_SL_PCT})')
    parser.add_argument('--tp-pct', type=float, default=DEFAULT_TP_PCT,
                        help=f'Take profit %% from entry (default: {DEFAULT_TP_PCT})')
    args = parser.parse_args()

    result = run_guardian(
        testnet=not args.mainnet,
        sl_pct=args.sl_pct,
        tp_pct=args.tp_pct,
    )
    print(json.dumps(result))
    sys.exit(0 if result.get('success') else 1)


if __name__ == '__main__':
    main()
