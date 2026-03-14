"""
btquantr/engine/templates/funding_strategies.py — 5 estrategias Funding Rate.

Todas usan backtesting.py directamente (hereda de Strategy).
Requieren columnas pre-computadas en el DataFrame:
  - Funding       : float  — funding rate annualizado en % (ej. 75.0 = 75%)
  - OI            : float  — open interest en USD (para FundingOIDivergence)
  - FundingSpread : float  — HL funding - Binance funding en % (FundingCrossExchange)

Si la columna no está presente, la estrategia corre sin generar trades (no-op seguro).

Estrategias:
  1. FundingRateArbitrage   — delta-neutral: SHORT > threshold, LONG < -threshold
  2. FundingMeanReversion   — contra el crowd: SELL > trigger, BUY < -trigger
  3. FundingOIDivergence    — capitulación / euforia combinando funding + OI
  4. FundingCrossExchange   — spread HL vs Binance; actúa cuando spread > umbral
  5. HIP3FundingExploit     — igual que FundingMeanReversion, threshold 75% (más agresivo)

Todos los parámetros de clase son mutables por GeneticMutator del EvolutionLoop.
SeedLibrary los detecta automáticamente vía AST (hereda de Strategy).
"""
from __future__ import annotations

import numpy as np
from backtesting import Strategy


# ─────────────────────────────────────────────────────────────────────────────
# 1. FundingRateArbitrage
# ─────────────────────────────────────────────────────────────────────────────

class FundingRateArbitrage(Strategy):
    """Delta-neutral funding rate arbitrage en perpetuos.

    Lógica:
      - funding_annualized > threshold_pct  → SHORT perp (longs pagando)
      - funding_annualized < -threshold_pct → LONG perp (shorts pagando)
      - Cierre por SL/TP o cuando hold_bars se agota

    Requiere columna Funding en el DataFrame (% annualizado).
    Sin columna → 0 trades.

    Parámetros mutables para EvolutionLoop:
      threshold_pct   — umbral para activar posición
      hold_bars       — máximo de barras abierto
      stop_loss_pct   — stop loss como fracción del precio
      take_profit_pct — take profit como fracción del precio
    """

    strategy_name  = "Funding Rate Arbitrage"
    strategy_type  = "Funding Arbitrage"

    threshold_pct   = 50.0
    hold_bars       = 10
    stop_loss_pct   = 0.03
    take_profit_pct = 0.06

    def init(self):
        if "Funding" in self.data.df.columns:
            funding_arr = self.data.df["Funding"].values.copy()
            self.funding = self.I(lambda: funding_arr, name="Funding")
            self._has_funding = True
        else:
            self.funding = None
            self._has_funding = False
        self._bars_held = 0

    def next(self):
        if not self._has_funding:
            return
        f = self.funding[-1]
        if np.isnan(f):
            return

        price = self.data.Close[-1]

        if self.position:
            self._bars_held += 1
            if self._bars_held >= self.hold_bars:
                self.position.close()
                self._bars_held = 0
            return

        self._bars_held = 0
        if f > self.threshold_pct:
            self.sell(
                sl=price * (1 + self.stop_loss_pct),
                tp=price * (1 - self.take_profit_pct),
            )
        elif f < -self.threshold_pct:
            self.buy(
                sl=price * (1 - self.stop_loss_pct),
                tp=price * (1 + self.take_profit_pct),
            )


# ─────────────────────────────────────────────────────────────────────────────
# 2. FundingMeanReversion
# ─────────────────────────────────────────────────────────────────────────────

class FundingMeanReversion(Strategy):
    """Contra el crowd: opera cuando el funding alcanza extremos irracionales.

    Lógica:
      - funding > trigger_pct  (100%) → SELL (mercado sobrecalentado long)
      - funding < -trigger_pct (100%) → BUY  (pánico de shorts)
      - Cierre cuando |funding| cae por debajo de exit_pct (25%)
        ó cuando se agota hold_bars

    Parámetros mutables para EvolutionLoop:
      trigger_pct     — umbral de entrada (extreme)
      exit_pct        — umbral de salida (funding vuelve a la normalidad)
      hold_bars       — timeout máximo de la posición
      stop_loss_pct
      take_profit_pct
    """

    strategy_name  = "Funding Mean Reversion"
    strategy_type  = "Funding Mean Reversion"

    trigger_pct     = 100.0
    exit_pct        = 25.0
    hold_bars       = 24
    stop_loss_pct   = 0.04
    take_profit_pct = 0.08

    def init(self):
        if "Funding" in self.data.df.columns:
            funding_arr = self.data.df["Funding"].values.copy()
            self.funding = self.I(lambda: funding_arr, name="Funding")
            self._has_funding = True
        else:
            self.funding = None
            self._has_funding = False
        self._bars_held = 0

    def next(self):
        if not self._has_funding:
            return
        f = self.funding[-1]
        if np.isnan(f):
            return

        price = self.data.Close[-1]

        if self.position:
            self._bars_held += 1
            # Salida temprana: funding vuelve a zona normal
            if abs(f) < self.exit_pct:
                self.position.close()
                self._bars_held = 0
                return
            # Timeout
            if self._bars_held >= self.hold_bars:
                self.position.close()
                self._bars_held = 0
            return

        self._bars_held = 0
        if f > self.trigger_pct:
            self.sell(
                sl=price * (1 + self.stop_loss_pct),
                tp=price * (1 - self.take_profit_pct),
            )
        elif f < -self.trigger_pct:
            self.buy(
                sl=price * (1 - self.stop_loss_pct),
                tp=price * (1 + self.take_profit_pct),
            )


