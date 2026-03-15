"""
hl_execute.py — Execute swarm orders on HyperLiquid.

Uses HLConnector for mainnet, direct REST API for testnet (SDK bug workaround).
Called by pty-manager.ts when user confirms a swarm EXECUTE decision.
Outputs JSON to stdout for the TypeScript caller to parse.

Order logic:
  - Default: LIMIT order with 0.1% slippage (better entry price)
  - If limit not filled within FILL_TIMEOUT (60s): cancel + retry as IOC market
  - Priority 1 signals skip limit and go straight to market (time-sensitive)

Usage:
    python hl_execute.py --symbol BTC --direction LONG --size half --score 0.74
    python hl_execute.py --symbol ETH --direction SHORT --size full --score 0.85 --mainnet
    python hl_execute.py --symbol BTC --direction LONG --size full --score 0.90 --priority 1
"""
import argparse
import json
import os
import sys
import time
import requests

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

TESTNET_URL = "https://api.hyperliquid-testnet.xyz"
MAINNET_URL = "https://api.hyperliquid.xyz"

# Position size mapping (USD amounts)
SIZE_MAP_TESTNET = {'full': 50.0, 'half': 25.0, 'quarter': 12.5}
SIZE_MAP_MAINNET = {'full': 25.0, 'half': 12.5, 'quarter': 6.25}

# Order execution config
LIMIT_SLIPPAGE = 0.001   # 0.1% slippage for limit orders (tight, good entry)
MARKET_SLIPPAGE = 0.005  # 0.5% slippage for market fallback
FILL_TIMEOUT = 60        # Seconds to wait for limit fill before market fallback


