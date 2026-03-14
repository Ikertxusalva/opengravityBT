"""
nice_funcs — utilidades comunes para agentes y estrategias.
OHLCV, parsing de respuestas LLM, indicadores básicos.
"""
from __future__ import annotations
import time
import re
from typing import Optional
import pandas as pd
import pandas_ta as ta
from moondev.data.yfinance_data import get_ohlcv as _yf_get_ohlcv


def get_ohlcv(symbol: str, days: int = 14, timeframe: str = "1h") -> pd.DataFrame:
    """
    Descarga OHLCV desde yfinance via yfinance_data.
    symbol: 'BTC-USD', 'ETH-USD', etc.
    timeframe: '1h', '4h', '1d'
    Retorna columnas lowercase para compatibilidad con agentes existentes.
    """
    df = _yf_get_ohlcv(symbol, interval=timeframe, days=days)
    if df is None or df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df.columns = [c.lower() for c in df.columns]
    df.index.name = "datetime"
    return df[["open", "high", "low", "close", "volume"]].dropna()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Añade SMA20, SMA50, RSI14, MACD, Bollinger Bands."""
    df = df.copy()
    df["sma20"] = ta.sma(df["close"], 20)
    df["sma50"] = ta.sma(df["close"], 50)
    df["rsi"] = ta.rsi(df["close"], 14)
    macd = ta.macd(df["close"])
    if macd is not None:
        df["macd"] = macd.iloc[:, 0]
        df["macd_signal"] = macd.iloc[:, 1]
        df["macd_hist"] = macd.iloc[:, 2]
    bb = ta.bbands(df["close"])
    if bb is not None:
        df["bb_upper"] = bb.iloc[:, 2]
        df["bb_mid"] = bb.iloc[:, 1]
        df["bb_lower"] = bb.iloc[:, 0]
    return df


def parse_llm_action(text: str) -> tuple[str, str, int]:
    """
    Parsea respuesta LLM de 3 líneas:
        BUY/SELL/NOTHING
        Razón corta
        Confidence: X%
    Retorna (action, reason, confidence_int)
    """
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    action = lines[0].upper() if lines else "NOTHING"
    reason = lines[1] if len(lines) > 1 else ""
    conf_line = lines[2] if len(lines) > 2 else ""
    m = re.search(r"(\d+)", conf_line)
    confidence = int(m.group(1)) if m else 0
    if action not in ("BUY", "SELL", "NOTHING"):
        action = "NOTHING"
    return action, reason, confidence


def sleep_with_message(seconds: int, msg: str = "Esperando") -> None:
    from rich.console import Console
    c = Console()
    for i in range(seconds, 0, -1):
        c.print(f"[dim]{msg}... {i}s[/dim]", end="\r")
        time.sleep(1)
    c.print()
