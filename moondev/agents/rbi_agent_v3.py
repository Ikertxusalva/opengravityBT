"""
rbi_agent v3 — v2 + optimization loop hasta TARGET_RETURN.

Si el retorno < TARGET_RETURN%, el LLM mejora la estrategia y reejecutua.
La mejor versión se guarda como _WORKING.py

Uso:
    python moondev/agents/rbi_agent_v3.py
"""
import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Fix Windows cp1252 encoding issues with rich/unicode characters
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from moondev.agents.rbi_agent_v2 import (
    process_idea_v2, execute_backtest, has_zero_trades,
    save_result, write_code, EXEC_DIR
)
from moondev.agents.rbi_agent import (
    research_strategy, create_backtest, package_fix, debug_fix,
    read_ideas, is_processed, mark_processed, console
)
from moondev.core.model_factory import ModelFactory, extract_code, clean_response
import moondev.config as cfg

DRAWDOWN_KNOWLEDGE = """
=== DRAWDOWN REDUCTION TOOLKIT (Research 2026-03-01) ===

USE WHEN DD IS THE BOTTLENECK (DD > 20%, Calmar too low):

A. ATR POSITION SIZING — reduces DD 20-25%, may reduce return proportionally
   atr = self.data.df.ta.atr(length=14)
   stop_dist = atr.iloc[-1] * 2.5
   size = min((self.equity * 0.02) / (stop_dist * self.data.Close[-1]), 0.5)
   self.buy(size=size)
   ⚠ Do NOT set size < 0.05 — too small = negligible return

B. VOLATILITY-ADJUSTED STOPS — tighter SL/TP based on current volatility
   atr_val = self.atr[-1]
   sl = self.data.Close[-1] - 2.5 * atr_val
   tp = self.data.Close[-1] + 3.0 * atr_val   # RR 1.2 → keeps profit flowing
   self.buy(size=fraction, sl=sl, tp=tp)
   ⚠ TP multiplier < 2.0 kills return — keep >= 2.5

C. SMA200 REGIME FILTER — skip trades in wrong trend direction
   sma200 = self.data.Close.s.rolling(200).mean()
   if long_signal and self.data.Close[-1] < sma200[-1]: return
   ⚠ Too strict = 0 trades. Use only for clear trend strategies.

D. VOLATILITY CIRCUIT BREAKER — skip when market is chaotic
   atr14 = self.I(ta.atr, self.data.High, self.data.Low, self.data.Close, 14)
   if atr14[-1] > atr14[-84:].mean() * 2.0: return  # 2x threshold, not 1.5x
   ⚠ Threshold 1.5x = too sensitive, kills most trades. Use 1.8-2.5x.

DO NOT OVER-APPLY: applying all techniques together collapses return to near 0.
Pick ONE or TWO based on what the stats show.
"""

OPTIMIZE_PROMPT = DRAWDOWN_KNOWLEDGE + """
=== OPTIMIZATION TASK: MAXIMIZE CALMAR RATIO ===

GOAL: Calmar Ratio = Return / |Max Drawdown|  (higher = better balance)
- Calmar {target_calmar:.1f}+ = excellent (Return {target}% / DD 20%)
- Calmar 1.5+ = acceptable
- Calmar < 1.0 = poor risk/reward

Current snapshot:
  Return:  {current_return:.1f}%  (target: {target}%)
  DD:      {current_dd:.1f}%   (target: < 20%, hard limit: < 35%)
  Calmar:  {current_calmar:.2f}  (target: {target_calmar:.1f}+)
  Status:  {status}

DECISION TREE — apply exactly ONE change per iteration:

IF DD > 35%  (dangerous):
  → Apply technique A (ATR sizing) with 2% risk per trade
  → Also add technique B (ATR stops with TP >= 2.5x ATR)

ELIF DD > 20%  (high):
  → Apply technique A OR B, not both
  → Choose based on whether strategy is trend (B) or breakout (A)

ELIF return < {target}% and DD is fine:
  → Do NOT touch risk management
  → Instead: loosen entry filters, add momentum confirmation, widen TP
  → Increase position size slightly (within 2% risk rule)

ELIF Calmar < {target_calmar:.1f} but both metrics almost at target:
  → Fine-tune: adjust TP/SL ratio to improve RR (target RR 2.0-3.0)
  → Or loosen one overly-strict filter that's reducing trade frequency

NEVER do this:
  ✗ Set position size < 0.05 (no return)
  ✗ Apply 3+ DD techniques at once (kills trades)
  ✗ Add ADX > 40 or RSI > 70/< 30 filters to an already-filtered strategy
  ✗ Change strategy type (trend → mean reversion) mid-optimization

Current code:
{code}

Current stats:
{stats}

Output ONLY the improved Python code, no explanation."""


