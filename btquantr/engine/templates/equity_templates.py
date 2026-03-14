"""
3 Equity/ETF Templates — calibrados para mercados de renta variable (daily).

Diferencias clave respecto a los crypto templates:
- EMA 50/200 (vs 9/21 crypto) — tendencias son más lentas en equity
- ADX threshold 20 (vs 25) — equity daily suele tener ADX menor
- RSI thresholds 40/60 (vs 30/70) — equity raramente extrema en daily
- BB std 1.5 (vs 2.0) — bandas más estrechas para volatilidad baja
- SL/TP via ATR — se adapta a la volatilidad del activo (no % fijo)
"""
import numpy as np
import pandas_ta as ta
from backtesting.lib import crossover

from rbi.strategies.base import RBIStrategy


# ─────────────────────────────────────────────────────────────────────────────
# 1. EMA_CROSSOVER_EQUITY
# ─────────────────────────────────────────────────────────────────────────────
class EMACrossoverEquity(RBIStrategy):
    """EMA 50/200 Crossover con filtro ADX — calibrado para equity daily.

    Long:  EMA 50 cruza por encima de EMA 200 + ADX > 20 (tendencia confirmada).
    Short: EMA 50 cruza por debajo de EMA 200 + ADX > 20.
    SL/TP via ATR para adaptarse a la volatilidad del activo.
    """

    strategy_name = "EMA Crossover Equity"
    strategy_type = "Trend Following"

    ema_fast      = 50
    ema_slow      = 200
    adx_period    = 14
    adx_threshold = 20.0
    atr_period    = 14
    sl_atr_mult   = 2.0
    tp_atr_mult   = 4.0   # RR = 2:1

    def init(self):
        n     = len(self.data)
        _nan  = np.full(n, np.nan)

        ema_f_raw  = ta.ema(self.close, length=self.ema_fast)
        ema_s_raw  = ta.ema(self.close, length=self.ema_slow)
        adx_raw    = ta.adx(self.high, self.low, self.close, length=self.adx_period)
        atr_raw    = ta.atr(self.high, self.low, self.close, length=self.atr_period)

        ema_f   = ema_f_raw                 if ema_f_raw  is not None else _nan
        ema_s   = ema_s_raw                 if ema_s_raw  is not None else _nan
        adx_col = adx_raw.iloc[:, 0].values if adx_raw    is not None else _nan
        atr_v   = atr_raw.values            if atr_raw    is not None else _nan

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
# 2. RSI_EQUITY
# ─────────────────────────────────────────────────────────────────────────────
class RSIEquity(RBIStrategy):
    """RSI Mean Reversion — calibrado para equity daily.

    Umbrales 40/60 en vez de 30/70: en daily equity el RSI raramente
    llega a extremos, y 40/60 genera más señales sin demasiado ruido.
    SL/TP via ATR.
    """

    strategy_name = "RSI Equity"
    strategy_type = "Mean Reversion"

    rsi_period = 14
    rsi_buy    = 40
    rsi_sell   = 60
    atr_period = 14
    sl_atr_mult = 1.5
    tp_atr_mult = 3.0   # RR = 2:1

    def init(self):
        rsi = ta.rsi(self.close, length=self.rsi_period)
        atr = ta.atr(self.high, self.low, self.close, length=self.atr_period)

        self.rsi = self.I(lambda: rsi, name="RSI")
        self.atr = self.I(lambda: atr, name="ATR")

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
            if rsi < self.rsi_buy:
                self.buy(sl=price - self.sl_atr_mult * atr,
                         tp=price + self.tp_atr_mult * atr)
            elif rsi > self.rsi_sell:
                self.sell(sl=price + self.sl_atr_mult * atr,
                          tp=price - self.tp_atr_mult * atr)


# ─────────────────────────────────────────────────────────────────────────────
# 3. BOLLINGER_EQUITY
# ─────────────────────────────────────────────────────────────────────────────
class BollingerEquity(RBIStrategy):
    """Bollinger Bands Mean Reversion — calibrado para equity daily.

    BB std=1.5 en vez de 2.0: bandas más estrechas que capturan
    desviaciones relevantes en activos de baja volatilidad.
    Salida: precio vuelve a la banda media o por SL/TP ATR.
    """

    strategy_name = "Bollinger Equity"
    strategy_type = "Mean Reversion"

    bb_length  = 20
    bb_std     = 1.5
    atr_period = 14
    sl_atr_mult = 1.5
    tp_atr_mult = 3.0   # RR = 2:1

    def init(self):
        bb  = ta.bbands(self.close, length=self.bb_length, std=self.bb_std)
        atr = ta.atr(self.high, self.low, self.close, length=self.atr_period)

        self.bb_lower = self.I(lambda: bb.iloc[:, 0], name="BB_Lower")
        self.bb_mid   = self.I(lambda: bb.iloc[:, 1], name="BB_Mid")
        self.bb_upper = self.I(lambda: bb.iloc[:, 2], name="BB_Upper")
        self.atr      = self.I(lambda: atr,           name="ATR")

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
# Registry
# ─────────────────────────────────────────────────────────────────────────────
EQUITY_TEMPLATE_REGISTRY: dict[str, type[RBIStrategy]] = {
    "ema-crossover-equity": EMACrossoverEquity,
    "rsi-equity":           RSIEquity,
    "bollinger-equity":     BollingerEquity,
}
