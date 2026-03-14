"""
btquantr/execution/position_sizer.py — PositionSizer autónomo.

Calcula el tamaño óptimo de posición combinando:
  1. Kelly Criterion:  f* = p - q/b  (p=win_rate, q=1-p, b=avg_win/avg_loss)
  2. Regime scaling:   BULL=100%, SIDEWAYS=50%, BEAR=25% del Kelly
  3. ATR scaling:      reduce cuando ATR > 2× media
  4. Portfolio heat:   suma exposure ≤ max_portfolio_heat_pct (default 30%)
  5. Single position:  ninguna posición > max_single_pct (default 10%)

Uso:
    ps = PositionSizer()
    result = ps.calculate(
        balance=10_000,
        win_rate=0.6, avg_win=1.5, avg_loss=1.0,
        regime="BULL",
        atr=250, atr_mean=100,
        open_exposure_usd=500,
    )
    # result["size_usd"] → tamaño en USD para la orden
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("BTQUANTRPositionSizer")

_REGIME_SCALE: dict[str, float] = {
    "BULL":     1.00,
    "SIDEWAYS": 0.50,
    "BEAR":     0.25,
}


class PositionSizer:
    """Calcula tamaño de posición con Kelly + ajustes adaptativos.

    Parámetros:
        max_portfolio_heat_pct: máximo % del balance que puede estar en riesgo (default 30%).
        max_single_pct:         máximo % del balance en una sola posición (default 10%).
    """

    def __init__(
        self,
        max_portfolio_heat_pct: float = 30.0,
        max_single_pct: float = 10.0,
    ) -> None:
        self.max_portfolio_heat_pct = max_portfolio_heat_pct
        self.max_single_pct = max_single_pct

    # ── API pública ───────────────────────────────────────────────────────────

    def kelly_fraction(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
    ) -> float:
        """Calcula la fracción Kelly óptima.

        Fórmula: f* = p - q/b  donde b = avg_win / avg_loss
        Resultado clampeado a [0, 1].

        Args:
            win_rate: probabilidad de ganancia (0–1).
            avg_win:  ganancia media en unidades monetarias.
            avg_loss: pérdida media (valor positivo, ej. 1.0).

        Returns:
            Fracción Kelly en [0, 1].
        """
        if win_rate <= 0.0 or avg_loss <= 0.0 or avg_win <= 0.0:
            return 0.0
        b = avg_win / avg_loss
        q = 1.0 - win_rate
        f = win_rate - q / b
        return max(0.0, min(1.0, f))

    def regime_scale(self, regime: str) -> float:
        """Retorna el multiplicador de Kelly según el régimen.

        BULL=1.0, SIDEWAYS=0.5, BEAR=0.25, desconocido→1.0.
        """
        return _REGIME_SCALE.get(regime.upper(), 1.0)

    def atr_scale(
        self,
        atr: Optional[float],
        atr_mean: Optional[float],
    ) -> float:
        """Factor de escala por volatilidad ATR.

        Si ATR ≤ 2× media → sin reducción (1.0).
        Si ATR > 2× media → scale = 2 × atr_mean / atr  (proporcional).
        Resultado clampeado a (0, 1].

        Args:
            atr:      ATR actual del símbolo.
            atr_mean: ATR medio de referencia.

        Returns:
            Factor en (0, 1].
        """
        if atr is None or atr_mean is None or atr_mean <= 0.0 or atr <= 0.0:
            return 1.0
        if atr <= 2.0 * atr_mean:
            return 1.0
        scale = (2.0 * atr_mean) / atr
        return max(1e-6, min(1.0, scale))

    def calculate(
        self,
        balance: float,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        regime: str = "BULL",
        atr: Optional[float] = None,
        atr_mean: Optional[float] = None,
        open_exposure_usd: float = 0.0,
    ) -> dict:
        """Calcula el tamaño de posición óptimo aplicando todos los ajustes.

        Args:
            balance:          Capital total disponible en USD.
            win_rate:         Probabilidad de ganancia histórica (0–1).
            avg_win:          Ganancia media por trade (en la misma unidad que avg_loss).
            avg_loss:         Pérdida media por trade (valor positivo).
            regime:           Régimen de mercado ("BULL" | "SIDEWAYS" | "BEAR").
            atr:              ATR actual (opcional, para scaling de volatilidad).
            atr_mean:         ATR medio de referencia (obligatorio si atr se pasa).
            open_exposure_usd: Suma de USD ya en riesgo en posiciones abiertas.

        Returns:
            dict con:
              - size_usd (float):        Tamaño final en USD.
              - size_pct (float):        Tamaño como % del balance.
              - kelly_fraction (float):  Fracción Kelly bruta (sin ajustes).
              - regime_scale (float):    Multiplicador de régimen aplicado.
              - atr_scale (float):       Factor de escala por ATR aplicado.
              - capped_by (str|None):    "portfolio_heat" | "single_position" | None.
              - blocked (bool):          True si no hay capacidad de portfolio.
              - reason (str):            Descripción del resultado.
        """
        if balance <= 0.0:
            return _zero_result(0.0, 0.0, 1.0, reason="balance=0")

        # ── 1. Kelly bruto ──────────────────────────────────────────────────
        kf = self.kelly_fraction(win_rate, avg_win, avg_loss)

        # ── 2. Regime scaling ───────────────────────────────────────────────
        r_scale = self.regime_scale(regime)
        size_fraction = kf * r_scale

        # ── 3. ATR scaling ──────────────────────────────────────────────────
        a_scale = self.atr_scale(atr, atr_mean)
        size_fraction *= a_scale

        # Tamaño crudo en USD
        raw_size_usd = size_fraction * balance

        # ── 4. Single position cap ──────────────────────────────────────────
        max_single_usd = self.max_single_pct / 100.0 * balance
        capped_by: Optional[str] = None
        if raw_size_usd > max_single_usd:
            raw_size_usd = max_single_usd
            capped_by = "single_position"

        # ── 5. Portfolio heat cap ───────────────────────────────────────────
        max_heat_usd = self.max_portfolio_heat_pct / 100.0 * balance
        available_usd = max_heat_usd - open_exposure_usd

        if available_usd <= 0.0:
            log.warning(
                "PositionSizer BLOCKED: portfolio heat exhausted "
                "(exposure=%.2f, max=%.2f)",
                open_exposure_usd, max_heat_usd,
            )
            return _zero_result(kf, r_scale, a_scale, reason="portfolio_heat_exhausted",
                                blocked=True)

        if raw_size_usd > available_usd:
            raw_size_usd = available_usd
            if capped_by is None:
                capped_by = "portfolio_heat"

        size_usd = max(0.0, raw_size_usd)
        size_pct = size_usd / balance * 100.0

        log.debug(
            "PositionSizer: kelly=%.4f regime_scale=%.2f atr_scale=%.2f "
            "→ size=$%.2f (%.2f%%) capped_by=%s",
            kf, r_scale, a_scale, size_usd, size_pct, capped_by,
        )

        return {
            "size_usd":       round(size_usd, 4),
            "size_pct":       round(size_pct, 4),
            "kelly_fraction": round(kf, 6),
            "regime_scale":   r_scale,
            "atr_scale":      round(a_scale, 6),
            "capped_by":      capped_by,
            "blocked":        False,
            "reason":         "ok",
        }


# ── Helpers internos ──────────────────────────────────────────────────────────

def _zero_result(
    kf: float,
    r_scale: float,
    a_scale: float,
    reason: str,
    blocked: bool = False,
) -> dict:
    return {
        "size_usd":       0.0,
        "size_pct":       0.0,
        "kelly_fraction": round(kf, 6),
        "regime_scale":   r_scale,
        "atr_scale":      round(a_scale, 6),
        "capped_by":      None,
        "blocked":        blocked,
        "reason":         reason,
    }
