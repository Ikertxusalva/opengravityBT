# moondev/swarm/coordinator.py
"""
Coordinador del Swarm — ejecuta 5 agentes en paralelo, vota por consenso,
guarda decisión en Qdrant y muestra resultado con Rich.

Uso:
    from moondev.swarm.coordinator import run_swarm
    run_swarm()

    # O desde CLI:
    uv run python moondev/run.py swarm
"""
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from moondev.core.model_factory import ModelFactory
from moondev.swarm.signals import (
    get_funding_signal,
    get_whale_signal,
    get_news_signal,
    get_top_mover_signal,
    get_liquidation_signal,
)

import json as _json
import moondev.config as cfg

console = Console()

# ── Configuración ─────────────────────────────────────────────────────────────

AGENTS = {
    "funding":     (get_funding_signal,     0.25),
    "whale":       (get_whale_signal,       0.25),
    "news":        (get_news_signal,        0.20),
    "top_mover":   (get_top_mover_signal,   0.15),
    "liquidation": (get_liquidation_signal, 0.15),
}

ACTION_SCORE = {"BUY": 1.0, "SELL": -1.0, "NOTHING": 0.0}
BUY_THRESHOLD  =  0.35
SELL_THRESHOLD = -0.35


# ── Core ──────────────────────────────────────────────────────────────────────

def _write_sentiment_json(signals: dict[str, dict]) -> None:
    """
    Agrega news + top_mover + liquidation en sentiment_signals.json.
    execution_agent lo lee con peso 0.05 como señal de sentimiento.
    Usa la señal de mayor confianza que no sea NOTHING.
    """
    sentiment_sources = ["news", "top_mover", "liquidation"]
    candidates = [
        signals[name] for name in sentiment_sources
        if name in signals and signals[name]["action"] != "NOTHING"
    ]

    if candidates:
        best = max(candidates, key=lambda s: s["confidence"])
    else:
        best = {"action": "NOTHING", "confidence": 0, "reason": "sin señales de sentimiento"}

    output = {
        "action":     best["action"],
        "confidence": best["confidence"],
        "reason":     best.get("reason", ""),
        "timestamp":  datetime.utcnow().isoformat(),
        "sources": {
            name: {"action": signals[name]["action"], "confidence": signals[name]["confidence"]}
            for name in sentiment_sources
            if name in signals
        },
    }

    out_path = cfg.DATA_DIR / "sentiment_signals.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        _json.dump(output, f, indent=2)

    console.print(f"[dim]>> sentiment_signals.json -> {best['action']} {best['confidence']}%[/dim]")


def _run_regime(symbol: str = "BTC") -> dict:
    """
    Detecta régimen de mercado (BULL/BEAR/SIDEWAYS/HIGH_VOLATILITY).
    Escribe regime_state.json para que execution_agent lo lea con peso 0.35.
    """
    try:
        from moondev.agents.regime_agent import detect_regime
        from moondev.data.data_fetcher import get_ohlcv

        df = get_ohlcv(symbol, interval="1h", days=90)
        if df is None or len(df) < 50:
            return {}

        regime_data = detect_regime(df)
        regime     = regime_data["regime"]
        confidence = regime_data["confidence"]

        REGIME_COLORS = {
            "BULL": "green", "BEAR": "red",
            "SIDEWAYS": "yellow", "HIGH_VOLATILITY": "magenta",
        }
        color = REGIME_COLORS.get(regime, "white")
        console.print(
            f"[dim]Régimen {symbol}:[/dim] [{color}]{regime}[/{color}] "
            f"[dim]{confidence}%[/dim] — {regime_data['description'][:60]}"
        )

        output = {
            "symbol":    symbol,
            "interval":  "1h",
            "timestamp": datetime.utcnow().isoformat(),
            "regime":    regime,
            "confidence": confidence,
            "description": regime_data["description"],
            "signals":   regime_data["signals"],
            "recommended_strategy": None,
        }
        out_path = cfg.DATA_DIR / "regime_state.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            _json.dump(output, f, indent=2)

        return output

    except Exception as e:
        console.print(f"[dim]regime_agent no disponible: {e}[/dim]")
        return {}


def _collect_signals(model) -> dict[str, dict]:
    """Ejecuta todos los agentes en paralelo y retorna sus señales."""
    results = {}

    def run_agent(name: str, fn, _weight: float) -> tuple[str, dict]:
        try:
            return name, fn(model=model)
        except Exception as e:
            return name, {"action": "NOTHING", "reason": f"exception: {e}", "confidence": 0, "source": name}

    with ThreadPoolExecutor(max_workers=len(AGENTS)) as pool:
        futures = {
            pool.submit(run_agent, name, fn, w): name
            for name, (fn, w) in AGENTS.items()
        }
        for future in as_completed(futures):
            name, signal = future.result()
            results[name] = signal

    return results


