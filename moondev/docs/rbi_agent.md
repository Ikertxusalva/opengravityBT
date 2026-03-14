# RBI Agent (Research-Based Inference)

Converts YouTube videos/PDFs into backtestable trading strategies.

## What It Does
- Extracts strategies from YouTube videos
- Parses trading PDFs/whitepapers
- Generates backtesting code
- Runs backtests automatically
- Returns performance metrics

## Usage
```bash
python src/agents/rbi_agent.py
```

## Input Sources
- YouTube URL
- PDF file path
- Text description of strategy
- Trading book excerpts

## Process
1. Extract content (transcript/text)
2. AI analyzes strategy rules
3. Generate backtesting.py code
4. Run backtest on historical data
5. Return Sharpe, returns, etc.

## Configuration
```python
RBI_MODEL = 'deepseek'  # Best for code generation
RBI_DEFAULT_TIMEFRAME = '1H'
RBI_DEFAULT_LOOKBACK = 365  # Days
```

## Cost
~$0.027 per strategy (DeepSeek R1)

## Output
`src/data/rbi/[date]/[strategy_name]_backtest.py`