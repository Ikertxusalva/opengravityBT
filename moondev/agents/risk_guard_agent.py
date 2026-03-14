"""
risk_guard_agent — capa de riesgo y circuit breakers.

Corre en paralelo con el resto del sistema y actúa como guardián:
  1. Daily loss limit: si PnL día < -MAX_DAILY_LOSS_PCT → pausa todo
  2. Drawdown global: lee portfolio_state y alerta si DD > umbral
  3. Correlación: bloquea nuevas posiciones si hay >N activos correlacionados
  4. Concentración: bloquea si un activo supera MAX_SINGLE_EXPOSURE_PCT
  5. Circuit breaker: escribe HALT flag que leen otros agentes

Uso:
    python moondev/agents/risk_guard_agent.py [--monitor]

Flags:
    --monitor : loop continuo (default: una sola evaluación)
"""
from __future__ import annotations

import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone, date
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import moondev.config as cfg
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

# ── Límites de riesgo ──────────────────────────────────────────────────────────
MAX_DAILY_LOSS_PCT       = 3.0     # % pérdida diaria máxima
MAX_DRAWDOWN_ALERT_PCT   = 10.0    # % drawdown para alerta
MAX_DRAWDOWN_HALT_PCT    = 15.0    # % drawdown para halt total
MAX_SINGLE_EXPOSURE_PCT  = 25.0    # % máximo en un solo activo
MAX_TOTAL_EXPOSURE_PCT   = 60.0    # % máximo de portfolio expuesto
MAX_CORRELATED_POSITIONS = 3       # máximo de posiciones correlacionadas
MIN_TRADE_INTERVAL_SEC   = 60      # segundos mínimos entre trades del mismo activo
CHECK_INTERVAL           = 30      # segundos entre evaluaciones en modo monitor

# Grupos de correlación (activos que se mueven juntos)
CORRELATION_GROUPS = {
    "crypto_large":  ["BTC", "ETH"],
    "crypto_alt":    ["SOL", "BNB", "AVAX", "LINK", "DOT", "ADA"],
    "crypto_meme":   ["DOGE", "MATIC"],
    "tech_stocks":   ["NVDA", "AMD", "MSFT", "GOOGL", "META"],
    "etfs":          ["SPY", "QQQ"],
    "forex":         ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"],
}

DATA_DIR      = cfg.DATA_DIR
PORT_STATE    = DATA_DIR / "portfolio" / "state.json"
HALT_FLAG     = DATA_DIR / "HALT"          # si existe → todos los agentes paran
RISK_LOG      = DATA_DIR / "risk_log.json"