# ─────────────────────────────────────────────────────────────────────────────
# 3. FundingOIDivergence
# ─────────────────────────────────────────────────────────────────────────────

class FundingOIDivergence(Strategy):
    """Señal basada en la divergencia entre Funding Rate y Open Interest.

    Capitulación (BUY):  funding baja drásticamente + OI baja drásticamente
    Euforia     (SELL):  funding sube agresivamente + OI sube agresivamente

    Requiere columnas Funding (% annualized) y OI (USD) en el DataFrame.
    Sin ambas columnas → 0 trades.

    Parámetros mutables:
      window               — ventana de barras para medir el cambio
      funding_drop_threshold — caída mínima de funding (%) para señal capitulación
      oi_drop_threshold    — caída mínima de OI (fracción) para señal capitulación
      hold_bars
      stop_loss_pct
      take_profit_pct
    """

    strategy_name  = "Funding OI Divergence"
    strategy_type  = "Funding Divergence"

    window                = 20
    funding_drop_threshold = 10.0   # funding debe caer ≥ 10 pp en la ventana
    oi_drop_threshold      = 0.05   # OI debe caer ≥ 5% en la ventana
    hold_bars              = 16
    stop_loss_pct          = 0.04
    take_profit_pct        = 0.08

    def init(self):
        has_funding = "Funding" in self.data.df.columns
        has_oi      = "OI"      in self.data.df.columns
        if has_funding and has_oi:
            funding_arr = self.data.df["Funding"].values.copy()
            oi_arr      = self.data.df["OI"].values.copy()
            n = len(funding_arr)
            w = self.window

            # Delta de Funding en la ventana (en pp)
            fdelta = np.zeros(n)
            for i in range(w, n):
                fdelta[i] = funding_arr[i] - funding_arr[i - w]

            # Delta relativo de OI en la ventana (fracción)
            oi_delta_rel = np.zeros(n)
            for i in range(w, n):
                base = oi_arr[i - w]
                if base != 0:
                    oi_delta_rel[i] = (oi_arr[i] - base) / abs(base)

            self.funding      = self.I(lambda: funding_arr,   name="Funding")
            self.fdelta       = self.I(lambda: fdelta,         name="FundingDelta")
            self.oi_delta_rel = self.I(lambda: oi_delta_rel,  name="OI_DeltaRel")
            self._has_data    = True
        else:
            self.funding      = None
            self.fdelta       = None
            self.oi_delta_rel = None
            self._has_data    = False

        self._bars_held = 0

    def next(self):
        if not self._has_data:
            return

        fd  = self.fdelta[-1]
        oid = self.oi_delta_rel[-1]
        if np.isnan(fd) or np.isnan(oid):
            return

        price = self.data.Close[-1]

        if self.position:
            self._bars_held += 1
            if self._bars_held >= self.hold_bars:
                self.position.close()
                self._bars_held = 0
            return

        self._bars_held = 0

        # Capitulación: funding cae + OI cae → BUY (los shorts van a cubrir)
        if fd <= -self.funding_drop_threshold and oid <= -self.oi_drop_threshold:
            self.buy(
                sl=price * (1 - self.stop_loss_pct),
                tp=price * (1 + self.take_profit_pct),
            )
        # Euforia: funding sube + OI sube → SELL (la música va a parar)
        elif fd >= self.funding_drop_threshold and oid >= self.oi_drop_threshold:
            self.sell(
                sl=price * (1 + self.stop_loss_pct),
                tp=price * (1 - self.take_profit_pct),
            )


