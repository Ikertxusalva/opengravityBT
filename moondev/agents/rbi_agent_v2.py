"""
rbi_agent v2 — v1 + execution loop con subprocess + debug automático.

Ejecuta el código generado, captura errores, los repara en loop (10x).
Detecta caso especial: 0 trades (strategy corre pero sin signals).

Uso:
    python moondev/agents/rbi_agent_v2.py
"""
import sys
import subprocess
import json
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Reutilizar helpers de v1
from moondev.agents.rbi_agent import (
    research_strategy, create_backtest, package_fix, debug_fix,
    read_ideas, is_processed, mark_processed, write_code, console,
    RBI_DIR, DEBUG_PROMPT, PACKAGE_PROMPT
)
from moondev.core.model_factory import ModelFactory, extract_code, clean_response
import moondev.config as cfg

EXEC_DIR = RBI_DIR / "backtests_final"
EXEC_DIR.mkdir(parents=True, exist_ok=True)

NO_TRADES_HINT = """
IMPORTANT: The strategy runs without errors but generates 0 trades.
This usually means:
1. Position size is invalid (use fraction 0-1 OR positive integer)
2. self.buy() / self.sell() is never reached (check conditions)
3. Cash is insufficient for the order size
4. Entry condition is never True in the data period

Fix the strategy logic so it generates at least some trades.
"""


def execute_backtest(path: Path) -> dict:
    """Ejecuta el archivo Python y captura stdout/stderr."""
    start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "elapsed": time.time() - start,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": "TIMEOUT (5min)", "elapsed": 300}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e), "elapsed": 0}


def has_zero_trades(result: dict) -> bool:
    if not result["success"]:
        return False
    stdout = result["stdout"]
    indicators = [
        "# Trades                                     0",
        "Win Rate [%]                               NaN",
    ]
    return sum(1 for ind in indicators if ind in stdout) >= 1


def save_result(result: dict, path: Path) -> None:
    out = path.with_suffix(".json")
    with open(out, "w") as f:
        json.dump({
            "file": str(path),
            "success": result["success"],
            "stdout": result["stdout"][:3000],
            "stderr": result["stderr"][:1000],
            "elapsed": result["elapsed"],
        }, f, indent=2)


def process_idea_v2(idea: str, model) -> None:
    console.rule("[bold cyan]rbi_agent v2")
    console.print(f"[dim]{idea[:120]}[/dim]")

    name, research = research_strategy(idea, model)
    console.print(f"[green]Estrategia:[/green] {name}")

    code = create_backtest(research, model)
    code = package_fix(code, model)

    # Añadir bloque de ejecución al final si no existe
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

    path = write_code(code, name, "backtests_final")

    for attempt in range(1, cfg.MAX_DEBUG_ITERATIONS + 1):
        console.print(f"[cyan]Intento {attempt}/{cfg.MAX_DEBUG_ITERATIONS}[/cyan]", end=" ")
        result = execute_backtest(path)

        if result["success"] and not has_zero_trades(result):
            console.print("[bold green]✓ Éxito[/bold green]")
            save_result(result, path)
            console.print(result["stdout"][:500])
            mark_processed(idea, name)
            return

        if has_zero_trades(result):
            console.print("[yellow]0 trades detectados[/yellow]")
            error = NO_TRADES_HINT
        else:
            console.print(f"[red]Error[/red]")
            error = result["stderr"][-800:]

        code = debug_fix(code, error, model)
        code = package_fix(code, model)
        if "if __name__" not in code:
            code += run_block
        path = write_code(code, name, "backtests_final")

    console.print(f"[red]✗ Fallido tras {cfg.MAX_DEBUG_ITERATIONS} intentos[/red]")


def main():
    model = ModelFactory().get()
    console.print(f"[bold]rbi_agent v2[/bold] | modelo: {model.name}")

    for idea in read_ideas():
        if is_processed(idea):
            continue
        process_idea_v2(idea, model)


if __name__ == "__main__":
    main()
