# Technical Specifications for Funding Rate Strategies

**Purpose**: Exact coding requirements for backtesting and live trading
**Target**: Python backtesting.py + HyperLiquid API
**Updated**: 2026-03-15

---

## STRATEGY #1: FundingRateArbitrage (Delta-Neutral Carry)

### Function Signature

```python
class FundingRateArbitrage(Strategy):
    """
    Delta-neutral funding rate arbitrage.
    Primary Entry: funding_rate > threshold_pct
    Exit: funding_rate < exit_threshold OR hold_bars exceeded
    """
```

### Initialization (Required Data)

```python
def init(self):
    # Input: DataFrame must have column "Funding" (% annualized)
    # If missing: strategy operates without trades (safe no-op)

    if "Funding" in self.data.df.columns:
        self.funding_data = self.data.df["Funding"].values.copy()
        self.funding = self.I(lambda: self.funding_data, name="Funding")
        self._has_funding = True
    else:
        self.funding = None
        self._has_funding = False

    self._bars_held = 0
```

### Entry Logic

```python
def next(self):
    if not self._has_funding:
        return

    current_funding = self.funding[-1]  # Current bar's funding rate

    if np.isnan(current_funding):
        return

    price = self.data.Close[-1]

    # EXISTING POSITION MANAGEMENT
    if self.position:
        self._bars_held += 1

        # Exit condition 1: hold_bars exceeded
        if self._bars_held >= self.hold_bars:
            self.position.close()
            self._bars_held = 0
            return

        # Exit condition 2: funding dropped below exit threshold
        if current_funding < self.exit_threshold_pct:
            self.position.close()
            self._bars_held = 0
            return

        # Exit condition 3: funding flipped to negative
        if current_funding < 0:
            self.position.close()
            self._bars_held = 0
            return

    # NO POSITION - CHECK FOR ENTRY
    self._bars_held = 0

    # LONG entry: funding positive and above threshold
    if current_funding > self.threshold_pct:
        self.buy(
            size=0.95,
            sl=price * (1 - self.stop_loss_pct),
            tp=price * (1 + self.take_profit_pct)
        )

    # SHORT entry: funding very negative (alternative)
    # Note: Only for true delta-neutral setup with spot hedge
    elif current_funding < -self.threshold_pct:
        self.sell(
            size=0.95,
            sl=price * (1 + self.stop_loss_pct),
            tp=price * (1 - self.take_profit_pct)
        )
```

### Parameter Ranges

```python
class FundingRateArbitrage(Strategy):
    strategy_name = "Funding Rate Arbitrage"
    strategy_type = "Funding Arbitrage"

    # BASELINE (from spec)
    threshold_pct        = 0.01   # % annualized, trigger entry
    exit_threshold_pct   = 0.005  # % annualized, trigger exit
    stop_loss_pct        = 0.03   # 3% SL below entry for LONG
    take_profit_pct      = 0.06   # 6% TP above entry for LONG
    hold_bars            = 10     # max bars to hold position

    # OPTIMIZATION RANGES FOR GENETIC ALGORITHM
    # threshold_pct:      [0.005, 0.010, 0.015, 0.020, 0.030]
    # exit_threshold_pct: [0.001, 0.005, 0.010]
    # hold_bars:          [5, 10, 20, 30, 50]
    # stop_loss_pct:      [0.01, 0.02, 0.03, 0.05]
    # take_profit_pct:    [0.03, 0.06, 0.10, 0.15]
```

### Data Requirements

```python
# Input DataFrame columns REQUIRED:
required_columns = [
    "Open",     # float
    "High",     # float
    "Low",      # float
    "Close",    # float
    "Volume",   # float (can be 0 if not used)
    "Funding"   # float (% annualized, positive or negative)
]

# Funding column source:
# ├─ Historical: HyperLiquid API fundingHistory endpoint
# │  └─ Returns: time, fundingRate (per 8h), premium
# │  └─ Annualize: funding_8h × 3 × 365
# └─ Simulated (if real not available):
#    funding_proxy = (close - sma(close, 20)) / sma(close, 20) * 0.1
#    (When perp > average, funding positive)
```

### Backtest Configuration

