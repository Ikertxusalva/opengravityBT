"""
BTQUANTR Terminal UI Theme & Components
========================================
Configuración visual profesional para toda la CLI de BTQUANTR.
Usa rich para paneles, tablas, spinners y branding consistente.

INSTRUCCIONES DE IMPLEMENTACIÓN:
1. Copiar este archivo a btquantr/ui/theme.py
2. Importar desde cualquier comando CLI: from btquantr.ui.theme import *
3. Reemplazar prints planos por los componentes de aquí
4. Nombre de la app: BTQUANTR (siempre mayúsculas)

Dependencia: pip install rich (ya debería estar instalada)
"""

import sys
import colorama

colorama.init()
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from rich.console import Console
from rich.theme import Theme
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.layout import Layout
from rich.live import Live
from rich.spinner import Spinner
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.style import Style
from rich.align import Align
from rich.rule import Rule
from rich import box
import time

# ═══════════════════════════════════════════════════════
# PALETA DE COLORES BTQUANTR
# ═══════════════════════════════════════════════════════
# Inspirada en terminales de trading institucional.
# Fondo oscuro, acentos cian/verde, alertas claras.

BTQUANTR_THEME = Theme({
    # --- Branding ---
    "brand":          "bold #00D4AA",        # Cian BTQUANTR — color primario
    "brand.dim":      "#00D4AA dim",
    "brand.bg":       "on #0A2E28",

    # --- Regímenes ---
    "bull":           "bold #00E676",        # Verde brillante
    "bull.dim":       "#00E676 dim",
    "bear":           "bold #FF5252",        # Rojo brillante
    "bear.dim":       "#FF5252 dim",
    "sideways":       "bold #42A5F5",        # Azul
    "sideways.dim":   "#42A5F5 dim",
    "transitioning":  "bold #FFB300",        # Ámbar
    "transitioning.dim": "#FFB300 dim",

    # --- Estados ---
    "ok":             "bold #00E676",
    "warn":           "bold #FFB300",
    "error":          "bold #FF5252",
    "critical":       "bold #FF1744 on #2D0A0A",

    # --- Datos ---
    "price":          "bold #E8ECF1",
    "price.up":       "#00E676",
    "price.down":     "#FF5252",
    "pnl.pos":        "bold #00E676",
    "pnl.neg":        "bold #FF5252",
    "pct":            "#42A5F5",
    "muted":          "#6B7B8D",
    "dim":            "#3D4F63",

    # --- Agentes ---
    "agent.thinking": "bold #FFB300",
    "agent.done":     "bold #00E676",
    "agent.error":    "bold #FF5252",
    "agent.waiting":  "#3D4F63",

    # --- Seguridad ---
    "secure":         "bold #00E676",
    "injection":      "bold #FF1744",

    # --- Paneles ---
    "panel.border":   "#1E2A3A",
    "panel.title":    "bold #00D4AA",
    "header":         "bold #E8ECF1",
    "label":          "#6B7B8D",
    "value":          "bold #E8ECF1",
})

# Consola global con tema (force_terminal evita el renderer legacy de Windows cp1252)
console = Console(theme=BTQUANTR_THEME, force_terminal=True, color_system="truecolor")


# ═══════════════════════════════════════════════════════
# BRANDING
# ═══════════════════════════════════════════════════════

LOGO_SMALL = "[brand]◆ BTQUANTR[/brand]"

LOGO_BANNER = """[brand]
 ██████╗ ████████╗ ██████╗ ██╗   ██╗ █████╗ ███╗   ██╗████████╗██████╗
 ██╔══██╗╚══██╔══╝██╔═══██╗██║   ██║██╔══██╗████╗  ██║╚══██╔══╝██╔══██╗
 ██████╔╝   ██║   ██║   ██║██║   ██║███████║██╔██╗ ██║   ██║   ██████╔╝
 ██╔══██╗   ██║   ██║▄▄ ██║██║   ██║██╔══██║██║╚██╗██║   ██║   ██╔══██╗
 ██████╔╝   ██║   ╚██████╔╝╚██████╔╝██║  ██║██║ ╚████║   ██║   ██║  ██║
 ╚═════╝    ╚═╝    ╚══▀▀═╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝
[/brand][muted] Algorithmic Trading System · Regime-Aware Multi-Agent[/muted]"""

