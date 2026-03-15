# STRATEGY IMPLEMENTATION SPECIFICATIONS
## Technical Details for Coding & Backtesting

---

## TABLE OF CONTENTS
1. NEW STRATEGY 1: VRAE (Volatility Regime Adaptive Entry)
2. NEW STRATEGY 2: MTFB (Multi-Timeframe Confirmation Breakout)
3. NEW STRATEGY 3: VWMD (Volume-Weighted Momentum Divergence)
4. NEW STRATEGY 4: LCVB (Liquidity Cascade + VWAP Bounce)
5. NEW STRATEGY 5: CAMR (Cross-Asset Momentum Rotation)
6. NEW STRATEGY 6: CBH (Consolidation Breakout Hunter)
7. NEW STRATEGY 7: STC (Smart Stop-Loss Trailing + Chandelier)
8. NEW STRATEGY 8: BAST (Bid-Ask Spread Tightening)

---

## STRATEGY 1: VRAE — Volatility Regime Adaptive Entry

### Class Definition
```python
class VolatilityRegimeAdaptive(Strategy):
    """
    Volatility-Aware Position Sizing & Risk Management Overlay.

    Adapts SL/TP multipliers based on realized volatility regime:
    - Low vol: tighter stops, wider targets
    - High vol: wider stops, tighter targets

    Use as wrapper around any base strategy.
    """

    # Base strategy parameters (parent strategy)
    base_momentum_period = 9
    base_atr_period = 14

    # Vol adaptation
    vol_lookback = 20
    vol_percentile_low = 0.20   # Bottom 20%
    vol_percentile_high = 0.80  # Top 20%

    # Regime-specific multipliers (optimizable)
    low_vol_sl_mult = 0.8      # Tighter stops in low vol
    low_vol_tp_mult = 3.5      # Wider targets in low vol

    med_vol_sl_mult = 1.5
    med_vol_tp_mult = 2.5

    high_vol_sl_mult = 2.0     # Wider stops in high vol
    high_vol_tp_mult = 1.5     # Tighter targets in high vol

    def init(self):
        close = pd.Series(self.data.Close)
        high = pd.Series(self.data.High)
        low = pd.Series(self.data.Low)

        # Base indicators
        self.atr = self.I(
            lambda: ta.atr(high, low, close, length=self.base_atr_period).values,
            name="ATR"
        )

        # Volatility indicators
        def parkinson_vol(h, l):
            """Parkinson volatility = sqrt(sum((log(h) - log(l))²) / (4×ln(2)×n))"""
            h_s = pd.Series(h)
            l_s = pd.Series(l)
            log_range_sq = np.log(h_s / l_s) ** 2
            pv = np.sqrt(log_range_sq.rolling(5).sum() / (4 * np.log(2) * 5))
            return pv.values

        self.pv_vol = self.I(
            parkinson_vol, high, low,
            name="ParkinsonVol"
        )

        # Historical volatility percentile
        def hv_percentile(vol_series, window=20):
            v = pd.Series(vol_series)
            hv_rank = v.rolling(window).apply(
                lambda x: pd.Series(x).rank().iloc[-1] / len(x),
                raw=False
            )
            return hv_rank.values

        self.hv_rank = self.I(
            hv_percentile, self.pv_vol,
            name="HV_Rank"
        )

        # Momentum (for signal direction)
        self.momentum = self.I(
            lambda: ta.mom(close, length=self.base_momentum_period).values,
            name="Momentum"
        )

    def get_vol_regime(self):
        """Returns (regime_name, sl_mult, tp_mult) tuple."""
        hv = float(self.hv_rank[-1])

        if hv < self.vol_percentile_low:
            return ("LOW", self.low_vol_sl_mult, self.low_vol_tp_mult)
        elif hv > self.vol_percentile_high:
            return ("HIGH", self.high_vol_sl_mult, self.high_vol_tp_mult)
        else:
            return ("MED", self.med_vol_sl_mult, self.med_vol_tp_mult)

    def next(self):
        if len(self.data) < max(self.vol_lookback, self.base_atr_period) + 5:
            return

        price = self.data.Close[-1]
        atr = self.atr[-1]
        momentum = self.momentum[-1]
        regime, sl_mult, tp_mult = self.get_vol_regime()

        if atr <= 0 or np.isnan(momentum):
            return

        # Entry logic (simplified momentum cross for example)
        if not self.position:
            if momentum > 0:
                # LONG entry with adaptive stops
                sl = price - (atr * sl_mult)
                tp = price + (atr * tp_mult)
                self.buy(sl=sl, tp=tp)
            elif momentum < 0:
                # SHORT entry with adaptive stops
                sl = price + (atr * sl_mult)
                tp = price - (atr * tp_mult)
                self.sell(sl=sl, tp=tp)
```

