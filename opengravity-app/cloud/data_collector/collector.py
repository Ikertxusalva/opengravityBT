"""Data Collector Daemon — runs as Railway worker service.

Schedules multi-exchange data collection into PostgreSQL.
Entry point: python -m data_collector.collector
"""
import asyncio
import signal
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import (
    INTERVAL_FUNDING, INTERVAL_OI, INTERVAL_LIQUIDATIONS,
    INTERVAL_SNAPSHOT, OHLCV_BACKUP_HOUR,
)
from .storage.postgres import create_pool, init_schema
from .sources import hyperliquid as hl
from .sources import binance as bn
from .sources import bybit as bb

pool = None


# ── Job wrappers (catch all errors so scheduler never dies) ──────────

async def job_funding():
    """Fetch funding rates from all 3 exchanges."""
    for name, fn in [("HL", hl.fetch_funding_rates),
                     ("BN", bn.fetch_funding_rates),
                     ("BYBIT", bb.fetch_funding_rates)]:
        try:
            await fn(pool)
        except Exception as e:
            print(f"[COLLECTOR] {name} funding error: {e}")


async def job_open_interest():
    """Fetch OI from all 3 exchanges."""
    for name, fn in [("HL", hl.fetch_open_interest),
                     ("BN", bn.fetch_open_interest),
                     ("BYBIT", bb.fetch_open_interest)]:
        try:
            await fn(pool)
        except Exception as e:
            print(f"[COLLECTOR] {name} OI error: {e}")


async def job_liquidations():
    """Fetch liquidations from Binance."""
    try:
        await bn.fetch_liquidations(pool)
    except Exception as e:
        print(f"[COLLECTOR] Liquidations error: {e}")


async def job_snapshot():
    """Build and store a market snapshot from latest data."""
    try:
        from .storage.postgres import insert_snapshot
        from datetime import datetime, timezone
        import aiohttp

        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

        # Aggregate from latest data in DB
        async with pool.acquire() as conn:
            # Total OI
            oi_row = await conn.fetchrow(
                "SELECT SUM(oi_usd) as total FROM open_interest "
                "WHERE timestamp = (SELECT MAX(timestamp) FROM open_interest)")
            total_oi = float(oi_row["total"]) if oi_row and oi_row["total"] else 0

            # Funding stats
            fr_rows = await conn.fetch(
                "SELECT symbol, funding_rate FROM funding_rates "
                "WHERE exchange='binance' AND timestamp = "
                "(SELECT MAX(timestamp) FROM funding_rates WHERE exchange='binance')")
            if fr_rows:
                rates = [float(r["funding_rate"]) for r in fr_rows]
                avg_funding = sum(rates) / len(rates)
                neg = sum(1 for r in rates if r < 0)
                pos = sum(1 for r in rates if r >= 0)
            else:
                avg_funding, neg, pos = 0, 0, 0

        # Fear & Greed from alternative.me
        fgi = None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://api.alternative.me/fng/?limit=1") as resp:
                    if resp.status == 200:
                        fdata = await resp.json()
                        fgi = int(fdata["data"][0]["value"])
        except Exception:
            pass

        row = (now, total_oi, None, None, avg_funding, fgi, neg, pos)
        await insert_snapshot(pool, row)
        print(f"[COLLECTOR] Snapshot saved: OI=${total_oi:,.0f} FGI={fgi}")

    except Exception as e:
        print(f"[COLLECTOR] Snapshot error: {e}")


async def job_ohlcv_backup():
    """Daily OHLCV backup from Binance."""
    try:
        await bn.fetch_ohlcv(pool, timeframe="1d", limit=2)  # Just last 2 days
        await bn.fetch_ohlcv(pool, timeframe="1h", limit=24)  # Last 24h
    except Exception as e:
        print(f"[COLLECTOR] OHLCV error: {e}")


async def job_backfill():
    """One-time backfill on first startup."""
    print("[COLLECTOR] Starting backfill...")
    try:
        await hl.backfill_funding(pool)
        await bn.backfill_funding(pool)
    except Exception as e:
        print(f"[COLLECTOR] Backfill error: {e}")
    print("[COLLECTOR] Backfill complete")


# ── Main ─────────────────────────────────────────────────────────────

async def main():
    global pool

    print("[COLLECTOR] Starting data collector daemon...")

    # Init DB
    pool = await create_pool()
    await init_schema(pool)

    # Check if we need backfill (no data yet)
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM funding_rates")
    if count == 0:
        await job_backfill()

    # Run once at startup
    for fn in [job_funding, job_open_interest, job_liquidations, job_snapshot]:
        try:
            await fn()
        except Exception as e:
            print(f"[COLLECTOR] Startup {fn.__name__} failed: {e}")

    # Schedule recurring jobs
    scheduler = AsyncIOScheduler()
    scheduler.add_job(job_funding, "interval", seconds=INTERVAL_FUNDING,
                      id="funding", name="Funding rates")
    scheduler.add_job(job_open_interest, "interval", seconds=INTERVAL_OI,
                      id="oi", name="Open Interest")
    scheduler.add_job(job_liquidations, "interval", seconds=INTERVAL_LIQUIDATIONS,
                      id="liquidations", name="Liquidations")
    scheduler.add_job(job_snapshot, "interval", seconds=INTERVAL_SNAPSHOT,
                      id="snapshot", name="Market Snapshot")
    scheduler.add_job(job_ohlcv_backup, CronTrigger(hour=OHLCV_BACKUP_HOUR),
                      id="ohlcv", name="OHLCV Backup")
    scheduler.start()

    print("[COLLECTOR] Scheduler running. Jobs:")
    for job in scheduler.get_jobs():
        print(f"  - {job.name}: next run {job.next_run_time}")

    # Keep alive until signal
    stop = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass  # Windows

    await stop.wait()
    scheduler.shutdown()
    await pool.close()
    print("[COLLECTOR] Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