def parse_return(stdout: str) -> float:
    """Extrae 'Return [%]' del stdout de backtesting.py."""
    m = re.search(r"Return \[%\]\s+([\d\.\-]+)", stdout)
    return float(m.group(1)) if m else 0.0


def parse_drawdown(stdout: str) -> float:
    """Extrae 'Max. Drawdown [%]' del stdout de backtesting.py."""
    m = re.search(r"Max\. Drawdown \[%\]\s+([\d\.\-]+)", stdout)
    return float(m.group(1)) if m else 0.0


def calmar_score(ret: float, dd: float) -> float:
    """Calmar ratio = Return / |MaxDD|. Penaliza DD peligroso (> CAUTION).
    Balanza óptima: no prioriza ni retorno ni DD por separado."""
    dd_abs = abs(dd)
    if ret <= 0:
        return ret  # negativo → siempre peor
    if dd_abs < 1.0:
        return ret  # sin DD significativo, usar retorno directo
    calmar = ret / dd_abs
    # Penalización progresiva cuando DD supera zona de caución (35%)
    caution = abs(cfg.CAUTION_MAX_DD_PCT)
    if dd_abs > caution:
        excess = (dd_abs - caution) / caution  # 0..1+ según cuánto excede
        calmar *= max(0.2, 1.0 - excess)       # mín 20% del calmar base
    return calmar


DD_HINT_PROMPT = DRAWDOWN_KNOWLEDGE + """
=== OPTIMIZATION TASK: INTEGRATE PROVEN DD PARAMS ===

CONTEXT: An automated DD optimizer ran 48 parameter combinations on this strategy
and found the following configuration improves Calmar Ratio from {base_calmar:.2f}
to {opt_calmar:.2f} (+{improvement:.2f}). These are PROVEN — not guesses.

PROVEN PARAMETERS:
  dd_risk_pct      = {dd_risk_pct}    (% equity risked per trade for ATR sizing)
  dd_atr_sl_mult   = {dd_atr_sl_mult}   (ATR multiplier for stop loss distance)
  dd_atr_tp_mult   = {dd_atr_tp_mult}   (ATR multiplier for take profit distance)
  dd_regime_filter = {dd_regime_filter}  (True = skip trades when price < SMA200)
  dd_vol_mult      = {dd_vol_mult}    (volatility circuit breaker, 0 = off)

YOUR TASK: Rewrite the strategy to USE these exact parameters.

STEP-BY-STEP INSTRUCTIONS:
1. Add these as class-level attributes at the top of the class body.
2. In init(): add ATR-14 if not already present:
   self.atr14 = self.I(
       lambda h,l,c: ta.atr(pd.Series(h), pd.Series(l), pd.Series(c), 14).bfill().fillna(0).values,
       self.data.High, self.data.Low, self.data.Close)
3. If dd_regime_filter is True, add SMA200 in init():
   self.sma200 = self.I(
       lambda c: pd.Series(c).rolling(200).mean().bfill().fillna(0).values,
       self.data.Close)
4. In next(), at the TOP before any signal logic:
   a. Regime check (only if dd_regime_filter={dd_regime_filter}):
      if not self.position and self.data.Close[-1] < self.sma200[-1]: return
   b. Volatility circuit (only if dd_vol_mult={dd_vol_mult} > 0):
      hist = list(self.atr14[-84:]) if len(self.atr14) >= 84 else list(self.atr14)
      if self.atr14[-1] > (sum(hist)/len(hist)) * {dd_vol_mult}: return
5. Replace ALL self.buy(size=...) calls with ATR-based sizing:
   atr_val = float(self.atr14[-1])
   if atr_val > 0:
       stop_dist = atr_val * {dd_atr_sl_mult}
       size = min((self.equity * {dd_risk_pct}) / (stop_dist * self.data.Close[-1]), 0.5)
       sl = self.data.Close[-1] - atr_val * {dd_atr_sl_mult}
       tp = self.data.Close[-1] + atr_val * {dd_atr_tp_mult}
       self.buy(size=max(0.05, size), sl=sl, tp=tp)

CRITICAL: Keep ALL entry/exit signal logic untouched. Only modify sizing and stops.

Current code:
{code}

Current stats (pre-DD):
{stats}

Output ONLY the improved Python code, no explanation."""


def is_first_pass_viable(ret: float, dd: float) -> bool:
    """True si el attempt 1 ya es suficientemente bueno para saltar el DD probe."""
    target_calmar = cfg.TARGET_RETURN / abs(cfg.PASS_MAX_DD_PCT)
    score = calmar_score(ret, dd)
    dd_abs = abs(dd)
    # Viable si: Calmar ≥ 80% del target Y DD no supera 1.5x el límite PASS
    return score >= target_calmar * 0.8 and dd_abs <= abs(cfg.PASS_MAX_DD_PCT) * 1.5