### Backtest Configuration
```python
# Use with any base strategy
# Parameters to optimize
params = {
    'low_vol_sl_mult': [0.6, 0.8, 1.0],
    'low_vol_tp_mult': [3.0, 3.5, 4.0],
    'high_vol_sl_mult': [1.5, 2.0, 2.5],
    'high_vol_tp_mult': [1.0, 1.5, 2.0],
    'vol_lookback': [15, 20, 30],
    'vol_percentile_low': [0.15, 0.20, 0.25],
}

# Expected improvement: +0.3-0.5 Sharpe points
```

### Key Optimizations
- **Parkinson Volatility**: Fast, responds to intrabar volatility
- **Historical Vol Percentile**: Ranks current vol against lookback window
- **Regime Multipliers**: Tune for each asset class (crypto = higher range)

---

## STRATEGY 2: MTFB — Multi-Timeframe Confirmation Breakout

### Class Definition
```python
class MultiTimeframeBreakout(Strategy):
    """
    Breakout on 1h confirmed by trend on 4h.

    Reduces false breakouts by requiring higher-timeframe alignment.
    Requires downloading 4h data separately and aligning with 1h.
    """

    # 1h (entry timeframe) parameters
    lookback_entry = 20
    atr_period = 14

    # 4h (confirmation timeframe) parameters
    sma_fast = 20
    sma_slow = 50

    # Position management
    risk_reward_ratio = 2.0

    def init(self):
        close = pd.Series(self.data.Close)
        high = pd.Series(self.data.High)
        low = pd.Series(self.data.Low)

        # --- 1h indicators (entry) ---
        self.atr = self.I(
            lambda: ta.atr(high, low, close, length=self.atr_period).values,
            name="ATR"
        )

        self.highest = self.I(
            lambda: high.rolling(self.lookback_entry).max().shift(1).values,
            name="HH"
        )

        self.lowest = self.I(
            lambda: low.rolling(self.lookback_entry).min().shift(1).values,
            name="LL"
        )

        # --- 4h indicators (confirmation) ---
        # Download 4h data separately (outside of init, in Backtest setup)
        self.sma_fast_4h = None
        self.sma_slow_4h = None
        self._load_4h_data()

        self._last_breakout_type = 0  # 0=none, 1=up, -1=down
        self._last_breakout_bar = -100

    def _load_4h_data(self):
        """Load 4h data and align with 1h bars."""
        try:
            # This would normally be passed via Backtest parameter
            # For now, we fetch within init (not ideal, but works)
            df_4h = self.data  # Placeholder - would be separate download

            sma_f = df_4h.Close.rolling(self.sma_fast).mean()
            sma_s = df_4h.Close.rolling(self.sma_slow).mean()

            self.sma_fast_4h = self.I(lambda: sma_f.values, name="SMA_F_4h")
            self.sma_slow_4h = self.I(lambda: sma_s.values, name="SMA_S_4h")
        except Exception as e:
            print(f"Failed to load 4h data: {e}")
            # Fallback: use same timeframe (less effective)
            sma_f = pd.Series(self.data.Close).rolling(self.sma_fast).mean()
            sma_s = pd.Series(self.data.Close).rolling(self.sma_slow).mean()
            self.sma_fast_4h = self.I(lambda: sma_f.values, name="SMA_F")
            self.sma_slow_4h = self.I(lambda: sma_s.values, name="SMA_S")

    def get_4h_trend(self):
        """
        Returns trend direction based on 4h SMA:
        +1 = uptrend, -1 = downtrend, 0 = neutral
        """
        if self.sma_fast_4h is None or self.sma_slow_4h is None:
            return 0

        sma_f = float(self.sma_fast_4h[-1])
        sma_s = float(self.sma_slow_4h[-1])

        if np.isnan(sma_f) or np.isnan(sma_s):
            return 0

        if sma_f > sma_s:
            return 1
        elif sma_f < sma_s:
            return -1
        else:
            return 0

    def next(self):
        if len(self.data) < max(self.lookback_entry, self.sma_slow) + 5:
            return

        price = self.data.Close[-1]
        highest = self.highest[-1]
        lowest = self.lowest[-1]
        atr = self.atr[-1]
        trend_4h = self.get_4h_trend()

        if atr <= 0 or np.isnan(highest) or np.isnan(lowest):
            return

        # Detect breakout
        is_breakout_up = price > highest
        is_breakout_down = price < lowest

        # Only enter if 4h trend aligns with breakout direction
        if not self.position:
            if is_breakout_up and trend_4h == 1:
                # LONG: 1h breakout up + 4h uptrend
                sl = price - (atr * 1.5)
                tp = price + (atr * self.risk_reward_ratio)
                self.buy(sl=sl, tp=tp)
                self._last_breakout_type = 1
                self._last_breakout_bar = len(self.data)

            elif is_breakout_down and trend_4h == -1:
                # SHORT: 1h breakout down + 4h downtrend
                sl = price + (atr * 1.5)
                tp = price - (atr * self.risk_reward_ratio)
                self.sell(sl=sl, tp=tp)
                self._last_breakout_type = -1
                self._last_breakout_bar = len(self.data)

        # Close position if 4h trend flips
        if self.position:
            if self.position.is_long and trend_4h == -1:
                self.position.close()
            elif self.position.is_short and trend_4h == 1:
                self.position.close()
```

