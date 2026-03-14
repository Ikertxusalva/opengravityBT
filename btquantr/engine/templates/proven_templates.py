"""
15 Proven Templates — estrategias backtesting.py de referencia.

Cada template:
- Hereda de RBIStrategy (backtesting.Strategy con utilidades pandas-ta)
- Implementa init() y next() correctos
- Usa self.I() para todos los indicadores
- Incluye SL y TP en cada trade
- Gestiona NaN correctamente

Templates:
    BB_MEAN_REVERSION       - Mean Reversion con Bollinger Bands
    KELTNER_MEAN_REVERSION  - Mean Reversion con Keltner Channel
    EMA_CROSSOVER_ADX       - EMA cross filtrado por tendencia ADX
    DONCHIAN_BREAKOUT       - Breakout de canal Donchian
    MACD_MOMENTUM           - Cruce MACD con confirmación histograma
    BB_INSIDE_KELTNER       - Squeeze (BB dentro de KC) + momentum
    ATR_EXPANSION           - Breakout por expansión súbita de ATR
    FUNDING_RATE_CONTRARIAN - Contrarian por momentum extremo (proxy funding)
    VOLUME_SPIKE_BREAKOUT   - Breakout con spike de volumen
    RSI_BB_COMBO            - RSI + Bollinger doble confirmación
    STOCH_MACD_CONFIRM      - Estocástico + MACD confirmación
    TRIPLE_EMA_FILTER       - Triple EMA + pullback
    ATR_SIZED_ENTRY         - Entrada con SL/TP calibrado por ATR
    REGIME_SWITCH           - Switching trend/mean-reversion por ADX
    TIME_OF_DAY             - Filtro horario UTC + EMA crossover
"""
import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting.lib import crossover

from rbi.strategies.base import RBIStrategy


# ─────────────────────────────────────────────────────────────────────────────
# 1. BB_MEAN_REVERSION
# ─────────────────────────────────────────────────────────────────────────────
class BBMeanReversion(RBIStrategy):
    """Bollinger Bands Mean Reversion.

    Long: precio <= banda inferior. Short: precio >= banda superior.
    Salida: precio vuelve a la banda media o por SL/TP.
    """

    strategy_name = "BB Mean Reversion"
    strategy_type = "Mean Reversion"

    bb_length = 20
    bb_std = 2.0
    stop_loss_pct = 0.03
    take_profit_pct = 0.05

    def init(self):
        bb = ta.bbands(self.close, length=self.bb_length, std=self.bb_std)
        self.bb_lower = self.I(lambda: bb.iloc[:, 0], name="BB_Lower")
        self.bb_mid   = self.I(lambda: bb.iloc[:, 1], name="BB_Mid")
        self.bb_upper = self.I(lambda: bb.iloc[:, 2], name="BB_Upper")

    def next(self):
        if len(self.data) < self.bb_length + 1:
            return
        if np.isnan(self.bb_lower[-1]) or np.isnan(self.bb_upper[-1]):
            return

        price = self.data.Close[-1]

        if not self.position:
            if price <= self.bb_lower[-1]:
                self.buy(sl=price * (1 - self.stop_loss_pct),
                         tp=price * (1 + self.take_profit_pct))
            elif price >= self.bb_upper[-1]:
                self.sell(sl=price * (1 + self.stop_loss_pct),
                          tp=price * (1 - self.take_profit_pct))
        else:
            if self.position.is_long and price >= self.bb_mid[-1]:
                self.position.close()
            elif self.position.is_short and price <= self.bb_mid[-1]:
                self.position.close()


# ─────────────────────────────────────────────────────────────────────────────
# 2. KELTNER_MEAN_REVERSION
# ─────────────────────────────────────────────────────────────────────────────
class KeltnerMeanReversion(RBIStrategy):
    """Keltner Channel Mean Reversion.

    Long: precio toca banda inferior KC.
    Short: precio toca banda superior KC.
    Salida: precio vuelve al centro KC o por SL/TP.
    """

    strategy_name = "Keltner Mean Reversion"
    strategy_type = "Mean Reversion"

    kc_length = 20
    kc_scalar = 2.0
    stop_loss_pct = 0.03
    take_profit_pct = 0.05

    def init(self):
        kc = ta.kc(self.high, self.low, self.close,
                   length=self.kc_length, scalar=self.kc_scalar)
        self.kc_lower = self.I(lambda: kc.iloc[:, 0], name="KC_Lower")
        self.kc_mid   = self.I(lambda: kc.iloc[:, 1], name="KC_Mid")
        self.kc_upper = self.I(lambda: kc.iloc[:, 2], name="KC_Upper")

    def next(self):
        if len(self.data) < self.kc_length + 1:
            return
        if np.isnan(self.kc_lower[-1]) or np.isnan(self.kc_upper[-1]):
            return

        price = self.data.Close[-1]

        if not self.position:
            if price <= self.kc_lower[-1]:
                self.buy(sl=price * (1 - self.stop_loss_pct),
                         tp=price * (1 + self.take_profit_pct))
            elif price >= self.kc_upper[-1]:
                self.sell(sl=price * (1 + self.stop_loss_pct),
                          tp=price * (1 - self.take_profit_pct))
        else:
            if self.position.is_long and price >= self.kc_mid[-1]:
                self.position.close()
            elif self.position.is_short and price <= self.kc_mid[-1]:
                self.position.close()


