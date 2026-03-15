"""Bybit data fetcher — funding rates + open interest."""
import aiohttp
import asyncio
from datetime import datetime, timezone
from ..config import BYBIT_API, ALL_SYMBOLS, bybit_symbol, BYBIT_RPS


async def fetch_funding_rates(pool, symbols: list[str] = None):
    """Fetch latest funding from Bybit linear perpetuals."""
    symbols = symbols or ALL_SYMBOLS
    rows = []
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    async with aiohttp.ClientSession() as session:
        # Bybit tickers endpoint — one call for all
        url = f"{BYBIT_API}/v5/market/tickers?category=linear"
        async with session.get(url) as resp:
            if resp.status != 200:
                print(f"[BYBIT] tickers error: {resp.status}")
                return 0
            data = await resp.json()

        if data.get("retCode") != 0:
            print(f"[BYBIT] tickers retCode: {data.get('retCode')} {data.get('retMsg')}")
            return 0

        sym_map = {bybit_symbol(s): s for s in symbols}

        for item in data["result"]["list"]:
            bb_sym = item.get("symbol", "")
            if bb_sym not in sym_map:
                continue
            sym = sym_map[bb_sym]
            rate = float(item.get("fundingRate", 0))
            mark = float(item.get("markPrice", 0))
            index = float(item.get("indexPrice", 0))
            apy = rate * 3 * 365 * 100
            rows.append((now, "bybit", sym, rate, apy, None, mark, index))

    if rows:
        from ..storage.postgres import insert_funding
        n = await insert_funding(pool, rows)
        print(f"[BYBIT] Funding: {n}/{len(rows)} rows")
        return n
    return 0


async def fetch_open_interest(pool, symbols: list[str] = None):
    """Fetch open interest from Bybit."""
    symbols = symbols or ALL_SYMBOLS
    rows = []
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    async with aiohttp.ClientSession() as session:
        for sym in symbols:
            url = (f"{BYBIT_API}/v5/market/open-interest"
                   f"?category=linear&symbol={bybit_symbol(sym)}&intervalTime=5min&limit=1")
            async with session.get(url) as resp:
                if resp.status != 200:
                    continue
                data = await resp.json()

            if data.get("retCode") != 0:
                continue

            items = data.get("result", {}).get("list", [])
            if not items:
                continue

            item = items[0]
            oi = float(item.get("openInterest", 0))
            # Get mark for USD conversion from tickers
            mark_url = f"{BYBIT_API}/v5/market/tickers?category=linear&symbol={bybit_symbol(sym)}"
            async with session.get(mark_url) as resp2:
                if resp2.status == 200:
                    mdata = await resp2.json()
                    mlist = mdata.get("result", {}).get("list", [])
                    mark = float(mlist[0].get("markPrice", 0)) if mlist else 0
                else:
                    mark = 0

            oi_usd = oi * mark
            rows.append((now, "bybit", sym, oi, oi_usd))
            await asyncio.sleep(1.0 / BYBIT_RPS)

    if rows:
        from ..storage.postgres import insert_open_interest
        n = await insert_open_interest(pool, rows)
        print(f"[BYBIT] OI: {n}/{len(rows)} rows")
        return n
    return 0