def run_dd_probe(saved_path: "Path", class_name: str) -> "dict | None":
    """
    Carga la estrategia del attempt 1 y ejecuta dd_optimizer con BTC 1h 1y.
    Retorna dict con mejores params DD si la mejora de Calmar >= 0.3, else None.
    """
    from moondev.backtests.dd_optimizer import (
        load_strategy_class, run_baseline, run_dd_optimize, fetch_data,
    )
    try:
        cls  = load_strategy_class(str(saved_path), class_name)
        df   = fetch_data("BTC", "1h", "1y")
        if df is None or len(df) < 200:
            return None

        base = run_baseline(cls, df)
        if "error" in base:
            return None

        console.print(f"[dim]  DD probe: baseline Calmar={base['calmar']:.2f} — optimizando 48 combos...[/dim]")
        opt = run_dd_optimize(cls, df)

        if "error" in opt or "params" not in opt:
            return None

        improvement = opt["calmar"] - base["calmar"]
        if improvement < 0.3:
            console.print(f"[dim]  DD probe: mejora insuficiente ({improvement:+.2f}) — usando LLM generico[/dim]")
            return None

        return {
            "params":       opt["params"],
            "base_calmar":  base["calmar"],
            "opt_calmar":   opt["calmar"],
            "improvement":  improvement,
        }
    except Exception as e:
        console.print(f"[dim]  DD probe error: {str(e)[:80]}[/dim]")
        return None


def optimize_with_dd_hint(code: str, ret: float, dd: float, stats: str,
                           dd_probe: dict, model) -> str:
    """Integra los params DD exactos encontrados por el probe (más preciso que optimize genérico)."""
    p = dd_probe["params"]
    prompt = DD_HINT_PROMPT.format(
        base_calmar=dd_probe["base_calmar"],
        opt_calmar=dd_probe["opt_calmar"],
        improvement=dd_probe["improvement"],
        dd_risk_pct=p["dd_risk_pct"],
        dd_atr_sl_mult=p["dd_atr_sl_mult"],
        dd_atr_tp_mult=p["dd_atr_tp_mult"],
        dd_regime_filter=p["dd_regime_filter"],
        dd_vol_mult=p["dd_vol_mult"],
        code=code,
        stats=stats[:800],
    )
    resp = model.ask(prompt, "", max_tokens=3000)
    return extract_code(clean_response(resp.content))


def optimize(code: str, current_return: float, current_dd: float, stats: str, model) -> str:
    target_calmar = cfg.TARGET_RETURN / abs(cfg.PASS_MAX_DD_PCT)  # 50/20 = 2.5
    current_calmar = calmar_score(current_return, current_dd)
    dd_abs = abs(current_dd)

    if dd_abs > abs(cfg.CAUTION_MAX_DD_PCT):
        status = f"DANGER — DD={dd_abs:.1f}% far exceeds limit. Apply DD reduction first."
    elif dd_abs > abs(cfg.PASS_MAX_DD_PCT):
        status = f"HIGH DD={dd_abs:.1f}%. Apply ONE DD technique then re-evaluate."
    elif current_return < cfg.TARGET_RETURN:
        status = f"DD={dd_abs:.1f}% OK. Return={current_return:.1f}% too low. Improve return WITHOUT touching DD."
    else:
        status = f"Both metrics close to target. Fine-tune RR ratio or loosen one filter."

    prompt = OPTIMIZE_PROMPT.format(
        current_return=current_return,
        current_dd=current_dd,
        current_calmar=current_calmar,
        target_calmar=target_calmar,
        target=cfg.TARGET_RETURN,
        status=status,
        code=code,
        stats=stats[:800],
    )
    resp = model.ask(prompt, "", max_tokens=3000)
    return extract_code(clean_response(resp.content))


