"""
Polymarket Trading Bot — Paper Mode
=====================================
Sistema completo de trading en mercados de predicción.

PAPER_MODE = True  ->  Simula órdenes con datos reales. NO mueve dinero.
PAPER_MODE = False ->  Ejecuta órdenes reales en Polygon via CLOB.
                       (Requiere credenciales configuradas)

Uso:
    python paper_trader.py scan          # Escanear y abrir posiciones
    python paper_trader.py status        # Portfolio actual + P&L
    python paper_trader.py resolve       # Cerrar mercados resueltos
    python paper_trader.py report        # Reporte completo con métricas
    python paper_trader.py update        # Actualizar precios + stop-loss
    python paper_trader.py loop [min]    # Ciclo automático (default: 30 min)
"""

import sys
import json
import os
import time
import math
import httpx
from datetime import datetime, timezone, timedelta

# Modulos de señales externas
try:
    from signals.kalshi import check_kalshi_arb
    from signals.manifold import check_manifold_signal
    from signals.orderbook import check_orderbook_imbalance
    from signals.whale_clob import check_whale_activity
    SIGNALS_AVAILABLE = True
except ImportError:
    SIGNALS_AVAILABLE = False
from pathlib import Path
from statistics import mean, stdev
from typing import Optional

# ==============================================================================
#  CONFIGURACIÓN CENTRAL
#  ↓↓↓ ÚNICO PUNTO DE CONTROL PAPER vs REAL ↓↓↓
# ==============================================================================

PAPER_MODE = True          # False = trading real (requiere POLYMARKET_PK etc.)

# Capital simulado (solo usado en PAPER_MODE)
STARTING_BANK   = 2_000   # USD de partida

# Parámetros de riesgo (aplican en PAPER y en REAL)
MAX_POSITION    = 300      # USD máximo por posición
MAX_EXPOSURE    = 2_000    # USD máximo total desplegado
MIN_EDGE        = 0.05     # Edge mínimo para entrar (5 puntos)
MIN_LIQUIDITY   = 2_000    # Liquidez mínima en order book
MIN_VOLUME      = 30_000   # Volumen total mínimo del mercado
MIN_DAYS_LEFT   = 3        # Días mínimos hasta resolución
MAX_SPREAD      = 0.15     # Spread máximo tolerado
STOP_LOSS_PCT   = -0.30    # Cerrar si pérdida > 30% del capital invertido
TAKE_PROFIT_PCT =  0.50    # Tomar ganancias si +50% del capital invertido
SLIPPAGE_EST    =  0.003   # Slippage estimado al comprar (0.3%)
SCAN_LIMIT      = 200      # Mercados a escanear por ciclo

# APIs Polymarket (públicas, sin auth para lectura)
GAMMA = "https://gamma-api.polymarket.com"
CLOB  = "https://clob.polymarket.com"

# Paths de datos
DATA_DIR  = Path(__file__).parent / "data"
DB_FILE   = DATA_DIR / "paper_positions.json"
LOG_FILE  = DATA_DIR / "paper_log.jsonl"
PRIOR_FILE = DATA_DIR / "bayesian_priors.json"
DATA_DIR.mkdir(exist_ok=True)


# ==============================================================================
#  BAYESIAN KELLY — Tamaño de posición con incertidumbre
# ==============================================================================

class BayesianKelly:
    """
    Calcula el Kelly óptimo usando una distribución Beta sobre la
    probabilidad de ganar. Se actualiza con cada trade resuelto.

    P(win) ~ Beta(α, β)
    E[p]   = α / (α + β)
    Var[p] = α·β / (α+β)²·(α+β+1)

    Kelly robusto = E[p] - confidence_factor · StdDev[p]
    -> A menor certeza, posición más pequeña.
    """

    def __init__(self, priors: dict):
        self.priors = priors  # {source: {"alpha": float, "beta": float}}

    @staticmethod
    def _beta_mean(alpha: float, beta: float) -> float:
        return alpha / (alpha + beta)

    @staticmethod
    def _beta_std(alpha: float, beta: float) -> float:
        n = alpha + beta
        return math.sqrt(alpha * beta / (n * n * (n + 1)))

    def get_prior(self, source: str) -> tuple[float, float]:
        """Devuelve (alpha, beta) para una fuente de edge."""
        p = self.priors.get(source, {"alpha": 2.0, "beta": 2.0})
        return p["alpha"], p["beta"]

    def update(self, source: str, won: bool):
        """Actualiza el prior Beta tras resolver un trade."""
        if source not in self.priors:
            self.priors[source] = {"alpha": 2.0, "beta": 2.0}
        if won:
            self.priors[source]["alpha"] += 1
        else:
            self.priors[source]["beta"] += 1

    def kelly_fraction(self, source: str, entry_price: float,
                       edge: float = 0.0,
                       confidence_factor: float = 1.0) -> float:
        """
        Calcula la fracción de Kelly ajustada por incertidumbre Bayesiana.

        Lógica dual:
        - Con n < 5 muestras: usa el edge directamente (bootstrap conservador)
        - Con n >= 5 muestras: Kelly Bayesiano completo con prior Beta

        p_win = entry_price + edge  (nuestra estimación de ganar)
        p_robust = p_win - confidence_factor * posterior_std
        """
        alpha, beta = self.get_prior(source)
        n_samples = int(alpha + beta - 4)  # descontar prior inicial (2+2)

        # p_win estimada desde el edge (no desde el prior del source)
        p_win = min(0.95, max(0.05, entry_price + edge))

        if n_samples < 5:
            # Bootstrap: Kelly directo con p_win, sin penalización bayesiana
            # pero con un cap conservador del 8%
            b = (1.0 / entry_price) - 1.0
            if b <= 0:
                return 0.0
            q = 1.0 - p_win
            kelly = (p_win * b - q) / b
            half_kelly = kelly / 2.0
            return max(0.0, min(half_kelly, 0.08))  # cap 8% en bootstrap
        else:
            # Bayesian Kelly completo: usar posterior del source para ajustar confianza
            p_std = self._beta_std(alpha, beta)
            p_robust = max(0.01, p_win - confidence_factor * p_std)

            b = (1.0 / entry_price) - 1.0
            if b <= 0:
                return 0.0
            q = 1.0 - p_robust
            kelly = (p_robust * b - q) / b
            half_kelly = kelly / 2.0
            return max(0.0, min(half_kelly, 0.25))

    def confidence_label(self, source: str) -> str:
        alpha, beta = self.get_prior(source)
        n = alpha + beta - 4  # restamos el prior inicial (2+2)
        if n < 5:
            return "baja (pocas muestras)"
        elif n < 20:
            return "media"
        else:
            return "alta"

    def summary(self) -> str:
        lines = ["  BAYESIAN KELLY — Estado de priors:"]
        for src, p in self.priors.items():
            a, b = p["alpha"], p["beta"]
            n = int(a + b - 4)
            wr = self._beta_mean(a, b)
            std = self._beta_std(a, b)
            lines.append(f"  {src:<20} E[p]={wr:.2%} ±{std:.2%}  n={n}")
        return "\n".join(lines)


