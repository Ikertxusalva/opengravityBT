"""OpenGravity Cloud Backend — FastAPI + PostgreSQL + WebSocket."""
import os
import sys
import json
import glob as glob_module
from datetime import datetime
from contextlib import asynccontextmanager

# Allow importing src/rbi modules if they exist (local dev or Docker with full repo)
_rbi_path = os.path.join(os.path.dirname(__file__), "..", "..")
if os.path.isdir(os.path.join(_rbi_path, "src", "rbi")):
    sys.path.insert(0, os.path.abspath(_rbi_path))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Text, BigInteger
from sqlalchemy.orm import sessionmaker, declarative_base
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import httpx
import re
import time
import secrets
from collections import defaultdict
import asyncio
import concurrent.futures as _cf

# ── Database Setup ──
# ── Database Setup ──
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./dev.db")

# Railway Postgres uses postgresql:// but SQLAlchemy needs postgresql+psycopg2://
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

try:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine)
    Base = declarative_base()
except Exception as e:
    print(f"❌ Error setting up database: {e}")
    # Fallback to sqlite if postgres fails (optional, but prevents crash)
    DATABASE_URL = "sqlite:///./dev.db"
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    Base = declarative_base()


# ── Database Models ──

class Candle(Base):
    """OHLCV candle data from exchanges."""
    __tablename__ = "candles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)       # e.g. BTCUSDT
    exchange = Column(String(20), nullable=False, default="binance")
    timeframe = Column(String(10), nullable=False, default="1h")   # 1m, 5m, 1h, 4h, 1d
    timestamp = Column(BigInteger, nullable=False, index=True)     # Unix ms
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)


class AgentLog(Base):
    """Logs from agent actions and decisions."""
    __tablename__ = "agent_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String(50), nullable=False, index=True)
    action = Column(String(50), nullable=False)                   # e.g. "ANALYSIS", "TRADE", "ALERT"
    symbol = Column(String(20))
    decision = Column(String(20))                                  # LONG, SHORT, NO_TRADE, HOLD
    confidence = Column(Float)
    reasoning = Column(Text)
    data = Column(Text)                                            # JSON blob
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class StrategyResult(Base):
    """Results from backtesting runs."""
    __tablename__ = "strategy_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_name = Column(String(50), nullable=False, index=True)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    return_pct = Column(Float)
    sharpe_ratio = Column(Float)
    max_drawdown = Column(Float)
    win_rate = Column(Float)
    total_trades = Column(Integer)
    profit_factor = Column(Float)
    parameters = Column(Text)                                      # JSON
    verdict = Column(String(20))                                   # APPROVED, CAUTION, REJECTED
    created_at = Column(DateTime, default=datetime.utcnow)


class SwarmDecision(Base):
    """Swarm consensus decisions from multi-agent voting."""
    __tablename__ = "swarm_decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow = Column(String(50))                                   # market_analysis, rbi_pipeline, etc.
    symbol = Column(String(20))
    decision = Column(String(20), nullable=False)                  # BUY, SELL, HOLD, ESCALATE
    consensus_score = Column(Float)                                 # -1.0 to 1.0
    confidence_avg = Column(Float)                                  # 0-100
    votes = Column(Text)                                            # JSON: {agent_id: {vote, confidence, reasoning}}
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class AgentContext(Base):
    """Persistent conversational context for agent sessions across restarts."""
    __tablename__ = "agent_contexts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String(50), nullable=False, unique=True, index=True)
    context_summary = Column(Text)                                 # Last session output (ANSI-stripped)
    updated_at = Column(DateTime, default=datetime.utcnow)


class AgentMemoryEntry(Base):
    """Structured agent memories (semantic, episodic, procedural, working)."""
    __tablename__ = "agent_memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    memory_id = Column(String(50), nullable=False, unique=True, index=True)  # mem-xxxx client ID
    agent_id = Column(String(50), nullable=False, index=True)
    type = Column(String(20), nullable=False)                      # semantic, episodic, procedural, working
    scope = Column(String(20), default="private")                  # private, shared
    content = Column(Text, nullable=False)
    context = Column(Text, default="")
    tags = Column(Text, default="[]")                              # JSON array
    importance = Column(Float, default=0.5)
    access_count = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class FundingRate(Base):
    """Historical funding rates from HyperLiquid stored in Railway Postgres."""
    __tablename__ = "funding_rates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    coin = Column(String(20), nullable=False, index=True)
    timestamp = Column(BigInteger, nullable=False, index=True)
    rate_8h_pct = Column(Float)
    annual_pct = Column(Float)
    open_interest = Column(Float)
    mark_px = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)


class LiquidationEvent(Base):
    """Liquidation events from HyperLiquid, stored for historical analysis."""
    __tablename__ = "liquidation_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    coin = Column(String(20), nullable=False, index=True)
    side = Column(String(10))           # LONG or SHORT
    usd_size = Column(Float)
    px = Column(String(30))
    sz = Column(String(30))
    tid = Column(BigInteger, index=True)   # trade id from HL for deduplication
    time_ms = Column(BigInteger, nullable=False, index=True)
    leverage = Column(Float, nullable=True)           # Real leverage from clearinghouseState
    liq_px = Column(String(30), nullable=True)        # Liquidation price
    entry_px = Column(String(30), nullable=True)      # Entry price of liquidated position
    margin_used = Column(String(30), nullable=True)   # Margin used
    created_at = Column(DateTime, default=datetime.utcnow)


# Create tables
try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"❌ Error creating tables: {e}")


# ── WebSocket Connection Manager ──

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, message: dict):
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()


# ── Security Infrastructure ──
API_TOKEN = os.environ.get("OPENGRAVITY_API_TOKEN")

# Rate limiter
MAX_REQUESTS_PER_MINUTE = 60
_rate_limits = defaultdict(list)

def _check_rate_limit(client_ip: str) -> bool:
    now = time.time()
    window = _rate_limits[client_ip]
    _rate_limits[client_ip] = [t for t in window if now - t < 60]
    if len(_rate_limits[client_ip]) >= MAX_REQUESTS_PER_MINUTE:
        return False
    _rate_limits[client_ip].append(now)
    return True

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        if not _check_rate_limit(client_ip):
            return JSONResponse(status_code=429, content={"detail": "Too many requests"})
        
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store"
        return response

