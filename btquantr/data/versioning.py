"""Versionado SHA-256 para reproducibilidad total."""
import hashlib
import time
import pandas as pd
from typing import Dict


def compute_sha256(df: pd.DataFrame) -> str:
    return hashlib.sha256(df.to_csv().encode()).hexdigest()


def create_snapshot(df: pd.DataFrame, symbol: str, tf: str, source: str) -> Dict:
    return {
        "sha256": compute_sha256(df),
        "symbol": symbol, "timeframe": tf, "source": source,
        "n_rows": len(df),
        "start": str(df.index[0]) if len(df) > 0 else None,
        "end": str(df.index[-1]) if len(df) > 0 else None,
        "created_at": time.time(),
    }


def snapshots_match(a: Dict, b: Dict) -> bool:
    return a["sha256"] == b["sha256"]