# ==============================================================================
#  PERSISTENCIA
# ==============================================================================

def load_db() -> dict:
    if DB_FILE.exists():
        return json.loads(DB_FILE.read_text())
    return {
        "mode": "paper" if PAPER_MODE else "real",
        "bank": STARTING_BANK,
        "deployed": 0.0,
        "positions": [],
        "closed": [],
        "stats": {
            "trades": 0, "wins": 0, "losses": 0,
            "total_pnl": 0.0, "stop_losses": 0, "take_profits": 0,
        },
    }

def save_db(db: dict):
    DB_FILE.write_text(json.dumps(db, indent=2, default=str))

def load_priors() -> BayesianKelly:
    if PRIOR_FILE.exists():
        priors = json.loads(PRIOR_FILE.read_text())
    else:
        priors = {}
    return BayesianKelly(priors)

def save_priors(bk: BayesianKelly):
    PRIOR_FILE.write_text(json.dumps(bk.priors, indent=2))

def log_event(event: dict):
    event["ts"] = datetime.now(timezone.utc).isoformat()
    event["mode"] = "paper" if PAPER_MODE else "real"
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(event, default=str) + "\n")


# ==============================================================================
#  CAPA DE DATOS — Polymarket APIs
# ==============================================================================

def get_markets(limit=200) -> list:
    try:
        r = httpx.get(f"{GAMMA}/markets", params={
            "active": True, "closed": False,
            "limit": limit, "_sort": "volume:desc",
        }, timeout=25)
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        print(f"  [!] Error obteniendo mercados: {e}")
        return []

def get_orderbook(token_id: str) -> Optional[dict]:
    try:
        r = httpx.get(f"{CLOB}/book", params={"token_id": token_id}, timeout=10)
        if r.status_code != 200:
            return None
        ob = r.json()
        bids = [(float(b["price"]), float(b["size"])) for b in ob.get("bids", [])]
        asks = [(float(a["price"]), float(a["size"])) for a in ob.get("asks", [])]
        if not bids or not asks:
            return None
        best_bid = max(bids, key=lambda x: x[0])[0]
        best_ask = min(asks, key=lambda x: x[0])[0]
        mid = (best_bid + best_ask) / 2
        spread = best_ask - best_bid
        # Liquidez total estimada (primeros 5 niveles)
        bid_liq = sum(p * s for p, s in bids[:5])
        ask_liq = sum(p * s for p, s in asks[:5])
        return {
            "best_bid": best_bid, "best_ask": best_ask,
            "mid": mid, "spread": spread,
            "bid_liquidity": bid_liq, "ask_liquidity": ask_liq,
            "bids": bids[:5], "asks": asks[:5],
        }
    except Exception:
        return None

def get_recent_trades(condition_id: str, limit=150) -> list:
    try:
        r = httpx.get(f"{CLOB}/trades",
                      params={"market": condition_id, "limit": limit}, timeout=12)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []

def get_market_detail(condition_id: str) -> Optional[dict]:
    try:
        r = httpx.get(f"{GAMMA}/markets", params={"id": condition_id}, timeout=10)
        data = r.json()
        return data[0] if isinstance(data, list) and data else None
    except Exception:
        return None

def get_clob_token_ids(condition_id: str) -> tuple[Optional[str], Optional[str]]:
    """Obtiene yes_token_id y no_token_id del CLOB (formato correcto de 77 dígitos)."""
    data = get_clob_market_data(condition_id)
    if data:
        return data["yes_token_id"], data["no_token_id"]
    return None, None

def get_clob_market_data(condition_id: str) -> Optional[dict]:
    """
    Una sola llamada al CLOB: token IDs + precios actuales.
    Reemplaza get_clob_token_ids() + get_orderbook() para la mayoría de casos.
    """
    try:
        r = httpx.get(f"{CLOB}/markets/{condition_id}", timeout=10)
        if r.status_code != 200:
            return None
        m = r.json()
        tokens = m.get("tokens", [])
        yes = next((t for t in tokens if t.get("outcome", "").lower() == "yes"), None)
        no  = next((t for t in tokens if t.get("outcome", "").lower() == "no"), None)
        if not yes or not no:
            return None
        yes_price = float(yes.get("price", 0) or 0)
        no_price  = float(no.get("price", 0)  or 0)
        if yes_price <= 0 or no_price <= 0:
            return None
        # Spread estimado desde la suma (idealmente suman 1.0; desviación = spread)
        price_sum = yes_price + no_price
        spread_est = abs(1.0 - price_sum) + 0.02  # mínimo 2% spread
        return {
            "yes_token_id": yes["token_id"],
            "no_token_id": no["token_id"],
            "yes_price": yes_price,
            "no_price": no_price,
            "price_sum": round(price_sum, 4),
            "spread_est": round(spread_est, 4),
            "accepting_orders": m.get("accepting_orders", False),
        }
    except Exception:
        return None


# ==============================================================================
#  DETECCIÓN DE EDGE — Señales de mispricing
# ==============================================================================

