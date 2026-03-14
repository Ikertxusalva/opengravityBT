"""
Polymarket Paper Trader
=======================
Simula trades con datos reales del CLOB de Polymarket.
NO ejecuta órdenes reales — registra posiciones virtuales y calcula P&L.

Uso:
    python paper_trader.py scan          # Escanear mercados y buscar edge
    python paper_trader.py status        # Ver posiciones abiertas y P&L
    python paper_trader.py resolve       # Resolver mercados cerrados y actualizar P&L
    python paper_trader.py report        # Reporte completo de performance
    python paper_trader.py loop          # Escanear cada 30 min en bucle
"""

import sys
import json
import time
import httpx
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean, stdev
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────
GAMMA = "https://gamma-api.polymarket.com"
CLOB  = "https://clob.polymarket.com"

DATA_DIR  = Path(__file__).parent / "data"
DB_FILE   = DATA_DIR / "paper_positions.json"
LOG_FILE  = DATA_DIR / "paper_log.jsonl"
DATA_DIR.mkdir(exist_ok=True)

# Parámetros del sistema
MIN_VOLUME      = 30_000    # USD mínimo de volumen total
MIN_LIQUIDITY   = 3_000     # USD mínimo en order book
MIN_EDGE        = 0.05      # 5 puntos mínimo de edge
MAX_POSITION    = 200       # USD máximos por posición (paper)
MAX_EXPOSURE    = 2_000     # USD máximos en total (paper)
STARTING_BANK   = 2_000    # Bankroll inicial simulado

# ── Persistencia ─────────────────────────────────────────────────────────────

def load_db() -> dict:
    if DB_FILE.exists():
        return json.loads(DB_FILE.read_text())
    return {
        "bank": STARTING_BANK,
        "deployed": 0.0,
        "positions": [],
        "closed": [],
        "stats": {"trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0},
    }

def save_db(db: dict):
    DB_FILE.write_text(json.dumps(db, indent=2, default=str))

def log_event(event: dict):
    event["ts"] = datetime.now(timezone.utc).isoformat()
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(event, default=str) + "\n")


# ── APIs Polymarket ───────────────────────────────────────────────────────────

def get_markets(limit=50) -> list:
    try:
        r = httpx.get(f"{GAMMA}/markets", params={
            "active": True, "closed": False,
            "limit": limit, "_sort": "volume:desc",
        }, timeout=15)
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        print(f"  [!] Error obteniendo mercados: {e}")
        return []


def get_orderbook(token_id: str) -> Optional[dict]:
    try:
        r = httpx.get(f"{CLOB}/orderbook/{token_id}", timeout=10)
        if r.status_code != 200:
            return None
        ob = r.json()
        bids = [(float(b["price"]), float(b["size"])) for b in ob.get("bids", [])]
        asks = [(float(a["price"]), float(a["size"])) for a in ob.get("asks", [])]
        if not bids or not asks:
            return None
        best_bid = max(bids, key=lambda x: x[0])[0]
        best_ask = min(asks, key=lambda x: x[0])[0]
        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid": (best_bid + best_ask) / 2,
            "spread": best_ask - best_bid,
            "bids": bids[:5],
            "asks": asks[:5],
        }
    except Exception:
        return None


def get_market_detail(condition_id: str) -> Optional[dict]:
    try:
        r = httpx.get(f"{GAMMA}/markets", params={"id": condition_id}, timeout=10)
        data = r.json()
        return data[0] if isinstance(data, list) and data else None
    except Exception:
        return None


def get_recent_trades_for_token(condition_id: str, limit=100) -> list:
    try:
        r = httpx.get(f"{CLOB}/trades", params={"market": condition_id, "limit": limit}, timeout=10)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


# ── Edge Detection ────────────────────────────────────────────────────────────

BASE_RATES = {
    "bitcoin above":   0.52, "btc above":  0.52, "btc will":  0.50,
    "eth above":       0.48, "eth will":   0.48,
    "crypto":          0.50,
    "fed raise":       0.40, "fed cut":    0.45, "rate hike":  0.40,
    "recession":       0.28, "inflation":  0.55,
    "incumbent":       0.62, "president":  0.55,
    "senate":          0.50, "house":      0.50,
    "championship":    0.50, "will win":   0.50,
}

