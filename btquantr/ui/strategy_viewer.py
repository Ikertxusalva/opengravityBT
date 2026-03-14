"""btquantr/ui/strategy_viewer.py — Dashboard Rich para StrategyStore.

Muestra todas las estrategias registradas con: nombre, símbolo, régimen,
fitness, Sharpe, trades, Walk-Forward status y código fuente opcional.
"""
from __future__ import annotations

from datetime import datetime

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from btquantr.engine.strategy_store import StrategyStore
from btquantr.ui.theme import LOGO_SMALL, console, regime_badge


class StrategyViewer:
    """Dashboard Rich que lee el StrategyStore y renderiza estrategias."""

    def __init__(self, store: StrategyStore | None = None) -> None:
        self._store = store or StrategyStore()

    # ─────────────────────────────────────────────────────────────────────────
    # API pública
    # ─────────────────────────────────────────────────────────────────────────

    def show(
        self,
        symbol_filter: str | None = None,
        show_code: bool = False,
    ) -> None:
        """Muestra el dashboard completo de estrategias.

        Args:
            symbol_filter: Si se especifica, muestra solo ese símbolo (case-insensitive).
            show_code:     Si True, muestra el código fuente de cada estrategia.
        """
        registry = self._store.list_registry()
        if not registry:
            console.print(
                "[muted]No hay estrategias en el StrategyStore. "
                "Ejecuta primero: [brand]btquantr engine evolve[/brand][/muted]"
            )
            return

        strategies = self._enrich_registry(registry, symbol_filter)

        if not strategies:
            if symbol_filter:
                console.print(
                    f"[muted]Sin estrategias para símbolo [brand]{symbol_filter.upper()}[/brand]. "
                    f"Prueba sin --symbol para ver todas.[/muted]"
                )
            else:
                console.print("[muted]Store vacío.[/muted]")
            return

        console.print(self.render_strategies_table(strategies))

        if show_code:
            for entry in strategies:
                full = entry.get("_full", {})
                console.print(
                    self.render_strategy_detail(full, entry["symbol"], entry["regime"])
                )

    def _enrich_registry(
        self,
        registry: list[dict],
        symbol_filter: str | None,
    ) -> list[dict]:
        """Combina registry entries con datos completos del store.

        Args:
            registry:      Lista de entries de StrategyStore.list_registry().
            symbol_filter: Filtro de símbolo (case-insensitive). None = todos.

        Returns:
            Lista de entries enriquecidos con clave '_full' (dict completo del store).
        """
        enriched: list[dict] = []
        for entry in registry:
            sym = entry.get("symbol", "")
            if symbol_filter and sym.upper() != symbol_filter.upper():
                continue
            regime = entry.get("regime", "BULL")
            full = self._store.get_best(sym, regime) or {}
            enriched.append({**entry, "_full": full})
        return enriched

    # ─────────────────────────────────────────────────────────────────────────
    # Render: tabla principal
    # ─────────────────────────────────────────────────────────────────────────

    def render_strategies_table(self, strategies: list[dict]) -> Table:
        """Construye la tabla Rich con todas las estrategias.

        Args:
            strategies: Lista de entries enriquecidos (con clave '_full').

        Returns:
            Rich Table lista para imprimir.
        """
        total = len(strategies)
        tbl = Table(
            title=f"[brand]StrategyStore — {total} estrategia{'s' if total != 1 else ''} registrada{'s' if total != 1 else ''}[/brand]",
            box=box.ROUNDED,
            border_style="panel.border",
            show_lines=True,
        )
        tbl.add_column("#",            justify="right",  style="muted",   width=4)
        tbl.add_column("Nombre",       style="label",    min_width=28)
        tbl.add_column("Símbolo",      style="brand",    width=10)
        tbl.add_column("Régimen",      min_width=12)
        tbl.add_column("Fitness",      justify="right",  width=9)
        tbl.add_column("Sharpe",       justify="right",  width=8)
        tbl.add_column("Trades",       justify="right",  width=8)
        tbl.add_column("Walk-Forward", justify="center", width=14)
        tbl.add_column("Registrado",   style="muted",    width=16)

        for i, entry in enumerate(strategies, 1):
            full    = entry.get("_full", {})
            regime  = entry.get("regime", "?")
            rf      = full.get("regime_fitness", {})
            rd      = rf.get(regime, {})
            sharpe  = rd.get("sharpe", 0.0)
            trades  = rd.get("trades", 0)
            fitness = entry.get("fitness", full.get("fitness", 0.0))
            ts      = entry.get("timestamp", 0)
            dt_str  = (
                datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
                if ts else "—"
            )

            fitness_style = "ok"   if fitness >= 0.7 else "warn" if fitness >= 0.4 else "error"
            sharpe_style  = "ok"   if sharpe  >= 1.0 else "warn" if sharpe  >= 0.5 else "muted"

            tbl.add_row(
                str(i),
                entry.get("name", "?"),
                entry.get("symbol", "?"),
                regime_badge(regime),
                f"[{fitness_style}]{fitness:.4f}[/{fitness_style}]",
                f"[{sharpe_style}]{sharpe:.2f}[/{sharpe_style}]",
                str(trades),
                "[ok]✓ ROBUST[/ok]",
                dt_str,
            )

        return tbl

    # ─────────────────────────────────────────────────────────────────────────
    # Render: panel de detalle con código fuente
    # ─────────────────────────────────────────────────────────────────────────

    def render_strategy_detail(
        self,
        strategy: dict,
        symbol: str,
        regime: str,
    ) -> Panel:
        """Panel de detalle con metadata y código fuente de la estrategia.

        Args:
            strategy: Dict completo de la estrategia (de StrategyStore.get_best).
            symbol:   Símbolo al que pertenece.
            regime:   Régimen registrado (BULL/BEAR/SIDEWAYS).

        Returns:
            Rich Panel listo para imprimir.
        """
        name       = strategy.get("name", "?")
        code       = strategy.get("code", "# (código no disponible)")
        params     = strategy.get("params", {})
        indicators = strategy.get("indicators", [])
        origin     = strategy.get("origin", "?")
        fitness    = strategy.get("fitness", 0.0)

        rf = strategy.get("regime_fitness", {})
        rd = rf.get(regime, {})
        sharpe = rd.get("sharpe", 0.0)
        trades = rd.get("trades", 0)

        meta_lines = [
            f"[label]Símbolo:     [/label][brand]{symbol}[/brand]",
            f"[label]Régimen:     [/label]{regime_badge(regime)}",
            f"[label]Fitness:     [/label][value]{fitness:.4f}[/value]",
            f"[label]Sharpe:      [/label][value]{sharpe:.2f}[/value]",
            f"[label]Trades:      [/label][value]{trades}[/value]",
            f"[label]Walk-Forward:[/label] [ok]✓ ROBUST[/ok]",
            f"[label]Origin:      [/label][muted]{origin}[/muted]",
            f"[label]Indicators:  [/label][muted]{', '.join(indicators) or '—'}[/muted]",
            f"[label]Params:      [/label][muted]{params or '—'}[/muted]",
        ]

        meta   = Text.from_markup("\n".join(meta_lines))
        syntax = Syntax(
            code, "python",
            theme="monokai",
            line_numbers=True,
            word_wrap=True,
        )
        content = Group(meta, Rule(style="panel.border"), syntax)

        return Panel(
            content,
            title=f"{LOGO_SMALL} [label]{name}[/label]",
            border_style="panel.border",
            box=box.ROUNDED,
            padding=(1, 2),
        )