```python
from backtesting import Backtest, Strategy
import yfinance as yf

# Download data
data = yf.download("BTC-USD", start="2024-01-01", end="2025-12-31",
                   interval="4h", auto_adjust=True)
data.columns = ["Close", "High", "Low", "Open", "Volume"]
data = data[["Open", "High", "Low", "Close", "Volume"]].dropna()

# Add funding data (if available from HL API)
# data["Funding"] = load_funding_from_hl_api("BTC", data.index)

# Run backtest
bt = Backtest(
    data,
    FundingRateArbitrage,
    cash=10_000,
    commission=0.001,  # 0.1% per trade (HL maker fee)
    exclusive_orders=True,
    finalize_trades=True
)

stats = bt.run()
print(stats)

# Key output metrics to check:
# stats.Return (%)
# stats.Sharpe Ratio
# stats.Max. Drawdown (%)
# stats.Win Rate (%)
# stats.# Trades
```

---

## STRATEGY #2: FundingMeanReversion (Extreme Reversal)

### Function Signature

```python
class FundingMeanReversion(Strategy):
    """
    Contra el crowd: exploit extremos de funding.
    Entry: |funding| > trigger_pct
    Exit: |funding| < exit_pct OR hold_bars exceeded
    Direction: opposite to funding (SELL if funding positive, BUY if negative)
    """
```

### Initialization

```python
def init(self):
    if "Funding" in self.data.df.columns:
        self.funding_data = self.data.df["Funding"].values.copy()
        self.funding = self.I(lambda: self.funding_data, name="Funding")
        self._has_funding = True
    else:
        self.funding = None
        self._has_funding = False

    self._bars_held = 0
    self._entry_direction = None  # 1 for LONG, -1 for SHORT
```

### Entry and Exit Logic

```python
def next(self):
    if not self._has_funding:
        return

    f = self.funding[-1]
    if np.isnan(f):
        return

    price = self.data.Close[-1]

    # EXISTING POSITION MANAGEMENT
    if self.position:
        self._bars_held += 1

        # Exit condition 1: funding normalized (back to range)
        if abs(f) < self.exit_pct:
            self.position.close()
            self._bars_held = 0
            self._entry_direction = None
            return

        # Exit condition 2: timeout
        if self._bars_held >= self.hold_bars:
            self.position.close()
            self._bars_held = 0
            self._entry_direction = None
            return

    # NO POSITION - CHECK FOR ENTRY
    self._bars_held = 0
    self._entry_direction = None

    # ENTRY CONDITION: Extreme funding (long-side panic)
    if f > self.trigger_pct:
        # Longs are paying insane funding → shorts too leveraged
        # We SHORT to collect from the panic
        self.sell(
            size=0.95,
            sl=price * (1 + self.stop_loss_pct),      # SL ABOVE for short
            tp=price * (1 - self.take_profit_pct)     # TP BELOW for short
        )
        self._entry_direction = -1

    # ENTRY CONDITION: Extreme funding (short-side panic)
    elif f < -self.trigger_pct:
        # Shorts are paying insane funding → longs too leveraged
        # We LONG to collect from the panic
        self.buy(
            size=0.95,
            sl=price * (1 - self.stop_loss_pct),      # SL BELOW for long
            tp=price * (1 + self.take_profit_pct)     # TP ABOVE for long
        )
        self._entry_direction = 1
```

### Parameter Ranges

```python
class FundingMeanReversion(Strategy):
    strategy_name = "Funding Mean Reversion"
    strategy_type = "Funding Mean Reversion"

    # BASELINE
    trigger_pct     = 100.0   # % annualized (extreme threshold)
    exit_pct        = 25.0    # % annualized (normalization)
    hold_bars       = 24      # 1 day in 1h timeframe
    stop_loss_pct   = 0.04    # 4% protection
    take_profit_pct = 0.08    # 8% profit target

    # OPTIMIZATION RANGES
    # trigger_pct:     [25, 50, 75, 100, 150, 200]
    # exit_pct:        [10, 15, 20, 25, 35]
    # hold_bars:       [6, 12, 24, 48]
    # stop_loss_pct:   [0.02, 0.04, 0.06, 0.10]
    # take_profit_pct: [0.04, 0.08, 0.12, 0.20]
```

