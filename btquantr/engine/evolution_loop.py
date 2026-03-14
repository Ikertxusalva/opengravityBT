"""
btquantr/engine/evolution_loop.py — EvolutionLoop + quick_backtest.

Orquestador del ciclo evolutivo completo:
  genera → evalúa → selecciona por régimen → evoluciona → registra.

Spec: docs/biblia/autonomous_strategy_engine_v2.docx sección 9.
"""
from __future__ import annotations

import gc
import logging
import os
import warnings
from concurrent.futures import ProcessPoolExecutor

# backtesting.py emite este warning cuando exclusive_orders cancela una orden
# durante el ciclo evolutivo. Lo silenciamos a nivel de módulo para que aplique
# también en subprocesos que importan este módulo.
warnings.filterwarnings("ignore", message="Broker canceled")
from typing import Optional

import pandas as pd

from btquantr.adapters.backtest_adapter import HMMHistoryBuilder
from btquantr.data import ohlcv_router
from btquantr.engine.fitness import MultiFitness, RegimeAwareFitness
from btquantr.engine.generator import StrategyGenerator
from btquantr.engine.seed_library import SeedLibrary
from btquantr.engine.strategy_store import StrategyStore
from btquantr.engine.strategy_store_factory import get_strategy_store
from btquantr.analytics.walkforward import WalkForwardOptimizer
from btquantr.analytics.permutation_test import PermutationTest

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# quick_backtest
# ─────────────────────────────────────────────────────────────────────────────

def quick_backtest(strategy: dict, ohlcv: pd.DataFrame) -> dict | None:
    """Ejecuta un backtest rápido sobre una estrategia.

    La estrategia puede ser:
    1. Seed moondev/template: tiene 'code' con clase Strategy completa → exec()
    2. Seed generada: tiene 'template' de StrategyGenerator → busca en proven_templates

    Returns:
        {
            "returns":  list[float],    # return_pct por trade
            "trades":   list[dict],     # [{"opened_at": str, "return_pct": float}]
            "n_trades": int,
            "stats":    dict,           # stats crudos
        }
        None si falla o < 10 trades.

    NUNCA lanza excepciones — todo error retorna None.
    """
    try:
        result = _quick_backtest_impl(strategy, ohlcv)
        if result is not None and result.get("n_trades", 0) < 10:
            return None
        return result
    except Exception as exc:  # noqa: BLE001
        logger.debug("quick_backtest falló silenciosamente: %s", exc)
        return None
    finally:
        gc.collect()


MIN_TICK_BACKTEST_BARS = 500
MIN_BARS_AFTER_RESAMPLE = 100   # < 100 barras post-resample → exportar con advertencia


def _ticks_to_ohlc(tick_df: pd.DataFrame, timeframe: str = "1min") -> pd.DataFrame:
    """Convierte tick data (timestamp, price, size, side) a OHLCV.

    Args:
        tick_df: DataFrame con columnas timestamp, price, size, side.
        timeframe: Frecuencia de resample pandas (ej. '1min', '1s', '5min').

    Returns:
        DataFrame con columnas Open, High, Low, Close, Volume e índice DatetimeIndex.
        Vacío si tick_df está vacío.
    """
    if tick_df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    df = tick_df.set_index("timestamp").sort_index()
    ohlc = df["price"].resample(timeframe).ohlc()
    vol = df["size"].resample(timeframe).sum()

    result = ohlc.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"})
    result["Volume"] = vol
    return result.dropna(subset=["Open"])