def verify_token(authorization: str = Header(None)):
    if not API_TOKEN:
        # In development, if no token is set, we might allow access,
        # but in production, this is a CRITICAL configuration error.
        return

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = authorization.replace("Bearer ", "")
    if not secrets.compare_digest(token, API_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid API Token")


_AGENT_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')

def validate_agent_id(agent_id: str) -> str:
    """Validates agent_id format to prevent path traversal or injection attempts."""
    if not _AGENT_ID_PATTERN.match(agent_id):
        raise HTTPException(status_code=400, detail="Invalid agent_id format")
    return agent_id


# ── Scheduler for data ingestion ──

scheduler = AsyncIOScheduler()
_stress_cache: dict[str, float] = {}  # coin -> last_triggered_ts
_last_stress_rankings: list = []  # cached for REST endpoint
_last_funding_rates: dict = {}  # cached for REST endpoint
_last_liquidations: list = []  # cached for REST endpoint
_last_whale_data: dict = {"longs": [], "shorts": []}  # cached for REST endpoint


async def fetch_prices():
    """Fetch latest prices from Binance and broadcast to connected clients."""
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    async with httpx.AsyncClient() as client:
        for symbol in symbols:
            try:
                resp = await client.get(
                    f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
                    timeout=5.0,
                )
                data = resp.json()
                await manager.broadcast({
                    "type": "price_update",
                    "symbol": data["symbol"],
                    "price": float(data["price"]),
                    "timestamp": datetime.utcnow().isoformat(),
                })
            except Exception:
                pass


async def fetch_candles():
    """Fetch and store 1h candles for tracked symbols."""
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    async with httpx.AsyncClient() as client:
        db = SessionLocal()
        try:
            for symbol in symbols:
                try:
                    resp = await client.get(
                        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=5",
                        timeout=10.0,
                    )
                    klines = resp.json()
                    for k in klines:
                        existing = db.query(Candle).filter(Candle.symbol == symbol, Candle.timestamp == k[0]).first()
                        if not existing:
                            candle = Candle(
                                symbol=symbol, exchange="binance", timeframe="1h",
                                timestamp=k[0], open=float(k[1]), high=float(k[2]),
                                low=float(k[3]), close=float(k[4]), volume=float(k[5]),
                            )
                            db.add(candle)
                    db.commit()
                except Exception:
                    db.rollback()
        finally:
            db.close()


async def fetch_fear_greed():
    """Fetch Fear & Greed index and broadcast to connected clients."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get("https://api.alternative.me/fng/?limit=1", timeout=8.0)
            data = resp.json()["data"][0]
            await manager.broadcast({
                "type": "fear_greed",
                "value": int(data["value"]),
                "classification": data["value_classification"],
                "timestamp": datetime.utcnow().isoformat(),
            })
        except Exception as e:
            print(f"[fear_greed] Error: {e}")


async def fetch_top_movers():
    """Fetch top gainers/losers from CoinGecko (no API key needed) and broadcast."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/coins/markets"
                "?vs_currency=usd&order=percent_change_24h_desc&per_page=20&page=1"
                "&price_change_percentage=24h&sparkline=false",
                timeout=10.0,
                headers={"Accept": "application/json"},
            )
            coins = resp.json()
            gainers = sorted(
                [c for c in coins if isinstance(c.get("price_change_percentage_24h"), float)],
                key=lambda x: x["price_change_percentage_24h"],
                reverse=True,
            )[:5]
            losers = sorted(
                [c for c in coins if isinstance(c.get("price_change_percentage_24h"), float)],
                key=lambda x: x["price_change_percentage_24h"],
            )[:5]
            await manager.broadcast({
                "type": "top_movers",
                "gainers": [
                    {"symbol": c["symbol"].upper(), "change_24h": round(c["price_change_percentage_24h"], 2)}
                    for c in gainers
                ],
                "losers": [
                    {"symbol": c["symbol"].upper(), "change_24h": round(c["price_change_percentage_24h"], 2)}
                    for c in losers
                ],
                "timestamp": datetime.utcnow().isoformat(),
            })
        except Exception as e:
            print(f"[top_movers] Error: {e}")


HL_BASE = "https://api.hyperliquid.xyz/info"
# Core coins for stress index and whale tracking (expanded)
HL_WATCH = ["BTC", "ETH", "SOL", "DOGE", "XRP", "AVAX", "LINK", "ARB", "OP", "INJ", "WIF", "PEPE", "HYPE", "BNB", "SUI", "APT", "TIA", "SEI", "TON", "ADA"]
# Dynamic list populated at startup with ALL HL assets
_hl_all_coins: list[str] = []


async def fetch_funding_rates():
    """Fetch funding rates from HyperLiquid for ALL assets and broadcast."""
    global _hl_all_coins
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(HL_BASE, json={"type": "metaAndAssetCtxs"}, timeout=10.0)
            result = resp.json()
            if isinstance(result, list) and len(result) == 2:
                universe, ctxs = result[0].get("universe", []), result[1]
                rates = {}
                carry_ops = []
                db_data: list[dict] = []
                all_coins: list[str] = []
                now_ms = int(time.time() * 1000)
                for i, asset in enumerate(universe):
                    if i >= len(ctxs):
                        break
                    name = asset.get("name", "")
                    if not name:
                        continue
                    all_coins.append(name)
                    ctx = ctxs[i]
                    funding = float(ctx.get("funding", 0) or 0)
                    annual = round(funding * 24 * 365 * 100, 2)
                    rates[name] = {"h8_pct": round(funding * 100, 4), "annual_pct": annual}
                    if abs(annual) > 20:
                        carry_ops.append({"coin": name, "annual_pct": annual})
                    # Persist HL_WATCH coins to DB
                    if name in HL_WATCH:
                        db_data.append({
                            "coin": name, "timestamp": now_ms,
                            "rate_8h_pct": round(funding * 100, 6),
                            "annual_pct": annual,
                            "open_interest": float(ctx["openInterest"]) if ctx.get("openInterest") else None,
                            "mark_px": float(ctx["markPx"]) if ctx.get("markPx") else None,
                        })
                # Update dynamic coin list
                if all_coins:
                    _hl_all_coins = all_coins
                carry_ops.sort(key=lambda x: abs(x["annual_pct"]), reverse=True)
                global _last_funding_rates
                # Send ALL funding rates (not just HL_WATCH)
                _last_funding_rates = rates
                await manager.broadcast({
                    "type": "funding_update",
                    "rates": rates,
                    "carry_opportunities": carry_ops[:10],
                    "timestamp": datetime.utcnow().isoformat(),
                })
                # Persist to DB
                if db_data:
                    _db = SessionLocal()
                    try:
                        for d in db_data:
                            _db.add(FundingRate(**d))
                        _db.commit()
                    except Exception as _db_err:
                        _db.rollback()
                        print(f"[funding_rates] DB error: {_db_err}")
                    finally:
                        _db.close()
        except Exception as e:
            print(f"[funding_rates] Error: {e}")