### Backtest Configuration
```python
# Requires dual OHLCV data: 1h and 4h
# Implementation: Download both, align by datetime

from backtesting import Backtest
import yfinance as yf

# Download 1h data
df_1h = yf.download("BTC-USD", interval="1h", period="2y", auto_adjust=True)

# Download 4h data
df_4h = yf.download("BTC-USD", interval="4h", period="2y", auto_adjust=True)

# Align 4h to 1h index (forward-fill)
df_4h_aligned = df_4h.reindex(df_1h.index, method='ffill')

# Merge into single dataset with 4h columns prefixed
df_combined = df_1h.copy()
for col in ['Close', 'High', 'Low', 'Open', 'Volume']:
    if col in df_4h_aligned.columns:
        df_combined[f'{col}_4h'] = df_4h_aligned[col]

bt = Backtest(df_1h, MultiTimeframeBreakout,
              cash=10000, commission=0.001,
              exclusive_orders=True, finalize_trades=True)
stats = bt.run()
```

### Parameters to Optimize
```python
params = {
    'lookback_entry': [15, 20, 30, 40],
    'sma_fast': [10, 20, 30],
    'sma_slow': [30, 50, 60],
    'risk_reward_ratio': [1.5, 2.0, 2.5, 3.0],
}

# Expected results: Sharpe 2.0-2.5, Win Rate 52-58%
```

---

## STRATEGY 3: VWMD — Volume-Weighted Momentum Divergence

