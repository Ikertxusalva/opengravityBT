"""
run.py — Punto de entrada unificado para backtest-architect + agentes moondev.

Uso:
    uv run python moondev/run.py                          # lista todo
    uv run python moondev/run.py breakout META 1h         # test individual
    uv run python moondev/run.py squeeze-v2 BTC 1h --multi # test multi-activo
    uv run python moondev/run.py agent funding             # lanza agente de mercado
    uv run python moondev/run.py agent rbi                 # lanza rbi_agent_v3
"""
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent

# ── Estrategias backtestables ─────────────────────────────────────────────────
STRATEGIES = {
    # Testeadas y validadas
    "breakout":    ("moondev/strategies/breakout_retest.py",      "BreakoutRetest"),
    "squeeze":     ("moondev/strategies/volatility_squeeze.py",   "VolatilitySqueeze"),
    "squeeze-v2":  ("moondev/strategies/volatility_squeeze_v2.py","VolatilitySqueezeV2"),

    # Testeadas - resultados mixtos
    "supertrend":  ("moondev/strategies/supertrend_adaptive.py",  "SuperTrendAdaptive"),
    "gap":         ("moondev/strategies/gap_and_go.py",           "GapAndGo"),
    "liq-dip":     ("moondev/strategies/liquidation_dip.py",      "LiquidationDip"),
    "orb":         ("moondev/strategies/orb_strategy.py",         "ORBStrategy"),

    # Pendientes de test completo
    "bollinger":   ("moondev/strategies/bollinger_altcoin.py",    "BollingerAltcoin"),
    "funding-rev": ("moondev/strategies/funding_reversal.py",     "FundingReversal"),
    "vol-mom":     ("moondev/strategies/volume_momentum.py",      "VolumeMomentum"),
    "patterns":    ("moondev/strategies/technical_patterns.py",   "TechnicalPatterns"),
    "arb":         ("moondev/strategies/synthetic_arb.py",        "SyntheticArb"),
    "rsi-band":    ("moondev/strategies/rsi_band.py",             "RSIBand"),
}

# ── Agentes de mercado ────────────────────────────────────────────────────────
AGENTS = {
    # Pipeline RBI
    "rbi":         ("moondev/agents/rbi_agent_v3.py",       "RBI Agent v3 — Research+Code+Optimize"),
    "research":    ("moondev/agents/research_agent.py",     "Generador de ideas -> ideas.txt"),
    # Market intelligence
    "funding":     ("moondev/agents/funding_agent.py",      "Funding Rates HyperLiquid (15min)"),
    "liquidation": ("moondev/agents/liquidation_agent.py",  "Liquidation Spike Detector (10min)"),
    "coingecko":   ("moondev/agents/coingecko_agent.py",    "Macro Dual Analysis — CoinGecko (30min)"),
    "chart":       ("moondev/agents/chart_agent.py",        "Price Action + Estructura de Mercado (30min)"),
    "news":        ("moondev/agents/news_agent.py",         "Noticias Crypto — Impacto en precio (10min)"),
    "top-mover":   ("moondev/agents/top_mover_agent.py",    "Top Gainers/Losers — Momentum/Contrarian (15min)"),
    "whale":       ("moondev/agents/whale_agent.py",        "On-Chain Whale Tracker (20min)"),
    "new-listing": ("moondev/agents/new_listing_agent.py",  "Nuevos Listings Binance/Coinbase (30min)"),
    # Execution
    "copybot":     ("moondev/agents/copybot_agent.py",      "Portfolio Rebalancer — HyperLiquid"),
    "sentiment":   ("moondev/agents/sentiment_agent.py",    "Twitter Sentiment / BERT (15min)"),
    "sniper":      ("moondev/agents/sniper_agent.py",       "Solana Token Sniper (10s polling)"),
}

# ── Universos de activos ──────────────────────────────────────────────────────
STOCK_SYMBOLS  = "AAPL,MSFT,GOOGL,NVDA,TSLA,AMZN,META,AMD,SPY,QQQ"
CRYPTO_SYMBOLS = "BTC,ETH,SOL,AVAX,LINK,BNB,DOT,ADA"
ALL_SYMBOLS    = STOCK_SYMBOLS + "," + CRYPTO_SYMBOLS


def list_all():
    print("\n" + "=" * 54)
    print("         MOONDEV BACKTEST ARCHITECT")
    print("=" * 54)

    print("\nESTRATEGIAS BACKTESTABLES:")
    print("-" * 54)
    status = {
        "breakout":    "PASS Sharpe 2.06 (META 1h)",
        "squeeze":     "PASS Sharpe 1.61 (BTC 1h)",
        "squeeze-v2":  "PASS Sharpe 2.18 (BTC 1h) <- RECOMENDADA",
        "supertrend":  "CAUTION Sharpe 0.62",
        "gap":         "FAIL (crypto 24/7 incompatible)",
        "liq-dip":     "FAIL (pocos trades)",
        "orb":         "FAIL (WR < 45%)",
        "bollinger":   "TODO pendiente de test",
        "funding-rev": "TODO pendiente de test",
        "vol-mom":     "TODO pendiente de test",
        "patterns":    "TODO pendiente de test",
        "arb":         "TODO pendiente de test",
        "rsi-band":    "TODO pendiente de test",
    }
    for name, (path, cls) in STRATEGIES.items():
        s = status.get(name, "")
        print(f"  {name:<14} ->{cls:<25} {s}")

    print("\nAGENTES DE MERCADO:")
    print("-" * 54)
    for name, (path, desc) in AGENTS.items():
        print(f"  {name:<14} -> {desc}")

    print("\nEJEMPLOS:")
    print("  uv run python moondev/run.py squeeze-v2 BTC 1h")
    print("  uv run python moondev/run.py squeeze-v2 BTC 1h --multi")
    print("  uv run python moondev/run.py squeeze-v2 BTC 1h --multi --dd   # + DD optimizer")
    print("  uv run python moondev/run.py agent funding")
    print("  uv run python moondev/run.py agent rbi")
    print("  uv run python moondev/run.py bollinger BTC 1h --multi --crypto --dd")

    print("\nSWARM MODE:")
    print("-" * 54)
    print("  uv run python moondev/run.py swarm             # un ciclo")
    print("  uv run python moondev/run.py swarm --loop 4    # 4 ciclos c/15min")
    print()


