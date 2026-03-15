#!/usr/bin/env python3
"""
Strategy Scanner — Evalúa estrategias backtested en datos live.

Corre cada 5 min desde pty-manager.ts. Fetch velas de Railway API,
calcula indicadores, y escribe señales al swarm bus si detecta setup.

Strategies evaluadas:
  - VolatilitySqueezeV2 (BTC 1h): TTM Squeeze + ADX + min squeeze bars

Exit codes:
  0 = sin señal (normal)
  1 = error
  10 = señal escrita al bus (parseable por pty-manager)
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Fix Windows cp1252 encoding issues
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import numpy as np
import pandas as pd

try:
    import pandas_ta as ta
except ImportError:
    print("ERROR: pandas_ta not installed. Run: pip install pandas_ta")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)

# ── Config ──────────────────────────────────────────────────────────────────
RAILWAY_URL = os.environ.get(
    "RAILWAY_URL", "https://chic-encouragement-production.up.railway.app"
)
BUS_FILE = os.environ.get("BUS_FILE", "")
CANDLE_COUNT = 120  # Need ~100+ bars for indicators to warm up

# Strategies to evaluate: (symbol, interval, strategy_fn)
STRATEGIES = []


# ── Data fetching ───────────────────────────────────────────────────────────
def fetch_candles(symbol: str, interval: str = "1h", count: int = CANDLE_COUNT) -> pd.DataFrame | None:
    """Fetch OHLCV from Railway API → DataFrame."""
    url = f"{RAILWAY_URL}/api/hl/candles/{symbol}?interval={interval}&count={count}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        candles = data.get("candles", [])
        if len(candles) < 50:
            print(f"  [{symbol}] Solo {len(candles)} velas — insuficiente")
            return None
        df = pd.DataFrame(candles)
        df = df.rename(columns={"t": "timestamp", "o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
        df["Open"] = df["Open"].astype(float)
        df["High"] = df["High"].astype(float)
        df["Low"] = df["Low"].astype(float)
        df["Close"] = df["Close"].astype(float)
        df["Volume"] = df["Volume"].astype(float)
        return df
    except Exception as e:
        print(f"  [{symbol}] Error fetching candles: {e}")
        return None


# ── VolatilitySqueezeV2 ────────────────────────────────────────────────────
def eval_volatility_squeeze_v2(df: pd.DataFrame, symbol: str) -> dict | None:
    """
    Evalúa VolatilitySqueezeV2 en las últimas barras.
    Retorna dict con señal si hay setup, None si no.

    Parámetros (idénticos al backtest):
      BB 20/2.0, KC 20/1.2, ADX 14 (threshold 20),
      min_squeeze_bars=2, momentum period=9
      SL 2.0x ATR, TP 4.0x ATR
    """
    if len(df) < 50:
        return None

    close = df["Close"].reset_index(drop=True)
    high = df["High"].reset_index(drop=True)
    low = df["Low"].reset_index(drop=True)

    # ── Bollinger Bands (20, 2.0) ──
    bb = ta.bbands(close, length=20, std=2.0)
    if bb is None or bb.empty:
        return None
    bb_upper = bb.iloc[:, 2]  # BBU
    bb_lower = bb.iloc[:, 0]  # BBL

    # ── Keltner Channel (20, 1.2) ──
    ema = ta.ema(close, length=20)
    atr_kc = ta.atr(high, low, close, length=20)
    if ema is None or atr_kc is None:
        return None
    kc_upper = ema + 1.2 * atr_kc
    kc_lower = ema - 1.2 * atr_kc

    # ── ATR 14 para SL/TP ──
    atr14 = ta.atr(high, low, close, length=14)

    # ── Momentum (close.diff(9)) ──
    momentum = close.diff(9)

    # ── ADX 14 ──
    adx_df = ta.adx(high, low, close, length=14)
    if adx_df is None or adx_df.empty:
        return None
    adx = adx_df["ADX_14"]

    # ── Squeeze: BB dentro de KC ──
    squeeze = ((bb_upper < kc_upper) & (bb_lower > kc_lower)).astype(float)

    # ── Squeeze count (barras consecutivas) ──
    sqz_count = np.zeros(len(squeeze))
    for i in range(len(squeeze)):
        if squeeze.iloc[i] == 1.0:
            sqz_count[i] = (sqz_count[i - 1] + 1.0) if i > 0 else 1.0

    # ── Evaluar las últimas 3 barras para squeeze release ──
    # Buscamos: barra[-2] en squeeze, barra[-1] fuera de squeeze
    for offset in [1, 2, 3]:  # Check last 3 bars (delay tolerance)
        idx = len(df) - offset
        if idx < 2:
            continue

        sqz_prev = squeeze.iloc[idx - 1]
        sqz_now = squeeze.iloc[idx]
        squeeze_released = (sqz_prev == 1.0) and (sqz_now == 0.0)

        if not squeeze_released:
            continue

        # Barras en squeeze antes del release
        bars_in_squeeze = sqz_count[idx - 1]
        if bars_in_squeeze < 2:
            continue

        # ADX > 20
        adx_val = adx.iloc[idx]
        if pd.isna(adx_val) or adx_val < 20:
            continue

        # Momentum direction
        mom_val = momentum.iloc[idx]
        if pd.isna(mom_val) or mom_val == 0:
            continue

        atr_val = atr14.iloc[idx]
        if pd.isna(atr_val) or atr_val <= 0:
            continue

        price = close.iloc[idx]
        direction = "LONG" if mom_val > 0 else "SHORT"

        # SL/TP calculation
        if direction == "LONG":
            sl = round(price - atr_val * 2.0, 2)
            tp = round(price + atr_val * 4.0, 2)
        else:
            sl = round(price + atr_val * 2.0, 2)
            tp = round(price - atr_val * 4.0, 2)

        # Confidence: base 0.70, +0.05 per extra squeeze bar (max 0.90)
        confidence = min(0.90, 0.70 + (bars_in_squeeze - 2) * 0.05)
        # ADX bonus
        if adx_val > 30:
            confidence = min(0.95, confidence + 0.05)

        return {
            "symbol": symbol,
            "direction": direction,
            "confidence": round(confidence, 2),
            "strategy": "VolatilitySqueezeV2",
            "reason": (
                f"Squeeze release tras {int(bars_in_squeeze)} barras, "
                f"ADX={adx_val:.1f}, momentum={'positivo' if mom_val > 0 else 'negativo'} ({mom_val:.1f})"
            ),
            "price": round(price, 2),
            "stopLoss": sl,
            "takeProfit": tp,
            "atr": round(atr_val, 2),
            "bars_ago": offset,  # How many bars ago the signal fired
            "indicators": {
                "adx": round(adx_val, 1),
                "momentum": round(mom_val, 2),
                "squeeze_bars": int(bars_in_squeeze),
                "atr14": round(atr_val, 2),
                "bb_upper": round(bb_upper.iloc[idx], 2),
                "bb_lower": round(bb_lower.iloc[idx], 2),
                "kc_upper": round(kc_upper.iloc[idx], 2),
                "kc_lower": round(kc_lower.iloc[idx], 2),
            },
        }

    # No setup found — print current state for debugging
    idx = len(df) - 1
    sqz_val = squeeze.iloc[idx] if idx < len(squeeze) else 0
    adx_now = adx.iloc[idx] if idx < len(adx) and not pd.isna(adx.iloc[idx]) else 0
    mom_now = momentum.iloc[idx] if idx < len(momentum) and not pd.isna(momentum.iloc[idx]) else 0
    bars = sqz_count[idx] if idx < len(sqz_count) else 0
    print(f"  [{symbol}] VSQv2: squeeze={'ON' if sqz_val == 1 else 'OFF'} ({int(bars)} bars), ADX={adx_now:.1f}, mom={mom_now:.1f}")
    return None


# ── Register strategies ─────────────────────────────────────────────────────
STRATEGIES = [
    ("BTC", "1h", eval_volatility_squeeze_v2),
    # Add more as they pass validation:
    # ("ETH", "1h", eval_volatility_squeeze_v2),
    # ("BTC", "1h", eval_rsi_band),
]


# ── Bus writer ──────────────────────────────────────────────────────────────
def write_signal_to_bus(signal: dict, bus_file: str):
    """Append a signal event to the swarm bus JSONL file."""
    event = {
        "id": f"scanner-{signal['strategy'].lower()}-{uuid.uuid4().hex[:8]}",
        "channel": "realtime",
        "from": "signal-scanner",
        "type": "signal",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ttl": 300,
        "priority": 2,
        "payload": {
            "symbol": signal["symbol"],
            "direction": signal["direction"],
            "confidence": signal["confidence"],
            "reason": signal["reason"],
            "data": {
                "strategy": signal["strategy"],
                "price": signal["price"],
                "stopLoss": signal["stopLoss"],
                "takeProfit": signal["takeProfit"],
                "atr": signal["atr"],
                "bars_ago": signal["bars_ago"],
                "indicators": signal["indicators"],
            },
        },
    }

    # Ensure directory exists
    Path(bus_file).parent.mkdir(parents=True, exist_ok=True)

    with open(bus_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")

    print(f"  SIGNAL WRITTEN: {signal['symbol']} {signal['direction']} "
          f"conf={signal['confidence']} strategy={signal['strategy']}")
    return event


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    print(f"\n{'='*50}")
    print(f"  Strategy Scanner — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"{'='*50}")

    if not BUS_FILE:
        # Auto-detect bus file from project root
        script_dir = Path(__file__).resolve().parent
        project_root = script_dir.parent.parent  # scripts/ → opengravity-app/ → OpenGravity/
        bus_path = project_root / ".claude" / "swarm-bus" / "events.jsonl"
    else:
        bus_path = Path(BUS_FILE)

    print(f"  Bus: {bus_path}")
    print(f"  Railway: {RAILWAY_URL}")
    print(f"  Strategies: {len(STRATEGIES)}")

    signals_found = []

    for symbol, interval, strategy_fn in STRATEGIES:
        print(f"\n  Evaluating {symbol} {interval} → {strategy_fn.__name__}")
        df = fetch_candles(symbol, interval)
        if df is None:
            continue

        print(f"  [{symbol}] {len(df)} candles, last close: {df['Close'].iloc[-1]:.2f}")

        result = strategy_fn(df, symbol)
        if result:
            event = write_signal_to_bus(result, str(bus_path))
            signals_found.append(event)

    print(f"\n{'='*50}")
    if signals_found:
        print(f"  {len(signals_found)} señal(es) escritas al bus")
        # Output JSON summary to stdout for pty-manager to parse
        print(f"SCANNER_SIGNALS={json.dumps([s['payload']['symbol'] + ':' + s['payload']['direction'] for s in signals_found])}")
        sys.exit(10)  # Exit 10 = signals found
    else:
        print("  Sin señales — mercado sin setup activo")
        sys.exit(0)


if __name__ == "__main__":
    main()
