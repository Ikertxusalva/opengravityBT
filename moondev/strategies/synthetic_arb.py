"""
SyntheticArb — simulación de carry trade cuando funding anual > 50%.

Sin datos reales de funding, simula: cuando RSI(funding_proxy) es extremo positivo,
el carry trade debería ser rentable. Usa OI proxy via volume spike.

Entry: Volume muy alto (> 3× media) = alta OI → funding probablemente positivo
Exit:  Después de N velas (holding period fijo) o si volumen cae

Inspirado en: fundingarb_agent de moon-dev-ai-agents
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas_ta as ta
from backtesting import Backtest, Strategy
from backtesting.test import SMA
import yfinance as yf


class SyntheticArb(Strategy):
    vol_multiplier = 3.0    # señal de alto OI / funding positivo
    hold_periods = 8        # velas a mantener (8 × 8h = 2.67 días)
    vol_avg_period = 20

    def init(self):
        self.vol_avg = self.I(SMA, self.data.Volume, self.vol_avg_period)
        self._entry_bar = 0

    def next(self):
        if len(self.data) < self.vol_avg_period + 1:
            return

        vol = self.data.Volume[-1]
        vol_avg = self.vol_avg[-1]
        bar = len(self.data)

        if not self.position:
            # Proxy: volumen alto = funding positivo = carry trade
            if vol > vol_avg * self.vol_multiplier:
                self.buy(size=0.95)
                self._entry_bar = bar
        else:
            # Exit por tiempo O caída de volumen
            held = bar - self._entry_bar
            if held >= self.hold_periods or vol < vol_avg * 0.5:
                self.position.close()


if __name__ == "__main__":
    data = yf.download("BTC-USD", period="365d", interval="4h", auto_adjust=True)
    data.columns = ["Close", "High", "Low", "Open", "Volume"]
    data = data[["Open", "High", "Low", "Close", "Volume"]].dropna()

    bt = Backtest(data, SyntheticArb, cash=10_000, commission=0.001,
                  exclusive_orders=True, finalize_trades=True)
    stats = bt.run()
    print(stats)