# Base rates empíricos por categoría de pregunta
# Orden importa: más específico primero (se usa el match con mayor edge)
BASE_RATES = {
    # ── Crypto ────────────────────────────────────────────────────────────────
    "bitcoin above 200": 0.20, "btc above 200": 0.20,
    "bitcoin above 150": 0.30, "btc above 150": 0.30,
    "bitcoin above 100": 0.50, "btc above 100": 0.50,
    "bitcoin reach 100": 0.50, "btc reach 100": 0.50,
    "bitcoin hit 100": 0.50,   "btc hit 100": 0.50,
    "bitcoin above": 0.50,     "btc above": 0.50,
    "btc will": 0.48,          "btc hit": 0.45,
    "bitcoin hit": 0.45,       "bitcoin reach": 0.45,
    "eth above 5": 0.40,       "eth above 10": 0.25,
    "eth above": 0.45,         "eth will": 0.45,
    "ethereum above": 0.45,    "ethereum": 0.43,
    "solana above": 0.45,      "sol above": 0.45,
    "crypto": 0.50,

    # ── Macro / Fed ───────────────────────────────────────────────────────────
    "fed rate cut": 0.55,   "fed cut": 0.55,    "rate cut in": 0.55,
    "fed raise": 0.25,      "rate hike": 0.25,  "fed pause": 0.45,
    "fomc": 0.50,           "interest rate": 0.45,
    "recession": 0.25,      "inflation above": 0.50,
    "unemployment": 0.50,   "gdp": 0.50,
    "cpi above": 0.50,      "pce above": 0.50,

    # ── Política EE.UU. ───────────────────────────────────────────────────────
    "trump": 0.60,           "harris": 0.40,    "biden": 0.40,
    "re-elected": 0.55,      "reelected": 0.55, "incumbent": 0.58,
    "senate": 0.50,          "house": 0.50,     "midterm": 0.50,
    "presidential election": 0.50,
    "impeach": 0.15,         "resign": 0.12,    "pardon": 0.45,
    "convicted": 0.35,       "arrested": 0.25,  "indicted": 0.35,
    "tariff": 0.55,          "sanction": 0.50,  "executive order": 0.55,

    # ── Política Mundial ──────────────────────────────────────────────────────
    "election": 0.50,        "prime minister": 0.50,
    "ceasefire": 0.40,       "peace deal": 0.30, "peace agreement": 0.30,
    "war": 0.40,             "invasion": 0.35,   "nato": 0.50,
    "netanyahu": 0.45,       "zelensky": 0.50,   "putin": 0.50,

    # ── Tech / AI ─────────────────────────────────────────────────────────────
    "gpt-5": 0.60,           "o3 ": 0.55,        "gemini": 0.50,
    "openai": 0.55,          "anthropic": 0.55,  "google deepmind": 0.55,
    "ai ": 0.55,             "artificial intelligence": 0.55,
    "ipo ": 0.55,            "launch": 0.55,     "release": 0.58,
    "acquisition": 0.50,     "merger": 0.48,

    # ── Finanzas / Empresas ───────────────────────────────────────────────────
    "bankrupt": 0.15,        "default": 0.18,   "collapse": 0.20,
    "layoff": 0.50,          "earnings": 0.50,

    # ── Deportes: Clasificación / Playoff (50/50 inherente) ──────────────────
    "qualify for the 2026 fifa": 0.50,
    "qualify for the world cup": 0.50,
    "qualify for": 0.50,
    "advance to": 0.50,      "make the playoffs": 0.50,
    "make the finals": 0.50, "reach the finals": 0.50,

    # ── Deportes: Torneo (1/N; usamos avg histórico ~10% para equipos no fav) ──
    # NOTA: solo activa si el precio actual se aleja mucho del promedio del grupo
    "win the 2026 fifa": 0.12,    "win the world cup": 0.12,
    "win the nba": 0.08,          "win the nba finals": 0.08,
    "win the stanley cup": 0.06,  "nhl stanley cup": 0.06,
    "win the super bowl": 0.06,   "super bowl": 0.06,
    "win the masters": 0.04,      "win the us open": 0.04,
    "win the open": 0.04,
    "win the premier league": 0.12, "premier league title": 0.12,
    "win the champions league": 0.07,
    "win la liga": 0.12,          "win the bundesliga": 0.12,
    "relegated from": 0.30,       "finish in the top 4": 0.35,

    # ── Entretenimiento ───────────────────────────────────────────────────────
    "album": 0.45,           "movie": 0.55,      "season": 0.60,
    "oscar": 0.50,           "grammy": 0.50,     "emmy": 0.50,

    # ── Geopolítico / Desastres ───────────────────────────────────────────────
    "earthquake": 0.20,      "hurricane": 0.30,  "pandemic": 0.15,
}

def check_base_rate(question: str, price_yes: float) -> Optional[dict]:
    q = question.lower()
    best_match = None
    best_edge = 0.0
    for kw, rate in BASE_RATES.items():
        if kw in q:
            edge = rate - price_yes
            if abs(edge) > abs(best_edge):
                best_edge = edge
                best_match = (kw, rate)
    if best_match and abs(best_edge) >= MIN_EDGE:
        kw, rate = best_match
        return {
            "source": "base_rate",
            "edge": round(best_edge, 4),
            "base_rate": rate,
            "keyword": kw,
            "direction": "BUY_YES" if best_edge > 0 else "BUY_NO",
        }
    return None

def check_overreaction(condition_id: str, lookback_h=24) -> Optional[dict]:
    trades = get_recent_trades(condition_id)
    if len(trades) < 15:
        return None

    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - lookback_h * 3600 * 1000

    recent, old = [], []
    for t in trades:
        ts = t.get("timestamp") or t.get("created_at") or 0
        if isinstance(ts, str):
            try:
                ts = int(datetime.fromisoformat(
                    ts.replace("Z", "+00:00")).timestamp() * 1000)
            except Exception:
                continue
        price = float(t.get("price", 0) or 0)
        if price <= 0.01 or price >= 0.99:
            continue
        (recent if ts >= cutoff_ms else old).append(price)

    if len(recent) < 5 or len(old) < 5:
        return None

    p_now = mean(recent[-8:])
    p_old = mean(old[:8])
    change = p_now - p_old

    if abs(change) < 0.18:  # Movimiento < 18% no cuenta como overreaction
        return None

    # Asumimos reversión parcial del 40%
    edge = abs(change) * 0.40
    if edge < MIN_EDGE:
        return None

    direction = "BUY_NO" if change > 0 else "BUY_YES"
    return {
        "source": "overreaction",
        "edge": round(edge, 4),
        "change_24h": round(change, 4),
        "price_now": round(p_now, 4),
        "price_old": round(p_old, 4),
        "direction": direction,
    }

def check_wide_spread(ob: dict) -> Optional[dict]:
    """
    Mercados con spread ancho en zona de alta incertidumbre (mid 0.35-0.65)
    ofrecen edge al tomar posición en la dirección del mid.
    """
    spread = ob["spread"]
    mid = ob["mid"]
    if 0.35 <= mid <= 0.65 and spread >= 0.07:
        edge = spread * 0.45  # Capturamos ~45% del spread como edge
        if edge < MIN_EDGE:
            return None
        direction = "BUY_YES" if mid < 0.50 else "BUY_NO"
        return {
            "source": "wide_spread",
            "edge": round(edge, 4),
            "spread": round(spread, 4),
            "mid": round(mid, 4),
            "direction": direction,
        }
    return None

def check_yes_no_sum(clob_data: dict) -> Optional[dict]:
    """
    Detecta cuando YES_price + NO_price se desvía de 1.0.
    - sum < 0.90: ambos tokens subvalorados (edge comprando el más alejado del fair value)
    - sum > 1.10: vigorish excesivo (evitar, o BUY_NO si YES está inflado)
    """
    price_sum = clob_data.get("price_sum", 1.0)
    yes_price = clob_data.get("yes_price", 0.5)
    no_price  = clob_data.get("no_price", 0.5)

    # Sum bajo: hay liquidez insuficiente o mispricing a favor del comprador
    if price_sum < 0.90:
        gap = 1.0 - price_sum
        edge = gap * 0.6  # capturamos ~60% del gap
        if edge < MIN_EDGE:
            return None
        # Comprar el que tiene más descuento respecto a fair value (0.5 base)
        yes_discount = 0.5 - yes_price if yes_price < 0.5 else 0
        no_discount  = 0.5 - no_price  if no_price  < 0.5 else 0
        direction = "BUY_YES" if yes_discount >= no_discount else "BUY_NO"
        return {
            "source": "sum_arb",
            "edge": round(edge, 4),
            "direction": direction,
            "price_sum": price_sum,
            "yes_price": yes_price,
            "no_price": no_price,
        }

    # Sum alto: market maker cobrando mucho vig o yes está inflado
    if price_sum > 1.10:
        gap = price_sum - 1.0
        edge = gap * 0.5
        if edge < MIN_EDGE:
            return None
        # El que tiene precio más alto está más overpriced -> BUY_NO de ese
        direction = "BUY_NO" if yes_price > no_price else "BUY_YES"
        return {
            "source": "sum_arb",
            "edge": round(edge, 4),
            "direction": direction,
            "price_sum": price_sum,
            "yes_price": yes_price,
            "no_price": no_price,
        }
    return None