# ─────────────────────────────────────────────────────────────────────────────
# 3. EMA_CROSSOVER_ADX
# ─────────────────────────────────────────────────────────────────────────────
class EMACrossoverADX(RBIStrategy):
    """EMA Crossover filtrado por ADX.

    Long: EMA rápida cruza por encima de EMA lenta + ADX > umbral.
    Short: EMA rápida cruza por debajo de EMA lenta + ADX > umbral.
    El filtro ADX evita señales falsas en mercados laterales.
    """

    strategy_name = "EMA Crossover + ADX"
    strategy_type = "Trend Following"

    ema_fast = 9
    ema_slow = 21
    adx_period = 14
    adx_threshold = 25.0
    stop_loss_pct = 0.025
    take_profit_pct = 0.05

    def init(self):
        ema_f  = ta.ema(self.close, length=self.ema_fast)
        ema_s  = ta.ema(self.close, length=self.ema_slow)
        adx_df = ta.adx(self.high, self.low, self.close, length=self.adx_period)

        self.ema_f = self.I(lambda: ema_f,             name="EMA_Fast")
        self.ema_s = self.I(lambda: ema_s,             name="EMA_Slow")
        self.adx   = self.I(lambda: adx_df.iloc[:, 0], name="ADX")

    def next(self):
        if len(self.data) < self.ema_slow + self.adx_period + 2:
            return
        if np.isnan(self.adx[-1]) or np.isnan(self.ema_f[-1]):
            return

        price = self.data.Close[-1]
        strong_trend = self.adx[-1] > self.adx_threshold

        if not self.position:
            if strong_trend and crossover(self.ema_f, self.ema_s):
                self.buy(sl=price * (1 - self.stop_loss_pct),
                         tp=price * (1 + self.take_profit_pct))
            elif strong_trend and crossover(self.ema_s, self.ema_f):
                self.sell(sl=price * (1 + self.stop_loss_pct),
                          tp=price * (1 - self.take_profit_pct))
        else:
            if self.position.is_long and crossover(self.ema_s, self.ema_f):
                self.position.close()
            elif self.position.is_short and crossover(self.ema_f, self.ema_s):
                self.position.close()


# ─────────────────────────────────────────────────────────────────────────────
# 4. DONCHIAN_BREAKOUT
# ─────────────────────────────────────────────────────────────────────────────
class DonchianBreakout(RBIStrategy):
    """Donchian Channel Breakout (Turtle Trading style).

    Long: precio actual supera el máximo de N períodos anteriores.
    Short: precio actual cae bajo el mínimo de N períodos anteriores.
    """

    strategy_name = "Donchian Breakout"
    strategy_type = "Breakout"

    dc_length = 20
    stop_loss_pct = 0.03
    take_profit_pct = 0.06

    def init(self):
        dc = ta.donchian(self.high, self.low,
                         lower_length=self.dc_length,
                         upper_length=self.dc_length)
        self.dc_lower = self.I(lambda: dc.iloc[:, 0], name="DC_Lower")
        self.dc_mid   = self.I(lambda: dc.iloc[:, 1], name="DC_Mid")
        self.dc_upper = self.I(lambda: dc.iloc[:, 2], name="DC_Upper")

    def next(self):
        if len(self.data) < self.dc_length + 2:
            return
        if np.isnan(self.dc_upper[-2]) or np.isnan(self.dc_lower[-2]):
            return

        price = self.data.Close[-1]

        if not self.position:
            # Usa barra anterior del canal para evitar look-ahead
            if price > self.dc_upper[-2]:
                self.buy(sl=price * (1 - self.stop_loss_pct),
                         tp=price * (1 + self.take_profit_pct))
            elif price < self.dc_lower[-2]:
                self.sell(sl=price * (1 + self.stop_loss_pct),
                          tp=price * (1 - self.take_profit_pct))


# ─────────────────────────────────────────────────────────────────────────────
# 5. MACD_MOMENTUM
# ─────────────────────────────────────────────────────────────────────────────
class MACDMomentum(RBIStrategy):
    """MACD Momentum Strategy.

    Long: línea MACD cruza por encima de la señal + histograma > 0.
    Short: línea MACD cruza por debajo de la señal + histograma < 0.
    """

    strategy_name = "MACD Momentum"
    strategy_type = "Momentum"

    macd_fast   = 12
    macd_slow   = 26
    macd_sig    = 9
    stop_loss_pct  = 0.025
    take_profit_pct = 0.05

    def init(self):
        macd_df = ta.macd(self.close,
                          fast=self.macd_fast,
                          slow=self.macd_slow,
                          signal=self.macd_sig)
        self.macd_line = self.I(lambda: macd_df.iloc[:, 0], name="MACD")
        self.macd_hist = self.I(lambda: macd_df.iloc[:, 1], name="MACD_Hist")
        self.macd_sig_line = self.I(lambda: macd_df.iloc[:, 2], name="MACD_Sig")

    def next(self):
        if len(self.data) < self.macd_slow + self.macd_sig + 2:
            return
        if np.isnan(self.macd_line[-1]) or np.isnan(self.macd_sig_line[-1]):
            return

        price = self.data.Close[-1]

        if not self.position:
            if crossover(self.macd_line, self.macd_sig_line) and self.macd_hist[-1] > 0:
                self.buy(sl=price * (1 - self.stop_loss_pct),
                         tp=price * (1 + self.take_profit_pct))
            elif crossover(self.macd_sig_line, self.macd_line) and self.macd_hist[-1] < 0:
                self.sell(sl=price * (1 + self.stop_loss_pct),
                          tp=price * (1 - self.take_profit_pct))


