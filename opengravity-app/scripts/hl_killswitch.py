"""
hl_killswitch.py — Emergency kill switch for HyperLiquid.

Closes ALL open positions and cancels ALL pending orders.
Designed to be callable from:
  1. CLI:     python hl_killswitch.py [--mainnet]
  2. Backend: POST /api/killswitch (Railway endpoint)
  3. Mobile:  curl -X POST https://your-railway.app/api/killswitch?token=xxx

This is a DESTRUCTIVE operation. All positions will be market-closed.
"""
import json
import os
import sys
import time
import requests
from datetime import datetime, timezone

TESTNET_URL = "https://api.hyperliquid-testnet.xyz"
MAINNET_URL = "https://api.hyperliquid.xyz"


def hl_post(base_url: str, payload: dict) -> dict:
    resp = requests.post(f"{base_url}/info", json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_account(testnet: bool = True):
    """Load private key and derive address."""
    key_env = 'HL_TESTNET_PRIVATE_KEY' if testnet else 'HL_PRIVATE_KEY'
    private_key = os.environ.get(key_env) or os.environ.get('HYPERLIQUID_PRIVATE_KEY', '')
    if not private_key:
        return None, None, f'No private key in {key_env}'
    if not private_key.startswith('0x'):
        private_key = '0x' + private_key

    from eth_account import Account
    account = Account.from_key(private_key)
    return private_key, account.address, None


def cancel_all_orders(base_url: str, address: str, private_key: str) -> list:
    """Cancel all open orders."""
    cancelled = []
    try:
        open_orders = hl_post(base_url, {"type": "openOrders", "user": address})
        if not open_orders:
            return cancelled

        from hyperliquid.utils import constants
        from hyperliquid.exchange import Exchange
        from eth_account import Account

        # Monkey-patch for testnet if needed
        if "testnet" in base_url:
            _orig = __import__('hyperliquid').info.Info.__init__
            def _patched_init(self, base_url_arg=None, skip_ws=False):
                _orig(self, base_url_arg or constants.TESTNET_API_URL, skip_ws=True)
            __import__('hyperliquid').info.Info.__init__ = _patched_init

        wallet = Account.from_key(private_key)
        exchange = Exchange(wallet, base_url)

        for order in open_orders:
            oid = order.get("oid")
            coin = order.get("coin", "")
            try:
                result = exchange.cancel(coin, oid)
                cancelled.append({"oid": oid, "coin": coin, "status": "cancelled"})
            except Exception as e:
                cancelled.append({"oid": oid, "coin": coin, "error": str(e)})

    except Exception as e:
        cancelled.append({"error": f"cancel_all failed: {e}"})
    return cancelled


def close_all_positions(base_url: str, address: str, private_key: str) -> list:
    """Market-close all open positions."""
    closed = []
    try:
        state = hl_post(base_url, {"type": "clearinghouseState", "user": address})
        positions = state.get("assetPositions", [])

        from hyperliquid.utils import constants
        from hyperliquid.exchange import Exchange
        from eth_account import Account

        if "testnet" in base_url:
            _orig = __import__('hyperliquid').info.Info.__init__
            def _patched_init(self, base_url_arg=None, skip_ws=False):
                _orig(self, base_url_arg or constants.TESTNET_API_URL, skip_ws=True)
            __import__('hyperliquid').info.Info.__init__ = _patched_init

        wallet = Account.from_key(private_key)
        exchange = Exchange(wallet, base_url)

        for pos in positions:
            p = pos.get("position", {})
            coin = p.get("coin", "")
            size = float(p.get("szi", 0))
            if size == 0:
                continue

            is_long = size > 0
            abs_size = abs(size)

            # Get current price for slippage calc
            try:
                mid = hl_post(base_url, {"type": "allMids"})
                px = float(mid.get(coin, 0))
            except Exception:
                px = float(p.get("entryPx", 0))

            # Market close with 1% slippage
            slippage = 0.01
            if is_long:
                limit_px = round(px * (1 - slippage), 6)
            else:
                limit_px = round(px * (1 + slippage), 6)

            try:
                result = exchange.order(
                    coin, not is_long, abs_size, limit_px,
                    {"limit": {"tif": "Ioc"}},
                    reduce_only=True,
                )
                status = result.get("response", {}).get("data", {}).get("statuses", [{}])
                closed.append({
                    "coin": coin,
                    "side": "LONG" if is_long else "SHORT",
                    "size": abs_size,
                    "close_px": limit_px,
                    "status": "closed",
                    "detail": status,
                })
            except Exception as e:
                closed.append({
                    "coin": coin,
                    "side": "LONG" if is_long else "SHORT",
                    "size": abs_size,
                    "error": str(e),
                })

    except Exception as e:
        closed.append({"error": f"close_all failed: {e}"})
    return closed


def kill(testnet: bool = True) -> dict:
    """Execute kill switch: cancel all orders + close all positions."""
    ts = datetime.now(timezone.utc).isoformat()
    network = "testnet" if testnet else "MAINNET"
    base_url = TESTNET_URL if testnet else MAINNET_URL

    print(f"🚨 KILL SWITCH ACTIVATED — {network} — {ts}")

    private_key, address, error = get_account(testnet)
    if error:
        return {"success": False, "error": error, "network": network, "timestamp": ts}

    print(f"   Address: {address}")
    print(f"   Cancelling all orders...")
    cancelled = cancel_all_orders(base_url, address, private_key)
    print(f"   Cancelled: {len(cancelled)} orders")

    print(f"   Closing all positions...")
    closed = close_all_positions(base_url, address, private_key)
    print(f"   Closed: {len(closed)} positions")

    # Write kill event to log
    log_path = os.path.join(os.path.dirname(__file__), "crypto", "data", "killswitch_log.jsonl")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps({
            "timestamp": ts, "network": network,
            "cancelled_orders": len(cancelled),
            "closed_positions": len(closed),
        }) + "\n")

    return {
        "success": True,
        "network": network,
        "timestamp": ts,
        "address": address,
        "orders_cancelled": cancelled,
        "positions_closed": closed,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Emergency kill switch — close everything")
    parser.add_argument("--mainnet", action="store_true", help="Use mainnet (default: testnet)")
    parser.add_argument("--confirm", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    if args.mainnet and not args.confirm:
        print("⚠️  MAINNET KILL SWITCH — This will close ALL positions and cancel ALL orders.")
        print("   Type 'KILL' to confirm:")
        confirm = input("   > ").strip()
        if confirm != "KILL":
            print("Aborted.")
            sys.exit(1)

    result = kill(testnet=not args.mainnet)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["success"] else 1)
