"""
Estrategia: VolatilitySqueezeV3MultiAsset
Tipo: Breakout / Volatility
Logica: Squeeze = BB(20, 1.8std) completamente dentro de KC(20, 1.0xATR).
  - Minimo 2 barras en squeeze
  - ADX > 18 (confirma momentum de salida)
  - Volumen en breakout > 1.3x media(20)
  - Momentum(9) > 0 -> LONG, < 0 -> SHORT
  - SL: 1.5x ATR(14), TP: 3.5x ATR(14)
"""
import pandas as pd
import numpy as np
import pandas_ta as ta
from backtesting import Strategy, Backtest


class VolatilitySqueezeV3MultiAsset(Strategy):
    bb_length = 20
    bb_std = 1.8
    kc_length = 20
    kc_atr_mult = 1.5
    atr_length = 14
    adx_length = 14
    mom_length = 9
    vol_window = 20
    vol_mult = 1.3
    min_squeeze_bars = 2
    adx_threshold = 18
    sl_atr_mult = 1.5
    tp_atr_mult = 3.5

    def init(self):
        close  = pd.Series(self.data.Close,  index=range(len(self.data.Close)))
        high   = pd.Series(self.data.High,   index=range(len(self.data.High)))
        low    = pd.Series(self.data.Low,    index=range(len(self.data.Low)))
        volume = pd.Series(self.data.Volume, index=range(len(self.data.Volume)))

        # Bollinger Bands
        bb = ta.bbands(close, length=self.bb_length, std=self.bb_std)
        self.bb_upper = self.I(lambda: bb.iloc[:, 2].values, name="BB_Upper")
        self.bb_lower = self.I(lambda: bb.iloc[:, 0].values, name="BB_Lower")

        # Keltner Channel: mid +/- mult * ATR
        kc_mid = ta.ema(close, length=self.kc_length)
        kc_atr = ta.atr(high, low, close, length=self.kc_length)
        kc_upper_vals = (kc_mid + self.kc_atr_mult * kc_atr).values
        kc_lower_vals = (kc_mid - self.kc_atr_mult * kc_atr).values
        self.kc_upper = self.I(lambda: kc_upper_vals, name="KC_Upper")
        self.kc_lower = self.I(lambda: kc_lower_vals, name="KC_Lower")

        # ATR para SL/TP
        atr_vals = ta.atr(high, low, close, length=self.atr_length)
        self.atr = self.I(lambda: atr_vals.values, name="ATR")

        # ADX
        adx_df = ta.adx(high, low, close, length=self.adx_length)
        self.adx = self.I(lambda: adx_df.iloc[:, 0].values, name="ADX")

        # Momentum
        mom_vals = ta.mom(close, length=self.mom_length)
        self.mom = self.I(lambda: mom_vals.values, name="MOM")

        # Volume MA
        vol_ma = ta.sma(volume, length=self.vol_window)
        self.vol_ma = self.I(lambda: vol_ma.values, name="VolMA")

        self._squeeze_count = 0

    def next(self):
        min_bars = max(self.bb_length, self.kc_length, self.atr_length,
                       self.adx_length, self.mom_length, self.vol_window) + 5
        if len(self.data) < min_bars:
            return

        bb_u = self.bb_upper[-1]
        bb_l = self.bb_lower[-1]
        kc_u = self.kc_upper[-1]
        kc_l = self.kc_lower[-1]
        atr  = self.atr[-1]
        adx  = self.adx[-1]
        mom  = self.mom[-1]
        vol  = self.data.Volume[-1]
        vol_ma = self.vol_ma[-1]
        price = self.data.Close[-1]

        if any(np.isnan(x) for x in [bb_u, bb_l, kc_u, kc_l, atr, adx, mom, vol_ma]):
            return
        if atr <= 0 or vol_ma <= 0:
            return

        # Detectar squeeze: BB completamente dentro de KC
        in_squeeze = (bb_u < kc_u) and (bb_l > kc_l)

        if in_squeeze:
            self._squeeze_count += 1
        else:
            # Salida del squeeze — evaluar señal
            if not self.position and self._squeeze_count >= self.min_squeeze_bars:
                # Confirmar con ADX y volumen
                if adx > self.adx_threshold and vol > self.vol_mult * vol_ma:
                    sl = atr * self.sl_atr_mult
                    tp = atr * self.tp_atr_mult
                    if mom > 0:
                        self.buy(sl=price - sl, tp=price + tp)
                    elif mom < 0:
                        self.sell(sl=price + sl, tp=price - tp)
            self._squeeze_count = 0


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    import yfinance as yf

    data = yf.download("BTC-USD", period="1y", interval="1h", auto_adjust=True, progress=False)
    data.columns = [c[0] if isinstance(c, tuple) else c for c in data.columns]
    data = data[["Open", "High", "Low", "Close", "Volume"]].dropna()

    cash = max(10_000, data["Close"].max() * 3)
    bt = Backtest(data, VolatilitySqueezeV3MultiAsset, cash=cash, commission=0.001,
                  exclusive_orders=True, finalize_trades=True)
    s = bt.run()
    print(f"Return: {float(s['Return [%]']):.1f}%  "
          f"Sharpe: {float(s['Sharpe Ratio']) if str(s['Sharpe Ratio']) != 'nan' else 0:.2f}  "
          f"DD: {float(s['Max. Drawdown [%]']):.1f}%  "
          f"Trades: {int(s['# Trades'])}  "
          f"WR: {float(s['Win Rate [%]']) if str(s['Win Rate [%]']) != 'nan' else 0:.1f}%")
