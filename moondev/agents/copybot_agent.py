"""
copybot_agent — rebalanceo de portfolio con confidence-scaled sizing.

Analiza posiciones actuales con LLM.
Sizing: target = max_position * (confidence/100).

Uso: python moondev/agents/copybot_agent.py
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from moondev.core.model_factory import ModelFactory
from moondev.core.exchange_manager import ExchangeManager
from moondev.core.portfolio_tracker import PortfolioTracker
from moondev.core.nice_funcs import get_ohlcv, add_indicators, parse_llm_action
import moondev.config as cfg
from rich.console import Console

console = Console()

SYSTEM_PROMPT = """You are a portfolio rebalancing AI.
Analyze the provided position and market data.

Consider:
1. Recent price action and momentum
2. Position size relative to other holdings
3. Risk/reward based on current levels
4. Market conditions (BTC trend)

Respond in exactly 3 lines:
Line 1: BUY (increase), SELL (reduce), or NOTHING
Line 2: One short reason
Line 3: Confidence: X%
"""


def analyze_position(symbol: str, position_info: dict, model) -> tuple[str, str, int]:
    try:
        df = get_ohlcv(f"{symbol}-USD", days=3, timeframe="1h")
        df = add_indicators(df)
        ctx = df.tail(5).to_string()
    except Exception:
        ctx = "No OHLCV data"

    user = f"""
Symbol: {symbol}
Current position: ${position_info.get('usd_value', 0):.2f}
PnL: {position_info.get('pnl_pct', 0):.2f}%
Is Long: {position_info.get('is_long', True)}

Market data (last 5 candles 1h):
{ctx}
"""
    resp = model.ask(SYSTEM_PROMPT, user)
    return parse_llm_action(resp.content)


def main():
    model = ModelFactory().get()
    em = ExchangeManager()
    tracker = PortfolioTracker()

    console.print(f"[bold]copybot_agent[/bold] | {model.name} | exchange: {cfg.EXCHANGE}")

    account_value = em.get_account_value()
    tracker.set_start(account_value)
    console.print(f"Portfolio: ${account_value:.2f}")

    max_position = account_value * (cfg.MAX_POSITION_PERCENTAGE / 100)

    for token in cfg.MONITORED_TOKENS:
        pos = em.get_position(token)
        if not pos.has_position:
            console.print(f"[dim]{token}: sin posición[/dim]")
            continue

        console.print(f"\n[cyan]{token}[/cyan] ${pos.usd_value:.2f} | PnL {pos.pnl_pct:.1f}%")
        action, reason, confidence = analyze_position(
            token, {"usd_value": pos.usd_value, "pnl_pct": pos.pnl_pct, "is_long": pos.is_long},
            model
        )

        if confidence < cfg.STRATEGY_MIN_CONFIDENCE:
            console.print(f"  [dim]SKIP — confianza {confidence}% < {cfg.STRATEGY_MIN_CONFIDENCE}%[/dim]")
            continue

        target_usd = max_position * (confidence / 100)
        console.print(f"  {action} | {confidence}% | target: ${target_usd:.2f} | {reason}")

        if action == "BUY":
            buy_amount = max(0, target_usd - pos.usd_value)
            if buy_amount > 1:
                console.print(f"  [green]→ Comprando ${buy_amount:.2f}[/green]")
                em.market_buy(token, buy_amount)
                time.sleep(cfg.TX_SLEEP)
        elif action == "SELL":
            console.print(f"  [red]→ Vendiendo posición[/red]")
            em.close_position(token)
            time.sleep(cfg.TX_SLEEP)

    account_value = em.get_account_value()
    tracker.log(account_value, "copybot_run")
    pnl = tracker.get_pnl()
    console.print(f"\nPortfolio final: ${account_value:.2f} | PnL: {pnl['pnl_pct']:.2f}%")


if __name__ == "__main__":
    main()
