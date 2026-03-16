"""
VolatilityTargeting — Overlay que mejora cualquier estrategia existente.

Fuente: Man Group / AHL, QuantPedia
  - Mejora Sharpe 10-30% sobre cualquier estrategia base
  - Reduce drawdown 20-40%
  - Usado por la mayoría de CTAs y managed futures funds

Concepto:
  - Ajusta el position sizing dinámicamente: size = target_vol / realized_vol
  - Cuando vol es baja → sube size (captura más del movimiento)
  - Cuando vol es alta → baja size (protege capital)
  - Weekly rebalance del sizing

Uso como wrapper:
  Se puede aplicar sobre cualquier Strategy class existente.
  Ver VolTargeted_VolatilitySqueeze como ejemplo de composición.

Uso standalone:
  Como estrategia propia usa EMA crossover como señal base + vol targeting sizing.
"""
import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Strategy


def vol_target_size(realized_vol: float, target_vol: float = 0.12,
                    max_leverage: float = 2.0, base_size: float = 0.95) -> float:
    """Calcula position size con vol targeting.

    Args:
        realized_vol: Volatilidad realizada anualizada actual
        target_vol: Volatilidad objetivo anualizada (default 12%)
        max_leverage: Leverage máximo permitido
        base_size: Size base (fracción del capital)

    Returns:
        Position size ajustado [0.1, base_size]
    """
    if realized_vol <= 0 or np.isnan(realized_vol):
        return 0.1
    leverage = min(target_vol / realized_vol, max_leverage)
    return min(base_size, max(0.1, leverage * base_size))


class VolatilityTargetingEMACross(Strategy):
    """Estrategia standalone: EMA crossover + vol targeting sizing."""

    strategy_name = "VolatilityTargeting (EMA Cross)"
    strategy_type = "Trend Following"

    # Señal base: EMA crossover
    fast_ema = 20
    slow_ema = 50

    # Vol targeting
    vol_window = 20         # Ventana rolling vol
    target_vol = 0.12       # 12% anualizado
    max_leverage = 2.0

    # Risk management
    sl_atr_mult = 2.0
    tp_atr_mult = 4.0

    def init(self):
        close = pd.Series(self.data.Close, index=range(len(self.data.Close)))
        high = pd.Series(self.data.High, index=range(len(self.data.High)))
        low = pd.Series(self.data.Low, index=range(len(self.data.Low)))

        # EMAs para señal
        fast_vals = ta.ema(close, length=self.fast_ema).values
        slow_vals = ta.ema(close, length=self.slow_ema).values
        self.ema_fast = self.I(lambda: fast_vals, name="EMA_F")
        self.ema_slow = self.I(lambda: slow_vals, name="EMA_S")

        # Volatilidad realizada anualizada
        log_ret = np.log(close / close.shift(1))
        vol_vals = (log_ret.rolling(self.vol_window).std() * np.sqrt(365 * 24)).values
        self.realized_vol = self.I(lambda: vol_vals, name="RVOL")

        # ATR
        atr_vals = ta.atr(high, low, close, length=14).values
        self.atr = self.I(lambda: atr_vals, name="ATR")

    def next(self):
        if len(self.data.Close) < self.slow_ema + 5:
            return

        price = self.data.Close[-1]
        ema_f = self.ema_fast[-1]
        ema_s = self.ema_slow[-1]
        vol = self.realized_vol[-1]
        atr = self.atr[-1]

        if any(np.isnan(x) for x in [ema_f, ema_s, vol, atr]) or atr <= 0:
            return

        # Vol-targeted size
        size = vol_target_size(vol, self.target_vol, self.max_leverage)

        # Señal: EMA crossover
        ema_f_prev = self.ema_fast[-2]
        ema_s_prev = self.ema_slow[-2]

        if np.isnan(ema_f_prev) or np.isnan(ema_s_prev):
            return

        golden_cross = (ema_f_prev <= ema_s_prev) and (ema_f > ema_s)
        death_cross = (ema_f_prev >= ema_s_prev) and (ema_f < ema_s)

        if not self.position:
            if golden_cross:
                sl = price - atr * self.sl_atr_mult
                tp = price + atr * self.tp_atr_mult
                if sl < price < tp:
                    self.buy(size=size, sl=sl, tp=tp)
            elif death_cross:
                sl = price + atr * self.sl_atr_mult
                tp = price - atr * self.tp_atr_mult
                if tp < price < sl:
                    self.sell(size=size, sl=sl, tp=tp)
        else:
            # Flip en señal contraria
            if self.position.is_long and death_cross:
                self.position.close()
            elif self.position.is_short and golden_cross:
                self.position.close()