def hl_post(base_url: str, payload: dict) -> dict:
    """POST to HyperLiquid info API."""
    resp = requests.post(f"{base_url}/info", json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


def execute_order(symbol: str, direction: str, size: str, score: float, testnet: bool = True, priority: int = 2) -> dict:
    """Execute a market order on HyperLiquid."""
    key_env = 'HL_TESTNET_PRIVATE_KEY' if testnet else 'HL_PRIVATE_KEY'
    private_key = os.environ.get(key_env) or os.environ.get('HYPERLIQUID_PRIVATE_KEY', '')

    if not private_key:
        return {
            'success': False,
            'error': f'No private key found in env var {key_env}',
            'network': 'testnet' if testnet else 'mainnet',
        }
    if not private_key.startswith('0x'):
        private_key = '0x' + private_key

    base_url = TESTNET_URL if testnet else MAINNET_URL
    size_map = SIZE_MAP_TESTNET if testnet else SIZE_MAP_MAINNET
    usd_amount = size_map.get(size, size_map['quarter'])
    network = 'testnet' if testnet else 'mainnet'

    try:
        from eth_account import Account
        account = Account.from_key(private_key)
        address = account.address
    except Exception as e:
        return {'success': False, 'error': f'Invalid private key: {e}', 'network': network}

    # Get account state (check both perp and spot for unified accounts)
    try:
        state = hl_post(base_url, {"type": "clearinghouseState", "user": address})
        margin = state.get("crossMarginSummary", {})
        balance = float(margin.get("accountValue", 0))
        # Unified accounts keep funds in spot — check spot balance too
        if balance == 0:
            spot_state = hl_post(base_url, {"type": "spotClearinghouseState", "user": address})
            for b in spot_state.get("balances", []):
                if b.get("coin") == "USDC":
                    balance = float(b.get("total", 0))
                    break
    except Exception as e:
        return {'success': False, 'error': f'Failed to get account state: {e}', 'network': network}

    if balance < usd_amount * 1.1:
        return {
            'success': False,
            'error': f'Insufficient balance: ${balance:.2f} < ${usd_amount:.2f} required',
            'balance': balance,
            'network': network,
            'address': address,
        }

    # Get oracle price (more reliable than mid on testnet)
    try:
        ctx = hl_post(base_url, {"type": "metaAndAssetCtxs"})
        meta_universe = ctx[0]["universe"]
        asset_ctxs = ctx[1]
        price = 0.0
        sz_decimals = 6
        for i, asset in enumerate(meta_universe):
            if asset["name"] == symbol:
                oracle = float(asset_ctxs[i].get("oraclePx", 0))
                mark = float(asset_ctxs[i].get("markPx", 0))
                price = oracle if oracle > 0 else mark
                sz_decimals = asset.get("szDecimals", 6)
                break
    except Exception as e:
        return {'success': False, 'error': f'Failed to get price: {e}', 'network': network}

    if price <= 0:
        return {'success': False, 'error': f'No price for {symbol}', 'network': network}

    is_buy = direction.upper() == 'LONG'
    asset_size = round(usd_amount / price, sz_decimals)

    # Execute via monkey-patched SDK (bypass buggy Info.__init__ on testnet)
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

            # ── Order type selection ──
            # Priority 1 = urgent → market (IOC with wider slippage)
            # Priority 2/3 = normal → limit (GTC with tight slippage) + market fallback
            use_market = (priority == 1)

            # Tick size: BTC=1 (integer), most others vary
            # For simplicity, round to integer for prices >1000, 2 decimals otherwise
            def round_price(px):
                if px > 1000:
                    return int(round(px))
                elif px > 10:
                    return round(px, 1)
                else:
                    return round(px, 2)

            if use_market:
                # MARKET ORDER — IOC with 0.5% slippage
                slippage = 1 + MARKET_SLIPPAGE if is_buy else 1 - MARKET_SLIPPAGE
                market_px = round_price(price * slippage)
                response = exchange.order(symbol, is_buy, asset_size, market_px, {'limit': {'tif': 'Ioc'}})
                order_type = 'market'
            else:
                # LIMIT ORDER — GTC with 0.1% slippage (better entry)
                slippage = 1 + LIMIT_SLIPPAGE if is_buy else 1 - LIMIT_SLIPPAGE
                limit_px = round_price(price * slippage)
                response = exchange.order(symbol, is_buy, asset_size, limit_px, {'limit': {'tif': 'Gtc'}})
                order_type = 'limit'

            if response.get("status") != "ok":
                return {
                    'success': False, 'error': str(response.get("response", "unknown")),
                    'network': network, 'balance': balance, 'price': price, 'order_type': order_type,
                }

            # Extract order status
            order_id = None
            filled = False
            try:
                statuses = response["response"]["data"]["statuses"]
                status0 = statuses[0]
                if "filled" in status0:
                    order_id = status0["filled"].get("oid")
                    filled = True
                elif "resting" in status0:
                    order_id = status0["resting"].get("oid")
                    filled = False
            except (KeyError, IndexError, TypeError):
                pass

            # ── LIMIT FILL TIMEOUT → MARKET FALLBACK ──
            if order_type == 'limit' and not filled and order_id is not None:
                # Wait up to FILL_TIMEOUT seconds for the limit to fill
                deadline = time.time() + FILL_TIMEOUT
                while time.time() < deadline:
                    time.sleep(5)
                    try:
                        # Check if order is still open
                        open_orders = hl_post(base_url, {"type": "openOrders", "user": address})
                        still_open = any(str(o.get("oid")) == str(order_id) for o in open_orders)
                        if not still_open:
                            filled = True
                            break
                    except Exception:
                        pass

                if not filled:
                    # Cancel the limit order and place market
                    try:
                        # Find asset index for cancel
                        asset_idx = None
                        for i, a in enumerate(meta_universe):
                            if a["name"] == symbol:
                                asset_idx = i
                                break
                        if asset_idx is not None:
                            exchange.cancel(symbol, order_id)
                    except Exception:
                        pass  # Best effort cancel

                    # Market fallback with wider slippage
                    market_slippage = 1 + MARKET_SLIPPAGE if is_buy else 1 - MARKET_SLIPPAGE
                    market_px = round_price(price * market_slippage)
                    try:
                        response2 = exchange.order(symbol, is_buy, asset_size, market_px, {'limit': {'tif': 'Ioc'}})
                        if response2.get("status") == "ok":
                            try:
                                s2 = response2["response"]["data"]["statuses"][0]
                                if "filled" in s2:
                                    order_id = s2["filled"].get("oid")
                                    filled = True
                                    order_type = 'market_fallback'
                            except (KeyError, IndexError, TypeError):
                                pass
                    except Exception:
                        pass  # Market fallback failed, return limit result

        finally:
            _hl_info.Info.__init__ = _orig_init

        return {
            'success': True,
            'order_id': order_id,
            'order_type': order_type,
            'filled': filled,
            'network': network,
            'usd_amount': usd_amount,
            'asset_size': asset_size,
            'price': price,
            'balance_before': balance,
            'score': score,
            'address': address,
        }

    except Exception as e:
        return {
            'success': False, 'error': str(e),
            'network': network, 'balance': balance, 'price': price,
        }


def main():
    parser = argparse.ArgumentParser(description='Execute HyperLiquid order from swarm')
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--direction', required=True, choices=['LONG', 'SHORT'])
    parser.add_argument('--size', default='quarter', choices=['full', 'half', 'quarter'])
    parser.add_argument('--score', type=float, default=0.0)
    parser.add_argument('--mainnet', action='store_true')
    parser.add_argument('--priority', type=int, default=2, choices=[1, 2, 3])
    args = parser.parse_args()

    result = execute_order(
        symbol=args.symbol, direction=args.direction,
        size=args.size, score=args.score, testnet=not args.mainnet,
        priority=args.priority,
    )
    print(json.dumps(result))
    sys.exit(0 if result.get('success') else 1)


if __name__ == '__main__':
    main()
