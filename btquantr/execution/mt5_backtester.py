"""btquantr/execution/mt5_backtester.py — Automatiza backtests en MT5 desde Python.

Flujo:
    1. generate_ini()  → crea archivo .ini para MT5 Strategy Tester
    2. run_backtest()  → mata MT5, ejecuta terminal64.exe /config:<ini>, espera
    3. parse_report()  → parsea el reporte HTML generado por MT5
    4. run_all()       → itera todos los EAs en exports/mt5/ y genera tabla Rich
    5. optimize()      → grid search sobre TP/SL, devuelve mejor combinación

Correcciones v2 (2026-03-10):
    - Visualization=0 en el INI (clave real de MT5, no "Visual")
    - Report=<ea_name> sin ruta — MT5 guarda <data_dir>/<ea_name>.htm
    - _kill_mt5(): taskkill /F antes de cada run (MT5 ya abierto → ignoraba /config)
    - detect_mt5_data_dir(): mapea exe → data dir vía origin.txt
    - _mt5_experts_dir: auto-detecta carpeta MQL5/Experts del terminal
    - parse_report(): soporta etiquetas en español e inglés
"""
from __future__ import annotations

import configparser
import itertools
import logging
import re
import subprocess
import time
from datetime import date
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("BTQUANTRmt5bt")

# Mapeo de modelos de simulación → código MT5
_MODEL_MAP: dict[str, str] = {
    "EVERY_TICK":      "0",
    "OHLC1":           "1",  # OHLC on M1 (fast, default)
    "OPEN_PRICES":     "2",
    "MATH_CALC":       "3",
    "EVERY_TICK_REAL": "4",
}

# Base MetaQuotes data dir (Windows)
_METATRADER_BASE = (
    Path.home() / "AppData" / "Roaming" / "MetaQuotes" / "Terminal"
)

# ─────────────────────────────────────────────────────────────────────────────
# Symbol extraction — parsea el símbolo MT5 del nombre del EA
# ─────────────────────────────────────────────────────────────────────────────

# Regímenes HMM (usado para detectar el sufijo del nombre)
_EA_REGIMES = {"BULL", "BEAR", "SIDEWAYS"}

# Aliases de símbolo → nombre MT5 canónico
_SYMBOL_ALIASES: dict[str, str] = {
    "GOLD":   "XAUUSD",
    "GLD":    "XAUUSD",
    "XAUUSD": "XAUUSD",
    "SILVER": "XAGUSD",
    "XAGUSD": "XAGUSD",
    "CL":     "USOIL",
    "SPY":    "SP500m",
    "XYZ100": "SP500m",
}


def extract_symbol_from_ea_name(ea_name: str) -> str:
    """Extrae el símbolo MT5 del nombre del EA.

    Formato esperado: {strategy_parts}_{SYMBOL}_{REGIME}
    o con prefijo xyz:  {strategy_parts}_xyz_{SYMBOL}_{REGIME}

    Reglas de mapeo:
      - USDT pairs → strip 'USDT': BTCUSDT → BTC, ETHUSDT → ETH
      - GOLD / GLD  → XAUUSD
      - CL          → USOIL
      - SPY / XYZ100 → SP500m
      - Resto       → se devuelve tal cual (AAPL, NVDA, EURUSD…)

    Examples:
        >>> extract_symbol_from_ea_name("SW_SEED_BTCUSDT_SIDEWAYS")
        'BTC'
        >>> extract_symbol_from_ea_name("BREAKOUT_0187_m0019_xyz_GOLD_BULL")
        'XAUUSD'
        >>> extract_symbol_from_ea_name("MACDCrossover_mut16_GLD_BULL")
        'XAUUSD'
        >>> extract_symbol_from_ea_name("BREAKOUT_0119_m0012_m0009_m0015_m0041_xyz_CL_BULL")
        'USOIL'
        >>> extract_symbol_from_ea_name("EURUSD_BEAR")
        'EURUSD'
    """
    parts = ea_name.split("_")

    # Encuentra el índice del régimen (BULL/BEAR/SIDEWAYS) desde la derecha
    regime_idx: Optional[int] = None
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].upper() in _EA_REGIMES:
            regime_idx = i
            break

    if regime_idx is None or regime_idx == 0:
        # No se encontró régimen — devuelve "EURUSD" como fallback seguro
        return "EURUSD"

    raw = parts[regime_idx - 1].upper()

    # Alias directos (GOLD, GLD, CL, SPY, XYZ100…)
    if raw in _SYMBOL_ALIASES:
        return _SYMBOL_ALIASES[raw]

    # USDT pairs → base asset (BTCUSDT → BTC, ETHUSDT → ETH…)
    if raw.endswith("USDT"):
        return raw[:-4]  # strip 'USDT'

    return raw