# ── Control de halt ────────────────────────────────────────────────────────────
def set_halt(reason: str) -> None:
    """Escribe flag HALT que todos los agentes deben leer antes de operar."""
    HALT_FLAG.parent.mkdir(parents=True, exist_ok=True)
    with open(HALT_FLAG, "w") as f:
        json.dump({
            "halted":    True,
            "reason":    reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, f, indent=2)
    console.print(f"\n[bold red]🛑 HALT ACTIVADO: {reason}[/bold red]")


def clear_halt() -> None:
    """Limpia el flag HALT (llamar manualmente cuando se resuelva el problema)."""
    if HALT_FLAG.exists():
        HALT_FLAG.unlink()
        console.print("[green]✓ HALT liberado[/green]")


def is_halted() -> bool:
    return HALT_FLAG.exists()


# ── Lectura del estado del portfolio ───────────────────────────────────────────
def load_portfolio() -> Optional[dict]:
    if not PORT_STATE.exists():
        return None
    try:
        return json.load(open(PORT_STATE))
    except Exception:
        return None


# ── Evaluaciones de riesgo ─────────────────────────────────────────────────────
def check_daily_loss(portfolio: dict) -> dict:
    """Verifica pérdida diaria vs límite."""
    today = date.today().isoformat()
    daily_pnl = portfolio.get("daily_pnl", {})
    today_pnl = daily_pnl.get(today, 0.0)

    status = "OK"
    if today_pnl <= -MAX_DAILY_LOSS_PCT:
        status = "HALT"
        set_halt(f"Daily loss {today_pnl:.1f}% ≥ límite -{MAX_DAILY_LOSS_PCT}%")
    elif today_pnl <= -MAX_DAILY_LOSS_PCT * 0.7:
        status = "WARNING"

    return {"check": "daily_loss", "value": today_pnl, "limit": -MAX_DAILY_LOSS_PCT,
            "status": status}


def check_drawdown(portfolio: dict) -> dict:
    """Verifica drawdown actual vs umbrales."""
    dd = portfolio.get("current_dd_pct", 0.0)

    if dd >= MAX_DRAWDOWN_HALT_PCT:
        status = "HALT"
        set_halt(f"Drawdown {dd:.1f}% ≥ halt {MAX_DRAWDOWN_HALT_PCT}%")
    elif dd >= MAX_DRAWDOWN_ALERT_PCT:
        status = "ALERT"
    else:
        status = "OK"

    return {"check": "drawdown", "value": dd,
            "alert_limit": MAX_DRAWDOWN_ALERT_PCT,
            "halt_limit": MAX_DRAWDOWN_HALT_PCT, "status": status}


def check_concentration(portfolio: dict) -> dict:
    """Verifica concentración por activo."""
    positions = [p for p in portfolio.get("positions", [])
                 if isinstance(p, dict) and p.get("status") == "open"]

    exposures = {}
    for p in positions:
        sym = p.get("symbol", "?")
        exposures[sym] = exposures.get(sym, 0) + p.get("size_pct", 0) * 100

    violations = {s: e for s, e in exposures.items() if e > MAX_SINGLE_EXPOSURE_PCT}
    total_exposure = sum(exposures.values())

    status = "OK"
    if violations:
        status = "ALERT"
        console.print(f"[yellow]⚠ Concentración excesiva: {violations}[/yellow]")
    if total_exposure > MAX_TOTAL_EXPOSURE_PCT:
        status = "ALERT"
        console.print(f"[yellow]⚠ Exposición total {total_exposure:.0f}% > límite {MAX_TOTAL_EXPOSURE_PCT}%[/yellow]")

    return {"check": "concentration", "exposures": exposures,
            "total_pct": round(total_exposure, 1),
            "violations": violations, "status": status}


def check_correlation(portfolio: dict) -> dict:
    """Detecta posiciones excesivamente correlacionadas."""
    positions = [p for p in portfolio.get("positions", [])
                 if isinstance(p, dict) and p.get("status") == "open"]
    symbols = [p.get("symbol", "?") for p in positions]

    alerts = []
    for group_name, group_syms in CORRELATION_GROUPS.items():
        in_group = [s for s in symbols if s in group_syms]
        if len(in_group) > MAX_CORRELATED_POSITIONS:
            alerts.append(f"{group_name}: {in_group} ({len(in_group)} posiciones)")

    status = "ALERT" if alerts else "OK"
    if alerts:
        console.print(f"[yellow]⚠ Correlación excesiva: {alerts}[/yellow]")

    return {"check": "correlation", "alerts": alerts, "status": status}


def check_halt_flag() -> dict:
    """Verifica si hay un HALT activo."""
    if HALT_FLAG.exists():
        d = json.load(open(HALT_FLAG))
        return {"check": "halt", "halted": True, "reason": d.get("reason"), "status": "HALT"}
    return {"check": "halt", "halted": False, "status": "OK"}


# ── Evaluación completa ────────────────────────────────────────────────────────
def evaluate_all() -> dict:
    """Corre todos los checks y retorna resultado consolidado."""
    portfolio = load_portfolio()
    if not portfolio:
        return {"error": "Sin estado de portfolio. Ejecuta portfolio_agent primero."}

    checks = [
        check_halt_flag(),
        check_daily_loss(portfolio),
        check_drawdown(portfolio),
        check_concentration(portfolio),
        check_correlation(portfolio),
    ]

    overall = "OK"
    for c in checks:
        if c["status"] == "HALT":
            overall = "HALT"
            break
        elif c["status"] in ("ALERT", "WARNING") and overall == "OK":
            overall = c["status"]

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall":   overall,
        "checks":    checks,
        "portfolio_summary": {
            "pnl_pct":    portfolio.get("total_pnl_pct", 0),
            "dd_pct":     portfolio.get("current_dd_pct", 0),
            "is_paused":  portfolio.get("is_paused", False),
        }
    }


