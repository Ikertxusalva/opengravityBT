"""
execution_agent — coloca órdenes en HyperLiquid basado en señales.

Flujo:
  1. Lee régimen actual de data/regime_state.json
  2. Lee señales de otros agentes (funding, whale, sentiment)
  3. Agrega señales con pesos → score total
  4. Si score supera umbral de confianza → calcula size (Kelly / fixed)
  5. Coloca orden en HyperLiquid via exchange_manager
  6. Monitorea SL/TP hasta cierre o timeout

Uso:
    python moondev/agents/execution_agent.py [--dry-run]

Flags:
    --dry-run : simula órdenes sin enviarlas (default: True si no hay private key)
"""
from __future__ import annotations

import sys
import json
import time
import math
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import moondev.config as cfg
from moondev.core.model_factory import ModelFactory
from moondev.core.nice_funcs import get_ohlcv, add_indicators, parse_llm_action
from moondev.data.hyperliquid_data import get_mid_prices as _hl_mid_prices
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

# ── Config ─────────────────────────────────────────────────────────────────────
DRY_RUN          = not bool(cfg.HYPERLIQUID_KEY)   # dry-run si no hay key
CHECK_INTERVAL   = 5 * 60        # 5 min entre ciclos
SIGNAL_TIMEOUT   = 30 * 60       # 30 min para que señal siga vigente
MAX_POSITION_PCT = 0.20          # máximo 20% del portfolio en una posición
MIN_CONFIDENCE   = cfg.STRATEGY_MIN_CONFIDENCE  # 60% default

DATA_DIR  = cfg.DATA_DIR
LOGS_DIR  = DATA_DIR / "execution_logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Archivos de señales de otros agentes
SIGNAL_FILES = {
    "regime":      DATA_DIR / "regime_state.json",
    "funding":     DATA_DIR / "funding" / "funding_signals.csv",
    "whale":       DATA_DIR / "whale"   / "whale_signals.csv",
    "sentiment":   DATA_DIR / "sentiment_signals.json",
}

# Pesos de cada fuente de señal (deben sumar 1.0)
SIGNAL_WEIGHTS = {
    "regime":    0.35,   # régimen de mercado — más peso
    "strategy":  0.30,   # señal directa de estrategia backtestada
    "funding":   0.15,   # funding rate extremo
    "whale":     0.15,   # movimiento ballena
    "sentiment": 0.05,   # sentimiento social
}

SYSTEM_PROMPT = """You are a disciplined algorithmic trading execution agent.
You receive aggregated signals from multiple sources and decide whether to execute a trade.

Respond in exactly 3 lines:
Line 1: BUY, SELL, or NOTHING
Line 2: Brief reason (max 15 words)
Line 3: Confidence: X%

Rules:
- Only trade if multiple signals agree (minimum 2 sources)
- Prefer NOTHING over a bad trade
- Consider current regime — bull favors longs, bear favors shorts
- High volatility regimes require extra caution
"""


# ── Kelly Criterion ────────────────────────────────────────────────────────────
def kelly_size(win_rate: float, avg_win: float, avg_loss: float,
               max_pct: float = MAX_POSITION_PCT) -> float:
    """
    Calcula fracción de Kelly para position sizing.
    f* = (W/L * p - (1-p)) / (W/L)
    Usa half-Kelly para ser conservador.
    """
    if avg_loss <= 0 or avg_win <= 0:
        return 0.02  # fallback conservador
    ratio   = avg_win / avg_loss
    kelly   = (ratio * win_rate - (1 - win_rate)) / ratio
    half_k  = kelly * 0.5  # half-Kelly
    return max(0.01, min(half_k, max_pct))


def fixed_size(confidence: float, base_pct: float = 0.05) -> float:
    """Position sizing fijo escalado por confianza."""
    scale = confidence / 100
    return max(0.01, min(base_pct * scale, MAX_POSITION_PCT))


# ── Lectura de señales ─────────────────────────────────────────────────────────
def read_regime_signal() -> dict:
    """Lee régimen actual desde regime_state.json."""
    path = SIGNAL_FILES["regime"]
    if not path.exists():
        return {"action": "NOTHING", "confidence": 0, "source": "regime"}

    try:
        d = json.load(open(path))
        regime = d.get("regime", "SIDEWAYS")
        conf   = d.get("confidence", 50)

        # Convertir régimen a señal
        if regime == "BULL":
            action = "BUY"
        elif regime == "BEAR":
            action = "SELL"
        else:
            action = "NOTHING"

        return {"action": action, "confidence": conf, "source": "regime",
                "regime": regime, "strategy": d.get("recommended_strategy")}
    except Exception:
        return {"action": "NOTHING", "confidence": 0, "source": "regime"}


