"""CLI de BTQUANTR — comandos: data, regime, agents, debate, validate."""
import warnings
import concurrent.futures

import click
import colorama

# Timeout por estrategia en el tick-filter (segundos).
# Parcheable en tests: patch("btquantr.cli.TICK_FILTER_TIMEOUT_S", 1)
TICK_FILTER_TIMEOUT_S = 60
from rich.table import Table
from rich.panel import Panel
from dotenv import load_dotenv

from btquantr.ui.theme import (
    console, print_banner, print_header,
    panel_claude_api, panel_apis,
    debate_result_panel, monitor_alert,
    paper_status_panel, metrics_panel,
    regime_badge, regime_text, REGIME_STYLES,
    status_bar,
)

from btquantr.engine.seed_library import SeedLibrary
from btquantr.engine.generator import StrategyGenerator
from btquantr.engine.mutator import GeneticMutator
from btquantr.engine.scraper import GitHubScraper
from btquantr.engine.strategy_store import StrategyStore
from btquantr.engine.strategy_store_factory import get_strategy_store
from btquantr.engine.evolution_loop import EvolutionLoop
from btquantr.security.circuit_breakers import CircuitBreakerManager
from btquantr.execution.router import ExecutionRouter
from btquantr.execution.hl_connector import HLConnector
from btquantr.execution.pnl_tracker import PnLTracker

load_dotenv(override=False)  # carga ANTHROPIC_API_KEY desde .env si no está en entorno
colorama.init()               # habilita ANSI en Windows (cmd.exe / PowerShell)
warnings.filterwarnings("ignore", message="Broker canceled")


@click.group()
def main():
    """BTQUANTR — Sistema de trading algorítmico (Jim Simons method)."""
    pass


@main.group(invoke_without_command=True)
@click.option("--symbol", default="BTCUSDT", help="Símbolo a fetchear")
@click.option("--no-cache", "no_cache", is_flag=True, default=False,
              help="Ignorar caché en disco y descargar datos frescos.")
@click.pass_context
def data(ctx, symbol: str, no_cache: bool):
    """Fetch datos de mercado y publica en Redis. Subcomandos: funding-scanner."""
    ctx.ensure_object(dict)
    ctx.obj["symbol"] = symbol
    ctx.obj["no_cache"] = no_cache
    if ctx.invoked_subcommand is not None:
        return  # subcomando maneja la ejecución
    print_banner()
    from btquantr.redis_client import is_redis_available
    if not is_redis_available():
        console.print("[error]Redis no disponible. Ejecutar: docker run -d -p 6379:6379 redis:alpine[/error]")
        return
    from btquantr.data.service import DataService
    from btquantr.data.ohlcv_router import get_ohlcv
    console.print(f"[brand]Fetching {symbol}...[/brand]")
    if no_cache:
        console.print(f"[muted]--no-cache: descargando OHLCV fresco para {symbol}[/muted]")
    get_ohlcv(symbol, timeframe="1h", days=30, no_cache=no_cache)
    svc = DataService()
    res = svc.fetch_once(symbol)
    macro = svc.fetch_macro_once()
    t = Table(title=f"[brand]DataService — {symbol}[/brand]")
    t.add_column("Redis Key", style="label")
    t.add_column("Estado")
    for k in res["published"] + macro["published"]:
        t.add_row(k, "[ok]OK[/ok]")
    for k in res["errors"]:
        t.add_row(k, "[error]error[/error]")
    console.print(t)


@data.command("funding-scanner")
@click.option("--loop", is_flag=True, default=False,
              help=f"Ejecutar en loop cada {300}s (5 min). Sin --loop: ejecuta una vez.")
def funding_scanner(loop: bool):
    """Muestra funding rates de todos los crypto perps y activos HIP3 en HyperLiquid."""
    from btquantr.data.funding_scanner import FundingScanner
    scanner = FundingScanner()
    if loop:
        scanner.run_loop()
    else:
        scanner.run_once()


@data.command("smart-money")
@click.option("--symbols", default="BTCUSDT,ETHUSDT", help="Símbolos separados por coma")
@click.option("--threshold", default=3, type=int, help="Mínimo traders alineados para señal")
@click.option("--loop", is_flag=True, default=False, help="Loop cada 300s")
@click.option("--interval", default=300, type=int, help="Intervalo en segundos si --loop")
def smart_money(symbols: str, threshold: int, loop: bool, interval: int):
    """Trackea top traders HyperLiquid y genera señales de dirección."""
    from btquantr.redis_client import get_redis
    from btquantr.data.sources.smart_money_tracker import SmartMoneyTracker
    r = get_redis()
    sym_list = [s.strip() for s in symbols.split(",")]
    tracker = SmartMoneyTracker(r=r, threshold=threshold)
    if loop:
        tracker.run_loop(sym_list, interval_s=interval)
    else:
        t = Table(title="[brand]Smart Money Signals[/brand]")
        t.add_column("Symbol", style="label")
        t.add_column("Direction")
        t.add_column("Longs")
        t.add_column("Shorts")
        t.add_column("Count")
        for sym in sym_list:
            sig = tracker.publish(sym)
            dir_color = "ok" if sig["direction"] == "long" else ("error" if sig["direction"] == "short" else "muted")
            t.add_row(
                sym,
                f"[{dir_color}]{sig['direction'].upper()}[/{dir_color}]",
                str(sig["long_count"]),
                str(sig["short_count"]),
                str(sig["count"]),
            )
        console.print(t)


@data.command("orderflow")
@click.option("--symbols", default="BTC,ETH", help="Coins HyperLiquid separadas por coma")
@click.option("--duration", default=60, type=int, help="Segundos a escuchar el WebSocket")
def orderflow(symbols: str, duration: int):
    """Escucha trades HyperLiquid y calcula order flow imbalance en 5m/15m/1h/4h."""
    import asyncio
    from btquantr.redis_client import get_redis
    from btquantr.data.sources.orderflow import OrderFlowTracker
    r = get_redis()
    sym_list = [s.strip() for s in symbols.split(",")]
    tracker = OrderFlowTracker(symbols=sym_list, redis_client=r)

    async def _run():
        task = asyncio.create_task(tracker.subscribe_trades())
        await asyncio.sleep(duration)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())

    t = Table(title="[brand]Order Flow Imbalance[/brand]")
    t.add_column("Symbol", style="label")
    t.add_column("5m")
    t.add_column("15m")
    t.add_column("1h")
    t.add_column("4h")
    for sym in sym_list:
        imb = tracker._windows.get(sym, {})
        t.add_row(
            sym,
            f"{imb.get('5m', {}).imbalance_ratio() if imb.get('5m') else 0:.3f}",
            f"{imb.get('15m', {}).imbalance_ratio() if imb.get('15m') else 0:.3f}",
            f"{imb.get('1h', {}).imbalance_ratio() if imb.get('1h') else 0:.3f}",
            f"{imb.get('4h', {}).imbalance_ratio() if imb.get('4h') else 0:.3f}",
        )
    console.print(t)


@data.command("liq-multi")
@click.option("--symbols", default="BTCUSDT,ETHUSDT", help="Símbolos separados por coma")
@click.option("--duration", default=60, type=int, help="Segundos a escuchar WebSockets")
def liq_multi(symbols: str, duration: int):
    """Consolida liquidaciones de Binance + Bybit en Redis liq:{exchange}:{symbol}."""
    import asyncio
    from btquantr.redis_client import get_redis
    from btquantr.data.sources.multi_exchange_liq import MultiExchangeLiqSource
    r = get_redis()
    sym_list = [s.strip() for s in symbols.split(",")]
    source = MultiExchangeLiqSource(symbols=sym_list, redis_client=r)

    async def _run():
        await source.start()
        await asyncio.sleep(duration)
        await source.stop()

    asyncio.run(_run())

    t = Table(title="[brand]Multi-Exchange Liquidations[/brand]")
    t.add_column("Symbol", style="label")
    t.add_column("Exchange")
    t.add_column("Total Vol USD")
    t.add_column("Buy Liqs")
    t.add_column("Sell Liqs")
    for sym in sym_list:
        summary = source.get_summary(sym)
        for ex, data in summary.get("by_exchange", {}).items():
            t.add_row(
                sym, ex,
                f"${data.get('total_volume_usd', 0):,.0f}",
                str(data.get("buy_liq", 0)),
                str(data.get("sell_liq", 0)),
            )
    console.print(t)


@data.command("hlp-sentiment")
@click.option("--loop", is_flag=True, default=False, help="Loop cada 1h")
@click.option("--interval", default=3600, type=int, help="Intervalo en segundos si --loop")
def hlp_sentiment(loop: bool, interval: int):
    """Monitorea sentimiento del vault HLP: net delta + z-score 24h."""
    import asyncio
    import httpx
    from btquantr.redis_client import get_redis
    from btquantr.data.sources.hlp_sentiment import HLPSentimentTracker
    r = get_redis()

    async def _fetch_once():
        async with httpx.AsyncClient() as client:
            tracker = HLPSentimentTracker(redis_client=r, http_client=client)
            return await tracker.fetch()

    async def _run_loop():
        async with httpx.AsyncClient() as client:
            tracker = HLPSentimentTracker(redis_client=r, http_client=client)
            await tracker.run_loop(interval_seconds=interval)

    if loop:
        asyncio.run(_run_loop())
    else:
        snap = asyncio.run(_fetch_once())
        t = Table(title="[brand]HLP Vault Sentiment[/brand]")
        t.add_column("Metric", style="label")
        t.add_column("Value")
        sentiment_color = "ok" if snap["sentiment"] == "BULLISH" else ("error" if snap["sentiment"] == "BEARISH" else "muted")
        t.add_row("Sentiment", f"[{sentiment_color}]{snap['sentiment']}[/{sentiment_color}]")
        t.add_row("Net Delta", f"${snap['net_delta']:,.0f}")
        t.add_row("Z-Score 24h", f"{snap['z_score_24h']:.2f}")
        t.add_row("Position Count", str(snap["position_count"]))
        if snap.get("largest_position"):
            lp = snap["largest_position"]
            t.add_row("Largest", f"{lp['symbol']} {lp['side']} ${lp['size_usd']:,.0f}")
        console.print(t)


@main.command()
@click.option("--symbol", default="BTCUSDT")
@click.option("--steps", default=10, type=int)
@click.option("--no-cache", "no_cache", is_flag=True, default=False,
              help="Ignorar caché en disco y descargar datos frescos.")
def regime(symbol: str, steps: int, no_cache: bool):
    """Ejecuta el HMM + Regime Interpreter y muestra régimen actual."""
    print_banner()
    from btquantr.redis_client import is_redis_available
    if not is_redis_available():
        console.print("[error]Redis no disponible.[/error]")
        return
    from btquantr.data.ohlcv_router import get_ohlcv
    if no_cache:
        console.print(f"[muted]--no-cache: descargando OHLCV fresco para {symbol}[/muted]")
    get_ohlcv(symbol, timeframe="1h", days=30, no_cache=no_cache)
    import httpx
    from btquantr.regime.service import RegimeService
    from btquantr.agents.regime_interpreter import RegimeInterpreter
    from btquantr.redis_client import get_redis

    import numpy as np
    from btquantr.config import config as btq_config

    r = get_redis()
    svc = RegimeService(r)

    # Pre-seed histories con klines históricos de Binance.
    console.print(f"[brand]Cargando histórico {symbol}...[/brand]")
    try:
        resp = httpx.get(
            "https://fapi.binance.com/fapi/v1/klines",
            params={"symbol": symbol, "interval": "1m", "limit": 200},
            timeout=15.0,
        )
        candles = resp.json()
        if isinstance(candles, list) and len(candles) > 25:
            closes = [float(c[4]) for c in candles]

            buf = svc.collector._buf.setdefault(symbol, [])
            buf.extend(closes[-60:])

            sample = svc.collector.collect(symbol)
            feat_names = sorted(sample.keys())

            if len(feat_names) >= btq_config.hmm.min_features:
                static = {k: sample[k] for k in feat_names if k not in ("returns", "volatility")}
                start = 21 if "volatility" in feat_names else 1
                hist = svc.histories.setdefault(symbol, [])
                for i in range(start, len(closes)):
                    ret = float(np.log(closes[i] / closes[i - 1]))
                    win = closes[max(0, i - 21):i + 1]
                    vol = float(np.std(np.diff(np.log(win)))) if "volatility" in feat_names else None
                    vec = {**static}
                    if "returns" in feat_names:
                        vec["returns"] = ret
                    if "volatility" in feat_names and vol is not None:
                        vec["volatility"] = vol
                    if len(vec) == len(feat_names):
                        hist.append([vec[k] for k in feat_names])

                console.print(f"[muted]{len(hist)} obs históricas ({len(feat_names)} features: {', '.join(feat_names)})[/muted]")
            else:
                console.print("[warn]Pocas features en Redis — ejecutar 'btquantr data' primero[/warn]")
    except Exception as e:
        console.print(f"[muted]Sin pre-seed histórico: {e}[/muted]")

    console.print(f"[brand]{steps} ciclos HMM finales...[/brand]")
    result = None
    for _ in range(steps):
        result = svc.step(symbol)
        if result:
            break
    if result:
        r = get_redis()
        interp = RegimeInterpreter(r).run(symbol)
        reg = interp.get("regime", result["state_name"]) if interp else result["state_name"]
        conv = interp.get("conviction", "?") if interp else "?"
        actions = interp.get("allowed_actions", []) if interp else []
        rtext = regime_text(reg, confidence=result["confidence"] * 100, stability=result["stability"])
        console.print(Panel(
            rtext,
            title=f"[brand]Régimen BTQUANTR — {symbol}[/brand]",
            subtitle=f"Convicción: {conv} | Acciones: {', '.join(actions) or 'HOLD'} | Max size: {interp.get('max_size_pct', 0) if interp else '?'}%",
            border_style="panel.border",
        ))
    else:
        console.print("[warn]Datos insuficientes. Ejecutar 'btquantr data' primero.[/warn]")


def _start_status_bar_thread(r, symbols: list, interval: int = 30) -> None:
    """Daemon thread: imprime status_bar con stats de Claude API cada `interval` segundos."""
    import threading, time as _time
    from btquantr.monitoring.stats import read_claude_stats

    def _loop():
        _time.sleep(interval)          # primera impresión tras interval, no al arrancar
        while True:
            try:
                claude = read_claude_stats(r)
                sym = symbols[0] if symbols else "BTCUSDT"
                data_ok   = bool(r.exists(f"market:{sym}:price"))
                regime_ok = bool(r.exists(f"regime:{sym}"))
                bar = status_bar(
                    data_ok=data_ok,
                    regime_ok=regime_ok,
                    claude_calls=claude["calls"],
                    claude_cost=claude["cost"],
                    tokens_in=claude["tokens_in"],
                    tokens_out=claude["tokens_out"],
                )
                console.rule(style="dim")
                console.print(bar)
            except Exception:
                pass
            _time.sleep(interval)

    threading.Thread(target=_loop, daemon=True, name="StatusBar").start()


@main.command("run-all")
@click.option("--symbols", default="BTCUSDT,ETHUSDT", help="Símbolos separados por coma")
def run_all(symbols: str):
    """Levanta DataService + RegimeService en paralelo (un solo proceso)."""
    print_banner()
    from btquantr.redis_client import is_redis_available
    if not is_redis_available():
        console.print("[error]Redis no disponible.[/error]")
        return
    import logging, threading
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    from btquantr.data.service import DataService
    from btquantr.regime.service import RegimeService
    from btquantr.config import config as btq_config
    from btquantr.redis_client import get_redis

    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    btq_config.hmm.symbols = sym_list
    console.print(f"[brand]BTQUANTR stack — símbolos: {sym_list}[/brand]")

    r = get_redis()
    data_svc = DataService()
    regime_svc = RegimeService()

    t_data = threading.Thread(target=data_svc.run, name="DataService", daemon=True)
    t_regime = threading.Thread(target=regime_svc.run, name="RegimeService", daemon=True)

    t_data.start()
    t_regime.start()
    _start_status_bar_thread(r, sym_list)
    console.print("[muted]DataService + RegimeService activos. Ctrl+C para detener.[/muted]")

    try:
        t_data.join()
        t_regime.join()
    except KeyboardInterrupt:
        console.print("\n[warn]Deteniendo servicios...[/warn]")


@main.command("run-data")
@click.option("--symbols", default="BTCUSDT,ETHUSDT", help="Símbolos separados por coma")
def run_data(symbols: str):
    """Arranca DataService en loop: fetch HL + Binance + macro -> Redis 24/7."""
    print_banner()
    from btquantr.redis_client import is_redis_available
    if not is_redis_available():
        console.print("[error]Redis no disponible.[/error]")
        return
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    from btquantr.data.service import DataService
    from btquantr.config import config as btq_config
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    btq_config.hmm.symbols = sym_list
    console.print(f"[brand]DataService — símbolos: {sym_list}[/brand]")
    console.print(f"[muted]Loop cada {btq_config.data.fetch_interval}s[/muted]")
    svc = DataService()
    svc.run()


@main.command("run-regime")
@click.option("--symbols", default="BTCUSDT,ETHUSDT", help="Símbolos separados por coma")
def run_regime(symbols: str):
    """Arranca RegimeService en loop: bootstrap historico -> HMM 24/7."""
    print_banner()
    from btquantr.redis_client import is_redis_available
    if not is_redis_available():
        console.print("[error]Redis no disponible.[/error]")
        return
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    from btquantr.regime.service import RegimeService
    from btquantr.config import config as btq_config
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    btq_config.hmm.symbols = sym_list
    console.print(f"[brand]RegimeService — símbolos: {sym_list}[/brand]")
    console.print(f"[muted]Bootstrap -> loop cada {btq_config.hmm.predict_interval}s[/muted]")
    svc = RegimeService()
    svc.run()