def check_volume_spike(m: dict, price_yes: float) -> Optional[dict]:
    """
    Detecta picos de volumen 24h inusuales (>3x el promedio diario).
    Indica actividad informada reciente → precio podría moverse más.
    Edge: si ya se movió, hay momentum; si no, hay información pendiente de pricear.
    """
    vol_24h = float(m.get("volume24hr") or m.get("volumeNum24hr") or 0)
    vol_total = float(m.get("volumeClob") or m.get("volume") or 0)

    if vol_24h <= 0 or vol_total <= 0:
        return None

    # Días de vida estimados desde volumen total (mínimo 7 para evitar mercados nuevos)
    days_old = vol_total / max(vol_24h, 1)
    if days_old < 7:
        return None

    avg_daily = vol_total / max(days_old, 1)
    spike_ratio = vol_24h / max(avg_daily, 1)

    if spike_ratio < 2.5:
        return None

    # Spike alto + precio en zona de incertidumbre = señal de movimiento
    if price_yes < 0.20 or price_yes > 0.80:
        return None  # mercado ya casi resuelto

    edge = min(0.10, (spike_ratio - 2.5) * 0.015)
    if edge < MIN_EDGE:
        return None

    # Dirección: si precio < 0.5, el spike sugiere BUY_YES (más compradores)
    direction = "BUY_YES" if price_yes <= 0.50 else "BUY_NO"
    return {
        "source": "volume_spike",
        "edge": round(edge, 4),
        "direction": direction,
        "spike_ratio": round(spike_ratio, 2),
        "vol_24h": round(vol_24h),
        "avg_daily": round(avg_daily),
    }


def check_tournament_relative_value(m: dict, markets_pool: list,
                                     price_yes: float) -> Optional[dict]:
    """
    Detecta anomalías de precio relativo en grupos de mercados del mismo torneo.
    Si la suma de todos los precios del grupo > 115%, los overpriced son
    candidatos a BUY_NO. Si suma < 85%, los underpriced son BUY_YES.

    Estrategia: comprar el equipo/candidato con precio más bajo relativo
    a lo que debería ser su fair share.
    """
    question = m.get("question", "")
    q_lower = question.lower()

    # Detectar si es un mercado de torneo ("win the X", "qualify for X")
    TOURNAMENT_PATTERNS = [
        "win the", "win la", "win der", "win le",
        "qualify for", "relegated from", "finish in the top",
        "make the playoffs", "advance to",
    ]
    is_tournament = any(pat in q_lower for pat in TOURNAMENT_PATTERNS)
    if not is_tournament:
        return None

    # Extraer "grupo" por las últimas 3-4 palabras significativas del torneo
    # Ej: "Will X win the NBA Finals?" -> grupo = "win the nba finals"
    group_keywords = []
    for pat in TOURNAMENT_PATTERNS:
        if pat in q_lower:
            idx = q_lower.find(pat)
            group_keywords = q_lower[idx:].split()[:5]
            break

    if not group_keywords:
        return None

    group_tag = " ".join(group_keywords[:4])

    # Buscar mercados del mismo grupo en el pool
    group_markets = []
    for pm in markets_pool:
        pq = pm.get("question", "").lower()
        if group_tag in pq:
            p = float(pm.get("outcomePrices", [0.5])[0] if isinstance(pm.get("outcomePrices"), list)
                      else 0.5)
            if isinstance(pm.get("outcomePrices"), str):
                try:
                    prices = json.loads(pm["outcomePrices"])
                    p = float(prices[0])
                except Exception:
                    p = 0.5
            group_markets.append({"question": pm["question"], "price": p})

    if len(group_markets) < 4:
        return None

    group_prices = [gm["price"] for gm in group_markets]
    price_sum = sum(group_prices)
    n = len(group_markets)
    fair_share = 1.0 / n  # distribución uniforme implícita

    # Solo señal si la suma total es significativa (grupo bien representado)
    if price_sum < 0.5:
        return None

    # Calcular el overpricing/underpricing relativo
    adjusted_fair = price_sum / n  # fair share ajustado a la suma real
    relative_deviation = price_yes - adjusted_fair

    # Señal si el precio está muy alejado del fair share ajustado
    threshold = max(0.08, adjusted_fair * 0.5)  # 50% de desviación o mínimo 8pts
    if abs(relative_deviation) < threshold:
        return None

    edge = abs(relative_deviation) * 0.4
    if edge < MIN_EDGE:
        return None

    direction = "BUY_NO" if relative_deviation > 0 else "BUY_YES"
    return {
        "source": "tournament_rv",
        "edge": round(edge, 4),
        "direction": direction,
        "price_yes": round(price_yes, 4),
        "group_avg": round(adjusted_fair, 4),
        "price_sum": round(price_sum, 4),
        "n_competitors": n,
        "group_tag": group_tag[:50],
    }