def check_base_rate(question: str, price_yes: float) -> Optional[dict]:
    q = question.lower()
    for kw, rate in BASE_RATES.items():
        if kw in q:
            edge = rate - price_yes
            if abs(edge) >= MIN_EDGE:
                return {
                    "source": "base_rate",
                    "edge": round(edge, 4),
                    "base_rate": rate,
                    "keyword": kw,
                    "direction": "BUY_YES" if edge > 0 else "BUY_NO",
                }
    return None


def check_overreaction(condition_id: str, token_id: str) -> Optional[dict]:
    trades = get_recent_trades_for_token(condition_id)
    if len(trades) < 10:
        return None

    now_ms = int(time.time() * 1000)
    window_ms = 24 * 3600 * 1000
    cutoff_ms = now_ms - window_ms

    recent, old = [], []
    for t in trades:
        ts = t.get("timestamp") or t.get("created_at") or 0
        if isinstance(ts, str):
            try:
                ts = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
            except Exception:
                continue
        price = float(t.get("price", 0) or 0)
        if price <= 0 or price >= 1:
            continue
        (recent if ts >= cutoff_ms else old).append(price)

    if len(recent) < 3 or len(old) < 3:
        return None

    p_now = mean(recent[-5:])
    p_old = mean(old[:5])
    change = p_now - p_old

    if abs(change) < 0.15:
        return None

    edge = abs(change) * 0.35  # reversión esperada parcial
    direction = "BUY_NO" if change > 0 else "BUY_YES"
    return {
        "source": "overreaction",
        "edge": round(edge, 4),
        "change_24h": round(change, 4),
        "price_now": round(p_now, 4),
        "price_old": round(p_old, 4),
        "direction": direction,
    }


def check_spread_value(ob: dict, price_yes: float) -> Optional[dict]:
    """
    Detecta mercados donde el spread es anormalmente ancho
    vs. la incertidumbre implícita — hay edge para el que provee liquidez.
    """
    spread = ob["spread"]
    mid = ob["mid"]
    # Si mid está entre 0.3 y 0.7 (alta incertidumbre) y spread > 0.06 → oportunidad
    if 0.30 <= mid <= 0.70 and spread >= 0.06:
        # Edge = cobrar el spread como market maker en la dirección más probable
        edge = spread / 2  # asumimos que capturamos ~50% del spread
        direction = "BUY_YES" if price_yes < 0.50 else "BUY_NO"
        if edge >= MIN_EDGE:
            return {
                "source": "spread_value",
                "edge": round(edge, 4),
                "spread": round(spread, 4),
                "mid": round(mid, 4),
                "direction": direction,
            }
    return None


def analyze_market(m: dict) -> Optional[dict]:
    """Análisis completo de un mercado. Retorna señal si hay edge."""
    tokens = m.get("tokens", [])
    if len(tokens) < 2:
        return None

    yes_token = tokens[0]["token_id"]
    no_token  = tokens[1]["token_id"]

    ob = get_orderbook(yes_token)
    if not ob:
        return None

    price_yes = ob["mid"]
    liq = float(m.get("liquidity", 0) or 0)
    vol = float(m.get("volume", 0) or 0)

    if liq < MIN_LIQUIDITY or vol < MIN_VOLUME:
        return None

    # Fecha de resolución
    end_str = m.get("endDate") or m.get("end_date_iso") or ""
    days_left = None
    if end_str:
        try:
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            days_left = (end_dt - datetime.now(timezone.utc)).days
        except Exception:
            pass

    if days_left is not None and days_left < 2:
        return None  # muy cercana, no hay tiempo

    # Checks de edge
    checks = []
    br = check_base_rate(m["question"], price_yes)
    if br:
        checks.append(br)

    sv = check_spread_value(ob, price_yes)
    if sv:
        checks.append(sv)

    # overreaction (más lento, solo si ya hay 1 señal)
    if len(checks) >= 1:
        ov = check_overreaction(m["conditionId"], yes_token)
        if ov:
            checks.append(ov)

    if not checks:
        return None

    # Edge compuesto
    edges = [c["edge"] for c in checks]
    composite = sum(edges) / len(edges)

    if composite < MIN_EDGE:
        return None

    # Dirección mayoritaria
    dirs = [c["direction"] for c in checks]
    direction = max(set(dirs), key=dirs.count)

    # Kelly para tamaño de posición
    p_win = price_yes if direction == "BUY_YES" else 1 - price_yes
    entry = price_yes if direction == "BUY_YES" else 1 - price_yes
    b = (1 / entry) - 1
    q = 1 - p_win
    kelly = (p_win * b - q) / b if b > 0 else 0
    half_kelly = max(0, kelly / 2)
    pos_usd = min(half_kelly * STARTING_BANK, MAX_POSITION)

    return {
        "condition_id": m["conditionId"],
        "question": m["question"][:100],
        "end_date": end_str[:10] if end_str else "?",
        "days_left": days_left,
        "price_yes": round(price_yes, 4),
        "price_no": round(1 - price_yes, 4),
        "liquidity": liq,
        "volume": vol,
        "composite_edge": round(composite, 4),
        "direction": direction,
        "entry_price": round(entry, 4),
        "position_usd": round(pos_usd, 2),
        "ev_usd": round(composite * pos_usd, 2),
        "checks": checks,
        "yes_token_id": yes_token,
        "no_token_id": no_token,
        "spread": round(ob["spread"], 5),
    }