async def fetch_hl_prices():
    """Fetch mid prices from HyperLiquid and broadcast (fallback polling, se usa si el WS nativo falla)."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(HL_BASE, json={"type": "allMids"}, timeout=8.0)
            data = resp.json()
            if isinstance(data, dict):
                prices = {k: float(v) for k, v in data.items() if k in HL_WATCH and v}
                await manager.broadcast({
                    "type": "hl_prices",
                    "prices": prices,
                    "timestamp": datetime.utcnow().isoformat(),
                })
        except Exception as e:
            print(f"[hl_prices] Error: {e}")


HL_LIQ_COINS = ["BTC", "ETH"]  # Real-time liquidation tracking for these

# Minimum notional for liquidation to be relevant (filters dust)
# HyperLiquid perps only — all liquidations here are leveraged positions.
MIN_LIQ_NOTIONAL = 5_000
MIN_LIQ_LEVERAGE = 10  # Only show x10+ leverage liquidations

# Cache: user address → clearinghouseState (TTL 30s to avoid spamming the API)
_user_state_cache: dict[str, tuple[float, dict]] = {}
_USER_STATE_TTL = 30

async def _get_user_leverage(user_address: str, coin: str) -> dict | None:
    """Query HL clearinghouseState to get real leverage data for a liquidated user."""
    now = time.time()
    cached = _user_state_cache.get(user_address)
    if cached and (now - cached[0]) < _USER_STATE_TTL:
        state = cached[1]
    else:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(HL_BASE, json={
                    "type": "clearinghouseState", "user": user_address,
                }, timeout=5.0)
                state = resp.json()
                _user_state_cache[user_address] = (now, state)
                # Prune cache (keep max 200 entries)
                if len(_user_state_cache) > 200:
                    oldest = sorted(_user_state_cache, key=lambda k: _user_state_cache[k][0])
                    for k in oldest[:50]:
                        del _user_state_cache[k]
        except Exception:
            return None

    # Find the position for this coin
    positions = state.get("assetPositions", [])
    for pos_wrapper in positions:
        pos = pos_wrapper.get("position", pos_wrapper)
        if pos.get("coin") == coin:
            try:
                leverage_data = pos.get("leverage", {})
                lev_value = float(leverage_data.get("value", 0)) if isinstance(leverage_data, dict) else float(leverage_data or 0)
                return {
                    "leverage": round(lev_value, 1),
                    "liquidation_px": pos.get("liquidationPx"),
                    "entry_px": pos.get("entryPx"),
                    "margin_used": pos.get("marginUsed"),
                    "position_value": pos.get("positionValue"),
                    "unrealized_pnl": pos.get("unrealizedPnl"),
                    "return_on_equity": pos.get("returnOnEquity"),
                }
            except Exception:
                return None

    # Position already closed (fully liquidated) — estimate from margin summary
    margin = state.get("marginSummary", {})
    try:
        account_value = float(margin.get("accountValue", 0))
        total_ntl = float(margin.get("totalNtlPos", 0))
        if account_value > 0 and total_ntl > 0:
            return {"leverage": round(total_ntl / account_value, 1)}
    except Exception:
        pass
    return None


async def fetch_liquidations():
    """Fetch recent liquidation trades from HyperLiquid perpetuals.

    System trades (hash = 0x000...0) are liquidations/ADL on perps.
    Queries clearinghouseState for real leverage data. Filters x10+.
    """
    all_liqs: list[dict] = []
    # Check BTC and ETH + top stressed coins
    coins_to_check = list(HL_LIQ_COINS)
    for item in _last_stress_rankings[:5]:
        if item["coin"] not in coins_to_check:
            coins_to_check.append(item["coin"])

    async with httpx.AsyncClient() as client:
        for coin in coins_to_check:
            try:
                resp = await client.post(HL_BASE, json={"type": "recentTrades", "coin": coin}, timeout=8.0)
                trades = resp.json()
                if not isinstance(trades, list):
                    continue
                for t in trades:
                    h = t.get("hash", "")
                    is_system = h == "0x0000000000000000000000000000000000000000000000000000000000000000"
                    if not is_system:
                        continue
                    side = "LONG" if t.get("side") == "A" else "SHORT"
                    try:
                        px = float(t.get("px", 0))
                        sz = float(t.get("sz", 0))
                        usd_size = px * sz
                    except (TypeError, ValueError):
                        continue
                    if usd_size < MIN_LIQ_NOTIONAL:
                        continue

                    # Get liquidated user and query real leverage
                    users = t.get("users", [])
                    liq_user = None
                    if len(users) >= 2:
                        liq_user = users[0] if t.get("side") == "A" else users[1]

                    leverage = None
                    liq_px = None
                    entry_px = None
                    margin_used = None
                    if liq_user:
                        try:
                            lev_data = await _get_user_leverage(liq_user, coin)
                            if lev_data:
                                leverage = lev_data.get("leverage")
                                liq_px = lev_data.get("liquidation_px")
                                entry_px = lev_data.get("entry_px")
                                margin_used = lev_data.get("margin_used")
                        except Exception:
                            pass

                    if leverage is not None and leverage < MIN_LIQ_LEVERAGE:
                        continue

                    liq_entry = {
                        "coin": coin,
                        "side": side,
                        "usd_size": round(usd_size, 2),
                        "px": t.get("px", "0"),
                        "sz": t.get("sz", "0"),
                        "tid": t.get("tid", 0),
                        "time_ms": t.get("time", 0),
                    }
                    if leverage is not None:
                        liq_entry["leverage"] = leverage
                    if liq_px is not None:
                        liq_entry["liq_px"] = liq_px
                    if entry_px is not None:
                        liq_entry["entry_px"] = entry_px
                    if margin_used is not None:
                        liq_entry["margin_used"] = margin_used
                    all_liqs.append(liq_entry)
            except Exception:
                pass

    if not all_liqs:
        # Still broadcast empty to clear stale data
        global _last_liquidations
        _last_liquidations = []
        await manager.broadcast({
            "type": "liquidation_update",
            "liquidations": [],
            "count": 0,
            "timestamp": datetime.utcnow().isoformat(),
        })
        return

    all_liqs.sort(key=lambda x: x["time_ms"], reverse=True)

    # Persist new liquidations to DB
    db = SessionLocal()
    try:
        new_count = 0
        for liq in all_liqs[:30]:
            tid = liq.get("tid") or 0
            existing = (
                db.query(LiquidationEvent)
                .filter(LiquidationEvent.tid == tid, LiquidationEvent.coin == liq["coin"])
                .first()
            ) if tid else None
            if not existing:
                db.add(LiquidationEvent(
                    coin=liq["coin"], side=liq["side"], usd_size=liq["usd_size"],
                    px=liq["px"], sz=liq["sz"], tid=tid, time_ms=liq["time_ms"],
                    leverage=liq.get("leverage"), liq_px=liq.get("liq_px"),
                    entry_px=liq.get("entry_px"), margin_used=liq.get("margin_used"),
                ))
                new_count += 1
        if new_count:
            db.commit()
            print(f"[liquidations] Stored {new_count} new events")
    except Exception:
        db.rollback()
    finally:
        db.close()

    _last_liquidations = all_liqs[:20]
    await manager.broadcast({
        "type": "liquidation_update",
        "liquidations": _last_liquidations,
        "count": len(all_liqs),
        "timestamp": datetime.utcnow().isoformat(),
    })


def _fetch_whale_positions_sync() -> dict:
    """Sync: fetches top leveraged positions from HL leaderboard (runs in executor)."""
    base = "https://api.hyperliquid.xyz/info"
    hdrs = {"Content-Type": "application/json"}

    # Mark prices
    try:
        r = httpx.post(base, json={"type": "metaAndAssetCtxs"}, headers=hdrs, timeout=12)
        result = r.json()
        universe = result[0].get("universe", [])
        ctxs = result[1]
        mark_prices: dict[str, float] = {}
        for i, m in enumerate(universe):
            nm = m.get("name", "")
            if i < len(ctxs) and ctxs[i].get("markPx"):
                try:
                    mark_prices[nm] = float(ctxs[i]["markPx"])
                except (TypeError, ValueError):
                    pass
    except Exception as e:
        print(f"[whale_sync] mark_prices error: {e}")
        return {"longs": [], "shorts": []}

    # Leaderboard
    try:
        r = httpx.post(base, json={"type": "leaderboard"}, headers=hdrs, timeout=12)
        rows = r.json().get("leaderboardRows", [])
        rows = sorted(rows, key=lambda x: float(x.get("accountValue", 0) or 0), reverse=True)
        addresses = [row["ethAddress"] for row in rows[:20] if row.get("ethAddress")]
    except Exception as e:
        print(f"[whale_sync] leaderboard error: {e}")
        return {"longs": [], "shorts": []}

    def _get_pos(addr: str) -> list[dict]:
        try:
            r = httpx.post(base, json={"type": "clearinghouseState", "user": addr}, headers=hdrs, timeout=8)
            data = r.json()
            positions = []
            for ap in data.get("assetPositions", []):
                pos = ap.get("position", {})
                try:
                    szi = float(pos.get("szi", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if szi == 0:
                    continue
                coin = pos.get("coin", "")
                mark = mark_prices.get(coin, 0)
                if not mark:
                    continue
                size_usd = abs(szi) * mark
                if size_usd < 50_000:
                    continue
                lev_obj = pos.get("leverage", {}) or {}
                try:
                    lev = float(lev_obj.get("value", 1) or 1)
                except (TypeError, ValueError):
                    lev = 1.0
                if lev < 5:
                    continue
                liq_raw = pos.get("liquidationPx")
                liq_px = float(liq_raw) if liq_raw else None
                side = "LONG" if szi > 0 else "SHORT"
                dist_pct: float | None = None
                if liq_px and mark:
                    dist_pct = ((mark - liq_px) / mark * 100) if side == "LONG" else ((liq_px - mark) / mark * 100)
                danger = (size_usd * lev / max(abs(dist_pct), 0.1)) if dist_pct else size_usd * lev
                try:
                    entry_px = float(pos.get("entryPx") or 0)
                except (TypeError, ValueError):
                    entry_px = 0.0
                positions.append({
                    "coin": coin, "side": side,
                    "size_usd": round(size_usd, 0),
                    "leverage": round(lev, 1),
                    "entry_px": entry_px,
                    "liq_px": liq_px,
                    "mark_px": mark,
                    "dist_pct": round(dist_pct, 2) if dist_pct else None,
                    "danger_score": round(danger, 0),
                    "trader": addr[:8] + "...",
                })
            return positions
        except Exception:
            return []

    all_positions: list[dict] = []
    with _cf.ThreadPoolExecutor(max_workers=5) as executor:
        for result_list in executor.map(_get_pos, addresses):
            all_positions.extend(result_list)

    longs = sorted([p for p in all_positions if p["side"] == "LONG"],
                   key=lambda x: x["danger_score"], reverse=True)[:10]
    shorts = sorted([p for p in all_positions if p["side"] == "SHORT"],
                    key=lambda x: x["danger_score"], reverse=True)[:10]
    return {"longs": longs, "shorts": shorts}


async def fetch_whale_positions():
    """Run whale position fetch in executor (heavy sync task) and broadcast."""
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, _fetch_whale_positions_sync)
        if result.get("longs") or result.get("shorts"):
            global _last_whale_data
            _last_whale_data = {"longs": result["longs"], "shorts": result["shorts"]}
            await manager.broadcast({
                "type": "whale_update",
                "longs": result["longs"],
                "shorts": result["shorts"],
                "timestamp": datetime.utcnow().isoformat(),
            })
    except Exception as e:
        print(f"[whale_positions] Error: {e}")


async def fetch_binance_funding():
    """Fetch funding rates from Binance perpetuals for cross-exchange validation."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                "https://fapi.binance.com/fapi/v1/premiumIndex",
                timeout=10.0,
            )
            data = resp.json()
            if not isinstance(data, list):
                return
            rates: dict[str, dict] = {}
            for item in data:
                symbol = item.get("symbol", "")
                coin = symbol.replace("USDT", "").replace("BUSD", "")
                if coin not in HL_WATCH:
                    continue
                try:
                    fr = float(item.get("lastFundingRate", 0) or 0)
                    rates[coin] = {
                        "funding_8h_pct": round(fr * 100, 4),
                        "annual_pct": round(fr * 24 * 365 * 100, 2),
                        "mark_price": float(item.get("markPrice", 0) or 0),
                    }
                except (TypeError, ValueError):
                    pass
            if rates:
                await manager.broadcast({
                    "type": "binance_funding",
                    "rates": rates,
                    "timestamp": datetime.utcnow().isoformat(),
                })
        except Exception as e:
            print(f"[binance_funding] Error: {e}")


