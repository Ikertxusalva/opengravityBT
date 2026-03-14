"""GaussianHMM con 3 estados. Walk-forward: nunca ve datos futuros."""
from __future__ import annotations
import time, logging
import numpy as np
from typing import List, Dict, Optional
from hmmlearn import hmm
from btquantr.config import config

log = logging.getLogger("RegimeDetector")


class RegimeDetector:
    STATE_NAMES = {0: "BULL", 1: "SIDEWAYS", 2: "BEAR"}

    def __init__(self):
        self.model = hmm.GaussianHMM(n_components=config.hmm.n_states,
                                      covariance_type="full", n_iter=500,
                                      random_state=42, verbose=False)
        self.is_trained = False
        self.feature_names: List[str] = []
        self.means_: Optional[np.ndarray] = None
        self.stds_: Optional[np.ndarray] = None
        self.last_train_time: float = 0
        self.train_count: int = 0

    def train(self, history: List[List[float]], feature_names: List[str]) -> bool:
        if len(history) < config.hmm.min_train:
            return False
        # Filtrar vectores con longitud consistente al tamaño más reciente
        # (puede haber inhomogeneidad si las features disponibles en Redis cambiaron)
        window = history[-config.hmm.window:]
        target_len = len(window[-1])
        window = [v for v in window if len(v) == target_len]
        if len(window) < config.hmm.min_train:
            return False
        X = np.array(window)
        self.means_ = X.mean(axis=0)
        self.stds_ = X.std(axis=0)
        self.stds_[self.stds_ == 0] = 1.0
        X_norm = (X - self.means_) / self.stds_
        try:
            self.model.fit(X_norm)
            self.is_trained = True
            self.feature_names = feature_names
            self.last_train_time = time.time()
            self.train_count += 1
            if "returns" in feature_names:
                idx = feature_names.index("returns")
                order = np.argsort(self.model.means_[:, idx])[::-1]
                self.STATE_NAMES = {int(order[i]): l for i, l in enumerate(["BULL", "SIDEWAYS", "BEAR"])}
            log.info(f"HMM #{self.train_count} entrenado — {len(X)} muestras")
            return True
        except Exception as e:
            log.error(f"Error HMM: {e}")
            return False

    def predict(self, history: List[List[float]]) -> Optional[Dict]:
        if not self.is_trained or self.means_ is None:
            return None
        expected_len = len(self.means_)
        window = [v for v in history[-config.hmm.window:] if len(v) == expected_len]
        if not window:
            return None
        X = np.array(window)
        X_norm = (X - self.means_) / self.stds_
        try:
            states = self.model.predict(X_norm)
            probs = self.model.predict_proba(X_norm)
            cur = int(states[-1])
            cur_p = probs[-1].tolist()
            recent = states[-10:] if len(states) >= 10 else states
            return {
                "state": cur,
                "state_name": self.STATE_NAMES.get(cur, f"STATE_{cur}"),
                "confidence": round(float(max(cur_p)), 4),
                "probs": {self.STATE_NAMES.get(i, f"S{i}"): round(p, 4) for i, p in enumerate(cur_p)},
                "stability": round(float(np.mean(recent == cur)), 3),
                "features_used": self.feature_names,
                "train_count": self.train_count,
                "samples_in_window": len(X),
                "timestamp": time.time(),
            }
        except Exception as e:
            log.error(f"Error predict: {e}")
            return None

    def should_retrain(self) -> bool:
        return not self.is_trained or (time.time() - self.last_train_time) > config.hmm.retrain_interval