### When to Use

```
Best in: Bullish years with funding extremes (2021-2022)
Good in: Normal years with occasional spikes
Bad in: Bear markets with persistent negative funding
```

---

## STRATEGY #3: FundingOIDivergence (Signal Confluence)

### Function Signature

```python
class FundingOIDivergence(Strategy):
    """
    Capitalize on funding + OI divergence signals.
    Capitulation (BUY):  funding down + OI down in window
    Euforia (SELL):      funding up + OI up in window
    Requires: Funding AND OpenInterest columns in data
    """
```

### Initialization

```python
def init(self):
    has_funding = "Funding" in self.data.df.columns
    has_oi      = "OI" in self.data.df.columns

    if has_funding and has_oi:
        # Pre-compute funding delta and OI delta
        funding_arr = self.data.df["Funding"].values.copy()
        oi_arr      = self.data.df["OI"].values.copy()
        n = len(funding_arr)
        w = self.window

        # Funding delta in percentage points (not relative)
        fdelta = np.zeros(n)
        for i in range(w, n):
            fdelta[i] = funding_arr[i] - funding_arr[i - w]

        # OI relative delta (fraction change)
        oi_delta_rel = np.zeros(n)
        for i in range(w, n):
            base = oi_arr[i - w]
            if base != 0:
                oi_delta_rel[i] = (oi_arr[i] - base) / abs(base)

        self.funding = self.I(lambda: funding_arr, name="Funding")
        self.fdelta = self.I(lambda: fdelta, name="FundingDelta")
        self.oi_delta_rel = self.I(lambda: oi_delta_rel, name="OI_DeltaRel")
        self._has_data = True
    else:
        self.funding = None
        self.fdelta = None
        self.oi_delta_rel = None
        self._has_data = False

    self._bars_held = 0
```

### Entry and Exit Logic

```python
def next(self):
    if not self._has_data:
        return

    fd = self.fdelta[-1]      # funding delta (pp)
    oid = self.oi_delta_rel[-1]  # OI delta (fraction)

    if np.isnan(fd) or np.isnan(oid):
        return

    price = self.data.Close[-1]

    # POSITION MANAGEMENT
    if self.position:
        self._bars_held += 1
        if self._bars_held >= self.hold_bars:
            self.position.close()
            self._bars_held = 0
        return

    self._bars_held = 0

    # CAPITULATION SIGNAL (BUY)
    # Funding drops + OI drops = shorts covering, longs liquidating
    # → Next move: longs cover, price rallies
    if fd <= -self.funding_drop_threshold and oid <= -self.oi_drop_threshold:
        self.buy(
            size=0.95,
            sl=price * (1 - self.stop_loss_pct),
            tp=price * (1 + self.take_profit_pct)
        )

    # EUFORIA SIGNAL (SELL)
    # Funding rises + OI rises = longs apalancados, shorts running
    # → Next move: profit taking, reversal
    elif fd >= self.funding_drop_threshold and oid >= self.oi_drop_threshold:
        self.sell(
            size=0.95,
            sl=price * (1 + self.stop_loss_pct),
            tp=price * (1 - self.take_profit_pct)
        )
```

### Parameter Ranges

```python
class FundingOIDivergence(Strategy):
    strategy_name = "Funding OI Divergence"
    strategy_type = "Funding Divergence"

    # BASELINE
    window = 20                      # 20-bar lookback (20h in 1h chart)
    funding_drop_threshold = 10.0    # pp (percentage points)
    oi_drop_threshold = 0.05         # 5% relative change
    hold_bars = 16
    stop_loss_pct = 0.04
    take_profit_pct = 0.08

    # OPTIMIZATION RANGES
    # window:                 [10, 15, 20, 30, 40]
    # funding_drop_threshold: [5, 10, 15, 20]
    # oi_drop_threshold:      [0.03, 0.05, 0.10]
    # hold_bars:              [8, 16, 24]
```

### Data Requirements

```python
# Must have these columns:
required_columns = [
    "Open", "High", "Low", "Close", "Volume",
    "Funding",      # % annualized
    "OI"            # USD (absolute open interest)
]

# OI source:
# - HyperLiquid API: getStatus endpoint for asset
# - Alternative: getAssetCtx (deprecated but works)
# - Ensure consistent source (not mixing APIs)
```

