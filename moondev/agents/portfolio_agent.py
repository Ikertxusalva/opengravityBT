"""
portfolio_agent — gestor de portfolio multi-estrategia.

Monitorea en tiempo real:
  - PnL total y por estrategia
  - Drawdown global (pausa si supera MAX_DD_PCT)
  - Exposición por activo y total
  - Reporte diario automático

Integra con:
  - execution_agent.py (lee logs de órdenes)
  - risk_guard_agent.py (recibe alertas de riesgo)
  - HyperLiquid API (posiciones reales)

Uso:
    python moondev/agents/portfolio_agent.py
"""
from __future__ import annotations

import sys
import json
import time
import glob
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional
from dataclasses import dataclass, field, asdict
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import moondev.config as cfg
from moondev.data.hyperliquid_data import get_mid_prices as _hl_mid_prices
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live

console = Console()

# ── Config ─────────────────────────────────────────────────────────────────────
CHECK_INTERVAL   = 60           # segundos entre actualizaciones
MAX_DD_PCT       = 15.0         # drawdown máximo global antes de pausar
MAX_EXPOSURE_PCT = 60.0         # exposición total máxima del portfolio
REPORT_HOUR      = 20           # hora (UTC) del reporte diario

DATA_DIR  = cfg.DATA_DIR
LOGS_DIR  = DATA_DIR / "execution_logs"
PORT_DIR  = DATA_DIR / "portfolio"
PORT_DIR.mkdir(parents=True, exist_ok=True)

PORT_STATE_FILE = PORT_DIR / "state.json"
PORT_REPORT_DIR = PORT_DIR / "reports"
PORT_REPORT_DIR.mkdir(parents=True, exist_ok=True)


# ── Estructuras de datos ───────────────────────────────────────────────────────
@dataclass
class Position:
    symbol:      str
    strategy:    str
    side:        str        # "long" | "short"
    entry_price: float
    size_pct:    float      # fracción del portfolio
    sl:          float
    tp:          float
    entry_time:  str
    pnl_pct:     float = 0.0
    status:      str   = "open"  # "open" | "closed" | "stopped"


@dataclass
class PortfolioState:
    initial_capital:  float = 10_000.0
    current_capital:  float = 10_000.0
    peak_capital:     float = 10_000.0
    total_pnl_pct:    float = 0.0
    max_drawdown_pct: float = 0.0
    current_dd_pct:   float = 0.0
    total_trades:     int   = 0
    winning_trades:   int   = 0
    is_paused:        bool  = False
    pause_reason:     str   = ""
    last_updated:     str   = ""
    positions:        list  = field(default_factory=list)
    daily_pnl:        dict  = field(default_factory=dict)   # fecha → pnl %


# ── Carga / guardado de estado ─────────────────────────────────────────────────
def load_state() -> PortfolioState:
    if PORT_STATE_FILE.exists():
        try:
            d = json.load(open(PORT_STATE_FILE))
            ps = PortfolioState(**{k: v for k, v in d.items()
                                   if k in PortfolioState.__dataclass_fields__})
            return ps
        except Exception:
            pass
    return PortfolioState()


def save_state(state: PortfolioState) -> None:
    state.last_updated = datetime.now(timezone.utc).isoformat()
    with open(PORT_STATE_FILE, "w") as f:
        json.dump(asdict(state), f, indent=2)


# ── Lectura de órdenes ejecutadas ──────────────────────────────────────────────
def load_new_orders(since: Optional[str] = None) -> list[dict]:
    """Lee órdenes de los logs de execution_agent desde timestamp dado."""
    orders = []
    for path in sorted(glob.glob(str(LOGS_DIR / "orders_*.json"))):
        try:
            items = json.load(open(path))
            for item in items:
                order = item.get("order")
                if not order:
                    continue
                if order.get("dry_run"):
                    continue  # ignorar dry-run en portfolio real
                if since and order.get("timestamp", "") <= since:
                    continue
                orders.append(order)
        except Exception:
            continue
    return orders


# ── Cálculo de PnL ─────────────────────────────────────────────────────────────
def get_current_price(symbol: str) -> Optional[float]:
    """Obtiene precio actual de HyperLiquid via hyperliquid_data."""
    mids = _hl_mid_prices()
    return mids.get(symbol) or None