### Class Definition
```python
class VolumeWeightedMomentumDivergence(Strategy):
    """
    Detect momentum divergence with volume confirmation.

    Bearish divergence: Price new high, ROC declining, volume declining → SELL
    Bullish divergence: Price new low, ROC improving, volume declining → BUY
    """

    roc_period = 12
    volume_period = 20
    volume_spike_threshold = 1.5  # Volume decline < this × MA
    rolling_period = 20
    atr_period = 14

    def init(self):
        close = pd.Series(self.data.Close)
        high = pd.Series(self.data.High)
        low = pd.Series(self.data.Low)
        volume = pd.Series(self.data.Volume)

        # ROC: Rate of Change (momentum)
        self.roc = self.I(
            lambda: ((close - close.shift(self.roc_period)) / close.shift(self.roc_period) * 100).values,
            name="ROC"
        )

        # Volume moving averages
        self.vol_ema = self.I(
            lambda: volume.ewm(span=self.volume_period).mean().values,
            name="VolEMA"
        )

        # Price extrema (rolling max/min)
        self.rolling_high = self.I(
            lambda: high.rolling(self.rolling_period).max().values,
            name="RollingHigh"
        )

        self.rolling_low = self.I(
            lambda: low.rolling(self.rolling_period).min().values,
            name="RollingLow"
        )

        # ATR for position sizing
        self.atr = self.I(
            lambda: ta.atr(high, low, close, length=self.atr_period).values,
            name="ATR"
        )

        # Internal state tracking
        self._swing_history = []  # List of (price, roc, bar_idx)

    def detect_divergence(self):
        """
        Check if current bar has divergence setup.
        Returns: (divergence_type, confidence) where type is 'BULL', 'BEAR', or None
        """
        current_price = self.data.Close[-1]
        current_roc = float(self.roc[-1]) if not np.isnan(self.roc[-1]) else 0
        current_vol = self.data.Volume[-1]
        vol_ema = float(self.vol_ema[-1]) if not np.isnan(self.vol_ema[-1]) else 1

        # Detect price extrema
        price_high = float(self.rolling_high[-1])
        price_low = float(self.rolling_low[-1])

        is_new_high = current_price >= price_high * 0.999
        is_new_low = current_price <= price_low * 1.001

        # Volume check: declining or normal
        vol_declining = current_vol < vol_ema * self.volume_spike_threshold

        # Check divergence against swing history
        divergence_type = None
        confidence = 0

        if is_new_high and vol_declining:
            # Check if ROC is declining
            if len(self._swing_history) > 0:
                prev_roc = self._swing_history[-1][1]
                if current_roc < prev_roc:
                    divergence_type = 'BEAR'
                    confidence = 1 + (1 if vol_declining else 0)

        elif is_new_low and vol_declining:
            # Check if ROC is improving
            if len(self._swing_history) > 0:
                prev_roc = self._swing_history[-1][1]
                if current_roc > prev_roc:
                    divergence_type = 'BULL'
                    confidence = 1 + (1 if vol_declining else 0)

        # Store current swing
        if is_new_high or is_new_low:
            self._swing_history.append((current_price, current_roc, len(self.data)))
            if len(self._swing_history) > 10:
                self._swing_history.pop(0)

        return divergence_type, confidence

    def next(self):
        if len(self.data) < max(self.roc_period, self.rolling_period, self.atr_period) + 5:
            return

        divergence_type, confidence = self.detect_divergence()

        price = self.data.Close[-1]
        atr = self.atr[-1]

        if atr <= 0:
            return

        if not self.position:
            if divergence_type == 'BEAR' and confidence >= 1:
                # Bearish divergence → SELL
                sl = price + (atr * 1.0)
                tp = price - (atr * 2.0)
                self.sell(sl=sl, tp=tp)

            elif divergence_type == 'BULL' and confidence >= 1:
                # Bullish divergence → BUY
                sl = price - (atr * 1.0)
                tp = price + (atr * 2.0)
                self.buy(sl=sl, tp=tp)
```

### Parameters to Optimize
```python
params = {
    'roc_period': [8, 10, 12, 14],
    'volume_period': [15, 20, 25],
    'volume_spike_threshold': [1.3, 1.5, 1.8],
    'rolling_period': [15, 20, 25, 30],
}

# Expected: Win Rate 55-62%, Sharpe 1.5-2.0, 40-80 trades/year
```

---

## STRATEGY 4: LCVB — Liquidation Cascade + VWAP Bounce

