"""
4 Forex Templates — calibrados para pares de divisas en timeframe 1h.

Diferencias clave respecto a los crypto/equity templates:
- SL/TP via ATR — esencial para forex; los % fijos (3-5%) son demasiado amplios para pips
- Sin dependencia de volumen — yfinance retorna volumen 0/irreal en forex
- EMAs cortas (5/13, 9/21) — forex 1h necesita señales más frecuentes
- Umbrales RSI estándar 30/70 — forex llega a extremos de oscilador con más frecuencia
- ADX threshold bajo (15) — forex daily raramente supera 25 ADX

Compatibles con: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF
También útiles para: SPY, GLD, AAPL (baja volatilidad)
"""
import numpy as np
import pandas_ta as ta
from backtesting.lib import crossover

from rbi.strategies.base import RBIStrategy


# ─────────────────────────────────────────────────────────────────────────────
# 1. FOREX_EMA_CROSS_ATR
# ─────────────────────────────────────────────────────────────────────────────
class ForexEMACrossATR(RBIStrategy):
    """EMA 9/21 Crossover con filtro ADX — calibrado para forex 1h.

    Long:  EMA 9 cruza por encima de EMA 21 + ADX > 15 (tendencia débil confirmada).
    Short: EMA 9 cruza por debajo de EMA 21 + ADX > 15.
    SL/TP via ATR — funciona con cualquier precio (pips o crypto).
    EMAs cortas (9/21) generan más señales en forex 1h que 50/200.
    """

    strategy_name = "Forex EMA Cross ATR"
    strategy_type = "Trend Following"

    ema_fast      = 9
    ema_slow      = 21
    adx_period    = 14
    adx_threshold = 15.0   # más bajo que equity (20) — forex tiene ADX más bajo
    atr_period    = 14
    sl_atr_mult   = 1.5
    tp_atr_mult   = 3.0    # RR = 2:1

    def init(self):
        n    = len(self.data)
        _nan = np.full(n, np.nan)

        ema_f_raw = ta.ema(self.close, length=self.ema_fast)
        ema_s_raw = ta.ema(self.close, length=self.ema_slow)
        adx_raw   = ta.adx(self.high, self.low, self.close, length=self.adx_period)
        atr_raw   = ta.atr(self.high, self.low, self.close, length=self.atr_period)

        ema_f   = ema_f_raw                  if ema_f_raw  is not None else _nan
        ema_s   = ema_s_raw                  if ema_s_raw  is not None else _nan
        adx_col = adx_raw.iloc[:, 0].values  if adx_raw    is not None else _nan
        atr_v   = atr_raw.values             if atr_raw    is not None else _nan

        self.ema_f = self.I(lambda: ema_f,   name="EMA_Fast")
        self.ema_s = self.I(lambda: ema_s,   name="EMA_Slow")
        self.adx   = self.I(lambda: adx_col, name="ADX")
        self.atr   = self.I(lambda: atr_v,   name="ATR")

    def next(self):
        warmup = self.ema_slow + self.adx_period + 2
        if len(self.data) < warmup:
            return
        if np.isnan(self.adx[-1]) or np.isnan(self.ema_f[-1]) or np.isnan(self.atr[-1]):
            return

        price        = self.data.Close[-1]
        atr          = self.atr[-1]
        strong_trend = self.adx[-1] > self.adx_threshold

        if not self.position:
            if strong_trend and crossover(self.ema_f, self.ema_s):
                self.buy(sl=price - self.sl_atr_mult * atr,
                         tp=price + self.tp_atr_mult * atr)
            elif strong_trend and crossover(self.ema_s, self.ema_f):
                self.sell(sl=price + self.sl_atr_mult * atr,
                          tp=price - self.tp_atr_mult * atr)
        else:
            if self.position.is_long and crossover(self.ema_s, self.ema_f):
                self.position.close()
            elif self.position.is_short and crossover(self.ema_f, self.ema_s):
                self.position.close()