# ── Paper Trading Engine ──────────────────────────────────────────────────────

def open_position(signal: dict, db: dict) -> bool:
    """Registra una posición paper si tenemos bankroll suficiente."""
    pos_usd = signal["position_usd"]

    if pos_usd <= 0:
        print(f"  [skip] Kelly negativo para {signal['question'][:60]}")
        return False

    available = db["bank"] - db["deployed"]
    if available < pos_usd:
        pos_usd = round(available * 0.5, 2)  # reducir si poco capital
        if pos_usd < 10:
            print(f"  [skip] Capital insuficiente (disponible: ${available:.2f})")
            return False

    # Verificar que no estemos ya en este mercado
    existing = [p for p in db["positions"] if p["condition_id"] == signal["condition_id"]]
    if existing:
        print(f"  [skip] Ya tenemos posición en este mercado")
        return False

    position = {
        "id": f"P{int(time.time())}",
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "condition_id": signal["condition_id"],
        "question": signal["question"],
        "end_date": signal["end_date"],
        "direction": signal["direction"],
        "entry_price": signal["entry_price"],
        "size_usd": pos_usd,
        "shares": round(pos_usd / signal["entry_price"], 2),
        "composite_edge": signal["composite_edge"],
        "edge_sources": [c["source"] for c in signal["checks"]],
        "yes_token_id": signal["yes_token_id"],
        "no_token_id": signal["no_token_id"],
        "status": "open",
        "current_price": signal["entry_price"],
        "unrealized_pnl": 0.0,
    }

    db["positions"].append(position)
    db["deployed"] = round(db["deployed"] + pos_usd, 2)
    save_db(db)

    log_event({"type": "OPEN", "position": position})

    print(f"""
  ✅ POSICIÓN ABIERTA (paper)
     ID:      {position['id']}
     Mercado: {position['question'][:70]}
     Dir:     {position['direction']} @ {position['entry_price']:.4f}
     Tamaño:  ${pos_usd:.2f} ({position['shares']:.1f} shares)
     Edge:    {position['composite_edge']:.2%}
     Vence:   {position['end_date']}""")
    return True


def update_positions(db: dict):
    """Actualiza precios actuales de posiciones abiertas."""
    if not db["positions"]:
        return

    print("\n  Actualizando precios de posiciones abiertas...")
    for pos in db["positions"]:
        if pos["status"] != "open":
            continue

        ob = get_orderbook(pos["yes_token_id"])
        if not ob:
            continue

        if pos["direction"] == "BUY_YES":
            current = ob["mid"]
        else:
            current = 1 - ob["mid"]

        pos["current_price"] = round(current, 5)
        pnl = (current - pos["entry_price"]) * pos["shares"]
        pos["unrealized_pnl"] = round(pnl, 3)

    save_db(db)