def process_idea_v3(idea: str, model) -> None:
    console.rule("[bold cyan]rbi_agent v3")
    console.print(f"[dim]{idea[:120]}[/dim]")

    name, research = research_strategy(idea, model)
    code = create_backtest(research, model)
    code = package_fix(code, model)

    run_block = f"""
if __name__ == "__main__":
    from backtesting import Backtest
    import yfinance as yf
    data = yf.download("BTC-USD", period="1y", interval="1h", auto_adjust=True)
    data.columns = ["Close", "High", "Low", "Open", "Volume"]
    data = data[["Open", "High", "Low", "Close", "Volume"]].dropna()
    bt = Backtest(data, {name}, cash=10_000, commission=0.001,
                  exclusive_orders=True, finalize_trades=True)
    stats = bt.run()
    print(stats)
"""
    if "if __name__" not in code:
        code += run_block

    best_score = -999.0
    best_return = -999.0
    best_dd = 0.0
    best_code = code
    best_stats = ""
    TARGET_MAX_DD = abs(cfg.PASS_MAX_DD_PCT)       # 20%
    HARD_DD_LIMIT = abs(cfg.CAUTION_MAX_DD_PCT)    # 35%
    TARGET_CALMAR = cfg.TARGET_RETURN / TARGET_MAX_DD  # 2.5

    for attempt in range(1, cfg.MAX_DEBUG_ITERATIONS + 1):
        path = write_code(code, f"{name}_v{attempt}", "backtests_final")
        result = execute_backtest(path)

        if result["success"] and not has_zero_trades(result):
            ret = parse_return(result["stdout"])
            dd = parse_drawdown(result["stdout"])
            score = calmar_score(ret, dd)

            # Color por zona de riesgo
            dd_abs = abs(dd)
            if dd_abs > HARD_DD_LIMIT:
                dd_color = "bold red"
            elif dd_abs > TARGET_MAX_DD:
                dd_color = "yellow"
            else:
                dd_color = "green"

            console.print(
                f"[cyan]v{attempt}[/cyan] "
                f"Return: [bold]{ret:.1f}%[/bold] | "
                f"DD: [{dd_color}]{dd:.1f}%[/{dd_color}] | "
                f"Calmar: [bold]{score:.2f}[/bold] (target {TARGET_CALMAR:.1f})"
            )

            # Guardar si mejora el Calmar (balance óptimo)
            if score > best_score:
                best_score = score
                best_return = ret
                best_dd = dd
                best_code = code
                best_stats = result["stdout"]

            # Criterio de parada: Calmar alcanzado O ambas métricas en zona PASS
            calmar_ok = score >= TARGET_CALMAR
            both_pass = (ret >= cfg.TARGET_RETURN and dd_abs <= TARGET_MAX_DD)
            if calmar_ok or both_pass:
                console.print(
                    f"[bold green]✓ Óptimo alcanzado: "
                    f"Return {ret:.1f}% | DD {dd:.1f}% | Calmar {score:.2f}[/bold green]"
                )
                break

            if attempt < cfg.MAX_OPTIMIZATION_ITERATIONS:
                console.print(
                    f"[yellow]Optimizando... "
                    f"(Calmar target {TARGET_CALMAR:.1f} | actual {score:.2f})[/yellow]"
                )
                # DD probe condicional: solo en attempt 1 si la estrategia no es viable
                dd_probe = None
                if attempt == 1 and not is_first_pass_viable(ret, dd):
                    console.print("[yellow]v1 no viable → DD probe (48 combos)...[/yellow]")
                    dd_probe = run_dd_probe(path, name)

                if dd_probe:
                    console.print(
                        f"[cyan]DD probe: +{dd_probe['improvement']:.2f} Calmar "
                        f"({dd_probe['base_calmar']:.2f} → {dd_probe['opt_calmar']:.2f}) "
                        f"→ integrando params exactos[/cyan]"
                    )
                    code = optimize_with_dd_hint(code, ret, dd, result["stdout"], dd_probe, model)
                else:
                    code = optimize(code, ret, dd, result["stdout"], model)
                code = package_fix(code, model)
                if "if __name__" not in code:
                    code += run_block
        else:
            error = result["stderr"][-600:] if not result["success"] else "0 trades"
            code = debug_fix(code, error, model)
            code = package_fix(code, model)
            if "if __name__" not in code:
                code += run_block

    # Guardar mejor versión (mayor Calmar encontrado)
    if best_return > -999:
        working_path = EXEC_DIR / f"{name}_WORKING.py"
        working_path.write_text(best_code, encoding="utf-8")
        dd_status = "✓" if abs(best_dd) <= TARGET_MAX_DD else ("⚠" if abs(best_dd) <= HARD_DD_LIMIT else "✗")
        console.print(
            f"[green]Mejor versión guardada: {working_path.name} | "
            f"Return: {best_return:.1f}% | DD: {best_dd:.1f}% {dd_status} | "
            f"Calmar: {best_score:.2f}[/green]"
        )
        mark_processed(idea, name)
    else:
        console.print(f"[red]✗ No se encontró versión funcional[/red]")


def main():
    model = ModelFactory().get()
    console.print(f"[bold]rbi_agent v3[/bold] | modelo: {model.name} | target: {cfg.TARGET_RETURN}%")

    for idea in read_ideas():
        if is_processed(idea):
            continue
        process_idea_v3(idea, model)


if __name__ == "__main__":
    main()