class MT5Backtester:
    """Automatiza backtests en MetaTrader 5 desde Python.

    Uso básico:
        bt = MT5Backtester()
        ini = bt.generate_ini("SW_SEED_BTCUSDT_SIDEWAYS", "BTCUSDT", "H1",
                              date(2024,1,1), date(2024,12,31), 10_000)
        bt.run_backtest(ini)        # mata MT5, arranca, espera, cierra
        report_html = bt._find_report("SW_SEED_BTCUSDT_SIDEWAYS")
        metrics = bt.parse_report(report_html)

    Uso completo:
        results = bt.run_all()      # todos los EAs en exports/mt5/
        best = bt.optimize("EURUSD_BEAR", "EURUSD", {"tp":[20,30,40], "sl":[15,20]})
    """

    _MT5_DEFAULT_PATHS: list[Path] = [
        Path("C:/Program Files/MetaTrader 5/terminal64.exe"),
        Path("C:/Program Files (x86)/MetaTrader 5/terminal64.exe"),
    ]

    def __init__(
        self,
        mt5_path: Optional[Path] = None,
        exports_dir: Optional[Path] = None,
        ini_dir: Optional[Path] = None,
        reports_dir: Optional[Path] = None,
        experts_dir: Optional[Path] = None,
    ) -> None:
        self.mt5_path = Path(mt5_path) if mt5_path else self.detect_mt5_path()
        self.exports_dir = Path(exports_dir) if exports_dir else Path("exports/mt5")
        self._ini_dir_override = Path(ini_dir) if ini_dir else None
        self._reports_dir = Path(reports_dir) if reports_dir else Path("exports/mt5/reports")
        self._experts_dir = Path(experts_dir) if experts_dir else None

    # ── ini_dir ────────────────────────────────────────────────────────────

    @property
    def _ini_dir(self) -> Path:
        if self._ini_dir_override:
            return self._ini_dir_override
        d = Path("exports/mt5/ini")
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── 1. generate_ini ───────────────────────────────────────────────────

    def generate_ini(
        self,
        ea_name: str,
        symbol: str,
        timeframe: str,
        date_from: date,
        date_to: date,
        deposit: int,
        modeling: str = "OHLC1",
        leverage: int = 50,
        output_path: Optional[Path] = None,
    ) -> Path:
        """Genera un archivo .ini para el Strategy Tester de MT5 (modo batch).

        El reporte se guarda en <mt5_data_dir>/<ea_name>.htm (Report= sin ruta).
        Usa Visualization=0 para forzar modo no-visual (batch automático).

        Args:
            ea_name:     Nombre del EA (coincide con .ex5 en MQL5/Experts/)
            symbol:      Símbolo (ej. "EURUSD", "BTCUSDT")
            timeframe:   Periodo ("M1", "H1", "H4", "D1", etc.)
            date_from:   Fecha inicio
            date_to:     Fecha fin
            deposit:     Depósito inicial en USD
            modeling:    OHLC1 (default), EVERY_TICK, OPEN_PRICES, MATH_CALC
            leverage:    Apalancamiento (default 50 → 1:50)
            output_path: Ruta de salida; si None → ini_dir/<ea_name>.ini

        Returns:
            Path al archivo .ini generado.
        """
        model_code = _MODEL_MAP.get(modeling.upper(), "1")

        cfg = configparser.ConfigParser()
        cfg.optionxform = str  # preservar mayúsculas (MT5 las requiere)

        # FIX: Report= debe ser solo nombre (sin ruta) → MT5 guarda en <data_dir>/<ea_name>.htm
        # Con ruta absoluta, MT5 ignora la clave silenciosamente.
        cfg["Tester"] = {
            "Expert":           ea_name,
            "Symbol":           symbol,
            "Period":           timeframe,
            "FromDate":         date_from.strftime("%Y.%m.%d"),
            "ToDate":           date_to.strftime("%Y.%m.%d"),
            "Model":            model_code,
            "Deposit":          str(deposit),
            "Leverage":         f"1:{leverage}",
            "Currency":         "USD",
            "Report":           ea_name,       # FIX: solo nombre → data_dir/<ea_name>.htm
            "Visualization":    "0",           # FIX: batch mode (clave real; "Visual" se ignora)
            "ReplaceReport":    "1",           # sobreescribir si ya existe
            "ShutdownTerminal": "1",
        }

        out = Path(output_path) if output_path else self._ini_dir / f"{ea_name}.ini"
        out.parent.mkdir(parents=True, exist_ok=True)

        with out.open("w", encoding="utf-8") as fh:
            cfg.write(fh)

        log.debug("INI generado: %s", out)
        return out

    # ── 2. _kill_mt5 ──────────────────────────────────────────────────────

    def _kill_mt5(self) -> bool:
        """Mata todos los procesos terminal64.exe en ejecución.

        MT5 ignora /config si ya hay una instancia corriendo. Este método
        debe llamarse antes de run_backtest() para garantizar arranque limpio.

        Returns:
            True  — se mató al menos un proceso
            False — no había ningún proceso running (o taskkill falló)
        """
        result = subprocess.run(
            ["taskkill", "/F", "/IM", "terminal64.exe"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log.debug("_kill_mt5: sin procesos MT5 activos")
            return False

        # Esperar a que el proceso desaparezca completamente
        for _ in range(20):  # hasta 10 segundos
            check = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq terminal64.exe"],
                capture_output=True,
                text=True,
            )
            if "terminal64.exe" not in check.stdout.lower():
                break
            time.sleep(0.5)

        log.info("_kill_mt5: MT5 cerrado")
        return True

    # ── 3. run_backtest ───────────────────────────────────────────────────

    def run_backtest(self, ini_path: Path) -> int:
        """Ejecuta MT5 en modo backtest con la configuración dada.

        Antes de lanzar, mata cualquier instancia de MT5 abierta para
        garantizar que /config sea procesado correctamente.

        Args:
            ini_path: Ruta al archivo .ini generado por generate_ini()

        Returns:
            Código de retorno del proceso (0 = éxito)

        Raises:
            FileNotFoundError: Si ini_path no existe.
            ValueError: Si mt5_path no está configurado.
        """
        ini_path = Path(ini_path)
        if not ini_path.exists():
            raise FileNotFoundError(f"INI no encontrado: {ini_path}")

        if self.mt5_path is None:
            raise ValueError(
                "mt5_path no configurado. Pasa la ruta al terminal64.exe o instala MT5."
            )

        # FIX: matar MT5 antes para que /config sea procesado
        self._kill_mt5()

        cmd = [str(self.mt5_path), f"/config:{ini_path}", "/shutdown"]
        log.info("Ejecutando backtest: %s", " ".join(cmd))

        result = subprocess.run(cmd, check=False)
        return result.returncode

    # ── 4. parse_report ───────────────────────────────────────────────────

    def parse_report(self, html_path: Path) -> dict[str, Any]:
        """Parsea el reporte HTML generado por MT5 Strategy Tester.

        Args:
            html_path: Ruta al archivo .html del reporte.

        Returns:
            dict con claves: net_profit, profit_factor, total_trades,
            drawdown_pct, win_rate, sharpe (puede ser None si no está en el HTML).

        Raises:
            FileNotFoundError: Si html_path no existe.
        """
        html_path = Path(html_path)
        if not html_path.exists():
            raise FileNotFoundError(f"Reporte HTML no encontrado: {html_path}")

        # MT5 puede generar el reporte en inglés o en el idioma del terminal (ej. español).
        # El encoding depende del build: detectar por BOM.
        raw = html_path.read_bytes()
        if raw[:2] == b"\xff\xfe":                        # UTF-16-LE BOM
            content = raw[2:].decode("utf-16-le", errors="replace")
        elif raw[:3] == b"\xef\xbb\xbf":                  # UTF-8 BOM
            content = raw[3:].decode("utf-8", errors="replace")
        else:
            content = raw.decode("utf-8", errors="replace")

        def _find(*labels: str) -> Optional[str]:
            """Busca el valor en la celda siguiente a cualquiera de los labels dados.
            Soporta etiquetas con o sin ':' al final (inglés/español de MT5).
            """
            for label in labels:
                pattern = rf"<td[^>]*>\s*{re.escape(label)}:?\s*</td>\s*<td[^>]*>(.*?)</td>"
                m = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
                if m:
                    return re.sub(r"<[^>]+>", "", m.group(1)).strip()
            return None

        def _float(val: Optional[str]) -> Optional[float]:
            if val is None:
                return None
            m = re.search(r"-?\d[\d ]*[.,]?\d*", val)
            if not m:
                return None
            return float(m.group().replace(" ", "").replace(",", ".").replace("..", "."))

        # Etiquetas en inglés + español (MT5 adapta al idioma del terminal)
        net_profit_raw    = _find("Total Net Profit",                  "Beneficio Neto")
        profit_factor_raw = _find("Profit Factor",                     "Factor de Beneficio")
        total_trades_raw  = _find("Total Trades",                      "Total de operaciones ejecutadas")
        dd_raw            = _find("Maximal Drawdown",                  "Reducci\u00f3n m\u00e1xima del balance")
        short_raw         = _find("Short Trades (won %)",              "Posiciones cortas (% rentables)")
        long_raw          = _find("Long Trades (won %)",               "Posiciones largas (% rentables)")
        sharpe_raw        = _find("Sharpe Ratio",                      "Ratio de Sharpe")

        # Drawdown: "567.89 (5.68%)" → extraer porcentaje
        drawdown_pct: Optional[float] = None
        if dd_raw:
            pct_m = re.search(r"\((\d+\.?\d*)%\)", dd_raw)
            if pct_m:
                drawdown_pct = float(pct_m.group(1))

        def _extract_pct(raw: Optional[str]) -> Optional[float]:
            if raw is None:
                return None
            m = re.search(r"\((\d+\.?\d*)%\)", raw)
            return float(m.group(1)) if m else None

        short_pct = _extract_pct(short_raw)
        long_pct  = _extract_pct(long_raw)
        win_rate: Optional[float] = None
        if short_pct is not None and long_pct is not None:
            win_rate = (short_pct + long_pct) / 2.0
        elif short_pct is not None:
            win_rate = short_pct
        elif long_pct is not None:
            win_rate = long_pct

        total_trades = int(_float(total_trades_raw)) if total_trades_raw else None

        return {
            "net_profit":    _float(net_profit_raw),
            "profit_factor": _float(profit_factor_raw),
            "total_trades":  total_trades,
            "drawdown_pct":  drawdown_pct,
            "win_rate":      win_rate,
            "sharpe":        _float(sharpe_raw),
        }

    # ── 5. _find_report ───────────────────────────────────────────────────

    def _find_report(self, ea_name: str) -> Optional[Path]:
        """Busca el reporte HTML generado por MT5 para un EA dado.

        MT5 guarda Report=<ea_name> como <data_dir>/<ea_name>.htm (sin subdirectorio).
        """
        # 1. Ruta canónica: data_dir/<ea_name>.htm (donde MT5 realmente escribe)
        if self.mt5_path:
            data_dir = self.detect_mt5_data_dir(self.mt5_path)
            if data_dir:
                for ext in (".htm", ".html"):
                    p = data_dir / f"{ea_name}{ext}"
                    if p.exists():
                        return p

        # 2. Ruta directa en reports_dir (compat. con rutas explícitas o copias)
        for ext in (".html", ".htm"):
            direct = self._reports_dir / f"{ea_name}{ext}"
            if direct.exists():
                return direct

        # 3. Glob en reports_dir
        for p in self._reports_dir.glob(f"*{ea_name}*.html"):
            return p
        for p in self._reports_dir.glob(f"*{ea_name}*.htm"):
            return p

        # 4. Fallback: exports_dir
        for p in self.exports_dir.glob(f"*{ea_name}*.html"):
            return p
        for p in self.exports_dir.glob(f"*{ea_name}*.htm"):
            return p

        return None

    # ── 6. check_compiled ─────────────────────────────────────────────────

    def check_compiled(self, ea_name: str) -> Optional[bool]:
        """Comprueba si el EA tiene binario .ex5 en la carpeta de Experts.

        Usa _mt5_experts_dir (auto-detectado o explícito).

        Returns:
            True  — .ex5 encontrado
            False — directorio configurado pero .ex5 ausente
            None  — no se puede determinar (sin experts_dir)
        """
        experts = self._mt5_experts_dir
        if experts is None:
            return None
        return (experts / f"{ea_name}.ex5").exists()

    # ── 7. _mt5_experts_dir ───────────────────────────────────────────────

    @property
    def _mt5_experts_dir(self) -> Optional[Path]:
        """Ruta a MQL5/Experts/ del terminal activo.

        Orden de búsqueda:
        1. experts_dir pasado al constructor
        2. Auto-detectado via detect_mt5_data_dir() → MQL5/Experts/
        """
        if self._experts_dir is not None:
            return self._experts_dir
        if self.mt5_path is None:
            return None
        data_dir = self.detect_mt5_data_dir(self.mt5_path)
        if data_dir is None:
            return None
        experts = data_dir / "MQL5" / "Experts"
        return experts if experts.exists() else experts  # devolver siempre para que check_compiled funcione

    # ── 8. run_all ────────────────────────────────────────────────────────

    def run_all(
        self,
        symbol: str = "EURUSD",
        timeframe: str = "H1",
        date_from: date = date(2024, 1, 1),
        date_to: date = date(2024, 12, 31),
        deposit: int = 10_000,
    ) -> list[dict[str, Any]]:
        """Ejecuta backtest para todos los EAs en exports_dir y devuelve resultados."""
        ea_files = list(self.exports_dir.glob("*.mq5"))
        results: list[dict[str, Any]] = []

        for ea_file in ea_files:
            ea_name = ea_file.stem
            log.info("Backtesting %s ...", ea_name)

            try:
                compiled = self.check_compiled(ea_name)
                if compiled is False:
                    log.warning("EA no compilado: %s (falta .ex5)", ea_name)
                    results.append({"ea_name": ea_name, "status": "not_compiled"})
                    continue

                # Extraer símbolo del nombre del EA (ignora el parámetro symbol default)
                ea_symbol = extract_symbol_from_ea_name(ea_name)
                ini = self.generate_ini(
                    ea_name, ea_symbol, timeframe, date_from, date_to, deposit
                )
                rc = self.run_backtest(ini)

                if rc != 0:
                    results.append({"ea_name": ea_name, "status": "error",
                                    "returncode": rc})
                    continue

                report_path = self._find_report(ea_name)
                if report_path is None:
                    results.append({"ea_name": ea_name, "status": "no_report"})
                    continue

                metrics = self.parse_report(report_path)
                metrics["ea_name"] = ea_name
                metrics["status"] = "ok"
                results.append(metrics)

            except Exception as exc:
                log.warning("Error en %s: %s", ea_name, exc)
                results.append({"ea_name": ea_name, "status": "error",
                                 "error": str(exc)})

        return results

    # ── 9. optimize ───────────────────────────────────────────────────────

    def optimize(
        self,
        ea_name: str,
        symbol: str,
        param_ranges: dict[str, list],
        timeframe: str = "H1",
        date_from: date = date(2024, 1, 1),
        date_to: date = date(2024, 12, 31),
        deposit: int = 10_000,
        metric: str = "sharpe",
    ) -> dict[str, Any]:
        """Grid search sobre param_ranges, devuelve la mejor combinación por metric."""
        param_names = list(param_ranges.keys())
        param_values = list(param_ranges.values())

        best_score = float("-inf")
        best: dict[str, Any] = {}

        for combo in itertools.product(*param_values):
            params = dict(zip(param_names, combo))
            combo_ea = f"{ea_name}_tp{params.get('tp', '')}_sl{params.get('sl', '')}"

            ini = self.generate_ini(
                combo_ea, symbol, timeframe, date_from, date_to, deposit
            )
            rc = self.run_backtest(ini)
            if rc != 0:
                continue

            report_path = self._find_report(combo_ea) or self._find_report(ea_name)
            if report_path is None:
                continue

            metrics = self.parse_report(report_path)
            score = metrics.get(metric) or float("-inf")

            if score > best_score:
                best_score = score
                best = {**params, **metrics}

        return best

    # ── 10. detect_mt5_path ───────────────────────────────────────────────

    @classmethod
    def detect_mt5_path(cls) -> Optional[Path]:
        """Detecta terminal64.exe en rutas default de Windows."""
        for p in cls._MT5_DEFAULT_PATHS:
            if p.exists():
                return p
        return None

    # ── 11. detect_mt5_data_dir ───────────────────────────────────────────

    @classmethod
    def detect_mt5_data_dir(
        cls,
        mt5_path: Path,
        metatrader_base: Optional[Path] = None,
    ) -> Optional[Path]:
        """Mapea un terminal64.exe a su carpeta de datos vía origin.txt.

        MT5 almacena sus datos de usuario en:
            %APPDATA%/MetaQuotes/Terminal/<ID>/

        Cada carpeta tiene un origin.txt (UTF-16-LE) con la ruta del instalador.
        Comparamos con el directorio padre de mt5_path para encontrar la match.

        Args:
            mt5_path:        Ruta al terminal64.exe
            metatrader_base: Override para tests; default = %APPDATA%/MetaQuotes/Terminal

        Returns:
            Path a la carpeta de datos o None si no se encuentra.
        """
        base = metatrader_base or _METATRADER_BASE
        if not base.exists():
            return None

        mt5_dir = str(Path(mt5_path).parent).lower()

        for entry in base.iterdir():
            if not entry.is_dir():
                continue
            origin = entry / "origin.txt"
            if not origin.exists():
                continue
            try:
                content = origin.read_bytes().decode("utf-16-le", errors="replace").strip()
                if mt5_dir in content.lower():
                    return entry
            except Exception:
                continue

        return None
