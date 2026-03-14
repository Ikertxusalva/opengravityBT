"""OpenGravity Cloud Backend — FastAPI + PostgreSQL + WebSocket."""
import os
import json
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Text, BigInteger
from sqlalchemy.orm import sessionmaker, declarative_base
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import httpx

# ── Database Setup ──
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./dev.db")

# Railway Postgres uses postgresql:// but SQLAlchemy needs postgresql+psycopg2://
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
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


# Create tables
Base.metadata.create_all(bind=engine)


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


# ── FastAPI App ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: schedule jobs
    scheduler.add_job(fetch_prices, "interval", seconds=30)
    scheduler.add_job(fetch_candles, "interval", minutes=5)
    scheduler.start()
    yield
    # Shutdown
    scheduler.shutdown()

app = FastAPI(
    title="OpenGravity Cloud",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── REST Endpoints ──

@app.get("/")
async def root():
    return {"status": "alive", "service": "opengravity-cloud", "version": "0.1.0"}


@app.get("/health")
async def health():
    return {"status": "ok", "db": "connected", "agents": len(manager.active)}


@app.get("/api/prices/{symbol}")
async def get_price(symbol: str):
    """Get latest price from Binance."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}",
            timeout=5.0,
        )
        return resp.json()


@app.get("/api/candles/{symbol}")
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


@app.get("/api/strategies")
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


@app.post("/api/agent-log")
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
                await ws.send_json({"type": "subscribed", "symbols": data.get("symbols", [])})
    except WebSocketDisconnect:
        manager.disconnect(ws)