LOGO_COMPACT = "[brand]◆ BTQUANTR[/brand] [muted]│ Algorithmic Trading System[/muted]"


def print_banner():
    """Imprime el banner completo al arrancar."""
    console.print(LOGO_BANNER)
    console.print()


def print_header(title: str):
    """Header de sección con línea."""
    console.print()
    console.print(Rule(f"[brand] {title} [/brand]", style="panel.border"))
    console.print()


# ═══════════════════════════════════════════════════════
# COMPONENTES DE RÉGIMEN
# ═══════════════════════════════════════════════════════

REGIME_STYLES = {
    "BULL":          ("bull",          "▲", "🟢"),
    "BEAR":          ("bear",          "▼", "🔴"),
    "SIDEWAYS":      ("sideways",      "◆", "🔵"),
    "TRANSITIONING": ("transitioning", "⟳", "🟡"),
}

def regime_text(regime: str, confidence: float = None, stability: float = None) -> Text:
    """Formatea un régimen con color y símbolo."""
    style, symbol, _ = REGIME_STYLES.get(regime, ("muted", "?", "⚪"))
    t = Text()
    t.append(f"{symbol} {regime}", style=style)
    if confidence is not None:
        t.append(f"  {confidence:.1f}%", style=f"{style}.dim")
    if stability is not None:
        t.append(f"  stab={stability:.0%}", style="muted")
    return t


def regime_badge(regime: str) -> str:
    """Badge inline para tablas."""
    style, symbol, _ = REGIME_STYLES.get(regime, ("muted", "?", "⚪"))
    return f"[{style}]{symbol} {regime}[/{style}]"


# ═══════════════════════════════════════════════════════
# PANELES DE STATUS
# ═══════════════════════════════════════════════════════

def panel_services(services: list) -> Panel:
    """Panel de estado de servicios."""
    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column("service", style="label")
    table.add_column("status", justify="center")
    table.add_column("last", style="muted")

    for svc in services:
        status = svc.get("status", "unknown")
        style = "ok" if status == "ok" else "warn" if status == "warn" else "error"
        icon = "●" if status == "ok" else "▲" if status == "warn" else "✗"
        table.add_row(
            svc["name"],
            f"[{style}]{icon}[/{style}]",
            svc.get("last_update", "—"),
        )

    return Panel(
        table,
        title=f"{LOGO_SMALL} [label]Services[/label]",
        border_style="panel.border",
        box=box.ROUNDED,
        padding=(1, 2),
    )


def panel_symbols(symbols: list) -> Panel:
    """Panel de símbolos con precio, cambio y régimen."""
    table = Table(box=None, show_header=True, padding=(0, 1))
    table.add_column("Symbol", style="header", min_width=10)
    table.add_column("Price", justify="right", style="price")
    table.add_column("24h", justify="right", min_width=7)
    table.add_column("Regime", min_width=16)
    table.add_column("Fund", justify="right", style="muted", min_width=8)
    table.add_column("OI", justify="right", style="muted")
    table.add_column("L/S", justify="right", style="muted")

    for s in symbols:
        change_style = "price.up" if s.get("change", 0) >= 0 else "price.down"
        change_arrow = "▲" if s.get("change", 0) >= 0 else "▼"
        table.add_row(
            f"[brand]{s['symbol']}[/brand]",
            f"${s['price']:,.2f}" if s['price'] > 100 else f"${s['price']:.2f}",
            f"[{change_style}]{change_arrow} {abs(s.get('change', 0)):.2f}%[/{change_style}]",
            regime_badge(s.get("regime", "UNKNOWN")),
            f"{s.get('funding', 0):.4f}%",
            f"{s.get('oi', 0):,}",
            f"{s.get('ls_ratio', 0):.2f}",
        )

    return Panel(
        table,
        title=f"{LOGO_SMALL} [label]Markets[/label]",
        border_style="panel.border",
        box=box.ROUNDED,
        padding=(1, 2),
    )


