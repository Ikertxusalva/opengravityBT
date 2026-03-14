# moondev/swarm/signals.py
"""
Extractores one-shot de señal para cada agente de mercado.
Cada función ejecuta UN ciclo del agente y retorna la señal inmediatamente.
No hay loops ni sleep — estos son para uso en el coordinador de swarm.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from moondev.core.model_factory import ModelFactory
from moondev.core.nice_funcs import parse_llm_action, get_ohlcv, add_indicators
import moondev.config as cfg

# ── Tipo de retorno ───────────────────────────────────────────────────────────

def _signal(action: str, reason: str, confidence: str | int, source: str) -> dict:
    """Normaliza una señal al formato estándar del swarm."""
    return {
        "action": action.upper() if action else "NOTHING",
        "reason": reason or "sin datos",
        "confidence": int(confidence) if str(confidence).isdigit() else 50,
        "source": source,
    }


def _error_signal(source: str, error: str) -> dict:
    return _signal("NOTHING", f"Error: {error}", 0, source)


def _persist_funding_csv(symbol: str, annual_rate: float, action: str, reason: str, confidence) -> None:
    """Escribe la señal al CSV que lee execution_agent (data/funding/funding_signals.csv)."""
    import csv as _csv
    from datetime import datetime as _dt
    funding_dir = cfg.DATA_DIR / "funding"
    funding_dir.mkdir(parents=True, exist_ok=True)
    path = funding_dir / "funding_signals.csv"
    is_new = not path.exists()
    with open(path, "a", newline="") as f:
        writer = _csv.DictWriter(
            f,
            fieldnames=["timestamp", "symbol", "annual_rate", "action", "confidence", "reason"],
        )
        if is_new:
            writer.writeheader()
        writer.writerow({
            "timestamp":   _dt.now().isoformat(),
            "symbol":      symbol,
            "annual_rate": f"{annual_rate:.2f}",
            "action":      action,
            "confidence":  int(confidence) if str(confidence).isdigit() else confidence,
            "reason":      reason,
        })


# ── Señal 1: Funding Rates ────────────────────────────────────────────────────

def get_funding_signal(model=None) -> dict:
    """
    Un ciclo del funding_agent.
    Obtiene tasas de funding de HyperLiquid y analiza los tokens fuera de rango.
    Devuelve la señal del token con funding más extremo.
    """
    import requests

    if model is None:
        model = ModelFactory().get()

    SYSTEM_PROMPT = """You are a funding rate carry trade analyst.
Analyze the provided funding rate data and market context.

Respond in exactly 3 lines:
Line 1: BUY, SELL, or NOTHING
Line 2: One short reason
Line 3: Confidence: X%

Consider:
- Negative funding in uptrend = potential long (funding reversal)
- Positive funding in downtrend = potential short
- Extreme funding (>100% annual) = carry trade opportunity
"""
    NEG_THRESHOLD = -5.0
    POS_THRESHOLD = 20.0

    try:
        resp = requests.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "metaAndAssetCtxs"},
            timeout=10,
        )
        data = resp.json()
        meta = data[0].get("universe", [])
        ctxs = data[1]

        # Buscar el token con funding más extremo
        best = None
        best_extremity = 0.0

        for i, asset in enumerate(meta):
            name = asset["name"]
            if name in cfg.MONITORED_TOKENS and i < len(ctxs):
                funding = float(ctxs[i].get("funding", 0))
                annual = funding * 24 * 365 * 100
                extremity = abs(annual)
                if (annual < NEG_THRESHOLD or annual > POS_THRESHOLD) and extremity > best_extremity:
                    best = (name, annual)
                    best_extremity = extremity

        if best is None:
            return _signal("NOTHING", "todos los funding rates dentro de rango normal", 70, "funding")

        symbol, annual_rate = best
        try:
            df = get_ohlcv(f"{symbol}-USD", days=7, timeframe="1h")
            df = add_indicators(df)
            last5 = df.tail(5).to_string()
        except Exception:
            last5 = "No market data available"

        user_content = f"""
Token: {symbol}
Annual Funding Rate: {annual_rate:.2f}%
Hourly Funding Rate: {annual_rate / 24 / 365:.4f}%

