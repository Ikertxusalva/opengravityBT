import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

"""
Polymarket Wallet Tracker — Hybrid Signal Model
=================================================
Rastrea top wallets del leaderboard de Polymarket y genera señales de confluencia.

Uso:
    python wallet_tracker.py discover     # Descubrir top wallets del leaderboard
    python wallet_tracker.py update       # Actualizar posiciones de wallets tracked
    python wallet_tracker.py score <cid>  # Confluence score para un mercado
    python wallet_tracker.py report       # Reporte completo de wallets + posiciones

Datos guardados en data/:
    tracked_wallets.json    — Wallets monitoreadas con métricas
    wallet_positions.json   — Posiciones actuales de smart wallets
    wallet_history.jsonl    — Historial de trades de wallets (append-only)
"""

import sys
import json
import time
import httpx
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional
from statistics import mean

# ── APIs ──────────────────────────────────────────────────────────────────────
GAMMA = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
POLYGONSCAN = "https://api.polygonscan.com/api"

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

WALLETS_FILE = DATA_DIR / "tracked_wallets.json"
POSITIONS_FILE = DATA_DIR / "wallet_positions.json"
HISTORY_FILE = DATA_DIR / "wallet_history.jsonl"
COPY_POSITIONS_FILE = DATA_DIR / "copy_positions.json"
COPY_LOG_FILE = DATA_DIR / "copy_log.jsonl"
LAST_DISCOVER_FILE = DATA_DIR / "last_discover.json"

# ── Config ────────────────────────────────────────────────────────────────────
MIN_PNL_USD = 500           # PnL mínimo para considerar una wallet
MIN_TRADES = 20             # Trades mínimos para validar
MIN_WIN_RATE = 0.55         # Win rate mínimo (55%)
MAX_WALLETS = 30            # Máximo de wallets a trackear
VALIDATION_DAYS = 30        # Días mínimos de track record para validar
STALE_HOURS = 4             # Horas antes de considerar datos stale

# Copy Trading config
COPY_ALLOC_PCT = 0.30       # 30% del bank para copy trading
COPY_MAX_PER_TRADE = 150    # USD máximo por copy trade
COPY_MIN_WALLET_SCORE = 50  # Score mínimo para copiar
COPY_DISCARD_DAYS = 7       # Días de pérdidas consecutivas → descarte
COPY_MONITOR_HOURS = 4      # Monitorear posiciones cada 4h
DISCOVER_INTERVAL_HOURS = 24  # Discover diario

# Wallets pinned para copy trading (vacío = usar top N por score)
# Seleccionadas por ser las más ACTIVAS del top 50 con mejor ROI real
PINNED_WALLETS = [
    "0x6a72f61820b26b1fe4d956e17b6dc2a1ea3033ee",  # kch123       — Rank#3  $11M   4.4% ROI | 2 pos activas
    "0x94a428cfa4f84b264e01f70d93d02bc96cb36356",  # GCottrell93  — Rank#24 $3.4M 21.7% ROI | 5 pos activas
    "0xd7f85d0eb0fe0732ca38d9107ad0d4d01b1289e4",  # tdrhrhhd     — Rank#50 $1.8M 13.9% ROI | 14 pos activas
]


def _load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default if default is not None else {}


def _save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, default=str))


