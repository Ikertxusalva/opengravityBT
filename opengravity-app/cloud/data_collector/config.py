"""Data Collector configuration — symbols, URLs, intervals."""
import os

# Database
DATABASE_URL = os.environ.get("DATABASE_URL", "")
# Railway uses postgresql:// but asyncpg expects postgresql:// (not +psycopg2)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# API endpoints (all public, no keys needed)
HL_API = "https://api.hyperliquid.xyz/info"
BINANCE_API = "https://fapi.binance.com"
BYBIT_API = "https://api.bybit.com"

# Symbol tiers
TIER1 = ["BTC", "ETH"]
TIER2 = ["SOL", "BNB", "DOGE", "AVAX", "ADA", "LINK", "ARB"]
TIER3 = ["OP", "INJ", "TIA", "SEI", "SUI", "NEAR", "PEPE", "WIF"]
ALL_SYMBOLS = TIER1 + TIER2
ALL_WITH_TIER3 = ALL_SYMBOLS + TIER3

# Symbol mapping per exchange
def bn_symbol(sym: str) -> str:
    return f"{sym}USDT"

def bybit_symbol(sym: str) -> str:
    return f"{sym}USDT"

# Schedule intervals (seconds)
INTERVAL_FUNDING = 3600        # 1 hour
INTERVAL_OI = 14400            # 4 hours
INTERVAL_LIQUIDATIONS = 300    # 5 minutes
INTERVAL_SNAPSHOT = 3600       # 1 hour
OHLCV_BACKUP_HOUR = 1         # Run at 01:00 UTC daily

# Rate limiting (requests per second)
BINANCE_RPS = 10    # Conservative (limit is 1200/min)
BYBIT_RPS = 2       # Conservative (limit is 120/min)
HL_RPS = 5          # Not documented, be conservative

# Backfill on first deploy
BACKFILL_DAYS_FUNDING = 333    # Binance allows ~1000 records = 333 days
BACKFILL_DAYS_OI = 30          # OI history is limited