async def _debate_live(sym: str, r, con) -> dict | None:
    """Debate con display rich en tiempo real — spinners por agente, resultado parcial al terminar."""
    import asyncio, time as _t
    from rich.live import Live
    from rich.table import Table as _Table

    STEPS = [
        ("gate1",     "Gate 1: Data Quality"),
        ("gate2",     "Gate 2: Régimen HMM"),
        ("technical", "Technical Analyst"),
        ("sentiment", "Sentiment Analyst"),
        ("bull",      "Bull Advocate"),
        ("bear",      "Bear Advocate"),
        ("risk",      "Risk Manager"),
    ]
    SPIN = "⣾⣽⣻⢿⡿⣟⣯⣷"
    state: dict[str, dict] = {k: {"st": "pending", "txt": "", "t0": 0.0} for k, _ in STEPS}

    def _grid():
        g = _Table.grid(padding=(0, 1))
        g.add_column(width=2, no_wrap=True)
        g.add_column(width=25, no_wrap=True)
        g.add_column()
        now = _t.time()
        for key, label in STEPS:
            s = state[key]
            if s["st"] == "pending":
                icon, txt = "[muted]·[/muted]", "[muted]esperando[/muted]"
            elif s["st"] == "running":
                c = SPIN[int((now - s["t0"]) * 8) % len(SPIN)]
                icon = f"[brand]{c}[/brand]"
                txt  = f"[brand]pensando… {now - s['t0']:.1f}s[/brand]"
            elif s["st"] == "done":
                icon, txt = "[ok]✓[/ok]", s["txt"]
            elif s["st"] == "skip":
                icon, txt = "[warn]⊘[/warn]", s["txt"]
            else:
                icon, txt = "[error]✗[/error]", s["txt"]
            g.add_row(icon, f"[bold]{label}[/bold]", txt)
        return Panel(g, title=f"[brand]Debate BTQUANTR — {sym}[/brand]",
                     border_style="brand", padding=(0, 1))

    def _go(key):
        state[key].update(st="running", t0=_t.time())

    def _done(key, txt="", ok=True):
        state[key].update(st="done" if ok else "error", txt=txt)

    def _skip(key, txt=""):
        state[key].update(st="skip", txt=txt)

    with Live(_grid(), refresh_per_second=12, console=con, transient=False) as live:
        upd = lambda: live.update(_grid())

        # ── Gate 1: Data Quality ─────────────────────────────────────────
        _go("gate1"); upd()
        try:
            from btquantr.agents.data_quality_auditor import DataQualityAuditor
            quality = await asyncio.to_thread(DataQualityAuditor(r).run, [sym])
            qst = quality.get("status", "BLOCKED")
            if qst == "BLOCKED":
                _done("gate1", "[error]BLOCKED — sin datos suficientes[/error]", ok=False); upd()
                return None
            _done("gate1", f"[ok]{qst}[/ok]")
        except Exception as e:
            _done("gate1", f"[error]{e}[/error]", ok=False); upd(); return None
        upd()

        # ── Gate 2: Régimen ──────────────────────────────────────────────
        _go("gate2"); upd()
        try:
            from btquantr.agents.regime_interpreter import RegimeInterpreter
            interp = await asyncio.to_thread(RegimeInterpreter(r).run, sym)
            reg  = (interp or {}).get("regime", "?")
            conv = (interp or {}).get("conviction", "?")
            acts = ", ".join((interp or {}).get("allowed_actions", [])) or "HOLD"
            if reg == "TRANSITIONING":
                _skip("gate2", "[warn]TRANSITIONING — sin operaciones[/warn]"); upd()
                return {"decision": "VETO", "veto_reason": "Régimen TRANSITIONING"}
            _done("gate2", f"{regime_badge(reg)} {conv} | {acts}")
        except Exception as e:
            _done("gate2", f"[error]{e}[/error]", ok=False); upd(); return None
        upd()

        # ── Fase 2: Technical + Sentiment (paralelo) ─────────────────────
        for k in ("technical", "sentiment"):
            _go(k)
        upd()

        async def _tech():
            from btquantr.agents.technical_analyst import TechnicalAnalyst
            return await asyncio.to_thread(TechnicalAnalyst(r).run, sym)

        async def _sent():
            from btquantr.agents.sentiment_analyst import SentimentAnalyst
            return await asyncio.to_thread(SentimentAnalyst(r).run, sym)

        rt, rs = await asyncio.gather(_tech(), _sent(), return_exceptions=True)

        if isinstance(rt, Exception):
            _done("technical", f"[error]{str(rt)[:60]}[/error]", ok=False)
        else:
            sig  = rt.get("signal", "?");  conf = rt.get("confidence", 0)
            sc   = {"LONG": "ok", "SHORT": "error"}.get(sig, "warn")
            _done("technical", f"[{sc}]{sig}[/{sc}] · conf:{conf}%")

        if isinstance(rs, Exception):
            _done("sentiment", f"[error]{str(rs)[:60]}[/error]", ok=False)
        else:
            sent = rs.get("sentiment", "?"); conf = rs.get("confidence", 0)
            contra = rs.get("contrarian_signal", "")
            sfx = f" → [brand]{contra}[/brand]" if contra else ""
            _done("sentiment", f"{sent} · conf:{conf}%{sfx}")
        upd()

        # ── Fase 3: Bull + Bear (debate ciego, paralelo) ─────────────────
        for k in ("bull", "bear"):
            _go(k)
        upd()

        async def _bull():
            from btquantr.agents.bull_advocate import BullAdvocate
            return await asyncio.to_thread(BullAdvocate(r).run, sym)

        async def _bear():
            from btquantr.agents.bear_advocate import BearAdvocate
            return await asyncio.to_thread(BearAdvocate(r).run, sym)

        rb, rbe = await asyncio.gather(_bull(), _bear(), return_exceptions=True)

        if isinstance(rb, Exception):
            _done("bull", f"[error]{str(rb)[:60]}[/error]", ok=False)
        else:
            bc = rb.get("confidence", 0)
            case = str(rb.get("bull_case", ""))[:60]
            _done("bull", f"conf:[ok]{bc}%[/ok] · {case}")

        if isinstance(rbe, Exception):
            _done("bear", f"[error]{str(rbe)[:60]}[/error]", ok=False)
        else:
            bc = rbe.get("confidence", 0)
            rec = rbe.get("recommendation", "")
            case = str(rbe.get("bear_case", ""))[:55]
            _done("bear", f"conf:[error]{bc}%[/error] · {rec} · {case}")
        upd()

        # ── Fase 4: Risk Manager ──────────────────────────────────────────
        _go("risk"); upd()
        try:
            from btquantr.agents.risk_manager import RiskManager
            risk = await asyncio.to_thread(RiskManager(r).run, sym)
            dec  = risk.get("decision", "?")
            size = risk.get("approved_size_pct", 0)
            rpct = risk.get("max_risk_pct", 0)
            dc   = {"APPROVE": "ok", "APPROVE_REDUCED": "warn", "VETO": "error"}.get(dec, "muted")
            ok   = dec != "VETO"
            _done("risk", f"[{dc}]{dec}[/{dc}] · size:{size}% · max-risk:{rpct}%", ok=ok)
        except Exception as e:
            risk = {"decision": "ERROR", "_error": str(e)}
            _done("risk", f"[error]{e}[/error]", ok=False)
        upd()

    return risk


@main.command()
@click.option("--symbol", default="BTCUSDT")
@click.option("--symbols", default=None, help="Símbolos separados por coma (override)")
@click.option("--yes", "-y", is_flag=True, default=False, help="Auto-confirmar sin preguntar")
def debate(symbol: str, symbols: str, yes: bool):
    """Debate Fase 2 con progreso en tiempo real (spinners + resultados parciales)."""
    print_banner()
    from btquantr.redis_client import is_redis_available
    if not is_redis_available():
        console.print("[error]Redis no disponible.[/error]")
        return
    import asyncio, json as _json
    from btquantr.redis_client import get_redis

    r = get_redis()
    from btquantr.agents.base import init_rate_limiter_redis
    init_rate_limiter_redis(r)
    targets = [s.strip() for s in symbols.split(",")] if symbols else [symbol]

    # ── Confirmación interactiva cuando hay oportunidad clara ─────────────
    if not yes:
        confirmed = []
        for sym in targets:
            raw = r.get(f"regime:{sym}:interpreted")
            interp = _json.loads(raw) if raw else {}
            reg  = interp.get("regime", "?")
            conv = interp.get("conviction", "?")
            if reg in ("BULL", "BEAR") and conv == "HIGH":
                allowed = ", ".join(interp.get("allowed_actions", [])) or "?"
                max_sz  = interp.get("max_size_pct", "?")
                console.print(
                    f"\n  {regime_badge(reg)} {sym} — convicción {conv} | "
                    f"acciones: {allowed} | max size: {max_sz}%"
                )
                answer = console.input("  ¿Ejecutar debate? [s/n]: ").strip().lower()
                if answer in ("s", "si", "sí", "y", "yes", ""):
                    confirmed.append(sym)
                else:
                    console.print(f"  [muted]Saltando {sym}[/muted]")
            else:
                confirmed.append(sym)
        if not confirmed:
            console.print("[warn]Todos los símbolos saltados.[/warn]")
            return
        targets = confirmed

    # ── Debate con display rich en tiempo real ────────────────────────────
    async def _run_all():
        results = {}
        for sym in targets:
            console.print()
            res = await _debate_live(sym, r, console)
            results[sym] = res

            if res is None:
                console.print(Panel(
                    "[warn]Gate bloqueado — sin señal[/warn]",
                    title=f"[label]Resultado — {sym}[/label]",
                    border_style="warn",
                ))
            elif "_error" in res:
                err = res["_error"]
                hint = " → añadir ANTHROPIC_API_KEY en .env" if "api_key" in err.lower() or "auth" in err.lower() else ""
                console.print(Panel(
                    f"[error]{err[:200]}{hint}[/error]",
                    title=f"[error]Error — {sym}[/error]",
                    border_style="error",
                ))
            else:
                dec    = res.get("decision", "?")
                size   = res.get("approved_size_pct", 0)
                risk   = res.get("max_risk_pct", 0)
                reason = (res.get("reasoning") or res.get("veto_reason") or "")[:140]
                conds  = res.get("conditions", [])
                agents_summary = {
                    "Size aprobado": f"{size}%",
                    "Max riesgo":    f"{risk}%",
                }
                if conds:
                    agents_summary["Condiciones"] = ", ".join(conds)[:120]
                console.print(debate_result_panel(sym, dec, reason=reason, agents_summary=agents_summary))
        return results

    asyncio.run(_run_all())


@main.command()
@click.option("--symbols", default="BTCUSDT,ETHUSDT", help="Símbolos a monitorear")
@click.option("--interval", default=60, type=int, help="Segundos entre checks")
def monitor(symbols: str, interval: int):
    """Monitor 24/7 (sin Claude): avisa cuando el régimen es accionable y pregunta si debate."""
    print_banner()
    from btquantr.redis_client import is_redis_available
    if not is_redis_available():
        console.print("[error]Redis no disponible.[/error]")
        return
    import asyncio, json as _json, time as _time
    from btquantr.redis_client import get_redis
    from btquantr.agents.orchestrator import Orchestrator

    r = get_redis()
    from btquantr.agents.base import init_rate_limiter_redis
    init_rate_limiter_redis(r)
    orch = Orchestrator(r)
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]

    prev_state: dict = {}  # {sym: (regime, conviction)}

    console.print(
        f"[brand]Monitor BTQUANTR — {sym_list} | check cada {interval}s | Ctrl+C para salir[/brand]"
    )

    def _read_regime(sym: str) -> dict:
        raw = r.get(f"regime:{sym}:interpreted")
        return _json.loads(raw) if raw else {}

    def _show_debate_result(sym: str, res: dict | None) -> None:
        if res is None:
            console.print(f"  [warn]{sym}: debate saltado por gate[/warn]")
            return
        if "_error" in res:
            console.print(f"  [error]{sym}: error — {res['_error'][:120]}[/error]")
            return
        decision = res.get("decision", "?")
        dc = {"APPROVE": "ok", "APPROVE_REDUCED": "warn", "VETO": "error"}.get(decision, "muted")
        size = res.get("approved_size_pct", 0)
        reason = (res.get("reasoning") or res.get("veto_reason") or "")[:100]
        console.print(f"  [{dc}]{sym} → {decision}[/{dc}] | size: {size}% | {reason}")

    try:
        while True:
            for sym in sym_list:
                interp = _read_regime(sym)
                reg = interp.get("regime", "?")
                conv = interp.get("conviction", "?")
                allowed = ", ".join(interp.get("allowed_actions", [])) or "HOLD"
                max_sz = interp.get("max_size_pct", 0)

                prev = prev_state.get(sym)
                current = (reg, conv)

                regime_changed = prev is not None and prev != current
                is_actionable = reg in ("BULL", "BEAR") and conv == "HIGH"

                if regime_changed or is_actionable:
                    prefix = "[CAMBIO] " if regime_changed else ""
                    if is_actionable:
                        # Alerta visual con monitor_alert del tema
                        conviction_pct = {"HIGH": 90.0, "MEDIUM": 70.0, "LOW": 50.0}.get(conv, 60.0)
                        stability = interp.get("stability", 0.8)
                        console.print()
                        console.print(monitor_alert(sym, reg, conviction_pct, stability))
                    else:
                        console.print(
                            f"\n  {regime_badge(reg)} {prefix}{sym} | convicción {conv} | "
                            f"acciones: {allowed} | max size: {max_sz}%"
                        )

                    if is_actionable:
                        try:
                            answer = console.input(
                                f"  ¿Ejecutar debate para {sym}? [s/n]: "
                            ).strip().lower()
                        except (EOFError, KeyboardInterrupt):
                            raise KeyboardInterrupt

                        if answer in ("s", "si", "sí", "y", "yes", ""):
                            console.print(f"  [brand]Lanzando debate {sym}...[/brand]")
                            results = asyncio.run(orch.run_once([sym]))
                            _show_debate_result(sym, results.get(sym))
                        else:
                            console.print(f"  [muted]{sym} saltado[/muted]")
                    elif regime_changed:
                        console.print(f"  [muted]{sym}: régimen no accionable — monitoreando[/muted]")

                prev_state[sym] = current

            _time.sleep(interval)

    except KeyboardInterrupt:
        console.print("\n[warn]Monitor detenido.[/warn]")


@main.command("api-stats")
def api_stats():
    """Muestra estado de todas las APIs: Claude (coste, tokens, rate limiter) + fuentes de datos."""
    print_banner()
    from btquantr.redis_client import is_redis_available
    if not is_redis_available():
        console.print("[error]Redis no disponible.[/error]")
        return
    import datetime
    from btquantr.redis_client import get_redis
    from btquantr.monitoring.stats import read_all
    from btquantr.agents.base import _rate_limiter

    r = get_redis()
    data = read_all(r)

    def _ts(val: str | None) -> str:
        if not val:
            return "nunca"
        try:
            dt = datetime.datetime.fromtimestamp(int(val))
            return dt.strftime("%d/%m %H:%M:%S")
        except Exception:
            return str(val)

    # ── Claude ────────────────────────────────────────────────────────────
    claude_raw = data.get("claude", {})
    rl = _rate_limiter.get_stats()

    calls_total = int(claude_raw.get("calls_total", 0))
    calls_ok    = int(claude_raw.get("calls_ok", 0))
    calls_err   = int(claude_raw.get("calls_err", 0))
    tokens_in   = int(claude_raw.get("tokens_in", 0))
    tokens_out  = int(claude_raw.get("tokens_out", 0))
    cost_usd    = int(claude_raw.get("cost_usd_micro", 0)) / 1_000_000
    last_model  = claude_raw.get("last_model", "?")
    last_call_str = _ts(claude_raw.get("last_call_ts"))

    print_header("Claude API")
    console.print(panel_claude_api({
        "calls":      calls_total,
        "cost":       cost_usd,
        "tokens_in":  tokens_in,
        "tokens_out": tokens_out,
        "last_call":  last_call_str,
    }))

    # Rate limiter info extra
    paused_str = "[error]PAUSADO[/error]" if rl["paused"] else "[ok]OK[/ok]"
    console.print(Panel(
        f"Modelo: [brand]{last_model}[/brand]\n"
        f"Rate limiter: {paused_str} | "
        f"último min: {rl['calls_last_minute']}/20 | "
        f"última hora: {rl['calls_last_hour']}/200\n"
        f"Llamadas: {calls_total} total  ([ok]{calls_ok}[/ok] ok / [error]{calls_err}[/error] err)\n"
        f"Coste hora: [warn]${rl['cost_last_hour']:.4f}[/warn]  "
        f"hoy: [warn]${rl['cost_today']:.4f}[/warn]  "
        f"total: [warn]${cost_usd:.6f}[/warn]",
        title="[brand]Rate Limiter[/brand]",
        border_style="panel.border",
    ))

    # ── APIs gratuitas ────────────────────────────────────────────────────
    print_header("APIs externas")
    sources = [
        ("binance",        "Binance"),
        ("hyperliquid",    "HyperLiquid"),
        ("alternative_me", "Alternative.me"),
        ("yfinance",       "yfinance"),
    ]
    apis_list = []
    for key, label in sources:
        s = data.get(key, {})
        reqs = int(s.get("requests", 0))
        errs = int(s.get("errors", 0))
        status = "ok" if errs == 0 else "warn" if reqs and errs / reqs < 0.3 else "error"
        apis_list.append({
            "name":     label,
            "requests": reqs,
            "errors":   errs,
            "status":   status,
        })
    console.print(panel_apis(apis_list))


@main.command()
@click.option("--symbol", default="BTCUSDT")
def agents(symbol: str):
    """Corre los agentes de Fase 1: Data Quality Auditor + Regime Interpreter."""
    print_banner()
    from btquantr.redis_client import is_redis_available
    if not is_redis_available():
        console.print("[error]Redis no disponible.[/error]")
        return
    from btquantr.redis_client import get_redis
    from btquantr.agents.data_quality_auditor import DataQualityAuditor
    from btquantr.agents.regime_interpreter import RegimeInterpreter
    r = get_redis()
    print_header("Data Quality Auditor")
    quality = DataQualityAuditor(r).run([symbol])
    status_style = {"CLEAN": "ok", "DEGRADED": "warn", "BLOCKED": "error"}.get(quality["status"], "muted")
    console.print(f"  Status: [{status_style}]{quality['status']}[/{status_style}]")
    print_header("Regime Interpreter")
    interp = RegimeInterpreter(r).run(symbol)
    if interp:
        reg = interp.get("regime", "?")
        console.print(f"  Régimen: {regime_badge(reg)} ({interp.get('conviction')})")
        console.print(f"  Acciones: {', '.join(interp.get('allowed_actions', []))}")
    else:
        console.print("  [warn]Sin datos HMM aún — ejecutar 'btquantr data' + 'btquantr regime'[/warn]")


