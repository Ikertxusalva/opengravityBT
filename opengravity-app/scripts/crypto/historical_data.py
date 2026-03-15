"""
historical_data.py — Descarga datos históricos OHLCV desde Binance (gratis, sin API key).

Uso:
    python historical_data.py BTC 365 1d          # BTC último año, velas diarias
    python historical_data.py ETH 90 4h           # ETH 90 días, velas 4h
    python historical_data.py SOL 730 1d           # SOL 2 años, velas diarias
    python historical_data.py BTC 30 1h --json     # Output JSON en vez de tabla

Intervalos válidos: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M
"""

import sys
import time
import json
import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

BINANCE_API = "https://api.binance.com/api/v3/klines"
DATA_DIR = Path(__file__).parent / "data"

# Mapeo de símbolos comunes a pares Binance
SYMBOL_MAP = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT",
    "BNB": "BNBUSDT", "AVAX": "AVAXUSDT", "DOGE": "DOGEUSDT",
    "ADA": "ADAUSDT", "XRP": "XRPUSDT", "DOT": "DOTUSDT",
    "MATIC": "MATICUSDT", "LINK": "LINKUSDT", "UNI": "UNIUSDT",
    "ATOM": "ATOMUSDT", "APT": "APTUSDT", "ARB": "ARBUSDT",
    "OP": "OPUSDT", "SUI": "SUIUSDT", "SEI": "SEIUSDT",
    "TIA": "TIAUSDT", "WIF": "WIFUSDT", "PEPE": "PEPEUSDT",
    "NEAR": "NEARUSDT", "FTM": "FTMUSDT", "INJ": "INJUSDT",
}

# Milisegundos por intervalo (para calcular cuántas requests necesitamos)
INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "6h": 21_600_000, "8h": 28_800_000, "12h": 43_200_000,
    "1d": 86_400_000, "3d": 259_200_000, "1w": 604_800_000, "1M": 2_592_000_000,
}


def fetch_klines(symbol: str, interval: str, days: int) -> pd.DataFrame:
    """Descarga velas históricas de Binance con paginación automática."""
    pair = SYMBOL_MAP.get(symbol.upper(), f"{symbol.upper()}USDT")
    end_time = int(time.time() * 1000)
    start_time = end_time - (days * 86_400_000)

    all_klines = []
    current_start = start_time

    while current_start < end_time:
        params = {
            "symbol": pair,
            "interval": interval,
            "startTime": current_start,
            "endTime": end_time,
            "limit": 1000,
        }
        resp = requests.get(BINANCE_API, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if not data:
            break

        all_klines.extend(data)
        # Avanzar al siguiente bloque
        current_start = data[-1][6] + 1  # close_time + 1ms

        if len(data) < 1000:
            break

        time.sleep(0.1)  # Rate limit cortesía

    if not all_klines:
        print(f"ERROR: No se encontraron datos para {pair}")
        sys.exit(1)

    df = pd.DataFrame(all_klines, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_vol",
        "taker_buy_quote_vol", "ignore"
    ])

    # Convertir tipos
    df["date"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[col] = df[col].astype(float)
    df["trades"] = df["trades"].astype(int)

    df = df[["date", "open", "high", "low", "close", "volume", "quote_volume", "trades"]]
    df = df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)

    return df


def print_summary(df: pd.DataFrame, symbol: str, interval: str):
    """Imprime resumen de los datos descargados."""
    print(f"\n{'='*60}")
    print(f"  {symbol.upper()} | {interval} | {len(df)} velas")
    print(f"  Desde: {df['date'].iloc[0]}")
    print(f"  Hasta: {df['date'].iloc[-1]}")
    print(f"{'='*60}")

    first_price = df["close"].iloc[0]
    last_price = df["close"].iloc[-1]
    change_pct = ((last_price - first_price) / first_price) * 100
    high = df["high"].max()
    low = df["low"].min()
    avg_vol = df["volume"].mean()

    print(f"  Precio inicial:  ${first_price:,.2f}")
    print(f"  Precio actual:   ${last_price:,.2f}")
    print(f"  Cambio:          {change_pct:+.2f}%")
    print(f"  ATH periodo:     ${high:,.2f}")
    print(f"  ATL periodo:     ${low:,.2f}")
    print(f"  Vol promedio:    {avg_vol:,.0f}")
    print(f"  Max drawdown:    {_max_drawdown(df['close']):.2f}%")
    print(f"{'='*60}\n")

    # Últimas 10 velas
    print(df.tail(10).to_string(index=False))
    print()


def _max_drawdown(series: pd.Series) -> float:
    """Calcula el máximo drawdown de una serie de precios."""
    peak = series.expanding().max()
    dd = ((series - peak) / peak) * 100
    return dd.min()


def save_data(df: pd.DataFrame, symbol: str, interval: str, fmt: str = "csv"):
    """Guarda los datos en disco."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{symbol.upper()}_{interval}_{df['date'].iloc[0].strftime('%Y%m%d')}_{df['date'].iloc[-1].strftime('%Y%m%d')}"

    if fmt == "json":
        path = DATA_DIR / f"{filename}.json"
        df["date"] = df["date"].astype(str)
        path.write_text(json.dumps(df.to_dict(orient="records"), indent=2))
    else:
        path = DATA_DIR / f"{filename}.csv"
        df.to_csv(path, index=False)

    print(f"  Guardado en: {path}")
    return path


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    symbol = sys.argv[1]
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 365
    interval = sys.argv[3] if len(sys.argv) > 3 else "1d"
    output_fmt = "json" if "--json" in sys.argv else "csv"

    if interval not in INTERVAL_MS:
        print(f"ERROR: Intervalo '{interval}' no válido. Usa: {', '.join(INTERVAL_MS.keys())}")
        sys.exit(1)

    print(f"\n  Descargando {symbol.upper()} | {days} días | {interval}...")
    df = fetch_klines(symbol, interval, days)
    print_summary(df, symbol, interval)
    save_data(df, symbol, interval, output_fmt)


if __name__ == "__main__":
    main()