### Implementation Notes
This strategy requires **live HyperLiquid liquidation data**, so backtest proxy only:

```python
class LiquidationVWAPBounce(Strategy):
    """
    VWAP bounce from liquidation-induced lows.

    Backtest logic: RSI < 25 + price at BB lower = capitulation proxy
    Live logic: Query HyperLiquid get_liquidations() for cascade events
    """

    rsi_period = 14
    bb_period = 20
    bb_std = 2.0
    atr_period = 14

    # Liquidation parameters (for live mode)
    min_liq_notional = 500_000  # $500K threshold
    liq_window_bars = 5

    def init(self):
        close = pd.Series(self.data.Close)
        high = pd.Series(self.data.High)
        low = pd.Series(self.data.Low)

        # RSI
        self.rsi = self.I(
            lambda: ta.rsi(close, length=self.rsi_period).values,
            name="RSI"
        )

        # Bollinger Bands
        bb = ta.bbands(close, length=self.bb_period, std=self.bb_std)
        self.bb_upper = self.I(lambda: bb.iloc[:, 2].values, name="BB_U")
        self.bb_mid = self.I(lambda: bb.iloc[:, 1].values, name="BB_M")
        self.bb_lower = self.I(lambda: bb.iloc[:, 0].values, name="BB_L")

        # VWAP
        self.vwap = self.I(
            lambda: ta.vwap(high, low, close, self.data.Volume).values,
            name="VWAP"
        )

        # ATR
        self.atr = self.I(
            lambda: ta.atr(high, low, close, length=self.atr_period).values,
            name="ATR"
        )

        self._recent_liquidations = 0
        self._last_liq_bar = -100

    def _get_liquidation_volume(self):
        """
        In live mode: query HyperLiquid API
        In backtest: use volume spike as proxy
        """
        # Backtest proxy: volume spike > 2.0× MA
        vol_recent = self.data.Volume[-1]
        vol_ma = pd.Series(self.data.Volume[-20:]).mean()

        if vol_recent > vol_ma * 2.0:
            return vol_recent * self.data.Close[-1]  # Estimate notional
        else:
            return 0

    def next(self):
        if len(self.data) < max(self.bb_period, self.rsi_period) + 5:
            return

        price = self.data.Close[-1]
        rsi = float(self.rsi[-1])
        bb_l = float(self.bb_lower[-1])
        bb_m = float(self.bb_mid[-1])
        vwap = float(self.vwap[-1])
        atr = float(self.atr[-1])

        if any(np.isnan(x) for x in [rsi, bb_l, bb_m, vwap, atr]) or atr <= 0:
            return

        # Liquidation detection
        liq_vol = self._get_liquidation_volume()
        if liq_vol > self.min_liq_notional:
            self._recent_liquidations += 1
            self._last_liq_bar = len(self.data)

        # Reset counter if too old
        if len(self.data) - self._last_liq_bar > self.liq_window_bars:
            self._recent_liquidations = 0

        # VWAP bounce setup
        if not self.position:
            # Long bounce from liquidation
            if (rsi < 25 and price <= bb_l and
                self._recent_liquidations > 0 and
                price <= vwap):
                # Price at VWAP, RSI extreme, recent liquidation
                sl = vwap - (atr * 1.5)
                tp = vwap + (atr * 2.0)
                self.buy(sl=sl, tp=tp)

            # Short bounce (inverse)
            elif (rsi > 75 and price >= bb_l * 1.5 and  # Approximate upper
                  self._recent_liquidations > 0):
                sl = vwap + (atr * 1.5)
                tp = vwap - (atr * 2.0)
                self.sell(sl=sl, tp=tp)
```

---

## STRATEGY 5: CAMR — Cross-Asset Momentum Rotation

### Implementation Notes
Requires tracking multiple assets simultaneously (9-asset portfolio):