def calc_position_pnl(pos: Position, current_price: float) -> float:
    """Calcula PnL % de una posición abierta."""
    if pos.side == "long":
        return (current_price - pos.entry_price) / pos.entry_price * 100
    else:
        return (pos.entry_price - current_price) / pos.entry_price * 100


def check_sl_tp(pos: Position, current_price: float) -> Optional[str]:
    """Verifica si SL o TP fueron alcanzados."""
    if pos.side == "long":
        if current_price <= pos.sl:
            return "stopped"
        if current_price >= pos.tp:
            return "closed"
    else:
        if current_price >= pos.sl:
            return "stopped"
        if current_price <= pos.tp:
            return "closed"
    return None


# ── Métricas del portfolio ─────────────────────────────────────────────────────
def update_metrics(state: PortfolioState) -> None:
    """Actualiza drawdown, PnL, win rate en el estado."""
    # Drawdown actual
    if state.current_capital > state.peak_capital:
        state.peak_capital = state.current_capital
    dd = (state.peak_capital - state.current_capital) / state.peak_capital * 100
    state.current_dd_pct  = round(dd, 2)
    state.max_drawdown_pct = max(state.max_drawdown_pct, dd)

    # PnL total
    state.total_pnl_pct = round(
        (state.current_capital - state.initial_capital) / state.initial_capital * 100, 2
    )

    # Circuit breaker
    if state.current_dd_pct >= MAX_DD_PCT and not state.is_paused:
        state.is_paused  = True
        state.pause_reason = f"Drawdown {state.current_dd_pct:.1f}% ≥ límite {MAX_DD_PCT}%"
        console.print(f"\n[bold red]⚠ PORTFOLIO PAUSADO: {state.pause_reason}[/bold red]")

    # Win rate
    if state.total_trades > 0:
        state.winning_trades = sum(
            1 for p in state.positions
            if p.get("status") == "closed" and p.get("pnl_pct", 0) > 0
        )


# ── Tabla de posiciones ────────────────────────────────────────────────────────
def build_positions_table(state: PortfolioState) -> Table:
    table = Table(show_header=True, header_style="bold magenta", title="Posiciones abiertas")
    table.add_column("Symbol",   style="cyan",   width=8)
    table.add_column("Strategy", style="white",  width=20)
    table.add_column("Side",     style="white",  width=6)
    table.add_column("Size%",    justify="right",width=7)
    table.add_column("Entry",    justify="right",width=10)
    table.add_column("PnL%",     justify="right",width=8)
    table.add_column("SL",       justify="right",width=10)
    table.add_column("TP",       justify="right",width=10)

    open_pos = [p for p in state.positions if isinstance(p, dict) and p.get("status") == "open"]
    for p in open_pos:
        pnl_color = "green" if p.get("pnl_pct", 0) >= 0 else "red"
        table.add_row(
            p.get("symbol", "?"),
            p.get("strategy", "?")[:20],
            p.get("side", "?").upper(),
            f"{p.get('size_pct',0)*100:.1f}%",
            f"{p.get('entry_price',0):.4f}",
            f"[{pnl_color}]{p.get('pnl_pct',0):+.2f}%[/{pnl_color}]",
            f"{p.get('sl',0):.4f}",
            f"{p.get('tp',0):.4f}",
        )
    if not open_pos:
        table.add_row("-", "Sin posiciones abiertas", "", "", "", "", "", "")
    return table


def build_summary_panel(state: PortfolioState) -> Panel:
    color = "red" if state.is_paused else ("green" if state.total_pnl_pct >= 0 else "yellow")
    status = "⏸ PAUSADO" if state.is_paused else "▶ ACTIVO"
    wr = (state.winning_trades / state.total_trades * 100) if state.total_trades else 0

    text = (
        f"[bold]Estado: [{color}]{status}[/{color}][/bold]   "
        f"PnL: [{color}]{state.total_pnl_pct:+.2f}%[/{color}]   "
        f"DD actual: {state.current_dd_pct:.1f}%   "
        f"DD máx: {state.max_drawdown_pct:.1f}%\n"
        f"Capital: ${state.current_capital:,.0f}   "
        f"Trades: {state.total_trades}   "
        f"Win Rate: {wr:.0f}%"
    )
    if state.is_paused:
        text += f"\n[red]Razón pausa: {state.pause_reason}[/red]"
    return Panel(text, title=f"Portfolio — {datetime.now().strftime('%H:%M:%S')}")