---

## STRATEGY #4: FundingCrossExchange (Spread Arbitrage)

### Function Signature

```python
class FundingCrossExchange(Strategy):
    """
    Exploit funding rate spreads between HyperLiquid and Binance.
    Entry: |spread| > spread_threshold_pct
    Direction: Long if HL cheaper, Short if HL expensive
    Must hedge opposite exchange simultaneously (code not shown)
    """
```

### Initialization

```python
def init(self):
    # Spread = HL_funding - Binance_funding (in %)
    # Pre-computed via external script

    if "FundingSpread" in self.data.df.columns:
        spread_arr = self.data.df["FundingSpread"].values.copy()
        self.spread = self.I(lambda: spread_arr, name="FundingSpread")
        self._has_spread = True
    else:
        self.spread = None
        self._has_spread = False

    self._bars_held = 0
```

### Entry and Exit Logic

```python
def next(self):
    if not self._has_spread:
        return

    sp = self.spread[-1]  # current spread

    if np.isnan(sp):
        return

    price = self.data.Close[-1]

    # POSITION MANAGEMENT
    if self.position:
        self._bars_held += 1
        if self._bars_held >= self.hold_bars:
            self.position.close()
            self._bars_held = 0
        return

    self._bars_held = 0

    # SPREAD POSITIVE: HL funding > Binance funding
    # Meaning: HL is more expensive to hold long
    # Strategy: SHORT on HL, LONG on Binance (hedge)
    if sp > self.spread_threshold_pct:
        self.sell(
            size=0.95,
            sl=price * (1 + self.stop_loss_pct),
            tp=price * (1 - self.take_profit_pct)
        )
        # In live: simultaneously enter long on Binance

    # SPREAD NEGATIVE: HL funding < Binance funding
    # Meaning: HL is cheaper to hold long
    # Strategy: LONG on HL, SHORT on Binance (hedge)
    elif sp < -self.spread_threshold_pct:
        self.buy(
            size=0.95,
            sl=price * (1 - self.stop_loss_pct),
            tp=price * (1 + self.take_profit_pct)
        )
        # In live: simultaneously enter short on Binance
```

### Parameter Ranges

```python
class FundingCrossExchange(Strategy):
    strategy_name = "Funding Cross Exchange"
    strategy_type = "Funding Arbitrage"

    # BASELINE
    spread_threshold_pct = 0.01     # 1 bps spread threshold
    hold_bars = 8                   # 8 hours (1h bars)
    stop_loss_pct = 0.02            # 2% protection
    take_profit_pct = 0.04          # 4% profit target

    # OPTIMIZATION RANGES
    # spread_threshold_pct: [0.005, 0.01, 0.02, 0.05]
    # hold_bars:          [4, 8, 16]
    # stop_loss_pct:      [0.01, 0.02, 0.03]
    # take_profit_pct:    [0.02, 0.04, 0.06]
```

### Data Requirements

```python
# Spread must be pre-computed from two sources:
# 1. HyperLiquid API: fundingHistory for HL funding
# 2. Binance API: premiumIndexKlines for BUSD pair
# 3. Computation:
#    spread = hl_funding_8h - binance_funding_8h
#    (both annualized for consistency)

# Column in DataFrame:
required_columns = [
    "Open", "High", "Low", "Close", "Volume",
    "FundingSpread"  # HL funding - Binance funding (%)
]
```

---

## STRATEGY #5: HIP3FundingExploit (Mean Reversion - Aggressive)

### Function Signature

```python
class HIP3FundingExploit(Strategy):
    """
    Aggressive mean reversion for HIP3 assets (lower liquidity, wider swings).
    Identical to FundingMeanReversion but with:
    - trigger_pct = 75% (vs 100%)
    - Larger SL/TP (5%/10% vs 4%/8%)
    Applies to: GOLD, CL, NVDA, TSLA (synthetic stocks on HL)
    """
```

### Code (Identical to FundingMeanReversion with parameters adjusted)

