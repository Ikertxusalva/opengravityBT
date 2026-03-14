"""Datos macro via yfinance — VIX, DXY, SPY, Gold, TLT."""
import yfinance as yf
from typing import Dict, Optional

MACRO_TICKERS = {"VIX": "^VIX", "DXY": "DX-Y.NYB", "SPY": "SPY",
                 "GOLD": "GC=F", "TLT": "TLT"}


class YFinanceSource:
    def get_latest(self, ticker_key: str) -> Optional[Dict]:
        symbol = MACRO_TICKERS.get(ticker_key)
        if not symbol:
            return None
        try:
            hist = yf.Ticker(symbol).history(period="2d", interval="1d")
            if len(hist) < 2:
                return None
            price = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2])
            return {"ticker": ticker_key, "price": round(price, 4),
                    "chg_1d": round((price - prev) / prev * 100, 3)}
        except Exception:
            return None

    def get_all_macro(self) -> Dict:
        return {k: self.get_latest(k) for k in MACRO_TICKERS}

    def get_vix_history(self, days: int = 365) -> list:
        try:
            hist = yf.Ticker("^VIX").history(period=f"{days}d", interval="1d")
            return [{"timestamp": int(ts.timestamp() * 1000), "close": round(float(row["Close"]), 4)}
                    for ts, row in hist.iterrows()]
        except Exception:
            return []