def run_single(strategy_name: str, symbol: str = "BTC", interval: str = "1h"):
    """Test individual de una estrategia."""
    if strategy_name not in STRATEGIES:
        print(f"ERROR: estrategia '{strategy_name}' no encontrada.")
        list_all()
        return

    filepath, classname = STRATEGIES[strategy_name]
    print(f"\n[SINGLE] {classname} | {symbol} | {interval}")
    print("=" * 50)

    import os
    env = os.environ.copy()
    env["BACKTEST_SYMBOL"]   = symbol
    env["BACKTEST_INTERVAL"] = interval

    result = subprocess.run(
        ["uv", "run", "python", filepath],
        cwd=str(ROOT),
        env=env,
    )
    return result.returncode


def run_multi(strategy_name: str, interval: str = "1h", period: str = "1y",
              symbols: str = STOCK_SYMBOLS, optimize_dd: bool = False):
    """Test multi-activo de una estrategia."""
    if strategy_name not in STRATEGIES:
        print(f"ERROR: estrategia '{strategy_name}' no encontrada.")
        list_all()
        return

    filepath, classname = STRATEGIES[strategy_name]
    print(f"\n[MULTI] {classname} | {interval} | {period}")
    print(f"Activos: {symbols}")
    if optimize_dd:
        print("[DD] Fase 2: DD Optimizer activado (Calmar-based ATR params)")
    print("=" * 50)

    cmd = [
        "uv", "run", "python",
        "moondev/backtests/multi_data_tester.py",
        filepath, classname,
        "--interval", interval,
        "--period", period,
        "--symbols", symbols,
    ]
    if optimize_dd:
        cmd.append("--optimize-dd")

    result = subprocess.run(cmd, cwd=str(ROOT))
    return result.returncode


def run_agent(agent_name: str):
    """Lanza un agente de mercado."""
    if agent_name not in AGENTS:
        print(f"ERROR: agente '{agent_name}' no encontrado.")
        print("Agentes disponibles:", ", ".join(AGENTS.keys()))
        return

    filepath, desc = AGENTS[agent_name]
    print(f"\n[AGENT] {desc}")
    print("=" * 50)

    result = subprocess.run(
        ["uv", "run", "python", filepath],
        cwd=str(ROOT),
    )
    return result.returncode


def main():
    args = sys.argv[1:]

    if not args:
        list_all()
        return

    first = args[0]

    if first in ("-h", "--help", "help", "list"):
        list_all()
        return

    # Lanzar agente: `run.py agent funding`
    if first == "agent":
        agent_name = args[1] if len(args) > 1 else ""
        if not agent_name:
            print("Uso: uv run python moondev/run.py agent <nombre>")
            print("Agentes:", ", ".join(AGENTS.keys()))
            return
        run_agent(agent_name)
        return

    # Swarm mode: `run.py swarm [--loop N]`
    if first == "swarm":
        from moondev.swarm.coordinator import run_swarm
        loop_count = 1
        for i, a in enumerate(args[1:], 1):
            if a == "--loop" and i + 1 < len(args):
                try:
                    loop_count = int(args[i + 1])
                except ValueError:
                    pass

        import time as _time
        for iteration in range(loop_count):
            if loop_count > 1:
                print(f"\nIteración {iteration+1}/{loop_count}")
            run_swarm()
            if iteration < loop_count - 1:
                print("Próximo ciclo en 15 min...")
                _time.sleep(15 * 60)
        return

    # Backtest de estrategia
    strategy_name = first
    symbol      = args[1] if len(args) > 1 and not args[1].startswith("--") else "BTC"
    interval    = args[2] if len(args) > 2 and not args[2].startswith("--") else "1h"
    multi       = "--multi" in args
    optimize_dd = "--dd" in args or "--optimize-dd" in args
    period      = "1y"
    symbols     = STOCK_SYMBOLS

    for i, a in enumerate(args):
        if a == "--symbols" and i + 1 < len(args):
            symbols = args[i + 1]
        if a == "--period" and i + 1 < len(args):
            period = args[i + 1]
        if a == "--crypto":
            symbols = CRYPTO_SYMBOLS
        if a == "--all":
            symbols = ALL_SYMBOLS

    if multi:
        run_multi(strategy_name, interval=interval, period=period,
                  symbols=symbols, optimize_dd=optimize_dd)
    else:
        run_single(strategy_name, symbol=symbol, interval=interval)


if __name__ == "__main__":
    main()
