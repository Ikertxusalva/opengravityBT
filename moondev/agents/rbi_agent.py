"""
rbi_agent v1 — pipeline Research → Backtest → Package → Debug.

Uso:
    python moondev/agents/rbi_agent.py

Lee ideas de moondev/data/ideas.txt (una por línea).
Salida en moondev/data/rbi/<fecha>/
"""
import sys
import re
import hashlib
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from moondev.core.model_factory import ModelFactory, clean_response, extract_code
import moondev.config as cfg
from rich.console import Console

console = Console()
TODAY = datetime.now().strftime("%m_%d_%Y")
RBI_DIR = cfg.DATA_DIR / "rbi" / TODAY
RBI_DIR.mkdir(parents=True, exist_ok=True)

# ─── Prompts ─────────────────────────────────────────────────────────────────

RESEARCH_PROMPT = """You are an expert quantitative trading strategy researcher.
Analyze the provided trading idea and create a detailed strategy specification.

Include:
1. Strategy name (2 words, unique, e.g. 'AdaptiveBreakout', 'FractalMomentum')
2. Entry conditions (specific indicator values, crossovers, patterns)
3. Exit conditions (TP, SL, indicator reversal)
4. Timeframe and asset class
5. Position sizing logic
6. Risk management rules

Be precise and technical. Avoid generic descriptions."""

BACKTEST_PROMPT = """You are an expert Python developer specializing in backtesting.py.

Convert the provided strategy specification into a complete, runnable backtesting.py class.

CRITICAL REQUIREMENTS:
- Import ONLY: backtesting, pandas_ta (no backtesting.lib)
- Data columns available: Open, High, Low, Close, Volume (capital letters)
- Position sizing: use self.buy(size=fraction) where 0 < fraction <= 1
  OR self.buy(size=int) for fixed shares — NEVER floats > 1
- Use self.data.Close[-1] to access last close
- NO .shift() on backtesting indicators — use plain slicing
- Use self.trades[-1].entry_price (NOT self.position.entry_price)
- crossover detection: prev < threshold and curr >= threshold (manual)

Output ONLY the Python code, no explanation."""

PACKAGE_PROMPT = """Review the provided backtesting.py code and fix any imports.

RULES:
- REMOVE any 'from backtesting.lib import ...' lines
- KEEP all other imports
- Replace crossover() calls with manual crossover detection:
  prev[-2] < threshold and prev[-1] >= threshold
- Output ONLY the corrected Python code."""

DEBUG_PROMPT = """Fix the following backtesting.py code error.

ERROR:
{error}

CODE:
{code}

CRITICAL RULES:
1. Fix ONLY the reported error — do not change strategy logic
2. Column names: Open, High, Low, Close, Volume (capital)
3. Position size: fraction (0-1) or positive integer, never float > 1
4. No backtesting.lib imports
5. self.trades[-1].entry_price for entry price (not self.position.entry_price)
6. If '0 trades': check size param, verify self.buy() is called in next()

Output ONLY the corrected Python code."""

# ─── Helpers ─────────────────────────────────────────────────────────────────

def read_ideas() -> list[str]:
    if not cfg.IDEAS_FILE.exists():
        return []
    return [l.strip() for l in cfg.IDEAS_FILE.read_text().splitlines() if l.strip()]


def idea_hash(idea: str) -> str:
    return hashlib.md5(idea.encode()).hexdigest()


def is_processed(idea: str) -> bool:
    log = RBI_DIR.parent / "processed.log"
    if not log.exists():
        return False
    return idea_hash(idea) in log.read_text()


def mark_processed(idea: str, name: str) -> None:
    log = RBI_DIR.parent / "processed.log"
    with open(log, "a") as f:
        f.write(f"{idea_hash(idea)},{datetime.now().isoformat()},{name}\n")


def write_code(code: str, name: str, stage: str) -> Path:
    folder = RBI_DIR / stage
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}.py"
    path.write_text(code, encoding="utf-8")
    return path


# ─── Pipeline stages ─────────────────────────────────────────────────────────

def research_strategy(idea: str, model) -> tuple[str, str]:
    """Retorna (strategy_name, research_text)"""
    resp = model.ask(RESEARCH_PROMPT, idea, max_tokens=1000)
    research = clean_response(resp.content)
    # Extraer nombre: primera línea que contenga palabras capitalizadas
    name_match = re.search(r"\b([A-Z][a-z]+[A-Z][a-zA-Z]+)\b", research)
    name = name_match.group(1) if name_match else "UnknownStrategy"
    return name, research


def create_backtest(research: str, model) -> str:
    resp = model.ask(BACKTEST_PROMPT, research, max_tokens=2000)
    return extract_code(clean_response(resp.content))


def package_fix(code: str, model) -> str:
    resp = model.ask(PACKAGE_PROMPT, code, max_tokens=2000)
    return extract_code(clean_response(resp.content))


def debug_fix(code: str, error: str, model) -> str:
    prompt = DEBUG_PROMPT.format(error=error[:1000], code=code)
    resp = model.ask(prompt, "", max_tokens=2000)
    return extract_code(clean_response(resp.content))


# ─── Main ────────────────────────────────────────────────────────────────────

def process_idea(idea: str, model) -> None:
    console.rule(f"[bold cyan]Procesando idea")
    console.print(f"[dim]{idea[:120]}[/dim]")

    name, research = research_strategy(idea, model)
    console.print(f"[green]Estrategia:[/green] {name}")
    (RBI_DIR / "research").mkdir(exist_ok=True)
    (RBI_DIR / "research" / f"{name}.txt").write_text(research, encoding="utf-8")

    code = create_backtest(research, model)
    write_code(code, name, "backtests")

    code = package_fix(code, model)
    write_code(code, name, "backtests_package")

    console.print(f"[green]✓[/green] {name} — guardado en {RBI_DIR}")
    mark_processed(idea, name)


def main():
    model = ModelFactory().get()
    console.print(f"[bold]rbi_agent v1[/bold] | modelo: {model.name}")

    ideas = read_ideas()
    if not ideas:
        console.print("[yellow]No hay ideas en ideas.txt. Ejecuta research_agent.py primero.[/yellow]")
        return

    for idea in ideas:
        if is_processed(idea):
            console.print(f"[dim]Saltando (ya procesada): {idea[:60]}[/dim]")
            continue
        process_idea(idea, model)


if __name__ == "__main__":
    main()
