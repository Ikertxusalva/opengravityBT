"""
TSMOM — Time Series Momentum (Moskowitz, Ooi, Pedersen 2012)

La estrategia de momentum más probada académicamente:
  - 44 años de datos, 58 instrumentos, Sharpe 1.31, alpha 20.7%
  - Fuente: AQR Capital Management

Reglas:
  - Si el retorno de los últimos N meses es > 0: LONG
  - Si el retorno de los últimos N meses es < 0: SHORT
  - Position sizing: vol targeting (target_vol / realized_vol)
  - Rebalance mensual (cada lookback_rebalance barras)

Adaptación crypto:
  - Lookback 252 barras (≈252h en 1h, ≈63 días en 4h, ≈252 días en 1d)
  - Vol targeting 12% anualizado (crypto más volátil que equities)
  - Max leverage 2.0x cap (protección contra vol extrema)
"""
import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Strategy


class TSMOM(Strategy):
    strategy_name = "TSMOM (Time Series Momentum)"
    strategy_type = "Trend Following"

    # ── Parámetros ────────────────────────────────────────────────────────
    lookback = 252          # Barras de retorno lookback (12 meses en 1d, ~10d en 1h)
    vol_window = 20         # Ventana para calcular vol realizada
    target_vol = 0.12       # Vol anualizada objetivo (12%)
    max_leverage = 2.0      # Cap de leverage
    sl_atr_mult = 3.0       # SL en múltiplos de ATR
    tp_atr_mult = 6.0       # TP en múltiplos de ATR (R:R 1:2)
    rebalance_freq = 20     # Rebalance cada N barras (~mensual en 1d)

    def init(self):
        close = pd.Series(self.data.Close, index=range(len(self.data.Close)))
        high = pd.Series(self.data.High, index=range(len(self.data.High)))
        low = pd.Series(self.data.Low, index=range(len(self.data.Low)))

        # Retorno sobre lookback period
        ret_vals = close.pct_change(self.lookback).values
        self.lookback_return = self.I(lambda: ret_vals, name="LB_RET")

        # Volatilidad realizada (rolling std de log returns, anualizada)
        log_ret = np.log(close / close.shift(1))
        # Anualizar: sqrt(barras_por_año). Para 1h ≈ 8760, 4h ≈ 2190, 1d ≈ 365
        # Usamos sqrt(365*24) como proxy conservador para 1h
        vol_vals = (log_ret.rolling(self.vol_window).std() * np.sqrt(365 * 24)).values
        self.realized_vol = self.I(lambda: vol_vals, name="RVOL")

        # ATR para SL/TP
        atr_vals = ta.atr(high, low, close, length=14).values
        self.atr = self.I(lambda: atr_vals, name="ATR")

        # Contador de barras para rebalance
        self._bar_count = 0

    def next(self):
        self._bar_count += 1

        # Protección warmup
        if len(self.data.Close) < self.lookback + 5:
            return

        ret = self.lookback_return[-1]
        vol = self.realized_vol[-1]
        atr = self.atr[-1]
        price = self.data.Close[-1]

        if np.isnan(ret) or np.isnan(vol) or np.isnan(atr) or vol <= 0 or atr <= 0:
            return

        # Vol targeting: sizing = target_vol / realized_vol, capped
        leverage = min(self.target_vol / vol, self.max_leverage)
        size = min(0.95, max(0.1, leverage * 0.95))

        # Solo operar en rebalance o si no tenemos posición
        is_rebalance = (self._bar_count % self.rebalance_freq == 0)

        if not self.position:
            # Señal TSMOM: dirección del retorno pasado
            if ret > 0:
                sl = price - atr * self.sl_atr_mult
                tp = price + atr * self.tp_atr_mult
                if sl < price < tp:
                    self.buy(size=size, sl=sl, tp=tp)
            elif ret < 0:
                sl = price + atr * self.sl_atr_mult
                tp = price - atr * self.tp_atr_mult
                if tp < price < sl:
                    self.sell(size=size, sl=sl, tp=tp)

        elif is_rebalance and self.position:
            # Rebalance: si la señal cambió de dirección, flip
            if self.position.is_long and ret < 0:
                self.position.close()
            elif self.position.is_short and ret > 0:
                self.position.close()


# Atributos para registry
TSMOM.strategy_name = "TSMOM (Time Series Momentum)"
TSMOM.strategy_type = "Trend Following"


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from moondev.data.data_fetcher import get_ohlcv
    from backtesting import Backtest

    for symbol in ["BTC", "ETH", "SOL"]:
        print(f"\n== TSMOM -- {symbol} 4h 730d ==")
        df = get_ohlcv(symbol, interval="4h", days=730)
        if df is None or len(df) < 300:
            print(f"  Sin datos para {symbol}")
            continue
        cash = max(10_000, float(df["Close"].max()) * 3)
        bt = Backtest(df, TSMOM, cash=cash, commission=0.001,
                      exclusive_orders=True, finalize_trades=True)
        stats = bt.run()
        print(stats[["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]",
                     "# Trades", "Win Rate [%]"]])