def panel_portfolio(portfolio: dict) -> Panel:
    """Panel de portfolio (paper trading)."""
    balance = portfolio.get("balance", 0)
    initial = portfolio.get("initial_balance", 10000)
    pnl = portfolio.get("pnl", balance - initial)
    pnl_pct = portfolio.get("pnl_pct", (pnl / initial * 100) if initial else 0)
    pnl_style = "pnl.pos" if pnl >= 0 else "pnl.neg"
    pnl_arrow = "▲" if pnl >= 0 else "▼"

    content = Text()
    content.append("Balance    ", style="label")
    content.append(f"${balance:,.2f}\n", style="value")
    content.append("P&L        ", style="label")
    content.append(f"{pnl_arrow} ${abs(pnl):,.2f} ({pnl_pct:+.2f}%)\n", style=pnl_style)
    content.append("Trades     ", style="label")
    content.append(f"{portfolio.get('trades', 0)}", style="value")
    content.append(f"  Win Rate ", style="label")
    content.append(f"{portfolio.get('win_rate', 0):.1f}%\n", style="value")
    content.append("Open       ", style="label")
    content.append(f"{portfolio.get('open_positions', 0)}", style="value")

    return Panel(
        content,
        title=f"{LOGO_SMALL} [label]Paper Portfolio[/label]",
        border_style="panel.border",
        box=box.ROUNDED,
        padding=(1, 2),
    )


def panel_claude_api(claude: dict) -> Panel:
    """Panel de uso de Claude API."""
    cost = claude.get("cost", 0)
    cost_style = "ok" if cost < 0.10 else "warn" if cost < 1.0 else "error"

    content = Text()
    content.append("Calls      ", style="label")
    content.append(f"{claude.get('calls', 0)}\n", style="value")
    content.append("Cost       ", style="label")
    content.append(f"${cost:.4f}\n", style=cost_style)
    content.append("Tokens     ", style="label")
    content.append(f"{claude.get('tokens_in', 0):,}", style="muted")
    content.append(" in  ", style="dim")
    content.append(f"{claude.get('tokens_out', 0):,}", style="muted")
    content.append(" out\n", style="dim")
    content.append("Last call  ", style="label")
    content.append(f"{claude.get('last_call', '—')}", style="muted")

    return Panel(
        content,
        title=f"{LOGO_SMALL} [label]Claude API[/label]",
        border_style="panel.border",
        box=box.ROUNDED,
        padding=(1, 2),
    )


def panel_security(security: dict) -> Panel:
    """Panel de seguridad."""
    inj = security.get("injections", 0)
    inv = security.get("invalid_outputs", 0)
    blk = security.get("enforcer_blocks", 0)
    all_ok = inj == 0 and inv == 0 and blk == 0

    content = Text()
    content.append("Status     ", style="label")
    if all_ok:
        content.append("● SECURE\n", style="secure")
    else:
        content.append("▲ ALERT\n", style="error")
    content.append("Injections ", style="label")
    content.append(f"{inj}\n", style="ok" if inj == 0 else "error")
    content.append("Invalid    ", style="label")
    content.append(f"{inv}\n", style="ok" if inv == 0 else "error")
    content.append("Blocked    ", style="label")
    content.append(f"{blk}", style="ok" if blk == 0 else "warn")

    return Panel(
        content,
        title=f"{LOGO_SMALL} [label]Security[/label]",
        border_style="panel.border",
        box=box.ROUNDED,
        padding=(1, 2),
    )


def panel_apis(apis: list) -> Panel:
    """Panel de estado de APIs externas."""
    table = Table(box=None, show_header=True, padding=(0, 1))
    table.add_column("API", style="label", min_width=14)
    table.add_column("Reqs", justify="right", style="value")
    table.add_column("Err", justify="right")
    table.add_column("", justify="center", min_width=3)

    for api in apis:
        err_style = "ok" if api.get("errors", 0) == 0 else "error"
        status = api.get("status", "ok")
        icon_style = "ok" if status == "ok" else "warn" if status == "warn" else "error"
        icon = "●" if status == "ok" else "▲" if status == "warn" else "✗"
        table.add_row(
            api["name"],
            str(api.get("requests", 0)),
            f"[{err_style}]{api.get('errors', 0)}[/{err_style}]",
            f"[{icon_style}]{icon}[/{icon_style}]",
        )

    return Panel(
        table,
        title=f"{LOGO_SMALL} [label]APIs[/label]",
        border_style="panel.border",
        box=box.ROUNDED,
        padding=(1, 2),
    )