def _append_jsonl(path: Path, record: dict):
    with open(path, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


# ── 1. DISCOVER — Fetch leaderboard y filtrar top wallets ────────────────────

def fetch_leaderboard(limit: int = 100) -> list:
    """Fetch top traders del leaderboard de Polymarket via Data API."""
    all_traders = []
    # API max 50 per request, paginate with offset
    for offset in range(0, limit, 50):
        batch = min(50, limit - offset)
        try:
            resp = httpx.get(f"{DATA_API}/v1/leaderboard", params={
                "limit": batch,
                "offset": offset,
                "timePeriod": "ALL",
                "orderBy": "PNL",
            }, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    all_traders.extend(data)
                else:
                    break
            else:
                print(f"  [WARN] Leaderboard API returned {resp.status_code}")
                break
        except Exception as e:
            print(f"  [WARN] Leaderboard fetch failed: {e}")
            break
        time.sleep(0.3)  # Rate limit courtesy
    return all_traders


def fetch_wallet_positions(address: str) -> list:
    """Fetch posiciones abiertas de una wallet via Data API (filtra solo las con valor > 0)."""
    try:
        resp = httpx.get(f"{DATA_API}/v1/positions", params={
            "user": address.lower(),
            "limit": 20,
        }, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            positions = data if isinstance(data, list) else []
            # Solo posiciones con mercado aún abierto (currentValue > 0)
            return [p for p in positions if float(p.get("currentValue", 0) or 0) > 0]
    except Exception:
        pass
    return []


def fetch_wallet_trades(address: str, limit: int = 100) -> list:
    """Fetch trades recientes de una wallet desde el CLOB."""
    try:
        resp = httpx.get(f"{CLOB}/trades", params={
            "maker": address.lower(),
            "limit": limit,
        }, timeout=15)
        if resp.status_code == 200:
            return resp.json() if isinstance(resp.json(), list) else []
    except Exception:
        pass
    return []


def score_wallet(trader: dict) -> dict | None:
    """Calcula métricas de calidad para una wallet del leaderboard."""
    address = (trader.get("proxyWallet") or trader.get("address") or "").lower()
    if not address:
        return None

    pnl = float(trader.get("pnl", 0) or 0)
    volume = float(trader.get("vol", 0) or trader.get("volume", 0) or 0)
    rank = int(trader.get("rank", 999) or 999)
    name = trader.get("userName") or trader.get("name") or address[:10]

    # ROI basado en volumen
    roi = (pnl / volume * 100) if volume > 0 else 0

    # Score compuesto (0-100) basado en PnL, volumen, ROI, rank
    score = 0
    if pnl >= MIN_PNL_USD:
        score += 25
    if pnl >= MIN_PNL_USD * 10:
        score += 15
    if pnl >= MIN_PNL_USD * 50:
        score += 10
    if volume >= 10_000:
        score += 15
    if volume >= 100_000:
        score += 10
    if roi >= 5:
        score += 15
    if roi >= 20:
        score += 10
    if rank <= 50:
        score += 10

    # Filtro mínimo
    if pnl < MIN_PNL_USD:
        return None

    return {
        "address": address,
        "pnl": round(pnl, 2),
        "volume": round(volume, 2),
        "roi_pct": round(roi, 2),
        "rank": rank,
        "score": min(100, score),
        "name": name,
        "trades": 0,  # Se actualiza al hacer update
        "win_rate": 0,  # Se actualiza al hacer update
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "validated": False,
        "validation_start": None,
    }


def cmd_discover():
    """Descubrir y guardar top wallets del leaderboard."""
    print("🔍 Descubriendo top wallets de Polymarket...")

    traders = fetch_leaderboard(limit=200)
    print(f"  Leaderboard: {len(traders)} traders encontrados")

    if not traders:
        print("  ❌ No se pudo obtener el leaderboard. Intentando con trades grandes...")
        # Fallback: buscar wallets con trades grandes en mercados populares
        return

    # Score y filtrar (score_wallet returns None if below MIN_PNL_USD)
    scored = [s for t in traders if (s := score_wallet(t)) is not None]
    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:MAX_WALLETS]

    if not top:
        print("  ❌ Ninguna wallet pasó los filtros mínimos")
        return []

    # Merge con wallets existentes (no perder validated status)
    existing = _load_json(WALLETS_FILE, [])
    existing_map = {w["address"]: w for w in existing if isinstance(w, dict)}

    for wallet in top:
        addr = wallet["address"]
        if addr in existing_map:
            wallet["validated"] = existing_map[addr].get("validated", False)
            wallet["validation_start"] = existing_map[addr].get("validation_start")
            wallet["paper_pnl"] = existing_map[addr].get("paper_pnl", 0)
        else:
            wallet["validation_start"] = datetime.now(timezone.utc).isoformat()
            wallet["paper_pnl"] = 0

    _save_json(WALLETS_FILE, top)
    print(f"  ✅ {len(top)} wallets guardadas en tracked_wallets.json")
    for w in top[:5]:
        print(f"    {w['name']}: PnL ${w['pnl']:,.0f} | ROI {w['roi_pct']:.1f}% | Score {w['score']}")

    return top


# ── 2. UPDATE — Actualizar posiciones de wallets tracked ─────────────────────

def cmd_update():
    """Actualizar posiciones actuales de todas las wallets tracked."""
    wallets = _load_json(WALLETS_FILE, [])
    if not wallets:
        print("  ⚠️ No hay wallets tracked. Ejecuta 'discover' primero.")
        return

    print(f"📊 Actualizando posiciones de {len(wallets)} wallets...")

    all_positions = {}
    for i, wallet in enumerate(wallets):
        addr = wallet["address"]
        positions = fetch_wallet_positions(addr)
        if positions:
            all_positions[addr] = {
                "name": wallet.get("name", addr[:10]),
                "score": wallet.get("score", 0),
                "positions": positions,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            # Log history
            for pos in positions:
                _append_jsonl(HISTORY_FILE, {
                    "wallet": addr,
                    "market": pos.get("title") or pos.get("question", "?"),
                    "condition_id": pos.get("conditionId") or pos.get("condition_id", ""),
                    "side": pos.get("outcome", "?"),
                    "size_usd": float(pos.get("currentValue", 0) or 0),
                    "avg_price": float(pos.get("avgPrice", 0) or 0),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        if (i + 1) % 10 == 0:
            print(f"    {i + 1}/{len(wallets)} wallets procesadas...")
            time.sleep(0.5)  # Rate limit

    _save_json(POSITIONS_FILE, all_positions)

    total_pos = sum(len(v["positions"]) for v in all_positions.values())
    print(f"  ✅ {total_pos} posiciones de {len(all_positions)} wallets guardadas")

    return all_positions


# ── 3. CONFLUENCE SCORE — Smart money alignment para un mercado ──────────────

def get_confluence_score(condition_id: str) -> dict:
    """
    Calcula el confluence score entre el análisis del bot y smart money.

    Retorna:
        direction: "YES" | "NO" | "MIXED"
        score: 0-100 (0=sin datos, 100=máxima confluencia)
        wallets_aligned: N wallets en la misma dirección
        wallets_against: N wallets en dirección contraria
        total_usd_aligned: USD totales de wallets alineadas
        details: lista de wallets con su posición
    """
    positions_data = _load_json(POSITIONS_FILE, {})
    if not positions_data:
        return {"direction": "MIXED", "score": 0, "wallets_aligned": 0,
                "wallets_against": 0, "total_usd_aligned": 0, "details": []}

    wallets = _load_json(WALLETS_FILE, [])
    wallet_scores = {w["address"]: w.get("score", 50) for w in wallets}

    yes_wallets = []
    no_wallets = []
    yes_usd = 0
    no_usd = 0

    for addr, data in positions_data.items():
        for pos in data.get("positions", []):
            cid = (pos.get("conditionId") or pos.get("condition_id") or "").lower()
            if cid != condition_id.lower():
                continue

            outcome = (pos.get("outcome") or "").upper()
            value = float(pos.get("currentValue", 0) or 0)
            w_score = wallet_scores.get(addr, 50)
            entry = {
                "address": addr,
                "name": data.get("name", addr[:10]),
                "wallet_score": w_score,
                "side": outcome,
                "usd": round(value, 2),
            }

            if outcome in ("YES", "LONG", "1"):
                yes_wallets.append(entry)
                yes_usd += value
            elif outcome in ("NO", "SHORT", "0"):
                no_wallets.append(entry)
                no_usd += value

    total_wallets = len(yes_wallets) + len(no_wallets)
    if total_wallets == 0:
        return {"direction": "MIXED", "score": 0, "wallets_aligned": 0,
                "wallets_against": 0, "total_usd_aligned": 0, "details": []}

    # Determinar dirección del smart money
    if yes_usd > no_usd * 1.5 and len(yes_wallets) >= len(no_wallets):
        direction = "YES"
        aligned = len(yes_wallets)
        against = len(no_wallets)
        aligned_usd = yes_usd
    elif no_usd > yes_usd * 1.5 and len(no_wallets) >= len(yes_wallets):
        direction = "NO"
        aligned = len(no_wallets)
        against = len(yes_wallets)
        aligned_usd = no_usd
    else:
        direction = "MIXED"
        aligned = max(len(yes_wallets), len(no_wallets))
        against = min(len(yes_wallets), len(no_wallets))
        aligned_usd = max(yes_usd, no_usd)

    # Score compuesto
    wallet_count_score = min(40, aligned * 10)  # max 40 pts por cantidad
    usd_score = min(30, aligned_usd / 1000 * 10)  # max 30 pts por volumen
    imbalance = aligned / total_wallets if total_wallets > 0 else 0
    imbalance_score = min(30, imbalance * 30)  # max 30 pts por unanimidad

    score = int(wallet_count_score + usd_score + imbalance_score)

    return {
        "direction": direction,
        "score": min(100, score),
        "wallets_aligned": aligned,
        "wallets_against": against,
        "total_usd_aligned": round(aligned_usd, 2),
        "yes_wallets": len(yes_wallets),
        "no_wallets": len(no_wallets),
        "yes_usd": round(yes_usd, 2),
        "no_usd": round(no_usd, 2),
        "details": (yes_wallets + no_wallets)[:10],
    }


# ── 4. VALIDATE — Marcar wallets como validadas tras periodo de prueba ───────

def cmd_validate():
    """Validar wallets que cumplen criterios tras período de observación."""
    wallets = _load_json(WALLETS_FILE, [])
    now = datetime.now(timezone.utc)
    validated_count = 0

    for wallet in wallets:
        if wallet.get("validated"):
            continue

        start = wallet.get("validation_start")
        if not start:
            wallet["validation_start"] = now.isoformat()
            continue

        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        days_tracked = (now - start_dt).days

        if days_tracked >= VALIDATION_DAYS:
            # Verificar que sigue siendo rentable
            if (wallet.get("pnl_usd", 0) >= MIN_PNL_USD and
                    wallet.get("win_rate", 0) >= MIN_WIN_RATE):
                wallet["validated"] = True
                validated_count += 1
                print(f"  ✅ Validada: {wallet['name']} (PnL ${wallet['pnl_usd']:,.0f}, {days_tracked}d)")
            else:
                print(f"  ❌ No validada: {wallet['name']} (métricas insuficientes tras {days_tracked}d)")

    _save_json(WALLETS_FILE, wallets)
    print(f"\n  {validated_count} wallets validadas para trading real")
    return wallets


# ── 5. REPORT — Reporte completo ─────────────────────────────────────────────

def cmd_report():
    """Generar reporte de wallets tracked y sus posiciones."""
    wallets = _load_json(WALLETS_FILE, [])
    positions = _load_json(POSITIONS_FILE, {})

    print("=" * 70)
    print("  POLYMARKET WALLET TRACKER — REPORT")
    print("=" * 70)
    print(f"\n  Wallets tracked: {len(wallets)}")
    print(f"  Wallets con posiciones: {len(positions)}")
    validated = [w for w in wallets if w.get("validated")]
    print(f"  Wallets validadas (real-ready): {len(validated)}")

    print("\n  TOP WALLETS:")
    print(f"  {'Wallet':<15} {'PnL':>10} {'WR':>6} {'Trades':>7} {'Score':>6} {'Valid':>6}")
    print("  " + "-" * 56)
    for w in wallets[:15]:
        v = "✅" if w.get("validated") else "⏳"
        print(f"  {w['name']:<15} ${w['pnl_usd']:>8,.0f} {w['win_rate']:>5.0%} {w['trades']:>7} {w['score']:>6} {v:>6}")

    # Mercados con más smart money
    market_counts = {}
    for addr, data in positions.items():
        for pos in data.get("positions", []):
            title = pos.get("title") or pos.get("question", "?")
            market_counts[title] = market_counts.get(title, 0) + 1

    if market_counts:
        print("\n  MERCADOS CON MÁS SMART MONEY:")
        sorted_markets = sorted(market_counts.items(), key=lambda x: x[1], reverse=True)
        for title, count in sorted_markets[:10]:
            print(f"    {count} wallets → {title[:60]}")

    # Output JSON summary para el panel
    summary = {
        "total_wallets": len(wallets),
        "validated_wallets": len(validated),
        "wallets_with_positions": len(positions),
        "top_wallets": wallets[:15],
        "hot_markets": [{"title": t, "wallet_count": c}
                        for t, c in sorted(market_counts.items(),
                                            key=lambda x: x[1], reverse=True)[:10]],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_json(DATA_DIR / "wallet_summary.json", summary)
    print(f"\n  📄 Resumen guardado en data/wallet_summary.json")


# ── 6. COPY TRADING — Copiar posiciones de top wallets ────────────────────────

def _load_copy_db() -> dict:
    """Cargar o inicializar la base de datos de copy trading."""
    default = {
        "bank": 600,  # 30% de $2000 asignado a copy trading
        "deployed": 0,
        "positions": [],
        "closed": [],
        "stats": {"total_pnl": 0, "wins": 0, "losses": 0, "trades": 0},
        "wallet_pnl": {},  # address → {pnl, last_profit_date}
    }
    db = _load_json(COPY_POSITIONS_FILE, default)
    if "positions" not in db:
        db = default
    return db


def _save_copy_db(db: dict):
    _save_json(COPY_POSITIONS_FILE, db)


def cmd_copy_cycle():
    """Ciclo de copy trading: detectar nuevas posiciones y copiarlas."""
    wallets = _load_json(WALLETS_FILE, [])
    if not wallets:
        print("  [COPY] Sin wallets tracked")
        return

    # Filtrar wallets elegibles (pinned si están definidas, sino por score)
    if PINNED_WALLETS:
        eligible = [w for w in wallets if w["address"] in PINNED_WALLETS
                    and not w.get("discarded", False)]
        print(f"  [COPY] Modo pinned: {len(eligible)}/{len(PINNED_WALLETS)} wallets activas")
    else:
        eligible = [w for w in wallets if w.get("score", 0) >= COPY_MIN_WALLET_SCORE
                    and not w.get("discarded", False)]
    if not eligible:
        print("  [COPY] Sin wallets elegibles para copy trading")
        return

    print(f"  [COPY] {len(eligible)} wallets monitoreadas: {[w['name'] for w in eligible]}")

    # Cargar posiciones anteriores (snapshot) para detectar NUEVAS
    prev_positions = _load_json(POSITIONS_FILE, {})
    first_run = not prev_positions  # True si no hay datos previos

    # Actualizar posiciones actuales
    current_positions = {}
    for w in eligible[:15]:  # Top 15 por score (o todas las pinned)
        addr = w["address"]
        positions = fetch_wallet_positions(addr)
        if positions:
            current_positions[addr] = {
                "name": w.get("name", addr[:10]),
                "score": w.get("score", 0),
                "positions": positions,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        time.sleep(0.3)

    # Guardar posiciones actualizadas
    _save_json(POSITIONS_FILE, current_positions)

    # Detectar NUEVAS posiciones (están en current pero no en prev)
    new_trades = []
    for addr, data in current_positions.items():
        prev = prev_positions.get(addr, {}).get("positions", [])
        prev_cids = {(p.get("conditionId") or p.get("condition_id", "")).lower()
                     for p in prev}

        for pos in data["positions"]:
            cid = (pos.get("conditionId") or pos.get("condition_id", "")).lower()
            if cid and cid not in prev_cids:
                new_trades.append({
                    "wallet": addr,
                    "wallet_name": data["name"],
                    "wallet_score": data["score"],
                    "condition_id": cid,
                    "market": pos.get("title") or pos.get("question", "?"),
                    "direction": (pos.get("outcome") or "YES").upper(),
                    "avg_price": float(pos.get("avgPrice", 0) or 0),
                    "current_price": float(pos.get("curPrice", 0) or pos.get("price", 0) or 0),
                })

    # Primera ejecución: guardar baseline sin abrir trades
    if first_run:
        total = sum(len(d["positions"]) for d in current_positions.values())
        print(f"  [COPY] BASELINE establecido — {total} posiciones actuales ignoradas")
        print(f"         El próximo ciclo detectará posiciones NUEVAS como señales de copy.")
        return

    if not new_trades:
        print("  [COPY] Sin nuevas posiciones detectadas")
        # Actualizar precios de posiciones copy existentes
        _update_copy_prices(current_positions)
        return

    print(f"  [COPY] {len(new_trades)} nuevas posiciones detectadas!")

    # Abrir copy trades
    db = _load_copy_db()
    opened = 0

    for trade in new_trades:
        available = db["bank"] - db["deployed"]
        if available < 10:
            print("  [COPY] Sin capital disponible")
            break

        # Calcular tamaño basado en score de la wallet
        score_mult = trade["wallet_score"] / 100  # 0.5 a 1.0
        size = min(COPY_MAX_PER_TRADE * score_mult, available * 0.3)
        size = round(max(10, size), 2)

        price = trade["current_price"] or trade["avg_price"]
        if price <= 0.05 or price >= 0.95:
            continue  # Evitar extremos

        # Abrir posición copy
        copy_pos = {
            "id": f"copy_{int(time.time())}_{opened}",
            "source_wallet": trade["wallet"],
            "source_name": trade["wallet_name"],
            "condition_id": trade["condition_id"],
            "market": trade["market"],
            "direction": trade["direction"],
            "entry_price": round(price, 4),
            "current_price": round(price, 4),
            "size_usd": size,
            "unrealized_pnl": 0,
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "stop_loss": round(price * 0.6, 4),  # -40%
            "take_profit": round(min(price * 1.8, 0.98), 4),  # +80%
        }

        db["positions"].append(copy_pos)
        db["deployed"] = round(db["deployed"] + size, 2)
        opened += 1

        _append_jsonl(COPY_LOG_FILE, {
            "type": "COPY_OPEN", "position": copy_pos,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        print(f"    COPY: {trade['direction']} {trade['market'][:50]} "
              f"@ {price:.2f} | ${size:.0f} | from {trade['wallet_name']}")

    _save_copy_db(db)
    print(f"  [COPY] {opened} posiciones abiertas. "
          f"Bank: ${db['bank']:.0f} | Deployed: ${db['deployed']:.0f}")

    # Actualizar precios y cerrar SL/TP
    _update_copy_prices(current_positions)


def _update_copy_prices(current_positions: dict):
    """Actualizar precios de copy positions y cerrar por SL/TP."""
    db = _load_copy_db()
    if not db["positions"]:
        return

    # Construir mapa de precios actuales desde las posiciones de wallets
    price_map = {}
    for addr, data in current_positions.items():
        for pos in data.get("positions", []):
            cid = (pos.get("conditionId") or pos.get("condition_id", "")).lower()
            price = float(pos.get("curPrice", 0) or pos.get("price", 0) or 0)
            if cid and price > 0:
                price_map[cid] = price

    to_close = []
    for pos in db["positions"]:
        cid = pos["condition_id"].lower()
        if cid in price_map:
            pos["current_price"] = round(price_map[cid], 4)
            entry = pos["entry_price"]
            current = pos["current_price"]
            if pos["direction"] == "YES":
                pnl_pct = (current - entry) / entry if entry > 0 else 0
            else:
                pnl_pct = (entry - current) / entry if entry > 0 else 0
            pos["unrealized_pnl"] = round(pos["size_usd"] * pnl_pct, 2)

            # Check SL/TP
            if current <= pos["stop_loss"] or current >= pos["take_profit"]:
                to_close.append(pos)

    # Cerrar posiciones por SL/TP
    for pos in to_close:
        pnl = pos["unrealized_pnl"]
        reason = "TAKE_PROFIT" if pnl >= 0 else "STOP_LOSS"
        pos["close_reason"] = reason
        pos["closed_at"] = datetime.now(timezone.utc).isoformat()
        pos["realized_pnl"] = pnl

        db["positions"].remove(pos)
        db["closed"].append(pos)
        db["deployed"] = round(max(0, db["deployed"] - pos["size_usd"]), 2)
        db["bank"] = round(db["bank"] + pnl, 2)
        db["stats"]["total_pnl"] = round(db["stats"]["total_pnl"] + pnl, 2)
        db["stats"]["trades"] += 1
        if pnl >= 0:
            db["stats"]["wins"] += 1
        else:
            db["stats"]["losses"] += 1

        # Track PnL por wallet
        wallet = pos["source_wallet"]
        if wallet not in db["wallet_pnl"]:
            db["wallet_pnl"][wallet] = {"pnl": 0, "trades": 0, "last_profit_date": None}
        db["wallet_pnl"][wallet]["pnl"] = round(db["wallet_pnl"][wallet]["pnl"] + pnl, 2)
        db["wallet_pnl"][wallet]["trades"] += 1
        if pnl >= 0:
            db["wallet_pnl"][wallet]["last_profit_date"] = datetime.now(timezone.utc).isoformat()

        _append_jsonl(COPY_LOG_FILE, {
            "type": "COPY_CLOSE", "position": pos, "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        print(f"    CLOSE [{reason}]: {pos['market'][:40]} | PnL ${pnl:+.2f}")

    _save_copy_db(db)


# ── 7. DISCARD — Descartar wallets perdedoras ────────────────────────────────

def cmd_discard():
    """Descartar wallets que llevan perdiendo más de COPY_DISCARD_DAYS."""
    wallets = _load_json(WALLETS_FILE, [])
    db = _load_copy_db()
    now = datetime.now(timezone.utc)
    discarded = 0

    for wallet in wallets:
        if wallet.get("discarded"):
            continue

        addr = wallet["address"]
        wp = db.get("wallet_pnl", {}).get(addr)
        if not wp:
            continue

        # Si PnL acumulado es negativo y no ha tenido profit en N días
        if wp["pnl"] < 0 and wp.get("last_profit_date"):
            last_profit = datetime.fromisoformat(
                wp["last_profit_date"].replace("Z", "+00:00"))
            days_losing = (now - last_profit).days
            if days_losing >= COPY_DISCARD_DAYS:
                wallet["discarded"] = True
                wallet["discarded_at"] = now.isoformat()
                wallet["discard_reason"] = f"PnL ${wp['pnl']:.2f} tras {days_losing}d sin profit"
                discarded += 1
                print(f"  DISCARD: {wallet['name']} — {wallet['discard_reason']}")
        elif wp["pnl"] < -50 and wp["trades"] >= 3:
            # Pérdida significativa con suficientes trades
            wallet["discarded"] = True
            wallet["discarded_at"] = now.isoformat()
            wallet["discard_reason"] = f"PnL ${wp['pnl']:.2f} en {wp['trades']} trades"
            discarded += 1
            print(f"  DISCARD: {wallet['name']} — {wallet['discard_reason']}")

    _save_json(WALLETS_FILE, wallets)
    if discarded:
        print(f"  {discarded} wallets descartadas")
    else:
        print("  Sin wallets para descartar")
    return wallets


# ── 8. AUTO-DISCOVER — Discover diario automático ────────────────────────────

def should_discover() -> bool:
    """Verificar si toca hacer discover (cada 24h)."""
    last = _load_json(LAST_DISCOVER_FILE, {})
    last_time = last.get("last_discover")
    if not last_time:
        return True
    try:
        last_dt = datetime.fromisoformat(last_time.replace("Z", "+00:00"))
        hours_since = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
        return hours_since >= DISCOVER_INTERVAL_HOURS
    except Exception:
        return True


def mark_discovered():
    """Marcar timestamp del último discover."""
    _save_json(LAST_DISCOVER_FILE, {
        "last_discover": datetime.now(timezone.utc).isoformat(),
    })


def cmd_full_cycle():
    """Ciclo completo: auto-discover + copy + discard + report."""
    print("=" * 60)
    print("  COPY TRADING CYCLE")
    print("=" * 60)

    # 1. Auto-discover diario
    if should_discover():
        print("\n[1/4] DISCOVER (diario)")
        cmd_discover()
        mark_discovered()
    else:
        print("\n[1/4] DISCOVER — skip (último < 24h)")

    # 2. Copy cycle: monitorear + copiar nuevas posiciones
    print("\n[2/4] COPY MONITOR")
    cmd_copy_cycle()

    # 3. Descartar wallets perdedoras
    print("\n[3/4] DISCARD CHECK")
    cmd_discard()

    # 4. Report
    print("\n[4/4] COPY STATUS")
    db = _load_copy_db()
    stats = db.get("stats", {})
    total_pnl = stats.get("total_pnl", 0)
    trades = stats.get("trades", 0)
    wins = stats.get("wins", 0)
    wr = (wins / trades * 100) if trades > 0 else 0
    print(f"  Bank: ${db['bank']:.0f} | Deployed: ${db['deployed']:.0f} | "
          f"PnL: ${total_pnl:+.2f} | WR: {wr:.0f}% ({trades} trades)")
    print(f"  Posiciones abiertas: {len(db.get('positions', []))}")

    active_wallets = len([w for w in _load_json(WALLETS_FILE, [])
                          if not w.get("discarded")])
    discarded_wallets = len([w for w in _load_json(WALLETS_FILE, [])
                             if w.get("discarded")])
    print(f"  Wallets activas: {active_wallets} | Descartadas: {discarded_wallets}")
    print("=" * 60)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"

    if cmd == "discover":
        cmd_discover()
    elif cmd == "update":
        cmd_update()
    elif cmd == "validate":
        cmd_validate()
    elif cmd == "score":
        if len(sys.argv) < 3:
            print("Uso: python wallet_tracker.py score <condition_id>")
            sys.exit(1)
        result = get_confluence_score(sys.argv[2])
        print(json.dumps(result, indent=2))
    elif cmd == "report":
        cmd_discover()
        cmd_update()
        cmd_validate()
        cmd_report()
    elif cmd == "cycle":
        # Ciclo completo para integración con paper_trader
        cmd_update()
        cmd_validate()
        # Generar summary para el panel
        cmd_report()
    elif cmd == "copy":
        cmd_copy_cycle()
    elif cmd == "discard":
        cmd_discard()
    elif cmd == "full-cycle":
        cmd_full_cycle()
    else:
        print(f"Comando desconocido: {cmd}")
        print("Uso: discover | update | validate | score <cid> | report | cycle | copy | discard | full-cycle")