```python
class HIP3FundingExploit(Strategy):
    strategy_name = "HIP3 Funding Exploit"
    strategy_type = "Funding Mean Reversion"

    # AGGRESSIVE THRESHOLDS (due to low liquidity)
    trigger_pct = 75.0          # Trigger at 75% (vs 100% for crypto)
    exit_pct = 20.0
    hold_bars = 24
    stop_loss_pct = 0.05        # 5% SL (wider, less liquid)
    take_profit_pct = 0.10      # 10% TP (expect bigger moves)

    # OPTIMIZATION RANGES
    # trigger_pct:     [50, 75, 100]
    # exit_pct:        [15, 20, 25]
    # hold_bars:       [12, 24]
    # stop_loss_pct:   [0.03, 0.05, 0.08]
    # take_profit_pct: [0.08, 0.10, 0.15]

# next() logic: identical to FundingMeanReversion
# See above for complete implementation
```

---

## Testing Framework

### Minimal Backtest Template

```python
#!/usr/bin/env python3
"""
Minimal backtest for any funding strategy.
Usage: python backtest_funding.py
"""

import pandas as pd
import numpy as np
from backtesting import Backtest, Strategy
import yfinance as yf
from pathlib import Path

# IMPORT STRATEGY
from funding_strategies import FundingRateArbitrage

def load_funding_data(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV and load funding from cache if available."""

    # Download OHLCV
    df = yf.download(symbol, start=start, end=end, interval="4h", auto_adjust=True)
    df.columns = ["Close", "High", "Low", "Open", "Volume"]
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()

    # Try to load funding from local cache (if available)
    cache_path = Path(f"data/cache/{symbol.split('-')[0]}_funding.parquet")
    if cache_path.exists():
        funding_df = pd.read_parquet(cache_path)
        # Align with OHLCV data
        df = df.join(funding_df[["Funding"]], how="left")
        df["Funding"] = df["Funding"].fillna(method="bfill").fillna(0)
    else:
        # Fallback: simulate funding (for testing without real data)
        df["Funding"] = simulate_funding_proxy(df)

    return df

def simulate_funding_proxy(df: pd.DataFrame) -> pd.Series:
    """Simulate funding as proxy when real data not available."""
    import pandas_ta as ta

    close = df["Close"]
    sma20 = ta.sma(close, 20)

    # When perp > avg, funding is positive (longs pay)
    funding_proxy = ((close - sma20) / sma20 * 0.1) * 100  # Annualize
    return funding_proxy

def main():
    # Configuration
    SYMBOL = "BTC-USD"
    START = "2024-01-01"
    END = "2025-12-31"
    CASH = 10_000
    COMMISSION = 0.001  # 0.1%

    # Load data
    print(f"[*] Loading data for {SYMBOL}...")
    data = load_funding_data(SYMBOL, START, END)
    print(f"[*] Rows: {len(data)}, Columns: {data.columns.tolist()}")

    # Backtest
    print(f"[*] Running backtest for {SYMBOL}...")
    bt = Backtest(
        data,
        FundingRateArbitrage,
        cash=CASH,
        commission=COMMISSION,
        exclusive_orders=True,
        finalize_trades=True
    )

    stats = bt.run()
    print("\n" + "="*80)
    print(f"BACKTEST RESULTS: {SYMBOL}")
    print("="*80)
    print(stats)
    print("="*80)

    # Key metrics
    print(f"\nKey Metrics:")
    print(f"  Return:        {stats['Return [%]']:.2f}%")
    print(f"  Sharpe Ratio:  {stats['Sharpe Ratio']:.2f}")
    print(f"  Max Drawdown:  {stats['Max. Drawdown [%]']:.2f}%")
    print(f"  Win Rate:      {stats['Win Rate [%]']:.2f}%")
    print(f"  Trades:        {stats['# Trades']}")

if __name__ == "__main__":
    main()
```

### Multi-Asset Test