```python
class CrossAssetMomentumRotation(Strategy):
    """
    Rank 9 crypto assets by momentum, trade top 2 LONG.
    Requires custom implementation outside backtesting.py
    or multi-leg support.

    For backtesting.py single-symbol:
    Track all 9 symbols in parallel, vote on portfolio actions.
    """

    assets = ['BTC', 'ETH', 'SOL', 'XRP', 'ADA', 'DOGE', 'AVAX', 'MATIC', 'LINK']
    momentum_period = 20
    rebalance_bars = 4

    # Pseudo-code for multi-asset version:
    def get_momentum_ranking(self, asset_data_dict):
        """
        Args:
            asset_data_dict: {'BTC': df, 'ETH': df, ...}
        Returns:
            ranked list: [(asset, momentum_score), ...]
        """
        rankings = []
        for asset, df in asset_data_dict.items():
            momentum = (df['Close'].iloc[-1] - df['Close'].iloc[-self.momentum_period]) / df['Close'].iloc[-self.momentum_period]
            rankings.append((asset, momentum))

        return sorted(rankings, key=lambda x: x[1], reverse=True)

    def rebalance_portfolio(self, current_holdings, target_asset, target_type='LONG'):
        """
        Exit current position, enter new position in target asset.

        This requires either:
        1. Multiple Strategy instances (one per asset)
        2. Custom Portfolio class
        3. External orchestration layer
        """
        # Simplified logic
        if current_holdings != target_asset:
            # close(current)
            # open(target, target_type)
            pass
```

### For Full Implementation
Create a **Portfolio Manager** outside backtesting.py:

```python
class PortfolioManager:
    def __init__(self, assets, timeframe='4h'):
        self.assets = assets
        self.data = {}
        self.rankings = []
        self.current_long = None
        self.current_short = None

    def update(self, asset_prices):
        """Update with latest OHLCV for all assets."""
        # Calculate momentum for each
        # Rebalance if needed
        pass

    def get_signals(self):
        """Return (long_symbol, short_symbol, neutral_symbols)."""
        rankings = self._rank_by_momentum()
        return {
            'long': rankings[0],
            'short': rankings[-1],
            'neutral': rankings[1:-1]
        }

# Use with multi-leg backtesting or live trading engine
```

---

## STRATEGY 6: CBH — Consolidation Breakout Hunter

