"""
PairsBTCETH — Statistical Arbitrage BTC/ETH via z-score del spread log-precio.

Edge documentado:
  - Amberdata (empirical): Sharpe 0.93, Return 16%, DD -15.67%
  - EUR Thesis 2019-2024: Sharpe ~1.0, Return 16%
  - arXiv:2109.10662: Profit Factor 3.74, half-life spread 5-15 días

Lógica:
  - Calcular spread log: log(BTC) - β × log(ETH)    [β = hedge ratio OLS pre-calc]
  - z-score rolling del spread (ventana 504 barras × 4h = ~84 días)
  - z < -entry_z  → LONG spread (BTC barato vs ETH → comprar BTC proxy)
  - z > +entry_z  → SHORT spread (BTC caro vs ETH → vender BTC proxy)
  - Exit: z revierte a ±exit_z
  - Stop emergencia: |z| > stop_z (cointegración rota)

Implementación backtesting.py:
  ETH data se descarga en init() y se alinea con BTC (main symbol).
  Limitación: mono-símbolo → ETH price se importa como columna auxiliar.
  El "trade" opera solo BTC como proxy del spread.

⚠️  BUG HISTÓRICO CORREGIDO: zscore_window 252→504 barras 4h
     252 barras 1h = ~10 días (estadísticamente inválido)
     504 barras 4h = ~84 días (mínimo robusto para cointegración)
     Si se usa 1h: configurar zscore_window=2016 (504×4)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import warnings
import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy

warnings.filterwarnings("ignore", category=FutureWarning)


def _download_eth_aligned(btc_index: pd.DatetimeIndex, interval: str = "4h") -> pd.Series:
    """Descarga ETH-USD y lo alinea al índice de BTC."""
    try:
        import yfinance as yf
        # Descargar suficiente historia para el período de BTC
        start = btc_index[0] - pd.Timedelta(days=30)
        end   = btc_index[-1] + pd.Timedelta(days=1)
        eth = yf.download("ETH-USD", start=start, end=end,
                          interval=interval, auto_adjust=True, progress=False)
        if eth.empty:
            return pd.Series(np.nan, index=btc_index)
        eth_close = eth["Close"].squeeze()
        eth_close.index = pd.to_datetime(eth_close.index, utc=True)
        btc_idx_utc = btc_index.tz_localize("UTC") if btc_index.tzinfo is None else btc_index
        eth_aligned = eth_close.reindex(btc_idx_utc, method="ffill")
        eth_aligned.index = btc_index
        return eth_aligned
    except Exception as e:
        print(f"[PairsBTCETH] Error descargando ETH: {e}")
        return pd.Series(np.nan, index=btc_index)


class PairsBTCETH(Strategy):
    """
    Statistical Arbitrage BTC/ETH — z-score del spread log-precio.

    Parámetros:
        beta          : hedge ratio OLS (típico 0.6-0.8 históricamente)
        zscore_window : barras rolling (504 × 4h = ~84 días)
        entry_z       : z-score para entrar (|z| > entry_z)
        exit_z        : z-score para salir (|z| < exit_z, reversión)
        stop_z        : z-score para stop emergencia (cointegración rota)
        interval      : timeframe de ETH a descargar ('4h' por defecto)
    """
    beta          = 7     # ÷10 → 0.7 hedge ratio OLS
    zscore_window = 504   # barras 4h = ~84 días (NO usar < 252 en 4h)
    entry_z       = 20    # ÷10 → 2.0
    exit_z        = 5     # ÷10 → 0.5
    stop_z        = 35    # ÷10 → 3.5 (emergencia: cointegración rota)
    interval      = "4h"  # timeframe ETH — debe coincidir con BTC

    def init(self):
        close_btc = pd.Series(self.data.Close)
        idx = close_btc.index

        # Descargar ETH alineado al índice BTC
        eth_series = _download_eth_aligned(idx, interval=self.interval)

        # Calcular spread log-precio
        beta_f = float(self.beta) / 10.0
        log_btc = np.log(close_btc.clip(lower=1e-8))
        log_eth = np.log(eth_series.clip(lower=1e-8).fillna(method="ffill"))
        spread  = log_btc - beta_f * log_eth

        # Z-score rolling
        win  = int(self.zscore_window)
        s_mean = spread.rolling(win, min_periods=win // 2).mean()
        s_std  = spread.rolling(win, min_periods=win // 2).std()
        zscore = (spread - s_mean) / (s_std + 1e-10)

        self.zscore = self.I(lambda: zscore.fillna(0).values, name='ZScore')
        self.spread = self.I(lambda: spread.fillna(0).values, name='Spread')

    def next(self):
        if len(self.data) < self.zscore_window // 2 + 2:
            return

        z    = self.zscore[-1]
        z_p  = self.zscore[-2]

        entry = float(self.entry_z) / 10.0
        ex    = float(self.exit_z)  / 10.0
        stop  = float(self.stop_z)  / 10.0

        if np.isnan(z):
            return

        if self.position:
            held_ok = abs(z) < stop  # cointegración intacta

            if self.position.is_long:
                # Long spread: salir cuando z revirtió (z > -exit_z)
                if z > -ex or not held_ok:
                    self.position.close()
            else:
                # Short spread: salir cuando z revirtió (z < +exit_z)
                if z < ex or not held_ok:
                    self.position.close()
        else:
            if abs(z) > stop:
                return  # spread demasiado lejos → cointegración sospechosa

            # Primer cruce hacia territorio extremo (evita entrar en tendencia)
            if z_p >= -entry and z < -entry:
                # Spread muy bajo → BTC barato → LONG BTC proxy
                self.buy(size=0.95)

            elif z_p <= entry and z > entry:
                # Spread muy alto → BTC caro → SHORT BTC proxy
                self.sell(size=0.95)


if __name__ == "__main__":
    from moondev.data.data_fetcher import get_ohlcv

    print("\n== PairsBTCETH — BTC 4h 2y ==\n")
    df = get_ohlcv("BTC", interval="4h", days=730)
    if df is None or len(df) < 200:
        print("ERROR: Sin datos suficientes")
        sys.exit(1)

    print(f"Datos: {len(df)} barras, {df.index[0]} → {df.index[-1]}")
    cash = max(10_000, float(df["Close"].max()) * 3)

    bt = Backtest(df, PairsBTCETH, cash=cash, commission=0.001,
                  exclusive_orders=True, finalize_trades=True)
    stats = bt.run()
    print(stats[["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "# Trades", "Win Rate [%]"]])

    # Optimización rápida de parámetros clave
    print("\nOptimizando entry_z y zscore_window...")
    opt = bt.optimize(
        entry_z    = [15, 20, 25],
        zscore_window = [252, 504, 756],
        maximize   = "Sharpe Ratio",
        constraint = lambda p: p.entry_z < p.stop_z,
    )
    print(opt._strategy)
    print(opt[["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "# Trades"]])
