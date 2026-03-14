"""
Configuración central de moondev.
Todos los agentes y estrategias leen de aquí.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# === Exchange ===
EXCHANGE = os.getenv("MOONDEV_EXCHANGE", "hyperliquid")  # 'solana' | 'hyperliquid'

# === AI Models ===
# Opus 4.5 (Anthropic 1P): claude-opus-4-5-20251101
AI_MODEL = {"type": "ollama", "name": "qwen2.5-coder:7b"}
AI_FALLBACKS = [
    {"type": "ollama", "name": "llama3.1:8b"},
    {"type": "ollama", "name": "mistral:latest"},
    {"type": "groq", "name": "llama-3.3-70b-versatile"},
]

# === API Keys (desde .env) ===
ANTHROPIC_API_KEY    = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY       = os.getenv("OPENAI_API_KEY", "")
GROQ_API_KEY         = os.getenv("GROQ_API_KEY", "")
DEEPSEEK_API_KEY     = os.getenv("DEEPSEEK_API_KEY", "")
HYPERLIQUID_KEY      = os.getenv("HYPERLIQUID_PRIVATE_KEY", "")
COINGECKO_API_KEY    = os.getenv("COINGECKO_API_KEY", "")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")  # Twitter API v2 — sentiment_agent

# === Tokens a monitorear ===
MONITORED_TOKENS = ["BTC", "ETH", "SOL"]

# === Risk ===
USD_SIZE = 25                    # tamaño base por operación
MAX_POSITION_PERCENTAGE = 30     # % máximo del portfolio en un token
MAX_LOSS_USD = 25                # stop loss absoluto diario
MAX_GAIN_USD = 50                # take profit absoluto diario
STRATEGY_MIN_CONFIDENCE = 60     # % mínimo confianza LLM para ejecutar
MAX_USD_ORDER_SIZE = 3           # chunk size para órdenes fragmentadas
TX_SLEEP = 30                    # segundos entre transacciones

# === RBI Agent ===
TARGET_RETURN = 50               # % objetivo para optimization loop v3
MAX_DEBUG_ITERATIONS = 10
MAX_OPTIMIZATION_ITERATIONS = 10

# === Backtest (multi_data_tester + criterios Quant Architect) ===
BACKTEST_COMMISSION = 0.001       # por trade (0.1%)
BACKTEST_SLIPPAGE_PCT = 0.05     # 0.05% por lado — slippage realista crypto (antes: 0.0 → Sharpe inflado)
BACKTEST_MIN_BARS = 252          # minimo barras (ej. ~1y 1d o ~3.5 meses 1h) para considerar muestra valida
BACKTEST_DEFAULT_PERIOD = "1y"
BACKTEST_DEFAULT_INTERVAL = "1h"
# Criterios PASS (viable por activo)
PASS_SHARPE = 1.0
PASS_MAX_DD_PCT = -20.0
PASS_MIN_TRADES = 50             # aumentado de 30 → 50 (error std Sharpe ~0.28 vs ~0.36 anterior)
PASS_MIN_WINRATE_PCT = 45.0
# Criterios PRECAUCION (selectivo)
CAUTION_SHARPE = 0.5
CAUTION_MAX_DD_PCT = -35.0
CAUTION_MIN_TRADES = 10
# Veredicto global: % minimo de activos que pasan para considerar estrategia viable
VIABLE_PCT_THRESHOLD = 40       # >= 40% activos PASS => VIABLE
SELECTIVE_PCT_THRESHOLD = 20     # >= 20% => SELECTIVO; si no => NO VIABLE

# === Paths ===
import pathlib
MOONDEV_DIR = pathlib.Path(__file__).parent
DATA_DIR = MOONDEV_DIR / "data"
IDEAS_FILE = DATA_DIR / "ideas.txt"
IDEAS_LOG = DATA_DIR / "ideas.csv"
AGENT_MEMORY_DIR = DATA_DIR / "agent_memory"
OHLCV_DIR = DATA_DIR / "ohlcv"