class VolTargetedVolSqueeze(Strategy):
    """VolatilitySqueeze original + vol targeting overlay.

    Demuestra cómo aplicar vol targeting sobre una estrategia existente.
    Misma lógica que VolatilitySqueeze pero con sizing dinámico.
    """

    strategy_name = "VolTargeted VolSqueeze"
    strategy_type = "Trend Following"

    # Parámetros VolatilitySqueeze
    bb_len = 20
    bb_std = 2.0
    kc_len = 20
    kc_mult = 1.2
    mom_len = 9
    sl_mult = 2.0
    tp_mult = 4.0

    # Vol targeting overlay
    vol_window = 20
    target_vol = 0.12
    max_leverage = 2.0

    def init(self):
        close = pd.Series(self.data.Close, index=range(len(self.data.Close)))
        high = pd.Series(self.data.High, index=range(len(self.data.High)))
        low = pd.Series(self.data.Low, index=range(len(self.data.Low)))

        # BB
        bb = ta.bbands(close, length=self.bb_len, std=self.bb_std)
        self.bb_upper = self.I(lambda: bb.iloc[:, 2].values, name="BBU")
        self.bb_lower = self.I(lambda: bb.iloc[:, 0].values, name="BBL")

        # KC
        ema = ta.ema(close, length=self.kc_len)
        atr_kc = ta.atr(high, low, close, length=self.kc_len)
        kc_upper_vals = (ema + self.kc_mult * atr_kc).values
        kc_lower_vals = (ema - self.kc_mult * atr_kc).values
        self.kc_upper = self.I(lambda: kc_upper_vals, name="KCU")
        self.kc_lower = self.I(lambda: kc_lower_vals, name="KCL")

        # ATR
        atr_vals = ta.atr(high, low, close, length=14).values
        self.atr = self.I(lambda: atr_vals, name="ATR")

        # Momentum
        mom_vals = close.diff(self.mom_len).values
        self.momentum = self.I(lambda: mom_vals, name="MOM")

        # Squeeze
        bb_u = bb.iloc[:, 2]
        bb_l = bb.iloc[:, 0]
        squeeze_vals = ((bb_u < ema + self.kc_mult * atr_kc) &
                        (bb_l > ema - self.kc_mult * atr_kc)).astype(float).values
        self.squeeze = self.I(lambda: squeeze_vals, name="SQZ")

        # Vol targeting
        log_ret = np.log(close / close.shift(1))
        vol_vals = (log_ret.rolling(self.vol_window).std() * np.sqrt(365 * 24)).values
        self.realized_vol = self.I(lambda: vol_vals, name="RVOL")

    def next(self):
        price = self.data.Close[-1]
        atr = self.atr[-1]
        mom = self.momentum[-1]
        sqz_now = self.squeeze[-1]
        vol = self.realized_vol[-1]

        if len(self.data.Close) < 2:
            return

        sqz_prev = self.squeeze[-2]

        if any(np.isnan(x) for x in [atr, mom, vol]) or atr <= 0:
            return

        # Vol-targeted size (the overlay magic)
        size = vol_target_size(vol, self.target_vol, self.max_leverage)

        squeeze_released = (sqz_prev == 1.0) and (sqz_now == 0.0)

        if not self.position and squeeze_released:
            if mom > 0:
                sl = price - atr * self.sl_mult
                tp = price + atr * self.tp_mult
                if sl < price < tp:
                    self.buy(size=size, sl=sl, tp=tp)
            elif mom < 0:
                sl = price + atr * self.sl_mult
                tp = price - atr * self.tp_mult
                if tp < price < sl:
                    self.sell(size=size, sl=sl, tp=tp)


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from moondev.data.data_fetcher import get_ohlcv
    from backtesting import Backtest

    strategies = [
        ("VolTargeting EMA Cross", VolatilityTargetingEMACross),
        ("VolTargeted VolSqueeze", VolTargetedVolSqueeze),
    ]

    for name, cls in strategies:
        for symbol in ["BTC", "ETH", "SOL"]:
            print(f"\n== {name} -- {symbol} 1h 365d ==")
            df = get_ohlcv(symbol, interval="1h", days=365)
            if df is None or len(df) < 100:
                print(f"  Sin datos para {symbol}")
                continue
            cash = max(10_000, float(df["Close"].max()) * 3)
            bt = Backtest(df, cls, cash=cash, commission=0.001,
                          exclusive_orders=True, finalize_trades=True)
            stats = bt.run()
            print(stats[["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]",
                         "# Trades", "Win Rate [%]"]])
