"""
fred_data.py — Fuente de verdad unica para datos FRED (Federal Reserve Economic Data).

Centraliza: series FRED historicas y snapshot macro combinado (FRED + yfinance).

Uso:
    from moondev.data.fred_data import (
        get_series, get_macro_snapshot,
        FRED_BASE, FRED_SERIES,
    )
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

FRED_SERIES = {
    "fed_rate":     "DFF",
    "yield_curve":  "T10Y2Y",
    "cpi":          "CPIAUCSL",
    "unemployment": "UNRATE",
    "m2":           "M2SL",
    "hy_spread":    "BAMLH0A0HYM2",
    "gdp":          "GDP",
    "pce":          "PCE",
    "retail_sales": "RSAFS",
    "10y":          "DGS10",
    "vix":          "VIXCLS",
}

MACRO_SERIES_ALIASES = {
    "VIX":   "VIXCLS",
    "FED":   "FEDFUNDS",
    "CPI":   "CPIAUCSL",
    "UST10": "DGS10",
    "UNEMP": "UNRATE",
}


# ── Transporte ────────────────────────────────────────────────────────────────

def _parse_val(v: str) -> float | None:
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Series FRED
# ═══════════════════════════════════════════════════════════════════════════════

def get_series(
    series_id: str,
    days: int = 365,
    limit: int | None = None,
) -> Optional[pd.Series]:
    """
    Serie historica desde FRED.

    Args:
        series_id: ID FRED (e.g. "VIXCLS") o alias del dict FRED_SERIES
        days: dias de historia
        limit: maximo de observaciones (None = todas)

    Returns:
        pd.Series con DatetimeIndex UTC, None si falla.
    """
    resolved = FRED_SERIES.get(series_id.lower(), series_id.upper())
    resolved = MACRO_SERIES_ALIASES.get(resolved, resolved)

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    params: dict = {
        "series_id": resolved,
        "observation_start": start_date,
        "observation_end": end_date,
        "file_type": "json",
        "sort_order": "asc",
    }
    if FRED_API_KEY:
        params["api_key"] = FRED_API_KEY
    if limit:
        params["limit"] = limit
        params["sort_order"] = "desc"

    try:
        resp = requests.get(FRED_BASE, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    observations = data.get("observations", [])
    if not observations:
        return None

    records = []
    for obs in observations:
        val = _parse_val(obs.get("value", "."))
        if val is not None:
            records.append({"date": obs["date"], "value": val})

    if not records:
        return None

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df = df.set_index("date").sort_index()
    return df["value"].rename(resolved)


def get_series_list(
    series_id: str,
    limit: int = 100,
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    """
    Observaciones como lista de dicts (formato compatible con rbi.tools.fred).

    Returns:
        [{date: "YYYY-MM-DD", value: float}, ...]
    """
    if not FRED_API_KEY:
        return [{"error": "FRED_API_KEY no configurada"}]

    resolved = FRED_SERIES.get(series_id.lower(), series_id.upper())
    params: dict = {
        "series_id": resolved,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    if start:
        params["observation_start"] = start
    if end:
        params["observation_end"] = end

    try:
        resp = requests.get(FRED_BASE, params=params, timeout=15)
        return [
            {"date": o["date"], "value": _parse_val(o["value"])}
            for o in resp.json().get("observations", [])
            if o["value"] != "."
        ]
    except Exception as e:
        logger.warning("get_series_list error: %s", e)
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Macro snapshot (FRED + yfinance)
# ═══════════════════════════════════════════════════════════════════════════════

def get_macro_snapshot() -> dict:
    """
    Snapshot completo de indicadores macro.
    Combina yfinance (tiempo real, sin key) + FRED (si hay key).
    """
    from moondev.data.yfinance_data import get_macro_series, get_macro_latest

    snapshot: dict = {}

    yf_targets = [
        ("vix", "vix"), ("10y_yield", "10y"), ("dxy", "dxy"),
        ("gold", "gold"), ("oil", "oil"), ("sp500", "sp500"),
        ("eurusd", "eurusd"),
    ]
    for key, alias in yf_targets:
        obs = get_macro_series(alias, days=3)
        snapshot[key] = obs[-1] if obs and "error" not in obs[0] else {"value": None}

    y10 = snapshot.get("10y_yield", {}).get("value")
    y2 = get_macro_latest("2y").get("value")
    if y10 is not None and y2 is not None:
        spread = round((y10 - y2) / 10, 3) if y10 > 1 else round(y10 - y2, 3)
        snapshot["yield_curve_approx"] = {"value": spread, "note": "10Y-3m via yfinance"}

    if FRED_API_KEY:
        for key, sid in [("fed_rate", "DFF"), ("yield_curve_10y2y", "T10Y2Y"),
                         ("unemployment", "UNRATE"), ("cpi_yoy", "CPIAUCSL")]:
            try:
                obs = get_series_list(sid, limit=1)
                snapshot[key] = obs[0] if obs else {"value": None}
            except Exception:
                pass

    vix_val = snapshot.get("vix", {}).get("value")
    yc_val = snapshot.get("yield_curve_approx", {}).get("value")
    snapshot["regime"] = {
        "high_volatility": vix_val is not None and vix_val > 25,
        "extreme_volatility": vix_val is not None and vix_val > 40,
        "yield_curve_inverted": yc_val is not None and yc_val < 0,
        "risk_off": vix_val is not None and vix_val > 30,
        "data_source": "yfinance" + (" + FRED" if FRED_API_KEY else " (sin FRED_API_KEY)"),
    }
    return snapshot