# ═══════════════════════════════════════════════════════
# DEBATE DISPLAY
# ═══════════════════════════════════════════════════════

AGENT_ICONS = {
    "data_quality":   "🛡️",
    "regime":         "📊",
    "technical":      "📈",
    "sentiment":      "🧠",
    "bull":           "🟢",
    "bear":           "🔴",
    "risk_manager":   "⚖️",
}

def debate_panel(agents: list, symbol: str, status: str = "running") -> Panel:
    """
    Panel del debate con estado de cada agente.
    agents: [{"name": str, "status": "thinking|done|waiting|error", "result": str, "time": float}]
    """
    content = Text()

    for agent in agents:
        icon = AGENT_ICONS.get(agent.get("type", ""), "●")
        name = agent["name"].ljust(20)
        st = agent.get("status", "waiting")

        if st == "done":
            result = agent.get("result", "")
            content.append(f"  ✓  {icon} {name}", style="agent.done")
            content.append(f"  {result}\n", style="muted")
        elif st == "thinking":
            elapsed = agent.get("time", 0)
            content.append(f"  ⣻  {icon} {name}", style="agent.thinking")
            content.append(f"  pensando… {elapsed:.1f}s\n", style="muted")
        elif st == "error":
            error = agent.get("error", "error")
            content.append(f"  ✗  {icon} {name}", style="agent.error")
            content.append(f"  {error}\n", style="error")
        else:
            content.append(f"  ·  {icon} {name}", style="agent.waiting")
            content.append("  esperando\n", style="dim")

    border = "ok" if status == "complete" else "brand" if status == "running" else "error"
    return Panel(
        content,
        title=f"{LOGO_SMALL} [label]Debate — {symbol}[/label]",
        border_style=border,
        box=box.ROUNDED,
        padding=(1, 2),
    )


def debate_result_panel(symbol: str, decision: str, reason: str = None, agents_summary: dict = None) -> Panel:
    """Panel final del resultado del debate."""
    style = "bull" if decision == "APPROVE" else "bear" if decision == "VETO" else "warning"

    content = Text()
    content.append(f"\n  Decisión: ", style="label")
    content.append(f"{decision}\n\n", style=style)

    if reason:
        content.append(f"  Razón: ", style="label")
        content.append(f"{reason}\n", style="muted")

    if agents_summary:
        content.append("\n")
        for name, val in agents_summary.items():
            content.append(f"  {name.ljust(18)}", style="label")
            content.append(f"{val}\n", style="value")

    return Panel(
        content,
        title=f"{LOGO_SMALL} [label]Resultado — {symbol}[/label]",
        border_style=style,
        box=box.HEAVY,
        padding=(1, 2),
    )


# ═══════════════════════════════════════════════════════
# MONITOR DISPLAY
# ═══════════════════════════════════════════════════════

def monitor_alert(symbol: str, regime: str, confidence: float, stability: float) -> Panel:
    """Alerta del monitor cuando detecta oportunidad."""
    style, symbol_icon, emoji = REGIME_STYLES.get(regime, ("muted", "?", "⚪"))

    content = Text()
    content.append(f"\n  {emoji} ", style=style)
    content.append(f"{symbol}", style="brand")
    content.append(f" → ", style="dim")
    content.append(f"{regime}", style=style)
    content.append(f"  conf={confidence:.1f}%  stab={stability:.0%}\n\n", style="muted")
    content.append("  ¿Ejecutar debate? ", style="value")
    content.append("[s/n] ", style="brand")

    return Panel(
        content,
        title=f"{LOGO_SMALL} [label]Oportunidad Detectada[/label]",
        border_style=style,
        box=box.DOUBLE,
        padding=(0, 2),
    )


# ═══════════════════════════════════════════════════════
# PAPER TRADING DISPLAY
# ═══════════════════════════════════════════════════════

