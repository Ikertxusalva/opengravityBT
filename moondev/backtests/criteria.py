"""
Criterios de viabilidad para backtests (Quant Architect).
Centraliza umbrales definidos en moondev.config para PASS / PRECAUCION / FAIL
y veredicto global (VIABLE / SELECTIVO / NO_VIABLE).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

# Importar desde config central moondev
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from moondev.config import (
    PASS_SHARPE,
    PASS_MAX_DD_PCT,
    PASS_MIN_TRADES,
    PASS_MIN_WINRATE_PCT,
    CAUTION_SHARPE,
    CAUTION_MAX_DD_PCT,
    CAUTION_MIN_TRADES,
    VIABLE_PCT_THRESHOLD,
    SELECTIVE_PCT_THRESHOLD,
    BACKTEST_MIN_BARS,
)

if TYPE_CHECKING:
    from typing import Any


def verdict(r: Any) -> str:
    """
    Verdicto por activo: ERROR | PASS | PRECAUCION | FAIL.
    r debe tener: .error, .sharpe, .max_dd, .trades, .win_rate
    """
    if getattr(r, "error", None):
        return "ERROR"
    sharpe = getattr(r, "sharpe", 0.0) or 0.0
    max_dd = getattr(r, "max_dd", 0.0) or 0.0
    trades = getattr(r, "trades", 0) or 0
    win_rate = getattr(r, "win_rate", 0.0) or 0.0
    if (
        sharpe >= PASS_SHARPE
        and max_dd >= PASS_MAX_DD_PCT
        and trades >= PASS_MIN_TRADES
        and win_rate >= PASS_MIN_WINRATE_PCT
    ):
        return "PASS"
    if (
        sharpe >= CAUTION_SHARPE
        and max_dd >= CAUTION_MAX_DD_PCT
        and trades >= CAUTION_MIN_TRADES
    ):
        return "PRECAUCION"
    return "FAIL"


def global_verdict(pct_pass: float) -> str:
    """Veredicto global de la estrategia segun % de activos que pasan."""
    if pct_pass >= VIABLE_PCT_THRESHOLD:
        return "VIABLE"
    if pct_pass >= SELECTIVE_PCT_THRESHOLD:
        return "SELECTIVO"
    return "NO_VIABLE"


def global_verdict_label(pct_pass: float) -> str:
    """Etiqueta legible para informe (ASCII)."""
    g = global_verdict(pct_pass)
    if g == "VIABLE":
        return "VIABLE - funciona en multiples activos"
    if g == "SELECTIVO":
        return "SELECTIVO - solo funciona en algunos activos"
    return "NO VIABLE - no generaliza"


def is_valid_sample(n_bars: int) -> bool:
    """True si la muestra tiene suficientes barras (evita inferencia en muestras cortas)."""
    return n_bars >= BACKTEST_MIN_BARS