def resolve_positions(db: dict):
    """
    Resuelve posiciones donde el mercado ya cerró.
    Verifica si el mercado está marcado como closed y obtiene el precio final.
    """
    print("\n🔍 Verificando mercados para resolver...")
    resolved = 0

    for pos in db["positions"]:
        if pos["status"] != "open":
            continue

        detail = get_market_detail(pos["condition_id"])
        if not detail:
            continue

        is_closed   = detail.get("closed", False)
        is_resolved = detail.get("resolved", False)
        outcome_prices = detail.get("outcomePrices")

        if not (is_closed or is_resolved):
            # Verificar si el end_date ya pasó
            end_str = pos.get("end_date", "")
            if end_str and end_str != "?":
                try:
                    end_dt = datetime.fromisoformat(end_str + "T00:00:00+00:00")
                    if datetime.now(timezone.utc) < end_dt:
                        continue  # todavía activo
                except Exception:
                    pass
            else:
                continue

        # Determinar resultado final
        final_price_yes = None
        if outcome_prices:
            try:
                if isinstance(outcome_prices, list):
                    final_price_yes = float(outcome_prices[0])
                elif isinstance(outcome_prices, str):
                    prices = json.loads(outcome_prices)
                    final_price_yes = float(prices[0]) if prices else None
            except Exception:
                pass

        if final_price_yes is None:
            # Intentar desde el CLOB
            ob = get_orderbook(pos["yes_token_id"])
            if ob:
                final_price_yes = ob["mid"]
                # Si está muy cerca de 0 o 1, asumir resolución
                if final_price_yes > 0.95:
                    final_price_yes = 1.0
                elif final_price_yes < 0.05:
                    final_price_yes = 0.0

        if final_price_yes is None:
            print(f"  ⚠️  No se pudo obtener precio final para {pos['question'][:60]}")
            continue

        # Calcular P&L final
        if pos["direction"] == "BUY_YES":
            final_price = final_price_yes
        else:
            final_price = 1 - final_price_yes

        pnl = (final_price - pos["entry_price"]) * pos["shares"]
        won = pnl > 0

        pos["status"] = "closed"
        pos["closed_at"] = datetime.now(timezone.utc).isoformat()
        pos["final_price"] = round(final_price, 5)
        pos["final_price_yes"] = round(final_price_yes, 5)
        pos["realized_pnl"] = round(pnl, 3)
        pos["return_pct"] = round(pnl / pos["size_usd"] * 100, 2)

        db["deployed"] = round(db["deployed"] - pos["size_usd"], 2)
        db["bank"] = round(db["bank"] + pos["size_usd"] + pnl, 2)
        db["stats"]["trades"] += 1
        db["stats"]["wins" if won else "losses"] += 1
        db["stats"]["total_pnl"] = round(db["stats"]["total_pnl"] + pnl, 3)

        db["closed"].append(pos)
        log_event({"type": "CLOSE", "position": pos})

        result_icon = "✅" if won else "❌"
        print(f"""
  {result_icon} CERRADA: {pos['question'][:65]}
     Dir:    {pos['direction']} @ entrada {pos['entry_price']:.4f} → final {pos['final_price']:.4f}
     P&L:    ${pnl:+.2f} ({pos['return_pct']:+.1f}%)
     Banco:  ${db['bank']:.2f}""")
        resolved += 1

    db["positions"] = [p for p in db["positions"] if p["status"] != "closed"]
    if resolved == 0:
        print("  No hay mercados que resolver aún.")
    else:
        save_db(db)
    return resolved


# ── Comandos CLI ──────────────────────────────────────────────────────────────