async def compute_stress_index():
    """
    Compute Market Stress Index per coin combining:
    - Funding rate extremes from HL (stored in DB)
    - Recent liquidation volume (last 30 min from DB)
    Broadcasts stress_update and auto-fires SwarmDecision when score >= 60.
    """
    from sqlalchemy import func as sqlfunc
    db = SessionLocal()
    try:
        now_ms = int(time.time() * 1000)
        thirty_min_ago = now_ms - 30 * 60 * 1000

        # Latest funding rate per coin — use ALL coins from universe
        coins_to_check = _hl_all_coins if _hl_all_coins else HL_WATCH
        latest_rates: dict[str, object] = {}
        for coin in coins_to_check:
            fr = (
                db.query(FundingRate)
                .filter(FundingRate.coin == coin)
                .order_by(FundingRate.timestamp.desc())
                .first()
            )
            if fr:
                latest_rates[coin] = fr

        # Recent liquidations aggregated by coin + side
        liq_rows = (
            db.query(
                LiquidationEvent.coin,
                LiquidationEvent.side,
                sqlfunc.sum(LiquidationEvent.usd_size).label("total_usd"),
            )
            .filter(LiquidationEvent.time_ms > thirty_min_ago)
            .group_by(LiquidationEvent.coin, LiquidationEvent.side)
            .all()
        )
        liq_by_coin: dict[str, dict] = {}
        for row in liq_rows:
            if row.coin not in liq_by_coin:
                liq_by_coin[row.coin] = {"LONG": 0.0, "SHORT": 0.0}
            liq_by_coin[row.coin][row.side] = float(row.total_usd or 0)

        stress_results = []
        swarm_triggers = []

        for coin in coins_to_check:
            fr = latest_rates.get(coin)
            if not fr:
                continue
            annual = getattr(fr, "annual_pct", None) or 0.0
            score = 0.0
            signals: list[str] = []

            # Funding component (0–40 pts)
            abs_annual = abs(annual)
            if abs_annual > 200:
                score += 40; signals.append(f"EXTREME_FUNDING:{annual:.0f}%APY")
            elif abs_annual > 100:
                score += 30; signals.append(f"HIGH_FUNDING:{annual:.0f}%APY")
            elif abs_annual > 50:
                score += 20; signals.append(f"ELEVATED_FUNDING:{annual:.0f}%APY")
            elif abs_annual > 20:
                score += 10; signals.append(f"MODERATE_FUNDING:{annual:.0f}%APY")

            direction = "SHORT_BIAS" if annual < 0 else "LONG_BIAS"

            # Liquidation component (0–40 pts)
            liqs = liq_by_coin.get(coin, {})
            long_liqs = liqs.get("LONG", 0.0)
            short_liqs = liqs.get("SHORT", 0.0)
            total_liqs = long_liqs + short_liqs
            if total_liqs > 5_000_000:
                score += 40; signals.append(f"MASSIVE_LIQS:${total_liqs/1e6:.1f}M")
            elif total_liqs > 1_000_000:
                score += 25; signals.append(f"HIGH_LIQS:${total_liqs/1e6:.1f}M")
            elif total_liqs > 100_000:
                score += 10; signals.append(f"LIQS:${total_liqs/1e3:.0f}K")

            # Confluence bonus (0–20 pts)
            if annual < -20 and long_liqs > short_liqs and long_liqs > 100_000:
                score += 20; signals.append("CAPITULATION"); direction = "CAPITULATION_SIGNAL"
            elif annual > 20 and short_liqs > long_liqs and short_liqs > 100_000:
                score += 20; signals.append("SHORT_SQUEEZE"); direction = "SHORT_SQUEEZE_SIGNAL"

            score = round(min(score, 100.0), 1)
            stress_results.append({
                "coin": coin, "score": score,
                "annual_funding_pct": round(annual, 2),
                "direction": direction,
                "long_liqs_usd": round(long_liqs, 0),
                "short_liqs_usd": round(short_liqs, 0),
                "signals": signals,
            })

            # Queue SwarmDecision for extreme scores, max once/hour per coin
            if score >= 60 and time.time() - _stress_cache.get(coin, 0) >= 3600:
                swarm_triggers.append({"coin": coin, "score": score, "signals": signals, "direction": direction})

        stress_results.sort(key=lambda x: x["score"], reverse=True)

        global _last_stress_rankings
        _last_stress_rankings = stress_results[:30]

        await manager.broadcast({
            "type": "stress_update",
            "rankings": stress_results[:30],
            "timestamp": datetime.utcnow().isoformat(),
        })

        # Emit SwarmDecisions for extreme events
        for trigger in swarm_triggers:
            coin = trigger["coin"]
            score = trigger["score"]
            direction = trigger["direction"]
            has_cap = "CAPITULATION" in trigger["signals"]
            has_squeeze = "SHORT_SQUEEZE" in trigger["signals"]
            decision = "BUY" if has_cap else ("SELL" if has_squeeze else "ESCALATE")
            consensus = round(min(score / 100, 0.95), 3)
            _stress_cache[coin] = time.time()
            db.add(SwarmDecision(
                workflow="funding_stress",
                symbol=coin,
                decision=decision,
                consensus_score=consensus,
                confidence_avg=score,
                votes=json.dumps({
                    "funding_stress_agent": {
                        "vote": decision,
                        "confidence": score,
                        "reasoning": str(trigger["signals"]),
                    }
                }),
            ))
            await manager.broadcast({
                "type": "swarm_decision",
                "workflow": "funding_stress",
                "symbol": coin,
                "decision": decision,
                "consensus_score": consensus,
                "signals": trigger["signals"],
                "timestamp": datetime.utcnow().isoformat(),
            })

        if swarm_triggers:
            try:
                db.commit()
            except Exception:
                db.rollback()

    except Exception as e:
        print(f"[stress_index] Error: {e}")
    finally:
        db.close()


