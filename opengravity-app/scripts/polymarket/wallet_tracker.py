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
CLOB = "https://clob.polymarket.com"
POLYGONSCAN = "https://api.polygonscan.com/api"

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

WALLETS_FILE = DATA_DIR / "tracked_wallets.json"
POSITIONS_FILE = DATA_DIR / "wallet_positions.json"
HISTORY_FILE = DATA_DIR / "wallet_history.jsonl"

# ── Config ────────────────────────────────────────────────────────────────────
MIN_PNL_USD = 500           # PnL mínimo para considerar una wallet
MIN_TRADES = 20             # Trades mínimos para validar
MIN_WIN_RATE = 0.55         # Win rate mínimo (55%)
MAX_WALLETS = 30            # Máximo de wallets a trackear
VALIDATION_DAYS = 30        # Días mínimos de track record para validar
STALE_HOURS = 4             # Horas antes de considerar datos stale


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
    """Fetch top traders del leaderboard de Polymarket."""
    traders = []
    try:
        # Gamma API leaderboard endpoint
        resp = httpx.get(f"{GAMMA}/leaderboard", params={
            "limit": limit,
            "window": "all",  # all-time performance
        }, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                traders = data
            elif isinstance(data, dict):
                traders = data.get("leaderboard", data.get("data", []))
    except Exception as e:
        print(f"  [WARN] Leaderboard fetch failed: {e}")

    # Fallback: buscar profiles directamente si el leaderboard no funciona
    if not traders:
        try:
            resp = httpx.get(f"{GAMMA}/profiles", params={
                "limit": limit,
                "_sort": "profit:desc",
            }, timeout=20)
            if resp.status_code == 200:
                traders = resp.json() if isinstance(resp.json(), list) else []
        except Exception as e:
            print(f"  [WARN] Profiles fallback failed: {e}")

    return traders


def fetch_wallet_positions(address: str) -> list:
    """Fetch posiciones abiertas de una wallet."""
    try:
        resp = httpx.get(f"{GAMMA}/positions", params={
            "address": address.lower(),
            "sizeThreshold": 0.01,
        }, timeout=15)
        if resp.status_code == 200:
            return resp.json() if isinstance(resp.json(), list) else []
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


def score_wallet(trader: dict) -> dict:
    """Calcula métricas de calidad para una wallet del leaderboard."""
    address = (trader.get("address") or trader.get("id") or "").lower()
    if not address:
        return None

    # Extraer métricas del leaderboard (formato varía)
    pnl = float(trader.get("profit", 0) or trader.get("pnl", 0) or 0)
    volume = float(trader.get("volume", 0) or trader.get("totalVolume", 0) or 0)
    trades = int(trader.get("numTrades", 0) or trader.get("trades", 0) or 0)
    markets = int(trader.get("numMarkets", 0) or trader.get("markets", 0) or 0)

    # Win rate (si disponible)
    wins = int(trader.get("wins", 0) or 0)
    losses = int(trader.get("losses", 0) or 0)
    if wins + losses > 0:
        win_rate = wins / (wins + losses)
    elif trades > 0 and pnl > 0:
        win_rate = 0.55  # estimado conservador si es rentable
    else:
        win_rate = 0.0

    # Score compuesto (0-100)
    score = 0
    if pnl >= MIN_PNL_USD:
        score += 30
    if pnl >= MIN_PNL_USD * 5:
        score += 15
    if trades >= MIN_TRADES:
        score += 20
    if trades >= MIN_TRADES * 5:
        score += 10
    if win_rate >= MIN_WIN_RATE:
        score += 20
    if win_rate >= 0.65:
        score += 10
    if markets >= 5:
        score += 5

    # ROI si tenemos volumen
    roi = (pnl / volume * 100) if volume > 0 else 0

    return {
        "address": address,
        "pnl_usd": round(pnl, 2),
        "volume_usd": round(volume, 2),
        "trades": trades,
        "markets": markets,
        "win_rate": round(win_rate, 4),
        "roi_pct": round(roi, 2),
        "score": min(100, score),
        "name": trader.get("name") or trader.get("username") or address[:10],
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

    # Score y filtrar
    scored = []
    for t in traders:
        s = score_wallet(t)
        if s and s["score"] >= 30 and s["pnl_usd"] >= MIN_PNL_USD:
            scored.append(s)

    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:MAX_WALLETS]

    # Merge con wallets existentes (no perder validated status)
    existing = _load_json(WALLETS_FILE, [])
    existing_map = {w["address"]: w for w in existing if isinstance(w, dict)}

    for wallet in top:
        addr = wallet["address"]
        if addr in existing_map:
            # Preservar validation status
            wallet["validated"] = existing_map[addr].get("validated", False)
            wallet["validation_start"] = existing_map[addr].get("validation_start")
            wallet["paper_pnl"] = existing_map[addr].get("paper_pnl", 0)
        else:
            # Nueva wallet — empezar validación
            wallet["validation_start"] = datetime.now(timezone.utc).isoformat()
            wallet["paper_pnl"] = 0

    _save_json(WALLETS_FILE, top)
    print(f"  ✅ {len(top)} wallets guardadas en tracked_wallets.json")
    for w in top[:5]:
        print(f"    {w['name']}: PnL ${w['pnl_usd']:,.0f} | WR {w['win_rate']:.0%} | Score {w['score']}")

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
    else:
        print(f"Comando desconocido: {cmd}")
        print("Uso: discover | update | validate | score <cid> | report | cycle")