@main.command()
@click.argument("ticker", default="BTC-USD")
@click.option("--days", default=365, type=int)
def validate(ticker: str, days: int):
    """Valida el HMM con walk-forward backtest histórico."""
    print_banner()
    import warnings, numpy as np, yfinance as yf, pandas as pd
    from btquantr.regime.validator import walk_forward_backtest, validate_detector
    warnings.filterwarnings("ignore", category=UserWarning, module="hmmlearn")
    console.print(f"[brand]Validando HMM — {ticker} {days}d...[/brand]")
    data = yf.Ticker(ticker).history(period=f"{days}d", interval="1d")
    if len(data) < 100:
        console.print("[error]Datos insuficientes.[/error]")
        return
    prices = data["Close"]
    features = pd.DataFrame(index=data.index)
    features["returns"] = np.log(prices / prices.shift(1))
    features["volatility"] = features["returns"].rolling(21).std()
    features["range_norm"] = (data["High"] - data["Low"]) / data["Close"]
    features = features.dropna()
    console.print("[muted]Walk-forward en progreso...[/muted]")
    n = len(features)
    train_w = min(500, max(60, n // 4))
    step_w  = max(10, n // 20)
    console.print(f"[muted]{n} barras — train_window={train_w}, step={step_w}[/muted]")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        results = walk_forward_backtest(prices.loc[features.index], features,
                                        train_window=train_w, step=step_w)
    if results.empty:
        console.print("[error]Sin resultados.[/error]")
        return
    report = validate_detector(results)
    t = Table(title=f"[brand]Validación HMM — {ticker}[/brand]")
    t.add_column("Test", style="label"); t.add_column("Valor", style="value"); t.add_column("Pass")
    checks = [
        ("Estados distintos (ANOVA p<0.05)", f"p={report.get('anova_p', 'N/A')}", report.get("states_different")),
        ("Sharpe cond. > BnH", f"{report.get('regime_sharpe','?')} vs {report.get('bnh_sharpe','?')}", report.get("sharpe_improves")),
        ("Duración media > 20", f"{report.get('avg_state_duration','?')}", report.get("duration_ok")),
        ("DD cond. < DD BnH", f"{report.get('strat_max_dd','?')}% vs {report.get('bnh_max_dd','?')}%", report.get("dd_improves")),
    ]
    for name, val, passed in checks:
        t.add_row(name, str(val), "[ok]PASS[/ok]" if passed else "[error]FAIL[/error]")
    console.print(t)
    verdict = report.get("VERDICT", "FAIL")
    v_style = "ok" if verdict == "PASS" else "error"
    console.print(f"\n[{v_style}]VEREDICTO: {verdict} ({report.get('tests_passed',0)}/4)[/{v_style}]")


# ─────────────────────────────────────────────────────────────────────────────
# PAPER TRADING — btquantr paper <subcomando>
# ─────────────────────────────────────────────────────────────────────────────

@main.group()
def paper():
    """Paper trading — posiciones virtuales con comisión + slippage reales."""
    pass


def _get_paper_portfolio():
    """Helper: conecta a Redis y retorna PaperPortfolio, o None si Redis no está disponible."""
    from btquantr.redis_client import is_redis_available
    if not is_redis_available():
        console.print("[error]Redis no disponible.[/error]")
        return None
    from btquantr.redis_client import get_redis
    from btquantr.paper_trading.portfolio import PaperPortfolio
    return PaperPortfolio(get_redis())


@paper.command("status")
def paper_status():
    """Posiciones abiertas y balance actual."""
    print_banner()
    portfolio = _get_paper_portfolio()
    if portfolio is None:
        return
    state = portfolio.get_state()
    balance = portfolio.get_balance()

    # Build positions list for paper_status_panel
    positions = []
    for sym, pos in (state or {}).items():
        positions.append({
            "symbol":         sym,
            "side":           pos.get("side", "?"),
            "entry_price":    pos.get("entry_price", 0),
            "unrealized_pnl": pos.get("unrealized_pnl", 0),
        })

    portfolio_dict = {
        "balance":         balance,
        "initial_balance": 10_000.0,  # default reset value
    }
    console.print(paper_status_panel(portfolio_dict, positions))


@paper.command("history")
@click.option("--limit", default=20, type=int, help="Últimos N trades")
def paper_history(limit: int):
    """Historial de trades cerrados."""
    print_banner()
    portfolio = _get_paper_portfolio()
    if portfolio is None:
        return
    trades = portfolio.get_history(limit=limit)

    if not trades:
        console.print("[muted]Sin historial de trades.[/muted]")
        return

    print_header(f"Últimos {limit} trades")
    t = Table(show_lines=True)
    t.add_column("Símbolo", style="brand")
    t.add_column("Side")
    t.add_column("PnL USD", justify="right")
    t.add_column("PnL %", justify="right")
    t.add_column("Régimen", style="label")
    t.add_column("Fecha", style="muted")
    for tr in trades:
        pnl = tr["net_pnl_usd"]
        pnl_style = "pnl.pos" if pnl >= 0 else "pnl.neg"
        side_style = "bull" if tr["side"] == "LONG" else "bear"
        t.add_row(
            tr["symbol"],
            f"[{side_style}]{tr['side']}[/{side_style}]",
            f"[{pnl_style}]${pnl:+,.2f}[/{pnl_style}]",
            f"[{pnl_style}]{tr['pnl_pct']:+.2f}%[/{pnl_style}]",
            tr.get("regime_at_entry", "?"),
            tr.get("closed_at_str", "?"),
        )
    console.print(t)


@paper.command("metrics")
def paper_metrics():
    """Analytics institucionales completos (Phase 2.5B)."""
    print_banner()
    portfolio = _get_paper_portfolio()
    if portfolio is None:
        return
    report = portfolio.get_analytics()

    if report.get("status") == "NO_TRADES":
        console.print("[warn]Sin trades en historial. Ejecuta primero 'btquantr paper start'.[/warn]")
        return

    summary = report["summary"]
    verdict = summary["verdict"]
    verdict_style = {"APROBADO": "ok", "PRECAUCIÓN": "warn", "RECHAZADO": "error"}.get(verdict, "muted")

    print_header("Analytics Institucionales 2.5B")

    # Veredicto
    console.print(Panel(
        f"[{verdict_style}]{verdict}[/{verdict_style}]  "
        f"  Score: {summary['score']:.2%}  |  Trades: {summary['total_trades']}",
        title="[brand]Veredicto[/brand]",
        border_style=verdict_style,
    ))

    # Consistencia via metrics_panel del tema
    c = report["consistency"]
    console.print(metrics_panel({
        "sharpe":          c["sharpe"],
        "sortino":         c["sortino"] if c["sortino"] != float("inf") else 999.0,
        "win_rate":        c["win_rate"] * 100,
        "profit_factor":   c["profit_factor"] if c["profit_factor"] != float("inf") else 999.0,
        "max_dd_pct":      c["max_drawdown"] * 100,
        "calmar":          c["calmar"] if isinstance(c["calmar"], float) and c["calmar"] != float("inf") else 999.0,
    }, title="Consistencia"))

    # Monte Carlo
    mc = report["montecarlo"]
    mt = Table(title="[brand]Monte Carlo (500 sims)[/brand]", show_lines=False)
    mt.add_column("Métrica", style="label")
    mt.add_column("Valor", style="value", justify="right")
    mt.add_row("VaR 95%",       f"{mc['var_95']:.2%}")
    mt.add_row("VaR 99%",       f"{mc['var_99']:.2%}")
    mt.add_row("CVaR 95%",      f"{mc['cvar_95']:.2%}")
    mt.add_row("CVaR 99%",      f"{mc['cvar_99']:.2%}")
    mt.add_row("Prob. Ruina",   f"{mc['prob_ruin']:.2%}")
    mt.add_row("Mediana Final", f"{mc['median_final']:.2f}x")
    console.print(mt)

    # Performance por Régimen
    rs = report["regime_stress"]
    rt = Table(title="[brand]Performance por Régimen[/brand]", show_lines=True)
    rt.add_column("Régimen")
    rt.add_column("N", justify="right")
    rt.add_column("Sharpe", justify="right")
    rt.add_column("Mean Ret", justify="right")
    rt.add_column("Volatilidad", justify="right")
    _known_regimes = {"BULL", "BEAR", "SIDEWAYS", "TRANSITIONING"}
    for reg_name, m in rs["by_regime"].items():
        sharpe_style = "pnl.pos" if m["sharpe"] > 0 else "pnl.neg"
        reg_label = regime_badge(reg_name) if reg_name in _known_regimes else reg_name
        rt.add_row(
            reg_label,
            str(m["n_periods"]),
            f"[{sharpe_style}]{m['sharpe']:.3f}[/{sharpe_style}]",
            f"{m['mean_return']:.3%}",
            f"{m['volatility']:.3%}",
        )
    console.print(rt)

    best = rs["summary"].get("best_regime", "?")
    worst = rs["summary"].get("worst_regime", "?")
    console.print(f"[muted]Mejor: [ok]{best}[/ok] | Peor: [error]{worst}[/error][/muted]")


@paper.command("close")
@click.argument("symbol")
@click.option("--price", type=float, default=None, help="Precio de cierre (si no, usa Redis)")
def paper_close(symbol: str, price: float):
    """Cierra manualmente una posición."""
    print_banner()
    portfolio = _get_paper_portfolio()
    if portfolio is None:
        return
    if price is None:
        raw = portfolio.r.get(f"market:{symbol}:price")
        price = float(raw) if raw else None
    if price is None:
        console.print(f"[error]No hay precio para {symbol}. Usa --price.[/error]")
        return
    trade = portfolio.close_position(symbol, price, reason="MANUAL")
    if trade is None:
        console.print(f"[warn]No hay posición abierta para {symbol}.[/warn]")
        return
    pnl = trade["net_pnl_usd"]
    pnl_style = "pnl.pos" if pnl >= 0 else "pnl.neg"
    console.print(f"[{pnl_style}]Cerrado {symbol} | PnL: ${pnl:+,.2f} ({trade['pnl_pct']:+.2f}%)[/{pnl_style}]")


@paper.command("reset")
@click.option("--balance", default=10_000.0, type=float, help="Balance inicial")
@click.confirmation_option(prompt="¿Resetear portfolio completo?")
def paper_reset(balance: float):
    """Resetea portfolio: elimina posiciones e historial."""
    portfolio = _get_paper_portfolio()
    if portfolio is None:
        return
    portfolio.reset(balance)
    console.print(f"[ok]Portfolio reseteado — balance: ${balance:,.0f}[/ok]")


@paper.command("start")
@click.option("--symbols", default="BTCUSDT,ETHUSDT", help="Símbolos separados por coma")
@click.option("--interval", default=600, type=int, help="Segundos entre ciclos")
def paper_start(symbols: str, interval: int):
    """Arranca el loop de paper trading (ciclos cada N segundos)."""
    print_banner()
    from btquantr.redis_client import is_redis_available
    if not is_redis_available():
        console.print("[error]Redis no disponible.[/error]")
        return
    import asyncio, logging
    from btquantr.redis_client import get_redis
    from btquantr.paper_trading.orchestrator import PaperOrchestrator

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    r = get_redis()
    # Wiring completo: CircuitBreakerManager + ExecutionRouter (dry_run para paper)
    cb_manager = CircuitBreakerManager()
    router = ExecutionRouter(dry_run=True)
    orch = PaperOrchestrator(r, circuit_breakers=cb_manager, router=router)
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    balance = orch.portfolio.get_balance()
    console.print(f"[brand]Paper trading — símbolos: {sym_list} | balance: ${balance:,.0f}[/brand]")
    console.print(f"[muted]Ciclos cada {interval}s | loop: régimen→señal→CB→router | Ctrl+C para detener[/muted]")
    _start_status_bar_thread(r, sym_list)
    asyncio.run(orch.run(sym_list, interval=interval))

# ─────────────────────────────────────────────────────────────────────────────
# BACKTEST ENGINEER — btquantr backtest-engineer <subcomando>
# ─────────────────────────────────────────────────────────────────────────────

@main.group("backtest-engineer")
def backtest_engineer():
    """BacktestEngineer — análisis LLM de resultados de paper trading."""
    pass


@backtest_engineer.command("analyze")
@click.option("--symbol", default="ALL", show_default=True,
              help="Símbolo a analizar (ej: BTCUSDT) o ALL para todos.")
def be_analyze(symbol: str):
    """Analiza trades de paper trading con LLM y publica report en Redis."""
    print_banner()
    from btquantr.redis_client import is_redis_available
    if not is_redis_available():
        console.print("[error]Redis no disponible.[/error]")
        return
    from btquantr.redis_client import get_redis
    from btquantr.agents.backtest_engineer import BacktestEngineer

    r = get_redis()
    eng = BacktestEngineer(r)

    try:
        with console.status("[cyan]Analizando trades con BacktestEngineer...[/cyan]"):
            result = eng.analyze(symbol)
    except Exception as exc:
        console.print(f"[error]Error al analizar: {exc}[/error]")
        return

    if result is None:
        console.print(
            "[warn]No hay suficientes trades para analizar. "
            "Mínimo 10 trades cerrados requeridos.[/warn]"
        )
        return

    verdict = result.get("verdict", "?")
    color = {"APROBADO": "success", "PRECAUCIÓN": "warn", "RECHAZADO": "error"}.get(verdict, "muted")
    console.print(
        f"\n[{color}]Veredicto: {verdict}[/{color}] — "
        f"{result.get('total_trades', 0)} trades analizados"
    )

    summary = result.get("analytics_summary", {})
    if summary:
        console.print(
            f"  Sharpe: {summary.get('sharpe','?')} | "
            f"Max DD: {summary.get('max_dd','?')} | "
            f"Win Rate: {summary.get('win_rate','?')}"
        )

    console.print("\n[brand]Insights:[/brand]")
    for i, insight in enumerate(result.get("insights", []), 1):
        console.print(f"  {i}. {insight}")

    console.print("\n[brand]Recomendaciones:[/brand]")
    for rec in result.get("recommendations", []):
        action = rec.get("action", "?")
        target = rec.get("target", "?")
        reason = rec.get("reason", "")
        frm = rec.get("from")
        to = rec.get("to")
        change = f" ({frm} → {to})" if frm is not None and to is not None else ""
        console.print(f"  • [{color}]{action}[/{color}] {target}{change} — {reason}")

    params = result.get("suggested_params", {})
    if params:
        console.print(
            "\n[brand]Parámetros sugeridos "
            "(aplica con `btquantr config set <key> <value>`):[/brand]"
        )
        for k, v in params.items():
            console.print(f"  {k}: {v}")


@backtest_engineer.command("status")
@click.option("--symbol", default="ALL", show_default=True,
              help="Símbolo del report a mostrar.")
def be_status(symbol: str):
    """Muestra el último report del BacktestEngineer guardado en Redis."""
    print_banner()
    from btquantr.redis_client import is_redis_available
    if not is_redis_available():
        console.print("[error]Redis no disponible.[/error]")
        return
    from btquantr.redis_client import get_redis
    import json as _json, time as _time

    r = get_redis()
    raw = r.get(f"backtest_engineer:report:{symbol}")
    if not raw:
        console.print(
            f"[warn]No hay report guardado para {symbol}. "
            f"Ejecuta `btquantr backtest-engineer analyze --symbol {symbol}` primero.[/warn]"
        )
        return

    report = _json.loads(raw)
    verdict = report.get("verdict", "?")
    color = {"APROBADO": "success", "PRECAUCIÓN": "warn", "RECHAZADO": "error"}.get(verdict, "muted")
    ts = report.get("analyzed_at", 0)
    ts_str = _time.strftime("%Y-%m-%d %H:%M", _time.localtime(ts)) if ts else "?"

    console.print(
        f"\n[{color}]Veredicto: {verdict}[/{color}] — "
        f"{report.get('total_trades', 0)} trades | {ts_str}"
    )
    summary = report.get("analytics_summary", {})
    if summary:
        console.print(
            f"  Sharpe: {summary.get('sharpe','?')} | "
            f"Max DD: {summary.get('max_dd','?')} | "
            f"Win Rate: {summary.get('win_rate','?')}"
        )

    console.print("\n[brand]Insights:[/brand]")
    for i, insight in enumerate(report.get("insights", []), 1):
        console.print(f"  {i}. {insight}")

    console.print("\n[brand]Recomendaciones:[/brand]")
    for rec in report.get("recommendations", []):
        action = rec.get("action", "?")
        target = rec.get("target", "?")
        reason = rec.get("reason", "")
        console.print(f"  • [{color}]{action}[/{color}] {target} — {reason}")

    params = report.get("suggested_params", {})
    if params:
        console.print(
            "\n[brand]Parámetros sugeridos "
            "(aplica con `btquantr config set <key> <value>`):[/brand]"
        )
        for k, v in params.items():
            console.print(f"  {k}: {v}")


@main.group("dashboard", invoke_without_command=True)
@click.pass_context
def dashboard(ctx):
    """Dashboards en tiempo real. Subcomandos: funding. Sin subcomando: abre TUI clásico."""
    if ctx.invoked_subcommand is not None:
        return
    # Comportamiento original: abrir TUI en nueva ventana
    import subprocess, os, sys
    from pathlib import Path

    bat = Path(__file__).parent / "ui" / "launch_dashboard.bat"
    redis_port = os.environ.get("REDIS_PORT", "6380")

    if sys.platform == "win32":
        subprocess.Popen(
            ["cmd", "/c", "start", "cmd", "/k", str(bat)],
            env={**os.environ, "REDIS_PORT": redis_port},
            shell=False,
        )
        console.print("[brand]Dashboard abierto en nueva ventana.[/brand]")
    else:
        python = Path(sys.executable)
        script = Path(__file__).parent / "ui" / "dashboard.py"
        for term in ("gnome-terminal", "xterm", "konsole"):
            try:
                subprocess.Popen(
                    [term, "--", str(python), str(script)],
                    env={**os.environ, "REDIS_PORT": redis_port},
                )
                console.print(f"[brand]Dashboard abierto en {term}.[/brand]")
                return
            except FileNotFoundError:
                continue
        console.print("[warn]No se encontró terminal gráfica. Ejecuta manualmente:[/warn]")
        console.print(f"  REDIS_PORT={redis_port} {python} {script}")


@dashboard.command("funding")
def dashboard_funding():
    """Dashboard Live de funding rates (crypto perps + HIP3) via WebSocket de HyperLiquid."""
    from btquantr.ui.funding_dashboard import FundingDashboard
    import asyncio
    dashboard_obj = FundingDashboard()
    asyncio.run(dashboard_obj.run())


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY — btquantr strategy <subcomando>
# ─────────────────────────────────────────────────────────────────────────────

MOONDEV_STRATEGIES = {
    "trend-capture-pro":           ("BTC-USD", "ETH-USD"),
    "selective-momentum-swing":    ("BTC-USD", "ETH-USD"),
    "divergence-volatility-enhanced": ("BTC-USD", "ETH-USD"),
}

SYMBOL_MAP = {"BTCUSDT": "BTC-USD", "ETHUSDT": "ETH-USD",
              "BTC-USD": "BTCUSDT", "ETH-USD": "ETHUSDT"}


def _btq_sym(s: str) -> str:
    """Normaliza símbolo a formato BTQ (BTCUSDT).
    Acepta tanto 'BTC-USD' (yfinance) como 'BTCUSDT' (BTQ).
    Si ya es BTQ (sin '-'), lo devuelve tal cual."""
    if "-" not in s and "/" not in s:
        return s   # Ya es formato BTQ
    return SYMBOL_MAP.get(s, s.replace("-", "").replace("/", ""))


def _yf_sym(s: str) -> str:
    """Normaliza símbolo a formato yfinance (BTC-USD).
    Acepta tanto 'BTCUSDT' (BTQ) como 'BTC-USD' (yfinance)."""
    return SYMBOL_MAP.get(s, s)


def _verdict_color(v: str) -> str:
    return {"APROBADO": "success", "PRECAUCIÓN": "warn", "RECHAZADO": "error"}.get(v, "muted")


@main.group("strategy")
def strategy_group():
    """Testing de estrategias MoonDev: backtest → HMM → analytics → reporte."""
    pass


@strategy_group.command("test")
@click.option("--name", "-n", required=True, help="Clave de estrategia (ej: trend-capture-pro)")
@click.option("--symbol", "-s", default="BTCUSDT", show_default=True,
              help="Símbolo BTQUANTR (BTCUSDT, ETHUSDT)")
@click.option("--months", "-m", default=6, type=int, show_default=True,
              help="Meses de datos históricos")
@click.option("--timeframe", "-t", default="1h", show_default=True)
def strategy_test(name: str, symbol: str, months: int, timeframe: str):
    """Backtest completo de una estrategia con HMM histórico + analytics."""
    print_banner()
    from btquantr.redis_client import is_redis_available, get_redis
    if not is_redis_available():
        console.print("[error]Redis no disponible.[/error]"); return

    r = get_redis()
    sym_btq = _btq_sym(symbol)   # BTCUSDT o BTC-USD → BTCUSDT
    sym_yf  = _yf_sym(sym_btq)  # BTCUSDT → BTC-USD

    console.print(f"[brand]strategy test[/brand] {name} | {sym_btq} | {months}m {timeframe}")
    console.print("[muted]Flujo: OHLCV → HMM histórico → backtest → adapter → analytics[/muted]\n")

    try:
        from btquantr.adapters.backtest_adapter import run_strategy_test
        out = run_strategy_test(name, sym_yf, sym_btq, months, r, timeframe)
    except Exception as e:
        console.print(f"[error]Error: {e}[/error]")
        import traceback; traceback.print_exc()
        return

    _print_strategy_report(out["report"], console)


@strategy_group.command("test-all")
@click.option("--symbol", "-s", default="BTCUSDT", show_default=True)
@click.option("--months", "-m", default=6, type=int, show_default=True)
@click.option("--timeframe", "-t", default="1h", show_default=True)
def strategy_test_all(symbol: str, months: int, timeframe: str):
    """Backtest de las 3 estrategias MoonDev sobre un símbolo."""
    print_banner()
    from btquantr.redis_client import is_redis_available, get_redis
    if not is_redis_available():
        console.print("[error]Redis no disponible.[/error]"); return

    r = get_redis()
    sym_btq = _btq_sym(symbol)   # BTCUSDT o BTC-USD → BTCUSDT
    sym_yf  = _yf_sym(sym_btq)  # BTCUSDT → BTC-USD

    console.print(f"[brand]strategy test-all[/brand] | {sym_btq} | {months}m {timeframe}\n")

    from btquantr.adapters.backtest_adapter import run_strategy_test
    results = []
    for strat_key in MOONDEV_STRATEGIES:
        console.print(f"[brand]→ {strat_key}[/brand]")
        try:
            out = run_strategy_test(strat_key, sym_yf, sym_btq, months, r, timeframe)
            results.append(out["report"])
            bt = out["backtest_result"]
            an = out["report"].get("analytics") or {}
            verdict = an.get("summary", {}).get("verdict", "—")
            console.print(
                f"  {bt['num_trades']} trades | Sharpe {bt['sharpe_ratio']:.2f} | "
                f"WR {bt['win_rate_pct']:.1f}% | [{_verdict_color(verdict)}]{verdict}[/]"
            )
        except Exception as e:
            console.print(f"  [error]{e}[/error]")

    if results:
        console.print()
        _print_compare_table(results, console)


@strategy_group.command("test-tick")
@click.option("--name", "-n", required=True, help="Nombre de la estrategia en StrategyStore")
@click.option("--symbol", "-s", default="BTCUSDT", show_default=True)
@click.option("--duration", default=30, show_default=True, type=int,
              help="Segundos de tick data a descargar desde HyperLiquid WS")
@click.option("--timeframe", "-t", default="1min", show_default=True,
              help="Timeframe para conversión OHLC (1s, 1min, 5min...)")
def strategy_test_tick(name: str, symbol: str, duration: int, timeframe: str):
    """Re-testea una estrategia ganadora usando datos OHLC 1m reales."""
    print_banner()
    from btquantr.engine.evolution_loop import fetch_ohlc_for_tick_backtest, MIN_TICK_BACKTEST_BARS
    from btquantr.engine.evolution_loop import _quick_backtest_impl, _detect_strategy_timeframe, _resample_ohlc

    store = _get_store()
    sym = _btq_sym(symbol)

    # Buscar estrategia en el registry
    registry = store.list_registry()
    matches = [e for e in registry if e.get("name", "") == name]

    if not matches:
        console.print(f"[warn]No se encontró '{name}' en el StrategyStore.[/warn]")
        console.print("[muted]Usa: btquantr engine winners -s {sym} para ver estrategias disponibles[/muted]")
        return

    entry = matches[0]
    strategy = store.get_best(entry.get("symbol", sym), entry.get("regime", "BULL"))
    if strategy is None:
        console.print(f"[warn]No se encontró estrategia '{name}' en StrategyStore.[/warn]")
        return

    console.print(f"[brand]strategy test-tick[/brand] {name} | {sym} | 1m OHLC (7 días)")

    console.print(f"[muted]Descargando 1m OHLC para {sym} (7 días)...[/muted]")
    ohlc = fetch_ohlc_for_tick_backtest(sym)

    if ohlc.empty or len(ohlc) < MIN_TICK_BACKTEST_BARS:
        console.print(f"[warn]Datos insuficientes: {len(ohlc)} barras (mínimo {MIN_TICK_BACKTEST_BARS})[/warn]")
        return

    strat_tf = _detect_strategy_timeframe(strategy)
    ohlc = _resample_ohlc(ohlc, strat_tf)
    console.print(f"[muted]Resampleando a {strat_tf}...[/muted]")

    if ohlc.empty:
        console.print(f"[warn]Datos vacíos tras resamplear a {strat_tf}[/warn]")
        return

    result = _quick_backtest_impl(strategy, ohlc)

    if result is None:
        console.print(f"[error]FAIL[/error] — backtest retornó None")
    else:
        n = result.get("n_trades", 0)
        console.print(f"[success]PASS[/success] — {n} trades en {len(ohlc)} barras {strat_tf}")


@strategy_group.command("permutation-test")
@click.option("--name", "-n", required=True, help="Nombre de la estrategia en el StrategyStore")
@click.option("--symbol", "-s", default="BTCUSDT", show_default=True)
@click.option("--n-perm", default=1000, show_default=True, type=int,
              help="Número de permutaciones aleatorias")
def strategy_permutation_test(name: str, symbol: str, n_perm: int):
    """Permutation test: ¿tiene edge estadístico real o es suerte?

    p-value < 0.05 → edge estadístico real (no azar).
    """
    print_banner()
    from btquantr.analytics.permutation_test import PermutationTest

    store = _get_store()
    sym = _btq_sym(symbol)

    registry = store.list_registry()
    matches = [e for e in registry if e.get("name", "") == name]
    if not matches:
        console.print(f"[warn]No se encontró '{name}' en el StrategyStore.[/warn]")
        return

    entry = matches[0]
    strategy = store.get_best(entry.get("symbol", sym), entry.get("regime", "BULL"))
    if strategy is None:
        console.print(f"[warn]No se encontró estrategia '{name}'.[/warn]")
        return

    returns = strategy.get("_returns", [])
    if not returns or len(returns) < 20:
        console.print(
            f"[warn]Retornos insuficientes para '{name}': {len(returns)} trades "
            f"(mínimo 20).[/warn]"
        )
        return

    console.print(f"[brand]strategy permutation-test[/brand] {name} | {sym} | N={n_perm}")
    console.print(f"[muted]Corriendo {n_perm} permutaciones...[/muted]")

    result = PermutationTest(n_permutations=n_perm, seed=42).run(returns)

    p_value     = result["p_value"]
    has_edge    = result["has_edge"]
    real_sharpe = result["real_sharpe"]

    console.print(f"  Sharpe real:    [cyan]{real_sharpe:.4f}[/cyan]")
    console.print(f"  p-value:        [cyan]{p_value:.4f}[/cyan]")

    if has_edge:
        console.print(f"  [success]✓ EDGE ESTADÍSTICO REAL[/success] — p={p_value:.4f} < 0.05")
    else:
        console.print(f"  [error]✗ SIN EDGE — posible azar[/error] — p={p_value:.4f} >= 0.05")


@strategy_group.command("noise-test")
@click.option("--name", "-n", required=True, help="Nombre de la estrategia en el StrategyStore")
@click.option("--symbol", "-s", default="BTCUSDT", show_default=True)
@click.option("--n-series", default=1000, show_default=True, type=int,
              help="Número de series gaussianas sintéticas")
def strategy_noise_test(name: str, symbol: str, n_series: int):
    """Noise Test: ¿supera la estrategia a ruido gaussiano puro?

    Genera N series sintéticas con media=0 y misma volatilidad que los trades.
    p-value < 0.05 → edge estadístico real sobre ruido puro.
    """
    print_banner()
    from btquantr.analytics.noise_test import NoiseTest

    store = _get_store()
    sym = _btq_sym(symbol)

    registry = store.list_registry()
    matches = [e for e in registry if e.get("name", "") == name]
    if not matches:
        console.print(f"[warn]No se encontró '{name}' en el StrategyStore.[/warn]")
        return

    entry = matches[0]
    strategy = store.get_best(entry.get("symbol", sym), entry.get("regime", "BULL"))
    if strategy is None:
        console.print(f"[warn]No se encontró estrategia '{name}'.[/warn]")
        return

    returns = strategy.get("_returns", [])
    if not returns or len(returns) < 10:
        console.print(
            f"[warn]Retornos insuficientes para '{name}': {len(returns)} trades "
            f"(mínimo 10).[/warn]"
        )
        return

    console.print(f"[brand]strategy noise-test[/brand] {name} | {sym} | N={n_series}")
    console.print(f"[muted]Generando {n_series} series gaussianas sintéticas...[/muted]")

    result = NoiseTest(n_series=n_series, seed=42).run(returns)

    p_value     = result["p_value"]
    has_edge    = result["has_edge"]
    real_sharpe = result["real_sharpe"]

    console.print(f"  Sharpe real:    [cyan]{real_sharpe:.4f}[/cyan]")
    console.print(f"  p-value:        [cyan]{p_value:.4f}[/cyan]")
    console.print(f"  N series:       [cyan]{n_series}[/cyan]")

    if has_edge:
        console.print(f"  [success]✓ EDGE vs RUIDO PURO[/success] — p={p_value:.4f} < 0.05")
    else:
        console.print(f"  [error]✗ SIN EDGE — similar a azar gaussiano[/error] — p={p_value:.4f}")


@strategy_group.command("mc-variance")
@click.option("--name", "-n", required=True, help="Nombre de la estrategia en el StrategyStore")
@click.option("--symbol", "-s", default="BTCUSDT", show_default=True)
@click.option("--n-sims", default=1000, show_default=True, type=int,
              help="Número de resampleos bootstrap")
def strategy_mc_variance(name: str, symbol: str, n_sims: int):
    """Monte Carlo Variance Test: IC 95% de Sharpe y max drawdown via bootstrap.

    Resamplea los trades 1000 veces con reemplazo y calcula el intervalo de
    confianza al 95% del Sharpe y del max drawdown.
    """
    print_banner()
    from btquantr.analytics.montecarlo import MonteCarloVarianceTest

    store = _get_store()
    sym = _btq_sym(symbol)

    registry = store.list_registry()
    matches = [e for e in registry if e.get("name", "") == name]
    if not matches:
        console.print(f"[warn]No se encontró '{name}' en el StrategyStore.[/warn]")
        return

    entry = matches[0]
    strategy = store.get_best(entry.get("symbol", sym), entry.get("regime", "BULL"))
    if strategy is None:
        console.print(f"[warn]No se encontró estrategia '{name}'.[/warn]")
        return

    returns = strategy.get("_returns", [])
    if not returns or len(returns) < 10:
        console.print(
            f"[warn]Retornos insuficientes para '{name}': {len(returns)} trades "
            f"(mínimo 10).[/warn]"
        )
        return

    console.print(f"[brand]strategy mc-variance[/brand] {name} | {sym} | N={n_sims}")
    console.print(f"[muted]Resampleando {n_sims} veces...[/muted]")

    result = MonteCarloVarianceTest(n_sims=n_sims, seed=42).run(returns)

    s_lo  = result["sharpe_ci_low"]
    s_hi  = result["sharpe_ci_high"]
    s_med = result["sharpe_median"]
    d_lo  = result["drawdown_ci_low"]
    d_hi  = result["drawdown_ci_high"]
    d_med = result["drawdown_median"]

    console.print(f"\n  [bold]Sharpe — IC 95%[/bold]")
    console.print(f"    Mediana:  [cyan]{s_med:.4f}[/cyan]")
    console.print(f"    IC 95%:   [{s_lo:.4f}, {s_hi:.4f}]")

    console.print(f"\n  [bold]Max Drawdown — IC 95%[/bold]")
    console.print(f"    Mediana:  [cyan]{d_med:.2%}[/cyan]")
    console.print(f"    IC 95%:   [{d_lo:.2%}, {d_hi:.2%}]")

    if s_lo > 0:
        console.print(f"\n  [success]✓ Sharpe positivo en todo el IC 95%[/success]")
    elif s_hi > 0:
        console.print(f"\n  [warn]⚠ IC 95% cruza cero — incertidumbre alta[/warn]")
    else:
        console.print(f"\n  [error]✗ Sharpe negativo en todo el IC 95%[/error]")


@strategy_group.command("funding-arb")
@click.option("--symbol", "-s", default="BTCUSDT", show_default=True,
              help="Símbolo del perpetuo (ej. BTCUSDT, ETHUSDT)")
@click.option("--threshold", default=50.0, show_default=True, type=float,
              help="Threshold % annualized para activar BUY/SELL")
@click.option("--extreme", default=100.0, show_default=True, type=float,
              help="Threshold % annualized para señal contrarian extrema")
def strategy_funding_arb(symbol: str, threshold: float, extreme: float):
    """Señal de Funding Rate Arbitrage en tiempo real.

    Consulta el funding rate actual de HyperLiquid y genera señal:

    \b
    funding > threshold  → SELL (longs pagando, SHORT perp)
    funding < -threshold → BUY  (shorts pagando, LONG perp)
    |funding| > extreme  → señal contraria (reversión esperada)
    """
    print_banner()
    from btquantr.engine.templates.funding_arb import FundingSignalGenerator
    console.print(
        f"[brand]strategy funding-arb[/brand] {symbol} | "
        f"threshold={threshold}% | extreme={extreme}%"
    )
    gen = FundingSignalGenerator(
        threshold_pct=threshold,
        extreme_threshold_pct=extreme,
    )
    signal = gen.get_signal(symbol)

    action   = signal["action"]
    funding  = signal["funding_annualized"]
    reason   = signal["reason"]

    action_style = {
        "BUY":  "[success]",
        "SELL": "[error]",
        "HOLD": "[muted]",
    }.get(action, "[muted]")

    console.print(f"  Funding annualized:  [cyan]{funding:.2f}%[/cyan]")
    console.print(f"  Acción:              {action_style}{action}[/{action_style[1:]}")
    console.print(f"  Razón:               [muted]{reason}[/muted]")


@strategy_group.command("report")
@click.option("--name", "-n", required=True)
@click.option("--symbol", "-s", default="BTCUSDT", show_default=True)
def strategy_report(name: str, symbol: str):
    """Muestra el último reporte guardado de una estrategia."""
    print_banner()
    from btquantr.redis_client import is_redis_available, get_redis
    if not is_redis_available():
        console.print("[error]Redis no disponible.[/error]"); return

    r = get_redis()
    sym_btq = _btq_sym(symbol)
    raw = r.get(f"backtest:report:{name}:{sym_btq}")
    if not raw:
        console.print(f"[warn]Sin reporte para {name}/{sym_btq}. Ejecuta primero: btquantr strategy test -n {name} -s {sym_btq}[/warn]")
        return

    import json as _json
    report = _json.loads(raw)
    _print_strategy_report(report, console)


@strategy_group.command("compare")
@click.option("--symbol", "-s", default="BTCUSDT", show_default=True)
def strategy_compare(symbol: str):
    """Tabla comparativa de todas las estrategias testeadas."""
    print_banner()
    from btquantr.redis_client import is_redis_available, get_redis
    if not is_redis_available():
        console.print("[error]Redis no disponible.[/error]"); return

    r = get_redis()
    sym_btq = _btq_sym(symbol)
    import json as _json

    reports = []
    for key in r.keys(f"backtest:report:*:{sym_btq}"):
        try:
            reports.append(_json.loads(r.get(key)))
        except Exception:
            pass

    if not reports:
        console.print(f"[warn]Sin reportes para {sym_btq}. Ejecuta btquantr strategy test-all -s {sym_btq}[/warn]")
        return

    _print_compare_table(reports, console)


@strategy_group.command("regime-matrix")
@click.option("--symbol", "-s", default="BTCUSDT", show_default=True)
def strategy_regime_matrix(symbol: str):
    """Regime matrix: qué estrategia funciona mejor en cada régimen HMM."""
    print_banner()
    from btquantr.redis_client import is_redis_available, get_redis
    if not is_redis_available():
        console.print("[error]Redis no disponible.[/error]"); return

    r = get_redis()
    sym_btq = _btq_sym(symbol)
    import json as _json

    raw = r.get(f"backtest:regime_matrix:{sym_btq}")
    if not raw:
        console.print(f"[warn]Sin regime matrix para {sym_btq}. Ejecuta btquantr strategy test-all -s {sym_btq}[/warn]")
        return

    matrix = _json.loads(raw)
    regimes = sorted({r for data in matrix.values() for r in data.keys()})

    from rich.table import Table as _Table
    from rich import box as _box

    tbl = _Table(box=_box.ROUNDED, title=f"[bold]Regime Matrix — {sym_btq}[/bold]",
                 show_header=True, header_style="bold dim")
    tbl.add_column("Estrategia", width=32)
    regime_colors = {"BULL": "green", "SIDEWAYS": "blue", "BEAR": "red", "BACKTEST": "dim", "UNKNOWN": "dim"}
    for reg in regimes:
        tbl.add_column(reg, justify="right", width=10,
                       style=regime_colors.get(reg, "white"))

    # Encontrar mejor estrategia por régimen
    best: dict[str, tuple[str, float]] = {}
    for strat, data in matrix.items():
        for reg, sharpe in data.items():
            if reg not in best or sharpe > best[reg][1]:
                best[reg] = (strat, sharpe)

    for strat, data in sorted(matrix.items()):
        cells = []
        for reg in regimes:
            sh = data.get(reg)
            if sh is None:
                cells.append("—")
            else:
                is_best = best.get(reg, (None,))[0] == strat
                color = "green" if sh > 1.0 else ("yellow" if sh > 0 else "red")
                star = "★" if is_best else " "
                cells.append(f"[{color}]{sh:.2f}{star}[/]")
        tbl.add_row(strat, *cells)

    console.print(tbl)
    console.print()
    console.print("[dim]★ = mejor estrategia para ese régimen[/dim]")
    console.print("[dim]Verde = Sharpe > 1.0 · Amarillo = 0-1.0 · Rojo = negativo[/dim]")


# ── Helpers de display ────────────────────────────────────────────────────────

def _print_strategy_report(report: dict, con) -> None:
    import json as _json
    bt = report.get("backtest", {})
    an = report.get("analytics") or {}
    summary = an.get("summary", {})
    mc = an.get("montecarlo", {})
    verdict = summary.get("verdict", "—")
    vc = _verdict_color(verdict)

    con.print(f"\n[bold]{'─'*60}[/bold]")
    con.print(
        f"[brand]{report.get('strategy','?')}[/brand] | "
        f"{report.get('symbol','?')} | "
        f"{report.get('months','?')}m {report.get('timeframe','?')}"
    )
    con.print(f"[bold]Veredicto: [{vc}]{verdict}[/][/bold]\n")

    from rich.table import Table as _Table
    from rich import box as _box
    tbl = _Table.grid(padding=(0, 2))
    tbl.add_column(style="dim", width=20)
    tbl.add_column()

    tbl.add_row("Trades",       str(bt.get("num_trades", "?")))
    tbl.add_row("Sharpe",       f"{bt.get('sharpe_ratio', 0):.3f}")
    tbl.add_row("Win Rate",     f"{bt.get('win_rate_pct', 0):.1f}%")
    tbl.add_row("Max DD",       f"{bt.get('max_drawdown_pct', 0):.1f}%")
    tbl.add_row("Return",       f"{bt.get('return_pct', 0):+.1f}%")
    tbl.add_row("B&H Return",   f"{bt.get('buy_hold_pct', 0):+.1f}%")
    if summary:
        tbl.add_row("MC VaR 95%",  str(round(mc.get("var_95", 0), 4)))
        tbl.add_row("P(Ruin)",     str(round(mc.get("prob_ruin", 0), 3)))
    con.print(tbl)
    con.print()


def _print_compare_table(reports: list[dict], con) -> None:
    from rich.table import Table as _Table
    from rich import box as _box

    tbl = _Table(box=_box.ROUNDED, show_header=True, header_style="bold dim",
                 title="[bold]Comparativa de Estrategias[/bold]")
    tbl.add_column("Estrategia",   width=32)
    tbl.add_column("Trades",       width=7,  justify="right")
    tbl.add_column("Sharpe",       width=8,  justify="right")
    tbl.add_column("Win Rate",     width=9,  justify="right")
    tbl.add_column("Max DD",       width=9,  justify="right")
    tbl.add_column("Return",       width=9,  justify="right")
    tbl.add_column("VaR 95%",      width=9,  justify="right")
    tbl.add_column("Veredicto",    width=12, justify="center")

    for r in sorted(reports, key=lambda x: x.get("backtest", {}).get("sharpe_ratio", 0), reverse=True):
        bt = r.get("backtest", {})
        an = r.get("analytics") or {}
        summary = an.get("summary", {})
        mc = an.get("montecarlo", {})
        verdict = summary.get("verdict", "—")
        vc = _verdict_color(verdict)

        sh = bt.get("sharpe_ratio", 0)
        wr = bt.get("win_rate_pct", 0)
        dd = bt.get("max_drawdown_pct", 0)
        ret = bt.get("return_pct", 0)
        var95 = mc.get("var_95", None)

        sh_c  = "success" if sh >= 1.0 else ("warn" if sh >= 0.5 else "error")
        wr_c  = "success" if wr >= 50 else ("warn" if wr >= 40 else "error")
        dd_c  = "success" if dd >= -10 else ("warn" if dd >= -20 else "error")
        ret_c = "success" if ret >= 0 else "error"

        tbl.add_row(
            r.get("strategy", "?"),
            str(bt.get("num_trades", 0)),
            f"[{sh_c}]{sh:.2f}[/]",
            f"[{wr_c}]{wr:.1f}%[/]",
            f"[{dd_c}]{dd:.1f}%[/]",
            f"[{ret_c}]{ret:+.1f}%[/]",
            f"{var95:.4f}" if var95 is not None else "—",
            f"[{vc}]{verdict}[/]",
        )

    con.print(tbl)


def _get_store():
    """Retorna la implementación de StrategyStore según DEFAULT_CONFIG.storage_backend."""
    return get_strategy_store()


# ── strategy list ─────────────────────────────────────────────────────────────

@strategy_group.command("list")
@click.option("--venue", default=None,
              type=click.Choice(["hyperliquid", "mt5", "universal"]),
              help="Filtrar por venue destino")
@click.option("--symbol", default=None, help="Filtrar por símbolo")
def strategy_list(venue: str | None, symbol: str | None):
    """Lista estrategias del StrategyStore con filtro opcional por venue."""
    store = _get_store()
    if venue:
        registry = store.list_registry_by_venue(venue)
    else:
        registry = store.list_registry()

    if symbol:
        registry = [e for e in registry if e.get("symbol") == symbol]

    registry = sorted(registry, key=lambda e: e.get("fitness", 0.0), reverse=True)

    if not registry:
        console.print("[muted]No hay estrategias que coincidan con los filtros.[/muted]")
        return

    venue_title = f" [{venue}]" if venue else ""
    tbl = Table(title=f"[brand]Estrategias{venue_title}[/brand]")
    tbl.add_column("Nombre", style="label", width=36)
    tbl.add_column("Símbolo", width=10)
    tbl.add_column("Régimen", width=10)
    tbl.add_column("Venue", width=12)
    tbl.add_column("Fitness", justify="right", width=10)

    for e in registry:
        fit = e.get("fitness", 0.0)
        fit_c = "success" if fit >= 1.0 else ("warn" if fit >= 0.5 else "error")
        v = e.get("venue", "hyperliquid")
        venue_c = "brand" if v == "hyperliquid" else ("info" if v == "mt5" else "muted")
        tbl.add_row(
            e.get("name", "—"),
            e.get("symbol", "—"),
            e.get("regime", "—"),
            f"[{venue_c}]{v}[/]",
            f"[{fit_c}]{fit:.4f}[/]",
        )
    console.print(tbl)


# ─────────────────────────────────────────────────────────────────────────────
# Grupo engine
# ─────────────────────────────────────────────────────────────────────────────

@main.group("engine")
def engine_group():
    """Motor evolutivo autónomo: genera, evalúa y evoluciona estrategias."""
    pass


# ── engine seeds ──────────────────────────────────────────────────────────────

@engine_group.command("seeds")
@click.option("--origin", default=None,
              type=click.Choice(["moondev", "template", "scraped"]),
              help="Filtrar por origen")
def engine_seeds(origin: str | None):
    """Lista las estrategias semilla disponibles (SeedLibrary)."""
    seeds = SeedLibrary().load_all_seeds()
    if origin:
        seeds = [s for s in seeds if s.get("origin") == origin]

    if not seeds:
        console.print("[muted]No se encontraron seeds.[/muted]")
        return

    tbl = Table(title=f"[brand]Seeds[/brand] ({len(seeds)} total)")
    tbl.add_column("Nombre", style="label", width=36)
    tbl.add_column("Origen", width=12)
    tbl.add_column("Indicadores", width=30)
    tbl.add_column("Params", justify="right", width=8)

    for s in seeds:
        inds = ", ".join(s.get("indicators", [])[:4]) or "—"
        tbl.add_row(
            s["name"],
            s.get("origin", "—"),
            inds,
            str(len(s.get("params", {}))),
        )
    console.print(tbl)
    console.print(f"[muted]Total: {len(seeds)} seeds[/muted]")


# ── engine generate ───────────────────────────────────────────────────────────

@engine_group.command("generate")
@click.option("--n", default=20, show_default=True, type=int,
              help="Número de estrategias a generar")
@click.option("--seed", default=None, type=int, help="Semilla aleatoria (reproducibilidad)")
def engine_generate(n: int, seed: int | None):
    """Genera n estrategias combinando IndicatorLibrary (StrategyGenerator)."""
    lib_seeds = SeedLibrary().load_all_seeds()
    gen = StrategyGenerator(random_state=seed)
    strategies = gen.generate(n=n, seeds=lib_seeds)

    console.print(f"[brand]engine generate[/brand] → {len(strategies)} estrategias generadas\n")

    tbl = Table(title=f"[brand]Estrategias Generadas[/brand] ({len(strategies)})")
    tbl.add_column("Nombre", style="label", width=36)
    tbl.add_column("Template", width=22)
    tbl.add_column("Indicadores", width=30)
    tbl.add_column("Params", justify="right", width=8)

    for s in strategies[:50]:
        inds = ", ".join(s.get("indicators", [])[:3]) or "—"
        tbl.add_row(
            s["name"],
            s.get("template", "—"),
            inds,
            str(len(s.get("params", {}))),
        )

    console.print(tbl)
    if len(strategies) > 50:
        console.print(f"[muted]... y {len(strategies) - 50} más[/muted]")
    console.print(f"[muted]Total: {len(strategies)} generadas[/muted]")


# ── engine scrape ─────────────────────────────────────────────────────────────

@engine_group.command("scrape")
@click.option("--source", default="github",
              type=click.Choice(["github", "github-extended", "arxiv", "x-monitor"]),
              help="Fuente: github | github-extended | arxiv | x-monitor")
@click.option("--no-cache", "no_cache", is_flag=True, default=False,
              help="Ignorar caché Redis y re-descargar")
@click.option("--token", default=None, envvar="GITHUB_TOKEN",
              help="GitHub token (fuente github) o X Bearer Token (fuente x-monitor)")
def engine_scrape(source: str, no_cache: bool, token: str | None):
    """Descarga estrategias de repos GitHub, arXiv o X (Twitter)."""
    from btquantr.redis_client import is_redis_available, get_redis
    r = get_redis() if is_redis_available() else None

    if source == "github-extended":
        scraper = GitHubScraper(r=r, token=token)
        items = scraper.run_extended(use_cache=not no_cache)
        _show_seeds_table(items, title="Seeds GitHub Extended")

    elif source == "github":
        scraper = GitHubScraper(r=r, token=token)
        items = scraper.run(use_cache=not no_cache)
        _show_seeds_table(items, title="Seeds GitHub")

    elif source == "arxiv":
        from btquantr.engine.scrapers.arxiv_scraper import ArXivScraper
        scraper = ArXivScraper(r=r)
        papers = scraper.run(use_cache=not no_cache)
        console.print(f"[brand]engine scrape arxiv[/brand] → {len(papers)} papers\n")
        if not papers:
            console.print("[muted]No se encontraron papers.[/muted]")
            return
        tbl = Table(title=f"[brand]arXiv Papers[/brand] ({len(papers)})")
        tbl.add_column("ID", style="label", width=12)
        tbl.add_column("Título", width=50)
        tbl.add_column("GitHub URLs", width=20)
        tbl.add_column("Seeds", width=6)
        for p in papers[:30]:
            gh = str(len(p.get("github_urls", [])))
            seeds_n = str(len(p.get("seeds", [])))
            tbl.add_row(
                p.get("arxiv_id", "—"),
                p.get("title", "—")[:48],
                gh,
                seeds_n,
            )
        console.print(tbl)
        if len(papers) > 30:
            console.print(f"[muted]... y {len(papers) - 30} más[/muted]")

    elif source == "x-monitor":
        from btquantr.engine.scrapers.x_monitor import XMonitor
        bearer = token or None
        monitor = XMonitor(bearer_token=bearer, r=r)
        if not monitor.is_configured:
            console.print(
                "[warn]X_BEARER_TOKEN no configurado.[/warn]\n"
                "Obtén un token en https://developer.twitter.com/ y añade "
                "X_BEARER_TOKEN=<token> a tu .env"
            )
            return
        tweets = monitor.run(use_cache=not no_cache)
        relevant = [t for t in tweets if t["has_code"] or t["github_urls"]]
        console.print(
            f"[brand]engine scrape x-monitor[/brand] → "
            f"{len(tweets)} tweets ({len(relevant)} con código/GitHub)\n"
        )
        if not tweets:
            console.print("[muted]No se encontraron tweets.[/muted]")
            return
        tbl = Table(title=f"[brand]X #algotrading[/brand] ({len(tweets)})")
        tbl.add_column("ID", style="label", width=20)
        tbl.add_column("Texto", width=60)
        tbl.add_column("Código", width=6)
        tbl.add_column("GitHub", width=6)
        for t in tweets[:30]:
            tbl.add_row(
                t.get("id", "—"),
                t.get("text", "")[:58],
                "✓" if t["has_code"] else "—",
                str(len(t.get("github_urls", []))),
            )
        console.print(tbl)


def _show_seeds_table(seeds: list, title: str = "Seeds") -> None:
    console.print(f"[brand]engine scrape[/brand] → {len(seeds)} seeds obtenidas\n")
    if not seeds:
        console.print("[muted]No se encontraron estrategias válidas.[/muted]")
        return
    tbl = Table(title=f"[brand]{title}[/brand] ({len(seeds)})")
    tbl.add_column("Nombre", style="label", width=36)
    tbl.add_column("Origen", width=12)
    tbl.add_column("Archivo", width=40)
    for s in seeds[:30]:
        tbl.add_row(s.get("name", "—"), s.get("origin", "scraped"), s.get("source_file", "—"))
    console.print(tbl)
    if len(seeds) > 30:
        console.print(f"[muted]... y {len(seeds) - 30} más[/muted]")


# ── engine strategies ────────────────────────────────────────────────────────

@engine_group.command("strategies")
@click.option("--symbol", default=None,
              help="Filtrar por símbolo (ej: ETHUSDT, SPY). Sin filtro → todos.")
@click.option("--detail", is_flag=True, default=False,
              help="Mostrar código fuente de cada estrategia.")
def engine_strategies(symbol: str | None, detail: bool):
    """Dashboard Rich: todas las estrategias del StrategyStore."""
    from btquantr.ui.strategy_viewer import StrategyViewer
    print_header("Strategy Store — Dashboard")
    StrategyViewer().show(symbol_filter=symbol, show_code=detail)


# ── engine winners ────────────────────────────────────────────────────────────

@engine_group.command("winners")
@click.option("--symbol", default=None, help="Filtrar por símbolo")
@click.option("--venue", default=None,
              type=click.Choice(["hyperliquid", "mt5", "universal"]),
              help="Filtrar por venue")
def engine_winners(symbol: str | None, venue: str | None):
    """Muestra las mejores estrategias registradas en StrategyStore."""
    store = _get_store()
    if venue:
        registry = store.list_registry_by_venue(venue)
    else:
        registry = store.list_registry()

    if symbol:
        registry = [e for e in registry if e.get("symbol") == symbol]

    registry = sorted(registry, key=lambda e: e.get("fitness", 0.0), reverse=True)

    if not registry:
        console.print("[muted]No hay estrategias registradas.[/muted]")
        return

    tbl = Table(title="[brand]Winners — StrategyStore[/brand]")
    tbl.add_column("Nombre", style="label", width=36)
    tbl.add_column("Símbolo", width=10)
    tbl.add_column("Régimen", width=10)
    tbl.add_column("Fitness", justify="right", width=10)

    for e in registry:
        fit = e.get("fitness", 0.0)
        fit_c = "success" if fit >= 1.0 else ("warn" if fit >= 0.5 else "error")
        tbl.add_row(
            e.get("name", "—"),
            e.get("symbol", "—"),
            e.get("regime", "—"),
            f"[{fit_c}]{fit:.4f}[/]",
        )

    console.print(tbl)


# ── engine fitness ────────────────────────────────────────────────────────────

@engine_group.command("fitness")
@click.option("--symbol", default="BTCUSDT", show_default=True)
@click.option("--regime", "regime", default="BULL",
              type=click.Choice(["BULL", "BEAR", "SIDEWAYS"]), show_default=True)
def engine_fitness(symbol: str, regime: str):
    """Muestra el fitness de la mejor estrategia para symbol × régimen."""
    store = _get_store()
    strategy = store.get_best(symbol, regime)

    if strategy is None:
        console.print(f"[muted]No hay estrategia registrada para {symbol} × {regime}.[/muted]")
        return

    fit   = strategy.get("fitness", 0.0)
    name  = strategy.get("name", "—")
    inds  = ", ".join(strategy.get("indicators", [])[:6]) or "—"
    fit_c = "success" if fit >= 1.0 else ("warn" if fit >= 0.5 else "error")

    p = Panel(
        f"[label]Nombre:[/label]     {name}\n"
        f"[label]Fitness:[/label]    [{fit_c}]{fit:.4f}[/]\n"
        f"[label]Indicadores:[/label] {inds}\n"
        f"[label]Template:[/label]   {strategy.get('template', '—')}\n"
        f"[label]Origen:[/label]     {strategy.get('origin', '—')}",
        title=f"[brand]Fitness — {symbol} × {regime}[/brand]",
        border_style="brand",
    )
    console.print(p)


# ── engine mutate ─────────────────────────────────────────────────────────────

@engine_group.command("mutate")
@click.option("--symbol", default="BTCUSDT", show_default=True)
@click.option("--regime", "regime", default="BULL",
              type=click.Choice(["BULL", "BEAR", "SIDEWAYS"]), show_default=True)
@click.option("--n-offspring", default=20, show_default=True, type=int,
              help="Número de hijos a generar")
def engine_mutate(symbol: str, regime: str, n_offspring: int):
    """Evoluciona las mejores estrategias de StrategyStore con GeneticMutator."""
    store = _get_store()
    registry = store.list_registry()

    top_entries = [e for e in registry if e.get("symbol") == symbol]
    top_strategies = []
    for e in top_entries:
        s = store.get_best(e.get("symbol", symbol), e.get("regime", regime))
        if s and s not in top_strategies:
            top_strategies.append(s)

    if not top_strategies:
        best = store.get_best(symbol, regime)
        if best:
            top_strategies = [best]

    if not top_strategies:
        console.print(f"[muted]No hay estrategias en el store para {symbol}. "
                      f"Ejecuta primero: btquantr engine evolve --symbol {symbol}[/muted]")
        return

    mutator = GeneticMutator()
    offspring = mutator.evolve(top_strategies, n_offspring=n_offspring)

    console.print(
        f"[brand]engine mutate[/brand] — {symbol} × {regime}\n"
        f"  Padres: {len(top_strategies)} | Hijos generados: [success]{len(offspring)}[/success]\n"
    )

    if offspring:
        tbl = Table(title=f"[brand]Offspring[/brand] ({len(offspring)})")
        tbl.add_column("Nombre", style="label", width=40)
        tbl.add_column("Tipo mutación", width=18)
        tbl.add_column("Indicadores", width=30)

        for child in offspring[:20]:
            inds = ", ".join(child.get("indicators", [])[:3]) or "—"
            tbl.add_row(
                child.get("name", "—"),
                child.get("mutation_type", "—"),
                inds,
            )
        console.print(tbl)
        if len(offspring) > 20:
            console.print(f"[muted]... y {len(offspring) - 20} más[/muted]")


# ── engine evolve ─────────────────────────────────────────────────────────────

@engine_group.command("evolve")
@click.option("--symbol",      default="BTCUSDT", show_default=True,
              help="Símbolo único (ignorado si se usa --symbols)")
@click.option("--symbols",     default=None,
              help="Múltiples símbolos separados por coma: BTCUSDT,ETHUSDT,SPY,GLD")
@click.option("--timeframe",   default="1h",  show_default=True)
@click.option("--months",      default=12,    show_default=True, type=int)
@click.option("--generations", default=3,     show_default=True, type=int)
@click.option("--population",  default=50,    show_default=True, type=int)
@click.option("--workers",     default=1,     show_default=True, type=int,
              help="Procesos paralelos para evaluar población (1=secuencial)")
@click.option("--min-trades",  default=None,  type=int,
              help="Mínimo de trades para evaluar estrategia. "
                   "Auto: 5 para equity (no-USDT), 10 para crypto.")
def engine_evolve(
    symbol: str,
    symbols: str | None,
    timeframe: str,
    months: int,
    generations: int,
    population: int,
    workers: int,
    min_trades: int | None,
):
    """Ciclo evolutivo completo: genera → evalúa → selecciona → evoluciona → registra.

    Soporta múltiples símbolos (crypto + stocks + forex) via --symbols.
    """
    sym_list = [s.strip() for s in symbols.split(",")] if symbols else [symbol]

    all_results: dict[str, list[dict]] = {}

    for sym in sym_list:
        # Auto-detección de min_trades: equity (no USDT) → 5, crypto → 10
        effective_min_trades = min_trades
        if effective_min_trades is None:
            effective_min_trades = 5 if not sym.upper().endswith("USDT") else 10

        console.print(
            f"\n[brand]engine evolve[/brand] — [label]{sym}[/label] | {timeframe} | "
            f"{months}m | pop={population} | gens={generations} | "
            f"workers={workers} | min_trades={effective_min_trades}\n"
            "[muted]Descargando OHLCV y ejecutando ciclo evolutivo...[/muted]"
        )

        loop = EvolutionLoop()
        robust = loop.run(
            symbol=sym,
            timeframe=timeframe,
            months=months,
            n_population=population,
            n_generations=generations,
            n_workers=workers,
            min_trades=effective_min_trades,
        )
        all_results[sym] = robust

        if not robust:
            console.print(f"[warn]  {sym}: No se encontraron estrategias robustas.[/warn]")
        else:
            console.print(f"\n[success]{len(robust)} estrategias robustas — {sym}:[/success]\n")
            tbl = Table(title=f"[brand]Estrategias Robustas — {sym}[/brand]")
            tbl.add_column("Nombre", style="label", width=40)
            tbl.add_column("Fitness", justify="right", width=10)
            tbl.add_column("Régimen", width=10)
            tbl.add_column("Indicadores", width=30)

            for s in sorted(robust, key=lambda x: x.get("fitness", 0), reverse=True):
                fit = s.get("fitness", 0.0)
                fit_c = "success" if fit >= 1.0 else "warn"
                inds = ", ".join(s.get("indicators", [])[:3]) or "—"
                regime_top = s.get("regime_fitness", {}).get("best_regime", "—")
                tbl.add_row(
                    s.get("name", "—"),
                    f"[{fit_c}]{fit:.4f}[/]",
                    regime_top,
                    inds,
                )
            console.print(tbl)

    # Resumen Comparativo (solo si hay múltiples símbolos)
    if len(sym_list) > 1:
        _print_evolve_comparative(all_results)


def _print_evolve_comparative(results: dict[str, list[dict]]) -> None:
    """Imprime tabla comparativa de resultados multi-símbolo."""
    console.print("\n")
    tbl = Table(title="[brand]Resumen Comparativo — engine evolve[/brand]")
    tbl.add_column("Símbolo",        style="label",   width=14)
    tbl.add_column("Robustas",       justify="right",  width=10)
    tbl.add_column("Best Fitness",   justify="right",  width=13)
    tbl.add_column("Best Régimen",   width=12)
    tbl.add_column("Best Estrategia", width=34)

    for sym, robust in results.items():
        if not robust:
            tbl.add_row(sym, "[warn]0[/warn]", "—", "—", "[muted]ninguna[/muted]")
        else:
            best = max(robust, key=lambda s: s.get("fitness", 0))
            fit = best.get("fitness", 0.0)
            fit_c = "success" if fit >= 1.0 else "warn"
            regime = best.get("regime_fitness", {}).get("best_regime", "—")
            tbl.add_row(
                sym,
                f"[success]{len(robust)}[/success]",
                f"[{fit_c}]{fit:.4f}[/]",
                regime,
                best.get("name", "—"),
            )

    console.print(tbl)


# ─────────────────────────────────────────────────────────────────────────────
# DB — btquantr db <subcomando>
# ─────────────────────────────────────────────────────────────────────────────

@main.group("db")
def db_group():
    """Gestión de la base de datos de estrategias."""


@db_group.command("migrate-from-redis")
@click.option("--db-path", default=None, help="Ruta al fichero SQLite destino (default: data/strategies.db)")
@click.option("--dry-run", is_flag=True, default=False, help="Muestra qué se migraría sin escribir nada")
def db_migrate_from_redis(db_path: str | None, dry_run: bool):
    """Migra estrategias de Redis → SQLite.

    Lee todas las estrategias del StrategyStore Redis (o in-memory fallback)
    y las escribe en SQLiteStrategyStore. Seguro de re-ejecutar (idempotente).
    """
    from btquantr.engine.strategy_store import StrategyStore
    from btquantr.engine.strategy_store_sqlite import SQLiteStrategyStore, migrate_from_redis

    redis_store = StrategyStore()
    registry = redis_store.list_registry()

    if not registry:
        console.print("[muted]No hay estrategias en Redis (o Redis no disponible).[/muted]")
        return

    console.print(f"[label]Encontradas:[/label] {len(registry)} estrategias en Redis")

    if dry_run:
        for e in registry:
            console.print(f"  · {e.get('name','?')} | {e.get('symbol','?')} × {e.get('regime','?')} | fitness={e.get('fitness',0):.4f}")
        console.print("[warn]--dry-run: nada fue escrito.[/warn]")
        return

    sqlite_store = SQLiteStrategyStore(db_path=db_path)
    n = migrate_from_redis(redis_store, sqlite_store)
    db_loc = sqlite_store.db_path
    console.print(f"[success]Migradas {n} estrategias → {db_loc}[/success]")


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT — btquantr export <subcomando>
# ─────────────────────────────────────────────────────────────────────────────

@main.group("export")
def export_group():
    """Exporta estrategias ganadoras a formatos externos (MT5, Pine Script…)."""


@export_group.command("mt5")
@click.option("--symbol", default="BTCUSDT", show_default=True, help="Símbolo del StrategyStore")
@click.option("--regime", default="BULL", show_default=True, help="Régimen (BULL/BEAR/SIDEWAYS)")
@click.option("--output", default=None, help="Ruta del archivo .mq5 (default: exports/mt5/{symbol}_{regime}.mq5)")
def export_mt5(symbol: str, regime: str, output: str | None):
    """Genera un Expert Advisor MQL5 desde la mejor estrategia del StrategyStore."""
    from pathlib import Path as _Path
    from src.rbi.export.mql5_generator import MQL5Generator

    safe_symbol = symbol.replace(":", "_")  # "xyz:GOLD" → "xyz_GOLD" (Windows no permite ":")
    out = _Path(output) if output else _Path("exports") / "mt5" / f"{safe_symbol}_{regime}.mq5"
    try:
        code = MQL5Generator.from_store(symbol, regime)
    except ValueError as exc:
        console.print(f"[error]ERROR:[/error] {exc}")
        raise SystemExit(1)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(code, encoding="utf-8")
    console.print(
        f"[success]✓[/success] EA generado: [label]{out}[/label] "
        f"([brand]{symbol}[/brand] / {regime})"
    )


_MT5_FIXTURE_NAMES = {"bear_strategy", "bull_strategy", "sideways_strategy"}


def _is_fixture_name(name: str) -> bool:
    """Retorna True si el nombre parece un fixture de pytest (no una estrategia real)."""
    return name.lower().startswith("test") or name.lower() in _MT5_FIXTURE_NAMES


def _best_entries_by_combo(registry: list[dict]) -> list[dict]:
    """Deduplica por (symbol, regime) conservando la entrada con mayor fitness.

    También filtra entradas con nombres de fixture.
    Retorna una lista con exactamente 1 entrada por combinación symbol+regime.
    """
    best: dict[tuple, dict] = {}
    for entry in registry:
        name = entry.get("name", "")
        if _is_fixture_name(name):
            continue
        key = (entry.get("symbol", ""), entry.get("regime", ""))
        if key not in best or entry.get("fitness", 0) > best[key].get("fitness", 0):
            best[key] = entry
    return list(best.values())


@export_group.command("mt5-all")
@click.option("--output-dir", default="exports/mt5", show_default=True,
              help="Carpeta destino para los archivos .mq5")
@click.option("--tick-filter", is_flag=True, default=False,
              help="Solo exporta estrategias que también pasan tick_backtest con HyperLiquid WS")
def export_mt5_all(output_dir: str, tick_filter: bool):
    """Exporta TODAS las estrategias ganadoras del StrategyStore a .mq5.

    Deduplica por symbol+regime (1 EA por combinación, mayor fitness).
    Filtra entradas con nombres de fixture de pytest.
    """
    from pathlib import Path as _Path
    from src.rbi.export.mql5_generator import MQL5Generator

    store = _get_store()
    registry = store.list_registry()

    unique_entries = _best_entries_by_combo(registry)

    if not unique_entries:
        console.print("[warn]No hay estrategias reales registradas en el StrategyStore.[/warn]")
        console.print("[muted]Ejecuta primero: btquantr engine evolve --symbol BTCUSDT[/muted]")
        return

    out_dir = _Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Preparar tick filter si está activado
    _ohlc_cache: dict = {}
    if tick_filter:
        from btquantr.engine.evolution_loop import fetch_ohlc_for_tick_backtest as _fetch_ohlc_tick
        from btquantr.engine.evolution_loop import _quick_backtest_impl as _qbi
        from btquantr.engine.evolution_loop import MIN_TICK_BACKTEST_BARS, MIN_BARS_AFTER_RESAMPLE
        from btquantr.engine.evolution_loop import _detect_strategy_timeframe, _resample_ohlc
        from btquantr.engine.evolution_loop import _calc_tick_sharpe as _sharpe
        console.print("[muted]--tick-filter activado: pre-cargando OHLC 1m por símbolo...[/muted]")

        # Pre-cargar OHLC 1m una sola vez por símbolo único (evita timeout por descarga repetida)
        _unique_syms = {e.get("symbol", "") for e in unique_entries if e.get("symbol")}
        for _sym in sorted(_unique_syms):
            console.print(f"[muted]  ↓ {_sym}...[/muted]", end="")
            _ex_pre = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            _fut_pre = _ex_pre.submit(_fetch_ohlc_tick, _sym)
            try:
                _ohlc_cache[_sym] = _fut_pre.result(timeout=TICK_FILTER_TIMEOUT_S)
                console.print(f" {len(_ohlc_cache[_sym])} barras 1m")
            except concurrent.futures.TimeoutError:
                _ohlc_cache[_sym] = __import__("pandas").DataFrame()
                console.print(f" [warn]timeout[/warn]")
            finally:
                _ex_pre.shutdown(wait=False)

    exported = 0
    skipped = 0
    tick_rejected = 0
    tick_timeout = 0
    for entry in unique_entries:
        sym = entry.get("symbol", "")
        reg = entry.get("regime", "")
        strategy = store.get_best(sym, reg)
        if strategy is None:
            console.print(f"[warn]  ↷ Sin datos para {sym}/{reg} — saltando[/warn]")
            skipped += 1
            continue

        strategy["symbol"] = sym
        strategy["regime"] = reg
        _tick_sharpe: float = 0.0
        _few_bars: bool = False
        _status: str = ""

        # Tick filter: usar cache pre-cargado, resamplear al timeframe de la estrategia
        if tick_filter:
            strat_name_tf = strategy.get("name", "?")

            def _run_tick_filter(sym=sym, strategy=strategy):
                # Usar OHLC del cache (ya descargado) — sin I/O bloqueante
                tick_ohlc = _ohlc_cache.get(sym, __import__("pandas").DataFrame())
                if tick_ohlc.empty or len(tick_ohlc) < MIN_TICK_BACKTEST_BARS:
                    return "insufficient", len(tick_ohlc)
                # Resamplear al timeframe de la estrategia (1m → 1h, 4h, etc.)
                strat_tf = _detect_strategy_timeframe(strategy)
                tick_ohlc = _resample_ohlc(tick_ohlc, strat_tf)
                if tick_ohlc.empty:
                    return "insufficient", 0
                # < MIN_BARS_AFTER_RESAMPLE barras post-resample → pasar con advertencia
                few_bars = len(tick_ohlc) < MIN_BARS_AFTER_RESAMPLE
                result = _qbi(strategy, tick_ohlc)
                if result is None:
                    return "fail", None
                sharpe = _sharpe(result.get("returns", []))
                return "sharpe", (sharpe, few_bars)

            # Timeout solo para el backtest (la descarga ya fue pre-cargada)
            _ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            _fut = _ex.submit(_run_tick_filter)
            try:
                _status, _payload = _fut.result(timeout=TICK_FILTER_TIMEOUT_S)
                _ex.shutdown(wait=False)
            except concurrent.futures.TimeoutError:
                _ex.shutdown(wait=False)
                console.print(
                    f"[warn]  ⏱ tick-filter timeout ({TICK_FILTER_TIMEOUT_S}s): "
                    f"{strat_name_tf} {sym}/{reg} — saltando[/warn]"
                )
                tick_timeout += 1
                continue

            if _status == "insufficient":
                console.print(
                    f"[warn]  ✗ tick-filter: {strat_name_tf} {sym}/{reg} "
                    f"— datos insuficientes ({_payload} barras)[/warn]"
                )
                tick_rejected += 1
                continue
            if _status == "fail":
                console.print(
                    f"[warn]  ✗ {strat_name_tf} {sym}/{reg} "
                    f"tick_sharpe=N/A (backtest sin trades)[/warn]"
                )
                tick_rejected += 1
                continue
            # _status == "sharpe": _payload = (sharpe_float, few_bars_bool)
            _tick_sharpe: float
            _few_bars: bool
            if isinstance(_payload, tuple):
                _tick_sharpe, _few_bars = _payload
            else:
                _tick_sharpe = _payload if _payload is not None else 0.0
                _few_bars = False
            if _tick_sharpe <= -1.0:
                console.print(
                    f"[warn]  ✗ {strat_name_tf} {sym}/{reg} "
                    f"tick_sharpe={_tick_sharpe:.2f}[/warn]"
                )
                tick_rejected += 1
                continue

        strat_name = strategy.get("name", "Strategy")
        safe_sym = sym.replace(":", "_")   # "xyz:GOLD" → "xyz_GOLD" (Windows no permite ":")
        out_path = out_dir / f"{strat_name}_{safe_sym}_{reg}.mq5"
        from btquantr.engine.venue_adapter import VenueAdapter
        strategy = VenueAdapter.adapt_for_mt5(strategy)
        MQL5Generator.to_file(strategy, out_path)
        _sharpe_str = f" tick_sharpe={_tick_sharpe:.2f}" if tick_filter and _status == "sharpe" else ""
        _warn_str = " [warn]⚠ pocos datos[/warn]" if tick_filter and _few_bars else ""
        console.print(
            f"[success]  ✓[/success] [label]{out_path.name}[/label]  "
            f"[muted]{strategy.get('name', '?')} fitness={strategy.get('fitness', 0):.4f}"
            f"{_sharpe_str}[/muted]{_warn_str}"
        )
        exported += 1

    suffix = ""
    if skipped:
        suffix += f", [warn]{skipped}[/warn] saltados"
    if tick_rejected:
        suffix += f", [warn]{tick_rejected}[/warn] rechazados por tick-filter"
    if tick_timeout:
        suffix += f", [warn]{tick_timeout}[/warn] timeout ({TICK_FILTER_TIMEOUT_S}s)"
    console.print(
        f"\n[brand]mt5-all[/brand] → [success]{exported}[/success] archivos exportados"
        + suffix
        + f" en [label]{out_dir}[/label]"
    )


@main.command("download-ticks")
@click.option("--source", required=True,
              type=click.Choice(["hl", "hl-s3", "dukascopy", "tardis"]),
              help="Fuente de tick data")
@click.option("--symbols", default="BTCUSDT",
              help="Símbolos separados por coma: BTCUSDT,EURUSD")
@click.option("--duration", default=30, show_default=True,
              help="Segundos de colección (solo --source hl)")
@click.option("--start-block", default=None, type=int,
              help="Bloque inicial (solo --source hl-s3)")
@click.option("--n-blocks", default=10, show_default=True, type=int,
              help="Número de bloques a descargar (solo --source hl-s3)")
@click.option("--date", default=None,
              help="Fecha YYYY-MM-DD (solo --source tardis)")
@click.option("--no-cache", "no_cache", is_flag=True, default=False,
              help="Ignorar caché y forzar descarga")
def download_ticks(source: str, symbols: str, duration: int, start_block: int,
                   n_blocks: int, date: str, no_cache: bool):
    """Descarga tick data de HyperLiquid, Dukascopy o Tardis.dev."""
    from pathlib import Path
    from btquantr.data.tick_data import (
        HLWebSocketTickSource, HLS3TickSource,
        DukascopyTickSource, TardisTickSource,
    )
    ticks_dir = Path("data/ticks")
    sym_list = [s.strip() for s in symbols.split(",")]

    source_map = {
        "hl":        HLWebSocketTickSource(ticks_dir=ticks_dir),
        "hl-s3":     HLS3TickSource(ticks_dir=ticks_dir),
        "dukascopy": DukascopyTickSource(ticks_dir=ticks_dir),
        "tardis":    TardisTickSource(ticks_dir=ticks_dir),
    }
    src = source_map[source]

    for sym in sym_list:
        console.print(f"[brand]download-ticks[/brand] [{source}] [label]{sym}[/label]...")
        kwargs: dict = {"no_cache": no_cache}
        if source == "hl":
            kwargs["duration_seconds"] = duration
        elif source == "hl-s3":
            kwargs["start_block"] = start_block
            kwargs["n_blocks"] = n_blocks
        elif source == "tardis":
            kwargs["date"] = date

        try:
            df = src.download(sym, **kwargs)
            if df.empty:
                console.print(f"  [warn]  {sym}: sin datos[/warn]")
            else:
                console.print(f"  [ok]  {sym}: {len(df):,} ticks → {src._cache_path(sym)}[/ok]")
        except Exception as exc:
            console.print(f"  [error]  {sym}: {exc}[/error]")


# ── MT5 ────────────────────────────────────────────────────────────────────────

@main.group("mt5")
def mt5_group():
    """Conexión directa con MetaTrader5: cuenta, posiciones y órdenes."""
    pass


@mt5_group.command("connect")
@click.option("--login", default=None, type=int, help="Número de cuenta MT5")
@click.option("--server", default=None, help="Servidor MT5 (ej. 'Demo-Server')")
@click.option("--password", default=None, help="Contraseña de la cuenta")
def mt5_connect(login, server, password):
    """Conecta con MT5 y muestra el estado de la cuenta."""
    from btquantr.execution.mt5_connector import MT5Connector

    conn = MT5Connector()
    ok = conn.connect(login=login, server=server, password=password)
    if not ok:
        console.print("[error]No se pudo conectar con MT5. Verifica que MT5 esté abierto.[/error]")
        return

    info = conn.get_account_info()
    if info is None:
        console.print("[error]Conectado pero no se pudo obtener info de cuenta.[/error]")
        return

    table = Table(title="MT5 — Cuenta", show_header=True, header_style="bold cyan")
    table.add_column("Campo", style="label")
    table.add_column("Valor", style="ok")
    table.add_row("Login",    str(info["login"]))
    table.add_row("Servidor", str(info["server"]))
    table.add_row("Balance",  f"{info['balance']:.2f} {info['currency']}")
    table.add_row("Equity",   f"{info['equity']:.2f} {info['currency']}")
    table.add_row("Margen",   f"{info['margin']:.2f} {info['currency']}")
    console.print(table)


@mt5_group.command("positions")
@click.option("--login", default=None, type=int, help="Número de cuenta MT5")
@click.option("--server", default=None, help="Servidor MT5")
@click.option("--password", default=None, help="Contraseña de la cuenta")
def mt5_positions(login, server, password):
    """Muestra posiciones abiertas en MT5."""
    from btquantr.execution.mt5_connector import MT5Connector

    conn = MT5Connector()
    ok = conn.connect(login=login, server=server, password=password)
    if not ok:
        console.print("[error]No se pudo conectar con MT5.[/error]")
        return

    positions = conn.get_positions()
    if not positions:
        console.print("[muted]No hay posiciones abiertas.[/muted]")
        return

    table = Table(title=f"MT5 — Posiciones abiertas ({len(positions)})",
                  show_header=True, header_style="bold cyan")
    table.add_column("Ticket", style="label")
    table.add_column("Símbolo")
    table.add_column("Dir.")
    table.add_column("Vol.")
    table.add_column("Entrada")
    table.add_column("Actual")
    table.add_column("P&L")
    for p in positions:
        pnl_style = "ok" if p["profit"] >= 0 else "error"
        table.add_row(
            str(p["ticket"]),
            p["symbol"],
            p["direction"],
            f"{p['volume']:.2f}",
            f"{p['price_open']:.5f}",
            f"{p['price_current']:.5f}",
            f"[{pnl_style}]{p['profit']:.2f}[/{pnl_style}]",
        )
    console.print(table)


# ── TRADE ──────────────────────────────────────────────────────────────────────

@main.group("trade")
def trade_group():
    """Ejecución multi-broker: HyperLiquid (crypto) + MT5 (forex/stocks)."""
    pass


@mt5_group.command("backtest-all")
@click.option("--mt5-path", default=None, help="Ruta a terminal64.exe (autodetecta si no se indica)")
@click.option("--symbol", default="EURUSD", show_default=True, help="Símbolo para los backtests")
@click.option("--timeframe", default="H1", show_default=True, help="Timeframe (H1, H4, D1…)")
@click.option("--date-from", default="2024.01.01", show_default=True, help="Fecha inicio (YYYY.MM.DD)")
@click.option("--date-to",   default="2024.12.31", show_default=True, help="Fecha fin (YYYY.MM.DD)")
@click.option("--deposit",   default=10_000, show_default=True, type=int, help="Depósito inicial USD")
def mt5_backtest_all(mt5_path, symbol, timeframe, date_from, date_to, deposit):
    """Ejecuta backtests de todos los EAs en exports/mt5/ y muestra tabla comparativa."""
    from datetime import datetime
    from pathlib import Path as _Path
    from btquantr.execution.mt5_backtester import MT5Backtester

    _path = None
    if mt5_path:
        _path = _Path(mt5_path)
    else:
        _path = MT5Backtester.detect_mt5_path()

    if _path is None:
        console.print("[error]MT5 no encontrado. Indica la ruta con --mt5-path[/error]")
        return

    def _parse_date(s: str):
        return datetime.strptime(s, "%Y.%m.%d").date()

    bt = MT5Backtester(mt5_path=_path)
    console.print(f"[brand]Backtesting todos los EAs → {_path}[/brand]")
    results = bt.run_all(
        symbol=symbol,
        timeframe=timeframe,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
        deposit=deposit,
    )

    if not results:
        console.print("[muted]No se encontraron EAs en exports/mt5/[/muted]")
        return

    table = Table(title="MT5 — Resultados Backtest", show_header=True, header_style="bold cyan")
    table.add_column("EA", style="label")
    table.add_column("Estado")
    table.add_column("Profit", justify="right")
    table.add_column("Sharpe", justify="right")
    table.add_column("WR%", justify="right")
    table.add_column("DD%", justify="right")
    table.add_column("PF", justify="right")
    table.add_column("Trades", justify="right")

    for r in results:
        status_str = "[ok]OK[/ok]" if r.get("status") == "ok" else f"[error]{r.get('status','?')}[/error]"
        table.add_row(
            r.get("ea_name", "?"),
            status_str,
            f"{r.get('net_profit') or 0:.2f}" if r.get("status") == "ok" else "-",
            f"{r.get('sharpe') or 0:.2f}" if r.get("status") == "ok" else "-",
            f"{r.get('win_rate') or 0:.1f}" if r.get("status") == "ok" else "-",
            f"{r.get('drawdown_pct') or 0:.1f}" if r.get("status") == "ok" else "-",
            f"{r.get('profit_factor') or 0:.2f}" if r.get("status") == "ok" else "-",
            str(r.get("total_trades") or "-") if r.get("status") == "ok" else "-",
        )
    console.print(table)


@mt5_group.command("optimize")
@click.option("--ea", required=True, help="Nombre del EA (ej. EURUSD_BEAR)")
@click.option("--tp", default="20,30,40,50", show_default=True, help="Valores TP separados por coma")
@click.option("--sl", default="15,20,25,30", show_default=True, help="Valores SL separados por coma")
@click.option("--symbol", default="EURUSD", show_default=True)
@click.option("--timeframe", default="H1", show_default=True)
@click.option("--date-from", default="2024.01.01", show_default=True)
@click.option("--date-to",   default="2024.12.31", show_default=True)
@click.option("--deposit",   default=10_000, show_default=True, type=int)
@click.option("--mt5-path", default=None, help="Ruta a terminal64.exe")
def mt5_optimize(ea, tp, sl, symbol, timeframe, date_from, date_to, deposit, mt5_path):
    """Optimiza TP/SL de un EA con grid search y muestra la mejor combinación."""
    from datetime import datetime
    from btquantr.execution.mt5_backtester import MT5Backtester
    from pathlib import Path as _Path

    _p = _Path(mt5_path) if mt5_path else MT5Backtester.detect_mt5_path()
    if _p is None:
        console.print("[error]MT5 no encontrado. Indica la ruta con --mt5-path[/error]")
        return

    def _parse_date(s: str):
        return datetime.strptime(s, "%Y.%m.%d").date()

    tp_vals  = [int(v.strip()) for v in tp.split(",")]
    sl_vals  = [int(v.strip()) for v in sl.split(",")]

    bt = MT5Backtester(mt5_path=_p)
    console.print(f"[brand]Optimizando {ea}: TP={tp_vals} SL={sl_vals}[/brand]")

    best = bt.optimize(
        ea_name=ea,
        symbol=symbol,
        param_ranges={"tp": tp_vals, "sl": sl_vals},
        timeframe=timeframe,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
        deposit=deposit,
    )

    if not best:
        console.print("[error]No se encontraron resultados de optimización.[/error]")
        return

    table = Table(title=f"MT5 Optimize — Mejor configuración para {ea}",
                  show_header=True, header_style="bold cyan")
    table.add_column("Parámetro", style="label")
    table.add_column("Valor", style="ok")
    for k, v in best.items():
        table.add_row(str(k), str(v) if v is not None else "-")
    console.print(table)


@trade_group.command("connect")
@click.option("--hl-key", "hl_key", default=None, envvar="HL_PRIVATE_KEY",
              help="Clave privada HyperLiquid (o env HL_PRIVATE_KEY)")
@click.option("--mt5-login", default=None, type=int, help="Login MT5")
@click.option("--mt5-server", default=None, help="Servidor MT5")
@click.option("--mt5-password", default=None, help="Contraseña MT5")
def trade_connect(hl_key, mt5_login, mt5_server, mt5_password):
    """Conecta con HyperLiquid y MT5 y muestra el estado de ambas conexiones."""
    from btquantr.execution.hl_connector import HLConnector
    from btquantr.execution.mt5_connector import MT5Connector

    table = Table(title="Trade — Estado de conexiones", show_header=True,
                  header_style="bold cyan")
    table.add_column("Broker", style="label")
    table.add_column("Estado")
    table.add_column("Info")

    # ── HyperLiquid ──
    if hl_key:
        hl = HLConnector()
        hl_ok = hl.connect(hl_key)
        if hl_ok:
            addr = hl._address or ""
            table.add_row("HyperLiquid", "[ok]Conectado[/ok]",
                          f"wallet: {addr[:10]}..." if addr else "wallet: desconocida")
        else:
            table.add_row("HyperLiquid", "[error]Error[/error]", "clave inválida o red no disponible")
    else:
        table.add_row("HyperLiquid", "[warn]Sin clave[/warn]", "usa --hl-key o env HL_PRIVATE_KEY")

    # ── MT5 ──
    mt5 = MT5Connector()
    mt5_ok = mt5.connect(login=mt5_login, server=mt5_server, password=mt5_password)
    if mt5_ok:
        info = mt5.get_account_info() or {}
        table.add_row(
            "MT5",
            "[ok]Conectado[/ok]",
            f"login:{info.get('login')} server:{info.get('server')} "
            f"balance:{info.get('balance', 0):.2f} {info.get('currency', '')}",
        )
    else:
        table.add_row("MT5", "[error]No conectado[/error]",
                      "verifica que MT5 esté abierto")

    console.print(table)

    if not hl_key and not mt5_ok:
        console.print("[error]No se pudo conectar a ningún broker.[/error]")


@trade_group.command("positions")
@click.option("--hl-key", "hl_key", default=None, envvar="HL_PRIVATE_KEY",
              help="Clave privada HyperLiquid")
@click.option("--mt5-login", default=None, type=int)
@click.option("--mt5-server", default=None)
@click.option("--mt5-password", default=None)
def trade_positions(hl_key, mt5_login, mt5_server, mt5_password):
    """Muestra posiciones abiertas en HyperLiquid y MT5."""
    from btquantr.execution.hl_connector import HLConnector
    from btquantr.execution.mt5_connector import MT5Connector
    from btquantr.execution.router import ExecutionRouter

    hl, mt5 = None, None
    if hl_key:
        hl = HLConnector()
        hl.connect(hl_key)

    mt5_conn = MT5Connector()
    if mt5_conn.connect(login=mt5_login, server=mt5_server, password=mt5_password):
        mt5 = mt5_conn

    router = ExecutionRouter(hl_connector=hl, mt5_connector=mt5)
    positions = router.get_all_positions()

    if not positions:
        console.print("[muted]Sin posiciones abiertas.[/muted]")
        return

    table = Table(title=f"Posiciones abiertas ({len(positions)})",
                  show_header=True, header_style="bold cyan")
    table.add_column("Broker", style="label")
    table.add_column("Símbolo")
    table.add_column("Dir.")
    table.add_column("Size")
    table.add_column("P&L")

    for p in positions:
        pnl = p.get("unrealized_pnl") or p.get("profit") or 0.0
        pnl_style = "ok" if pnl >= 0 else "error"
        size = p.get("size") or p.get("volume") or 0.0
        table.add_row(
            p.get("source", "?").upper(),
            p.get("symbol", "?"),
            p.get("direction", "?"),
            f"{size:.4f}",
            f"[{pnl_style}]{pnl:.2f}[/{pnl_style}]",
        )
    console.print(table)


@trade_group.command("execute")
@click.option("--symbol",    required=True,  help="Símbolo (ej. BTCUSDT, EURUSD)")
@click.option("--direction", required=True,  type=click.Choice(["BUY", "SELL"]),
              help="Dirección de la orden")
@click.option("--size",      required=True,  type=float, help="Tamaño de la orden")
@click.option("--sl",        default=None,   type=float, help="Stop Loss")
@click.option("--tp",        default=None,   type=float, help="Take Profit")
@click.option("--hl-key",    "hl_key", default=None, envvar="HL_PRIVATE_KEY")
@click.option("--mt5-login", default=None, type=int)
@click.option("--mt5-server", default=None)
@click.option("--mt5-password", default=None)
@click.option("--live", is_flag=True, default=False,
              help="Ejecutar orden real (sin --live corre en DRY-RUN)")
def trade_execute(symbol, direction, size, sl, tp,
                  hl_key, mt5_login, mt5_server, mt5_password, live):
    """Envía una orden al broker correcto según el símbolo.

    Por defecto corre en DRY-RUN. Usa --live para órdenes reales.
    """
    from btquantr.execution.hl_connector import HLConnector
    from btquantr.execution.mt5_connector import MT5Connector
    from btquantr.execution.router import ExecutionRouter

    dry_run = not live

    hl, mt5 = None, None
    if hl_key and not dry_run:
        hl = HLConnector()
        hl.connect(hl_key)
    if not dry_run:
        mt5_conn = MT5Connector()
        if mt5_conn.connect(login=mt5_login, server=mt5_server, password=mt5_password):
            mt5 = mt5_conn

    router = ExecutionRouter(hl_connector=hl, mt5_connector=mt5, dry_run=dry_run)

    if dry_run:
        console.print(Panel(
            f"[warn]DRY-RUN[/warn] — orden simulada (usa --live para ejecutar)\n"
            f"  símbolo:   [label]{symbol}[/label]\n"
            f"  dirección: [label]{direction}[/label]\n"
            f"  size:      [label]{size}[/label]\n"
            f"  broker:    [label]{router.route(symbol).upper()}[/label]",
            title="Trade Execute — DRY-RUN",
            border_style="yellow",
        ))
        result = router.send_order(symbol, direction, size, sl=sl, tp=tp)
        console.print(f"  [muted]dry_run result: {result}[/muted]")
    else:
        result = router.send_order(symbol, direction, size, sl=sl, tp=tp)
        if result.get("success"):
            console.print(
                f"[ok]✓ Orden enviada[/ok] {direction} {symbol} size={size} "
                f"order_id={result.get('order_id')}"
            )
        else:
            console.print(f"[error]✗ Error:[/error] {result.get('error', result)}")


@trade_group.command("circuit-status")
def trade_circuit_status():
    """Muestra estado de todos los circuit breakers."""
    from btquantr.security.circuit_breakers import (
        DailyLossLimit, WeeklyLossLimit, MaxDrawdownLimit, MaxPositions,
        CircuitBreakerManager,
    )
    from btquantr.redis_client import is_redis_available, get_redis
    from btquantr.config_manager import ConfigManager, DEFAULT_CONFIG

    r = get_redis() if is_redis_available() else None

    # Cargar thresholds desde ConfigManager si Redis disponible
    if r:
        cfg = ConfigManager(r)
        daily_pct = float(cfg.get("cb_daily_loss_pct", 3.0))
        weekly_pct = float(cfg.get("cb_weekly_loss_pct", 7.0))
        dd_pct = float(cfg.get("cb_max_drawdown_pct", 15.0))
        max_pos = int(cfg.get("cb_max_positions", 5))
    else:
        daily_pct = float(DEFAULT_CONFIG.get("cb_daily_loss_pct", 3.0))
        weekly_pct = float(DEFAULT_CONFIG.get("cb_weekly_loss_pct", 7.0))
        dd_pct = float(DEFAULT_CONFIG.get("cb_max_drawdown_pct", 15.0))
        max_pos = int(DEFAULT_CONFIG.get("cb_max_positions", 5))

    manager = CircuitBreakerManager(
        daily_limit=DailyLossLimit(threshold_pct=daily_pct),
        weekly_limit=WeeklyLossLimit(threshold_pct=weekly_pct),
        drawdown_limit=MaxDrawdownLimit(threshold_pct=dd_pct),
        max_positions=MaxPositions(max_positions=max_pos),
        r=r,
    )

    # Leer estado del portfolio desde Redis si disponible
    portfolio: dict = {}
    n_positions = 0
    if r:
        import json as _json
        raw = r.get("risk:status")
        if raw:
            portfolio = _json.loads(raw)
        raw_pos = r.get("positions:count")
        if raw_pos:
            n_positions = int(raw_pos)

    statuses = manager.status_all(portfolio, n_positions)

    tbl = Table(title="Circuit Breakers — Estado", show_header=True)
    tbl.add_column("Breaker", style="bold", width=22)
    tbl.add_column("Estado", width=12)
    tbl.add_column("Threshold", width=12)
    tbl.add_column("Actual", width=12)

    for st in statuses:
        tripped = st["tripped"]
        estado = "[red]TRIPPED[/red]" if tripped else "[green]OK[/green]"
        tbl.add_row(
            st["name"],
            estado,
            str(st["threshold"]),
            str(st["current_value"]),
        )

    console.print(tbl)


@trade_group.command("test-connection")
@click.option("--testnet", is_flag=True, default=False, help="Usar testnet de HyperLiquid")
@click.option("--key-name", "key_name", default=None,
              help="Nombre de la clave en vault/.env (default: HL_TESTNET_PRIVATE_KEY para testnet)")
def trade_test_connection(testnet: bool, key_name: str):
    """Conecta al testnet/mainnet de HyperLiquid, muestra balance y posiciones."""
    from btquantr.security.credential_vault import vault_or_env
    default_key = "HL_TESTNET_PRIVATE_KEY" if testnet else "HL_PRIVATE_KEY"
    key = key_name or default_key
    private_key = vault_or_env(key)
    net_label = "[warn]TESTNET[/warn]" if testnet else "[success]MAINNET[/success]"
    console.print(f"\n[brand]HyperLiquid — {net_label}[/brand]")

    conn = HLConnector(testnet=testnet)
    if not private_key:
        console.print(f"[error]No se encontró '{key}' en vault ni en .env[/error]")
        return

    ok = conn.connect(private_key)
    if not ok:
        console.print("[error]Conexión fallida — verifica la clave privada[/error]")
        return

    balance = conn.get_balance()
    console.print(f"  Balance: [success]${balance:,.2f}[/success]")

    positions = conn.get_positions()
    if not positions:
        console.print("  [muted]Sin posiciones abiertas[/muted]")
    else:
        tbl = Table(title="Posiciones abiertas", show_header=True, header_style="bold cyan")
        tbl.add_column("Símbolo")
        tbl.add_column("Dir")
        tbl.add_column("Size")
        tbl.add_column("Entry")
        tbl.add_column("PnL")
        for p in positions:
            pnl = p.get("unrealized_pnl", 0.0)
            pnl_style = "success" if pnl >= 0 else "error"
            tbl.add_row(
                p["symbol"], p["direction"],
                str(p["size"]), f"${p['entry_price']:,.2f}",
                f"[{pnl_style}]${pnl:+,.2f}[/{pnl_style}]",
            )
        console.print(tbl)
    console.print("[muted]Conexión cerrada[/muted]")
    conn.disconnect()


@trade_group.command("test-order")
@click.option("--testnet", is_flag=True, default=False, help="Usar testnet de HyperLiquid")
@click.option("--symbol", default="BTC", show_default=True, help="Coin (ej: BTC, ETH)")
@click.option("--direction", default="BUY", type=click.Choice(["BUY", "SELL"]),
              show_default=True, help="Dirección de la orden")
@click.option("--size", default=0.001, type=float, show_default=True,
              help="Tamaño de la orden en la unidad del activo")
@click.option("--key-name", "key_name", default=None,
              help="Nombre de la clave en vault/.env")
def trade_test_order(testnet: bool, symbol: str, direction: str, size: float, key_name: str):
    """Envía una orden real al testnet/mainnet y cierra la posición tras verificar el fill."""
    from btquantr.security.credential_vault import vault_or_env
    default_key = "HL_TESTNET_PRIVATE_KEY" if testnet else "HL_PRIVATE_KEY"
    key = key_name or default_key
    private_key = vault_or_env(key)
    net_label = "TESTNET" if testnet else "MAINNET"
    console.print(f"\n[brand]Test Order — {net_label} | {direction} {size} {symbol}[/brand]")

    conn = HLConnector(testnet=testnet)
    if not private_key:
        console.print(f"[error]No se encontró '{key}' en vault ni en .env[/error]")
        return

    ok = conn.connect(private_key)
    if not ok:
        console.print("[error]Conexión fallida[/error]")
        return

    # Enviar orden
    with console.status(f"[cyan]Enviando orden {direction} {size} {symbol}...[/cyan]"):
        result = conn.send_order(symbol, direction, size)

    if not result.get("success"):
        console.print(f"[error]Orden fallida: {result.get('error', 'unknown')}[/error]")
        conn.disconnect()
        return

    order_id = result.get("order_id")
    console.print(f"  [success]Orden ejecutada — order_id={order_id}[/success]")

    # Cerrar posición
    with console.status(f"[cyan]Cerrando posición {symbol}...[/cyan]"):
        close_result = conn.close_position(symbol)

    if close_result.get("success"):
        console.print(f"  [success]Posición cerrada — order_id={close_result.get('order_id')}[/success]")
    else:
        console.print(f"  [warn]Close retornó: {close_result}[/warn]")

    conn.disconnect()
    console.print("[muted]Test completado[/muted]")


@trade_group.command("pnl")
@click.option("--live", is_flag=True, default=False, help="Actualizar PnL en tiempo real con Rich Live")
@click.option("--interval", default=1, type=int, show_default=True,
              help="Segundos entre actualizaciones (solo con --live)")
def trade_pnl(live: bool, interval: int):
    """Muestra PnL mark-to-market actual. Con --live actualiza cada N segundos."""
    from rich.live import Live
    from rich.table import Table as RichTable
    import time as _time

    tracker = PnLTracker()

    def _build_table() -> RichTable:
        summary = tracker.get_summary()
        tbl = RichTable(title="PnL Mark-to-Market", show_header=True, header_style="bold cyan")
        tbl.add_column("Símbolo")
        tbl.add_column("Side")
        tbl.add_column("Size")
        tbl.add_column("Entry")
        tbl.add_column("Mark")
        tbl.add_column("PnL USD")
        tbl.add_column("PnL %")

        for sym, pos in summary["positions"].items():
            pnl = pos["unrealized_pnl"]
            pnl_style = "green" if pnl >= 0 else "red"
            tbl.add_row(
                sym,
                pos["side"],
                f"{pos['size']:.6g}",
                f"${pos['entry_price']:,.2f}",
                f"${pos['mark_price']:,.2f}",
                f"[{pnl_style}]{pnl:+,.2f}[/{pnl_style}]",
                f"[{pnl_style}]{pos['pnl_pct']:+.2f}%[/{pnl_style}]",
            )

        total = summary["total_unrealized_pnl"]
        total_style = "green" if total >= 0 else "red"
        tbl.add_section()
        tbl.add_row(
            "TOTAL", "", "", "", "",
            f"[bold {total_style}]{total:+,.2f}[/bold {total_style}]", "",
        )
        return tbl

    if not live:
        console.print(_build_table())
        return

    console.print("[muted]Iniciando PnL live (Ctrl+C para detener)...[/muted]")
    try:
        with Live(console=console, refresh_per_second=1) as live_ctx:
            while True:
                live_ctx.update(_build_table())
                _time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[muted]PnL live detenido[/muted]")


@trade_group.command("size")
@click.option("--symbol",        required=True,  help="Símbolo (ej. BTCUSDT)")
@click.option("--direction",     required=True,  type=click.Choice(["BUY", "SELL"]),
              help="Dirección de la orden")
@click.option("--balance",       required=True,  type=float, help="Capital disponible en USD")
@click.option("--win-rate",      "win_rate",      default=0.55, type=float, show_default=True,
              help="Tasa de aciertos histórica (0-1)")
@click.option("--avg-win",       "avg_win",       default=1.5,  type=float, show_default=True,
              help="Ganancia media por trade (ratio)")
@click.option("--avg-loss",      "avg_loss",      default=1.0,  type=float, show_default=True,
              help="Pérdida media por trade (ratio)")
@click.option("--regime",        default="BULL",  type=click.Choice(["BULL", "SIDEWAYS", "BEAR"]),
              show_default=True, help="Régimen de mercado")
@click.option("--atr",           default=None,   type=float,
              help="ATR actual del símbolo (opcional)")
@click.option("--atr-mean",      "atr_mean",      default=None, type=float,
              help="ATR medio de referencia (requerido si --atr se pasa)")
@click.option("--open-exposure", "open_exposure", default=0.0,  type=float, show_default=True,
              help="Exposure abierta total en USD (portfolio heat usado)")
@click.option("--max-heat",      "max_heat",      default=30.0, type=float, show_default=True,
              help="Portfolio heat máximo %% del balance")
@click.option("--max-single",    "max_single",    default=10.0, type=float, show_default=True,
              help="Tamaño máximo single posición %% del balance")
def trade_size(symbol, direction, balance, win_rate, avg_win, avg_loss,
               regime, atr, atr_mean, open_exposure, max_heat, max_single):
    """Calcula el tamaño óptimo de posición con Kelly Criterion + ajustes."""
    from btquantr.execution.position_sizer import PositionSizer

    ps = PositionSizer(max_portfolio_heat_pct=max_heat, max_single_pct=max_single)
    result = ps.calculate(
        balance=balance,
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        regime=regime,
        atr=atr,
        atr_mean=atr_mean,
        open_exposure_usd=open_exposure,
    )

    if result["blocked"]:
        console.print(Panel(
            f"[error]BLOQUEADO[/error] — sin capacidad de portfolio heat\n"
            f"  Exposure abierta: [warn]${open_exposure:,.2f}[/warn]\n"
            f"  Heat máximo:      [warn]${balance * max_heat / 100:,.2f}[/warn] ({max_heat}% de ${balance:,.0f})\n"
            f"  Razón:            [warn]{result['reason']}[/warn]",
            title="Position Sizer — BLOQUEADO",
            border_style="red",
        ))
        return

    # Tabla de resultados
    atr_scale_pct = result["atr_scale"] * 100
    capped_label = f"[warn]{result['capped_by']}[/warn]" if result["capped_by"] else "[ok]ninguno[/ok]"

    table = Table(
        title=f"Position Sizer — {direction} {symbol} @ ${balance:,.0f}",
        show_header=True, header_style="bold cyan",
    )
    table.add_column("Parámetro", style="label", width=26)
    table.add_column("Valor", justify="right")

    table.add_row("Tamaño USD",       f"[ok]${result['size_usd']:,.2f}[/ok]")
    table.add_row("Tamaño %",         f"[ok]{result['size_pct']:.2f}%[/ok]")
    table.add_row("Kelly (bruto)",    f"{result['kelly_fraction']*100:.2f}%")
    table.add_row("Régimen",          f"{regime}  (×{result['regime_scale']:.2f})")
    table.add_row("ATR scale",        f"{atr_scale_pct:.1f}%"
                                      + (f"  [warn](ATR={atr:.1f} > 2×{atr_mean:.1f})[/warn]"
                                         if atr and atr_mean and atr > 2 * atr_mean else ""))
    table.add_row("Portfolio heat",   f"${open_exposure:,.2f} / ${balance*max_heat/100:,.2f}")
    table.add_row("Limitado por",     capped_label)

    console.print(table)


# ═══════════════════════════════════════════════════════════════════════════════
# vault — CredentialVault: almacén cifrado de API keys
# ═══════════════════════════════════════════════════════════════════════════════

@main.group("vault")
def vault_group():
    """Almacén cifrado de API keys y secretos (AES-256-GCM)."""
    pass


def _get_vault():
    """Retorna CredentialVault usando BTQUANTR_VAULT_PATH o data/vault.enc."""
    from btquantr.security.credential_vault import CredentialVault
    return CredentialVault()


@vault_group.command("init")
def vault_init():
    """Crea el vault cifrado. Pedirá la contraseña maestra."""
    from btquantr.security.credential_vault import VaultError
    v = _get_vault()
    if v.exists():
        console.print("[error]✗ El vault ya existe.[/error]")
        return
    pwd1 = click.prompt("Contraseña maestra", hide_input=True)
    pwd2 = click.prompt("Confirma contraseña", hide_input=True)
    if pwd1 != pwd2:
        console.print("[error]✗ Las contraseñas no coinciden.[/error]")
        return
    try:
        v.init(pwd1)
        console.print("[ok]✓ Vault creado correctamente.[/ok]")
    except VaultError as exc:
        console.print(f"[error]✗ Error:[/error] {exc}")


@vault_group.command("set")
@click.argument("name")
def vault_set(name):
    """Guarda o actualiza una clave en el vault."""
    from btquantr.security.credential_vault import VaultError
    v = _get_vault()
    if not v.exists():
        console.print("[error]✗ Vault no existe. Ejecuta 'btquantr vault init' primero.[/error]")
        return
    value = click.prompt(f"Valor para {name}", hide_input=True)
    master = click.prompt("Contraseña maestra", hide_input=True)
    try:
        v.store(name, value, master)
        console.print(f"[ok]✓ Clave '{name}' guardada correctamente.[/ok]")
    except VaultError as exc:
        console.print(f"[error]✗ Error:[/error] {exc}")


@vault_group.command("get")
@click.argument("name")
def vault_get(name):
    """Muestra el valor de una clave almacenada en el vault."""
    from btquantr.security.credential_vault import VaultError
    v = _get_vault()
    if not v.exists():
        console.print("[error]✗ Vault no existe. Ejecuta 'btquantr vault init' primero.[/error]")
        return
    master = click.prompt("Contraseña maestra", hide_input=True)
    try:
        value = v.get(name, master)
        if value is None:
            console.print(f"[warn]Clave '{name}' no encontrada en el vault.[/warn]")
        else:
            console.print(f"[label]{name}[/label] = {value}")
    except VaultError as exc:
        console.print(f"[error]✗ Error:[/error] {exc}")


@vault_group.command("list")
def vault_list():
    """Lista los nombres de todas las claves en el vault (sin mostrar valores)."""
    from btquantr.security.credential_vault import VaultError
    v = _get_vault()
    if not v.exists():
        console.print("[warn]Vault no existe. Ejecuta 'btquantr vault init' para crear uno.[/warn]")
        return
    master = click.prompt("Contraseña maestra", hide_input=True)
    try:
        names = v.list_names(master)
        if not names:
            console.print("[muted]El vault está vacío.[/muted]")
        else:
            for n in names:
                console.print(f"  [label]{n}[/label]")
    except VaultError as exc:
        console.print(f"[error]✗ Error:[/error] {exc}")


@vault_group.command("delete")
@click.argument("name")
def vault_delete(name):
    """Elimina una clave del vault."""
    from btquantr.security.credential_vault import VaultError
    v = _get_vault()
    if not v.exists():
        console.print("[error]✗ Vault no existe.[/error]")
        return
    master = click.prompt("Contraseña maestra", hide_input=True)
    try:
        v.delete(name, master)
        console.print(f"[ok]✓ Clave '{name}' eliminada.[/ok]")
    except VaultError as exc:
        console.print(f"[error]✗ Error:[/error] {exc}")