# ── Reporte diario ─────────────────────────────────────────────────────────────
def generate_daily_report(state: PortfolioState) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today in state.daily_pnl:
        return  # ya generado hoy

    state.daily_pnl[today] = state.total_pnl_pct

    closed = [p for p in state.positions if isinstance(p, dict) and p.get("status") in ("closed", "stopped")]
    today_closed = [p for p in closed if p.get("entry_time", "").startswith(today)]

    report = {
        "date":           today,
        "total_pnl_pct":  state.total_pnl_pct,
        "max_dd_pct":     state.max_drawdown_pct,
        "current_dd_pct": state.current_dd_pct,
        "trades_today":   len(today_closed),
        "capital":        state.current_capital,
        "is_paused":      state.is_paused,
        "positions_open": len([p for p in state.positions if isinstance(p, dict) and p.get("status") == "open"]),
    }

    report_path = PORT_REPORT_DIR / f"report_{today}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    console.print(f"\n[bold cyan]── Reporte diario {today} ──[/bold cyan]")
    console.print(f"  PnL: {state.total_pnl_pct:+.2f}%")
    console.print(f"  Max DD: {state.max_drawdown_pct:.1f}%")
    console.print(f"  Trades hoy: {len(today_closed)}")
    console.print(f"  Capital: ${state.current_capital:,.0f}")


# ── Ciclo principal ────────────────────────────────────────────────────────────
def run(initial_capital: float = 10_000.0) -> None:
    state = load_state()
    if state.initial_capital != initial_capital:
        state.initial_capital = initial_capital
        state.current_capital = initial_capital
        state.peak_capital    = initial_capital

    console.print(Panel(
        f"Portfolio Agent\nCapital inicial: ${initial_capital:,.0f}\n"
        f"Max DD: {MAX_DD_PCT}%  |  Max Exposición: {MAX_EXPOSURE_PCT}%",
        title="Portfolio Agent"
    ))

    while True:
        try:
            # Actualizar PnL de posiciones abiertas
            open_pos = [p for p in state.positions
                        if isinstance(p, dict) and p.get("status") == "open"]
            for p in open_pos:
                price = get_current_price(p.get("symbol", "BTC"))
                if price:
                    pnl = calc_position_pnl(
                        Position(**{k: p[k] for k in Position.__dataclass_fields__ if k in p}),
                        price
                    )
                    p["pnl_pct"] = round(pnl, 3)

                    # Simular capital
                    state.current_capital = state.initial_capital * (1 + pnl / 100 * p.get("size_pct", 0.05))

                    # Check SL/TP
                    pos_obj = Position(**{k: p[k] for k in Position.__dataclass_fields__ if k in p})
                    new_status = check_sl_tp(pos_obj, price)
                    if new_status:
                        p["status"] = new_status
                        state.total_trades += 1
                        emoji = "✓" if new_status == "closed" else "✗"
                        console.print(f"  {emoji} {p['symbol']} {new_status.upper()} PnL={pnl:+.2f}%")

            # Leer órdenes nuevas de execution_agent
            new_orders = load_new_orders()
            for order in new_orders:
                pos = {
                    "symbol":      order.get("symbol", "BTC"),
                    "strategy":    "execution_agent",
                    "side":        order.get("side", "long"),
                    "entry_price": order.get("entry", 0),
                    "size_pct":    order.get("size_pct", 0.05),
                    "sl":          order.get("sl", 0),
                    "tp":          order.get("tp", 0),
                    "entry_time":  order.get("timestamp", ""),
                    "pnl_pct":     0.0,
                    "status":      "open",
                }
                # Evitar duplicados
                exists = any(
                    p.get("entry_time") == pos["entry_time"]
                    for p in state.positions if isinstance(p, dict)
                )
                if not exists and not state.is_paused:
                    state.positions.append(pos)

            # Actualizar métricas
            update_metrics(state)

            # Reporte diario
            if datetime.now(timezone.utc).hour == REPORT_HOUR:
                generate_daily_report(state)

            # Display
            console.clear()
            console.print(build_summary_panel(state))
            console.print(build_positions_table(state))

            save_state(state)

        except KeyboardInterrupt:
            console.print("\n[yellow]Portfolio Agent detenido.[/yellow]")
            save_state(state)
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

        time.sleep(CHECK_INTERVAL)


def main():
    capital = float(sys.argv[1]) if len(sys.argv) > 1 else cfg.USD_SIZE * 400
    run(initial_capital=capital)


if __name__ == "__main__":
    main()