def paper_status_panel(portfolio: dict, positions: list) -> Panel:
    """Panel completo de paper trading status."""
    # Portfolio summary
    balance = portfolio.get("balance", 0)
    initial = portfolio.get("initial_balance", 10000)
    pnl = balance - initial
    pnl_pct = (pnl / initial * 100) if initial else 0
    pnl_style = "pnl.pos" if pnl >= 0 else "pnl.neg"

    content = Text()
    content.append("  PORTFOLIO\n", style="brand")
    content.append(f"  Balance: ", style="label")
    content.append(f"${balance:,.2f}", style="value")
    content.append(f"  ({pnl_pct:+.2f}%)\n", style=pnl_style)

    # Open positions
    if positions:
        content.append(f"\n  POSICIONES ABIERTAS ({len(positions)})\n", style="brand")
        for pos in positions:
            side_style = "bull" if pos.get("side") == "LONG" else "bear"
            side_icon = "▲" if pos.get("side") == "LONG" else "▼"
            upnl = pos.get("unrealized_pnl", 0)
            upnl_style = "pnl.pos" if upnl >= 0 else "pnl.neg"
            content.append(f"  [{side_style}]{side_icon} {pos.get('side', '?')}[/{side_style}] ", style=side_style)
            content.append(f"{pos.get('symbol', '?')}", style="brand")
            content.append(f" @ ${pos.get('entry_price', 0):,.2f}", style="muted")
            content.append(f"  P&L: ", style="label")
            content.append(f"${upnl:+,.2f}\n", style=upnl_style)
    else:
        content.append("\n  [dim]Sin posiciones abiertas[/dim]\n", style="dim")

    return Panel(
        content,
        title=f"{LOGO_SMALL} [label]Paper Trading[/label]",
        border_style="panel.border",
        box=box.ROUNDED,
        padding=(1, 2),
    )


# ═══════════════════════════════════════════════════════
# METRICS DISPLAY
# ═══════════════════════════════════════════════════════

def metrics_panel(metrics: dict, title: str = "Métricas") -> Panel:
    """Panel de métricas con colores por calidad."""
    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column("metric", style="label", min_width=20)
    table.add_column("value", justify="right", style="value")
    table.add_column("status", justify="center", min_width=3)

    thresholds = {
        "sharpe":        (1.0, 0.5),
        "sortino":       (1.5, 0.7),
        "max_dd_pct":    (-15, -25),
        "win_rate":      (50, 40),
        "profit_factor": (1.5, 1.0),
        "calmar":        (1.0, 0.5),
    }

    for key, val in metrics.items():
        if isinstance(val, (int, float)):
            good, acceptable = thresholds.get(key, (None, None))
            if good is not None:
                if key == "max_dd_pct":
                    icon = "[ok]●[/ok]" if val > good else "[warn]▲[/warn]" if val > acceptable else "[error]✗[/error]"
                else:
                    icon = "[ok]●[/ok]" if val >= good else "[warn]▲[/warn]" if val >= acceptable else "[error]✗[/error]"
            else:
                icon = ""

            formatted = f"{val:,.2f}%" if "pct" in key or "rate" in key else f"{val:,.2f}"
            table.add_row(key.replace("_", " ").title(), formatted, icon)

    return Panel(
        table,
        title=f"{LOGO_SMALL} [label]{title}[/label]",
        border_style="panel.border",
        box=box.ROUNDED,
        padding=(1, 2),
    )


# ═══════════════════════════════════════════════════════
# PRODUCTION CHECK
# ═══════════════════════════════════════════════════════

def production_check_panel(levels: dict) -> Panel:
    """Panel de production-check con los 4 niveles."""
    content = Text()

    level_names = {
        1: ("Paper Trading", "brand"),
        2: ("Prop Firm Ready", "sideways"),
        3: ("Hedge Fund Grade", "bull"),
        4: ("Wealth Management", "transitioning"),
    }

    for level, criteria in levels.items():
        name, style = level_names.get(level, (f"Level {level}", "muted"))
        passed = sum(1 for c in criteria if c.get("passed"))
        total = len(criteria)
        all_pass = passed == total

        icon = "✓" if all_pass else "⚠" if passed > 0 else "✗"
        icon_style = "ok" if all_pass else "warn" if passed > 0 else "error"

        content.append(f"\n  [{icon_style}]{icon}[/{icon_style}] ", style=icon_style)
        content.append(f"Level {level}: ", style="label")
        content.append(f"{name}", style=style)
        content.append(f"  {passed}/{total}\n", style="muted")

        for c in criteria:
            c_icon = "[ok]✓[/ok]" if c.get("passed") else "[error]✗[/error]"
            content.append(f"      {c_icon} {c['name']}", style="muted")
            content.append(f"  {c.get('value', '—')} / {c.get('threshold', '—')}\n", style="dim")

    return Panel(
        content,
        title=f"{LOGO_SMALL} [label]Production Readiness Check[/label]",
        border_style="panel.border",
        box=box.HEAVY,
        padding=(1, 2),
    )