# ─────────────────────────────────────────────────────────────────────────────
# 6. BB_INSIDE_KELTNER (Squeeze Momentum)
# ─────────────────────────────────────────────────────────────────────────────
class BBInsideKeltner(RBIStrategy):
    """BB Inside Keltner — Squeeze Momentum.

    Squeeze = BB dentro de KC (compresión de volatilidad).
    Cuando el squeeze se libera, entra en la dirección del momentum.
    Idéntico al template de John Carter / LazyBear.
    """

    strategy_name = "BB Inside Keltner (Squeeze)"
    strategy_type = "Volatility"

    bb_length  = 20
    bb_std     = 2.0
    kc_length  = 20
    kc_scalar  = 1.5
    mom_length = 12
    stop_loss_pct  = 0.03
    take_profit_pct = 0.06

    def init(self):
        bb  = ta.bbands(self.close, length=self.bb_length, std=self.bb_std)
        kc  = ta.kc(self.high, self.low, self.close,
                    length=self.kc_length, scalar=self.kc_scalar)
        mom = ta.mom(self.close, length=self.mom_length)

        self.bb_upper = self.I(lambda: bb.iloc[:, 2], name="BB_Upper")
        self.bb_lower = self.I(lambda: bb.iloc[:, 0], name="BB_Lower")
        self.kc_upper = self.I(lambda: kc.iloc[:, 2], name="KC_Upper")
        self.kc_lower = self.I(lambda: kc.iloc[:, 0], name="KC_Lower")
        self.momentum = self.I(lambda: mom,            name="Momentum")

        squeeze = (
            (bb.iloc[:, 0] > kc.iloc[:, 0]) & (bb.iloc[:, 2] < kc.iloc[:, 2])
        ).astype(float)
        self.squeeze = self.I(lambda: squeeze, name="Squeeze")

    def next(self):
        min_bars = max(self.bb_length, self.kc_length) + self.mom_length + 2
        if len(self.data) < min_bars:
            return
        if np.isnan(self.momentum[-1]) or np.isnan(self.squeeze[-1]):
            return

        price = self.data.Close[-1]
        was_squeeze = len(self.squeeze) > 1 and self.squeeze[-2] == 1.0
        no_squeeze  = self.squeeze[-1] == 0.0

        if not self.position and was_squeeze and no_squeeze:
            if self.momentum[-1] > 0:
                self.buy(sl=price * (1 - self.stop_loss_pct),
                         tp=price * (1 + self.take_profit_pct))
            else:
                self.sell(sl=price * (1 + self.stop_loss_pct),
                          tp=price * (1 - self.take_profit_pct))


# ─────────────────────────────────────────────────────────────────────────────
# 7. ATR_EXPANSION
# ─────────────────────────────────────────────────────────────────────────────
class ATRExpansion(RBIStrategy):
    """ATR Expansion Breakout.

    Detecta expansión súbita de volatilidad: ATR actual >> ATR promedio.
    Entra en la dirección de la tendencia definida por una EMA lenta.
    SL/TP calibrados en múltiplos de ATR.
    """

    strategy_name = "ATR Expansion"
    strategy_type = "Volatility"

    atr_period    = 14
    atr_smooth    = 20
    expansion_mult = 1.5   # ATR > mult × ATR promedio → expansión
    ema_trend     = 50
    sl_atr_mult   = 1.5
    tp_atr_mult   = 2.5

    def init(self):
        atr_vals = ta.atr(self.high, self.low, self.close, length=self.atr_period)
        atr_avg  = atr_vals.rolling(window=self.atr_smooth).mean()
        ema      = ta.ema(self.close, length=self.ema_trend)

        self.atr     = self.I(lambda: atr_vals, name="ATR")
        self.atr_avg = self.I(lambda: atr_avg,  name="ATR_Avg")
        self.ema     = self.I(lambda: ema,       name="EMA_Trend")

    def next(self):
        min_bars = self.atr_period + self.atr_smooth + self.ema_trend + 2
        if len(self.data) < min_bars:
            return
        if np.isnan(self.atr[-1]) or np.isnan(self.atr_avg[-1]) or np.isnan(self.ema[-1]):
            return

        price = self.data.Close[-1]
        atr   = self.atr[-1]
        is_expansion = atr > self.expansion_mult * self.atr_avg[-1]

        if not self.position and is_expansion:
            if price > self.ema[-1]:
                self.buy(sl=price - self.sl_atr_mult * atr,
                         tp=price + self.tp_atr_mult * atr)
            else:
                self.sell(sl=price + self.sl_atr_mult * atr,
                          tp=price - self.tp_atr_mult * atr)


