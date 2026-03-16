"""
hl_execute.py — Execute swarm orders on HyperLiquid.

Uses HLConnector for mainnet, direct REST API for testnet (SDK bug workaround).
Called by pty-manager.ts when user confirms a swarm EXECUTE decision.
Outputs JSON to stdout for the TypeScript caller to parse.

Order logic:
  - Default: LIMIT order with 0.1% slippage (better entry price)
  - If limit not filled within FILL_TIMEOUT (60s): cancel + retry as IOC market
  - Priority 1 signals skip limit and go straight to market (time-sensitive)

Pre-mainnet safety features:
  - Exposure limits: max 5 simultaneous positions, max 30% capital at risk
  - Slippage logging: post-fill comparison vs expected price → slippage_log.jsonl
  - Contrary position close: auto-close opposite direction before opening new
  - Trailing stop: optional per-strategy, activates after price moves in favor

Usage:
    python hl_execute.py --symbol BTC --direction LONG --size half --score 0.74
    python hl_execute.py --symbol ETH --direction SHORT --size full --score 0.85 --mainnet
    python hl_execute.py --symbol BTC --direction LONG --size full --score 0.90 --priority 1
    python hl_execute.py --symbol BTC --direction LONG --size half --trailing
"""
import argparse
import json
import os
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
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

# ── Exposure limits ──────────────────────────────────────────────────────────
MAX_POSITIONS = 5         # Max simultaneous open positions
MAX_RISK_PCT = 30.0       # Max % of total equity at risk across all positions

# ── Slippage logging ────────────────────────────────────────────────────────
SLIPPAGE_LOG = Path(__file__).parent / "crypto" / "data" / "slippage_log.jsonl"
SLIPPAGE_WARN_BPS = 10    # Warn if slippage > 10 bps (0.10%)

# ── Trailing stop defaults ──────────────────────────────────────────────────
TRAILING_ACTIVATION_PCT = 1.5   # Activate after price moves 1.5% in favor
TRAILING_DISTANCE_PCT = 0.8     # Trail 0.8% behind the high water mark
TRAILING_POLL_INTERVAL = 5      # Check price every 5 seconds