# ═══════════════════════════════════════════════════════
# STATUS BAR (bottom bar)
# ═══════════════════════════════════════════════════════

def status_bar(data_ok: bool, regime_ok: bool, claude_calls: int,
               claude_cost: float, tokens_in: int, tokens_out: int) -> Text:
    """Barra de estado inferior."""
    bar = Text()

    # Data Service
    bar.append(" DATA ", style="brand.bg" if data_ok else "critical")
    bar.append(" ", style="dim")

    # Regime Service
    bar.append(" HMM ", style="brand.bg" if regime_ok else "critical")
    bar.append("  │  ", style="dim")

    # Claude API
    cost_style = "ok" if claude_cost < 0.10 else "warn" if claude_cost < 1.0 else "error"
    bar.append("Claude API: ", style="label")
    bar.append(f"{claude_calls} calls", style="muted")
    bar.append(" · ", style="dim")
    bar.append(f"${claude_cost:.4f}", style=cost_style)
    bar.append(" · ", style="dim")
    bar.append(f"{tokens_in // 1000}k/{tokens_out // 1000}k tok", style="muted")

    return bar


# ═══════════════════════════════════════════════════════
# DASHBOARD COMPLETO (btquantr status)
# ═══════════════════════════════════════════════════════

def render_dashboard(symbols: list, services: list, portfolio: dict,
                     claude: dict, security: dict, apis: list):
    """
    Renderiza el dashboard completo de BTQUANTR.
    Uso: render_dashboard(symbols, services, portfolio, claude, security, apis)
    """
    console.clear()
    print_banner()
    console.print()

    # Fila 1: Símbolos
    console.print(panel_symbols(symbols))

    # Fila 2: Portfolio + Claude + Security
    row2 = Columns([
        panel_portfolio(portfolio),
        panel_claude_api(claude),
        panel_security(security),
    ], equal=True, expand=True)
    console.print(row2)

    # Fila 3: Services + APIs
    row3 = Columns([
        panel_services(services),
        panel_apis(apis),
    ], equal=True, expand=True)
    console.print(row3)

    # Status bar
    console.print()
    console.print(status_bar(
        data_ok=any(s.get("status") == "ok" for s in services if "Data" in s.get("name", "")),
        regime_ok=any(s.get("status") == "ok" for s in services if "Regime" in s.get("name", "")),
        claude_calls=claude.get("calls", 0),
        claude_cost=claude.get("cost", 0),
        tokens_in=claude.get("tokens_in", 0),
        tokens_out=claude.get("tokens_out", 0),
    ))


# ═══════════════════════════════════════════════════════
# PROGRESS BAR PARA DEBATES
# ═══════════════════════════════════════════════════════

def create_debate_progress() -> Progress:
    """Progress bar estilizada para debates."""
    return Progress(
        SpinnerColumn("dots", style="brand"),
        TextColumn("[brand]◆[/brand] {task.description}", style="value"),
        BarColumn(bar_width=20, style="dim", complete_style="brand", finished_style="ok"),
        TextColumn("{task.fields[status]}", style="muted"),
        TimeElapsedColumn(),
        console=console,
    )