Market context (last 5 candles 1h):
{last5}
"""
        llm_resp = model.ask(SYSTEM_PROMPT, user_content)
        action, reason, confidence = parse_llm_action(llm_resp.content)
        _persist_funding_csv(symbol, annual_rate, action, reason, confidence)
        return _signal(action, f"[{symbol} {annual_rate:+.1f}%/yr] {reason}", confidence, "funding")

    except Exception as e:
        return _error_signal("funding", str(e))


# ── Señal 2: Whale Movements ──────────────────────────────────────────────────

def get_whale_signal(model=None) -> dict:
    """
    Un ciclo del whale_agent.
    Obtiene movimientos on-chain grandes y analiza implicaciones de mercado.
    """
    import requests

    if model is None:
        model = ModelFactory().get()

    SYSTEM_PROMPT = """You are an on-chain whale movement analyst.
Large crypto transactions have been detected.

Analyze the market implications:
- Exchange INFLOWS (moving TO exchange) = selling pressure = BEARISH
- Exchange OUTFLOWS (moving FROM exchange) = accumulation = BULLISH
- Wallet-to-wallet = unknown intent, but large = important player moving

Respond in exactly 3 lines:
Line 1: BUY, SELL, or NOTHING
Line 2: One short reason (accumulation/distribution/unknown)
Line 3: Confidence: X%

Consider: multiple large outflows = stronger signal than single transaction.
"""

    whale_api_key = getattr(cfg, "WHALE_ALERT_API_KEY", "")

    if not whale_api_key:
        # Sin API key: usar datos mock (misma lógica que whale_agent.py)
        from datetime import datetime
        txs = [
            {
                "blockchain": "bitcoin", "symbol": "BTC", "amount": 500,
                "amount_usd": 43_000_000, "from_owner": "unknown",
                "to_owner": "binance", "direction": "TO_EXCHANGE",
                "timestamp": datetime.now().isoformat(),
            },
        ]
    else:
        try:
            resp = requests.get(
                "https://api.whale-alert.io/v1/transactions",
                params={"api_key": whale_api_key, "min_value": 500000, "limit": 10},
                timeout=10,
            )
            txs = resp.json().get("transactions", [])
        except Exception as e:
            return _error_signal("whale", str(e))

    if not txs:
        return _signal("NOTHING", "sin movimientos de ballenas detectados", 60, "whale")

    summary = "\n".join(
        f"- {t.get('symbol','?')} ${t.get('amount_usd',0)/1e6:.1f}M {t.get('from_owner','?')} → {t.get('to_owner','?')}"
        for t in txs[:5]
    )
    user_content = f"Recent large transactions:\n{summary}"

    try:
        llm_resp = model.ask(SYSTEM_PROMPT, user_content)
        action, reason, confidence = parse_llm_action(llm_resp.content)
        return _signal(action, reason, confidence, "whale")
    except Exception as e:
        return _error_signal("whale", str(e))


# ── Señal 3: News ─────────────────────────────────────────────────────────────

def get_news_signal(model=None) -> dict:
    """
    Un ciclo del news_agent.
    Obtiene las noticias más recientes y analiza su impacto en el precio.
    """
    import requests

    if model is None:
        model = ModelFactory().get()

    SYSTEM_PROMPT = """You are a crypto news impact analyst.
Analyze the following news headline and determine its market impact.

Classification rules:
- HACK/EXPLOIT = HIGH BEARISH (immediate risk)
- ETF APPROVAL/REJECTION = HIGH (direction depends)
- REGULATORY BAN = HIGH BEARISH
- INSTITUTIONAL ADOPTION = MEDIUM-HIGH BULLISH
- NEW EXCHANGE LISTING = MEDIUM BULLISH for that token
- FUD without source = LOW (potential contrarian BUY)
- Generic analysis/opinion = IGNORE

Respond in exactly 3 lines:
Line 1: BUY, SELL, or NOTHING
Line 2: Impact level + reason (e.g., "HIGH BEARISH: major hack detected")
Line 3: Confidence: X%

If impact is LOW or news is old/generic, say NOTHING.
"""

    try:
        resp = requests.get(
            "https://min-api.cryptocompare.com/data/v2/news/",
            params={"lang": "EN", "sortOrder": "latest", "limit": 5},
            timeout=10,
        )
        articles = resp.json().get("Data", [])
    except Exception as e:
        return _error_signal("news", str(e))

    if not articles:
        return _signal("NOTHING", "sin noticias recientes disponibles", 50, "news")

    headlines = "\n".join(f"- {a['title']}" for a in articles[:5])
    user_content = f"Latest crypto news:\n{headlines}"

    try:
        llm_resp = model.ask(SYSTEM_PROMPT, user_content)
        action, reason, confidence = parse_llm_action(llm_resp.content)
        return _signal(action, reason, confidence, "news")
    except Exception as e:
        return _error_signal("news", str(e))


# ── Señal 4: Top Mover Momentum ───────────────────────────────────────────────

def get_top_mover_signal(model=None) -> dict:
    """
    Un ciclo del top_mover_agent.
    Analiza top gainers/losers de las últimas 24h via CoinGecko free API.
    """
    import requests

    if model is None:
        model = ModelFactory().get()

    SYSTEM_PROMPT = """You are a top mover momentum analyst.