def cmd_scan(auto_open=True):
    """Escanear mercados y buscar edge."""
    db = load_db()
    print(f"\n{'='*65}")
    print(f"  POLYMARKET PAPER TRADER — SCAN")
    print(f"  Banco: ${db['bank']:.2f} | Desplegado: ${db['deployed']:.2f}")
    print(f"  Posiciones abiertas: {len(db['positions'])}")
    print(f"{'='*65}\n")

    print(f"  Descargando top mercados por volumen...")
    markets = get_markets(limit=60)
    if not markets:
        print("  [!] No se pudieron obtener mercados.")
        return

    print(f"  {len(markets)} mercados descargados. Analizando...\n")

    signals = []
    for m in markets:
        sys.stdout.write(f"  Analizando: {m.get('question', '')[:55]:<55}\r")
        sys.stdout.flush()
        sig = analyze_market(m)
        if sig:
            signals.append(sig)
        time.sleep(0.1)  # throttle API

    print(f"\n\n  {'─'*63}")
    print(f"  SEÑALES ENCONTRADAS: {len(signals)}")
    print(f"  {'─'*63}")

    if not signals:
        print("  No hay mercados con edge suficiente en este momento.")
        return

    # Ordenar por edge compuesto
    signals.sort(key=lambda s: s["composite_edge"], reverse=True)

    for i, s in enumerate(signals, 1):
        sources = ", ".join(c["source"] for c in s["checks"])
        print(f"""
  [{i}] {s['question'][:70]}
       YES={s['price_yes']:.2%}  NO={s['price_no']:.2%}  spread={s['spread']:.4f}
       Edge: {s['composite_edge']:+.2%}  Dir: {s['direction']}
       Size: ${s['position_usd']:.0f}  EV: ${s['ev_usd']:.2f}
       Vol: ${s['volume']:>10,.0f}  Liq: ${s['liquidity']:>8,.0f}
       Vence: {s['end_date']} ({s['days_left']} días)
       Fuentes: {sources}""")

    if auto_open:
        print(f"\n  {'─'*63}")
        print(f"  Abriendo posiciones con edge ≥ {MIN_EDGE:.0%}...")
        opened = 0
        for s in signals[:5]:  # max 5 posiciones por scan
            if db["deployed"] >= MAX_EXPOSURE:
                print(f"\n  [!] Exposición máxima alcanzada (${MAX_EXPOSURE})")
                break
            if open_position(s, db):
                opened += 1
                db = load_db()  # reload para deployed actualizado

        print(f"\n  Posiciones abiertas este scan: {opened}")


def cmd_status():
    """Ver estado actual del portfolio."""
    db = load_db()
    update_positions(db)
    db = load_db()

    print(f"\n{'='*65}")
    print(f"  POLYMARKET PAPER TRADER — STATUS")
    print(f"{'='*65}")
    print(f"  Banco actual:    ${db['bank']:.2f}")
    print(f"  Desplegado:      ${db['deployed']:.2f}")
    print(f"  Disponible:      ${db['bank'] - db['deployed']:.2f}")
    print(f"  Retorno vs start: {(db['bank'] - STARTING_BANK) / STARTING_BANK * 100:+.2f}%")

    stats = db["stats"]
    if stats["trades"] > 0:
        win_rate = stats["wins"] / stats["trades"] * 100
        print(f"\n  CERRADAS: {stats['trades']} trades")
        print(f"  Win Rate: {win_rate:.1f}%  ({stats['wins']}W / {stats['losses']}L)")
        print(f"  P&L Total: ${stats['total_pnl']:+.2f}")

    open_pos = db["positions"]
    if open_pos:
        print(f"\n  POSICIONES ABIERTAS ({len(open_pos)}):")
        print(f"  {'─'*63}")
        total_unrealized = 0
        for p in open_pos:
            upnl = p.get("unrealized_pnl", 0)
            total_unrealized += upnl
            pct = upnl / p["size_usd"] * 100 if p["size_usd"] else 0
            icon = "🟢" if upnl >= 0 else "🔴"
            print(f"""
  {icon} {p['id']} | {p['direction']}
     {p['question'][:65]}
     Entrada: {p['entry_price']:.4f} → Actual: {p.get('current_price', p['entry_price']):.4f}
     Size: ${p['size_usd']:.2f} | P&L: ${upnl:+.2f} ({pct:+.1f}%)
     Edge: {p['composite_edge']:.2%} | Vence: {p['end_date']}""")

        print(f"\n  P&L no realizado total: ${total_unrealized:+.2f}")
    else:
        print("\n  No hay posiciones abiertas.")


def cmd_resolve():
    """Resolver mercados cerrados."""
    db = load_db()
    print(f"\n{'='*65}")
    print(f"  POLYMARKET PAPER TRADER — RESOLVE")
    print(f"{'='*65}")
    resolve_positions(db)