# ─────────────────────────────────────────────────────────────────────────────
# 8. FUNDING_RATE_CONTRARIAN
# ─────────────────────────────────────────────────────────────────────────────
class FundingRateContrarian(RBIStrategy):
    """Funding Rate Contrarian (proxy por momentum de precio).

    Lógica: momentum extremo positivo → longs sobreextendidos →
    funding implícito positivo → entrada contrarian corto.
    Momentum extremo negativo → shorts sobreextendidos → entrada contrarian largo.

    Con datos de funding real se puede pasar la columna 'Funding' al DataFrame
    y reemplazar self.momentum por self.data.Funding.
    RSI confirma el extremo antes de entrar.
    """

    strategy_name = "Funding Rate Contrarian"
    strategy_type = "Mean Reversion"

    mom_period       = 20
    mom_threshold    = 5.0    # % de momentum para considerar extremo
    rsi_period       = 14
    rsi_confirm_long  = 35   # RSI bajo → confirmar long contrarian
    rsi_confirm_short = 65   # RSI alto → confirmar short contrarian
    stop_loss_pct    = 0.025
    take_profit_pct  = 0.04

    def init(self):
        close = self.close
        mom   = ((close / close.shift(self.mom_period)) - 1) * 100
        rsi   = ta.rsi(close, length=self.rsi_period)

        self.momentum = self.I(lambda: mom, name="Price_Momentum_Pct")
        self.rsi      = self.I(lambda: rsi, name="RSI")

    def next(self):
        if len(self.data) < self.mom_period + self.rsi_period + 2:
            return
        if np.isnan(self.momentum[-1]) or np.isnan(self.rsi[-1]):
            return

        price = self.data.Close[-1]
        mom   = self.momentum[-1]
        rsi   = self.rsi[-1]

        if not self.position:
            # Extremo alcista → contrarian short
            if mom > self.mom_threshold and rsi > self.rsi_confirm_short:
                self.sell(sl=price * (1 + self.stop_loss_pct),
                          tp=price * (1 - self.take_profit_pct))
            # Extremo bajista → contrarian long
            elif mom < -self.mom_threshold and rsi < self.rsi_confirm_long:
                self.buy(sl=price * (1 - self.stop_loss_pct),
                         tp=price * (1 + self.take_profit_pct))


# ─────────────────────────────────────────────────────────────────────────────
# 9. VOLUME_SPIKE_BREAKOUT
# ─────────────────────────────────────────────────────────────────────────────
class VolumeSpikeBreakout(RBIStrategy):
    """Volume Spike + Price Breakout.

    Señal: volumen actual > N × volumen promedio + precio rompe el rango
    de las últimas range_period barras.
    Volumen institucional confirma el breakout.
    """

    strategy_name = "Volume Spike Breakout"
    strategy_type = "Breakout"

    vol_period   = 20
    vol_mult     = 2.0    # spike threshold
    range_period = 10     # lookback del rango
    stop_loss_pct  = 0.025
    take_profit_pct = 0.05

    def init(self):
        vol      = self.volume
        vol_avg  = vol.rolling(window=self.vol_period).mean()
        rng_high = self.high.rolling(window=self.range_period).max()
        rng_low  = self.low.rolling(window=self.range_period).min()

        self.vol_avg   = self.I(lambda: vol_avg,  name="Vol_Avg")
        self.rng_high  = self.I(lambda: rng_high, name="Range_High")
        self.rng_low   = self.I(lambda: rng_low,  name="Range_Low")

    def next(self):
        if len(self.data) < self.vol_period + self.range_period + 2:
            return
        if np.isnan(self.vol_avg[-1]) or np.isnan(self.rng_high[-2]):
            return

        price     = self.data.Close[-1]
        vol_spike = self.data.Volume[-1] > self.vol_mult * self.vol_avg[-1]

        if not self.position and vol_spike:
            if price > self.rng_high[-2]:   # breakout alcista
                self.buy(sl=price * (1 - self.stop_loss_pct),
                         tp=price * (1 + self.take_profit_pct))
            elif price < self.rng_low[-2]:  # breakout bajista
                self.sell(sl=price * (1 + self.stop_loss_pct),
                          tp=price * (1 - self.take_profit_pct))


# ─────────────────────────────────────────────────────────────────────────────
# 10. RSI_BB_COMBO
# ─────────────────────────────────────────────────────────────────────────────
class RSIBBCombo(RBIStrategy):
    """RSI + Bollinger Bands — Doble Confirmación.

    Long: RSI < rsi_low AND precio < bb_lower (doble sobrevendido).
    Short: RSI > rsi_high AND precio > bb_upper (doble sobrecomprado).
    Salida cuando RSI cruza zona neutral (50).
    """

    strategy_name = "RSI + BB Combo"
    strategy_type = "Mean Reversion"

    rsi_period = 14
    rsi_low    = 30
    rsi_high   = 70
    bb_length  = 20
    bb_std     = 2.0
    stop_loss_pct  = 0.03
    take_profit_pct = 0.06

    def init(self):
        rsi = ta.rsi(self.close, length=self.rsi_period)
        bb  = ta.bbands(self.close, length=self.bb_length, std=self.bb_std)

        self.rsi      = self.I(lambda: rsi,           name="RSI")
        self.bb_lower = self.I(lambda: bb.iloc[:, 0], name="BB_Lower")
        self.bb_upper = self.I(lambda: bb.iloc[:, 2], name="BB_Upper")

    def next(self):
        if len(self.data) < max(self.rsi_period, self.bb_length) + 1:
            return
        if np.isnan(self.rsi[-1]) or np.isnan(self.bb_lower[-1]):
            return

        price = self.data.Close[-1]
        rsi   = self.rsi[-1]

        if not self.position:
            if rsi < self.rsi_low and price < self.bb_lower[-1]:
                self.buy(sl=price * (1 - self.stop_loss_pct),
                         tp=price * (1 + self.take_profit_pct))
            elif rsi > self.rsi_high and price > self.bb_upper[-1]:
                self.sell(sl=price * (1 + self.stop_loss_pct),
                          tp=price * (1 - self.take_profit_pct))
        else:
            if self.position.is_long and rsi > 50:
                self.position.close()
            elif self.position.is_short and rsi < 50:
                self.position.close()