async def hl_websocket_client():
    """
    Cliente WebSocket nativo de HyperLiquid.
    Suscribe a allMids (precios) + trades BTC/ETH (liquidaciones en tiempo real).
    """
    import websockets

    uri = "wss://api.hyperliquid.xyz/ws"
    while True:
        try:
            async with websockets.connect(uri, ping_interval=20, ping_timeout=10) as ws:
                print("[HL WS] Connected to HyperLiquid WebSocket")
                # Subscribe to all mid prices
                await ws.send(json.dumps({
                    "method": "subscribe",
                    "subscription": {"type": "allMids"},
                }))
                # Subscribe to BTC and ETH trades for real-time liquidation detection
                for coin in HL_LIQ_COINS:
                    await ws.send(json.dumps({
                        "method": "subscribe",
                        "subscription": {"type": "trades", "coin": coin},
                    }))
                print(f"[HL WS] Subscribed to allMids + trades for {HL_LIQ_COINS}")

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        channel = msg.get("channel")

                        if channel == "allMids":
                            mids = msg.get("data", {}).get("mids", {})
                            prices = {k: float(v) for k, v in mids.items() if v}
                            if prices:
                                await manager.broadcast({
                                    "type": "hl_prices",
                                    "prices": prices,
                                    "timestamp": datetime.utcnow().isoformat(),
                                })

                        elif channel == "trades":
                            # Real-time liquidation detection from perpetual trade stream
                            trades_data = msg.get("data", [])
                            if not isinstance(trades_data, list):
                                continue
                            new_liqs = []
                            for t in trades_data:
                                h = t.get("hash", "")
                                is_system = h == "0x0000000000000000000000000000000000000000000000000000000000000000"
                                if not is_system:
                                    continue
                                coin = t.get("coin", "")
                                # Side: "A" = sell = LONG liquidated, "B" = buy = SHORT liquidated
                                side = "LONG" if t.get("side") == "A" else "SHORT"
                                try:
                                    px = float(t.get("px", 0))
                                    sz = float(t.get("sz", 0))
                                    usd_size = px * sz
                                except (TypeError, ValueError):
                                    continue
                                if usd_size < MIN_LIQ_NOTIONAL:
                                    continue

                                # Extract liquidated user address from trade
                                # In a system trade: side=A (sell) → seller is liquidated (LONG)
                                #                    side=B (buy)  → buyer is liquidated (SHORT)
                                users = t.get("users", [])
                                liq_user = None
                                if len(users) >= 2:
                                    liq_user = users[0] if t.get("side") == "A" else users[1]

                                # Query real leverage from clearinghouseState
                                leverage = None
                                liq_px = None
                                entry_px = None
                                margin_used = None
                                if liq_user:
                                    try:
                                        lev_data = await _get_user_leverage(liq_user, coin)
                                        if lev_data:
                                            leverage = lev_data.get("leverage")
                                            liq_px = lev_data.get("liquidation_px")
                                            entry_px = lev_data.get("entry_px")
                                            margin_used = lev_data.get("margin_used")
                                    except Exception:
                                        pass

                                # Filter: only x10+ leverage (if we got leverage data)
                                if leverage is not None and leverage < MIN_LIQ_LEVERAGE:
                                    continue

                                liq_entry = {
                                    "coin": coin, "side": side,
                                    "usd_size": round(usd_size, 2),
                                    "px": t.get("px", "0"), "sz": t.get("sz", "0"),
                                    "tid": t.get("tid", 0), "time_ms": t.get("time", 0),
                                }
                                if leverage is not None:
                                    liq_entry["leverage"] = leverage
                                if liq_px is not None:
                                    liq_entry["liq_px"] = liq_px
                                if entry_px is not None:
                                    liq_entry["entry_px"] = entry_px
                                if margin_used is not None:
                                    liq_entry["margin_used"] = margin_used
                                new_liqs.append(liq_entry)
                            if new_liqs:
                                global _last_liquidations
                                # Prepend new liquidations, keep max 30
                                _last_liquidations = (new_liqs + _last_liquidations)[:30]
                                await manager.broadcast({
                                    "type": "liquidation_update",
                                    "liquidations": _last_liquidations[:20],
                                    "count": len(_last_liquidations),
                                    "timestamp": datetime.utcnow().isoformat(),
                                })
                                # Persist to DB (fire and forget)
                                try:
                                    db = SessionLocal()
                                    for liq in new_liqs:
                                        db.add(LiquidationEvent(
                                            coin=liq["coin"], side=liq["side"], usd_size=liq["usd_size"],
                                            px=liq["px"], sz=liq["sz"], tid=liq["tid"], time_ms=liq["time_ms"],
                                            leverage=liq.get("leverage"), liq_px=liq.get("liq_px"),
                                            entry_px=liq.get("entry_px"), margin_used=liq.get("margin_used"),
                                        ))
                                    db.commit()
                                    db.close()
                                except Exception:
                                    pass
                    except Exception:
                        pass
        except Exception as e:
            print(f"[HL WS] Disconnected: {e!r} — reconnecting in 5s")
            await asyncio.sleep(5)


# ── FastAPI App ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: schedule jobs
    scheduler.add_job(fetch_prices, "interval", seconds=30)
    scheduler.add_job(fetch_candles, "interval", minutes=5)
    scheduler.add_job(fetch_fear_greed, "interval", minutes=30)
    scheduler.add_job(fetch_top_movers, "interval", minutes=15)
    scheduler.add_job(fetch_funding_rates, "interval", minutes=15)
    scheduler.add_job(fetch_hl_prices, "interval", minutes=2)       # fallback polling
    scheduler.add_job(fetch_liquidations, "interval", minutes=2)    # liquidaciones cada 2min
    scheduler.add_job(fetch_whale_positions, "interval", minutes=10) # ballenas cada 10min
    scheduler.add_job(fetch_binance_funding, "interval", minutes=30) # Binance cross-check
    scheduler.add_job(compute_stress_index, "interval", minutes=15)  # Stress Index
    scheduler.start()

    # Run once at startup — populate caches immediately
    for fn in [fetch_funding_rates, fetch_hl_prices, fetch_liquidations, fetch_binance_funding,
               fetch_fear_greed, fetch_top_movers]:
        try:
            await fn()
        except Exception as e:
            print(f"⚠️ Startup fetch {fn.__name__} failed: {e}")

    # Compute stress index at startup (needs funding data first)
    try:
        await compute_stress_index()
    except Exception as e:
        print(f"⚠️ Startup compute_stress_index failed: {e}")

    # Start HyperLiquid native WebSocket client (prices + liquidation tracking)
    hl_ws_task = asyncio.create_task(hl_websocket_client())

    # Start whale positions in background (heavy task)
    asyncio.create_task(fetch_whale_positions())

    yield

    # Shutdown
    hl_ws_task.cancel()
    try:
        await hl_ws_task
    except asyncio.CancelledError:
        pass
    scheduler.shutdown()