```python
def test_multiple_assets():
    """Test strategy across multiple symbols and timeframes."""

    symbols = ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD"]
    timeframes = ["1h", "4h"]
    strategies = [
        FundingRateArbitrage,
        FundingMeanReversion,
        FundingOIDivergence,
    ]

    results = []

    for symbol in symbols:
        for tf in timeframes:
            for strategy_class in strategies:
                print(f"[*] Testing {strategy_class.__name__} on {symbol} {tf}...")

                data = yf.download(symbol, period="2y", interval=tf, auto_adjust=True)
                # Add funding column (simulated or real)
                data["Funding"] = simulate_funding_proxy(data)

                bt = Backtest(data, strategy_class, cash=10_000, commission=0.001)
                stats = bt.run()

                results.append({
                    "symbol": symbol,
                    "timeframe": tf,
                    "strategy": strategy_class.__name__,
                    "sharpe": stats["Sharpe Ratio"],
                    "return": stats["Return [%]"],
                    "max_dd": stats["Max. Drawdown [%]"],
                })

    # Summary table
    df_results = pd.DataFrame(results)
    print("\n" + df_results.to_string())
```

---

## Integration with HyperLiquid API

### Fetching Real Funding Data

```python
import httpx
import json
from datetime import datetime, timedelta

class HyperLiquidFundingFetcher:
    """Fetch real funding rate history from HyperLiquid."""

    BASE_URL = "https://api.hyperliquid.xyz/info"

    def get_funding_history(self, coin: str, lookback_days: int = 365) -> pd.DataFrame:
        """
        Fetch funding rate history for a coin.

        Args:
            coin: "BTC", "ETH", etc.
            lookback_days: How far back to fetch

        Returns:
            DataFrame with columns: time, fundingRate (%), premium
        """

        now_ms = int(datetime.utcnow().timestamp() * 1000)
        start_ms = int((datetime.utcnow() - timedelta(days=lookback_days)).timestamp() * 1000)

        payload = {
            "type": "fundingHistory",
            "coin": coin,
            "startTime": start_ms,
            "endTime": now_ms
        }

        response = httpx.post(self.BASE_URL, json=payload)
        data = response.json()

        # Parse funding history
        records = []
        for entry in data:
            records.append({
                "time": pd.Timestamp(entry["time"], unit="ms"),
                "funding_8h": float(entry["fundingRate"]) * 100,  # Convert to %
                "premium": float(entry["premium"]) * 100,
            })

        df = pd.DataFrame(records)

        # Annualize funding (8h rate × 3 × 365)
        df["Funding"] = df["funding_8h"] * 3 * 365

        return df.set_index("time")

    def merge_with_ohlcv(self, ohlcv: pd.DataFrame, funding: pd.DataFrame) -> pd.DataFrame:
        """Align funding data with OHLCV."""

        # Resample funding to match OHLCV timeframe (forward fill)
        funding_resampled = funding.resample(ohlcv.index.inferred_freq).ffill()

        # Merge
        result = ohlcv.join(funding_resampled[["Funding"]], how="left")
        result["Funding"] = result["Funding"].ffill().fillna(0)

        return result

# Usage
fetcher = HyperLiquidFundingFetcher()
funding_data = fetcher.get_funding_history("BTC", lookback_days=365)
ohlcv_data = yf.download("BTC-USD", period="1y", interval="4h")
merged = fetcher.merge_with_ohlcv(ohlcv_data, funding_data)

# Backtest with real funding
bt = Backtest(merged, FundingRateArbitrage, cash=10_000, commission=0.001)
stats = bt.run()
```

---

## Production Checklist

Before deploying to live trading:

- [ ] Backtest passes across 2+ years of data
- [ ] Sharpe Ratio > 1.0 (ideally > 1.5)
- [ ] Max Drawdown < 20% (or your tolerance)
- [ ] Win Rate > 50% (or profit factor > 1.5)
- [ ] Tested on 5+ different symbols
- [ ] Real funding data verified (not simulated)
- [ ] Comisiones in backtest match HL actual fees
- [ ] Stop loss and take profit prices are executable (within spreads)
- [ ] Paper traded for 1-2 weeks
- [ ] API keys and credentials securely stored
- [ ] Position sizing calculated (Kelly Criterion or fixed)
- [ ] Risk management rules in place (max loss per day, etc.)
- [ ] Monitoring alerts set up (funding flip, drawdown, etc.)
- [ ] Fallback plan if strategy underperforms

---

**End of Technical Specifications**

These specs are ready for implementation in `backtesting.py` or direct live trading via HyperLiquid API.
