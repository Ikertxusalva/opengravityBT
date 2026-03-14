"""RegimeService — proceso independiente 24/7."""
from __future__ import annotations
import logging, time
from collections import Counter
from typing import Dict, List, Optional
import redis as redis_lib
from btquantr.config import config
from btquantr.redis_client import get_redis
from btquantr.regime.detector import RegimeDetector
from btquantr.regime.features import FeatureCollector
from btquantr.regime.publisher import RegimePublisher

log = logging.getLogger("RegimeService")


class RegimeService:
    def __init__(self, r: redis_lib.Redis | None = None):
        self.r = r or get_redis()
        self.collector = FeatureCollector(self.r)
        self.publisher = RegimePublisher(self.r)
        self.detectors: Dict[str, RegimeDetector] = {}
        self.histories: Dict[str, List[List[float]]] = {}

    def warm_up(self, symbol: str, bootstrap_rows: List[Dict]) -> None:
        """Pre-entrena el HMM con vectores de bootstrap_history.

        Determina el feature set más frecuente, filtra vectores inconsistentes
        y entrena el detector directamente (sin pasar por step()).
        """
        if not bootstrap_rows:
            return
        feat_set_counts = Counter(frozenset(row.keys()) for row in bootstrap_rows)
        target_feats = sorted(feat_set_counts.most_common(1)[0][0])
        vecs = [
            [row[k] for k in target_feats]
            for row in bootstrap_rows
            if all(k in row for k in target_feats)
        ]
        if len(vecs) < config.hmm.min_train:
            log.warning(f"warm_up {symbol}: solo {len(vecs)} vectores (min={config.hmm.min_train}), skip")
            return
        self.histories[symbol] = vecs
        det = self.detectors.setdefault(symbol, RegimeDetector())
        trained = det.train(vecs, target_feats)
        if trained:
            log.info(f"warm_up {symbol}: HMM entrenado — {len(vecs)} vectores, features={target_feats}")
        else:
            log.warning(f"warm_up {symbol}: train() no pudo entrenar")

    def step(self, symbol: str) -> Optional[Dict]:
        features = self.collector.collect(symbol)
        if len(features) < config.hmm.min_features:
            return None
        feat_names = sorted(features.keys())
        vec = [features[k] for k in feat_names]
        hist = self.histories.setdefault(symbol, [])
        hist.append(vec)
        if len(hist) > config.hmm.window:
            hist[:] = hist[-config.hmm.window:]
        det = self.detectors.setdefault(symbol, RegimeDetector())
        if det.should_retrain():
            det.train(hist, feat_names)
        regime = det.predict(hist)
        if regime:
            self.publisher.publish(symbol, regime)
        return regime

    def _bootstrap_symbol(self, symbol: str) -> None:
        """Descarga histórico y pre-entrena el HMM antes del loop en tiempo real."""
        try:
            from btquantr.data.service import DataService
            log.info(f"bootstrap {symbol}: descargando histórico...")
            ds = DataService(self.r)
            rows = ds.bootstrap_history(symbol)
            if rows:
                self.warm_up(symbol, rows)
            else:
                log.warning(f"bootstrap {symbol}: sin datos históricos")
        except Exception as e:
            log.error(f"bootstrap {symbol}: {e}")

    def run(self) -> None:
        log.info(f"RegimeService iniciado — {config.hmm.symbols}")
        for sym in config.hmm.symbols:
            self._bootstrap_symbol(sym)
        while True:
            for sym in config.hmm.symbols:
                try:
                    self.step(sym)
                except Exception as e:
                    log.error(f"Error step({sym}): {e}")
            time.sleep(config.hmm.predict_interval)