# ─────────────────────────────────────────────────────────────────────────────
# 4. FundingCrossExchange
# ─────────────────────────────────────────────────────────────────────────────

class FundingCrossExchange(Strategy):
    """Arbitraje de spread de funding entre exchanges (HL vs Binance/Bybit).

    Usa la columna FundingSpread = HL_funding - Binance_funding (en %).
    Pre-computar con get_funding_divergence() de HyperLiquidSource.

    Lógica:
      - spread > spread_threshold_pct  → SELL (HL más caro que Binance)
      - spread < -spread_threshold_pct → BUY  (HL más barato que Binance)

    El threshold default es 0.01% (1 bps de spread = señal de arbitraje).
    Nota: predictedFundings endpoint de HL puede afinar la señal.

    Parámetros mutables:
      spread_threshold_pct — umbral de spread en % (raw rate, no annualized)
      hold_bars
      stop_loss_pct
      take_profit_pct
    """

    strategy_name  = "Funding Cross Exchange"
    strategy_type  = "Funding Arbitrage"

    spread_threshold_pct = 0.01
    hold_bars            = 8
    stop_loss_pct        = 0.02
    take_profit_pct      = 0.04

    def init(self):
        if "FundingSpread" in self.data.df.columns:
            spread_arr = self.data.df["FundingSpread"].values.copy()
            self.spread = self.I(lambda: spread_arr, name="FundingSpread")
            self._has_spread = True
        else:
            self.spread = None
            self._has_spread = False
        self._bars_held = 0

    def next(self):
        if not self._has_spread:
            return
        sp = self.spread[-1]
        if np.isnan(sp):
            return

        price = self.data.Close[-1]

        if self.position:
            self._bars_held += 1
            if self._bars_held >= self.hold_bars:
                self.position.close()
                self._bars_held = 0
            return

        self._bars_held = 0
        if sp > self.spread_threshold_pct:
            # HL funding > Binance → longs más caros en HL → SHORT en HL
            self.sell(
                sl=price * (1 + self.stop_loss_pct),
                tp=price * (1 - self.take_profit_pct),
            )
        elif sp < -self.spread_threshold_pct:
            # HL funding < Binance → shorts más caros en HL → LONG en HL
            self.buy(
                sl=price * (1 - self.stop_loss_pct),
                tp=price * (1 + self.take_profit_pct),
            )


# ─────────────────────────────────────────────────────────────────────────────
# 5. HIP3FundingExploit
# ─────────────────────────────────────────────────────────────────────────────

class HIP3FundingExploit(Strategy):
    """Funding mean-reversion optimizada para activos HIP3 (xyz:GOLD, xyz:CL, xyz:NVDA).

    HIP3 tiene menor liquidez que crypto perps, lo que amplifica los extremos
    de funding rate. Por eso se usan thresholds más agresivos (75% en vez de 100%).

    Lógica idéntica a FundingMeanReversion:
      - funding > trigger_pct (75%) → SELL
      - funding < -trigger_pct      → BUY
      - Cierre cuando |funding| < exit_pct ó se agota hold_bars

    Parámetros mutables:
      trigger_pct — umbral de entrada (default 75, más agresivo que FundingMeanReversion)
      exit_pct    — umbral de salida
      hold_bars
      stop_loss_pct
      take_profit_pct
    """

    strategy_name  = "HIP3 Funding Exploit"
    strategy_type  = "Funding Mean Reversion"

    trigger_pct     = 75.0
    exit_pct        = 20.0
    hold_bars       = 24
    stop_loss_pct   = 0.05
    take_profit_pct = 0.10

    def init(self):
        if "Funding" in self.data.df.columns:
            funding_arr = self.data.df["Funding"].values.copy()
            self.funding = self.I(lambda: funding_arr, name="Funding")
            self._has_funding = True
        else:
            self.funding = None
            self._has_funding = False
        self._bars_held = 0

    def next(self):
        if not self._has_funding:
            return
        f = self.funding[-1]
        if np.isnan(f):
            return

        price = self.data.Close[-1]

        if self.position:
            self._bars_held += 1
            if abs(f) < self.exit_pct:
                self.position.close()
                self._bars_held = 0
                return
            if self._bars_held >= self.hold_bars:
                self.position.close()
                self._bars_held = 0
            return

        self._bars_held = 0
        if f > self.trigger_pct:
            self.sell(
                sl=price * (1 + self.stop_loss_pct),
                tp=price * (1 - self.take_profit_pct),
            )
        elif f < -self.trigger_pct:
            self.buy(
                sl=price * (1 - self.stop_loss_pct),
                tp=price * (1 + self.take_profit_pct),
            )