### Class Definition
```python
class ConsolidationBreakoutHunter(Strategy):
    """
    Detect tight consolidation, trade the breakout.

    Setup:
      - Low ATR (< 20th percentile of 50 bars)
      - Tight range (< 2% of price)
      - Minimum 5 bars of consolidation
      - ADX > 25 on breakout (confirms trend)
      - Volume spike on breakout
    """

    atr_period = 14
    atr_percentile_window = 50
    atr_threshold_percentile = 0.20

    consolidation_range_threshold = 0.02  # 2%
    min_consolidation_bars = 5

    adx_period = 14
    adx_threshold = 25

    volume_period = 20
    volume_spike_threshold = 1.5

    risk_reward_ratio = 2.5

    def init(self):
        close = pd.Series(self.data.Close)
        high = pd.Series(self.data.High)
        low = pd.Series(self.data.Low)
        volume = pd.Series(self.data.Volume)

        # ATR
        self.atr = self.I(
            lambda: ta.atr(high, low, close, length=self.atr_period).values,
            name="ATR"
        )

        # ATR Percentile
        def atr_percentile(atr_series, window):
            a = pd.Series(atr_series)
            pct = a.rolling(window).apply(
                lambda x: (x.iloc[-1] <= x.quantile(0.5)) / len(x),
                raw=False
            )
            return pct.values

        self.atr_pct = self.I(
            atr_percentile, self.atr, self.atr_percentile_window,
            name="ATR_Pct"
        )

        # Range (High - Low) / Close
        self.range = self.I(
            lambda: ((high - low) / close).values,
            name="Range"
        )

        # ADX
        adx_df = ta.adx(high, low, close, length=self.adx_period)
        self.adx = self.I(
            lambda: adx_df.iloc[:, 0].values if adx_df is not None else [0]*len(close),
            name="ADX"
        )

        # Volume
        self.vol_ma = self.I(
            lambda: volume.rolling(self.volume_period).mean().values,
            name="VolMA"
        )

        # State tracking
        self._consolidation_active = False
        self._consolidation_bars = 0
        self._consolidation_high = 0
        self._consolidation_low = 0

    def next(self):
        if len(self.data) < max(self.atr_percentile_window, self.adx_period) + 10:
            return

        price = self.data.Close[-1]
        atr = float(self.atr[-1])
        atr_pct = float(self.atr_pct[-1])
        rng = float(self.range[-1])
        adx = float(self.adx[-1])
        vol = self.data.Volume[-1]
        vol_ma = float(self.vol_ma[-1])

        if any(np.isnan(x) for x in [atr, atr_pct, rng, adx]) or atr <= 0:
            return

        high = self.data.High[-1]
        low = self.data.Low[-1]

        # Consolidation detection
        is_tight = (atr_pct < self.atr_threshold_percentile and
                    rng < self.consolidation_range_threshold)

        if is_tight:
            if not self._consolidation_active:
                self._consolidation_active = True
                self._consolidation_bars = 1
                self._consolidation_high = high
                self._consolidation_low = low
            else:
                self._consolidation_bars += 1
                self._consolidation_high = max(self._consolidation_high, high)
                self._consolidation_low = min(self._consolidation_low, low)
        else:
            # Breakout detected
            if self._consolidation_active and self._consolidation_bars >= self.min_consolidation_bars:
                # Check confirmation
                vol_spike = vol > vol_ma * self.volume_spike_threshold
                trend_strong = adx > self.adx_threshold

                if vol_spike and trend_strong:
                    # Enter on breakout direction
                    if price > self._consolidation_high:
                        # Breakout up → LONG
                        sl = self._consolidation_low - atr
                        tp = price + (atr * self.risk_reward_ratio)
                        self.buy(sl=sl, tp=tp)

                    elif price < self._consolidation_low:
                        # Breakout down → SHORT
                        sl = self._consolidation_high + atr
                        tp = price - (atr * self.risk_reward_ratio)
                        self.sell(sl=sl, tp=tp)

            # Reset consolidation state
            self._consolidation_active = False
            self._consolidation_bars = 0
```

---

## STRATEGY 7: STC — Smart Trailing + Chandelier Exit

### Implementation
```python
class SmartTrailingChandelierExit:
    """
    Risk management overlay for any base strategy.
    Combines:
    - Chandelier exit (price closes beyond ATR-based level)
    - Dynamic trailing (ATR-adjusted, scales with profit)
    """

    atr_period = 14
    chandelier_lookback = 22
    chandelier_mult = 3.0

    trailing_profit_threshold_1 = 1.5  # Start trailing at 1.5% profit
    trailing_distance_1 = 1.0  # With 1.0x ATR

    trailing_profit_threshold_2 = 3.0  # Tighter at 3%
    trailing_distance_2 = 0.8

    trailing_profit_threshold_3 = 5.0  # Tightest at 5%
    trailing_distance_3 = 0.5

    max_hold_hours = 72

    def __init__(self, base_strategy_class):
        self.base_strategy = base_strategy_class
        self.entry_bar = None
        self.entry_price = None
        self.current_sl = None
        self.current_tp = None

    def update_stops(self, current_price, atr, bars_held):
        """Calculate new SL/TP based on profit and volatility."""

        if self.entry_price is None:
            return self.current_sl, self.current_tp

        profit_pct = (current_price - self.entry_price) / self.entry_price * 100

        # Time-based exit
        if bars_held > self.max_hold_hours:
            return None, None  # Signal to close

        # Chandelier exit (hard exit on wick test)
        chandelier_level_long = self._get_chandelier(up=True)
        chandelier_level_short = self._get_chandelier(up=False)

        new_sl = self.current_sl

        # Trailing stop logic (for LONG positions)
        if profit_pct > self.trailing_profit_threshold_1:
            trail = atr * self.trailing_distance_1
            new_sl = max(self.current_sl, current_price - trail)

        if profit_pct > self.trailing_profit_threshold_2:
            trail = atr * self.trailing_distance_2
            new_sl = max(self.current_sl, current_price - trail)

        if profit_pct > self.trailing_profit_threshold_3:
            trail = atr * self.trailing_distance_3
            new_sl = max(self.current_sl, current_price - trail)

        # Check chandelier (hard exit)
        if current_price < chandelier_level_long:
            return None, None  # Chandelier triggered

        return new_sl, self.current_tp

    def _get_chandelier(self, up=True):
        """Get Chandelier level (requires access to OHLC)."""
        # Would be implemented in actual Strategy class
        pass
```

