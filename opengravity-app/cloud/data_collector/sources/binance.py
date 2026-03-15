"""Binance Futures data fetcher — funding, OI, liquidations, OHLCV."""
import aiohttp
import asyncio
from datetime import datetime, timezone, timedelta
from ..config import (
    BINANCE_API, ALL_SYMBOLS, ALL_WITH_TIER3,
    bn_symbol, BINANCE_RPS, BACKFILL_DAYS_FUNDING, BACKFILL_DAYS_OI,
)


async def fetch_funding_rates(pool, symbols: list[str] = None):
    """Fetch latest funding rates from Binance Futures."""
    symbols = symbols or ALL_SYMBOLS
    rows = []

    async with aiohttp.ClientSession() as session:
        # premiumIndex gives funding for all symbols in one call
        url = f"{BINANCE_API}/fapi/v1/premiumIndex"
        async with session.get(url) as resp:
            if resp.status != 200:
                print(f"[BN] premiumIndex error: {resp.status}")
                return 0
            data = await resp.json()

        sym_map = {bn_symbol(s): s for s in symbols}
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

        for item in data:
            bn_sym = item["symbol"]
            if bn_sym not in sym_map:
                continue
            sym = sym_map[bn_sym]
            rate = float(item.get("lastFundingRate", 0))
            mark = float(item.get("markPrice", 0))
            index = float(item.get("indexPrice", 0))
            apy = rate * 3 * 365 * 100
            ts_ms = item.get("nextFundingTime", 0)
            # Use the current hour as timestamp
            rows.append((now, "binance", sym, rate, apy, None, mark, index))

    if rows:
        from ..storage.postgres import insert_funding
        n = await insert_funding(pool, rows)
        print(f"[BN] Funding: {n}/{len(rows)} rows")
        return n
    return 0


async def fetch_open_interest(pool, symbols: list[str] = None):
    """Fetch open interest from Binance Futures."""
    symbols = symbols or ALL_SYMBOLS
    rows = []
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    async with aiohttp.ClientSession() as session:
        for sym in symbols:
            url = f"{BINANCE_API}/fapi/v1/openInterest?symbol={bn_symbol(sym)}"
            async with session.get(url) as resp:
                if resp.status != 200:
                    continue
                data = await resp.json()

            oi_contracts = float(data.get("openInterest", 0))
            # Get mark price for USD conversion
            mark_url = f"{BINANCE_API}/fapi/v1/premiumIndex?symbol={bn_symbol(sym)}"
            async with session.get(mark_url) as resp2:
                if resp2.status == 200:
                    mark_data = await resp2.json()
                    mark = float(mark_data.get("markPrice", 0))
                else:
                    mark = 0
            oi_usd = oi_contracts * mark
            rows.append((now, "binance", sym, oi_contracts, oi_usd))
            await asyncio.sleep(1.0 / BINANCE_RPS)

    if rows:
        from ..storage.postgres import insert_open_interest
        n = await insert_open_interest(pool, rows)
        print(f"[BN] OI: {n}/{len(rows)} rows")
        return n
    return 0


async def fetch_liquidations(pool, symbols: list[str] = None):
    """Fetch recent liquidation orders from Binance Futures (forceOrders)."""
    symbols = symbols or ALL_SYMBOLS
    rows = []

    async with aiohttp.ClientSession() as session:
        # forceOrders — returns recent liquidations
        url = f"{BINANCE_API}/fapi/v1/forceOrders?limit=100"
        async with session.get(url) as resp:
            if resp.status != 200:
                print(f"[BN] forceOrders error: {resp.status}")
                return 0
            data = await resp.json()

        sym_map = {bn_symbol(s): s for s in symbols}

        for item in data:
            bn_sym = item.get("symbol", "")
            if bn_sym not in sym_map:
                continue
            sym = sym_map[bn_sym]
            ts = datetime.fromtimestamp(item["time"] / 1000, tz=timezone.utc)
            side = "long" if item.get("side", "").upper() == "SELL" else "short"
            qty = float(item.get("origQty", 0))
            price = float(item.get("averagePrice", 0) or item.get("price", 0))
            usd = qty * price
            rows.append((ts, "binance", sym, side, qty, usd, price))

    if rows:
        from ..storage.postgres import insert_liquidations
        n = await insert_liquidations(pool, rows)
        print(f"[BN] Liquidations: {n}/{len(rows)} rows")
        return n
    return 0


async def fetch_ohlcv(pool, symbols: list[str] = None, timeframe: str = "1d", limit: int = 500):
    """Fetch OHLCV candles from Binance Futures."""
    symbols = symbols or ALL_WITH_TIER3
    total = 0

    async with aiohttp.ClientSession() as session:
        for sym in symbols:
            url = (f"{BINANCE_API}/fapi/v1/klines"
                   f"?symbol={bn_symbol(sym)}&interval={timeframe}&limit={limit}")
            async with session.get(url) as resp:
                if resp.status != 200:
                    print(f"[BN] OHLCV {sym} error: {resp.status}")
                    continue
                data = await resp.json()

            rows = []
            for c in data:
                ts = datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc)
                rows.append((
                    ts, "binance", sym, timeframe,
                    float(c[1]),  # open
                    float(c[2]),  # high
                    float(c[3]),  # low
                    float(c[4]),  # close
                    float(c[5]),  # volume
                ))

            if rows:
                from ..storage.postgres import insert_ohlcv
                n = await insert_ohlcv(pool, rows)
                total += n

            await asyncio.sleep(1.0 / BINANCE_RPS)

    print(f"[BN] OHLCV: {total} rows")
    return total


async def backfill_funding(pool, symbols: list[str] = None, days: int = None):
    """Backfill historical funding from Binance fundingRate endpoint."""
    symbols = symbols or ALL_SYMBOLS
    days = days or BACKFILL_DAYS_FUNDING
    total = 0

    from ..storage.postgres import get_latest_timestamp, insert_funding

    async with aiohttp.ClientSession() as session:
        for sym in symbols:
            latest = await get_latest_timestamp(pool, "funding_rates", "binance", sym)
            if latest:
                start_ms = int(latest.timestamp() * 1000) + 1
            else:
                start_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)

            url = (f"{BINANCE_API}/fapi/v1/fundingRate"
                   f"?symbol={bn_symbol(sym)}&startTime={start_ms}&limit=1000")
            async with session.get(url) as resp:
                if resp.status != 200:
                    print(f"[BN] Backfill {sym} error: {resp.status}")
                    continue
                records = await resp.json()

            rows = []
            for rec in records:
                ts = datetime.fromtimestamp(rec["fundingTime"] / 1000, tz=timezone.utc)
                rate = float(rec["fundingRate"])
                apy = rate * 3 * 365 * 100
                mark = float(rec.get("markPrice", 0))
                rows.append((ts, "binance", sym, rate, apy, None, mark, None))

            if rows:
                n = await insert_funding(pool, rows)
                total += n
                print(f"[BN] Backfill {sym}: {n} rows")

            await asyncio.sleep(1.0 / BINANCE_RPS)

    print(f"[BN] Backfill complete: {total} total rows")
    return total