def read_csv_signal(path: Path, source: str) -> dict:
    """Lee última señal de un archivo CSV de agente."""
    if not path.exists():
        return {"action": "NOTHING", "confidence": 0, "source": source}
    try:
        import csv
        rows = list(csv.DictReader(open(path)))
        if not rows:
            return {"action": "NOTHING", "confidence": 0, "source": source}
        last = rows[-1]

        # Verificar que la señal no sea demasiado vieja
        ts = last.get("timestamp", "")
        if ts:
            age = (datetime.now(timezone.utc) -
                   datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds()
            if age > SIGNAL_TIMEOUT:
                return {"action": "NOTHING", "confidence": 0,
                        "source": source, "reason": "señal expirada"}

        action = last.get("action", "NOTHING").upper()
        conf   = int(float(last.get("confidence", 0)))
        return {"action": action, "confidence": conf, "source": source}
    except Exception:
        return {"action": "NOTHING", "confidence": 0, "source": source}


def read_json_signal(path: Path, source: str) -> dict:
    """Lee última señal de un archivo JSON."""
    if not path.exists():
        return {"action": "NOTHING", "confidence": 0, "source": source}
    try:
        d = json.load(open(path))
        action = d.get("action", "NOTHING").upper()
        conf   = int(d.get("confidence", 0))
        return {"action": action, "confidence": conf, "source": source}
    except Exception:
        return {"action": "NOTHING", "confidence": 0, "source": source}


def aggregate_signals(signals: list[dict]) -> dict:
    """
    Agrega señales ponderadas.
    BUY = +1, SELL = -1, NOTHING = 0
    Score total en [-1, +1], confidence = promedio ponderado.
    """
    score      = 0.0
    conf_total = 0.0
    weight_sum = 0.0
    active     = []

    for sig in signals:
        action = sig.get("action", "NOTHING")
        conf   = sig.get("confidence", 0) / 100
        source = sig.get("source", "?")
        weight = SIGNAL_WEIGHTS.get(source, 0.1)

        if action not in ("BUY", "SELL"):
            continue

        direction = 1.0 if action == "BUY" else -1.0
        score      += direction * weight * conf
        conf_total += weight * conf
        weight_sum += weight
        active.append({"source": source, "action": action,
                        "confidence": int(conf * 100), "weight": weight})

    # Normalizar score
    norm_score = score / weight_sum if weight_sum > 0 else 0.0
    avg_conf   = (conf_total / weight_sum * 100) if weight_sum > 0 else 0.0

    if norm_score > 0.2:
        final_action = "BUY"
    elif norm_score < -0.2:
        final_action = "SELL"
    else:
        final_action = "NOTHING"

    return {
        "action":      final_action,
        "score":       round(norm_score, 3),
        "confidence":  round(avg_conf, 1),
        "active_signals": active,
        "signal_count": len(active),
    }


# ── Ejecución ─────────────────────────────────────────────────────────────────
def execute_trade(symbol: str, action: str, size_pct: float,
                  price: float, atr: float) -> dict:
    """
    Coloca orden en HyperLiquid (o simula en dry-run).
    size_pct: fracción del portfolio (0.01 = 1%)
    """
    sl_pct = atr / price * 2   # SL = 2x ATR
    tp_pct = atr / price * 4   # TP = 4x ATR (RR 2:1)

    if action == "BUY":
        sl = price * (1 - sl_pct)
        tp = price * (1 + tp_pct)
        side = "long"
    else:
        sl = price * (1 + sl_pct)
        tp = price * (1 - tp_pct)
        side = "short"

    order = {
        "symbol":   symbol,
        "side":     side,
        "size_pct": round(size_pct, 4),
        "entry":    round(price, 4),
        "sl":       round(sl, 4),
        "tp":       round(tp, 4),
        "sl_pct":   round(sl_pct * 100, 2),
        "tp_pct":   round(tp_pct * 100, 2),
        "dry_run":  DRY_RUN,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if DRY_RUN:
        console.print(f"\n[yellow][DRY RUN][/yellow] Orden simulada:")
        console.print(f"  {side.upper()} {symbol} @ {price:.4f}")
        console.print(f"  Size: {size_pct*100:.1f}% portfolio")
        console.print(f"  SL: {sl:.4f} ({sl_pct*100:.1f}%) | TP: {tp:.4f} ({tp_pct*100:.1f}%)")
    else:
        try:
            from moondev.core.exchange_manager import ExchangeManager
            em = ExchangeManager()
            result = em.place_order(symbol, side, size_pct, sl, tp)
            order["exchange_result"] = result
            console.print(f"[bold green]✓ Orden ejecutada en HyperLiquid[/bold green]")
        except Exception as e:
            order["error"] = str(e)
            console.print(f"[red]Error ejecutando orden: {e}[/red]")

    return order


# ── Ciclo principal ────────────────────────────────────────────────────────────
def run_cycle(symbol: str) -> dict:
    """Ejecuta un ciclo completo de análisis y ejecución."""
    console.print(f"\n[dim]{datetime.now().strftime('%H:%M:%S')}[/dim] Analizando {symbol}...")

    # 1. Leer todas las señales
    signals = [
        read_regime_signal(),
        read_csv_signal(SIGNAL_FILES["funding"],   "funding"),
        read_csv_signal(SIGNAL_FILES["whale"],     "whale"),
        read_json_signal(SIGNAL_FILES["sentiment"], "sentiment"),
    ]

    # 2. Agregar señales
    agg = aggregate_signals(signals)

    console.print(f"  Score: {agg['score']:+.3f} | Confianza: {agg['confidence']:.0f}% | "
                  f"Señales activas: {agg['signal_count']}")

    result = {"symbol": symbol, "aggregated": agg, "order": None}

    # 3. Evaluar si ejecutar
    if agg["action"] == "NOTHING":
        console.print("  → NOTHING (sin consenso suficiente)")
        return result

    if agg["confidence"] < MIN_CONFIDENCE:
        console.print(f"  → NOTHING (confianza {agg['confidence']:.0f}% < mínimo {MIN_CONFIDENCE}%)")
        return result

    if agg["signal_count"] < 2:
        console.print(f"  → NOTHING (solo {agg['signal_count']} señal activa, necesita ≥2)")
        return result

    # 4. Obtener precio actual (HL mid) y ATR (OHLCV)
    try:
        mids = _hl_mid_prices()
        price = mids.get(symbol)
        df = get_ohlcv(f"{symbol}-USD", days=14, timeframe="1h")
        df = add_indicators(df)
        if not price:
            price = float(df["close"].iloc[-1])
        atr = float(df.get("atr", df["close"] * 0.02).iloc[-1]) if "atr" in df.columns else price * 0.02
    except Exception as e:
        console.print(f"  [red]Error obteniendo precio: {e}[/red]")
        return result

    # 5. Calcular size
    size_pct = fixed_size(agg["confidence"])

    # 6. Ejecutar
    console.print(f"  [bold]→ {agg['action']} {symbol} @ {price:.4f}[/bold] | Size: {size_pct*100:.1f}%")
    order = execute_trade(symbol, agg["action"], size_pct, price, atr)
    result["order"] = order

    # 7. Log
    log_path = LOGS_DIR / f"orders_{datetime.now().strftime('%Y%m%d')}.json"
    logs = json.load(open(log_path)) if log_path.exists() else []
    logs.append(result)
    with open(log_path, "w") as f:
        json.dump(logs, f, indent=2)

    return result


def main():
    dry = "--dry-run" in sys.argv or DRY_RUN
    symbol = next((sys.argv[i+1] for i, a in enumerate(sys.argv) if a == "--symbol"), "BTC")

    mode = "[yellow]DRY RUN[/yellow]" if dry else "[bold green]LIVE[/bold green]"
    console.print(Panel(
        f"Execution Agent — {symbol}\nModo: {mode}\nIntervalo: {CHECK_INTERVAL//60} min",
        title="Execution Agent"
    ))

    if not dry and not cfg.HYPERLIQUID_KEY:
        console.print("[red]ERROR: HYPERLIQUID_PRIVATE_KEY no configurada en .env[/red]")
        console.print("[yellow]Ejecutando en modo DRY RUN...[/yellow]")

    while True:
        try:
            run_cycle(symbol)
        except KeyboardInterrupt:
            console.print("\n[yellow]Execution Agent detenido.[/yellow]")
            break
        except Exception as e:
            console.print(f"[red]Error en ciclo: {e}[/red]")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
