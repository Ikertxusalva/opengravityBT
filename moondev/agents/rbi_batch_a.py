"""Batch A — ideas 0-5: WhaleFollowingProxy, FundingRateProxy, LiquidationCascadeShort,
VolatilitySqueezeV3MultiAsset, BreakoutRetestFiltered, RSIBandMultiTimeframe"""
import sys, re, hashlib
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from moondev.agents.rbi_agent import research_strategy, create_backtest, package_fix, debug_fix, console, write_code
from moondev.agents.rbi_agent_v2 import execute_backtest, has_zero_trades
from moondev.core.model_factory import ModelFactory, extract_code, clean_response
import moondev.config as cfg

BATCH_TAG = "A"
PROC_LOG = Path("moondev/data/rbi/processed_a.log")
PROC_LOG.touch()

IDEAS = [
    "WhaleFollowingProxy: Volume proxy for whale activity BTC 1h. When volume exceeds 5x 20-period average AND price moves more than 1.5% in one direction: enter same direction. SL 1.5x ATR, TP 2.5x ATR, hold max 8 candles. RSI < 60 for longs, RSI > 40 for shorts.",
    "FundingRateProxy: RSI momentum proxy for funding rates BTC 1h. RSI stays above 70 for 3+ consecutive candles: enter SHORT. RSI below 30 for 3+ candles: LONG. SL 2x ATR, TP 4x ATR. Only if ADX < 25.",
    "LiquidationCascadeShort: When BTC 1h volume spikes 4x average AND candle is green: enter SHORT immediately. Exhaustion reversal. SL 1.5% above entry, TP 3% below. Hold max 6 candles.",
    "VolatilitySqueezeV3MultiAsset: Tighter BB(20, 1.8 std) inside KC(20, 1.0 ATR). Squeeze min 2 bars. ADX > 18. Volume at breakout > 1.3x average. SL 1.5x ATR, TP 3.5x ATR. Goal: works on ETH, SOL, AVAX, META, NVDA 1h not just BTC.",
    "BreakoutRetestFiltered: Swing highs/lows over 20 periods. Break above swing high with volume > 1.5x: wait pullback within 0.5%, then LONG. SL below retest low (1x ATR). TP 2.5x risk. ADX > 25 required. Test on META, NVDA, BTC 1h.",
    "RSIBandMultiTimeframe: LONG only when 1h RSI < 35 AND 4h RSI (resampled from 1h data) < 45. SHORT when 1h RSI > 65 AND 4h RSI > 55. SL 2x ATR, TP 4x ATR. Test on BNB, BTC, ETH.",
]

OPTIMIZE_PROMPT = """You are an expert quantitative trading strategy optimizer.
The current strategy achieved {current_return:.1f}% return but the target is {target}%.
Improve the strategy code to increase returns while maintaining risk management.
Consider: adjust thresholds, add trend filters, optimize SL/TP, fix zero-trade issues.
Current code:\n{code}\nCurrent stats:\n{stats}\nOutput ONLY the improved Python code."""

RUN_BLOCK = """
if __name__ == "__main__":
    from backtesting import Backtest
    import yfinance as yf
    data = yf.download("BTC-USD", period="1y", interval="1h", auto_adjust=True, progress=False)
    data.columns = ["Close","High","Low","Open","Volume"]
    data = data[["Open","High","Low","Close","Volume"]].dropna()
    cash = max(10_000, data["Close"].max() * 3)
    bt = Backtest(data, {cls}, cash=cash, commission=0.001, exclusive_orders=True, finalize_trades=True)
    print(bt.run())
"""

def idea_hash(idea): return hashlib.md5(idea.encode()).hexdigest()
def is_done(idea): return idea_hash(idea) in PROC_LOG.read_text()
def mark_done(idea, name):
    with open(PROC_LOG, "a") as f:
        f.write(f"{idea_hash(idea)},{datetime.now().isoformat()},{name}\n")

def parse_return(stdout):
    m = re.search(r"Return \[%\]\s+([\d\.\-]+)", stdout)
    return float(m.group(1)) if m else 0.0

def add_run_block(code, name):
    if "if __name__" not in code:
        code += RUN_BLOCK.replace("{cls}", name)
    return code


def process(idea, model):
    if is_done(idea):
        print(f"[SKIP] {idea[:60]}", flush=True)
        return
    print(f"\n=== Batch {BATCH_TAG}: {idea[:80]} ===", flush=True)
    name, research = research_strategy(idea, model)
    code = create_backtest(research, model)
    code = package_fix(code, model)
    code = add_run_block(code, name)

    best_return, best_code = -999.0, code
    for attempt in range(1, cfg.MAX_DEBUG_ITERATIONS + 1):
        path = write_code(code, f"{name}_{BATCH_TAG}_v{attempt}", "backtests_final")
        result = execute_backtest(path)
        if result["success"] and not has_zero_trades(result):
            ret = parse_return(result["stdout"])
            print(f"  v{attempt} Return: {ret:.1f}%", flush=True)
            if ret > best_return:
                best_return, best_code = ret, code
            if ret >= cfg.TARGET_RETURN:
                print(f"  TARGET {ret:.1f}% alcanzado!", flush=True)
                break
            if attempt < cfg.MAX_OPTIMIZATION_ITERATIONS:
                prompt = OPTIMIZE_PROMPT.format(
                    current_return=ret, target=cfg.TARGET_RETURN,
                    code=code, stats=result["stdout"][:800])
                resp = model.ask("You are a quant strategy optimizer.", prompt, max_tokens=3000)
                code = extract_code(clean_response(resp.content))
                code = package_fix(code, model)
                code = add_run_block(code, name)
        else:
            err = result["stderr"][-600:] if not result["success"] else "0 trades"
            print(f"  v{attempt} FAIL/0trades - debugging...", flush=True)
            code = debug_fix(code, err, model)
            code = package_fix(code, model)
            code = add_run_block(code, name)

    out_dir = Path("moondev/data/rbi/03_01_2026/backtests_final")
    out_dir.mkdir(parents=True, exist_ok=True)
    if best_return > -999:
        wp = out_dir / f"{name}_{BATCH_TAG}_WORKING.py"
        wp.write_text(best_code, encoding="utf-8")
        print(f"WORKING: {wp.name} ({best_return:.1f}%)", flush=True)
    else:
        print(f"FAIL: {name} sin version funcional", flush=True)
    mark_done(idea, name)


def main():
    model = ModelFactory().get()
    print(f"Batch {BATCH_TAG} | {model.name} | {len(IDEAS)} ideas", flush=True)
    for idea in IDEAS:
        process(idea, model)
    print(f"\nBatch {BATCH_TAG} COMPLETO", flush=True)


if __name__ == "__main__":
    main()