# ── Display ────────────────────────────────────────────────────────────────────
def print_evaluation(result: dict) -> None:
    overall = result.get("overall", "?")
    color   = {"OK": "green", "WARNING": "yellow", "ALERT": "yellow", "HALT": "red"}.get(overall, "white")
    emoji   = {"OK": "✅", "WARNING": "⚠️", "ALERT": "🚨", "HALT": "🛑"}.get(overall, "?")

    console.print(Panel(
        f"[bold {color}]{emoji} Estado: {overall}[/bold {color}]",
        title=f"Risk Guard — {datetime.now().strftime('%H:%M:%S')}"
    ))

    table = Table(show_header=True, header_style="bold")
    table.add_column("Check",  style="cyan", width=18)
    table.add_column("Valor",  justify="right", width=15)
    table.add_column("Límite", justify="right", width=12)
    table.add_column("Estado", width=10)

    for c in result.get("checks", []):
        status = c.get("status", "?")
        s_color = {"OK": "green", "WARNING": "yellow", "ALERT": "yellow", "HALT": "red"}.get(status, "white")
        name    = c.get("check", "?")

        # Formatear valores según tipo
        if name == "daily_loss":
            val   = f"{c.get('value', 0):+.2f}%"
            limit = f"{c.get('limit', 0):.1f}%"
        elif name == "drawdown":
            val   = f"{c.get('value', 0):.2f}%"
            limit = f"{c.get('halt_limit', 0):.1f}%"
        elif name == "concentration":
            val   = f"{c.get('total_pct', 0):.0f}%"
            limit = f"{MAX_TOTAL_EXPOSURE_PCT:.0f}%"
        elif name == "correlation":
            val   = f"{len(c.get('alerts', []))} grupos"
            limit = f"{MAX_CORRELATED_POSITIONS} pos"
        else:
            val   = str(c.get("halted", ""))
            limit = "—"

        table.add_row(name, val, limit, f"[{s_color}]{status}[/{s_color}]")

    console.print(table)

    ps = result.get("portfolio_summary", {})
    console.print(
        f"  Portfolio: PnL={ps.get('pnl_pct',0):+.2f}%  "
        f"DD={ps.get('dd_pct',0):.1f}%  "
        f"Paused={ps.get('is_paused', False)}"
    )


# ── Log de riesgo ──────────────────────────────────────────────────────────────
def log_evaluation(result: dict) -> None:
    logs = json.load(open(RISK_LOG)) if RISK_LOG.exists() else []
    logs.append(result)
    logs = logs[-500:]  # mantener últimas 500 evaluaciones
    with open(RISK_LOG, "w") as f:
        json.dump(logs, f, indent=2)


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    monitor = "--monitor" in sys.argv

    if monitor:
        console.print(Panel(
            f"Risk Guard Agent — modo monitor\nCheck cada {CHECK_INTERVAL}s\n"
            f"Daily loss: -{MAX_DAILY_LOSS_PCT}%  |  DD halt: {MAX_DRAWDOWN_HALT_PCT}%",
            title="Risk Guard Agent"
        ))
        while True:
            try:
                result = evaluate_all()
                print_evaluation(result)
                log_evaluation(result)
            except KeyboardInterrupt:
                console.print("\n[yellow]Risk Guard detenido.[/yellow]")
                break
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
            time.sleep(CHECK_INTERVAL)
    else:
        # Una sola evaluación
        result = evaluate_all()
        if "error" in result:
            console.print(f"[yellow]{result['error']}[/yellow]")
        else:
            print_evaluation(result)
            log_evaluation(result)

        overall = result.get("overall", "?")
        sys.exit(0 if overall == "OK" else 1)


if __name__ == "__main__":
    main()
