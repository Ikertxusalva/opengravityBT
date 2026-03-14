"""
FundingArbReal — Delta-neutral funding rate arbitrage.

Long spot + short perp cuando funding > threshold. Exit cuando rate < exit_threshold.
Proxy de funding via (close - SMA) / SMA para backtest sin datos reales.

Spec: moondev/data/specs/funding_arb_real.md
Edge: arXiv:2212.06888 — Sharpe 1.8 retail, 3.5 market makers
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy


class FundingArbReal(Strategy):
    funding_entry = 2     # ÷1000 → 0.002 (~2% desviación de SMA)
    funding_exit = 1      # ÷1000 → 0.001
    zscore_entry = 8      # ÷10 → 0.8
    zscore_exit = -5      # ÷10 → -0.5 (mantener hasta reversión)
    max_hold = 60         # barras (~10 días en 4h)
    sma_period = 20
    sl_pct = 30           # ÷1000 → 0.03 (3% stop loss)
    tp_pct = 60           # ÷1000 → 0.06 (6% take profit, 2:1 ratio)

    def init(self):
        close = pd.Series(self.data.Close)
        sma = ta.sma(close, self.sma_period)

        funding_proxy = (close - sma) / sma * 0.1
        spread_mean = ta.sma(funding_proxy, self.sma_period)
        spread_std = funding_proxy.rolling(self.sma_period).std()
        zscore = (funding_proxy - spread_mean) / (spread_std + 1e-10)

        self.funding = self.I(lambda: funding_proxy.fillna(0).values, name='Funding')
        self.zscore = self.I(lambda: zscore.fillna(0).values, name='ZScore')
        self._entry_bar = 0

    def next(self):
        if len(self.data) < self.sma_period * 2:
            return

        f_entry = float(self.funding_entry) / 1000.0
        f_exit = float(self.funding_exit) / 1000.0
        z_entry = float(self.zscore_entry) / 10.0
        z_exit = float(self.zscore_exit) / 10.0

        funding = self.funding[-1]
        zscore = self.zscore[-1]
        bar = len(self.data)

        if np.isnan(funding) or np.isnan(zscore):
            return

        sl = float(self.sl_pct) / 1000.0
        tp = float(self.tp_pct) / 1000.0

        if self.position:
            held = bar - self._entry_bar
            exit_low_funding = funding < f_exit
            exit_zscore = zscore < z_exit
            exit_timeout = held >= self.max_hold

            if exit_low_funding or exit_zscore or exit_timeout:
                self.position.close()
        else:
            if funding > f_entry and zscore > z_entry:
                price = self.data.Close[-1]
                self.buy(size=0.95, sl=price * (1 - sl), tp=price * (1 + tp))
                self._entry_bar = bar


if __name__ == "__main__":
    from moondev.data.data_fetcher import get_ohlcv

    print("\n== FundingArbReal — BTC 4h 365d ==\n")
    df = get_ohlcv("BTC", interval="4h", days=365)
    if df is None or len(df) < 100:
        print("ERROR: Sin datos suficientes")
        sys.exit(1)

    print(f"Datos: {len(df)} barras")
    cash = max(10_000, float(df["Close"].max()) * 3)

    bt = Backtest(df, FundingArbReal, cash=cash, commission=0.001,
                  exclusive_orders=True, finalize_trades=True)
    stats = bt.run()
    print(stats[["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "# Trades", "Win Rate [%]"]])