# ─────────────────────────────────────────────────────────────────────────────
# 11. STOCH_MACD_CONFIRM
# ─────────────────────────────────────────────────────────────────────────────
class StochMACDConfirm(RBIStrategy):
    """Stochastic + MACD Confirmation.

    Long:  Stoch-K cruza D desde zona oversold (<stoch_low) + MACD hist > 0.
    Short: Stoch-K cruza D desde zona overbought (>stoch_high) + MACD hist < 0.
    """

    strategy_name = "Stochastic + MACD Confirm"
    strategy_type = "Momentum"

    stoch_k      = 14
    stoch_d      = 3
    stoch_smooth = 3
    stoch_low    = 20
    stoch_high   = 80
    macd_fast    = 12
    macd_slow    = 26
    macd_sig     = 9
    stop_loss_pct  = 0.025
    take_profit_pct = 0.05

    def init(self):
        stoch   = ta.stoch(self.high, self.low, self.close,
                           k=self.stoch_k, d=self.stoch_d,
                           smooth_k=self.stoch_smooth)
        macd_df = ta.macd(self.close,
                          fast=self.macd_fast,
                          slow=self.macd_slow,
                          signal=self.macd_sig)

        self.stoch_k_line = self.I(lambda: stoch.iloc[:, 0],   name="Stoch_K")
        self.stoch_d_line = self.I(lambda: stoch.iloc[:, 1],   name="Stoch_D")
        self.macd_hist    = self.I(lambda: macd_df.iloc[:, 1], name="MACD_Hist")

    def next(self):
        min_bars = self.macd_slow + self.macd_sig + self.stoch_k + 4
        if len(self.data) < min_bars:
            return
        if np.isnan(self.stoch_k_line[-1]) or np.isnan(self.macd_hist[-1]):
            return

        price = self.data.Close[-1]
        k     = self.stoch_k_line[-1]

        was_oversold   = len(self.stoch_k_line) > 1 and self.stoch_k_line[-2] < self.stoch_low
        was_overbought = len(self.stoch_k_line) > 1 and self.stoch_k_line[-2] > self.stoch_high

        if not self.position:
            if (was_oversold and k > self.stoch_low
                    and crossover(self.stoch_k_line, self.stoch_d_line)
                    and self.macd_hist[-1] > 0):
                self.buy(sl=price * (1 - self.stop_loss_pct),
                         tp=price * (1 + self.take_profit_pct))
            elif (was_overbought and k < self.stoch_high
                  and crossover(self.stoch_d_line, self.stoch_k_line)
                  and self.macd_hist[-1] < 0):
                self.sell(sl=price * (1 + self.stop_loss_pct),
                          tp=price * (1 - self.take_profit_pct))


# ─────────────────────────────────────────────────────────────────────────────
# 12. TRIPLE_EMA_FILTER
# ─────────────────────────────────────────────────────────────────────────────
class TripleEMAFilter(RBIStrategy):
    """Triple EMA Filter — Trend + Pullback.

    Condición de tendencia: EMA_fast > EMA_mid > EMA_slow (bull aligned).
    Entrada: precio hace pullback a EMA_mid + RSI confirma salida de debilidad.
    Salida: EMA_fast cruza por debajo de EMA_mid.
    """

    strategy_name = "Triple EMA Filter"
    strategy_type = "Trend Following"

    ema_fast  = 8
    ema_mid   = 21
    ema_slow  = 55
    rsi_period = 10
    rsi_entry  = 45   # RSI mínimo para confirmar impulso tras pullback
    stop_loss_pct  = 0.025
    take_profit_pct = 0.06

    def init(self):
        ema_f = ta.ema(self.close, length=self.ema_fast)
        ema_m = ta.ema(self.close, length=self.ema_mid)
        ema_s = ta.ema(self.close, length=self.ema_slow)
        rsi   = ta.rsi(self.close, length=self.rsi_period)

        self.ema_f = self.I(lambda: ema_f, name="EMA_Fast")
        self.ema_m = self.I(lambda: ema_m, name="EMA_Mid")
        self.ema_s = self.I(lambda: ema_s, name="EMA_Slow")
        self.rsi   = self.I(lambda: rsi,   name="RSI")

    def next(self):
        if len(self.data) < self.ema_slow + self.rsi_period + 2:
            return
        if np.isnan(self.ema_s[-1]) or np.isnan(self.rsi[-1]):
            return

        price = self.data.Close[-1]
        ef, em, es = self.ema_f[-1], self.ema_m[-1], self.ema_s[-1]
        rsi = self.rsi[-1]

        bull_aligned = ef > em > es
        bear_aligned = ef < em < es

        if not self.position:
            if bull_aligned and price <= em * 1.002 and rsi > self.rsi_entry:
                self.buy(sl=price * (1 - self.stop_loss_pct),
                         tp=price * (1 + self.take_profit_pct))
            elif bear_aligned and price >= em * 0.998 and rsi < (100 - self.rsi_entry):
                self.sell(sl=price * (1 + self.stop_loss_pct),
                          tp=price * (1 - self.take_profit_pct))
        else:
            if self.position.is_long and ef < em:
                self.position.close()
            elif self.position.is_short and ef > em:
                self.position.close()