def analyze_market(m: dict, markets_pool: Optional[list] = None) -> Optional[dict]:
    """Análisis completo de un mercado. Retorna señal si hay edge."""
    condition_id = m.get("conditionId", "")
    if not condition_id:
        return None

    # ── PASO 1: Filtros rápidos con datos de Gamma (sin calls al CLOB) ────────
    liq = float(m.get("liquidityClob") or m.get("liquidity") or 0)
    vol = float(m.get("volumeClob")    or m.get("volume")    or 0)
    if liq < MIN_LIQUIDITY or vol < MIN_VOLUME:
        return None

    # Filtro de fecha
    end_str = m.get("endDate") or m.get("endDateIso") or m.get("end_date_iso") or ""
    days_left = None
    if end_str:
        try:
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            days_left = (end_dt - datetime.now(timezone.utc)).days
        except Exception:
            pass
    if days_left is not None and days_left < MIN_DAYS_LEFT:
        return None

    # Filtro de spread usando datos de Gamma (sin llamada al CLOB)
    spread_g = 0.0
    best_bid_g = float(m.get("bestBid") or 0)
    best_ask_g = float(m.get("bestAsk") or 0)
    if best_bid_g > 0 and best_ask_g > 0:
        spread_g = best_ask_g - best_bid_g
        if spread_g > MAX_SPREAD:
            return None

    # Pre-filtro de precio con outcomePrices de Gamma (muy rápido)
    outcome_prices = m.get("outcomePrices")
    price_yes_pre = None
    if outcome_prices:
        try:
            op = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
            price_yes_pre = float(op[0])
        except Exception:
            pass
    if price_yes_pre is not None:
        if price_yes_pre > 0.93 or price_yes_pre < 0.07:
            return None  # mercado casi resuelto, skip sin llamar al CLOB

    # ── PASO 2: Obtener datos del CLOB (1 sola llamada: token IDs + precios) ──
    clob_data = get_clob_market_data(condition_id)
    if not clob_data:
        return None

    yes_token = clob_data["yes_token_id"]
    no_token  = clob_data["no_token_id"]
    price_yes = clob_data["yes_price"]
    price_no  = clob_data["no_price"]

    # No operar en mercados casi resueltos
    if price_yes > 0.93 or price_yes < 0.07:
        return None

    # Construir ob básico desde datos CLOB + Gamma
    if best_bid_g > 0 and best_ask_g > 0:
        ob = {
            "best_bid": best_bid_g, "best_ask": best_ask_g,
            "mid": (best_bid_g + best_ask_g) / 2,
            "spread": spread_g,
            "bid_liquidity": liq / 2, "ask_liquidity": liq / 2,
        }
        # Usar precio CLOB si está disponible (más actualizado)
        price_yes = clob_data["yes_price"] if clob_data["yes_price"] > 0 else ob["mid"]
    else:
        # Construir ob desde precios CLOB directos
        ob = {
            "best_bid": price_yes - 0.01,
            "best_ask": price_yes + 0.01,
            "mid": price_yes,
            "spread": clob_data["spread_est"],
            "bid_liquidity": liq / 2, "ask_liquidity": liq / 2,
        }

    if ob["spread"] > MAX_SPREAD:
        return None

    # ── PASO 3: Detección de edge ─────────────────────────────────────────────
    checks = []

    # 1. Sum arbitrage YES+NO (nueva señal, usa datos CLOB directos)
    sa = check_yes_no_sum(clob_data)
    if sa:
        checks.append(sa)

    # 2. Base rate
    br = check_base_rate(m["question"], price_yes)
    if br:
        checks.append(br)

    # 3. Wide spread
    ws = check_wide_spread(ob)
    if ws:
        checks.append(ws)

    # 4. Volume spike (nueva señal)
    vs = check_volume_spike(m, price_yes)
    if vs:
        checks.append(vs)

    # 5. Tournament relative value (nueva señal, solo si hay pool)
    if markets_pool:
        tv = check_tournament_relative_value(m, markets_pool, price_yes)
        if tv:
            checks.append(tv)

    # 6. Overreaction (solo si hay señal previa — es costoso)
    if checks:
        ov = check_overreaction(condition_id)
        if ov:
            checks.append(ov)

    # ── Señales externas (solo si SIGNALS_AVAILABLE) ──────────────────────────
    if SIGNALS_AVAILABLE and checks:
        # 7. Kalshi arbitrage
        try:
            ka = check_kalshi_arb(m["question"], price_yes, min_edge=MIN_EDGE)
            if ka:
                checks.append(ka)
        except Exception:
            pass

        # 8. Manifold signal
        try:
            mf = check_manifold_signal(m["question"], price_yes, min_edge=0.08)
            if mf:
                checks.append(mf)
        except Exception:
            pass

        # 9. Order book imbalance (call adicional al CLOB solo si hay señales)
        dirs_preview = [c["direction"] for c in checks]
        dir_preview = max(set(dirs_preview), key=dirs_preview.count)
        try:
            ob_full = get_orderbook(yes_token)
            if ob_full:
                obi = check_orderbook_imbalance(ob_full, dir_preview)
                if obi:
                    checks.append(obi)
        except Exception:
            pass

        # 10. Whale CLOB
        try:
            dirs_now = [c["direction"] for c in checks]
            dir_now = max(set(dirs_now), key=dirs_now.count)
            wh = check_whale_activity(condition_id, direction_hint=dir_now,
                                      lookback_hours=2)
            if wh and not wh.get("contradicts"):
                checks.append(wh)
            elif wh and wh.get("contradicts"):
                return None  # smart money en contra
        except Exception:
            pass

    if not checks:
        return None

    # ── Consenso de dirección ─────────────────────────────────────────────────
    dirs = [c["direction"] for c in checks]
    direction = max(set(dirs), key=dirs.count)

    if dirs.count(direction) < len(dirs) * 0.6:
        return None  # señales contradictorias

    all_edges = [c["edge"] for c in checks if c["direction"] == direction and c["edge"] > 0]
    if not all_edges:
        return None
    composite_edge = sum(all_edges) / len(all_edges)

    if composite_edge < MIN_EDGE:
        return None

    # ── Entry price realista ──────────────────────────────────────────────────
    if direction == "BUY_YES":
        entry_price = min(ob["best_ask"] + SLIPPAGE_EST, 0.97)
    else:
        entry_price = min(price_no + SLIPPAGE_EST, 0.97)

    return {
        "condition_id": condition_id,
        "question": m["question"][:100],
        "end_date": end_str[:10] if end_str else "?",
        "days_left": days_left,
        "price_yes": round(price_yes, 5),
        "price_no": round(price_no, 5),
        "entry_price": round(entry_price, 5),
        "direction": direction,
        "composite_edge": round(composite_edge, 5),
        "checks": checks,
        "liquidity": liq,
        "volume": vol,
        "spread": round(ob["spread"], 5),
        "yes_token_id": yes_token,
        "no_token_id": no_token,
    }


# ==============================================================================
#  MOTOR DE ÓRDENES — Paper mode vs Real mode
# ==============================================================================

def execute_order(signal: dict, size_usd: float, db: dict) -> bool:
    """
    Punto central de ejecución. En PAPER_MODE simula la orden.
    En modo real llama al CLOB de Polymarket.
    """
    if PAPER_MODE:
        return _paper_fill(signal, size_usd, db)
    else:
        return _real_fill(signal, size_usd, db)

def _paper_fill(signal: dict, size_usd: float, db: dict) -> bool:
    """Simula un fill: registra posición virtual."""
    entry = signal["entry_price"]
    shares = round(size_usd / entry, 4)

    position = {
        "id": f"P{int(time.time())}",
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "condition_id": signal["condition_id"],
        "question": signal["question"],
        "end_date": signal["end_date"],
        "days_left": signal["days_left"],
        "direction": signal["direction"],
        "entry_price": entry,
        "size_usd": size_usd,
        "shares": shares,
        "composite_edge": signal["composite_edge"],
        "edge_sources": [c["source"] for c in signal["checks"]],
        "primary_source": signal["checks"][0]["source"],
        "yes_token_id": signal["yes_token_id"],
        "no_token_id": signal["no_token_id"],
        "status": "open",
        "current_price": entry,
        "unrealized_pnl": 0.0,
        "high_watermark": entry,  # para trailing stop
        "stop_loss_price": round(entry * (1 + STOP_LOSS_PCT), 5),
        "take_profit_price": round(entry * (1 + TAKE_PROFIT_PCT), 5),
    }

    db["positions"].append(position)
    db["deployed"] = round(db["deployed"] + size_usd, 2)
    save_db(db)
    log_event({"type": "OPEN_PAPER", "position": position})

    print(f"""
  [OK] POSICIÓN ABIERTA [PAPER]
     ID:         {position['id']}
     Mercado:    {position['question'][:70]}
     Dir:        {position['direction']} @ ${entry:.4f}
     Tamaño:     ${size_usd:.2f}  ({shares:.2f} shares)
     Edge:       {position['composite_edge']:.2%}
     Stop-loss:  ${position['stop_loss_price']:.4f}
     Take-profit:${position['take_profit_price']:.4f}
     Vence:      {position['end_date']} ({position['days_left']} días)""")
    return True

