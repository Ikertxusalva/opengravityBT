#!/usr/bin/env python3
"""
Strategy Scanner — Evalua estrategias backtested en datos live.

Corre cada 5 min desde pty-manager.ts. Fetch velas de Railway API,
calcula indicadores, y escribe senales al swarm bus si detecta setup.

Strategies evaluadas:
  - VolatilitySqueezeV2 (BTC 1h): TTM Squeeze + ADX + min squeeze bars
  - VolatilitySqueezeV3 (BTC 1h): V2 + volume filter + BB 1.8std + KC 1.5
  - VolatilitySqueeze V1 (BTC 1h): Squeeze basico sin filtros extra
  - RSIBand (BNB 4h): RSI BB crossover + ADX
  - HeatMapRotation (ETH, SOL, DOGE, LINK, BNB, ADA 1h): Correlacion BTC + RSI + trend
  - HeatMapRotation BTC (BTC 4h): BTC self-trend + RSI pullback entry
  - LiquidationCascade (TSLA 1h): RSI oversold bounce on momentum stocks

Exit codes:
  0 = sin senal (normal)
  1 = error
  10 = senal escrita al bus (parseable por pty-manager)
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

# Cache de candles para evitar fetch duplicados (symbol:interval -> df)
_candle_cache: dict[str, pd.DataFrame] = {}


# ── Data fetching ───────────────────────────────────────────────────────────
def fetch_candles(symbol: str, interval: str = "1h", count: int = CANDLE_COUNT) -> pd.DataFrame | None:
    """Fetch OHLCV from Railway API -> DataFrame. Cached per symbol:interval."""
    cache_key = f"{symbol}:{interval}"
    if cache_key in _candle_cache:
        return _candle_cache[cache_key]

    url = f"{RAILWAY_URL}/api/hl/candles/{symbol}?interval={interval}&count={count}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        candles = data.get("candles", [])
        if len(candles) < 50:
            print(f"  [{symbol}] Solo {len(candles)} velas -- insuficiente")
            return None
        df = pd.DataFrame(candles)
        df = df.rename(columns={"t": "timestamp", "o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = df[col].astype(float)
        _candle_cache[cache_key] = df
        return df
    except Exception as e:
        print(f"  [{symbol}] Error fetching candles: {e}")
        return None


# ── Shared: build signal dict ───────────────────────────────────────────────
def make_signal(symbol, direction, confidence, strategy, reason, price, sl, tp, atr_val, bars_ago, indicators):
    return {
        "symbol": symbol,
        "direction": direction,
        "confidence": round(min(0.95, max(0.50, confidence)), 2),
        "strategy": strategy,
        "reason": reason,
        "price": round(price, 2),
        "stopLoss": round(sl, 2),
        "takeProfit": round(tp, 2),
        "atr": round(atr_val, 2),
        "bars_ago": bars_ago,
        "indicators": indicators,
    }


# ── Shared: squeeze detection helpers ───────────────────────────────────────
def compute_squeeze(close, high, low, bb_len=20, bb_std=2.0, kc_len=20, kc_mult=1.2):
    """Compute BB, KC, squeeze, and squeeze count arrays."""
    bb = ta.bbands(close, length=bb_len, std=bb_std)
    if bb is None or bb.empty:
        return None
    bb_upper = bb.iloc[:, 2]
    bb_lower = bb.iloc[:, 0]

    ema = ta.ema(close, length=kc_len)
    atr_kc = ta.atr(high, low, close, length=kc_len)
    if ema is None or atr_kc is None:
        return None
    kc_upper = ema + kc_mult * atr_kc
    kc_lower = ema - kc_mult * atr_kc

    squeeze = ((bb_upper < kc_upper) & (bb_lower > kc_lower)).astype(float)

    sqz_count = np.zeros(len(squeeze))
    for i in range(len(squeeze)):
        if squeeze.iloc[i] == 1.0:
            sqz_count[i] = (sqz_count[i - 1] + 1.0) if i > 0 else 1.0

    return {
        "bb_upper": bb_upper, "bb_lower": bb_lower,
        "kc_upper": kc_upper, "kc_lower": kc_lower,
        "squeeze": squeeze, "sqz_count": sqz_count,
    }


def find_squeeze_release(squeeze, sqz_count, min_bars=0, max_offset=3):
    """Find most recent squeeze release within last max_offset bars.
    Returns (idx, bars_in_squeeze, offset) or None."""
    for offset in range(1, max_offset + 1):
        idx = len(squeeze) - offset
        if idx < 2:
            continue
        sqz_prev = squeeze.iloc[idx - 1]
        sqz_now = squeeze.iloc[idx]
        if sqz_prev == 1.0 and sqz_now == 0.0:
            bars = sqz_count[idx - 1]
            if bars >= min_bars:
                return idx, int(bars), offset
    return None


# ═══════════════════════════════════════════════════════════════════════════
# STRATEGY EVALUATORS
# ═══════════════════════════════════════════════════════════════════════════

# ── 1. VolatilitySqueezeV2 (BTC 1h) ────────────────────────────────────────
# BB 20/2.0, KC 20/1.2, ADX 14 > 20, min_squeeze=2, mom(9), SL 2x ATR, TP 4x ATR
def eval_volatility_squeeze_v2(df: pd.DataFrame, symbol: str) -> dict | None:
    if len(df) < 50:
        return None
    close = df["Close"].reset_index(drop=True)
    high = df["High"].reset_index(drop=True)
    low = df["Low"].reset_index(drop=True)

    sq = compute_squeeze(close, high, low, bb_len=20, bb_std=2.0, kc_len=20, kc_mult=1.2)
    if sq is None:
        return None

    atr14 = ta.atr(high, low, close, length=14)
    momentum = close.diff(9)
    adx_df = ta.adx(high, low, close, length=14)
    if adx_df is None or adx_df.empty:
        return None
    adx = adx_df["ADX_14"]

    release = find_squeeze_release(sq["squeeze"], sq["sqz_count"], min_bars=2)
    if release:
        idx, bars, offset = release
        adx_val = adx.iloc[idx]
        mom_val = momentum.iloc[idx]
        atr_val = atr14.iloc[idx]
        if pd.isna(adx_val) or adx_val < 20:
            pass
        elif pd.isna(mom_val) or mom_val == 0 or pd.isna(atr_val) or atr_val <= 0:
            pass
        else:
            price = close.iloc[idx]
            d = "LONG" if mom_val > 0 else "SHORT"
            sl = price - atr_val * 2.0 if d == "LONG" else price + atr_val * 2.0
            tp = price + atr_val * 4.0 if d == "LONG" else price - atr_val * 4.0
            conf = min(0.90, 0.70 + (bars - 2) * 0.05)
            if adx_val > 30:
                conf += 0.05
            return make_signal(symbol, d, conf, "VolatilitySqueezeV2",
                f"Squeeze release {bars} bars, ADX={adx_val:.1f}, mom={'pos' if mom_val > 0 else 'neg'} ({mom_val:.1f})",
                price, sl, tp, atr_val, offset,
                {"adx": round(adx_val, 1), "momentum": round(mom_val, 2), "squeeze_bars": bars, "atr14": round(atr_val, 2)})

    # Debug output
    idx = len(df) - 1
    sqz_val = sq["squeeze"].iloc[idx]
    adx_now = adx.iloc[idx] if not pd.isna(adx.iloc[idx]) else 0
    mom_now = momentum.iloc[idx] if not pd.isna(momentum.iloc[idx]) else 0
    bars = int(sq["sqz_count"][idx])
    print(f"  [{symbol}] VSQv2: squeeze={'ON' if sqz_val == 1 else 'OFF'} ({bars}b), ADX={adx_now:.1f}, mom={mom_now:.1f}")
    return None


# ── 2. VolatilitySqueezeV3 (BTC 1h) ────────────────────────────────────────
# BB 20/1.8, KC 20/1.5, ADX 14 > 18, min_squeeze=2, volume > 1.3x avg, SL 1.5x, TP 3.5x
def eval_volatility_squeeze_v3(df: pd.DataFrame, symbol: str) -> dict | None:
    if len(df) < 50:
        return None
    close = df["Close"].reset_index(drop=True)
    high = df["High"].reset_index(drop=True)
    low = df["Low"].reset_index(drop=True)
    volume = df["Volume"].reset_index(drop=True)

    sq = compute_squeeze(close, high, low, bb_len=20, bb_std=1.8, kc_len=20, kc_mult=1.5)
    if sq is None:
        return None

    atr14 = ta.atr(high, low, close, length=14)
    mom = ta.mom(close, length=9)
    adx_df = ta.adx(high, low, close, length=14)
    vol_ma = ta.sma(volume, length=20)
    if adx_df is None or adx_df.empty or vol_ma is None:
        return None
    adx = adx_df.iloc[:, 0]

    release = find_squeeze_release(sq["squeeze"], sq["sqz_count"], min_bars=2)
    if release:
        idx, bars, offset = release
        adx_val = adx.iloc[idx]
        mom_val = mom.iloc[idx] if mom is not None else np.nan
        atr_val = atr14.iloc[idx]
        vol_now = volume.iloc[idx]
        vol_avg = vol_ma.iloc[idx]

        if (not pd.isna(adx_val) and adx_val >= 18 and
            not pd.isna(mom_val) and mom_val != 0 and
            not pd.isna(atr_val) and atr_val > 0 and
            not pd.isna(vol_avg) and vol_avg > 0 and vol_now > 1.3 * vol_avg):

            price = close.iloc[idx]
            d = "LONG" if mom_val > 0 else "SHORT"
            sl = price - atr_val * 1.5 if d == "LONG" else price + atr_val * 1.5
            tp = price + atr_val * 3.5 if d == "LONG" else price - atr_val * 3.5
            conf = min(0.90, 0.72 + (bars - 2) * 0.04)
            vol_ratio = vol_now / vol_avg
            if vol_ratio > 2.0:
                conf += 0.05
            return make_signal(symbol, d, conf, "VolatilitySqueezeV3",
                f"Squeeze release {bars}b, ADX={adx_val:.1f}, vol={vol_ratio:.1f}x avg",
                price, sl, tp, atr_val, offset,
                {"adx": round(adx_val, 1), "momentum": round(mom_val, 2), "squeeze_bars": bars,
                 "vol_ratio": round(vol_ratio, 2)})

    idx = len(df) - 1
    sqz_val = sq["squeeze"].iloc[idx]
    bars = int(sq["sqz_count"][idx])
    print(f"  [{symbol}] VSQv3: squeeze={'ON' if sqz_val == 1 else 'OFF'} ({bars}b)")
    return None


# ── 3. VolatilitySqueeze V1 (BTC, AVAX 1h) ─────────────────────────────────
# BB 20/2.0, KC 20/1.2, no ADX filter, no min squeeze, mom(9), SL 2x, TP 4x
def eval_volatility_squeeze_v1(df: pd.DataFrame, symbol: str) -> dict | None:
    if len(df) < 50:
        return None
    close = df["Close"].reset_index(drop=True)
    high = df["High"].reset_index(drop=True)
    low = df["Low"].reset_index(drop=True)

    sq = compute_squeeze(close, high, low, bb_len=20, bb_std=2.0, kc_len=20, kc_mult=1.2)
    if sq is None:
        return None

    atr14 = ta.atr(high, low, close, length=14)
    momentum = close.diff(9)

    # V1: no min_bars filter, just check for squeeze release
    release = find_squeeze_release(sq["squeeze"], sq["sqz_count"], min_bars=0)
    if release:
        idx, bars, offset = release
        mom_val = momentum.iloc[idx]
        atr_val = atr14.iloc[idx]
        if not pd.isna(mom_val) and mom_val != 0 and not pd.isna(atr_val) and atr_val > 0:
            price = close.iloc[idx]
            d = "LONG" if mom_val > 0 else "SHORT"
            sl = price - atr_val * 2.0 if d == "LONG" else price + atr_val * 2.0
            tp = price + atr_val * 4.0 if d == "LONG" else price - atr_val * 4.0
            # V1 lower confidence than V2 (no ADX confirmation)
            conf = 0.62 + min(0.13, bars * 0.03)
            return make_signal(symbol, d, conf, "VolatilitySqueezeV1",
                f"Squeeze release {bars}b, mom={'pos' if mom_val > 0 else 'neg'} ({mom_val:.1f})",
                price, sl, tp, atr_val, offset,
                {"momentum": round(mom_val, 2), "squeeze_bars": bars})

    idx = len(df) - 1
    sqz_val = sq["squeeze"].iloc[idx]
    bars = int(sq["sqz_count"][idx])
    print(f"  [{symbol}] VSQv1: squeeze={'ON' if sqz_val == 1 else 'OFF'} ({bars}b)")
    return None


# ── 4. RSIBand (BNB 4h) ────────────────────────────────────────────────────
# RSI(14) smoothed EMA(5), BB del RSI (lookback 50, 1.0 std), ADX>20
# LONG: RSI cruza por encima de upper band. SHORT: cruza por debajo de lower.
# SL 1.5x ATR, TP 2.5x ATR
def eval_rsi_band(df: pd.DataFrame, symbol: str) -> dict | None:
    if len(df) < 60:
        return None
    close = df["Close"].reset_index(drop=True)
    high = df["High"].reset_index(drop=True)
    low = df["Low"].reset_index(drop=True)

    # RSI smoothed
    rsi_raw = ta.rsi(close, length=14)
    if rsi_raw is None:
        return None
    rsi_raw = rsi_raw.fillna(50)
    rsi_ema = ta.ema(rsi_raw, length=5)
    if rsi_ema is None:
        return None
    rsi_ema = rsi_ema.fillna(50)

    # BB sobre el RSI
    rsi_series = pd.Series(rsi_ema.values)
    rsi_ma = rsi_series.rolling(50, min_periods=20).mean().fillna(50)
    rsi_std = rsi_series.rolling(50, min_periods=20).std().fillna(10)
    ub = (rsi_ma + rsi_std * 1.0).values  # bb_mult=10 -> 1.0
    lb = (rsi_ma - rsi_std * 1.0).values

    # ADX
    adx_df = ta.adx(high, low, close, length=14)
    if adx_df is None or adx_df.empty:
        return None
    adx = adx_df.iloc[:, 0].fillna(0).values

    # ATR
    atr14 = ta.atr(high, low, close, length=14)
    if atr14 is None:
        return None

    # Check last 3 bars for crossover
    for offset in range(1, 4):
        idx = len(df) - offset
        if idx < 2:
            continue

        rsi_now = rsi_ema.iloc[idx]
        rsi_prev = rsi_ema.iloc[idx - 1]
        ub_now = ub[idx]
        ub_prev = ub[idx - 1]
        lb_now = lb[idx]
        lb_prev = lb[idx - 1]
        adx_val = adx[idx]
        atr_val = atr14.iloc[idx]
        price = close.iloc[idx]

        if pd.isna(atr_val) or atr_val <= 0 or adx_val < 20:
            continue

        cross_above = (rsi_prev <= ub_prev) and (rsi_now > ub_now) and (rsi_now < 85)
        cross_below = (rsi_prev >= lb_prev) and (rsi_now < lb_now) and (rsi_now > 15)

        if cross_above:
            sl = price - atr_val * 1.5
            tp = price + atr_val * 2.5
            conf = 0.68
            if adx_val > 30:
                conf += 0.07
            return make_signal(symbol, "LONG", conf, "RSIBand",
                f"RSI crossover upper band, RSI={rsi_now:.1f}, ADX={adx_val:.1f}",
                price, sl, tp, atr_val, offset,
                {"rsi": round(rsi_now, 1), "rsi_upper": round(ub_now, 1), "rsi_lower": round(lb_now, 1),
                 "adx": round(adx_val, 1)})

        if cross_below:
            sl = price + atr_val * 1.5
            tp = price - atr_val * 2.5
            conf = 0.68
            if adx_val > 30:
                conf += 0.07
            return make_signal(symbol, "SHORT", conf, "RSIBand",
                f"RSI crossover lower band, RSI={rsi_now:.1f}, ADX={adx_val:.1f}",
                price, sl, tp, atr_val, offset,
                {"rsi": round(rsi_now, 1), "rsi_upper": round(ub_now, 1), "rsi_lower": round(lb_now, 1),
                 "adx": round(adx_val, 1)})

    idx = len(df) - 1
    print(f"  [{symbol}] RSIBand: RSI={rsi_ema.iloc[idx]:.1f}, UB={ub[idx]:.1f}, LB={lb[idx]:.1f}, ADX={adx[idx]:.1f}")
    return None


# ── 5. HeatMapRotation (ETH, SOL 1h) ───────────────────────────────────────
# Correlacion con BTC > 0.6 + BTC trending up (> SMA20) + RSI < 60 -> LONG
# Exit: corr < 0.2 or RSI > 70
# Para el scanner: detectamos ENTRY condition (no exit)
# Necesita BTC candles como referencia
def eval_heatmap_rotation(df: pd.DataFrame, symbol: str) -> dict | None:
    if len(df) < 50 or symbol == "BTC":
        return None  # No aplica a BTC (corr con si mismo = 1)

    # Fetch BTC candles (cached)
    btc_df = fetch_candles("BTC", "1h")
    if btc_df is None or len(btc_df) < 50:
        return None

    close = df["Close"].reset_index(drop=True)
    high = df["High"].reset_index(drop=True)
    low = df["Low"].reset_index(drop=True)
    btc_close = btc_df["Close"].reset_index(drop=True)

    # Align lengths
    min_len = min(len(close), len(btc_close))
    close = close.iloc[-min_len:].reset_index(drop=True)
    high = high.iloc[-min_len:].reset_index(drop=True)
    low = low.iloc[-min_len:].reset_index(drop=True)
    btc_close = btc_close.iloc[-min_len:].reset_index(drop=True)

    # Correlation rolling 30 bars
    corr = close.rolling(30).corr(btc_close)

    # BTC trend: BTC > SMA(20)
    btc_sma20 = ta.sma(btc_close, length=20)
    if btc_sma20 is None:
        return None
    btc_up = (btc_close > btc_sma20).astype(float)

    # RSI del activo
    rsi_raw = ta.rsi(close, length=14)
    if rsi_raw is None:
        return None

    # ATR para SL/TP
    atr14 = ta.atr(high, low, close, length=14)
    if atr14 is None:
        return None

    # Check last 3 bars for entry
    for offset in range(1, 4):
        idx = len(close) - offset
        if idx < 2:
            continue

        corr_val = corr.iloc[idx]
        btc_trend = btc_up.iloc[idx]
        rsi_val = rsi_raw.iloc[idx]
        atr_val = atr14.iloc[idx]
        price = close.iloc[idx]

        if pd.isna(corr_val) or pd.isna(rsi_val) or pd.isna(atr_val) or atr_val <= 0:
            continue

        # Entry: corr > 0.6, BTC up, RSI < 60
        if corr_val >= 0.6 and btc_trend == 1.0 and rsi_val < 60:
            # Also check that previous bar didn't meet criteria (fresh signal)
            if idx > 0:
                prev_corr = corr.iloc[idx - 1]
                prev_btc = btc_up.iloc[idx - 1]
                prev_rsi = rsi_raw.iloc[idx - 1]
                if (not pd.isna(prev_corr) and prev_corr >= 0.6 and
                    prev_btc == 1.0 and not pd.isna(prev_rsi) and prev_rsi < 60):
                    continue  # Not a fresh signal

            sl = price - atr_val * 2.0
            tp = price + atr_val * 3.0
            conf = 0.65
            if corr_val > 0.8:
                conf += 0.08
            if rsi_val < 40:
                conf += 0.05
            return make_signal(symbol, "LONG", conf, "HeatMapRotation",
                f"BTC corr={corr_val:.2f}, BTC trending up, RSI={rsi_val:.1f}",
                price, sl, tp, atr_val, offset,
                {"correlation": round(corr_val, 3), "rsi": round(rsi_val, 1),
                 "btc_price": round(btc_close.iloc[idx], 2)})

    idx = len(close) - 1
    corr_now = corr.iloc[idx] if not pd.isna(corr.iloc[idx]) else 0
    rsi_now = rsi_raw.iloc[idx] if not pd.isna(rsi_raw.iloc[idx]) else 50
    btc_now = "UP" if btc_up.iloc[idx] == 1 else "DOWN"
    print(f"  [{symbol}] HeatMap: corr={corr_now:.2f}, BTC={btc_now}, RSI={rsi_now:.1f}")
    return None


# ── 6. HeatMapRotation BTC (BTC 4h) ──────────────────────────────────────
# BTC self-mode: Sharpe 2.15, WR 78.7%, 122 trades en 2y-4h
# Entry: BTC > SMA(20) + RSI pullback (35-55) + ADX > 20
# SL 2x ATR, TP 3x ATR
def eval_heatmap_btc(df: pd.DataFrame, symbol: str) -> dict | None:
    if len(df) < 50 or symbol != "BTC":
        return None

    close = df["Close"].reset_index(drop=True)
    high = df["High"].reset_index(drop=True)
    low = df["Low"].reset_index(drop=True)

    sma20 = ta.sma(close, length=20)
    rsi = ta.rsi(close, length=14)
    atr14 = ta.atr(high, low, close, length=14)
    adx_df = ta.adx(high, low, close, length=14)
    if any(x is None for x in [sma20, rsi, atr14, adx_df]):
        return None
    adx = adx_df.iloc[:, 0]

    for offset in range(1, 4):
        idx = len(close) - offset
        if idx < 2:
            continue

        price = close.iloc[idx]
        sma_val = sma20.iloc[idx]
        rsi_val = rsi.iloc[idx]
        rsi_prev = rsi.iloc[idx - 1]
        atr_val = atr14.iloc[idx]
        adx_val = adx.iloc[idx]

        if any(pd.isna(x) for x in [sma_val, rsi_val, rsi_prev, atr_val, adx_val]):
            continue
        if atr_val <= 0:
            continue

        # BTC trending up + RSI pullback zone + ADX confirms trend
        if price > sma_val and 35 <= rsi_val <= 55 and adx_val > 20:
            # Fresh: previous RSI was outside pullback zone
            if rsi_prev > 55 or rsi_prev < 35:
                sl = price - atr_val * 2.0
                tp = price + atr_val * 3.0
                conf = 0.72
                if adx_val > 30:
                    conf += 0.05
                if rsi_val < 45:
                    conf += 0.05
                return make_signal(symbol, "LONG", conf, "HeatMapBTC4h",
                    f"BTC pullback RSI={rsi_val:.1f}, above SMA20, ADX={adx_val:.1f}",
                    price, sl, tp, atr_val, offset,
                    {"rsi": round(rsi_val, 1), "sma20": round(sma_val, 2),
                     "adx": round(adx_val, 1)})

    idx = len(close) - 1
    rsi_now = rsi.iloc[idx] if not pd.isna(rsi.iloc[idx]) else 50
    print(f"  [{symbol}] HeatMapBTC4h: RSI={rsi_now:.1f}, price vs SMA20={'ABOVE' if close.iloc[idx] > sma20.iloc[idx] else 'BELOW'}")
    return None


# ── 7. LiquidationCascade (TSLA 1h) ──────────────────────────────────────
# Sharpe 1.79, +74.3%, WR 84.6% en TSLA. Oversold RSI bounce.
# Entry: RSI < 30 + price near 20-period low + volume spike 2x
# SL 1.5x ATR, TP 3x ATR
def eval_liquidation_cascade(df: pd.DataFrame, symbol: str) -> dict | None:
    if len(df) < 50:
        return None

    close = df["Close"].reset_index(drop=True)
    high = df["High"].reset_index(drop=True)
    low = df["Low"].reset_index(drop=True)
    volume = df["Volume"].reset_index(drop=True)

    rsi = ta.rsi(close, length=14)
    atr14 = ta.atr(high, low, close, length=14)
    vol_ma = ta.sma(volume, length=20)
    swing_low = low.rolling(20).min()

    if any(x is None for x in [rsi, atr14, vol_ma]):
        return None

    for offset in range(1, 4):
        idx = len(close) - offset
        if idx < 2:
            continue

        price = close.iloc[idx]
        rsi_val = rsi.iloc[idx]
        rsi_prev = rsi.iloc[idx - 1]
        atr_val = atr14.iloc[idx]
        vol_now = volume.iloc[idx]
        vol_avg = vol_ma.iloc[idx]
        sw_low = swing_low.iloc[idx]

        if any(pd.isna(x) for x in [rsi_val, rsi_prev, atr_val, vol_avg, sw_low]):
            continue
        if atr_val <= 0 or vol_avg <= 0:
            continue

        vol_ratio = vol_now / vol_avg

        # RSI oversold bounce + near swing low + volume spike
        if rsi_val < 30 and price <= sw_low * 1.005 and vol_ratio > 2.0:
            # Fresh: was not oversold before
            if rsi_prev >= 30:
                sl = price - atr_val * 1.5
                tp = price + atr_val * 3.0
                conf = 0.70
                if rsi_val < 25:
                    conf += 0.05
                if vol_ratio > 3.0:
                    conf += 0.05
                return make_signal(symbol, "LONG", conf, "LiquidationCascade",
                    f"RSI oversold={rsi_val:.1f}, near swing low, vol={vol_ratio:.1f}x",
                    price, sl, tp, atr_val, offset,
                    {"rsi": round(rsi_val, 1), "vol_ratio": round(vol_ratio, 2),
                     "swing_low": round(sw_low, 2)})

    idx = len(close) - 1
    rsi_now = rsi.iloc[idx] if not pd.isna(rsi.iloc[idx]) else 50
    print(f"  [{symbol}] LiqCascade: RSI={rsi_now:.1f}")
    return None


# ═══════════════════════════════════════════════════════════════════════════
# STRATEGY REGISTRY — symbol, interval, evaluator
# ═══════════════════════════════════════════════════════════════════════════
STRATEGIES = [
    # Volatility Squeeze family — BTC 1h
    ("BTC",  "1h", eval_volatility_squeeze_v2),
    ("BTC",  "1h", eval_volatility_squeeze_v3),
    ("BTC",  "1h", eval_volatility_squeeze_v1),
    # RSIBand — BNB 4h
    ("BNB",  "4h", eval_rsi_band),
    # HeatMap Rotation — altcoins 1h (uses BTC correlation)
    ("ETH",  "1h", eval_heatmap_rotation),
    ("SOL",  "1h", eval_heatmap_rotation),
    ("DOGE", "1h", eval_heatmap_rotation),
    ("LINK", "1h", eval_heatmap_rotation),
    ("BNB",  "1h", eval_heatmap_rotation),
    ("ADA",  "1h", eval_heatmap_rotation),
    # HeatMap BTC self-mode — BTC 4h (Sharpe 2.15, WR 78.7%)
    ("BTC",  "4h", eval_heatmap_btc),
    # LiquidationCascade — US momentum stocks (TSLA Sharpe 1.79, WR 84.6%)
    ("TSLA", "1h", eval_liquidation_cascade),
    ("AMD",  "1h", eval_liquidation_cascade),
    ("QQQ",  "1h", eval_liquidation_cascade),
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

    Path(bus_file).parent.mkdir(parents=True, exist_ok=True)
    with open(bus_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")

    print(f"  >> SIGNAL: {signal['symbol']} {signal['direction']} conf={signal['confidence']} [{signal['strategy']}]")
    return event


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    print(f"\n{'='*55}")
    print(f"  Strategy Scanner -- {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"{'='*55}")

    if not BUS_FILE:
        script_dir = Path(__file__).resolve().parent
        project_root = script_dir.parent.parent
        bus_path = project_root / ".claude" / "swarm-bus" / "events.jsonl"
    else:
        bus_path = Path(BUS_FILE)

    print(f"  Bus: {bus_path}")
    print(f"  Railway: {RAILWAY_URL}")
    print(f"  Strategies: {len(STRATEGIES)} evaluations across {len(set(s[0] for s in STRATEGIES))} symbols")

    signals_found = []
    seen_strategies = set()  # Avoid duplicate signals per strategy per run

    for symbol, interval, strategy_fn in STRATEGIES:
        # Deduplicate: only one signal per strategy+symbol per scan
        dedup_key = f"{strategy_fn.__name__}:{symbol}"
        if dedup_key in seen_strategies:
            continue

        print(f"\n  {symbol} {interval} -- {strategy_fn.__name__}")
        df = fetch_candles(symbol, interval)
        if df is None:
            continue

        print(f"  [{symbol}] {len(df)} candles, last: {df['Close'].iloc[-1]:.2f}")

        result = strategy_fn(df, symbol)
        if result:
            # Check if we already have a signal for this symbol in this run
            existing = [s for s in signals_found if s['payload']['symbol'] == symbol]
            if len(existing) >= 2:
                print(f"  [{symbol}] Skipping -- already 2 signals for {symbol}")
                continue
            event = write_signal_to_bus(result, str(bus_path))
            signals_found.append(event)
            seen_strategies.add(dedup_key)

    print(f"\n{'='*55}")
    if signals_found:
        summary = [f"{s['payload']['symbol']}:{s['payload']['direction']}" for s in signals_found]
        print(f"  {len(signals_found)} signal(s): {', '.join(summary)}")
        print(f"SCANNER_SIGNALS={json.dumps(summary)}")
        sys.exit(10)
    else:
        print("  Sin senales -- mercado sin setup activo")
        sys.exit(0)


if __name__ == "__main__":
    main()