# ─────────────────────────────────────────────────────────────────────────────
# 2. FOREX_BB_REVERSION_ATR
# ─────────────────────────────────────────────────────────────────────────────
class ForexBBReversionATR(RBIStrategy):
    """Bollinger Bands Mean Reversion — calibrado para forex 1h.

    Long:  precio <= banda inferior BB.
    Short: precio >= banda superior BB.
    Salida: precio vuelve a banda media O por SL/TP ATR.
    Sin dependencia de volumen — adecuado para forex donde el volumen es irreal.
    BB std=1.8 genera más señales que 2.0 estándar.
    """

    strategy_name = "Forex BB Reversion ATR"
    strategy_type = "Mean Reversion"

    bb_length   = 20
    bb_std      = 1.8    # más estrecho que 2.0 → más señales en forex
    atr_period  = 14
    sl_atr_mult = 1.5
    tp_atr_mult = 2.5    # RR ≈ 1.7:1

    def init(self):
        n    = len(self.data)
        _nan = np.full(n, np.nan)

        bb  = ta.bbands(self.close, length=self.bb_length, std=self.bb_std)
        atr = ta.atr(self.high, self.low, self.close, length=self.atr_period)

        bb_lower = bb.iloc[:, 0].values if bb  is not None else _nan
        bb_mid   = bb.iloc[:, 1].values if bb  is not None else _nan
        bb_upper = bb.iloc[:, 2].values if bb  is not None else _nan
        atr_v    = atr.values           if atr is not None else _nan

        self.bb_lower = self.I(lambda: bb_lower, name="BB_Lower")
        self.bb_mid   = self.I(lambda: bb_mid,   name="BB_Mid")
        self.bb_upper = self.I(lambda: bb_upper, name="BB_Upper")
        self.atr      = self.I(lambda: atr_v,    name="ATR")

    def next(self):
        warmup = self.bb_length + self.atr_period + 2
        if len(self.data) < warmup:
            return
        if np.isnan(self.bb_lower[-1]) or np.isnan(self.atr[-1]):
            return

        price = self.data.Close[-1]
        atr   = self.atr[-1]

        if not self.position:
            if price <= self.bb_lower[-1]:
                self.buy(sl=price - self.sl_atr_mult * atr,
                         tp=price + self.tp_atr_mult * atr)
            elif price >= self.bb_upper[-1]:
                self.sell(sl=price + self.sl_atr_mult * atr,
                          tp=price - self.tp_atr_mult * atr)
        else:
            if self.position.is_long and price >= self.bb_mid[-1]:
                self.position.close()
            elif self.position.is_short and price <= self.bb_mid[-1]:
                self.position.close()


# ─────────────────────────────────────────────────────────────────────────────
# 3. FOREX_RSI_RANGE_ATR
# ─────────────────────────────────────────────────────────────────────────────
class ForexRSIRangeATR(RBIStrategy):
    """RSI Overbought/Oversold — calibrado para forex 1h en rango.

    Umbrales 30/70 estándar. Sin volumen.
    SL/TP via ATR para adaptarse a cualquier precio.
    RSI period=10 (más reactivo que 14) para 1h forex.
    Confirma salida con RSI cruzando nivel neutral (50).
    """

    strategy_name = "Forex RSI Range ATR"
    strategy_type = "Mean Reversion"

    rsi_period  = 10    # más reactivo que 14 — genera más trades en 1h
    rsi_oversold  = 30
    rsi_overbought = 70
    rsi_exit_long  = 55
    rsi_exit_short = 45
    atr_period    = 14
    sl_atr_mult   = 1.5
    tp_atr_mult   = 2.5

    def init(self):
        n    = len(self.data)
        _nan = np.full(n, np.nan)

        rsi = ta.rsi(self.close, length=self.rsi_period)
        atr = ta.atr(self.high, self.low, self.close, length=self.atr_period)

        rsi_v = rsi.values if rsi is not None else _nan
        atr_v = atr.values if atr is not None else _nan

        self.rsi = self.I(lambda: rsi_v, name="RSI")
        self.atr = self.I(lambda: atr_v, name="ATR")

    def next(self):
        warmup = self.rsi_period + self.atr_period + 2
        if len(self.data) < warmup:
            return
        if np.isnan(self.rsi[-1]) or np.isnan(self.atr[-1]):
            return

        price = self.data.Close[-1]
        atr   = self.atr[-1]
        rsi   = self.rsi[-1]

        if not self.position:
            if rsi < self.rsi_oversold:
                self.buy(sl=price - self.sl_atr_mult * atr,
                         tp=price + self.tp_atr_mult * atr)
            elif rsi > self.rsi_overbought:
                self.sell(sl=price + self.sl_atr_mult * atr,
                          tp=price - self.tp_atr_mult * atr)
        else:
            if self.position.is_long and rsi > self.rsi_exit_long:
                self.position.close()
            elif self.position.is_short and rsi < self.rsi_exit_short:
                self.position.close()


