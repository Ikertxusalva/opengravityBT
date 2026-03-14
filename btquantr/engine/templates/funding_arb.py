"""FundingRateArbitrage — Template backtesting.py para arbitraje de funding rate.

Lógica:
  - funding_annualized > threshold_pct  → SHORT perp (longs pagando, capturar funding)
  - funding_annualized < -threshold_pct → LONG perp (shorts pagando, capturar funding)
  - |funding_annualized| > extreme_threshold_pct → señal contraria (reversion)
    - funding > extreme → SELL (mercado overstretched long)
    - funding < -extreme → BUY (mercado overstretched short)

La cobertura spot se gestiona fuera del backtest.

Si el DataFrame tiene columna 'Funding' (annualized %), se usa directamente.
Si no, la estrategia no genera señales (HOLD implícito).

FundingSignalGenerator: señal en tiempo real vía FundingScanner.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from rbi.strategies.base import RBIStrategy

from btquantr.data.funding_scanner import FundingScanner


# ─────────────────────────────────────────────────────────────────────────────
# FundingRateArbitrage — Template backtesting.py
# ─────────────────────────────────────────────────────────────────────────────

class FundingRateArbitrage(RBIStrategy):
    """Arbitraje de funding rate en perpetuos (HyperLiquid / Binance perps).

    Abre SHORT cuando funding annualized > threshold_pct (longs pagando).
    Abre LONG cuando funding annualized < -threshold_pct (shorts pagando).
    Señal contrarian cuando |funding| > extreme_threshold_pct.
    """

    strategy_name  = "Funding Rate Arbitrage"
    strategy_type  = "Funding Arbitrage"

    # ── Parámetros mutables (EvolutionLoop + GeneticMutator) ──────────────────
    threshold_pct           = 50.0   # % annualized para activar posición
    extreme_threshold_pct   = 100.0  # % annualized para señal contrarian
    hold_bars               = 10     # max velas para mantener posición
    stop_loss_pct           = 0.03   # 3% SL
    take_profit_pct         = 0.06   # 6% TP

    def init(self):
        # Si hay columna Funding en el DataFrame, la exponemos como indicador
        if "Funding" in self.data.df.columns:
            self.funding = self.I(
                lambda: self.data.df["Funding"].values, name="Funding_Ann"
            )
            self._has_funding = True
        else:
            self.funding = None
            self._has_funding = False

        self._bars_in_position = 0

    def next(self):
        if not self._has_funding:
            return  # Sin datos de funding, sin señal

        funding = self.funding[-1]
        if np.isnan(funding):
            return

        price = self.data.Close[-1]

        # ── Gestión de posición abierta ───────────────────────────────────────
        if self.position:
            self._bars_in_position += 1
            if self._bars_in_position >= self.hold_bars:
                self.position.close()
                self._bars_in_position = 0
            return

        # ── Apertura de posición nueva ────────────────────────────────────────
        self._bars_in_position = 0

        if funding > self.threshold_pct:
            # Longs pagando → SHORT perp (señal SELL)
            self.sell(
                sl=price * (1 + self.stop_loss_pct),
                tp=price * (1 - self.take_profit_pct),
            )
        elif funding < -self.threshold_pct:
            # Shorts pagando → LONG perp (señal BUY)
            self.buy(
                sl=price * (1 - self.stop_loss_pct),
                tp=price * (1 + self.take_profit_pct),
            )


# ─────────────────────────────────────────────────────────────────────────────
# FundingSignalGenerator — Señal en tiempo real vía FundingScanner
# ─────────────────────────────────────────────────────────────────────────────

class FundingSignalGenerator:
    """Genera señal de trading basada en funding rate actual de HyperLiquid.

    Usa FundingScanner para obtener datos en tiempo real sin API key.

    Args:
        threshold_pct:         % annualized para activar BUY/SELL (default 50).
        extreme_threshold_pct: % annualized para señal contrarian (default 100).
        scanner:               FundingScanner a inyectar (para tests). Si None, crea uno.
    """

    def __init__(
        self,
        threshold_pct: float = 50.0,
        extreme_threshold_pct: float = 100.0,
        scanner: FundingScanner | None = None,
    ) -> None:
        self.threshold_pct = threshold_pct
        self.extreme_threshold_pct = extreme_threshold_pct
        self._scanner = scanner if scanner is not None else FundingScanner()

    def get_signal(self, symbol: str) -> dict:
        """Consulta el funding rate actual y devuelve la señal de trading.

        Args:
            symbol: Símbolo del perpetuo (ej. "BTCUSDT", "ETHUSDT").

        Returns:
            {
                "action":             "BUY" | "SELL" | "HOLD",
                "funding_annualized": float   — % annualized actual,
                "reason":             str     — explicación de la señal,
            }
        """
        rows = self._scanner.fetch_crypto_funding()
        if not rows:
            return self._hold(0.0, "Sin datos de funding disponibles")

        # Buscar símbolo (sin distinción de mayúsculas)
        sym_upper = symbol.upper()
        match = next(
            (r for r in rows if r.get("symbol", "").upper() == sym_upper),
            None,
        )
        if match is None:
            return self._hold(0.0, f"{symbol} no encontrado en datos de funding")

        funding = float(match.get("annualized_pct", 0.0))

        if funding > self.extreme_threshold_pct:
            return {
                "action":             "SELL",
                "funding_annualized": funding,
                "reason":             (
                    f"Funding positivo extremo {funding:.1f}% > {self.extreme_threshold_pct}% "
                    f"— señal contrarian SELL (mercado overstretched long)"
                ),
            }
        if funding < -self.extreme_threshold_pct:
            return {
                "action":             "BUY",
                "funding_annualized": funding,
                "reason":             (
                    f"Funding negativo extremo {funding:.1f}% < -{self.extreme_threshold_pct}% "
                    f"— señal contrarian BUY (mercado overstretched short)"
                ),
            }
        if funding > self.threshold_pct:
            return {
                "action":             "SELL",
                "funding_annualized": funding,
                "reason":             (
                    f"Funding positivo {funding:.1f}% > {self.threshold_pct}% "
                    f"— SHORT perp (longs pagando funding)"
                ),
            }
        if funding < -self.threshold_pct:
            return {
                "action":             "BUY",
                "funding_annualized": funding,
                "reason":             (
                    f"Funding negativo {funding:.1f}% < -{self.threshold_pct}% "
                    f"— LONG perp (shorts pagando funding)"
                ),
            }
        return self._hold(
            funding,
            f"Funding {funding:.1f}% dentro de zona normal "
            f"(threshold ±{self.threshold_pct}%)"
        )

    @staticmethod
    def _hold(funding: float, reason: str) -> dict:
        return {"action": "HOLD", "funding_annualized": funding, "reason": reason}