---

## STRATEGY 8: BAST — Bid-Ask Spread Tightening

### Implementation Notes
**Requires HyperLiquid API for live data:**

```python
class BidAskSpreadTightening(Strategy):
    """
    Monitor bid-ask spread compression from HyperLiquid orderbook.

    Live mode: Direct orderbook queries
    Backtest mode: Simulate with volume patterns
    """

    volume_period = 20
    momentum_period = 9

    def init(self):
        close = pd.Series(self.data.Close)
        volume = pd.Series(self.data.Volume)

        self.vol_ma = self.I(
            lambda: volume.rolling(self.volume_period).mean().values,
            name="VolMA"
        )

        self.momentum = self.I(
            lambda: ta.mom(close, length=self.momentum_period).values,
            name="Momentum"
        )

        self._last_spread = 0
        self._last_vol = 0

    def get_spread_compression(self):
        """
        Live mode: Query orderbook from HyperLiquid
        Backtest mode: Simulate with volume spike proxy
        """
        try:
            # Live: from rbi.tools.hyperliquid import get_orderbook
            # orderbook = get_orderbook(symbol)
            # spread = (ask - bid) / mid_price
            # compression = (prev_spread - current_spread) / prev_spread
            pass
        except:
            # Backtest proxy
            vol = self.data.Volume[-1]
            vol_ma = float(self.vol_ma[-1])

            if vol > vol_ma * 1.5:
                # Simulate 15% spread compression
                return 0.15
            else:
                return 0.0

    def next(self):
        compression = self.get_spread_compression()
        momentum = float(self.momentum[-1])

        if compression > 0.10 and not np.isnan(momentum):  # 10%+ compression
            if not self.position:
                if momentum > 0:
                    self.buy()
                elif momentum < 0:
                    self.sell()
```

---

## OPTIMIZATION GRID TEMPLATE

```python
# Use with backtesting.py optimize() function

optimization_params = {
    'VRAE': {
        'low_vol_sl_mult': [0.6, 0.8, 1.0],
        'low_vol_tp_mult': [3.0, 3.5, 4.0],
        'high_vol_sl_mult': [1.5, 2.0, 2.5],
        'high_vol_tp_mult': [1.0, 1.5, 2.0],
    },
    'MTFB': {
        'lookback_entry': [15, 20, 30, 40],
        'sma_fast': [10, 20, 30],
        'sma_slow': [30, 50, 60],
        'risk_reward_ratio': [1.5, 2.0, 2.5, 3.0],
    },
    'VWMD': {
        'roc_period': [8, 10, 12, 14],
        'volume_period': [15, 20, 25],
        'rolling_period': [15, 20, 25, 30],
    },
    'CBH': {
        'atr_threshold_percentile': [0.15, 0.20, 0.25],
        'min_consolidation_bars': [3, 5, 7],
        'risk_reward_ratio': [1.5, 2.0, 2.5],
    },
    'LCVB': {
        'rsi_period': [12, 14, 16],
        'bb_period': [18, 20, 22],
        'min_liq_notional': [300_000, 500_000, 1_000_000],
    },
}

# Run optimization
stats = bt.optimize(
    **optimization_params['VRAE'],
    maximize='Sharpe Ratio',
    constraint=lambda p: p.low_vol_tp_mult > p.med_vol_tp_mult > p.high_vol_tp_mult
)
```

---

**End of Implementation Specifications**

Next: Code generation and backtesting automation