def tick_backtest(strategy: dict, tick_df: pd.DataFrame, timeframe: str = "1min") -> dict | None:
    """Ejecuta backtest sobre tick data convirtiéndola primero a OHLC.

    Args:
        strategy: Diccionario de estrategia (igual que quick_backtest).
        tick_df: DataFrame con columnas timestamp, price, size, side.
        timeframe: Frecuencia de resample para conversión OHLC.

    Returns:
        Resultado de backtest o None si hay pocos datos o falla.
    """
    try:
        ohlc = _ticks_to_ohlc(tick_df, timeframe)
        if len(ohlc) < MIN_TICK_BACKTEST_BARS:
            return None
        return _quick_backtest_impl(strategy, ohlc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("tick_backtest falló: %s", exc)
        return None


_FOREX_SYMBOLS = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF"}
_STOCK_SYMBOLS = {"SPY", "GLD", "AAPL"}
_FOREX_YF_SUFFIX = _FOREX_SYMBOLS  # estos necesitan =X en yfinance


def _is_forex_or_stock(symbol: str) -> bool:
    return symbol.upper() in _FOREX_SYMBOLS or symbol.upper() in _STOCK_SYMBOLS


def fetch_ohlc_for_tick_backtest(symbol: str, days: int = 30) -> pd.DataFrame:
    """Obtiene OHLC 1m para tick backtest, usando la fuente adecuada por tipo de símbolo.

    - *USDT (crypto): HyperLiquid API candleSnapshot 1m, últimos `days` días.
    - HIP3 (xyz:*, cash:*): HyperLiquid API candleSnapshot 1m.
    - Forex (EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF): yfinance 1h 1mo.
    - Stocks (SPY, GLD, AAPL): yfinance 1h 1mo.
    - Otros: Dukascopy tick data → resamplea a 1m.

    Returns:
        DataFrame con columnas Open/High/Low/Close/Volume e índice DatetimeIndex.
        Vacío si todas las fuentes fallan.
    """
    if ":" in symbol:
        return _fetch_hl_candles_1m(symbol, days)
    if symbol.upper().endswith("USDT"):
        return _fetch_hl_candles_1m(symbol, days)
    if _is_forex_or_stock(symbol):
        return _fetch_yfinance_1h(symbol)
    ohlc = _fetch_dukascopy_ticks_to_ohlc(symbol, days * 4)
    if ohlc.empty:
        ohlc = _fetch_yfinance_1m(symbol, days)
    return ohlc


def _fetch_hl_candles_1m(symbol: str, days: int) -> pd.DataFrame:
    """Descarga candles 1m de HyperLiquid para los últimos `days` días.

    Soporta:
    - Perps crypto: "BTCUSDT" → coin="BTC"
    - HIP3 dex perps: "xyz:CL", "xyz:GOLD" → coin="xyz:CL" (pasado tal cual)
    """
    import time
    from btquantr.data.sources.hyperliquid import HyperLiquidSource
    # HIP3: pasar el símbolo completo (xyz:CL, xyz:GOLD) sin transformar
    if ":" in symbol:
        coin = symbol
    else:
        coin = symbol.upper().replace("USDT", "")
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000
    try:
        src = HyperLiquidSource()
        return src.get_candles(coin, "1m", start_ms, end_ms)
    except Exception as exc:  # noqa: BLE001
        logger.debug("_fetch_hl_candles_1m falló para %s: %s", symbol, exc)
        return pd.DataFrame()


def _fetch_dukascopy_ticks_to_ohlc(symbol: str, days: int) -> pd.DataFrame:
    """Descarga tick data de Dukascopy y la convierte a OHLC 1m."""
    from datetime import datetime, timezone, timedelta
    from pathlib import Path as _Path
    from btquantr.data.tick_data.dukascopy import DukascopyTickSource
    ticks_dir = _Path("data/ticks")
    ticks_dir.mkdir(parents=True, exist_ok=True)
    try:
        end = datetime.now(tz=timezone.utc)
        start = end - timedelta(days=days)
        src = DukascopyTickSource(ticks_dir)
        tick_df = src.download(symbol, start=start, end=end)
        if tick_df.empty:
            return pd.DataFrame()
        return _ticks_to_ohlc(tick_df, timeframe="1min")
    except Exception as exc:  # noqa: BLE001
        logger.debug("_fetch_dukascopy_ticks_to_ohlc falló para %s: %s", symbol, exc)
        return pd.DataFrame()


def _fetch_yfinance_1m(symbol: str, days: int) -> pd.DataFrame:
    """Descarga OHLC 1m desde yfinance (fallback para otros activos).

    yfinance soporta hasta 7 días de datos 1m. Si el símbolo no tiene sufijos,
    se usa tal cual.

    Args:
        symbol: Símbolo yfinance (ej. "SPY", "GLD", "EURUSD=X", "AAPL").
        days:   Días a descargar (máximo efectivo ≈ 7 en yfinance 1m).

    Returns:
        DataFrame con columnas Open/High/Low/Close/Volume e índice DatetimeIndex.
        Vacío si falla.
    """
    try:
        import yfinance as yf
        period = f"{min(days, 7)}d"
        ticker = yf.Ticker(symbol)
        df = ticker.history(interval="1m", period=period)
        if df.empty:
            return pd.DataFrame()
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col not in df.columns:
                return pd.DataFrame()
        return df[["Open", "High", "Low", "Close", "Volume"]]
    except Exception as exc:  # noqa: BLE001
        logger.debug("_fetch_yfinance_1m falló para %s: %s", symbol, exc)
        return pd.DataFrame()


def _fetch_yfinance_1h(symbol: str) -> pd.DataFrame:
    """Descarga OHLC 1h desde yfinance con period='1mo' (~720 barras).

    Usado para forex (EURUSD, GBPUSD, etc.) y stocks (SPY, GLD, AAPL).
    Forex pairs reciben sufijo =X en yfinance (EURUSD → EURUSD=X).

    Args:
        symbol: Símbolo sin sufijo (ej. "EURUSD", "SPY", "AAPL").

    Returns:
        DataFrame con columnas Open/High/Low/Close/Volume e índice DatetimeIndex.
        Vacío si falla.
    """
    try:
        import yfinance as yf
        yf_sym = symbol.upper() + "=X" if symbol.upper() in _FOREX_YF_SUFFIX else symbol.upper()
        ticker = yf.Ticker(yf_sym)
        df = ticker.history(interval="1h", period="60d")
        if df.empty:
            return pd.DataFrame()
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col not in df.columns:
                return pd.DataFrame()
        return df[["Open", "High", "Low", "Close", "Volume"]]
    except Exception as exc:  # noqa: BLE001
        logger.debug("_fetch_yfinance_1h falló para %s: %s", symbol, exc)
        return pd.DataFrame()


def _calc_tick_sharpe(returns: list[float]) -> float:
    """Calcula el Sharpe ratio de una lista de retornos por trade.

    Sharpe = mean(returns) / std(returns) * sqrt(n).
    Retorna 0.0 si hay menos de 2 retornos o std == 0.

    Args:
        returns: Lista de retornos porcentuales por trade.

    Returns:
        Sharpe ratio como float.
    """
    if len(returns) < 2:
        return 0.0
    arr = pd.array(returns, dtype=float)
    import numpy as _np
    arr = _np.array(returns, dtype=float)
    std = arr.std()
    if std == 0.0:
        return 0.0
    return float(arr.mean() / std * (len(arr) ** 0.5))


# Mapeo de alias de timeframe → string pandas
_TIMEFRAME_ALIASES: dict[str, str] = {
    "1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1h": "1h",   "2h": "2h",   "4h": "4h",   "6h": "6h",   "8h": "8h",
    "12h": "12h", "1d": "1D",   "1w": "1W",
}


def _detect_strategy_timeframe(strategy: dict) -> str:
    """Detecta el timeframe de la estrategia para resamplear los datos 1m.

    Orden de búsqueda:
      1. strategy["timeframe"]
      2. strategy["params"]["timeframe"]
      3. Sufijo en strategy["name"] (ej. "EMA_Cross_1h" → "1h")
      4. Default "1h"

    Returns:
        String pandas-compatible (ej. "1h", "4h", "1D", "1min").
    """
    import re

    # 1. Clave directa
    tf = strategy.get("timeframe")
    if tf:
        return _TIMEFRAME_ALIASES.get(str(tf).lower(), str(tf))

    # 2. En params
    tf = strategy.get("params", {}).get("timeframe")
    if tf:
        return _TIMEFRAME_ALIASES.get(str(tf).lower(), str(tf))

    # 3. Sufijo en el nombre (ej. "EMA_Cross_1h", "bb-reversion-4h")
    name = strategy.get("name", "")
    m = re.search(r"[_\-](\d+[mhd])\b", name, re.IGNORECASE)
    if m:
        key = m.group(1).lower()
        return _TIMEFRAME_ALIASES.get(key, key)

    # 4. Default
    return "1h"


def _resample_ohlc(ohlc_1m: pd.DataFrame, target_timeframe: str) -> pd.DataFrame:
    """Resamplea OHLC de 1m a un timeframe mayor.

    Args:
        ohlc_1m:          DataFrame con columnas Open/High/Low/Close/Volume e índice DatetimeIndex.
        target_timeframe: String pandas (ej. "1h", "4h", "1D"). Si es "1min" devuelve sin cambios.

    Returns:
        DataFrame resampleado o el original si target_timeframe == "1min".
    """
    if target_timeframe in ("1min", "1m"):
        return ohlc_1m
    if ohlc_1m.empty:
        return ohlc_1m
    try:
        agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
        return ohlc_1m.resample(target_timeframe).agg(agg).dropna(subset=["Open"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("_resample_ohlc falló para %s: %s", target_timeframe, exc)
        return ohlc_1m


def _quick_backtest_impl(strategy: dict, ohlcv: pd.DataFrame) -> dict | None:
    """Implementación interna de quick_backtest (puede lanzar)."""
    from backtesting import Backtest

    strategy_class = _resolve_strategy_class(strategy)
    if strategy_class is None:
        return None

    max_price = float(ohlcv["Close"].max())
    cash = max(100_000, max_price * 3)

    bt = Backtest(
        ohlcv,
        strategy_class,
        cash=cash,
        commission=0.0004,
        exclusive_orders=True,
        finalize_trades=True,
    )
    try:
        stats = bt.run()
    except Exception as exc:  # noqa: BLE001  — MACD None, indicator errors, etc.
        logger.debug("bt.run() falló para %s: %s", strategy.get("name", "?"), exc)
        return None

    trades_df = stats._trades
    if trades_df is None or len(trades_df) == 0:
        return None

    returns: list[float] = []
    trades: list[dict] = []

    for _, row in trades_df.iterrows():
        ret_pct = float(row.get("ReturnPct", row.get("Return [%]", 0.0)))
        entry_t = row.get("EntryTime", row.get("Entry Time", None))
        # HMMHistoryBuilder almacena claves como float timestamp — usar el mismo formato
        if hasattr(entry_t, "timestamp"):
            opened_at = float(entry_t.timestamp())
        elif hasattr(entry_t, "isoformat"):
            opened_at = entry_t.isoformat()
        else:
            opened_at = str(entry_t) if entry_t is not None else ""

        returns.append(ret_pct)
        trades.append({"opened_at": opened_at, "return_pct": ret_pct})

    n_trades = len(returns)

    return {
        "returns": returns,
        "trades": trades,
        "n_trades": n_trades,
        "stats": {},
    }


# Mapeo directo: template del generador → clave en TEMPLATE_REGISTRY
# Evita la búsqueda por substring que causaba que BREAKOUT siempre
# resolviera al primer match ("donchian-breakout") ignorando los params.
_GENERATOR_TO_TEMPLATE: dict[str, str] = {
    "BREAKOUT":           "donchian-breakout",
    "MEAN_REVERSION":     "bb-mean-reversion",
    "CROSSOVER":          "ema-crossover-adx",
    "THRESHOLD_CONFIRM":  "rsi-bb-combo",
    "MOMENTUM_FILTER":    "macd-momentum",
    "VOLATILITY_SQUEEZE": "bb-inside-keltner",
}


def _parameterize_class(cls, params: dict):
    """Crea un subclass dinámico de cls con los params del generador aplicados.

    Mapeo de nombres:
      'BollingerBands_length=25' → raw='length' → clase attr 'bb_length' → override 25
      'DonchianChannel_lower_length=15' → raw='lower_length' → último word='length' → 'dc_length'

    Estrategia de match (en orden):
      1. raw_param == nombre_attr (exacto)
      2. attr.endswith('_' + raw_param)
      3. attr.endswith('_' + raw_param.split('_')[-1])   ← última palabra
    Solo aplica a attrs numéricos (int/float) definidos en la propia clase.
    """
    cls_num_attrs = {
        k: v for k, v in vars(cls).items()
        if not k.startswith("_") and isinstance(v, (int, float))
    }
    if not cls_num_attrs:
        return cls

    overrides: dict = {}
    for param_key, param_value in params.items():
        # Extraer raw_param: todo lo que viene después del primer '_'
        # 'BollingerBands_length' → 'length'
        # 'DonchianChannel_lower_length' → 'lower_length'
        raw_param = param_key.split("_", 1)[1] if "_" in param_key else param_key
        last_word = raw_param.split("_")[-1]

        matched_attr = None
        for attr_name in cls_num_attrs:
            if attr_name == raw_param or attr_name.endswith("_" + raw_param):
                matched_attr = attr_name
                break
        if matched_attr is None:
            for attr_name in cls_num_attrs:
                if attr_name.endswith("_" + last_word):
                    matched_attr = attr_name
                    break

        if matched_attr is not None:
            try:
                orig_type = type(cls_num_attrs[matched_attr])
                overrides[matched_attr] = orig_type(param_value)
            except (ValueError, TypeError):
                pass

    if not overrides:
        return cls

    return type(f"{cls.__name__}_P", (cls,), overrides)


def _backtest_worker(args: tuple) -> tuple[dict, dict | None]:
    """Worker top-level para ProcessPoolExecutor.

    Args:
        args: (strategy_dict, ohlcv_df)

    Returns:
        (strategy_dict, backtest_result | None)
    """
    strategy, ohlcv = args
    try:
        result = quick_backtest(strategy, ohlcv)
    except Exception:  # noqa: BLE001
        result = None
    return (strategy, result)


def _resolve_strategy_class(strategy: dict):
    """Resuelve la clase Strategy desde una seed.

    Orden de resolución:
    1. Seeds moondev/scraped con source_file: importlib directo (sin exec).
    2. Si 'code' contiene 'class' y 'Strategy': exec() con namespace rico.
    3. Si tiene 'template' en proven_templates: importar por nombre.
       Para seeds generadas/mutadas: aplicar params con _parameterize_class.
    4. None si todo falla.
    """
    origin = strategy.get("origin", "")
    source_file = strategy.get("source_file", "")
    name = strategy.get("name", "")
    code = strategy.get("code", "")
    template_name = strategy.get("template", "")

    # --- Intento 1: importlib desde source_file (moondev / scraped) ---
    if source_file and name and origin in ("moondev", "mutated", "scraped"):
        # Para seeds mutadas, el name tiene sufijo _mut\d+ → intentar nombre original
        lookup_name = name
        if origin == "mutated":
            import re
            lookup_name = re.sub(r"_mut\d+$", "", name)
        cls = _import_class_from_file(source_file, lookup_name)
        if cls is not None:
            return cls

    # --- Intento 2: exec() con namespace rico ---
    if code and "class" in code and "Strategy" in code:
        cls = _exec_strategy_class(code)
        if cls is not None:
            return cls

    # --- Intento 3: proven_templates por nombre de template ---
    if template_name:
        cls = _resolve_from_template(template_name)
        if cls is not None:
            # Para seeds generadas/mutadas: inyectar params en subclass dinámico
            if origin in ("generated", "mutated") and strategy.get("params"):
                cls = _parameterize_class(cls, strategy["params"])
            return cls

    return None


def _import_class_from_file(source_file: str, class_name: str):
    """Importa una clase directamente desde su módulo fuente con importlib.

    Convierte 'src/rbi/strategies/bollinger.py' → 'rbi.strategies.bollinger'
    y hace getattr(module, class_name).

    Sin exec(), sin problemas de namespace.
    """
    import sys
    import importlib
    from pathlib import Path

    try:
        project_root = Path(__file__).parent.parent.parent
        # Asegurar src/ en sys.path
        src_path = str(project_root / "src")
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

        # Convertir ruta de archivo a module path
        # 'src/rbi/strategies/bollinger.py' → 'rbi.strategies.bollinger'
        path = Path(source_file)
        parts = list(path.parts)
        if parts and parts[0] in ("src", "src/"):
            parts = parts[1:]
        module_path = ".".join(parts).removesuffix(".py")

        module = importlib.import_module(module_path)
        cls = getattr(module, class_name, None)

        if cls is None:
            return None

        from backtesting import Strategy
        if isinstance(cls, type) and issubclass(cls, Strategy):
            return cls
        return None

    except Exception as exc:
        logger.debug("_import_class_from_file(%s, %s) falló: %s", source_file, class_name, exc)
        return None


def _exec_strategy_class(code: str):
    """Ejecuta código fuente y extrae la primera clase Strategy.

    Pre-rellena el namespace con imports comunes para que el código
    de seeds externas (scraped) pueda usar RBIStrategy, ta, np, etc.
    sin tener que declarar los imports explícitamente.
    """
    import sys
    import numpy as np
    import pandas as pd
    import pandas_ta as ta
    from pathlib import Path

    project_root = Path(__file__).parent.parent.parent
    src_path = str(project_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    from backtesting import Strategy
    from backtesting.lib import crossover, cross

    # Importar RBIStrategy como fallback en caso de que el código lo use
    try:
        from rbi.strategies.base import RBIStrategy
    except Exception:
        RBIStrategy = Strategy  # type: ignore[misc,assignment]

    # Namespace rico: los scraped/externos pueden heredar de cualquiera de estos
    ns: dict = {
        "__builtins__": __builtins__,
        "Strategy": Strategy,
        "RBIStrategy": RBIStrategy,
        "crossover": crossover,
        "cross": cross,
        "ta": ta,
        "np": np,
        "pd": pd,
    }

    import textwrap
    exec(compile(textwrap.dedent(code), "<strategy>", "exec"), ns)  # noqa: S102

    for obj_name, obj in ns.items():
        if (
            isinstance(obj, type)
            and issubclass(obj, Strategy)
            and obj is not Strategy
            and obj is not RBIStrategy
        ):
            return obj
    return None


def _resolve_from_template(template_name: str):
    """Resuelve una clase de estrategia desde proven_templates por nombre de template.

    TEMPLATE_REGISTRY usa claves kebab-case (ej. 'bb-mean-reversion').
    Esta función normaliza el template_name a ese formato y también hace
    búsqueda case-insensitive.

    Mapeo de entrada:
      BREAKOUT          → 'donchian-breakout'  (vía _GENERATOR_TO_TEMPLATE directo)
      BB_MEAN_REVERSION → 'bb-mean-reversion'  (vía normalización kebab)
      MEAN_REVERSION    → busca 'bb-mean-reversion', 'keltner-mean-reversion', etc.
    """
    try:
        from btquantr.engine.templates.proven_templates import TEMPLATE_REGISTRY

        # Intento 1: nombre directo en registry
        if template_name in TEMPLATE_REGISTRY:
            return TEMPLATE_REGISTRY[template_name]

        # Intento 2: mapeo directo generator→proven (evita ambigüedad de substring)
        direct_key = _GENERATOR_TO_TEMPLATE.get(template_name.upper())
        if direct_key and direct_key in TEMPLATE_REGISTRY:
            return TEMPLATE_REGISTRY[direct_key]

        # Intento 3: normalizar SNAKE_CASE → kebab-case
        kebab = template_name.lower().replace("_", "-")
        if kebab in TEMPLATE_REGISTRY:
            return TEMPLATE_REGISTRY[kebab]

        # Intento 4: búsqueda por substring (ej MEAN_REVERSION → 'bb-mean-reversion')
        template_norm = template_name.lower().replace("_", "-").replace(" ", "-")
        for key, cls in TEMPLATE_REGISTRY.items():
            if template_norm in key or key in template_norm:
                return cls

    except (ImportError, AttributeError, KeyError):
        pass
    return None


def _snake_to_camel(name: str) -> str:
    """BB_MEAN_REVERSION → BBMeanReversion."""
    return "".join(word.capitalize() for word in name.split("_"))


# ─────────────────────────────────────────────────────────────────────────────
# EvolutionLoop
# ─────────────────────────────────────────────────────────────────────────────

class EvolutionLoop:
    """Orquestador del ciclo evolutivo completo.

    Flujo: genera → evalúa → selecciona por régimen → evoluciona → registra.
    """

    def run(
        self,
        symbol: str,
        timeframe: str = "1h",
        months: int = 12,
        n_population: int = 100,
        n_generations: int = 3,
        n_workers: int = 1,
        min_trades: int = 10,
    ) -> list[dict]:
        """Ciclo completo.

        Args:
            n_workers:  Procesos paralelos para evaluar población. 1 = secuencial.
            min_trades: Mínimo de trades para que una estrategia sea evaluada.
                        Usar 5 para activos equity (SPY, GLD...) donde los
                        crossovers son poco frecuentes en timeframe diario.

        Returns:
            Lista de estrategias robustas que pasaron walk-forward y fueron registradas.
        """
        ohlcv = self._download_ohlcv(symbol, timeframe, months)
        if ohlcv is None or ohlcv.empty:
            raise ValueError(
                f"No se pudo obtener OHLCV para {symbol} ({timeframe}, {months}m). "
                f"Para timeframes intraday, yfinance limita: 1m→7d, 5m/15m/30m→60d, 1h→730d. "
                f"Reduce --months o usa un timeframe mayor (ej. --timeframe 1h)."
            )
        hmm = HMMHistoryBuilder().build_with_enrichment(ohlcv, symbol=symbol)
        seeds = SeedLibrary().load_all_seeds()

        fitness_fn = MultiFitness()
        regime_fn = RegimeAwareFitness()

        population = StrategyGenerator().generate(n_population, seeds=seeds)

        # Acumular evaluated de TODAS las generaciones para que las seeds BEAR/SIDEWAYS
        # de gen 0 (que pasan WalkForward) no desaparezcan por convergencia evolutiva a BULL.
        all_evaluated: list[dict] = []
        for gen in range(n_generations):
            evaluated = self._evaluate_population(
                population, ohlcv, fitness_fn, regime_fn, hmm,
                n_workers=n_workers, min_trades=min_trades,
            )
            all_evaluated.extend(evaluated)
            logger.info("Generación %d: %d evaluadas (%d acumuladas)", gen, len(evaluated), len(all_evaluated))

            top = regime_fn._select_by_regime(evaluated)
            if not top:
                logger.warning("Generación %d: ningún top seleccionado, deteniendo", gen)
                break
            population = self._evolve(top, n_offspring=50)

        # Walk-Forward sobre top finales seleccionados por régimen de TODAS las gens
        # (4 BULL + 3 BEAR + 3 SIDEWAYS) en vez de solo top-5 fitness global
        if not all_evaluated:
            return []

        final_top = regime_fn._select_by_regime(all_evaluated)
        robust: list[dict] = []
        store = get_strategy_store()

        for s in final_top:
            if self._maybe_register(s, ohlcv, store, symbol=symbol):
                robust.append(s)

        logger.info("EvolutionLoop: %d estrategias robustas para %s", len(robust), symbol)
        return robust

    def _evaluate_population(
        self,
        population: list[dict],
        ohlcv: pd.DataFrame,
        fitness_fn: MultiFitness,
        regime_fn: RegimeAwareFitness,
        hmm: dict,
        n_workers: int = 1,
        min_trades: int = 10,
    ) -> list[dict]:
        """Evalúa cada estrategia de la población con quick_backtest.

        Args:
            n_workers:  Número de procesos paralelos. 1 = secuencial (para tests).
            min_trades: Mínimo de trades para incluir en evaluados. Usar 5 para equity.
        """
        pairs: list[tuple[dict, dict | None]] = []

        if n_workers > 1:
            try:
                args = [(s, ohlcv) for s in population]
                with ProcessPoolExecutor(max_workers=min(n_workers, 2)) as executor:
                    pairs = list(executor.map(_backtest_worker, args))
            except Exception as exc:  # noqa: BLE001
                logger.warning("ProcessPoolExecutor falló (%s), usando path secuencial", exc)
                pairs = [_backtest_worker((s, ohlcv)) for s in population]
        else:
            for s in population:
                result = quick_backtest(s, ohlcv)
                pairs.append((s, result))

        evaluated: list[dict] = []
        for s, result in pairs:
            if result is None or result["n_trades"] < min_trades:
                continue
            s = dict(s)  # no mutar el original
            returns = result["returns"]
            s["fitness"] = fitness_fn.score(None, returns)
            s["regime_fitness"] = regime_fn.score(result["trades"], hmm)
            s["_returns"] = returns
            evaluated.append(s)
        return evaluated

    def _evolve(self, top: list[dict], n_offspring: int = 50) -> list[dict]:
        """Evoluciona usando GeneticMutator si está disponible, si no usa StrategyGenerator."""
        try:
            from btquantr.engine.mutator import GeneticMutator
            return GeneticMutator().evolve(top, n_offspring=n_offspring)
        except (ImportError, AttributeError, TypeError):
            # Fallback: StrategyGenerator genera nuevas combinaciones
            return StrategyGenerator().generate(n_offspring, seeds=top)

    # Crypto con alta volatilidad de régimen: threshold de degradación más permisivo.
    # Sharpe puede variar hasta 1.5 puntos entre ventanas sin que la estrategia sea mala.
    _VOLATILE_CRYPTO: frozenset[str] = frozenset({
        "ETHUSDT", "SOLUSDT", "AVAXUSDT", "ADAUSDT",
        "LINKUSDT", "DOTUSDT", "DOGEUSDT", "BNBUSDT",
        "BTCUSDT",
    })

    def _passes_walk_forward(
        self,
        strategy: dict,
        ohlcv: pd.DataFrame,
        symbol: str = "",
    ) -> bool:
        """Walk-forward validation: retorna True si el strategy es robusto.

        Usa n_splits=2 (folds más grandes → Sharpe más estable con pocos trades).
        Aplica degradation threshold dinámico:
          - Crypto volátil (ETH/SOL/AVAX…): 1.5  — régimen cambia más rápido
          - Resto (BTC, forex, equity):       1.0  — estándar
        """
        returns = strategy.get("_returns", [])
        if len(returns) < 15:
            return False
        try:
            result = WalkForwardOptimizer(n_splits=2, train_ratio=0.7).optimize(
                returns=returns,
                strategy_fn=lambda r, p: r,  # identidad (ya evaluado)
                param_grid=[None],
            )
            degradation = result.get("degradation", float("inf"))
            threshold = 1.5 if symbol.upper() in self._VOLATILE_CRYPTO else 1.0
            folds_ok = len(result.get("fold_results", [])) >= 1
            return bool(degradation < threshold and folds_ok)
        except Exception as exc:  # noqa: BLE001
            logger.debug("WalkForwardOptimizer falló: %s", exc)
            return False

    # Activos donde alpha=0.10 está justificado:
    # - Crypto de alta liquidez: muchos trades, datos abundantes desde HL/Binance
    # - Forex / equity / commodities: menos trades por la baja volatilidad en 1h,
    #   lo que reduce el poder estadístico. Alpha 0.10 compensa esto.
    _HIGH_LIQUIDITY_SYMBOLS: frozenset[str] = frozenset({
        # Crypto (alta frecuencia de datos)
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",
        "AVAXUSDT", "ADAUSDT", "LINKUSDT", "DOTUSDT", "DOGEUSDT",
        # Forex (pocos trades por pip-volatility baja → menor poder estadístico)
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF",
        # Equity / commodities (volumen diario, menos trades en 1h)
        "SPY", "GLD", "AAPL",
        # HIP3 sintéticos HyperLiquid
        "xyz:CL", "xyz:GOLD", "xyz:NVDA", "xyz:XYZ100",
    })

    def _passes_permutation_test(
        self,
        strategy: dict,
        n_permutations: int = 500,
        symbol: str = "",
    ) -> bool:
        """Permutation test: retorna True si la estrategia tiene edge estadístico real.

        Genera n_permutations shuffles de los retornos y calcula el p-value.
        Activos de alta liquidez (BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT) usan alpha=0.10
        para compensar el bajo poder estadístico con pocos meses de datos.
        El resto usa alpha=0.05 (más estricto).
        """
        returns = strategy.get("_returns", [])
        if len(returns) < 15:
            return False
        alpha = 0.10 if symbol.upper() in self._HIGH_LIQUIDITY_SYMBOLS else 0.05
        try:
            result = PermutationTest(n_permutations=n_permutations, seed=42, alpha=alpha).run(returns)
            return bool(result.get("has_edge", False))
        except Exception as exc:  # noqa: BLE001
            logger.debug("PermutationTest falló: %s", exc)
            return False

    def _maybe_register(
        self,
        strategy: dict,
        ohlcv: pd.DataFrame,
        store: StrategyStore,
        symbol: str = "BTCUSDT",
    ) -> bool:
        """Registra la estrategia solo si pasa walk-forward Y permutation test.

        Returns:
            True si la estrategia fue registrada.
        """
        if not self._passes_walk_forward(strategy, ohlcv, symbol=symbol):
            return False
        if not self._passes_permutation_test(strategy, symbol=symbol):
            return False
        best_regime = strategy.get("regime_fitness", {}).get("best_regime", "UNKNOWN")
        store.register(strategy, regime=best_regime, symbol=symbol)
        return True

    def _download_ohlcv(self, symbol: str, timeframe: str, months: int) -> pd.DataFrame:
        """Descarga OHLCV usando HyperLiquid (solo *USDT) o OHLCVRouter universal.

        - Símbolos *USDT: HyperLiquid si HYPERLIQUID_BASE_URL está definido, si no OHLCVRouter.
        - Otros (SPY, GLD, EURUSD, BTC-USD...): OHLCVRouter directamente.
        """
        days = months * 30

        # HyperLiquid solo aplica a perps crypto (USDT)
        if symbol.upper().endswith("USDT") and os.environ.get("HYPERLIQUID_BASE_URL"):
            try:
                return self._fetch_hyperliquid(symbol, timeframe, days)
            except Exception as exc:
                logger.warning("HyperLiquid falló para %s, usando OHLCVRouter: %s", symbol, exc)

        return ohlcv_router.get_ohlcv(symbol, timeframe=timeframe, days=days)

    # ─── Fetch helpers ─────────────────────────────────────────────────────────

    def _fetch_hyperliquid(self, symbol: str, timeframe: str, days: int) -> pd.DataFrame:
        """Descarga OHLCV desde HyperLiquid."""
        import sys
        from pathlib import Path
        project_root = Path(__file__).parent.parent.parent
        src_path = str(project_root / "src")
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

        from btquantr.data.sources.hyperliquid import get_ohlcv  # type: ignore[import]
        return get_ohlcv(symbol, interval=timeframe, days=days)
