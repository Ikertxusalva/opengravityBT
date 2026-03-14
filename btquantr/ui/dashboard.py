"""BTQUANTR Rich TUI Dashboard — live refresh cada 5s."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime

import redis
from rich import box
from rich.align import Align
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ── Conexión Redis ─────────────────────────────────────────────────────────────
def _redis() -> redis.Redis:
    import os
    host = os.environ.get("REDIS_HOST", "localhost")
    port = int(os.environ.get("REDIS_PORT", "6379"))
    db = int(os.environ.get("REDIS_DB", "0"))
    return redis.Redis(host=host, port=port, db=db, decode_responses=True)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get(r, key, default=None):
    try:
        v = r.get(key)
        return json.loads(v) if v else default
    except Exception:
        return default


def _hget(r, key, default=None):
    try:
        return r.hgetall(key) or default or {}
    except Exception:
        return default or {}


def _regime_color(name: str) -> str:
    return {"BULL": "bold green", "BEAR": "bold red", "SIDEWAYS": "bold blue"}.get(name, "white")


def _pnl_color(val: float) -> str:
    return "green" if val >= 0 else "red"


def _sign(val: float) -> str:
    return f"+{val:.2f}" if val >= 0 else f"{val:.2f}"


def _trades_history(r, limit: int = 8) -> list[dict]:
    """Lee historial via LRANGE sobre la list key (fallback si XREVRANGE no disponible)."""
    try:
        entries = r.xrevrange("paper:trades:history", "+", "-", count=limit)
        trades = []
        for _id, fields in entries:
            trades.append({k: json.loads(v) for k, v in fields.items()})
        return trades
    except Exception:
        pass
    # Fallback: list key alternativa
    try:
        raw = r.lrange("paper:trades:list", -limit, -1)
        trades = [json.loads(x) for x in raw]
        return list(reversed(trades))
    except Exception:
        return []


# ── Paneles ────────────────────────────────────────────────────────────────────

def _symbol_panel(r, symbol: str) -> Panel:
    price = _get(r, f"market:{symbol}:price", 0)
    regime_raw = _get(r, f"regime:{symbol}", {})
    regime_name = regime_raw.get("state_name", "?")
    confidence = regime_raw.get("confidence", 0) * 100
    stability = regime_raw.get("stability", 0) * 100

    funding_raw = _get(r, f"derivatives:{symbol}:funding", [{}])
    funding = funding_raw[0].get("fundingRate", 0) if funding_raw else 0
    funding_pct = funding * 100

    ls_raw = _get(r, f"derivatives:{symbol}:long_short", {})
    if isinstance(ls_raw, list):
        ls_raw = ls_raw[0] if ls_raw else {}
    ls_ratio = ls_raw.get("longShortRatio", ls_raw.get("longAccount", "?"))

    oi_raw = _get(r, f"derivatives:{symbol}:oi", {})
    oi = oi_raw.get("openInterest", 0) if isinstance(oi_raw, dict) else 0

    # Color precio
    color = _regime_color(regime_name)
    funding_color = "green" if funding >= 0 else "red"

    t = Table.grid(padding=(0, 1))
    t.add_column(style="dim", width=14)
    t.add_column()

    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else str(price)
    t.add_row("Precio", Text(price_str, style=f"bold white"))
    t.add_row("Régimen", Text(f"{regime_name}  {confidence:.0f}%", style=color))
    t.add_row("Stability", Text(f"{stability:.0f}%", style="dim"))
    t.add_row(
        "Funding",
        Text(f"{'+' if funding >= 0 else ''}{funding_pct:.4f}%", style=funding_color),
    )
    if ls_ratio and ls_ratio != "?":
        t.add_row("L/S ratio", Text(str(round(float(ls_ratio), 3)), style="dim white"))
    if oi:
        oi_b = float(oi) / 1e9
        t.add_row("OI", Text(f"${oi_b:.2f}B", style="dim white"))

    title_color = color
    return Panel(t, title=f"[{title_color}]{symbol}[/]", border_style="dim cyan", box=box.ROUNDED)


def _fear_greed_panel(r) -> Panel:
    fg = _get(r, "sentiment:fear_greed", {})
    value = fg.get("value", "?")
    cls = fg.get("class", "?")

    macro = _get(r, "macro:markets", {})
    vix = macro.get("vix", {})
    vix_val = vix.get("price", "?") if isinstance(vix, dict) else "?"
    spy = macro.get("spy", {})
    spy_val = spy.get("price", "?") if isinstance(spy, dict) else "?"

    fg_color = "red" if isinstance(value, int) and value < 25 else (
        "yellow" if isinstance(value, int) and value < 50 else "green"
    )

    t = Table.grid(padding=(0, 1))
    t.add_column(style="dim", width=10)
    t.add_column()
    t.add_row("F&G", Text(f"{value}  {cls}", style=f"bold {fg_color}"))
    if vix_val != "?":
        t.add_row("VIX", Text(f"{vix_val:.2f}" if isinstance(vix_val, float) else str(vix_val), style="dim white"))
    if spy_val != "?":
        t.add_row("SPY", Text(f"${spy_val:.2f}" if isinstance(spy_val, float) else str(spy_val), style="dim white"))

    return Panel(t, title="[bold magenta]MACRO[/]", border_style="dim magenta", box=box.ROUNDED)


def _portfolio_panel(r) -> Panel:
    balance = float(r.get("paper:portfolio:balance") or 10_000)
    state = _get(r, "paper:portfolio:state", {})
    initial = 10_000.0
    pnl_total = balance - initial
    pnl_pct = pnl_total / initial * 100
    pnl_color = _pnl_color(pnl_total)

    t = Table.grid(padding=(0, 1))
    t.add_column(style="dim", width=12)
    t.add_column()

    t.add_row(
        "Balance",
        Text(f"${balance:,.2f}  ({_sign(pnl_pct)}%)", style=f"bold {pnl_color}"),
    )
    t.add_row("PnL total", Text(f"${_sign(pnl_total)}", style=pnl_color))

    if state:
        t.add_row("", Text(""))
        t.add_row("Posiciones", Text(f"{len(state)} abiertas", style="bold yellow"))
        for sym, pos in state.items():
            side = pos.get("side", "?")
            size = pos.get("size_usd", 0)
            entry = pos.get("entry_price", 0)
            regime = pos.get("regime_at_entry", "?")
            # Calcular PnL en vivo
            current_price = _get(r, f"market:{sym}:price", entry) or entry
            if side == "LONG":
                live_pnl = (current_price - entry) / entry * size
            else:
                live_pnl = (entry - current_price) / entry * size
            lp_color = _pnl_color(live_pnl)
            side_color = "green" if side == "LONG" else "red"
            t.add_row(
                f"  {sym}",
                Text(
                    f"[{side_color}]{side}[/{side_color}]  ${size:,.0f} @ ${entry:,.0f}"
                    f"  PnL [{lp_color}]{_sign(live_pnl)}[/{lp_color}]  [{_regime_color(regime)}]{regime}[/{_regime_color(regime)}]",
                    no_wrap=True,
                ),
            )
    else:
        t.add_row("", Text(""))
        t.add_row("Posiciones", Text("Sin posiciones abiertas", style="dim"))

    return Panel(t, title="[bold yellow]PORTFOLIO[/]", border_style="dim yellow", box=box.ROUNDED)


def _history_panel(r) -> Panel:
    trades = _trades_history(r, limit=8)

    tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold dim")
    tbl.add_column("Símbolo", width=9)
    tbl.add_column("Side", width=6)
    tbl.add_column("PnL $", justify="right", width=9)
    tbl.add_column("PnL %", justify="right", width=7)
    tbl.add_column("Régimen", width=9)
    tbl.add_column("Fecha", width=17)

    if not trades:
        tbl.add_row("[dim]—[/]", "", "", "", "", "")
    else:
        for tr in trades:
            sym = tr.get("symbol", "?")
            side = tr.get("side", "?")
            pnl_usd = float(tr.get("net_pnl_usd", 0))
            pnl_pct = float(tr.get("pnl_pct", 0))
            regime = tr.get("regime_at_entry", "?")
            ts = tr.get("closed_at", 0)
            dt = datetime.fromtimestamp(float(ts)).strftime("%m-%d %H:%M") if ts else "?"

            pc = _pnl_color(pnl_usd)
            sc = "green" if side == "LONG" else "red"
            rc = _regime_color(regime)
            tbl.add_row(
                f"[white]{sym}[/]",
                f"[{sc}]{side}[/]",
                f"[{pc}]{_sign(pnl_usd)}[/]",
                f"[{pc}]{_sign(pnl_pct)}%[/]",
                f"[{rc}]{regime}[/]",
                f"[dim]{dt}[/]",
            )

    return Panel(tbl, title="[bold white]HISTORIAL[/]", border_style="dim white", box=box.ROUNDED)


def _api_panel(r) -> Panel:
    claude = _hget(r, "stats:api:claude")
    calls = claude.get("calls_total", "0")
    cost_micro = int(claude.get("cost_usd_micro", 0))
    cost = cost_micro / 1_000_000
    tok_in = int(claude.get("tokens_in", 0))
    tok_out = int(claude.get("tokens_out", 0))
    model = claude.get("last_model", "?").replace("claude-", "")

    t = Table.grid(padding=(0, 1))
    t.add_column(style="dim", width=14)
    t.add_column()
    t.add_row("Calls", Text(f"{calls}", style="bold cyan"))
    t.add_row("Costo", Text(f"${cost:.4f}", style="bold yellow"))
    t.add_row("Tokens in", Text(f"{tok_in:,}", style="dim"))
    t.add_row("Tokens out", Text(f"{tok_out:,}", style="dim"))
    t.add_row("Modelo", Text(model, style="dim"))

    # APIs externas
    apis = [
        ("Binance", "stats:api:binance"),
        ("HyperLiquid", "stats:api:hyperliquid"),
        ("AltMe", "stats:api:alternative_me"),
        ("yfinance", "stats:api:yfinance"),
    ]
    t.add_row("", Text(""))
    for name, key in apis:
        d = _hget(r, key)
        reqs = d.get("requests", "0")
        errs = d.get("errors", "0")
        dot = "[green]●[/]" if int(errs) == 0 else "[red]●[/]"
        t.add_row(name, Text(f"{dot} {reqs} req  {errs} err", no_wrap=True))

    return Panel(t, title="[bold cyan]API STATS[/]", border_style="dim cyan", box=box.ROUNDED)


def _health_panel(r) -> Panel:
    hd = _get(r, "health:data_service", {})
    hr = _get(r, "health:regime_service", {})
    dq = _get(r, "data:quality_status", {})

    def _dot(h):
        if not h:
            return "[red]● OFFLINE[/]"
        st = h.get("status", "?")
        return "[green]● OK[/]" if st == "ok" else f"[red]● {st}[/]"

    # Paper trading heartbeat
    paper_ts = r.get("paper:last_cycle_ts")
    if paper_ts:
        ago = int(time.time() - float(paper_ts))
        if ago < 3700:
            paper_dot = f"[bold green]● RUNNING (hace {ago}s)[/]"
        else:
            paper_dot = "[bold red]● STOPPED[/]"
    else:
        paper_dot = "[bold red]● STOPPED[/]"

    t = Table.grid(padding=(0, 1))
    t.add_column(style="dim", width=16)
    t.add_column()
    t.add_row("Paper Trading", Text(paper_dot, no_wrap=True))
    t.add_row("DataService", Text(_dot(hd), no_wrap=True))
    t.add_row("RegimeService", Text(_dot(hr), no_wrap=True))
    if dq:
        dq_status = dq.get("status", "?")
        dq_color = "green" if dq_status == "PASS" else "red"
        t.add_row("Data Quality", Text(f"[{dq_color}]{dq_status}[/]", no_wrap=True))

    # Rate limiter
    rl = _hget(r, "stats:api:claude")
    last_ts = rl.get("last_call_ts")
    if last_ts:
        ago = int(time.time()) - int(last_ts)
        t.add_row("Último call", Text(f"{ago}s ago", style="dim"))

    syms_raw = r.get("data:symbols_approved")
    if syms_raw:
        syms = json.loads(syms_raw) if syms_raw.startswith("[") else syms_raw
        t.add_row("Símbolos", Text(str(syms), style="dim"))

    return Panel(t, title="[bold green]HEALTH[/]", border_style="dim green", box=box.ROUNDED)


# ── Layout ─────────────────────────────────────────────────────────────────────

def _build(r) -> Layout:
    layout = Layout()

    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="market", size=10),
        Layout(name="mid", size=14),
        Layout(name="bottom", size=12),
        Layout(name="footer", size=1),
    )

    # Header
    now = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    header_text = Text(justify="center")
    header_text.append("◆ BTQUANTR ", style="bold #00D4AA")
    header_text.append("Dashboard", style="bold white")
    header_text.append(f"   ·   {now}", style="dim")
    layout["header"].update(Align.center(header_text, vertical="middle"))

    # Market row: 3 columnas
    layout["market"].split_row(
        Layout(name="btc", ratio=2),
        Layout(name="eth", ratio=2),
        Layout(name="macro", ratio=1),
    )
    layout["btc"].update(_symbol_panel(r, "BTCUSDT"))
    layout["eth"].update(_symbol_panel(r, "ETHUSDT"))
    layout["macro"].update(_fear_greed_panel(r))

    # Mid row: portfolio + historial
    layout["mid"].split_row(
        Layout(name="portfolio", ratio=1),
        Layout(name="history", ratio=1),
    )
    layout["portfolio"].update(_portfolio_panel(r))
    layout["history"].update(_history_panel(r))

    # Bottom row: api + health
    layout["bottom"].split_row(
        Layout(name="api", ratio=1),
        Layout(name="health", ratio=1),
    )
    layout["api"].update(_api_panel(r))
    layout["health"].update(_health_panel(r))

    # Footer
    layout["footer"].update(
        Align.center(
            Text("[dim]q[/dim] salir  ·  [dim]r[/dim] refresh  ·  auto-refresh cada 5s", style="dim"),
            vertical="middle",
        )
    )

    return layout


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    console = Console()
    r = _redis()

    try:
        r.ping()
    except Exception as e:
        console.print(f"[red]Redis no disponible: {e}[/]")
        sys.exit(1)

    console.clear()

    with Live(
        _build(r),
        console=console,
        refresh_per_second=0.2,
        screen=True,
    ) as live:
        try:
            while True:
                time.sleep(5)
                live.update(_build(r))
        except KeyboardInterrupt:
            pass

    console.clear()
    console.print("[bold #00D4AA]BTQUANTR Dashboard cerrado.[/]")


if __name__ == "__main__":
    main()