app = FastAPI(
    title="OpenGravity Cloud",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:8888",
    "http://127.0.0.1:8888",
    "app://.",            # Electron production origin
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


# ── REST Endpoints ──

@app.get("/")
async def root():
    return {"status": "alive", "service": "opengravity-cloud"}


@app.get("/health")
async def health():
    return {"status": "ok", "db": "connected", "agents": len(manager.active)}


@app.get("/api/prices/{symbol}", dependencies=[Depends(verify_token)])
async def get_price(symbol: str):
    """Get latest price from Binance."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}",
            timeout=5.0,
        )
        return resp.json()


@app.get("/api/candles/{symbol}", dependencies=[Depends(verify_token)])
async def get_candles(symbol: str, timeframe: str = "1h", limit: int = 100):
    """Get stored candles from database."""
    db = SessionLocal()
    try:
        candles = (
            db.query(Candle)
            .filter(Candle.symbol == symbol.upper(), Candle.timeframe == timeframe)
            .order_by(Candle.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [
            {"t": c.timestamp, "o": c.open, "h": c.high, "l": c.low, "c": c.close, "v": c.volume}
            for c in reversed(candles)
        ]
    finally:
        db.close()


@app.get("/api/strategies", dependencies=[Depends(verify_token)])
async def get_strategies():
    """Get all strategy results."""
    db = SessionLocal()
    try:
        results = db.query(StrategyResult).order_by(StrategyResult.created_at.desc()).limit(50).all()
        return [
            {
                "name": r.strategy_name, "symbol": r.symbol, "timeframe": r.timeframe,
                "return": r.return_pct, "sharpe": r.sharpe_ratio, "drawdown": r.max_drawdown,
                "win_rate": r.win_rate, "trades": r.total_trades, "verdict": r.verdict,
            }
            for r in results
        ]
    finally:
        db.close()


@app.post("/api/agent-log", dependencies=[Depends(verify_token)])
async def create_agent_log(log: dict):
    """Store an agent action log."""
    db = SessionLocal()
    try:
        entry = AgentLog(
            agent_id=log.get("agent_id", "unknown"),
            action=log.get("action", "LOG"),
            symbol=log.get("symbol"),
            decision=log.get("decision"),
            confidence=log.get("confidence"),
            reasoning=log.get("reasoning"),
            data=json.dumps(log.get("data", {})),
        )
        db.add(entry)
        db.commit()
        return {"status": "ok", "id": entry.id}
    finally:
        db.close()


# ── RBI Market Data Endpoints ──

@app.get("/api/market/fear-greed")
async def get_fear_greed():
    """Fear & Greed Index from alternative.me (no auth required)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://api.alternative.me/fng/?limit=1", timeout=8.0)
        data = resp.json()["data"][0]
        return {
            "value": int(data["value"]),
            "classification": data["value_classification"],
            "updated": data.get("timestamp"),
        }


@app.get("/api/market/top-movers")
async def get_top_movers(limit: int = 5):
    """Top gainers and losers in 24h from CoinGecko (no auth required)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.coingecko.com/api/v3/coins/markets"
            "?vs_currency=usd&order=percent_change_24h_desc&per_page=50&page=1"
            "&price_change_percentage=24h&sparkline=false",
            timeout=10.0,
            headers={"Accept": "application/json"},
        )
        coins = [c for c in resp.json() if isinstance(c.get("price_change_percentage_24h"), float)]
        gainers = sorted(coins, key=lambda x: x["price_change_percentage_24h"], reverse=True)[:limit]
        losers = sorted(coins, key=lambda x: x["price_change_percentage_24h"])[:limit]
        return {
            "gainers": [
                {"symbol": c["symbol"].upper(), "name": c["name"],
                 "price": c["current_price"], "change_24h": round(c["price_change_percentage_24h"], 2)}
                for c in gainers
            ],
            "losers": [
                {"symbol": c["symbol"].upper(), "name": c["name"],
                 "price": c["current_price"], "change_24h": round(c["price_change_percentage_24h"], 2)}
                for c in losers
            ],
        }


@app.get("/api/market/funding/{symbol}")
async def get_funding_rate(symbol: str):
    """Funding rate for a symbol from HyperLiquid (no auth required)."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(HL_BASE, json={"type": "metaAndAssetCtxs"}, timeout=10.0)
        result = resp.json()
        if isinstance(result, list) and len(result) == 2:
            meta, ctxs = result
            assets = meta.get("universe", [])
            sym = symbol.upper()
            for i, asset in enumerate(assets):
                if asset.get("name", "").upper() == sym and i < len(ctxs):
                    funding = ctxs[i].get("funding")
                    oi = ctxs[i].get("openInterest")
                    return {
                        "symbol": sym,
                        "funding_rate_pct": round(float(funding) * 100, 4) if funding else None,
                        "annualized_pct": round(float(funding) * 100 * 24 * 365, 2) if funding else None,
                        "open_interest": float(oi) if oi else None,
                    }
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found on HyperLiquid")


# ── HyperLiquid Endpoints ──

@app.get("/api/hl/prices")
async def get_hl_prices_endpoint():
    """All mid prices from HyperLiquid perpetuals."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(HL_BASE, json={"type": "allMids"}, timeout=8.0)
        data = resp.json()
        if isinstance(data, dict):
            return {"prices": {k: float(v) for k, v in data.items() if v}, "count": len(data)}
        raise HTTPException(status_code=502, detail="Invalid response from HyperLiquid")


@app.get("/api/hl/funding")
async def get_hl_funding_all():
    """Full funding snapshot for all HyperLiquid perpetuals with sentiment classification."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(HL_BASE, json={"type": "metaAndAssetCtxs"}, timeout=10.0)
        result = resp.json()
        if not isinstance(result, list) or len(result) < 2:
            raise HTTPException(status_code=502, detail="Invalid response from HyperLiquid")
        universe, ctxs = result[0].get("universe", []), result[1]
        rates = []
        for i, asset in enumerate(universe):
            if i >= len(ctxs):
                break
            name = asset.get("name", "")
            ctx = ctxs[i]
            funding = float(ctx.get("funding", 0) or 0)
            annual = funding * 24 * 365 * 100
            if annual > 100:
                sentiment = "EXTREME_LONG"
            elif annual > 50:
                sentiment = "VERY_LONG"
            elif annual > 20:
                sentiment = "LONG_BIAS"
            elif annual > 5:
                sentiment = "NEUTRAL_LONG"
            elif annual > -5:
                sentiment = "NEUTRAL"
            elif annual > -20:
                sentiment = "NEUTRAL_SHORT"
            elif annual > -50:
                sentiment = "SHORT_BIAS"
            elif annual > -100:
                sentiment = "VERY_SHORT"
            else:
                sentiment = "EXTREME_SHORT"
            rates.append({
                "coin": name,
                "funding_8h_pct": round(funding * 100, 4),
                "annual_pct": round(annual, 2),
                "open_interest": ctx.get("openInterest"),
                "mark_px": ctx.get("markPx"),
                "day_volume": ctx.get("dayNtlVlm"),
                "sentiment": sentiment,
            })
        carry = sorted([r for r in rates if r["annual_pct"] > 20], key=lambda x: x["annual_pct"], reverse=True)
        return {
            "total_assets": len(rates),
            "rates": rates,
            "carry_opportunities": carry[:10],
            "timestamp": datetime.utcnow().isoformat(),
        }


@app.get("/api/hl/candles/{coin}")
async def get_hl_candles(coin: str, interval: str = "1h", count: int = 100):
    """OHLCV candlestick data from HyperLiquid."""
    valid_intervals = {"1m", "5m", "15m", "1h", "4h", "1d"}
    if interval not in valid_intervals:
        raise HTTPException(status_code=400, detail=f"Invalid interval. Use one of: {', '.join(valid_intervals)}")
    interval_ms = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
    bar_ms = interval_ms[interval]
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - bar_ms * min(count, 1000)
    async with httpx.AsyncClient() as client:
        resp = await client.post(HL_BASE, json={
            "type": "candleSnapshot",
            "req": {"coin": coin.upper(), "interval": interval, "startTime": start_ms, "endTime": end_ms},
        }, timeout=15.0)
        candles = resp.json()
        if not isinstance(candles, list):
            raise HTTPException(status_code=502, detail=f"No candle data for {coin}")
        return {
            "coin": coin.upper(),
            "interval": interval,
            "count": len(candles),
            "candles": [
                {"t": c.get("t"), "o": float(c.get("o", 0)), "h": float(c.get("h", 0)),
                 "l": float(c.get("l", 0)), "c": float(c.get("c", 0)), "v": float(c.get("v", 0))}
                for c in candles
            ],
        }


@app.get("/api/hl/liquidations")
async def get_hl_liquidations(coins: str = "BTC,ETH,SOL,DOGE,AVAX"):
    """Recent liquidations from HyperLiquid (via recentTrades liquidation filter)."""
    coin_list = [c.strip().upper() for c in coins.split(",")][:10]
    async with httpx.AsyncClient() as client:
        all_liqs = []
        for coin in coin_list:
            try:
                resp = await client.post(HL_BASE, json={"type": "recentTrades", "coin": coin}, timeout=8.0)
                trades = resp.json()
                if isinstance(trades, list):
                    for t in trades:
                        if "liquidation" not in t:
                            continue
                        side = "LONG" if t.get("side") == "A" else "SHORT"
                        try:
                            usd_size = float(t.get("px", 0)) * float(t.get("sz", 0))
                        except (TypeError, ValueError):
                            usd_size = 0.0
                        all_liqs.append({
                            "coin": coin,
                            "side": side,
                            "usd_size": round(usd_size, 2),
                            "px": t.get("px"),
                            "sz": t.get("sz"),
                            "time_ms": t.get("time", 0),
                        })
            except Exception:
                pass
        all_liqs.sort(key=lambda x: x["time_ms"], reverse=True)
        return {"count": len(all_liqs), "liquidations": all_liqs[:50]}


@app.get("/api/hl/orderbook/{coin}")
async def get_hl_orderbook(coin: str, depth: int = 10):
    """L2 orderbook from HyperLiquid."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(HL_BASE, json={"type": "l2Book", "coin": coin.upper()}, timeout=8.0)
        data = resp.json()
        levels = data.get("levels", [[], []])
        bids = levels[0][:depth] if levels else []
        asks = levels[1][:depth] if len(levels) > 1 else []
        return {
            "coin": coin.upper(),
            "bids": [{"px": float(b["px"]), "sz": float(b["sz"])} for b in bids],
            "asks": [{"px": float(a["px"]), "sz": float(a["sz"])} for a in asks],
            "timestamp": datetime.utcnow().isoformat(),
        }


@app.get("/api/hl/markets")
async def get_hl_markets():
    """Market metadata from HyperLiquid (all perpetuals)."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(HL_BASE, json={"type": "meta"}, timeout=8.0)
        data = resp.json()
        universe = data.get("universe", [])
        return {
            "count": len(universe),
            "markets": [
                {"name": m.get("name"), "sz_decimals": m.get("szDecimals"), "max_leverage": m.get("maxLeverage")}
                for m in universe
            ],
        }


@app.get("/api/hl/stress")
async def get_stress_index():
    """On-demand Market Stress Index: funding + liquidations combined per coin."""
    await compute_stress_index()
    return {"status": "computed", "rankings": _last_stress_rankings, "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/market/snapshot")
async def get_market_snapshot():
    """Returns all cached market data in a single request (for initial load)."""
    return {
        "stress": _last_stress_rankings,
        "funding": _last_funding_rates,
        "liquidations": _last_liquidations,
        "whales": _last_whale_data,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/hl/funding/history/{coin}")
async def get_hl_funding_history(coin: str, days: int = 7):
    """Funding rate history for a coin from HyperLiquid."""
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86_400_000
    async with httpx.AsyncClient() as client:
        resp = await client.post(HL_BASE, json={
            "type": "fundingHistory", "coin": coin.upper(), "startTime": start_ms, "endTime": end_ms,
        }, timeout=10.0)
        data = resp.json()
        if not isinstance(data, list):
            raise HTTPException(status_code=502, detail=f"No funding history for {coin}")
        records = [
            {
                "time_ms": r.get("time"),
                "funding_rate": float(r.get("fundingRate", 0)),
                "annual_pct": round(float(r.get("fundingRate", 0)) * 24 * 365 * 100, 2),
            }
            for r in data
        ]
        return {"coin": coin.upper(), "days": days, "count": len(records), "history": records}


@app.get("/api/strategies/list", dependencies=[Depends(verify_token)])
async def list_strategies():
    """List available RBI strategy names from src/rbi/strategies/."""
    base = os.path.join(os.path.dirname(__file__), "..", "..", "src", "rbi", "strategies")
    if not os.path.isdir(base):
        return {"strategies": [], "note": "src/rbi/strategies not found in deployment"}
    files = glob_module.glob(os.path.join(base, "*.py"))
    names = [
        os.path.basename(f).replace(".py", "")
        for f in files
        if not os.path.basename(f).startswith("_")
    ]
    return {"strategies": sorted(names), "count": len(names)}


@app.post("/api/backtest/run", dependencies=[Depends(verify_token)])
async def run_backtest(params: dict):
    """Run a backtest for a given strategy+symbol+timeframe.
    Body: { strategy: str, symbol: str, timeframe: str, cash: int }
    """
    strategy_name = params.get("strategy", "rsi")
    symbol = params.get("symbol", "BTCUSDT").upper()
    timeframe = params.get("timeframe", "1h")
    cash = params.get("cash", 10000)

    try:
        import importlib
        import pandas as pd
        import yfinance as yf
        from backtesting import Backtest

        # Map CCXT symbol to yfinance (BTC/USDT → BTC-USD)
        yf_sym = symbol.replace("USDT", "-USD").replace("BTC-USD", "BTC-USD")

        # Fetch OHLCV data
        df = yf.download(yf_sym, period="1y", interval=timeframe, progress=False)
        if df.empty:
            raise HTTPException(status_code=400, detail=f"No data available for {symbol}")

        # Rename to backtesting.py format
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df = df.rename(columns={"Open": "Open", "High": "High", "Low": "Low",
                                 "Close": "Close", "Volume": "Volume"})
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()

        # Load strategy class from src/rbi/strategies/{name}.py
        module = importlib.import_module(f"src.rbi.strategies.{strategy_name}")
        # Find Strategy subclass
        from backtesting import Strategy
        strategy_cls = None
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            try:
                if isinstance(attr, type) and issubclass(attr, Strategy) and attr is not Strategy:
                    strategy_cls = attr
                    break
            except TypeError:
                pass

        if not strategy_cls:
            raise HTTPException(status_code=400, detail=f"No Strategy class found in {strategy_name}.py")

        bt = Backtest(df, strategy_cls, cash=cash, commission=0.002)
        stats = bt.run()

        # Determine verdict
        sharpe = float(stats.get("Sharpe Ratio", 0) or 0)
        dd = abs(float(stats.get("Max. Drawdown [%]", 100) or 100))
        wr = float(stats.get("Win Rate [%]", 0) or 0)
        trades = int(stats.get("# Trades", 0) or 0)
        pf = float(stats.get("Profit Factor", 0) or 0)

        if sharpe >= 1.0 and dd <= 20 and wr >= 40 and trades >= 50 and pf >= 1.5:
            verdict = "APPROVED"
        elif sharpe >= 0.5 and dd <= 35 and wr >= 35 and trades >= 25:
            verdict = "CAUTION"
        else:
            verdict = "REJECTED"

        result = {
            "strategy": strategy_name, "symbol": symbol, "timeframe": timeframe,
            "return_pct": round(float(stats.get("Return [%]", 0) or 0), 2),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown": round(dd, 2),
            "win_rate": round(wr, 2),
            "total_trades": trades,
            "profit_factor": round(pf, 3),
            "verdict": verdict,
        }

        # Save to database
        db = SessionLocal()
        try:
            entry = StrategyResult(
                strategy_name=strategy_name, symbol=symbol, timeframe=timeframe,
                return_pct=result["return_pct"], sharpe_ratio=result["sharpe_ratio"],
                max_drawdown=result["max_drawdown"], win_rate=result["win_rate"],
                total_trades=result["total_trades"], profit_factor=result["profit_factor"],
                verdict=verdict, parameters=json.dumps(params),
            )
            db.add(entry)
            db.commit()
            result["id"] = entry.id
        finally:
            db.close()

        return result

    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"RBI modules not available: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Swarm Consensus Endpoints ──

@app.post("/api/swarm/decision", dependencies=[Depends(verify_token)])
async def create_swarm_decision(decision: dict):
    """Store a swarm consensus decision and broadcast via WebSocket."""
    db = SessionLocal()
    try:
        entry = SwarmDecision(
            workflow=decision.get("workflow", "market_analysis"),
            symbol=decision.get("symbol"),
            decision=decision.get("decision", "HOLD"),
            consensus_score=decision.get("consensus_score"),
            confidence_avg=decision.get("confidence_avg"),
            votes=json.dumps(decision.get("votes", {})),
        )
        db.add(entry)
        db.commit()

        # Broadcast to all connected WebSocket clients
        await manager.broadcast({
            "type": "swarm_decision",
            "id": entry.id,
            "workflow": entry.workflow,
            "symbol": entry.symbol,
            "decision": entry.decision,
            "consensus_score": entry.consensus_score,
            "confidence_avg": entry.confidence_avg,
            "timestamp": datetime.utcnow().isoformat(),
        })

        return {"status": "ok", "id": entry.id}
    finally:
        db.close()


@app.get("/api/swarm/decisions", dependencies=[Depends(verify_token)])
async def get_swarm_decisions(limit: int = 20):
    """Get recent swarm decisions."""
    db = SessionLocal()
    try:
        results = (
            db.query(SwarmDecision)
            .order_by(SwarmDecision.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "workflow": r.workflow,
                "symbol": r.symbol,
                "decision": r.decision,
                "consensus_score": r.consensus_score,
                "confidence_avg": r.confidence_avg,
                "votes": json.loads(r.votes) if r.votes else {},
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in results
        ]
    finally:
        db.close()


# ── Agent Context Endpoints ──

@app.get("/api/agent/context/{agent_id}")
async def get_agent_context(agent_id: str):
    """Get saved conversational context for an agent (no auth — context is not sensitive)."""
    agent_id = validate_agent_id(agent_id)
    db = SessionLocal()
    try:
        ctx = db.query(AgentContext).filter(AgentContext.agent_id == agent_id).first()
        if not ctx:
            return {"agent_id": agent_id, "context_summary": None, "updated_at": None}
        return {
            "agent_id": agent_id,
            "context_summary": ctx.context_summary,
            "updated_at": ctx.updated_at.isoformat() if ctx.updated_at else None,
        }
    finally:
        db.close()


@app.post("/api/agent/context/{agent_id}", dependencies=[Depends(verify_token)])
async def save_agent_context(agent_id: str, data: dict):
    """Save or update conversational context for an agent."""
    agent_id = validate_agent_id(agent_id)
    db = SessionLocal()
    try:
        ctx = db.query(AgentContext).filter(AgentContext.agent_id == agent_id).first()
        if ctx:
            ctx.context_summary = data.get("context_summary", ctx.context_summary)
            ctx.updated_at = datetime.utcnow()
        else:
            ctx = AgentContext(
                agent_id=agent_id,
                context_summary=data.get("context_summary"),
            )
            db.add(ctx)
        db.commit()
        return {"status": "ok", "agent_id": agent_id}
    finally:
        db.close()


# ── Agent Memory Endpoints ──

@app.get("/api/agent/memory/{agent_id}")
async def get_agent_memories(agent_id: str, type: str = None, limit: int = 100):
    """Get all memories for an agent (optionally filtered by type)."""
    agent_id = validate_agent_id(agent_id)
    db = SessionLocal()
    try:
        q = db.query(AgentMemoryEntry).filter(AgentMemoryEntry.agent_id == agent_id)
        if type:
            q = q.filter(AgentMemoryEntry.type == type)
        results = q.order_by(AgentMemoryEntry.importance.desc()).limit(limit).all()
        return {
            "agent_id": agent_id,
            "count": len(results),
            "memories": [
                {
                    "id": r.memory_id,
                    "agent_id": r.agent_id,
                    "type": r.type,
                    "scope": r.scope,
                    "content": r.content,
                    "context": r.context,
                    "tags": json.loads(r.tags) if r.tags else [],
                    "importance": r.importance,
                    "access_count": r.access_count,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                    "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                    "links": [],
                }
                for r in results
            ],
        }
    finally:
        db.close()


@app.post("/api/agent/memory/{agent_id}", dependencies=[Depends(verify_token)])
async def save_agent_memory(agent_id: str, data: dict):
    """Save or update a memory entry for an agent."""
    agent_id = validate_agent_id(agent_id)
    memory_id = data.get("id", "")
    if not memory_id:
        raise HTTPException(status_code=400, detail="Missing memory id")
    db = SessionLocal()
    try:
        existing = db.query(AgentMemoryEntry).filter(
            AgentMemoryEntry.memory_id == memory_id
        ).first()
        if existing:
            existing.content = data.get("content", existing.content)
            existing.context = data.get("context", existing.context)
            existing.tags = json.dumps(data.get("tags", []))
            existing.importance = data.get("importance", existing.importance)
            existing.access_count = data.get("access_count", existing.access_count)
            existing.updated_at = datetime.utcnow()
        else:
            expires_at = None
            if data.get("expires_at"):
                try:
                    expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pass
            entry = AgentMemoryEntry(
                memory_id=memory_id,
                agent_id=agent_id,
                type=data.get("type", "semantic"),
                scope=data.get("scope", "private"),
                content=data.get("content", ""),
                context=data.get("context", ""),
                tags=json.dumps(data.get("tags", [])),
                importance=data.get("importance", 0.5),
                access_count=data.get("access_count", 0),
                expires_at=expires_at,
            )
            db.add(entry)
        db.commit()
        return {"status": "ok", "memory_id": memory_id, "agent_id": agent_id}
    finally:
        db.close()


@app.delete("/api/agent/memory/{agent_id}/{memory_id}", dependencies=[Depends(verify_token)])
async def delete_agent_memory(agent_id: str, memory_id: str):
    """Delete a specific memory entry."""
    agent_id = validate_agent_id(agent_id)
    db = SessionLocal()
    try:
        deleted = db.query(AgentMemoryEntry).filter(
            AgentMemoryEntry.memory_id == memory_id,
            AgentMemoryEntry.agent_id == agent_id,
        ).delete()
        db.commit()
        return {"status": "ok", "deleted": deleted}
    finally:
        db.close()


@app.get("/api/agent/memory/shared/all")
async def get_shared_memories(limit: int = 50):
    """Get all shared memories across agents."""
    db = SessionLocal()
    try:
        results = db.query(AgentMemoryEntry).filter(
            AgentMemoryEntry.scope == "shared"
        ).order_by(AgentMemoryEntry.importance.desc()).limit(limit).all()
        return {
            "count": len(results),
            "memories": [
                {
                    "id": r.memory_id,
                    "agent_id": r.agent_id,
                    "type": r.type,
                    "scope": r.scope,
                    "content": r.content,
                    "context": r.context,
                    "tags": json.loads(r.tags) if r.tags else [],
                    "importance": r.importance,
                    "access_count": r.access_count,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                    "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                    "links": [],
                }
                for r in results
            ],
        }
    finally:
        db.close()


# ── HyperLiquid Historical Data Endpoints ──

@app.get("/api/hl/liquidations/history")
async def get_liquidations_history(coin: str = None, limit: int = 50):
    """Recent liquidation events stored in Railway Postgres."""
    db = SessionLocal()
    try:
        q = db.query(LiquidationEvent)
        if coin:
            q = q.filter(LiquidationEvent.coin == coin.upper())
        results = q.order_by(LiquidationEvent.time_ms.desc()).limit(limit).all()
        return {
            "count": len(results),
            "liquidations": [
                {
                    "coin": r.coin, "side": r.side, "usd_size": r.usd_size,
                    "px": r.px, "sz": r.sz, "time_ms": r.time_ms,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in results
            ],
        }
    finally:
        db.close()


@app.get("/api/hl/funding/stored/{coin}")
async def get_funding_stored(coin: str, limit: int = 100):
    """Funding rate history for a coin from Railway Postgres."""
    db = SessionLocal()
    try:
        results = (
            db.query(FundingRate)
            .filter(FundingRate.coin == coin.upper())
            .order_by(FundingRate.timestamp.desc())
            .limit(limit)
            .all()
        )
        return {
            "coin": coin.upper(),
            "count": len(results),
            "history": [
                {
                    "timestamp": r.timestamp, "rate_8h_pct": r.rate_8h_pct,
                    "annual_pct": r.annual_pct, "open_interest": r.open_interest,
                    "mark_px": r.mark_px,
                }
                for r in results
            ],
        }
    finally:
        db.close()


@app.get("/api/hl/whale-positions")
async def get_whale_positions_endpoint():
    """Fetch current top leveraged whale positions from HyperLiquid (heavy, ~10s)."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _fetch_whale_positions_sync)
    return {
        "longs": result.get("longs", []),
        "shorts": result.get("shorts", []),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── WebSocket for real-time data ──

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            data = await ws.receive_json()
            # Handle commands from the Electron app
            if data.get("type") == "ping":
                await ws.send_json({"type": "pong"})
            elif data.get("type") == "subscribe":
                # Verify token — close connection immediately on failure
                if API_TOKEN:
                    token = data.get("token")
                    if not token or not secrets.compare_digest(token, API_TOKEN):
                        await ws.send_json({"type": "error", "message": "Authentication required"})
                        await ws.close(code=1008)  # 1008 = Policy Violation
                        manager.disconnect(ws)
                        return
                await ws.send_json({"type": "subscribed", "symbols": data.get("symbols", [])})
    except WebSocketDisconnect:
        manager.disconnect(ws)