def _real_fill(signal: dict, size_usd: float, db: dict) -> bool:
    """
    Ejecuta una orden real en el CLOB de Polymarket.
    Requiere: POLYMARKET_PK, POLYMARKET_API_KEY, POLYMARKET_API_SECRET,
              POLYMARKET_API_PASSPHRASE en variables de entorno.
    """
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.constants import POLYGON

        pk = os.environ.get("POLYMARKET_PK")
        if not pk:
            print("  [!] POLYMARKET_PK no configurada. Abortando.")
            return False

        client = ClobClient(
            host="https://clob.polymarket.com",
            key=pk,
            chain_id=POLYGON,
            signature_type=2,
        )
        creds = client.create_or_derive_api_creds()
        client.set_api_creds(creds)

        token_id = (signal["yes_token_id"] if signal["direction"] == "BUY_YES"
                    else signal["no_token_id"])

        order = client.create_order(OrderArgs(
            token_id=token_id,
            price=signal["entry_price"],
            size=round(size_usd / signal["entry_price"], 4),
            side="BUY",
            order_type=OrderType.GTC,
        ))
        resp = client.post_order(order)

        if resp.get("success"):
            position = {
                "id": resp.get("orderID", f"R{int(time.time())}"),
                "opened_at": datetime.now(timezone.utc).isoformat(),
                "condition_id": signal["condition_id"],
                "question": signal["question"],
                "end_date": signal["end_date"],
                "days_left": signal["days_left"],
                "direction": signal["direction"],
                "entry_price": signal["entry_price"],
                "size_usd": size_usd,
                "shares": round(size_usd / signal["entry_price"], 4),
                "composite_edge": signal["composite_edge"],
                "edge_sources": [c["source"] for c in signal["checks"]],
                "primary_source": signal["checks"][0]["source"],
                "yes_token_id": signal["yes_token_id"],
                "no_token_id": signal["no_token_id"],
                "status": "open",
                "current_price": signal["entry_price"],
                "unrealized_pnl": 0.0,
                "high_watermark": signal["entry_price"],
                "stop_loss_price": round(signal["entry_price"] * (1 + STOP_LOSS_PCT), 5),
                "take_profit_price": round(signal["entry_price"] * (1 + TAKE_PROFIT_PCT), 5),
                "clob_order_id": resp.get("orderID"),
            }
            db["positions"].append(position)
            db["deployed"] = round(db["deployed"] + size_usd, 2)
            save_db(db)
            log_event({"type": "OPEN_REAL", "position": position, "clob_resp": resp})
            print(f"  [OK] ORDEN REAL ENVIADA | ID: {position['id']}")
            return True
        else:
            print(f"  [!] Error CLOB: {resp}")
            return False

    except ImportError:
        print("  [!] py-clob-client no instalado. pip install py-clob-client")
        return False
    except Exception as e:
        print(f"  [!] Error en ejecución real: {e}")
        return False


# ==============================================================================
#  GESTIÓN DE POSICIONES — Stop-loss, Take-profit, Resolve
# ==============================================================================

def _close_position(pos: dict, final_price: float, reason: str,
                    db: dict, bk: BayesianKelly):
    """Cierra una posición y actualiza stats + priors bayesianos."""
    pnl = (final_price - pos["entry_price"]) * pos["shares"]
    won = pnl > 0
    ret_pct = pnl / pos["size_usd"] * 100

    pos["status"] = "closed"
    pos["closed_at"] = datetime.now(timezone.utc).isoformat()
    pos["close_reason"] = reason
    pos["final_price"] = round(final_price, 5)
    pos["realized_pnl"] = round(pnl, 3)
    pos["return_pct"] = round(ret_pct, 2)

    db["deployed"] = round(db["deployed"] - pos["size_usd"], 2)
    db["bank"] = round(db["bank"] + pos["size_usd"] + pnl, 2)
    db["stats"]["trades"] += 1
    db["stats"]["wins" if won else "losses"] += 1
    db["stats"]["total_pnl"] = round(db["stats"]["total_pnl"] + pnl, 3)
    if reason == "stop_loss":
        db["stats"]["stop_losses"] = db["stats"].get("stop_losses", 0) + 1
    if reason == "take_profit":
        db["stats"]["take_profits"] = db["stats"].get("take_profits", 0) + 1

    # Actualizar priors Bayesianos por fuente de edge
    for src in pos.get("edge_sources", [pos.get("primary_source", "unknown")]):
        bk.update(src, won)
    save_priors(bk)

    db["closed"].append(pos)
    log_event({"type": f"CLOSE_{reason.upper()}", "position": pos})

    icon = "[OK]" if won else "[X]"
    print(f"""
  {icon} CERRADA [{reason.upper()}]: {pos['question'][:65]}
     {pos['direction']} | Entrada {pos['entry_price']:.4f} -> Final {pos['final_price']:.4f}
     P&L: ${pnl:+.2f} ({ret_pct:+.1f}%)  |  Banco: ${db['bank']:.2f}""")


def cmd_update():
    """Actualiza precios y aplica stop-loss / take-profit."""
    db = load_db()
    bk = load_priors()

    if not db["positions"]:
        print("  No hay posiciones abiertas.")
        return

    print(f"\n{'='*65}")
    print(f"  ACTUALIZANDO {len(db['positions'])} posiciones...")
    print(f"{'='*65}")

    closed_ids = []
    for pos in db["positions"]:
        if pos["status"] != "open":
            continue

        ob = get_orderbook(pos["yes_token_id"])
        if not ob:
            print(f"  [!] Sin datos para {pos['id']}")
            continue

        # Precio actual según dirección
        if pos["direction"] == "BUY_YES":
            current = ob["mid"]
        else:
            current = 1.0 - ob["mid"]

        pos["current_price"] = round(current, 5)
        pos["unrealized_pnl"] = round(
            (current - pos["entry_price"]) * pos["shares"], 3)

        # Actualizar high watermark
        if current > pos.get("high_watermark", pos["entry_price"]):
            pos["high_watermark"] = current

        pct = (current - pos["entry_price"]) / pos["entry_price"]

        # -- Stop-loss ------------------------------------------------------
        if pct <= STOP_LOSS_PCT:
            _close_position(pos, current, "stop_loss", db, bk)
            closed_ids.append(pos["id"])
            continue

        # -- Take-profit ----------------------------------------------------
        if pct >= TAKE_PROFIT_PCT:
            _close_position(pos, current, "take_profit", db, bk)
            closed_ids.append(pos["id"])
            continue

        icon = "[+]" if pct >= 0 else "[-]"
        print(f"  {icon} {pos['id']} | {pos['direction']} | "
              f"entrada={pos['entry_price']:.4f} actual={current:.4f} "
              f"P&L={pos['unrealized_pnl']:+.2f} ({pct:+.1%})")

    db["positions"] = [p for p in db["positions"] if p["id"] not in closed_ids]
    save_db(db)


