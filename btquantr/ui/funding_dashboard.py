"""Funding Rate Dashboard — Rich Live con WebSocket de HyperLiquid.

Muestra funding rates en tiempo real para todos los crypto perps y activos HIP3.
Usa WebSocket (wss://api.hyperliquid.xyz/ws) con suscripción activeAssetCtx.

Arquitectura:
  1. pre_populate_from_rest()  → carga inicial (crypto perps + HIP3 paginado)
  2. asyncio.gather de 3 loops:
     a. _receive_loop()        → recibe WS, actualiza _assets, NUNCA toca display
     b. _display_loop()        → timer: cada 60s llama live.update + live.refresh
     c. _rest_fallback_loop()  → cuando _ws_connected=False, hace REST cada 60s

CLI:
  btquantr dashboard funding
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

log = logging.getLogger("FundingDashboard")

# ─── Constantes ───────────────────────────────────────────────────────────────

WS_URL = "wss://api.hyperliquid.xyz/ws"
HOURS_PER_YEAR: int    = 8760    # 24 * 365
ALERT_THRESHOLD: float = 100.0   # |annualized %| > 100 → ⚠
DISPLAY_REFRESH_INTERVAL: int = 60   # segundos entre refreshes de pantalla
MAX_HIP3_PAGES: int    = 20      # límite de páginas para evitar loops infinitos
_RECONNECT_DELAY: float = 5.0    # segundos antes de reconectar WS (legacy, mantener compat)

# ─── Layout responsivo ───────────────────────────────────────────────────────
NARROW_LAYOUT_COLS: int = 120   # < 120 cols → layout 1 columna

# ─── Reconexión con backoff exponencial ──────────────────────────────────────
WS_RECONNECT_BASE_S: float = 5.0    # delay base (intento 0)
WS_RECONNECT_MAX_S:  float = 60.0   # cap máximo
WS_MAX_FAILURES:     int   = 3      # fallos consecutivos → REST fallback
WS_BACKGROUND_RETRY_S: int = 300    # cada 5 min reintenta WS desde REST fallback


def _is_hip3(name: str) -> bool:
    return name.startswith("xyz:") or name.startswith("cash:")


# ─────────────────────────────────────────────────────────────────────────────
# AssetFunding — estado de un activo
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AssetFunding:
    symbol: str
    funding: float = 0.0
    mark_price: float = 0.0
    open_interest: float = 0.0
    last_update: float = field(default_factory=time.time)

    @property
    def rate_pct(self) -> float:
        return self.funding * 100

    @property
    def annualized_pct(self) -> float:
        return self.rate_pct * HOURS_PER_YEAR

    @property
    def oi_usd(self) -> float:
        return self.open_interest * self.mark_price

    @property
    def is_hip3(self) -> bool:
        return _is_hip3(self.symbol)

    @property
    def alert(self) -> bool:
        return abs(self.annualized_pct) > ALERT_THRESHOLD


# ─────────────────────────────────────────────────────────────────────────────
# FundingDashboard
# ─────────────────────────────────────────────────────────────────────────────

class FundingDashboard:
    """Dashboard de funding rates con Rich Live + HyperLiquid WebSocket."""

    def __init__(self) -> None:
        self._assets: Dict[str, AssetFunding] = {}
        self._running: bool = False
        self._ws_connected: bool = False
        self._last_display: float = 0.0
        # Reconexión con backoff
        self._reconnect_attempt: int = 0
        self._ws_failed_count: int = 0
        self._next_ws_retry_at: float = 0.0

    # ── Carga desde REST ─────────────────────────────────────────────────────

    def _load_assets_from_meta(self, data: dict) -> List[str]:
        universe = data.get("meta", {}).get("universe", [])
        ctxs     = data.get("ctxs", [])
        coins: List[str] = []
        for asset, ctx in zip(universe, ctxs):
            name: str = asset.get("name", "")
            if not name:
                continue
            try:
                self._assets[name] = AssetFunding(
                    symbol=name,
                    funding=float(ctx.get("funding", 0)),
                    mark_price=float(ctx.get("markPx", 0)),
                    open_interest=float(ctx.get("openInterest", 0)),
                )
                coins.append(name)
            except (ValueError, TypeError) as e:
                log.debug("_load_assets: skip %s — %s", name, e)
        return coins

    def _fetch_all_hip3_coins(self, hl_source) -> List[str]:
        """Obtiene todos los activos HIP3 paginando hasta que no haya nextCursor."""
        coins: List[str] = []
        cursor: Optional[str] = None
        for _ in range(MAX_HIP3_PAGES):
            data = hl_source.get_meta_and_asset_ctxs(dex="xyz", cursor=cursor)
            page_coins = self._load_assets_from_meta(data)
            coins += page_coins
            cursor = data.get("nextCursor")
            if not cursor:
                break
        return coins

    def pre_populate_from_rest(self, hl_source=None) -> List[str]:
        """Carga crypto perps + todos los HIP3 paginados. Devuelve lista de coins."""
        if hl_source is None:
            from btquantr.data.sources.hyperliquid import HyperLiquidSource
            hl_source = HyperLiquidSource()

        coins: List[str] = []
        data_crypto = hl_source.get_meta_and_asset_ctxs()
        coins += self._load_assets_from_meta(data_crypto)
        coins += self._fetch_all_hip3_coins(hl_source)
        return coins

    # ── Procesamiento de mensajes WebSocket ──────────────────────────────────

    def update_from_ws_message(self, msg: dict) -> Optional[str]:
        """Actualiza _assets desde mensaje WS. Retorna coin si fue actualizado."""
        if not isinstance(msg, dict):
            return None
        if msg.get("channel") != "activeAssetCtx":
            return None
        data = msg.get("data")
        if not isinstance(data, dict):
            return None
        coin: Optional[str] = data.get("coin")
        ctx: Optional[dict] = data.get("ctx")
        if not coin or not isinstance(ctx, dict):
            return None
        try:
            funding = float(ctx.get("funding", 0))
            mark_px = float(ctx.get("markPx", 0))
            oi      = float(ctx.get("openInterest", 0))
        except (ValueError, TypeError):
            return None

        existing = self._assets.get(coin)
        if existing is None:
            self._assets[coin] = AssetFunding(
                symbol=coin, funding=funding, mark_price=mark_px, open_interest=oi,
            )
        else:
            existing.funding      = funding
            existing.mark_price   = mark_px
            existing.open_interest = oi
            existing.last_update  = time.time()
        return coin

    # ── Reconexión con backoff exponencial ──────────────────────────────────

    def _calc_reconnect_delay(self, attempt: int) -> float:
        """Backoff exponencial: base * 2^attempt, cappado a WS_RECONNECT_MAX_S."""
        delay = WS_RECONNECT_BASE_S * (2 ** attempt)
        return min(delay, WS_RECONNECT_MAX_S)

    def _on_ws_connected(self) -> None:
        """Llamado cuando se establece conexión WS exitosa."""
        self._ws_connected = True
        self._ws_failed_count = 0
        self._reconnect_attempt = 0

    def _on_ws_disconnected(self) -> None:
        """Llamado cuando se pierde conexión WS."""
        self._ws_connected = False
        self._ws_failed_count += 1
        if self._ws_failed_count >= WS_MAX_FAILURES:
            self._set_rest_fallback_mode()

    def _is_in_rest_fallback(self) -> bool:
        """True si estamos en modo REST fallback (demasiados fallos WS)."""
        return getattr(self, "_ws_failed_count", 0) >= WS_MAX_FAILURES

    # ── Throttling del display ───────────────────────────────────────────────

    def _should_refresh(self) -> bool:
        return (time.time() - self._last_display) >= DISPLAY_REFRESH_INTERVAL

    def _mark_displayed(self) -> None:
        self._last_display = time.time()

    def _get_live_kwargs(self) -> dict:
        return {"auto_refresh": False, "refresh_per_second": 0}

    # Kept for backward compat with existing tests
    def _process_message(self, msg: dict, live) -> None:
        coin = self.update_from_ws_message(msg)
        if coin and self._should_refresh():
            live.update(self._build_layout())
            live.refresh()
            self._mark_displayed()

    # ── Acceso a datos ordenados ─────────────────────────────────────────────

    def get_sorted_crypto(self, top_n: int = 30) -> List[AssetFunding]:
        assets = [a for a in self._assets.values() if not a.is_hip3]
        assets.sort(key=lambda a: abs(a.annualized_pct), reverse=True)
        return assets[:top_n]

    def get_sorted_hip3(self) -> List[AssetFunding]:
        assets = [a for a in self._assets.values() if a.is_hip3]
        assets.sort(key=lambda a: abs(a.annualized_pct), reverse=True)
        return assets

    # ── Detección de tamaño de terminal ─────────────────────────────────────

    def _get_terminal_cols(self) -> int:
        """Devuelve el número de columnas del terminal actual."""
        try:
            return shutil.get_terminal_size().columns
        except OSError:
            return 80

    def _is_narrow(self) -> bool:
        """True si el terminal es más estrecho que NARROW_LAYOUT_COLS."""
        return self._get_terminal_cols() < NARROW_LAYOUT_COLS

    # ── Construcción de tablas Rich ──────────────────────────────────────────

    def _make_table(self, title: str, assets: List[AssetFunding]):
        from rich.table import Table
        t = Table(title=title, show_lines=False, highlight=False,
                  title_style="bold cyan", border_style="dim", width=None)
        t.add_column("Symbol",       style="bold cyan", no_wrap=True, min_width=12)
        t.add_column("Rate %",       justify="right",   min_width=9)
        t.add_column("Annualized %", justify="right",   min_width=11)
        t.add_column("Mark Price",   justify="right",   style="dim", min_width=10)
        t.add_column("OI (USD)",     justify="right",   style="dim", min_width=12)
        t.add_column("",             justify="center",  min_width=2)
        for a in assets:
            rate_str = f"{a.rate_pct:+.4f}%"
            ann_str  = f"{a.annualized_pct:+.1f}%"
            if a.rate_pct > 0:
                rate_markup = f"[green]{rate_str}[/green]"
                ann_markup  = f"[green]{ann_str}[/green]"
            else:
                rate_markup = f"[red]{rate_str}[/red]"
                ann_markup  = f"[red]{ann_str}[/red]"
            if a.alert:
                ann_markup = f"[bold yellow]{ann_str}[/bold yellow]"
                alert_str  = "⚠"
            else:
                alert_str  = ""
            t.add_row(
                a.symbol,
                rate_markup, ann_markup,
                f"{a.mark_price:,.2f}",
                f"${a.oi_usd:,.0f}",
                alert_str,
            )
        return t

    def build_crypto_table(self, top_n: int = 30):
        return self._make_table(
            f"🔵 Crypto Perps — Top {top_n} by |Annualized %|",
            self.get_sorted_crypto(top_n=top_n),
        )

    def build_hip3_table(self):
        return self._make_table("🟡 HIP3 Tokenized Assets", self.get_sorted_hip3())

    # ── Footer de estado ─────────────────────────────────────────────────────

    def build_footer(self):
        """Footer con: Última actualización HH:MM:SS | N crypto + N HIP3 | WS estado."""
        from rich.text import Text

        n_crypto = sum(1 for a in self._assets.values() if not a.is_hip3)
        n_hip3   = sum(1 for a in self._assets.values() if a.is_hip3)

        ts = datetime.fromtimestamp(self._last_display).strftime("%H:%M:%S") \
            if self._last_display else "--:--:--"

        # Estado WS con detalle de reconexión
        if getattr(self, "_ws_connected", False):
            ws_text  = "WebSocket: conectado"
            ws_style = "green"
        elif self._is_in_rest_fallback():
            # Mostrar countdown hasta próximo intento WS
            remaining = max(0.0, getattr(self, "_next_ws_retry_at", 0.0) - time.time())
            mins  = int(remaining) // 60
            secs  = int(remaining) % 60
            ws_text  = f"REST fallback (próximo intento WS en {mins}:{secs:02d})"
            ws_style = "yellow"
        else:
            # Reconectando — mostrar intento N/MAX
            attempt = getattr(self, "_reconnect_attempt", 0)
            ws_text  = f"WebSocket: reconectando (intento {attempt}/{WS_MAX_FAILURES})"
            ws_style = "orange1"

        t = Text()
        t.append(f"Última actualización: {ts}", style="dim")
        t.append("  │  ", style="dim")
        t.append(f"Activos: {n_crypto} crypto + {n_hip3} HIP3", style="dim")
        t.append("  │  ", style="dim")
        t.append(ws_text, style=ws_style)
        return t

    # ── Layout Rich ──────────────────────────────────────────────────────────

    def _build_layout(self):
        """Layout responsivo: 2 columnas en terminal ancho (>=120), 1 columna en estrecho.
        El ancho se recalcula en cada llamada con shutil.get_terminal_size().
        """
        from rich.layout import Layout
        from rich.panel import Panel

        n_hip3 = len(self.get_sorted_hip3())
        crypto_panel = Panel(self.build_crypto_table(top_n=30),
                             border_style="dim", padding=(0, 0))
        hip3_panel   = Panel(self.build_hip3_table(),
                             border_style="dim", padding=(0, 0),
                             subtitle=f"[dim]{n_hip3} activos[/dim]")

        layout = Layout()
        layout.split_column(
            Layout(name="tables", ratio=1),
            Layout(name="footer", size=1),
        )

        if self._is_narrow():
            # Terminal estrecho → 1 columna: crypto arriba, HIP3 abajo
            layout["tables"].split_column(
                Layout(name="crypto", ratio=1),
                Layout(name="hip3",   ratio=1),
            )
        else:
            # Terminal ancho → 2 columnas lado a lado
            layout["tables"].split_row(
                Layout(name="crypto", ratio=1),
                Layout(name="hip3",   ratio=1),
            )

        layout["crypto"].update(crypto_panel)
        layout["hip3"].update(hip3_panel)
        layout["footer"].update(self.build_footer())
        return layout

    # ── Subscripciones WebSocket ─────────────────────────────────────────────

    def build_subscriptions(self, coins: List[str]) -> List[dict]:
        return [
            {"method": "subscribe", "subscription": {"type": "activeAssetCtx", "coin": c}}
            for c in coins
        ]

    # ── Loops async ─────────────────────────────────────────────────────────

    async def _receive_loop(self, coins: List[str], live) -> None:
        """Conecta WS, suscribe y recibe mensajes actualizando _assets.
        Usa backoff exponencial (5s, 10s, 20s, max 60s) en caso de error.
        Tras WS_MAX_FAILURES fallos consecutivos, cede el control al REST fallback.
        NUNCA llama live.update / live.refresh — eso es responsabilidad de _display_loop.
        """
        import websockets

        subs = self.build_subscriptions(coins)
        while self._running:
            # En REST fallback, esta loop espera hasta que sea hora de reintentar WS
            if self._is_in_rest_fallback():
                await asyncio.sleep(1.0)
                continue

            try:
                async with websockets.connect(
                    WS_URL, ping_interval=30, ping_timeout=10
                ) as ws:
                    self._on_ws_connected()
                    log.info("WS conectado (%d subs)", len(subs))
                    for sub in subs:
                        await ws.send(json.dumps(sub))
                        await asyncio.sleep(0.02)
                    async for raw in ws:
                        if not self._running:
                            break
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        self.update_from_ws_message(msg)   # ← solo datos, sin display
            except Exception as e:
                if not self._running:
                    break
                self._on_ws_disconnected()
                delay = self._calc_reconnect_delay(self._reconnect_attempt)
                self._reconnect_attempt += 1
                log.warning(
                    "WS error: %s — reconectando en %.0fs (intento %d)",
                    e, delay, self._reconnect_attempt,
                )
                await asyncio.sleep(delay)
            finally:
                self._ws_connected = False

    async def _display_loop(self, live) -> None:
        """Timer independiente: refresca el display cada DISPLAY_REFRESH_INTERVAL s."""
        while self._running:
            await asyncio.sleep(DISPLAY_REFRESH_INTERVAL)
            if not self._running:
                break
            live.update(self._build_layout())
            live.refresh()
            self._mark_displayed()

    async def _rest_fallback_loop(self, hl_source, live) -> None:
        """Cuando el WebSocket está caído, refresca datos via REST cada intervalo.
        Cuando estamos en REST fallback (3+ fallos), reintenta WS cada 5 minutos
        reseteando _ws_failed_count para que _receive_loop vuelva a intentar.
        """
        while self._running:
            await asyncio.sleep(DISPLAY_REFRESH_INTERVAL)
            if not self._running:
                break
            if not self._ws_connected:
                log.info("REST fallback: actualizando assets via REST")
                self.pre_populate_from_rest(hl_source)
                # Si estamos en REST fallback y es hora de reintentar WS, reset contadores
                if self._is_in_rest_fallback() and time.time() >= self._next_ws_retry_at:
                    log.info("REST fallback: reintentando WS (background retry)")
                    self._ws_failed_count = 0
                    self._reconnect_attempt = 0
                    self._next_ws_retry_at = time.time() + WS_BACKGROUND_RETRY_S

    def _set_rest_fallback_mode(self) -> None:
        """Activa modo REST fallback y programa próximo intento WS en 5 minutos."""
        self._next_ws_retry_at = time.time() + WS_BACKGROUND_RETRY_S

    # ── Entry point ──────────────────────────────────────────────────────────

    async def run(self) -> None:
        from btquantr.data.sources.hyperliquid import HyperLiquidSource
        from btquantr.ui.theme import console
        from rich.live import Live

        console.print("[bold cyan]Cargando datos iniciales via REST...[/bold cyan]")
        hl = HyperLiquidSource()
        coins = self.pre_populate_from_rest(hl)

        if not coins:
            console.print("[red]No se pudieron obtener activos de HyperLiquid.[/red]")
            return

        n_crypto = sum(1 for c in coins if not _is_hip3(c))
        n_hip3   = sum(1 for c in coins if _is_hip3(c))
        console.print(
            f"[green]{n_crypto} crypto + {n_hip3} HIP3 cargados.[/green] "
            f"Conectando WebSocket... (Ctrl+C para salir)"
        )

        self._running = True
        self._last_display = time.time()
        try:
            with Live(
                self._build_layout(),
                console=console,
                auto_refresh=False,
                screen=True,
            ) as live:
                live.refresh()
                await asyncio.gather(
                    self._receive_loop(coins, live),
                    self._display_loop(live),
                    self._rest_fallback_loop(hl, live),
                )
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            self._running = False
            console.print("\n[muted]Dashboard cerrado.[/muted]")

    def start(self) -> None:
        asyncio.run(self.run())
