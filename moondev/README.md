# moondev/ — Lab de exploración

Sección independiente dentro de RBI-Backtester.
Inspirado en: https://github.com/Ikertxusalva/moon-dev-ai-agents

## Uso rápido

```bash
# Config: editar moondev/config.py o variables de entorno
export ANTHROPIC_API_KEY=tu-clave

# Generar ideas de estrategias
python moondev/agents/research_agent.py

# Pipeline RBI v2 (research → backtest → execute → debug)
python moondev/agents/rbi_agent_v2.py

# Backtest directo
python moondev/strategies/bollinger_altcoin.py
```

## Estructura
- `core/` — Model Factory, Exchange Manager, Portfolio Tracker
- `agents/` — Scripts ejecutables por agente
- `strategies/` — Estrategias backtestables (Backtesting.py)
- `backtests/` — Multi-data tester, criterios de viabilidad (Quant Architect)
- `data/` — Runtime data (excluido de git)

### Backtests y criterios
- **Config**: `config.py` define `BACKTEST_COMMISSION`, `BACKTEST_SLIPPAGE_PCT`, `BACKTEST_MIN_BARS`, umbrales PASS/PRECAUCION y `VIABLE_PCT_THRESHOLD`.
- **Criterios**: `backtests/criteria.py` centraliza veredicto por activo (PASS/PRECAUCION/FAIL) y veredicto global (VIABLE/SELECTIVO/NO VIABLE).
- **Multi-test**: `backtests/multi_data_tester.py <strategy.py> <ClassName>` corre una estrategia contra 25 activos; resultados en `results/multi_*.json` (incl. Sortino, n_bars, config).
