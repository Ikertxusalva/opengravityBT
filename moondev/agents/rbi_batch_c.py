"""Batch C — ideas 12-17: ATRBreakoutChannel, StochasticMeanReversion, DonchianTurtleBreakout,
OBVDivergenceSignal, SupertrendFilter, CCIMeanReversion"""
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

BATCH_TAG = "C"
PROC_LOG = Path("moondev/data/rbi/processed_c.log")
PROC_LOG.touch()

IDEAS = [
    "ATRBreakoutChannel: SMA(20) with 1.5x ATR channel. Break above SMA + 1.5*ATR with volume > 1.5x: LONG. Break below: SHORT. SL 1x ATR, TP 2.5x ATR. ADX(14) > 20. Exit if returns inside channel. BTC 1h, ETH 1h, META 1h.",
    "StochasticMeanReversion: StochRSI(14,14,3,3). LONG when K crosses above D AND both below 20 AND price near 20-period swing low. SHORT when K below D AND both above 80 AND near swing high. SL 1.5x ATR, TP 2x ATR. ADX < 30. BTC 4h, ETH 4h.",
    "DonchianTurtleBreakout: 20-period Donchian Channel. LONG when close breaks above 20-period high. SHORT when below 20-period low. SL 2x ATR(10), TP 3x ATR or trail with 10-period channel. Size 0.95. BTC 1d.",
    "OBVDivergenceSignal: OBV divergence. Price new 20-period low but OBV does NOT: LONG (bullish divergence). Price new 20-period high but OBV does NOT: SHORT. RSI < 45 for longs, RSI > 55 for shorts. SL 2x ATR, TP 3x ATR. BTC 4h, META 4h.",
    "SupertrendFilter: Supertrend(7,3) as trend filter. LONG only above Supertrend line AND RSI(14) between 40-50 (pullback entry). SHORT below Supertrend AND RSI 50-60. SL at Supertrend line, TP 3x ATR. EMA(50) confirmation. BTC 1h, META 1h.",
    "CCIMeanReversion: CCI(20). LONG when CCI crosses above -100 from below (oversold recovery). SHORT when CCI crosses below +100. TP when CCI reaches 0 OR 3x ATR. ADX < 25 (ranging only). BTC 4h, ETH 4h.",
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