def _vote(signals: dict[str, dict]) -> dict:
    """
    Calcula el consenso ponderado por confianza.
    Retorna dict con: action, score, confidence_avg.
    """
    weighted_sum   = 0.0
    weight_total   = 0.0

    for name, signal in signals.items():
        _, weight = AGENTS[name]
        confidence  = signal["confidence"] / 100.0   # 0.0–1.0
        vote_score  = ACTION_SCORE.get(signal["action"], 0.0)
        effective_w = weight * confidence

        weighted_sum  += vote_score * effective_w
        weight_total  += effective_w

    if weight_total == 0:
        return {"action": "HOLD", "score": 0.0, "confidence_avg": 0}

    score = weighted_sum / weight_total

    if score >= BUY_THRESHOLD:
        action = "BUY"
    elif score <= SELL_THRESHOLD:
        action = "SELL"
    else:
        action = "HOLD"

    avg_conf = sum(s["confidence"] for s in signals.values()) / len(signals)

    return {
        "action": action,
        "score": score,
        "confidence_avg": round(avg_conf),
    }


def _print_results(signals: dict[str, dict], consensus: dict) -> None:
    """Muestra tabla de señales y decisión de consenso con Rich."""
    table = Table(title="Swarm — Señales de Agentes", box=box.ROUNDED, show_lines=True)
    table.add_column("Agente",    style="cyan",   width=14)
    table.add_column("Acción",    width=8)
    table.add_column("Conf %",    justify="right", width=7)
    table.add_column("Razón",     style="dim")

    ACTION_COLOR = {"BUY": "green", "SELL": "red", "NOTHING": "dim", "HOLD": "yellow"}

    for name in AGENTS:
        s = signals.get(name, {})
        action = s.get("action", "?")
        color  = ACTION_COLOR.get(action, "white")
        table.add_row(
            name,
            f"[{color}]{action}[/{color}]",
            str(s.get("confidence", 0)),
            s.get("reason", "")[:60],
        )

    console.print(table)

    score    = consensus["score"]
    action   = consensus["action"]
    color    = ACTION_COLOR.get(action, "white")
    conf_avg = consensus["confidence_avg"]

    console.print(Panel(
        f"[bold {color}]{action}[/bold {color}]   score: {score:+.2f}   conf_avg: {conf_avg}%",
        title="[bold]SWARM CONSENSUS[/bold]",
        border_style=color,
        expand=False,
    ))


def _store_to_qdrant(signals: dict[str, dict], consensus: dict) -> None:
    """
    Guarda la decisión de swarm en Qdrant.
    Solo almacena si Qdrant está disponible (importación silenciosa).
    """
    try:
        from src.rbi.mcp.qdrant_store import QdrantStore
        store = QdrantStore()

        timestamp = datetime.utcnow().isoformat()
        votes_str = " | ".join(
            f"{name}: {s['action']} {s['confidence']}%"
            for name, s in signals.items()
        )
        content = (
            f"SWARM DECISION: {consensus['action']} | "
            f"Score: {consensus['score']:+.2f} | "
            f"Conf avg: {consensus['confidence_avg']}% | "
            f"Votos: {votes_str}"
        )

        store.store(
            agent_id="swarm-agent",
            content=content,
            metadata={
                "type": "decision_graph",
                "action": consensus["action"],
                "score": consensus["score"],
                "confidence_avg": consensus["confidence_avg"],
                "timestamp": timestamp,
                "source": "swarm_coordinator",
            },
        )
        console.print(f"[dim]>> Decision guardada en Qdrant[/dim]")
    except Exception:
        console.print("[dim]Qdrant no disponible — decisión no persistida[/dim]")


# ── Entry point ───────────────────────────────────────────────────────────────

def run_swarm() -> dict:
    """
    Ejecuta el pipeline moondev completo:
    halt check → regime → señales → sentimiento → voto → display → qdrant → ejecución.
    """
    # 0. Circuit breaker — si risk_guard activó HALT, no operar
    try:
        from moondev.agents.risk_guard_agent import is_halted
        if is_halted():
            halt_path = cfg.DATA_DIR / "HALT"
            halt_info = _json.load(open(halt_path)) if halt_path.exists() else {}
            console.print(Panel(
                f"[bold red]!! HALT ACTIVO[/bold red]\n{halt_info.get('reason', 'razon desconocida')}",
                border_style="red",
            ))
            return {"action": "HALT", "score": 0.0, "confidence_avg": 0}
    except Exception:
        pass  # risk_guard no disponible → continuar

    console.rule("[bold cyan]SWARM MODE[/bold cyan]")
    console.print(f"[dim]{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} — ejecutando {len(AGENTS)} agentes en paralelo...[/dim]")

    # 1. Detectar régimen de mercado → escribe regime_state.json
    _run_regime()

    model = ModelFactory().get()

    # 2. Recopilar señales en paralelo
    with console.status("[bold green]Recopilando señales...[/bold green]"):
        signals = _collect_signals(model)

    # 3. Persistir señal de sentimiento → escribe sentiment_signals.json
    _write_sentiment_json(signals)

    # 4. Votación ponderada
    consensus = _vote(signals)

    # 5. Display Rich
    _print_results(signals, consensus)

    # 6. Persistir en Qdrant
    _store_to_qdrant(signals, consensus)

    # 7. Llamar execution_agent si hay señal clara
    if consensus["action"] in ("BUY", "SELL"):
        try:
            from moondev.agents.execution_agent import run_cycle
            console.print(f"\n[dim]-> Pasando consenso '{consensus['action']}' a execution_agent...[/dim]")
            run_cycle(symbol="BTC")
        except Exception as e:
            console.print(f"[dim]execution_agent no disponible: {e}[/dim]")

    return consensus


if __name__ == "__main__":
    run_swarm()