# ─────────────────────────────────────────────────────────────────────────────
# 13. ATR_SIZED_ENTRY
# ─────────────────────────────────────────────────────────────────────────────
class ATRSizedEntry(RBIStrategy):
    """ATR-Sized Entry — Van Tharp / R-múltiplo style.

    SL = precio ± sl_atr_mult × ATR.
    TP = precio ± tp_atr_mult × ATR (ratio riesgo/recompensa fijo).
    Señal: EMA crossover con ADX mínimo para evitar entrar en rangos.
    """

    strategy_name = "ATR Sized Entry"
    strategy_type = "Trend Following"

    ema_fast    = 9
    ema_slow    = 21
    atr_period  = 14
    adx_period  = 14
    adx_min     = 20
    sl_atr_mult = 1.5
    tp_atr_mult = 3.0

    def init(self):
        ema_f  = ta.ema(self.close, length=self.ema_fast)
        ema_s  = ta.ema(self.close, length=self.ema_slow)
        atr    = ta.atr(self.high, self.low, self.close, length=self.atr_period)
        adx_df = ta.adx(self.high, self.low, self.close, length=self.adx_period)

        self.ema_f = self.I(lambda: ema_f,             name="EMA_Fast")
        self.ema_s = self.I(lambda: ema_s,             name="EMA_Slow")
        self.atr   = self.I(lambda: atr,               name="ATR")
        self.adx   = self.I(lambda: adx_df.iloc[:, 0], name="ADX")

    def next(self):
        if len(self.data) < self.ema_slow + self.adx_period + 2:
            return
        if np.isnan(self.atr[-1]) or np.isnan(self.adx[-1]):
            return

        price = self.data.Close[-1]
        atr   = self.atr[-1]

        if not self.position and self.adx[-1] > self.adx_min:
            if crossover(self.ema_f, self.ema_s):
                self.buy(sl=price - self.sl_atr_mult * atr,
                         tp=price + self.tp_atr_mult * atr)
            elif crossover(self.ema_s, self.ema_f):
                self.sell(sl=price + self.sl_atr_mult * atr,
                          tp=price - self.tp_atr_mult * atr)


# ─────────────────────────────────────────────────────────────────────────────
# 14. REGIME_SWITCH
# ─────────────────────────────────────────────────────────────────────────────
class RegimeSwitch(RBIStrategy):
    """Regime Switch — Adaptive Trend/Mean-Reversion.

    ADX > threshold → mercado en tendencia → EMA crossover (trend-following).
    ADX < threshold → mercado en rango    → RSI extremos (mean-reversion).
    Permite adaptar la estrategia al régimen de mercado sin datos externos.
    """

    strategy_name = "Regime Switch"
    strategy_type = "Adaptive"

    adx_period    = 14
    adx_threshold = 25.0
    ema_fast      = 9
    ema_slow      = 21
    rsi_period    = 14
    rsi_low       = 30
    rsi_high      = 70
    stop_loss_pct  = 0.03
    take_profit_pct = 0.05

    def init(self):
        ema_f  = ta.ema(self.close, length=self.ema_fast)
        ema_s  = ta.ema(self.close, length=self.ema_slow)
        adx_df = ta.adx(self.high, self.low, self.close, length=self.adx_period)
        rsi    = ta.rsi(self.close, length=self.rsi_period)

        self.ema_f = self.I(lambda: ema_f,             name="EMA_Fast")
        self.ema_s = self.I(lambda: ema_s,             name="EMA_Slow")
        self.adx   = self.I(lambda: adx_df.iloc[:, 0], name="ADX")
        self.rsi   = self.I(lambda: rsi,               name="RSI")

    def next(self):
        min_bars = max(self.ema_slow, self.adx_period, self.rsi_period) + 2
        if len(self.data) < min_bars:
            return
        if np.isnan(self.adx[-1]) or np.isnan(self.rsi[-1]):
            return

        price    = self.data.Close[-1]
        trending = self.adx[-1] > self.adx_threshold

        if not self.position:
            if trending:
                if crossover(self.ema_f, self.ema_s):
                    self.buy(sl=price * (1 - self.stop_loss_pct),
                             tp=price * (1 + self.take_profit_pct))
                elif crossover(self.ema_s, self.ema_f):
                    self.sell(sl=price * (1 + self.stop_loss_pct),
                              tp=price * (1 - self.take_profit_pct))
            else:
                if self.rsi[-1] < self.rsi_low:
                    self.buy(sl=price * (1 - self.stop_loss_pct),
                             tp=price * (1 + self.take_profit_pct))
                elif self.rsi[-1] > self.rsi_high:
                    self.sell(sl=price * (1 + self.stop_loss_pct),
                              tp=price * (1 - self.take_profit_pct))