# ═══════════════════════════════════════════════════════
# EJEMPLO DE USO
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    """Demo del tema BTQUANTR."""

    print_banner()
    console.print()

    # Símbolos
    console.print(panel_symbols([
        {"symbol": "BTCUSDT", "price": 66835.0, "change": 1.23, "regime": "BULL", "funding": 0.0043, "oi": 21526, "ls_ratio": 1.73},
        {"symbol": "ETHUSDT", "price": 1975.8, "change": -0.45, "regime": "SIDEWAYS", "funding": 0.0125, "oi": 595321, "ls_ratio": 2.14},
    ]))

    # Portfolio + Claude + Security
    console.print(Columns([
        panel_portfolio({"balance": 10234.50, "initial_balance": 10000, "trades": 12, "win_rate": 58.3, "open_positions": 1}),
        panel_claude_api({"calls": 7, "cost": 0.0043, "tokens_in": 12340, "tokens_out": 8920, "last_call": "14:32:15"}),
        panel_security({"injections": 0, "invalid_outputs": 0, "enforcer_blocks": 0}),
    ], equal=True, expand=True))

    # Services + APIs
    console.print(Columns([
        panel_services([
            {"name": "Data Service", "status": "ok", "last_update": "14:32:09"},
            {"name": "Regime Service", "status": "ok", "last_update": "14:32:31"},
            {"name": "Paper Trading", "status": "ok", "last_update": "14:32:15"},
        ]),
        panel_apis([
            {"name": "Binance", "requests": 152, "errors": 0, "status": "ok"},
            {"name": "HyperLiquid", "requests": 48, "errors": 0, "status": "ok"},
            {"name": "Alternative.me", "requests": 24, "errors": 0, "status": "ok"},
            {"name": "yfinance", "requests": 18, "errors": 1, "status": "warn"},
        ]),
    ], equal=True, expand=True))

    # Debate
    print_header("Último Debate")
    console.print(debate_panel([
        {"name": "Gate 1: Data Quality", "type": "data_quality", "status": "done", "result": "CLEAN"},
        {"name": "Gate 2: Régimen HMM", "type": "regime", "status": "done", "result": "BULL HIGH"},
        {"name": "Technical Analyst", "type": "technical", "status": "done", "result": "NEUTRAL 20%"},
        {"name": "Sentiment Analyst", "type": "sentiment", "status": "done", "result": "EXTREME_FEAR 72%"},
        {"name": "Bull Advocate", "type": "bull", "status": "done", "result": "58% conf"},
        {"name": "Bear Advocate", "type": "bear", "status": "done", "result": "68% conf"},
        {"name": "Risk Manager", "type": "risk_manager", "status": "done", "result": "VETO"},
    ], symbol="BTCUSDT", status="complete"))

    console.print(debate_result_panel(
        "BTCUSDT", "VETO",
        reason="transition_risk=0.50, Bear>Bull, sin OHLCV",
        agents_summary={
            "Technical": "NEUTRAL 20%",
            "Sentiment": "EXTREME_FEAR 72% → contrarian LONG",
            "Bull": "58% — F&G contrarian, HMM BULL",
            "Bear": "68% — sin OHLCV, VIX adverso",
        }
    ))

    # Monitor alert
    print_header("Monitor Alert")
    console.print(monitor_alert("BTCUSDT", "BULL", 92.3, 0.85))

    # Metrics
    print_header("Métricas")
    console.print(metrics_panel({
        "sharpe": 1.23,
        "sortino": 1.87,
        "max_dd_pct": -8.3,
        "win_rate": 58.3,
        "profit_factor": 1.65,
        "calmar": 1.42,
    }))

    # Production check
    print_header("Production Check")
    console.print(production_check_panel({
        1: [
            {"name": "Trades > 50", "value": "12", "threshold": "50", "passed": False},
            {"name": "Semanas > 3", "value": "1", "threshold": "3", "passed": False},
            {"name": "Sharpe > 1.0", "value": "1.23", "threshold": "1.0", "passed": True},
            {"name": "Max DD < 15%", "value": "-8.3%", "threshold": "-15%", "passed": True},
        ],
        2: [
            {"name": "Consistency > 60", "value": "—", "threshold": "60", "passed": False},
            {"name": "DD diario < 4%", "value": "—", "threshold": "4%", "passed": False},
        ],
        3: [
            {"name": "MC prob_profitable > 85%", "value": "—", "threshold": "85%", "passed": False},
            {"name": "WFE > 50%", "value": "—", "threshold": "50%", "passed": False},
        ],
    }))

    # Status bar
    console.print()
    console.print(status_bar(True, True, 7, 0.0043, 12340, 8920))
