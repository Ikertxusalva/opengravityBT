"""WalkForwardOptimizer — optimización walk-forward de parámetros de estrategia."""
from __future__ import annotations
import math
from typing import Any, Callable
import numpy as np


def _sharpe(returns: np.ndarray, annualize: int = 252) -> float:
    """Sharpe anualizado de una serie de retornos."""
    if len(returns) < 2:
        return 0.0
    mean = float(np.mean(returns))
    std = float(np.std(returns, ddof=1))
    return (mean / std * math.sqrt(annualize)) if std > 0 else 0.0


_VALID_MODES = ("rolling", "anchored")


class WalkForwardOptimizer:
    """Walk-forward optimization para evaluar robustez de parámetros.

    mode="rolling"  (default): ventana deslizante, cada fold tiene el mismo
                    tamaño de in-sample.
    mode="anchored": el in-sample SIEMPRE empieza desde la barra 0 y crece
                    progresivamente; solo el out-of-sample avanza.
    """

    def __init__(
        self,
        n_splits: int = 5,
        train_ratio: float = 0.7,
        mode: str = "rolling",
    ):
        if n_splits < 1:
            raise ValueError("n_splits must be >= 1")
        if not 0 < train_ratio < 1:
            raise ValueError("train_ratio must be in (0, 1)")
        if mode not in _VALID_MODES:
            raise ValueError(f"mode debe ser uno de {_VALID_MODES}, recibido: '{mode}'")
        self.n_splits = n_splits
        self.train_ratio = train_ratio
        self.mode = mode

    def optimize(
        self,
        returns: list[float],
        strategy_fn: Callable[[list[float], Any], list[float]],
        param_grid: list[Any],
    ) -> dict:
        """Ejecuta optimización walk-forward.

        Args:
            returns: Retornos históricos completos.
            strategy_fn: f(returns, param) → lista de retornos modificados.
            param_grid: Lista de parámetros a probar.

        Returns:
            Dict con: best_param, is_robust, degradation, fold_results.
        """
        if not returns:
            raise ValueError("returns no puede estar vacío")
        if not param_grid:
            raise ValueError("param_grid no puede estar vacío")

        arr = np.array(returns, dtype=float)
        n = len(arr)

        chunk_size = n // self.n_splits
        if chunk_size < 3:
            raise ValueError(f"Muy pocos datos ({n}) para {self.n_splits} splits")

        fold_results = []
        param_counts: dict[Any, int] = {p: 0 for p in param_grid}

        # En anchored, usamos (n_splits+1) chunks: n_splits de OOS + arranque inicial
        anchored_chunk = n // (self.n_splits + 1) if self.mode == "anchored" else chunk_size

        for i in range(self.n_splits):
            if self.mode == "anchored":
                # In-sample: barra 0 → fin del chunk i+1 (crece progresivamente)
                train_end = (i + 1) * anchored_chunk
                train_data = arr[:train_end]
                # Out-of-sample: chunk i+1
                oos_start = train_end
                oos_end = oos_start + anchored_chunk if i < self.n_splits - 1 else n
                test_data = arr[oos_start:oos_end]
                train_start_idx = 0
            else:
                # Rolling: ventana fija de tamaño chunk_size
                start = i * chunk_size
                end = start + chunk_size if i < self.n_splits - 1 else n
                fold_data = arr[start:end]
                split = int(len(fold_data) * self.train_ratio)
                train_data = fold_data[:split]
                test_data = fold_data[split:]
                train_start_idx = start

            if len(train_data) < 2 or len(test_data) < 2:
                continue

            # Encontrar mejor param en train
            best_train_sharpe = -float("inf")
            best_param = param_grid[0]
            for param in param_grid:
                strat_returns = np.array(strategy_fn(train_data.tolist(), param))
                s = _sharpe(strat_returns)
                if s > best_train_sharpe:
                    best_train_sharpe = s
                    best_param = param

            # Evaluar en test
            test_strat = np.array(strategy_fn(test_data.tolist(), best_param))
            test_sharpe = _sharpe(test_strat)

            param_counts[best_param] = param_counts.get(best_param, 0) + 1
            fold_results.append({
                "fold": i,
                "best_param": best_param,
                "train_sharpe": round(best_train_sharpe, 4),
                "test_sharpe": round(test_sharpe, 4),
                "train_size": int(len(train_data)),
                "train_start": int(train_start_idx),
            })

        if not fold_results:
            raise ValueError("No se pudieron completar folds — datos insuficientes")

        # Parámetro más elegido
        overall_best = max(param_counts, key=lambda p: param_counts[p])

        # Degradación: mean(train_sharpe - test_sharpe) — positivo = overfitting
        degradation = float(np.mean([
            f["train_sharpe"] - f["test_sharpe"] for f in fold_results
        ]))

        # Robusto si degradación < 1.0 Sharpe punto
        is_robust = bool(degradation < 1.0 and len(fold_results) >= self.n_splits * 0.8)

        return {
            "best_param": overall_best,
            "is_robust": is_robust,
            "degradation": round(degradation, 4),
            "fold_results": fold_results,
            "mode": self.mode,
        }