# ─────────────────────────────────────────────────────────────────────────────
# 15. TIME_OF_DAY
# ─────────────────────────────────────────────────────────────────────────────
class TimeOfDay(RBIStrategy):
    """Time of Day Filter — solo opera en la sesión definida (UTC).

    Señal base: EMA crossover con confirmación RSI.
    Cierra posiciones abiertas al salir de la ventana horaria.
    Útil para crypto (sesiones Asia/Europa/USA) o Forex.
    """

    strategy_name = "Time of Day"
    strategy_type = "Intraday"

    hour_open   = 8    # hora UTC de inicio de sesión
    hour_close  = 16   # hora UTC de fin (no entrar nuevas posiciones)
    ema_fast    = 9
    ema_slow    = 21
    rsi_period  = 14
    rsi_confirm = 50
    stop_loss_pct  = 0.02
    take_profit_pct = 0.04

    def init(self):
        ema_f = ta.ema(self.close, length=self.ema_fast)
        ema_s = ta.ema(self.close, length=self.ema_slow)
        rsi   = ta.rsi(self.close, length=self.rsi_period)

        self.ema_f = self.I(lambda: ema_f, name="EMA_Fast")
        self.ema_s = self.I(lambda: ema_s, name="EMA_Slow")
        self.rsi   = self.I(lambda: rsi,   name="RSI")

    def _current_hour(self) -> int:
        """Hora UTC de la barra actual. Devuelve 12 si no hay DatetimeIndex."""
        try:
            return self.data.index[-1].hour
        except (AttributeError, TypeError):
            return 12

    def next(self):
        if len(self.data) < self.ema_slow + self.rsi_period + 2:
            return
        if np.isnan(self.ema_f[-1]) or np.isnan(self.rsi[-1]):
            return

        price      = self.data.Close[-1]
        hour       = self._current_hour()
        in_session = self.hour_open <= hour < self.hour_close

        # Cierre forzado al salir de sesión
        if self.position and not in_session:
            self.position.close()
            return

        if not self.position and in_session:
            if crossover(self.ema_f, self.ema_s) and self.rsi[-1] > self.rsi_confirm:
                self.buy(sl=price * (1 - self.stop_loss_pct),
                         tp=price * (1 + self.take_profit_pct))
            elif crossover(self.ema_s, self.ema_f) and self.rsi[-1] < self.rsi_confirm:
                self.sell(sl=price * (1 + self.stop_loss_pct),
                          tp=price * (1 - self.take_profit_pct))


# ─────────────────────────────────────────────────────────────────────────────
# 16. STOCH_RSI_STRATEGY
# ─────────────────────────────────────────────────────────────────────────────
class StochRSIStrategy(RBIStrategy):
    """StochRSI Crossover Strategy.

    Aplica el oscilador Estocástico sobre el RSI para señales de reversión.
    Long:  StochRSI_K cruza por encima de StochRSI_D desde zona oversold (<20).
    Short: StochRSI_K cruza por debajo de StochRSI_D desde zona overbought (>80).
    """

    strategy_name = "StochRSI Crossover"
    strategy_type = "Momentum"

    rsi_length   = 14
    stoch_length = 14
    k_smooth     = 3
    d_smooth     = 3
    oversold     = 20
    overbought   = 80
    stop_loss_pct   = 0.025
    take_profit_pct = 0.05

    def init(self):
        srsi = ta.stochrsi(
            self.close,
            length=self.stoch_length,
            rsi_length=self.rsi_length,
            k=self.k_smooth,
            d=self.d_smooth,
        )
        self.k = self.I(lambda: srsi.iloc[:, 0], name="StochRSI_K")
        self.d = self.I(lambda: srsi.iloc[:, 1], name="StochRSI_D")

    def next(self):
        min_bars = self.rsi_length + self.stoch_length + self.k_smooth + 5
        if len(self.data) < min_bars:
            return
        if np.isnan(self.k[-1]) or np.isnan(self.d[-1]):
            return

        price = self.data.Close[-1]

        if not self.position:
            if self.k[-1] < self.oversold and crossover(self.k, self.d):
                self.buy(sl=price * (1 - self.stop_loss_pct),
                         tp=price * (1 + self.take_profit_pct))
            elif self.k[-1] > self.overbought and crossover(self.d, self.k):
                self.sell(sl=price * (1 + self.stop_loss_pct),
                          tp=price * (1 - self.take_profit_pct))


# ─────────────────────────────────────────────────────────────────────────────
# 17. MFI_STRATEGY
# ─────────────────────────────────────────────────────────────────────────────
class MFIStrategy(RBIStrategy):
    """Money Flow Index Momentum.

    El MFI combina precio y volumen para detectar flujo de dinero.
    Long:  MFI < oversold (dinero fluyendo hacia activo desde zona de pánico).
    Short: MFI > overbought (distribución desde zona de euforia).
    Salida: MFI vuelve a zona neutral o por SL/TP.
    """

    strategy_name = "MFI Momentum"
    strategy_type = "Volume Momentum"

    mfi_length   = 14
    oversold     = 20
    overbought   = 80
    neutral_lo   = 40
    neutral_hi   = 60
    stop_loss_pct   = 0.03
    take_profit_pct = 0.06

    def init(self):
        mfi = ta.mfi(self.high, self.low, self.close, self.volume,
                     length=self.mfi_length)
        self.mfi = self.I(lambda: mfi, name="MFI")

    def next(self):
        if len(self.data) < self.mfi_length + 2:
            return
        if np.isnan(self.mfi[-1]):
            return

        price = self.data.Close[-1]
        mfi   = self.mfi[-1]

        if not self.position:
            if mfi < self.oversold:
                self.buy(sl=price * (1 - self.stop_loss_pct),
                         tp=price * (1 + self.take_profit_pct))
            elif mfi > self.overbought:
                self.sell(sl=price * (1 + self.stop_loss_pct),
                          tp=price * (1 - self.take_profit_pct))
        else:
            if self.position.is_long and mfi > self.neutral_hi:
                self.position.close()
            elif self.position.is_short and mfi < self.neutral_lo:
                self.position.close()