def hl_post(base_url: str, payload: dict) -> dict:
    """POST to HyperLiquid info API."""
    resp = requests.post(f"{base_url}/info", json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


# ── Feature 1: Exposure limits ──────────────────────────────────────────────

def check_exposure_limits(base_url: str, address: str, new_usd: float, leverage: float = 10.0) -> dict:
    """Check if opening a new position would exceed exposure limits.

    Returns: {'allowed': bool, 'reason': str, 'positions': int, 'risk_pct': float}
    """
    try:
        state = hl_post(base_url, {"type": "clearinghouseState", "user": address})
        positions = state.get("assetPositions", [])
        open_positions = [p for p in positions if float(p["position"]["szi"]) != 0]
        num_open = len(open_positions)

        margin = state.get("crossMarginSummary", {})
        equity = float(margin.get("accountValue", 0))
        if equity <= 0:
            return {'allowed': False, 'reason': 'No equity in account', 'positions': num_open, 'risk_pct': 0}

        # Current total notional at risk
        total_notional = sum(
            abs(float(p["position"]["szi"])) * float(p["position"]["entryPx"])
            for p in open_positions
        )
        # Add proposed position
        new_notional = total_notional + new_usd * leverage
        risk_pct = (new_notional / equity) * 100

        if num_open >= MAX_POSITIONS:
            return {
                'allowed': False,
                'reason': f'Max positions reached: {num_open}/{MAX_POSITIONS}',
                'positions': num_open, 'risk_pct': risk_pct,
            }

        if risk_pct > MAX_RISK_PCT * 100 / leverage:
            # Actual comparison: total_notional / equity > MAX_RISK_PCT/100
            # risk_pct here is notional/equity*100, but we want position_value/equity
            pass

        # Simpler: sum of margin used (notional/leverage) / equity
        margin_used = total_notional / leverage
        new_margin = margin_used + new_usd
        margin_pct = (new_margin / equity) * 100

        if margin_pct > MAX_RISK_PCT:
            return {
                'allowed': False,
                'reason': f'Risk limit exceeded: {margin_pct:.1f}% > {MAX_RISK_PCT}% of capital at risk',
                'positions': num_open, 'risk_pct': margin_pct,
            }

        return {
            'allowed': True, 'reason': 'OK',
            'positions': num_open, 'risk_pct': margin_pct,
        }

    except Exception as e:
        # On error, allow the trade but log warning (don't block due to API glitch)
        print(f"WARNING: Exposure check failed ({e}), proceeding with trade", file=sys.stderr)
        return {'allowed': True, 'reason': f'Check failed: {e}', 'positions': -1, 'risk_pct': -1}


# ── Feature 2: Slippage logging ─────────────────────────────────────────────

def log_slippage(symbol: str, side: str, expected_price: float, fill_price: float, order_id, order_type: str):
    """Log slippage between expected and actual fill price."""
    if expected_price <= 0 or fill_price <= 0:
        return

    slippage_pct = (fill_price - expected_price) / expected_price * 100
    slippage_bps = abs(slippage_pct) * 100  # basis points

    # For buys, positive slippage = worse (paid more). For sells, negative = worse.
    is_adverse = (side == 'BUY' and fill_price > expected_price) or \
                 (side == 'SELL' and fill_price < expected_price)

    entry = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'symbol': symbol,
        'side': side,
        'expected_price': expected_price,
        'fill_price': fill_price,
        'slippage_pct': round(slippage_pct, 4),
        'slippage_bps': round(slippage_bps, 2),
        'adverse': is_adverse,
        'order_id': order_id,
        'order_type': order_type,
    }

    SLIPPAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(SLIPPAGE_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')

    if slippage_bps > SLIPPAGE_WARN_BPS:
        print(f"WARNING: Slippage {slippage_bps:.1f} bps on {symbol} {side} "
              f"(expected={expected_price}, fill={fill_price})", file=sys.stderr)


def get_fill_price(base_url: str, address: str, order_id, symbol: str) -> float:
    """Get the actual fill price for an order from user fills."""
    try:
        fills = hl_post(base_url, {"type": "userFills", "user": address})
        # Find fills matching our order (most recent first)
        for fill in reversed(fills):
            if str(fill.get("oid")) == str(order_id):
                return float(fill.get("px", 0))
            # Also match by startPosition if oid doesn't match
            if fill.get("coin") == symbol and fill.get("oid") == order_id:
                return float(fill.get("px", 0))
    except Exception as e:
        print(f"WARNING: Could not get fill price: {e}", file=sys.stderr)
    return 0.0


# ── Feature 3: Close contrary position ──────────────────────────────────────

def close_contrary_position(exchange, base_url: str, address: str, symbol: str,
                            new_direction: str, meta_universe: list, round_price) -> dict | None:
    """If there's an open position in the opposite direction, close it first.

    Returns close result dict or None if no contrary position exists.
    """
    try:
        state = hl_post(base_url, {"type": "clearinghouseState", "user": address})
        positions = state.get("assetPositions", [])

        for pos in positions:
            p = pos["position"]
            if p.get("coin") != symbol:
                continue

            szi = float(p.get("szi", 0))
            if szi == 0:
                continue

            # szi > 0 = LONG position, szi < 0 = SHORT position
            current_is_long = szi > 0
            new_is_long = new_direction.upper() == 'LONG'

            # Only close if directions are opposite
            if current_is_long == new_is_long:
                return None  # Same direction — let duplicate check handle it

            # Close the contrary position with market order
            close_size = abs(szi)
            close_side = not current_is_long  # Opposite side to close

            # Get current price for the close
            ctx = hl_post(base_url, {"type": "metaAndAssetCtxs"})
            close_price = 0.0
            for i, asset in enumerate(ctx[0]["universe"]):
                if asset["name"] == symbol:
                    close_price = float(ctx[1][i].get("markPx", 0))
                    break

            if close_price <= 0:
                return {'closed': False, 'error': 'No price for close'}

            # Market close with slippage
            slippage = 1 + MARKET_SLIPPAGE if close_side else 1 - MARKET_SLIPPAGE
            close_px = round_price(close_price * slippage)

            resp = exchange.order(symbol, close_side, close_size, close_px,
                                  {'limit': {'tif': 'Ioc'}}, reduce_only=True)

            if resp.get("status") == "ok":
                direction_str = 'LONG' if current_is_long else 'SHORT'
                print(f"CLOSED contrary {direction_str} {symbol} ({close_size} @ ~{close_price}) "
                      f"before opening {new_direction}", file=sys.stderr)
                return {
                    'closed': True,
                    'closed_direction': direction_str,
                    'closed_size': close_size,
                    'closed_price': close_price,
                }
            else:
                return {'closed': False, 'error': str(resp)}

    except Exception as e:
        print(f"WARNING: Contrary position check failed: {e}", file=sys.stderr)
        return {'closed': False, 'error': str(e)}

    return None


# ── Feature 4: Trailing stop ────────────────────────────────────────────────

def start_trailing_stop(base_url: str, address: str, exchange, symbol: str,
                        is_long: bool, entry_price: float, asset_size: float,
                        activation_pct: float = TRAILING_ACTIVATION_PCT,
                        distance_pct: float = TRAILING_DISTANCE_PCT,
                        round_price=None):
    """Start a background thread that monitors price and adjusts stop.

    Activates when price moves activation_pct% in favor, then trails at distance_pct%.
    Runs until position is closed or thread is stopped.
    """
    def _trail():
        high_water = entry_price if is_long else entry_price
        activated = False
        activation_price = entry_price * (1 + activation_pct / 100) if is_long \
            else entry_price * (1 - activation_pct / 100)

        print(f"TRAILING STOP started for {symbol} ({'LONG' if is_long else 'SHORT'}) "
              f"entry={entry_price}, activation={activation_price:.2f}", file=sys.stderr)

        while True:
            try:
                time.sleep(TRAILING_POLL_INTERVAL)

                # Get current price
                ctx = hl_post(base_url, {"type": "metaAndAssetCtxs"})
                current_price = 0.0
                for i, asset in enumerate(ctx[0]["universe"]):
                    if asset["name"] == symbol:
                        current_price = float(ctx[1][i].get("markPx", 0))
                        break

                if current_price <= 0:
                    continue

                # Check if position still exists
                state = hl_post(base_url, {"type": "clearinghouseState", "user": address})
                has_position = False
                for pos in state.get("assetPositions", []):
                    if pos["position"].get("coin") == symbol and float(pos["position"].get("szi", 0)) != 0:
                        has_position = True
                        break

                if not has_position:
                    print(f"TRAILING STOP: {symbol} position closed, stopping monitor", file=sys.stderr)
                    return

                if is_long:
                    high_water = max(high_water, current_price)
                    if not activated and current_price >= activation_price:
                        activated = True
                        print(f"TRAILING STOP ACTIVATED: {symbol} LONG at {current_price:.2f} "
                              f"(+{(current_price/entry_price - 1)*100:.2f}%)", file=sys.stderr)

                    if activated:
                        trail_stop = high_water * (1 - distance_pct / 100)
                        if current_price <= trail_stop:
                            # Close position
                            close_px = round_price(current_price * (1 - MARKET_SLIPPAGE)) if round_price \
                                else int(current_price * (1 - MARKET_SLIPPAGE))
                            try:
                                resp = exchange.order(symbol, False, asset_size, close_px,
                                                     {'limit': {'tif': 'Ioc'}}, reduce_only=True)
                                pnl_pct = (current_price / entry_price - 1) * 100
                                print(f"TRAILING STOP TRIGGERED: {symbol} LONG closed at {current_price:.2f} "
                                      f"(PnL: {pnl_pct:+.2f}%, HWM: {high_water:.2f})", file=sys.stderr)
                            except Exception as e:
                                print(f"TRAILING STOP close failed: {e}", file=sys.stderr)
                            return
                else:
                    high_water = min(high_water, current_price)
                    if not activated and current_price <= activation_price:
                        activated = True
                        print(f"TRAILING STOP ACTIVATED: {symbol} SHORT at {current_price:.2f} "
                              f"(+{(1 - current_price/entry_price)*100:.2f}%)", file=sys.stderr)

                    if activated:
                        trail_stop = high_water * (1 + distance_pct / 100)
                        if current_price >= trail_stop:
                            close_px = round_price(current_price * (1 + MARKET_SLIPPAGE)) if round_price \
                                else int(current_price * (1 + MARKET_SLIPPAGE))
                            try:
                                resp = exchange.order(symbol, True, asset_size, close_px,
                                                     {'limit': {'tif': 'Ioc'}}, reduce_only=True)
                                pnl_pct = (1 - current_price / entry_price) * 100
                                print(f"TRAILING STOP TRIGGERED: {symbol} SHORT closed at {current_price:.2f} "
                                      f"(PnL: {pnl_pct:+.2f}%, HWM: {high_water:.2f})", file=sys.stderr)
                            except Exception as e:
                                print(f"TRAILING STOP close failed: {e}", file=sys.stderr)
                            return

            except Exception as e:
                print(f"TRAILING STOP error: {e}", file=sys.stderr)
                time.sleep(10)

    thread = threading.Thread(target=_trail, daemon=True, name=f"trail_{symbol}")
    thread.start()
    return thread


# ── Main execution ──────────────────────────────────────────────────────────

def execute_order(symbol: str, direction: str, size: str, score: float,
                  testnet: bool = True, priority: int = 2,
                  sl_price: float = 0, tp_price: float = 0,
                  trailing: bool = False,
                  trailing_activation: float = TRAILING_ACTIVATION_PCT,
                  trailing_distance: float = TRAILING_DISTANCE_PCT) -> dict:
    """Execute an order on HyperLiquid with safety checks and optional trailing stop."""
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

    # ── FEATURE 1: Exposure limit check ──
    exposure = check_exposure_limits(base_url, address, usd_amount)
    if not exposure['allowed']:
        return {
            'success': False,
            'error': f'EXPOSURE BLOCKED: {exposure["reason"]}',
            'network': network,
            'balance': balance,
            'address': address,
            'exposure': exposure,
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

            # Tick size helper
            def round_price(px):
                if px > 1000:
                    return int(round(px))
                elif px > 10:
                    return round(px, 1)
                else:
                    return round(px, 2)

            # ── FEATURE 3: Close contrary position ──
            contrary_result = close_contrary_position(
                exchange, base_url, address, symbol, direction, meta_universe, round_price
            )

            # ── Order type selection ──
            # Priority 1 = urgent → market (IOC with wider slippage)
            # Priority 2/3 = normal → limit (GTC with tight slippage) + market fallback
            use_market = (priority == 1)
            expected_price = price  # Save for slippage comparison

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
                deadline = time.time() + FILL_TIMEOUT
                while time.time() < deadline:
                    time.sleep(5)
                    try:
                        open_orders = hl_post(base_url, {"type": "openOrders", "user": address})
                        still_open = any(str(o.get("oid")) == str(order_id) for o in open_orders)
                        if not still_open:
                            filled = True
                            break
                    except Exception:
                        pass

                if not filled:
                    try:
                        exchange.cancel(symbol, order_id)
                    except Exception:
                        pass

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
                        pass

            # ── FEATURE 2: Log slippage post-fill ──
            slippage_info = None
            if filled and order_id is not None:
                time.sleep(1)  # Brief wait for fill data to propagate
                fill_price = get_fill_price(base_url, address, order_id, symbol)
                if fill_price > 0:
                    side = 'BUY' if is_buy else 'SELL'
                    log_slippage(symbol, side, expected_price, fill_price, order_id, order_type)
                    slip_bps = abs(fill_price - expected_price) / expected_price * 10000
                    slippage_info = {
                        'expected_price': expected_price,
                        'fill_price': fill_price,
                        'slippage_bps': round(slip_bps, 2),
                    }

            # ── Place SL/TP via atomic bulk_orders (normalTpsl grouping) ──
            sl_oid = None
            tp_oid = None
            if filled and asset_size > 0 and (sl_price > 0 or tp_price > 0):
                close_side = not is_buy
                tpsl_orders = []

                # Entry order placeholder (already filled, but needed for grouping)
                # For normalTpsl: first order = parent (entry), rest = children (SL/TP)
                # Since entry is already filled, we use positionTpsl instead
                # positionTpsl attaches SL/TP to existing position
                if sl_price > 0:
                    sl_px = round_price(sl_price)
                    tpsl_orders.append({
                        'coin': symbol,
                        'is_buy': close_side,
                        'sz': asset_size,
                        'limit_px': sl_px,
                        'order_type': {'trigger': {'triggerPx': float(sl_px), 'isMarket': True, 'tpsl': 'sl'}},
                        'reduce_only': True,
                    })
                if tp_price > 0:
                    tp_px = round_price(tp_price)
                    tpsl_orders.append({
                        'coin': symbol,
                        'is_buy': close_side,
                        'sz': asset_size,
                        'limit_px': tp_px,
                        'order_type': {'trigger': {'triggerPx': float(tp_px), 'isMarket': False, 'tpsl': 'tp'}},
                        'reduce_only': True,
                    })

                try:
                    tpsl_resp = exchange.bulk_orders(tpsl_orders, grouping='positionTpsl')
                    if tpsl_resp.get("status") == "ok":
                        statuses = tpsl_resp.get("response", {}).get("data", {}).get("statuses", [])
                        idx = 0
                        if sl_price > 0 and idx < len(statuses):
                            s = statuses[idx]
                            sl_oid = s.get("resting", s.get("filled", {})).get("oid")
                            idx += 1
                        if tp_price > 0 and idx < len(statuses):
                            s = statuses[idx]
                            tp_oid = s.get("resting", s.get("filled", {})).get("oid")
                    else:
                        print(f"SL/TP bulk_orders failed: {tpsl_resp}", file=sys.stderr)
                        # Fallback: place individually
                        for req in tpsl_orders:
                            try:
                                resp = exchange.order(
                                    req['coin'], req['is_buy'], req['sz'], req['limit_px'],
                                    req['order_type'], reduce_only=True)
                                tpsl_type = req['order_type']['trigger']['tpsl']
                                if resp.get("status") == "ok":
                                    oid = resp.get("response", {}).get("data", {}).get("statuses", [{}])[0]
                                    oid = oid.get("resting", oid.get("filled", {})).get("oid")
                                    if tpsl_type == 'sl':
                                        sl_oid = oid
                                    else:
                                        tp_oid = oid
                            except Exception as e:
                                print(f"{tpsl_type.upper()} fallback failed: {e}", file=sys.stderr)
                except Exception as e:
                    print(f"SL/TP placement failed: {e}", file=sys.stderr)

            # ── FEATURE 4: Start trailing stop if requested ──
            trailing_active = False
            if trailing and filled and asset_size > 0:
                start_trailing_stop(
                    base_url, address, exchange, symbol, is_long=is_buy,
                    entry_price=price, asset_size=asset_size,
                    activation_pct=trailing_activation, distance_pct=trailing_distance,
                    round_price=round_price,
                )
                trailing_active = True

        finally:
            _hl_info.Info.__init__ = _orig_init

        result = {
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
            'exposure': exposure,
            'stopLoss': {'price': sl_price, 'oid': sl_oid} if sl_price > 0 else None,
            'takeProfit': {'price': tp_price, 'oid': tp_oid} if tp_price > 0 else None,
        }
        if slippage_info:
            result['slippage'] = slippage_info
        if contrary_result:
            result['contrary_closed'] = contrary_result
        if trailing_active:
            result['trailing_stop'] = {
                'active': True,
                'activation_pct': trailing_activation,
                'distance_pct': trailing_distance,
            }
        return result

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
    parser.add_argument('--sl', type=float, default=0, help='Stop loss price')
    parser.add_argument('--tp', type=float, default=0, help='Take profit price')
    parser.add_argument('--trailing', action='store_true', help='Enable trailing stop')
    parser.add_argument('--trail-activation', type=float, default=TRAILING_ACTIVATION_PCT,
                        help=f'Trailing stop activation %% (default: {TRAILING_ACTIVATION_PCT})')
    parser.add_argument('--trail-distance', type=float, default=TRAILING_DISTANCE_PCT,
                        help=f'Trailing stop distance %% (default: {TRAILING_DISTANCE_PCT})')
    args = parser.parse_args()

    result = execute_order(
        symbol=args.symbol, direction=args.direction,
        size=args.size, score=args.score, testnet=not args.mainnet,
        priority=args.priority, sl_price=args.sl, tp_price=args.tp,
        trailing=args.trailing,
        trailing_activation=args.trail_activation,
        trailing_distance=args.trail_distance,
    )
    print(json.dumps(result))

    # If trailing stop is active, keep process alive
    if result.get('trailing_stop', {}).get('active'):
        print("Trailing stop active — monitoring price...", file=sys.stderr)
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass
    else:
        sys.exit(0 if result.get('success') else 1)


if __name__ == '__main__':
    main()
