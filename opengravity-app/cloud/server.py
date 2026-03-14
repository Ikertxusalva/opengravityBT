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
import time
import secrets
from collections import defaultdict

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


# ── Scheduler for data ingestion ──

scheduler = AsyncIOScheduler()


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
HL_WATCH = ["BTC", "ETH", "SOL", "DOGE", "XRP", "AVAX", "LINK", "ARB", "OP", "INJ", "WIF", "PEPE", "HYPE", "BNB", "SUI", "APT", "TIA", "SEI", "TON", "ADA"]


async def fetch_funding_rates():
    """Fetch funding rates from HyperLiquid (no API key) and broadcast."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(HL_BASE, json={"type": "metaAndAssetCtxs"}, timeout=10.0)
            result = resp.json()
            if isinstance(result, list) and len(result) == 2:
                universe, ctxs = result[0].get("universe", []), result[1]
                rates = {}
                carry_ops = []
                for i, asset in enumerate(universe):
                    if i >= len(ctxs):
                        break
                    name = asset.get("name", "")
                    if not name:
                        continue
                    funding = float(ctxs[i].get("funding", 0) or 0)
                    annual = round(funding * 24 * 365 * 100, 2)
                    rates[name] = {"h8_pct": round(funding * 100, 4), "annual_pct": annual}
                    if annual > 20 and name in HL_WATCH:
                        carry_ops.append({"coin": name, "annual_pct": annual})
                carry_ops.sort(key=lambda x: x["annual_pct"], reverse=True)
                await manager.broadcast({
                    "type": "funding_update",
                    "rates": {k: v for k, v in rates.items() if k in HL_WATCH},
                    "carry_opportunities": carry_ops[:5],
                    "timestamp": datetime.utcnow().isoformat(),
                })
        except Exception as e:
            print(f"[funding_rates] Error: {e}")


async def fetch_hl_prices():
    """Fetch mid prices from HyperLiquid and broadcast (supplements Binance prices)."""
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


# ── FastAPI App ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: schedule jobs
    scheduler.add_job(fetch_prices, "interval", seconds=30)
    scheduler.add_job(fetch_candles, "interval", minutes=5)
    scheduler.add_job(fetch_fear_greed, "interval", minutes=30)
    scheduler.add_job(fetch_top_movers, "interval", minutes=15)
    scheduler.add_job(fetch_funding_rates, "interval", minutes=15)
    scheduler.add_job(fetch_hl_prices, "interval", minutes=1)
    scheduler.start()
    # Run once at startup — each wrapped individually so one failure doesn't block startup
    for fn in [fetch_fear_greed, fetch_top_movers, fetch_funding_rates, fetch_hl_prices]:
        try:
            await fn()
        except Exception as e:
            print(f"⚠️ Startup fetch {fn.__name__} failed: {e}")
    yield
    # Shutdown
    scheduler.shutdown()

app = FastAPI(
    title="OpenGravity Cloud",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to specific origins
    allow_methods=["*"],
    allow_headers=["*"],
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

@app.post("/api/swarm/decision")
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


@app.get("/api/swarm/decisions")
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


@app.post("/api/agent/context/{agent_id}")
async def save_agent_context(agent_id: str, data: dict):
    """Save or update conversational context for an agent."""
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
                # Verify token in the first message or every message
                if API_TOKEN:
                    token = data.get("token")
                    if not token or not secrets.compare_digest(token, API_TOKEN):
                        await ws.send_json({"type": "error", "message": "Authentication required"})
                        continue
                await ws.send_json({"type": "subscribed", "symbols": data.get("symbols", [])})
    except WebSocketDisconnect:
        manager.disconnect(ws)