def cmd_report():
    """Reporte completo de performance."""
    db = load_db()
    update_positions(db)
    db = load_db()

    print(f"\n{'='*65}")
    print(f"  POLYMARKET PAPER TRADER — PERFORMANCE REPORT")
    print(f"  Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*65}")

    stats = db["stats"]
    bank = db["bank"]
    total_return = (bank - STARTING_BANK) / STARTING_BANK * 100
    deployed = db["deployed"]

    print(f"\n  CAPITAL")
    print(f"  {'Inicial':<20} ${STARTING_BANK:.2f}")
    print(f"  {'Actual':<20} ${bank:.2f}")
    print(f"  {'Retorno total':<20} {total_return:+.2f}%")
    print(f"  {'Desplegado':<20} ${deployed:.2f}")

    if stats["trades"] > 0:
        win_rate = stats["wins"] / stats["trades"] * 100
        avg_pnl = stats["total_pnl"] / stats["trades"]

        print(f"\n  TRADES CERRADOS")
        print(f"  {'Total trades':<20} {stats['trades']}")
        print(f"  {'Ganadas':<20} {stats['wins']}")
        print(f"  {'Perdidas':<20} {stats['losses']}")
        print(f"  {'Win Rate':<20} {win_rate:.1f}%")
        print(f"  {'P&L Total':<20} ${stats['total_pnl']:+.2f}")
        print(f"  {'P&L Promedio':<20} ${avg_pnl:+.2f}")

        if db["closed"]:
            returns = [p["return_pct"] for p in db["closed"]]
            print(f"  {'Mejor trade':<20} {max(returns):+.1f}%")
            print(f"  {'Peor trade':<20} {min(returns):+.1f}%")
            if len(returns) > 1:
                print(f"  {'Std retornos':<20} {stdev(returns):.1f}%")

        # Análisis por dirección
        yes_trades = [p for p in db["closed"] if p["direction"] == "BUY_YES"]
        no_trades  = [p for p in db["closed"] if p["direction"] == "BUY_NO"]

        if yes_trades:
            yes_wr = sum(1 for p in yes_trades if p["realized_pnl"] > 0) / len(yes_trades) * 100
            print(f"\n  POR DIRECCIÓN")
            print(f"  {'BUY_YES':<20} {len(yes_trades)} trades, WR {yes_wr:.0f}%")
        if no_trades:
            no_wr = sum(1 for p in no_trades if p["realized_pnl"] > 0) / len(no_trades) * 100
            print(f"  {'BUY_NO':<20} {len(no_trades)} trades, WR {no_wr:.0f}%")

        # Análisis por fuente de edge
        source_stats: dict = {}
        for p in db["closed"]:
            for src in p.get("edge_sources", []):
                if src not in source_stats:
                    source_stats[src] = {"trades": 0, "wins": 0, "pnl": 0.0}
                source_stats[src]["trades"] += 1
                if p["realized_pnl"] > 0:
                    source_stats[src]["wins"] += 1
                source_stats[src]["pnl"] += p["realized_pnl"]

        if source_stats:
            print(f"\n  POR FUENTE DE EDGE")
            for src, st in source_stats.items():
                wr = st["wins"] / st["trades"] * 100
                print(f"  {src:<20} {st['trades']} trades, WR {wr:.0f}%, P&L ${st['pnl']:+.2f}")

    else:
        print("\n  Sin trades cerrados aún. Ejecuta 'resolve' primero.")

    # Posiciones abiertas
    open_pos = db["positions"]
    if open_pos:
        unrealized = sum(p.get("unrealized_pnl", 0) for p in open_pos)
        print(f"\n  POSICIONES ABIERTAS: {len(open_pos)}")
        print(f"  P&L no realizado:   ${unrealized:+.2f}")

    print(f"\n{'='*65}")

    # Diagnóstico del edge detector
    if stats["trades"] >= 5:
        print("\n  DIAGNÓSTICO DEL EDGE DETECTOR")
        win_rate = stats["wins"] / stats["trades"] * 100
        if win_rate >= 60 and stats["total_pnl"] > 0:
            print("  ✅ Edge positivo confirmado — considera capitalizar real")
        elif win_rate >= 50 and stats["total_pnl"] > 0:
            print("  ⚠️  Edge marginal — necesitas más datos (>20 trades)")
        else:
            print("  ❌ Edge negativo o insuficiente — no escalar a real")
            print("     Analiza qué fuentes de edge están fallando.")


def cmd_loop(interval_min=30):
    """Scan continuo cada N minutos."""
    print(f"\n  MODO LOOP — scan cada {interval_min} min (Ctrl+C para detener)")
    try:
        while True:
            cmd_scan(auto_open=True)
            cmd_resolve()
            print(f"\n  Próximo scan en {interval_min} min... ({datetime.now().strftime('%H:%M')})")
            time.sleep(interval_min * 60)
    except KeyboardInterrupt:
        print("\n\n  Loop detenido.")
        cmd_status()


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "scan":
        cmd_scan(auto_open=True)
    elif cmd == "scan-only":
        cmd_scan(auto_open=False)
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
