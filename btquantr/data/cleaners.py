"""Pipeline de limpieza con 7 detectores independientes."""
from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List

RETURN_THRESHOLDS = {
    "BTC": {"1m": 0.05, "5m": 0.08, "1h": 0.15, "4h": 0.20, "1d": 0.30},
    "ETH": {"1m": 0.07, "5m": 0.10, "1h": 0.20, "4h": 0.25, "1d": 0.35},
    "DEFAULT": {"1m": 0.05, "5m": 0.10, "1h": 0.15, "4h": 0.25, "1d": 0.35},
}
TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


@dataclass
class Anomaly:
    timestamp: pd.Timestamp
    detector: str
    severity: str  # "critical" | "warning"
    field: str
    value: float
    expected_range: str
    action: str


def detect_impossible_returns(df: pd.DataFrame, asset: str = "DEFAULT", tf: str = "1h") -> List[Anomaly]:
    out: List[Anomaly] = []
    thresh = RETURN_THRESHOLDS.get(asset, RETURN_THRESHOLDS["DEFAULT"])
    max_r = thresh.get(tf, 0.15)
    rets = df["close"].pct_change().abs()
    for ts in df.index[rets > max_r]:
        v = float(rets.loc[ts])
        out.append(Anomaly(ts, "return_impossible", "critical" if v > max_r * 2 else "warning",
                           "close", round(v, 4), f"<{max_r}", "investigate"))
    return out


def detect_volume_anomalies(df: pd.DataFrame) -> List[Anomaly]:
    out: List[Anomaly] = []
    for ts in df.index[df["volume"] == 0]:
        out.append(Anomaly(ts, "volume_zero", "critical", "volume", 0.0, ">0", "interpolate"))
    vol_ma = df["volume"].rolling(50, min_periods=1).mean()
    ratio = df["volume"] / vol_ma.replace(0, np.nan)
    for ts in df.index[ratio > 10]:
        out.append(Anomaly(ts, "volume_extreme", "warning", "volume",
                           round(float(ratio.loc[ts]), 1), "<10x media", "flag"))
    stale = (df["volume"].diff() == 0).rolling(5).sum() >= 5
    for ts in df.index[stale]:
        out.append(Anomaly(ts, "volume_stale", "warning", "volume",
                           float(df.loc[ts, "volume"]), "variable", "flag"))
    return out


def detect_temporal_gaps(df: pd.DataFrame, tf: str = "1h") -> List[Anomaly]:
    out: List[Anomaly] = []
    expected = pd.Timedelta(seconds=TF_SECONDS.get(tf, 3600)) * 1.5
    for ts, delta in df.index.to_series().diff().items():
        if not pd.isna(delta) and delta > expected:
            out.append(Anomaly(ts, "temporal_gap", "warning", "timestamp",
                               float(delta.total_seconds()), f"<{expected.total_seconds()}s", "flag"))
    return out


def detect_stale_prices(df: pd.DataFrame, window: int = 5) -> List[Anomaly]:
    out: List[Anomaly] = []
    mask = (df["close"].diff() == 0).rolling(window).sum() >= window
    for ts in df.index[mask]:
        out.append(Anomaly(ts, "stale_price", "critical", "close",
                           float(df.loc[ts, "close"]), "moving", "investigate"))
    return out


def detect_ohlc_inconsistency(df: pd.DataFrame) -> List[Anomaly]:
    out: List[Anomaly] = []
    if not all(c in df.columns for c in ["open", "high", "low", "close"]):
        return out
    bad = (df["high"] < df["low"]) | (df["close"] > df["high"]) | (df["close"] < df["low"])
    for ts in df.index[bad]:
        out.append(Anomaly(ts, "ohlc_inconsistent", "critical", "ohlc",
                           0.0, "H>=L, L<=C<=H", "remove"))
    return out


def detect_wicks(df: pd.DataFrame, factor: float = 5.0) -> List[Anomaly]:
    out: List[Anomaly] = []
    body = (df["close"] - df["open"]).abs()
    total = df["high"] - df["low"]
    wick_pct = (total - body) / body.replace(0, np.nan)
    for ts in df.index[wick_pct > factor]:
        out.append(Anomaly(ts, "extreme_wick", "warning", "high_low",
                           round(float(wick_pct.loc[ts]), 1), f"<{factor}x body", "flag"))
    return out


def detect_duplicates(df: pd.DataFrame) -> List[Anomaly]:
    out: List[Anomaly] = []
    for ts in df.index[df.index.duplicated()]:
        out.append(Anomaly(ts, "duplicate_timestamp", "critical", "timestamp", 0.0, "unique", "remove"))
    return out


def run_all_detectors(df: pd.DataFrame, asset: str = "DEFAULT", tf: str = "1h") -> dict:
    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Columnas faltantes: {missing}")

    all_anom: List[Anomaly] = []
    all_anom += detect_impossible_returns(df, asset, tf)
    all_anom += detect_volume_anomalies(df)
    all_anom += detect_temporal_gaps(df, tf)
    all_anom += detect_stale_prices(df)
    all_anom += detect_ohlc_inconsistency(df)
    all_anom += detect_wicks(df)
    all_anom += detect_duplicates(df)

    critical_ts = {a.timestamp for a in all_anom if a.severity == "critical"}
    pct_clean = (len(df) - len(critical_ts)) / len(df) if len(df) > 0 else 0.0
    return {
        "n_rows": len(df), "n_anomalies": len(all_anom),
        "n_critical": len(critical_ts),
        "pct_clean": round(pct_clean, 4),
        "is_clean": pct_clean >= 0.95,
        "anomalies": all_anom,
    }