# ─────────────────────────────────────────────────────────────────────────────
# 4. FOREX_MACD_ATR
# ─────────────────────────────────────────────────────────────────────────────
class ForexMACDATR(RBIStrategy):
    """MACD Crossover + Histograma — calibrado para forex 1h.

    Long:  MACD cruza por encima de Signal + histograma positivo.
    Short: MACD cruza por debajo de Signal + histograma negativo.
    MACD rápido (6/13/5) vs estándar (12/26/9) — genera el doble de señales.
    SL/TP via ATR. Sin volumen.
    """

    strategy_name = "Forex MACD ATR"
    strategy_type = "Trend Following"

    macd_fast   = 6     # vs 12 estándar — más señales en 1h forex
    macd_slow   = 13    # vs 26 estándar
    macd_signal = 5     # vs 9 estándar
    atr_period  = 14
    sl_atr_mult = 1.5
    tp_atr_mult = 3.0

    def init(self):
        n    = len(self.data)
        _nan = np.full(n, np.nan)

        macd_df = ta.macd(self.close,
                          fast=self.macd_fast,
                          slow=self.macd_slow,
                          signal=self.macd_signal)
        atr = ta.atr(self.high, self.low, self.close, length=self.atr_period)

        if macd_df is not None and len(macd_df.columns) >= 3:
            macd_line = macd_df.iloc[:, 0].values
            macd_sig  = macd_df.iloc[:, 1].values
            macd_hist = macd_df.iloc[:, 2].values
        else:
            macd_line = macd_sig = macd_hist = _nan

        atr_v = atr.values if atr is not None else _nan

        self.macd_line = self.I(lambda: macd_line, name="MACD")
        self.macd_sig  = self.I(lambda: macd_sig,  name="MACD_Signal")
        self.macd_hist = self.I(lambda: macd_hist, name="MACD_Hist")
        self.atr       = self.I(lambda: atr_v,     name="ATR")

    def next(self):
        warmup = self.macd_slow + self.macd_signal + self.atr_period + 2
        if len(self.data) < warmup:
            return
        if np.isnan(self.macd_line[-1]) or np.isnan(self.atr[-1]):
            return

        price = self.data.Close[-1]
        atr   = self.atr[-1]

        if not self.position:
            if crossover(self.macd_line, self.macd_sig) and self.macd_hist[-1] > 0:
                self.buy(sl=price - self.sl_atr_mult * atr,
                         tp=price + self.tp_atr_mult * atr)
            elif crossover(self.macd_sig, self.macd_line) and self.macd_hist[-1] < 0:
                self.sell(sl=price + self.sl_atr_mult * atr,
                          tp=price - self.tp_atr_mult * atr)


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────
FOREX_TEMPLATE_REGISTRY: dict[str, type[RBIStrategy]] = {
    "forex-ema-cross-atr":      ForexEMACrossATR,
    "forex-bb-reversion-atr":   ForexBBReversionATR,
    "forex-rsi-range-atr":      ForexRSIRangeATR,
    "forex-macd-atr":           ForexMACDATR,
}
