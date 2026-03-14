"""
Copy Trading Daemon — OpenGravity
==================================
Proceso independiente que ejecuta el ciclo de copy trading automáticamente.
Corre en background sin necesitar la app Electron abierta.

Intervalos:
  - Full cycle (discover + copy + discard): cada 4h
  - Log de estado: cada ciclo

Uso:
  python copy_daemon.py          # correr en foreground (con logs)
  pythonw copy_daemon.py         # correr en background (sin ventana)

Para instalar como tarea de Windows (ejecutar una vez como admin):
  python copy_daemon.py --install
  python copy_daemon.py --uninstall
  python copy_daemon.py --status
"""

import sys
import time
import subprocess
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
LOG_FILE = DATA_DIR / "copy_daemon.log"
PID_FILE = DATA_DIR / "copy_daemon.pid"
TRACKER_SCRIPT = SCRIPT_DIR / "wallet_tracker.py"

DATA_DIR.mkdir(exist_ok=True)

# ── Intervalos ─────────────────────────────────────────────────────────────────
CYCLE_INTERVAL_HOURS = 4
CYCLE_INTERVAL_SECS = CYCLE_INTERVAL_HOURS * 3600

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DAEMON] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("copy_daemon")


# ── Task Scheduler ─────────────────────────────────────────────────────────────

TASK_NAME = "OpenGravityCopyDaemon"


def _get_python_exe() -> str:
    """Obtener ruta a pythonw.exe (sin ventana) o python.exe."""
    py = Path(sys.executable)
    pythonw = py.parent / "pythonw.exe"
    return str(pythonw) if pythonw.exists() else str(py)


def install_task():
    """Registrar en Windows Task Scheduler para ejecutar al inicio de sesión."""
    python_exe = _get_python_exe()
    script_path = str(Path(__file__).resolve())

    cmd = [
        "schtasks", "/create",
        "/tn", TASK_NAME,
        "/tr", f'"{python_exe}" "{script_path}"',
        "/sc", "ONLOGON",
        "/rl", "HIGHEST",
        "/f",  # Overwrite si ya existe
        "/delay", "0002:00",  # Esperar 2 min después de login
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"[OK] Tarea '{TASK_NAME}' instalada — se ejecutará al iniciar sesión.")
        print(f"     Python: {python_exe}")
        print(f"     Script: {script_path}")
        print(f"     Log:    {LOG_FILE}")
    else:
        print(f"[ERROR] No se pudo instalar la tarea:")
        print(result.stderr or result.stdout)
        print("\nIntenta ejecutar como Administrador.")


def uninstall_task():
    """Eliminar la tarea del Task Scheduler."""
    result = subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"[OK] Tarea '{TASK_NAME}' eliminada.")
    else:
        print(f"[WARN] {result.stderr or result.stdout}")


def status_task():
    """Ver estado de la tarea en Task Scheduler."""
    result = subprocess.run(
        ["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(result.stdout)
    else:
        print(f"[INFO] Tarea '{TASK_NAME}' no encontrada (no instalada).")

    # Mostrar últimas líneas del log
    if LOG_FILE.exists():
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        print(f"\n--- Últimas 20 líneas de {LOG_FILE} ---")
        for line in lines[-20:]:
            print(line)


# ── Ciclo principal ─────────────────────────────────────────────────────────────

def run_full_cycle() -> bool:
    """Ejecutar wallet_tracker.py full-cycle y retornar True si OK."""
    log.info("Iniciando full-cycle...")
    try:
        result = subprocess.run(
            [sys.executable, str(TRACKER_SCRIPT), "full-cycle"],
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            timeout=300,
            encoding="utf-8",
            errors="replace",
        )
        if result.stdout:
            for line in result.stdout.strip().splitlines():
                log.info(f"  {line}")
        if result.returncode != 0:
            log.error(f"full-cycle terminó con código {result.returncode}")
            if result.stderr:
                log.error(result.stderr[:500])
            return False
        log.info("full-cycle completado OK")
        return True
    except subprocess.TimeoutExpired:
        log.error("full-cycle excedió timeout (300s)")
        return False
    except Exception as e:
        log.error(f"Error ejecutando full-cycle: {e}")
        return False


def save_pid():
    """Guardar PID del proceso actual."""
    import os
    PID_FILE.write_text(str(os.getpid()))


def run_daemon():
    """Loop principal del daemon."""
    save_pid()
    log.info(f"=== Copy Daemon iniciado ===")
    log.info(f"  Ciclo cada {CYCLE_INTERVAL_HOURS}h")
    log.info(f"  Script: {TRACKER_SCRIPT}")
    log.info(f"  Log: {LOG_FILE}")

    # Primer ciclo inmediato al arrancar
    run_full_cycle()
    last_cycle = time.monotonic()

    while True:
        elapsed = time.monotonic() - last_cycle
        remaining = CYCLE_INTERVAL_SECS - elapsed

        if remaining > 0:
            # Dormir en bloques de 60s para poder ver logs de actividad
            sleep_secs = min(60, remaining)
            time.sleep(sleep_secs)
        else:
            log.info(f"--- Ciclo programado ({CYCLE_INTERVAL_HOURS}h) ---")
            run_full_cycle()
            last_cycle = time.monotonic()


# ── Entrypoint ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Copy Trading Daemon — OpenGravity")
    parser.add_argument("--install", action="store_true",
                        help="Instalar en Windows Task Scheduler (ejecutar al login)")
    parser.add_argument("--uninstall", action="store_true",
                        help="Desinstalar del Task Scheduler")
    parser.add_argument("--status", action="store_true",
                        help="Ver estado de la tarea y últimas líneas del log")
    parser.add_argument("--run-once", action="store_true",
                        help="Ejecutar un solo ciclo y salir")
    args = parser.parse_args()

    if args.install:
        install_task()
    elif args.uninstall:
        uninstall_task()
    elif args.status:
        status_task()
    elif args.run_once:
        run_full_cycle()
    else:
        run_daemon()


if __name__ == "__main__":
    main()
