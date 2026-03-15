"""HyperLiquid data fetcher — funding rates + open interest."""
import aiohttp
import asyncio
from datetime import datetime, timezone, timedelta
from ..config import HL_API, ALL_SYMBOLS, HL_RPS, BACKFILL_DAYS_FUNDING


async def fetch_funding_rates(pool, symbols: list[str] = None):
    """Fetch current funding rates for all symbols from HyperLiquid."""
    symbols = symbols or ALL_SYMBOLS
    rows = []
    now = datetime.now(timezone.utc)
    # Truncate to the hour
    ts = now.replace(minute=0, second=0, microsecond=0)

    async with aiohttp.ClientSession() as session:
        # Single call gets all metas + funding
        async with session.post(HL_API, json={"type": "metaAndAssetCtxs"}) as resp:
            if resp.status != 200:
                print(f"[HL] metaAndAssetCtxs error: {resp.status}")
                return 0
            data = await resp.json()

        meta = data[0]  # universe info
        ctxs = data[1]  # asset contexts

        universe = {u["name"]: i for i, u in enumerate(meta["universe"])}

        for sym in symbols:
            if sym not in universe:
                continue
            idx = universe[sym]
            ctx = ctxs[idx]
            rate = float(ctx.get("funding", 0))
            mark = float(ctx.get("markPx", 0))
            # APY = rate * 3 * 365 (funding every 8h)
            apy = rate * 3 * 365 * 100
            rows.append((ts, "hyperliquid", sym, rate, apy, None, mark, None))

    if rows:
        from ..storage.postgres import insert_funding
        n = await insert_funding(pool, rows)
        print(f"[HL] Funding: {n}/{len(rows)} rows inserted")
        return n
    return 0


async def fetch_open_interest(pool, symbols: list[str] = None):
    """Fetch open interest for all symbols from HyperLiquid."""
    symbols = symbols or ALL_SYMBOLS
    rows = []
    now = datetime.now(timezone.utc)
    ts = now.replace(minute=0, second=0, microsecond=0)

    async with aiohttp.ClientSession() as session:
        async with session.post(HL_API, json={"type": "metaAndAssetCtxs"}) as resp:
            if resp.status != 200:
                print(f"[HL] OI error: {resp.status}")
                return 0
            data = await resp.json()

        ctxs = data[1]
        universe = {u["name"]: i for i, u in enumerate(data[0]["universe"])}

        for sym in symbols:
            if sym not in universe:
                continue
            idx = universe[sym]
            ctx = ctxs[idx]
            oi_contracts = float(ctx.get("openInterest", 0))
            mark = float(ctx.get("markPx", 0))
            oi_usd = oi_contracts * mark
            rows.append((ts, "hyperliquid", sym, oi_contracts, oi_usd))

    if rows:
        from ..storage.postgres import insert_open_interest
        n = await insert_open_interest(pool, rows)
        print(f"[HL] OI: {n}/{len(rows)} rows inserted")
        return n
    return 0


async def backfill_funding(pool, symbols: list[str] = None, days: int = None):
    """Backfill historical funding from HyperLiquid fundingHistory endpoint."""
    symbols = symbols or ALL_SYMBOLS
    days = days or BACKFILL_DAYS_FUNDING
    total = 0

    from ..storage.postgres import get_latest_timestamp, insert_funding

    async with aiohttp.ClientSession() as session:
        for sym in symbols:
            # Get last stored timestamp
            latest = await get_latest_timestamp(pool, "funding_rates", "hyperliquid", sym)
            if latest:
                start_ms = int(latest.timestamp() * 1000) + 1
            else:
                start_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)

            end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

            payload = {
                "type": "fundingHistory",
                "coin": sym,
                "startTime": start_ms,
                "endTime": end_ms,
            }
            async with session.post(HL_API, json=payload) as resp:
                if resp.status != 200:
                    print(f"[HL] Backfill {sym} error: {resp.status}")
                    continue
                records = await resp.json()

            rows = []
            for rec in records:
                ts = datetime.fromtimestamp(rec["time"] / 1000, tz=timezone.utc)
                rate = float(rec["fundingRate"])
                apy = rate * 3 * 365 * 100
                rows.append((ts, "hyperliquid", sym, rate, apy, None, None, None))

            if rows:
                n = await insert_funding(pool, rows)
                total += n
                print(f"[HL] Backfill {sym}: {n} rows")

            await asyncio.sleep(1.0 / HL_RPS)

    print(f"[HL] Backfill complete: {total} total rows")
    return total