def cmd_resolve():
    """Resuelve posiciones donde el mercado ya cerró."""
    db = load_db()
    bk = load_priors()

    print(f"\n{'='*65}")
    print(f"  VERIFICANDO RESOLUCIONES...")
    print(f"{'='*65}")

    resolved = 0
    closed_ids = []

    for pos in db["positions"]:
        if pos["status"] != "open":
            continue

        detail = get_market_detail(pos["condition_id"])
        if not detail:
            continue

        is_closed   = detail.get("closed", False)
        is_resolved = detail.get("resolved", False)

        if not (is_closed or is_resolved):
            # Verificar si la end_date ya pasó
            end_str = pos.get("end_date", "")
            if end_str and end_str != "?":
                try:
                    end_dt = datetime.fromisoformat(end_str + "T23:59:59+00:00")
                    if datetime.now(timezone.utc) < end_dt:
                        continue
                except Exception:
                    pass
            else:
                continue

        # Obtener precio final
        final_price_yes = None
        op = detail.get("outcomePrices")
        if op:
            try:
                prices = json.loads(op) if isinstance(op, str) else op
                final_price_yes = float(prices[0])
            except Exception:
                pass

        if final_price_yes is None:
            ob = get_orderbook(pos["yes_token_id"])
            if ob:
                mid = ob["mid"]
                final_price_yes = 1.0 if mid > 0.95 else (0.0 if mid < 0.05 else mid)

        if final_price_yes is None:
            print(f"  [!]  Sin precio final: {pos['question'][:60]}")
            continue

        final_price = (final_price_yes if pos["direction"] == "BUY_YES"
                       else 1.0 - final_price_yes)
        _close_position(pos, final_price, "resolution", db, bk)
        closed_ids.append(pos["id"])
        resolved += 1

    db["positions"] = [p for p in db["positions"] if p["id"] not in closed_ids]

    if resolved == 0:
        print("  No hay mercados resueltos pendientes.")
    else:
        save_db(db)
        print(f"\n  {resolved} mercado(s) resuelto(s).")


# ==============================================================================
#  COMANDOS PRINCIPALES
# ==============================================================================

def cmd_scan(auto_open=True):
    db = load_db()
    bk = load_priors()

    mode_str = "[PAPER]" if PAPER_MODE else "[[-] REAL]"
    print(f"\n{'='*65}")
    print(f"  POLYMARKET BOT {mode_str} — SCAN")
    print(f"  Banco: ${db['bank']:.2f} | Desplegado: ${db['deployed']:.2f} | "
          f"Disponible: ${db['bank'] - db['deployed']:.2f}")
    print(f"  Posiciones abiertas: {len(db['positions'])}")
    print(f"{'='*65}\n")

    print("  Descargando mercados top por volumen...")
    markets = get_markets(limit=SCAN_LIMIT)
    if not markets:
        print("  [!] No se pudieron obtener mercados.")
        return

    print(f"  {len(markets)} mercados. Analizando con {len(BASE_RATES)} keywords...\n")

    signals = []
    for i, m in enumerate(markets):
        q = m.get("question", "")[:55]
        sys.stdout.write(f"  [{i+1:03d}/{len(markets)}] {q:<55}\r")
        sys.stdout.flush()
        # Pasar el pool completo para el análisis cross-market (tournament_rv)
        sig = analyze_market(m, markets_pool=markets)
        if sig:
            signals.append(sig)
        time.sleep(0.05)

    print(f"\n\n  {'-'*63}")
    print(f"  SEÑALES CON EDGE ≥ {MIN_EDGE:.0%}: {len(signals)}")
    print(f"  {'-'*63}")

    if not signals:
        print("  No hay mercados con edge suficiente ahora.")
        return

    signals.sort(key=lambda s: s["composite_edge"], reverse=True)

    for i, s in enumerate(signals, 1):
        sources = " + ".join(c["source"] for c in s["checks"])
        primary = s["checks"][0]["source"]
        alpha, beta = bk.get_prior(primary)
        n_hist = int(alpha + beta - 4)
        conf = bk.confidence_label(primary)
        kelly_f = bk.kelly_fraction(primary, s["entry_price"], edge=s["composite_edge"])
        pos_usd = min(kelly_f * STARTING_BANK, MAX_POSITION)

        print(f"""
  [{i}] {s['question'][:72]}
       YES={s['price_yes']:.2%}  NO={s['price_no']:.2%}  spread={s['spread']:.4f}  días={s['days_left']}
       Edge: {s['composite_edge']:+.2%}  Dir: {s['direction']}  Entry: ${s['entry_price']:.4f}
       Señales: {sources}
       Kelly: {kelly_f:.1%} -> ${pos_usd:.0f} USD  |  Confianza Bayesiana: {conf} (n={n_hist})
       Vol: ${s['volume']:>10,.0f}  Liq: ${s['liquidity']:>8,.0f}""")

    if auto_open:
        print(f"\n  {'-'*63}")
        print(f"  Abriendo posiciones (max 5 por scan)...")
        opened = 0
        available = db["bank"] - db["deployed"]

        for s in signals[:5]:
            if db["deployed"] >= MAX_EXPOSURE:
                print(f"\n  [!] Exposición máxima alcanzada (${MAX_EXPOSURE})")
                break

            # Verificar que no estamos ya en este mercado
            if any(p["condition_id"] == s["condition_id"] for p in db["positions"]):
                print(f"  [skip] Ya en posición: {s['question'][:50]}")
                continue

            # Tamaño de posición con Bayesian Kelly
            primary = s["checks"][0]["source"]
            kelly_f = bk.kelly_fraction(primary, s["entry_price"], edge=s["composite_edge"])
            pos_usd = min(kelly_f * STARTING_BANK, MAX_POSITION)
            available = db["bank"] - db["deployed"]
            pos_usd = min(pos_usd, available * 0.5, MAX_POSITION)

            if pos_usd < 10:
                print(f"  [skip] Capital insuficiente (${available:.2f})")
                break

            s["position_usd"] = round(pos_usd, 2)
            if execute_order(s, pos_usd, db):
                opened += 1
                db = load_db()

        print(f"\n  Posiciones abiertas este scan: {opened}")
        if opened > 0:
            print(f"  Banco actualizado: ${db['bank']:.2f} | Desplegado: ${db['deployed']:.2f}")