# ─────────────────────────────────────────────────────────────────────────────
# 18. MARKET_CIPHER_B
# ─────────────────────────────────────────────────────────────────────────────
class MarketCipherB(RBIStrategy):
    """Market Cipher B — WaveTrend + MFI + VWAP + StochRSI.

    Combina 4 indicadores para señales de alta confluencia:
    - WaveTrend (WT1): oscilador basado en EMA de HLC3 normalizado
    - MFI: flujo de dinero para confirmar presión compradora/vendedora
    - VWAP: precio relativo a valor justo del día
    - StochRSI: momentum de corto plazo para timing de entrada

    Long:  WT1 < wt_oversold  + MFI < mfi_oversold  + precio<VWAP + StochRSI K cruza D arriba
    Short: WT1 > wt_overbought + MFI > mfi_overbought + precio>VWAP + StochRSI K cruza D abajo
    """

    strategy_name = "Market Cipher B"
    strategy_type = "Multi-Signal"

    wt_channel    = 10
    wt_average    = 21
    mfi_length    = 14
    rsi_length    = 14
    stoch_length  = 14
    wt_oversold   = -60
    wt_overbought = 60
    mfi_oversold  = 30
    mfi_overbought = 70
    stop_loss_pct   = 0.03
    take_profit_pct = 0.07

    def init(self):
        # WaveTrend: EMA del HLC3 normalizado
        hlc3  = (self.high + self.low + self.close) / 3
        esa   = ta.ema(hlc3, length=self.wt_channel)
        d_abs = ta.ema(abs(hlc3 - esa), length=self.wt_channel)
        # Evitar división por cero con epsilon
        ci    = (hlc3 - esa) / (0.015 * d_abs + 1e-10)
        wt1   = ta.ema(ci, length=self.wt_average)
        wt2   = ta.sma(wt1, length=4)

        # MFI
        mfi  = ta.mfi(self.high, self.low, self.close, self.volume,
                      length=self.mfi_length)

        # VWAP rolling (ta.vwap requiere DatetimeIndex; usamos rolling manual)
        typ_price = (self.high + self.low + self.close) / 3
        vol = pd.Series(self.volume)
        tp_vol = pd.Series(typ_price) * vol
        vwap = tp_vol.rolling(48).sum() / vol.rolling(48).sum()
        vwap = vwap.replace([np.inf, -np.inf], np.nan)

        # StochRSI
        srsi = ta.stochrsi(
            self.close,
            length=self.stoch_length,
            rsi_length=self.rsi_length,
            k=3,
            d=3,
        )

        self.wt1    = self.I(lambda: wt1,             name="WT1")
        self.wt2    = self.I(lambda: wt2,             name="WT2")
        self.mfi    = self.I(lambda: mfi,             name="MFI")
        self.vwap   = self.I(lambda: vwap,            name="VWAP")
        self.srsi_k = self.I(lambda: srsi.iloc[:, 0], name="StochRSI_K")
        self.srsi_d = self.I(lambda: srsi.iloc[:, 1], name="StochRSI_D")

    def next(self):
        min_bars = self.wt_average + self.wt_channel + self.stoch_length + 10
        if len(self.data) < min_bars:
            return
        for sig in (self.wt1, self.mfi, self.vwap, self.srsi_k, self.srsi_d):
            if np.isnan(sig[-1]):
                return

        price = self.data.Close[-1]
        wt1   = self.wt1[-1]
        mfi   = self.mfi[-1]
        vwap  = self.vwap[-1]

        if not self.position:
            bull = (
                wt1 < self.wt_oversold
                and mfi < self.mfi_oversold
                and price < vwap
                and crossover(self.srsi_k, self.srsi_d)
            )
            bear = (
                wt1 > self.wt_overbought
                and mfi > self.mfi_overbought
                and price > vwap
                and crossover(self.srsi_d, self.srsi_k)
            )
            if bull:
                self.buy(sl=price * (1 - self.stop_loss_pct),
                         tp=price * (1 + self.take_profit_pct))
            elif bear:
                self.sell(sl=price * (1 + self.stop_loss_pct),
                          tp=price * (1 - self.take_profit_pct))


# ─────────────────────────────────────────────────────────────────────────────
# Registry map
# ─────────────────────────────────────────────────────────────────────────────
from btquantr.engine.templates.equity_templates import EQUITY_TEMPLATE_REGISTRY  # noqa: E402
from btquantr.engine.templates.forex_templates import FOREX_TEMPLATE_REGISTRY  # noqa: E402

TEMPLATE_REGISTRY: dict[str, type[RBIStrategy]] = {
    "bb-mean-reversion":        BBMeanReversion,
    "keltner-mean-reversion":   KeltnerMeanReversion,
    "ema-crossover-adx":        EMACrossoverADX,
    "donchian-breakout":        DonchianBreakout,
    "macd-momentum":            MACDMomentum,
    "bb-inside-keltner":        BBInsideKeltner,
    "atr-expansion":            ATRExpansion,
    "funding-rate-contrarian":  FundingRateContrarian,
    "volume-spike-breakout":    VolumeSpikeBreakout,
    "rsi-bb-combo":             RSIBBCombo,
    "stoch-macd-confirm":       StochMACDConfirm,
    "triple-ema-filter":        TripleEMAFilter,
    "atr-sized-entry":          ATRSizedEntry,
    "regime-switch":            RegimeSwitch,
    "time-of-day":              TimeOfDay,
    # Templates 16-18
    "stoch-rsi":                StochRSIStrategy,
    "mfi-momentum":             MFIStrategy,
    "market-cipher-b":          MarketCipherB,
    # Equity templates (19-21)
    **EQUITY_TEMPLATE_REGISTRY,
    # Forex templates (22-25) — ATR-based, sin volumen, calibrados para pips
    **FOREX_TEMPLATE_REGISTRY,
}
