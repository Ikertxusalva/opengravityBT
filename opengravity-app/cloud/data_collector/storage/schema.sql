-- Data Collector Schema — Multi-exchange market data
-- Runs on Railway PostgreSQL alongside the existing backend

-- Funding rates multi-exchange (hourly)
CREATE TABLE IF NOT EXISTS funding_rates (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    funding_rate DOUBLE PRECISION,
    funding_apy DOUBLE PRECISION,
    predicted_rate DOUBLE PRECISION,
    mark_price DOUBLE PRECISION,
    index_price DOUBLE PRECISION,
    UNIQUE(timestamp, exchange, symbol)
);
CREATE INDEX IF NOT EXISTS idx_funding_ts ON funding_rates(timestamp, symbol);
CREATE INDEX IF NOT EXISTS idx_funding_exchange ON funding_rates(exchange, symbol, timestamp);

-- Open Interest multi-exchange (every 4h)
CREATE TABLE IF NOT EXISTS open_interest (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    oi_contracts DOUBLE PRECISION,
    oi_usd DOUBLE PRECISION,
    UNIQUE(timestamp, exchange, symbol)
);
CREATE INDEX IF NOT EXISTS idx_oi_ts ON open_interest(timestamp, symbol);

-- Liquidations (every 5 min)
CREATE TABLE IF NOT EXISTS liquidations (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(5) NOT NULL,
    quantity DOUBLE PRECISION,
    usd_value DOUBLE PRECISION,
    price DOUBLE PRECISION,
    UNIQUE(timestamp, exchange, symbol, side)
);
CREATE INDEX IF NOT EXISTS idx_liq_ts ON liquidations(timestamp, symbol);

-- OHLCV backup (daily sync)
CREATE TABLE IF NOT EXISTS ohlcv (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(5) NOT NULL,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    UNIQUE(timestamp, exchange, symbol, timeframe)
);
CREATE INDEX IF NOT EXISTS idx_ohlcv_ts ON ohlcv(timestamp, symbol, timeframe);

-- Market snapshots (hourly)
CREATE TABLE IF NOT EXISTS market_snapshots (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    total_oi_usd DOUBLE PRECISION,
    total_volume_24h DOUBLE PRECISION,
    btc_dominance DOUBLE PRECISION,
    funding_weighted_avg DOUBLE PRECISION,
    fear_greed_index INTEGER,
    num_coins_negative_funding INTEGER,
    num_coins_positive_funding INTEGER,
    UNIQUE(timestamp)
);

-- Swarm trades (for ML training data)
CREATE TABLE IF NOT EXISTS swarm_trades (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    signal_id VARCHAR(50),
    strategy VARCHAR(50) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    direction VARCHAR(5) NOT NULL,
    entry_price DOUBLE PRECISION,
    sl_price DOUBLE PRECISION,
    tp_price DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    regime VARCHAR(20),
    ml_win_prob DOUBLE PRECISION,
    exit_price DOUBLE PRECISION,
    exit_reason VARCHAR(20),
    pnl_pct DOUBLE PRECISION,
    slippage_bps DOUBLE PRECISION,
    features JSONB
);
CREATE INDEX IF NOT EXISTS idx_trades_ts ON swarm_trades(timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON swarm_trades(strategy, symbol);