def cmd_status():
    db = load_db()
    bk = load_priors()
    mode_str = "[PAPER]" if PAPER_MODE else "[[-] REAL]"

    # Actualizar precios silenciosamente
    for pos in db["positions"]:
        if pos["status"] != "open":
            continue
        ob = get_orderbook(pos["yes_token_id"])
        if ob:
            current = ob["mid"] if pos["direction"] == "BUY_YES" else 1.0 - ob["mid"]
            pos["current_price"] = round(current, 5)
            pos["unrealized_pnl"] = round(
                (current - pos["entry_price"]) * pos["shares"], 3)
    save_db(db)

    print(f"\n{'='*65}")
    print(f"  PORTFOLIO {mode_str}  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*65}")
    print(f"  Capital inicial:  ${STARTING_BANK:>8.2f}")
    print(f"  Banco actual:     ${db['bank']:>8.2f}  ({(db['bank']-STARTING_BANK)/STARTING_BANK*100:+.2f}%)")
    print(f"  Desplegado:       ${db['deployed']:>8.2f}")
    print(f"  Disponible:       ${db['bank']-db['deployed']:>8.2f}")

    stats = db["stats"]
    if stats["trades"] > 0:
        wr = stats["wins"] / stats["trades"] * 100
        print(f"\n  TRADES CERRADOS:  {stats['trades']}")
        print(f"  Win Rate:         {wr:.1f}%  ({stats['wins']}W / {stats['losses']}L)")
        print(f"  P&L realizado:    ${stats['total_pnl']:+.2f}")
        if stats.get("stop_losses"):
            print(f"  Stop-losses:      {stats['stop_losses']}")
        if stats.get("take_profits"):
            print(f"  Take-profits:     {stats['take_profits']}")

    open_pos = db["positions"]
    total_unrealized = sum(p.get("unrealized_pnl", 0) for p in open_pos)

    if open_pos:
        print(f"\n  POSICIONES ABIERTAS ({len(open_pos)})  —  P&L no realizado: ${total_unrealized:+.2f}")
        print(f"  {'-'*63}")
        for p in open_pos:
            upnl = p.get("unrealized_pnl", 0)
            pct = upnl / p["size_usd"] * 100 if p["size_usd"] else 0
            icon = "[+]" if upnl >= 0 else "[-]"
            sl = p.get("stop_loss_price", "?")
            tp = p.get("take_profit_price", "?")
            print(f"""
  {icon} {p['id']} | {p['direction']}
     {p['question'][:68]}
     Entrada: {p['entry_price']:.4f} -> Actual: {p.get('current_price', p['entry_price']):.4f}
     ${p['size_usd']:.2f} | P&L: ${upnl:+.2f} ({pct:+.1f}%)
     SL: {sl}  TP: {tp}  |  Vence: {p['end_date']}""")
    else:
        print("\n  No hay posiciones abiertas.")

    # Estado bayesiano
    if bk.priors:
        print(f"\n{bk.summary()}")


def cmd_report():
    db = load_db()
    bk = load_priors()
    mode_str = "[PAPER]" if PAPER_MODE else "[[-] REAL]"

    print(f"\n{'='*65}")
    print(f"  REPORTE DE PERFORMANCE {mode_str}")
    print(f"  Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*65}")

    stats = db["stats"]
    bank = db["bank"]
    total_return = (bank - STARTING_BANK) / STARTING_BANK * 100

    print(f"\n  CAPITAL")
    print(f"  {'Inicial':<22} ${STARTING_BANK:>8.2f}")
    print(f"  {'Actual':<22} ${bank:>8.2f}")
    print(f"  {'Retorno total':<22} {total_return:>+8.2f}%")
    print(f"  {'Desplegado':<22} ${db['deployed']:>8.2f}")

    closed = db["closed"]
    if stats["trades"] > 0:
        wr = stats["wins"] / stats["trades"] * 100
        avg_pnl = stats["total_pnl"] / stats["trades"]

        print(f"\n  TRADES CERRADOS: {stats['trades']}")
        print(f"  {'Win Rate':<22} {wr:.1f}%  ({stats['wins']}W / {stats['losses']}L)")
        print(f"  {'P&L Total':<22} ${stats['total_pnl']:>+8.2f}")
        print(f"  {'P&L Promedio':<22} ${avg_pnl:>+8.2f}")

        if closed:
            returns = [p["return_pct"] for p in closed]
            print(f"  {'Mejor trade':<22} {max(returns):>+8.1f}%")
            print(f"  {'Peor trade':<22} {min(returns):>+8.1f}%")
            if len(returns) > 1:
                print(f"  {'Std retornos':<22} {stdev(returns):>8.1f}%")

            # Sharpe aproximado (usando retornos por trade)
            if len(returns) > 2:
                avg_r = mean(returns)
                std_r = stdev(returns)
                sharpe = avg_r / std_r if std_r > 0 else 0
                print(f"  {'Sharpe (por trade)':<22} {sharpe:>8.2f}")

        # Motivos de cierre
        reasons = {}
        for p in closed:
            r = p.get("close_reason", "resolution")
            reasons[r] = reasons.get(r, 0) + 1
        if reasons:
            print(f"\n  MOTIVOS DE CIERRE")
            for r, n in reasons.items():
                print(f"  {r:<22} {n}")

        # Por fuente de edge
        source_stats: dict = {}
        for p in closed:
            for src in p.get("edge_sources", ["unknown"]):
                if src not in source_stats:
                    source_stats[src] = {"trades": 0, "wins": 0, "pnl": 0.0}
                source_stats[src]["trades"] += 1
                if p.get("realized_pnl", 0) > 0:
                    source_stats[src]["wins"] += 1
                source_stats[src]["pnl"] += p.get("realized_pnl", 0)

        if source_stats:
            print(f"\n  POR FUENTE DE EDGE")
            for src, st in sorted(source_stats.items(),
                                  key=lambda x: x[1]["pnl"], reverse=True):
                wr_s = st["wins"] / st["trades"] * 100 if st["trades"] else 0
                print(f"  {src:<22} {st['trades']} trades | WR {wr_s:.0f}% | "
                      f"P&L ${st['pnl']:+.2f}")

    else:
        print("\n  Sin trades cerrados aún.")

    # Diagnóstico
    print(f"\n{'-'*65}")
    if stats["trades"] >= 10:
        wr = stats["wins"] / stats["trades"] * 100
        if wr >= 60 and stats["total_pnl"] > 0:
            print("  [OK] Edge positivo confirmado. Preparado para escalar.")
        elif wr >= 50 and stats["total_pnl"] > 0:
            print("  [!]  Edge marginal. Necesitas más datos (≥20 trades).")
        else:
            print("  [X] Edge insuficiente. Revisa las señales.")
    else:
        needed = 10 - stats["trades"]
        print(f"  [i] Necesitas {needed} trade(s) más para diagnóstico confiable.")

    # Estado Bayesiano
    if bk.priors:
        print(f"\n{bk.summary()}")

    print(f"\n{'='*65}")


def cmd_loop(interval_min=30):
    print(f"\n  MODO LOOP — ciclo cada {interval_min} min | Ctrl+C para detener")
    print(f"  PAPER_MODE = {PAPER_MODE}")
    try:
        cycle = 0
        while True:
            cycle += 1
            print(f"\n{'-'*65}")
            print(f"  CICLO #{cycle} — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'-'*65}")
            cmd_scan(auto_open=True)
            cmd_update()
            cmd_resolve()
            print(f"\n  Próximo ciclo en {interval_min} min...")
            time.sleep(interval_min * 60)
    except KeyboardInterrupt:
        print("\n\n  Loop detenido.")
        cmd_status()


# ==============================================================================
#  ENTRY POINT
# ==============================================================================

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    PYTHON = "/c/Users/ijsal/Desktop/RBI-Backtester/.venv/Scripts/python.exe"

    if cmd == "scan":
        cmd_scan(auto_open=True)
    elif cmd == "scan-only":
        cmd_scan(auto_open=False)
    elif cmd == "update":
        cmd_update()
    elif cmd == "status":
        cmd_status()
    elif cmd == "resolve":
        cmd_resolve()
    elif cmd == "report":
        cmd_report()
    elif cmd == "loop":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        cmd_loop(interval)
    else:
        print(__doc__)