Analyze the top gainers and losers in the last 24h.

Rules:
- Extreme gainers (+20%/day): potential breakout OR exhaustion reversal
- Multiple coins moving together = sector rotation signal

Respond in exactly 3 lines:
Line 1: BUY, SELL, or NOTHING (for the overall crypto market)
Line 2: One short reason about the momentum pattern
Line 3: Confidence: X%
"""

    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 20,
                "page": 1,
                "price_change_percentage": "24h",
            },
            timeout=10,
        )
        data = resp.json()
    except Exception as e:
        return _error_signal("top_mover", str(e))

    if not data or not isinstance(data, list):
        return _signal("NOTHING", "sin datos de top movers", 50, "top_mover")

    gainers = sorted(data, key=lambda x: x.get("price_change_percentage_24h") or 0, reverse=True)
    losers  = sorted(data, key=lambda x: x.get("price_change_percentage_24h") or 0)

    summary = "Top gainers (24h):\n"
    for c in gainers[:3]:
        chg = c.get("price_change_percentage_24h") or 0
        summary += f"  {c['symbol'].upper()}: +{chg:.1f}%\n"
    summary += "Top losers (24h):\n"
    for c in losers[:3]:
        chg = c.get("price_change_percentage_24h") or 0
        summary += f"  {c['symbol'].upper()}: {chg:.1f}%\n"

    try:
        llm_resp = model.ask(SYSTEM_PROMPT, summary)
        action, reason, confidence = parse_llm_action(llm_resp.content)
        return _signal(action, reason, confidence, "top_mover")
    except Exception as e:
        return _error_signal("top_mover", str(e))


# ── Señal 5: Liquidation Spikes ───────────────────────────────────────────────

def get_liquidation_signal(model=None) -> dict:
    """
    Un ciclo del liquidation_agent.
    Detecta spikes de volumen en BTC 1h como proxy de cascadas de liquidación.
    """
    if model is None:
        model = ModelFactory().get()

    SYSTEM_PROMPT = """You are a liquidation cascade analyst.
Analyze the recent price action and volume spikes to detect liquidation events.

Rules:
- Large volume spike + large red candle = long liquidation cascade = potential BUY (capitulation)
- Large volume spike + large green candle = short squeeze = potential SELL (exhaustion)
- Multiple spikes in short time = stronger signal

Respond in exactly 3 lines:
Line 1: BUY, SELL, or NOTHING
Line 2: One short reason (long liquidation / short squeeze / no clear signal)
Line 3: Confidence: X%
"""

    try:
        df = get_ohlcv("BTC-USD", days=3, timeframe="1h")
        df = add_indicators(df)

        vol_mean = df["volume"].rolling(20).mean()
        vol_std  = df["volume"].rolling(20).std()
        df["vol_spike"] = (df["volume"] - vol_mean) / vol_std.replace(0, 1)
        df["body_pct"]  = (df["close"] - df["open"]).abs() / df["close"]

        recent = df.tail(12)
        spikes = recent[recent["vol_spike"] > 2.0]

        if spikes.empty:
            return _signal("NOTHING", "sin spikes de volumen significativos en 12h", 65, "liquidation")

        spike_info = []
        for _, row in spikes.iterrows():
            direction = "RED" if row["close"] < row["open"] else "GREEN"
            spike_info.append(
                f"  {row.name}: vol {row['vol_spike']:.1f}σ | {direction} candle {row['body_pct']*100:.1f}% body"
            )

        user_content = "BTC 1h - Volume spikes detected (last 12 candles):\n" + "\n".join(spike_info)
        llm_resp = model.ask(SYSTEM_PROMPT, user_content)
        action, reason, confidence = parse_llm_action(llm_resp.content)
        return _signal(action, reason, confidence, "liquidation")

    except Exception as e:
        return _error_signal("liquidation", str(e))
