"""PostgreSQL connection and insert helpers using asyncpg."""
import asyncpg
from pathlib import Path
from ..config import DATABASE_URL


async def create_pool() -> asyncpg.Pool:
    """Create connection pool to Railway PostgreSQL."""
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    print(f"[DB] Pool created ({DATABASE_URL[:30]}...)")
    return pool


async def init_schema(pool: asyncpg.Pool):
    """Run schema.sql to create tables if they don't exist."""
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text()
    # Strip SQL comments before execution
    lines = [l for l in sql.splitlines() if not l.strip().startswith("--")]
    clean_sql = "\n".join(lines)
    async with pool.acquire() as conn:
        for stmt in clean_sql.split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    await conn.execute(stmt)
                except Exception as e:
                    print(f"[DB] Statement warning: {e}")
    print("[DB] Schema initialized")


async def insert_funding(pool: asyncpg.Pool, rows: list[tuple]) -> int:
    """Bulk insert funding rates. Returns count inserted."""
    if not rows:
        return 0
    async with pool.acquire() as conn:
        result = await conn.executemany("""
            INSERT INTO funding_rates (timestamp, exchange, symbol,
                funding_rate, funding_apy, predicted_rate, mark_price, index_price)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            ON CONFLICT (timestamp, exchange, symbol) DO NOTHING
        """, rows)
    return len(rows)


async def insert_open_interest(pool: asyncpg.Pool, rows: list[tuple]) -> int:
    if not rows:
        return 0
    async with pool.acquire() as conn:
        await conn.executemany("""
            INSERT INTO open_interest (timestamp, exchange, symbol, oi_contracts, oi_usd)
            VALUES ($1,$2,$3,$4,$5)
            ON CONFLICT (timestamp, exchange, symbol) DO NOTHING
        """, rows)
    return len(rows)


async def insert_liquidations(pool: asyncpg.Pool, rows: list[tuple]) -> int:
    if not rows:
        return 0
    async with pool.acquire() as conn:
        await conn.executemany("""
            INSERT INTO liquidations (timestamp, exchange, symbol, side,
                quantity, usd_value, price)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT (timestamp, exchange, symbol, side) DO NOTHING
        """, rows)
    return len(rows)


async def insert_ohlcv(pool: asyncpg.Pool, rows: list[tuple]) -> int:
    if not rows:
        return 0
    async with pool.acquire() as conn:
        await conn.executemany("""
            INSERT INTO ohlcv (timestamp, exchange, symbol, timeframe,
                open, high, low, close, volume)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (timestamp, exchange, symbol, timeframe) DO NOTHING
        """, rows)
    return len(rows)


async def insert_snapshot(pool: asyncpg.Pool, row: tuple) -> int:
    if not row:
        return 0
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO market_snapshots (timestamp, total_oi_usd, total_volume_24h,
                btc_dominance, funding_weighted_avg, fear_greed_index,
                num_coins_negative_funding, num_coins_positive_funding)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            ON CONFLICT (timestamp) DO NOTHING
        """, *row)
    return 1


async def get_latest_timestamp(pool: asyncpg.Pool, table: str, exchange: str, symbol: str = None):
    """Get the most recent timestamp for a table+exchange+symbol combo."""
    async with pool.acquire() as conn:
        if symbol:
            row = await conn.fetchrow(
                f"SELECT MAX(timestamp) as ts FROM {table} WHERE exchange=$1 AND symbol=$2",
                exchange, symbol)
        else:
            row = await conn.fetchrow(
                f"SELECT MAX(timestamp) as ts FROM {table} WHERE exchange=$1", exchange)
        return row['ts'] if row and row['ts'] else None
