# Spec: HMMAdaptive
> Para: Backtest Architect | Prioridad: P2 | Sharpe documentado: 0.48–1.9 (como filtro)

## Idea (one-liner)
Usar Hidden Markov Model (2 estados: low-vol bull y high-vol bear) sobre log-returns para detectar régimen de mercado. En estado 0 (bull/low-vol): activar estrategia momentum. En estado 1 (bear/high-vol): solo cerrar posiciones existentes, no abrir nuevas.

## Tipo
Regime Detection / Adaptive Meta-Strategy / Filter

## Dependencias
```bash
# Requiere hmmlearn (NO instalado por defecto)
uv add hmmlearn
# o en requirements:
# hmmlearn>=0.3.0
```

## Cómo funciona
El HMM no es una estrategia standalone — es un **filtro de régimen** que wrappea otra estrategia:
1. HMM detecta en qué estado está el mercado
2. Si estado = 0 (favorable) → la estrategia subyacente puede operar
3. Si estado = 1 (desfavorable) → solo cerrar, no abrir nuevas posiciones

## Variables en init() — PRE-ENTRENAR el HMM
```python
from hmmlearn.hmm import GaussianHMM
import numpy as np

close = pd.Series(self.data.Close)

# Calcular log-returns (feature de input al HMM)
log_returns = np.log(close / close.shift(1)).dropna()
X = log_returns.values.reshape(-1, 1)

# ENTRENAR HMM en los primeros 70% de los datos (para evitar look-ahead bias)
train_size = int(len(X) * 0.7)
X_train = X[:train_size]

model = GaussianHMM(
    n_components=2,
    covariance_type="full",
    n_iter=1000,
    random_state=42
)
model.fit(X_train)

# Predecir estados para TODO el período (incluyendo out-of-sample)
all_states = model.predict(X)

# Identificar cuál estado es "bull" (mayor mean return)
means = model.means_.flatten()
bull_state = int(np.argmax(means))  # estado con mayor retorno medio

# Generar señal de régimen: 1 = bull, 0 = bear
regime = np.where(all_states == bull_state, 1.0, 0.0)

# Prepend NaN para alinear (log_returns pierde primera fila)
regime_aligned = np.concatenate([[np.nan], regime])

self.regime = self.I(lambda: regime_aligned, name='Regime')

# Indicadores de la estrategia subyacente (momentum)
self.rsi14  = self.I(lambda: ta.rsi(close, 14).values, name='RSI14')
self.ema50  = self.I(lambda: ta.ema(close, 50).values, name='EMA50')
self.ema200 = self.I(lambda: ta.ema(close, 200).values, name='EMA200')
self.atr14  = self.I(lambda: ta.atr(
    pd.Series(self.data.High),
    pd.Series(self.data.Low),
    close, 14
).values, name='ATR14')
```

## Entry conditions (solo si régimen = bull)
```
LONG (momentum en régimen favorable):
1. self.regime[-1] == 1.0              (HMM dice: estamos en bull)
2. self.ema50[-1] > self.ema200[-1]    (golden cross EMA)
3. self.rsi14[-1] > 50                 (momentum positivo)
4. self.rsi14[-2] <= 50               (cruce de RSI 50)

→ buy(size=0.95, sl=entry_price - atr*sl_mult, tp=entry_price + atr*tp_mult)
```

## Exit conditions
```
Cerrar posición SIEMPRE (incluso si régimen = bull):
1. self.regime[-1] == 0.0              (cambio a bear → salida inmediata)
2. self.rsi14[-1] > 75                 (sobrecomprado)
3. precio cruza EMA50 hacia abajo

Solo en régimen = 0 (bear):
→ NO abrir nuevas posiciones (QuantStart rule: "Long entry only in regime 0")
→ Sí se permite cerrar existentes
```

## Parámetros optimizables
```python
n_components   = 2      # estados HMM, rango: [2, 3]
train_pct      = 0.70   # % para entrenar, rango: [0.60, 0.70, 0.80]
sl_atr_mult    = 2.0    # rango: [1.5, 2.0, 2.5]
tp_atr_mult    = 3.0    # rango: [2.0, 3.0, 4.0]
rsi_entry      = 50     # rango: [45, 50, 55]
ema_fast       = 50     # rango: [20, 50]
ema_slow       = 200    # rango: [100, 200]
```

## Performance documentada
| Ejemplo | Sin HMM | Con HMM | Mejora |
|---------|---------|---------|--------|
| QuantStart S&P500 (2005-2014) | Sharpe 0.37, DD -56% | Sharpe **0.48**, DD **-24%** | DD -57% |
| QuantInsti (3 estados + RF) | Baseline | Sharpe **1.9** | +filtrado por régimen |
| Trend-following general | Baseline | Sharpe **0.857** | Filtro simple |

## Edge / Por qué funciona
- Mercados tienen regímenes con estadísticas distintas (demostrado empíricamente)
- En bear/high-vol: estrategias de momentum tienen expectancy negativa
- Filtrar entradas en mal régimen reduce DD sin sacrificar mucho return
- HMM captura transiciones de régimen mejor que indicadores simples

## Advertencias críticas
- ⚠️ **Look-ahead bias**: el HMM entrenado en datos futuros contamina el backtest
  Fix: train en primeros 70%, predict sobre el restante 30% out-of-sample
- ⚠️ **Label switching**: el "bull state" puede cambiar de número entre runs
  Fix: siempre identificar por `np.argmax(model.means_)`
- ⚠️ **hmmlearn random_state**: SIN fijar, los resultados cambian en cada run
  Fix: siempre `random_state=42`
- ⚠️ Necesita mínimo 500 barras para training (usar 1h data de >1 año)

## Variables nuevas interesantes a explorar
```python
# Versión con 3 estados (bull/sideways/bear)
model_3 = GaussianHMM(n_components=3, covariance_type="full", n_iter=1000, random_state=42)

# Usar volatilidad como feature adicional (multivariado)
vol_20 = log_returns.rolling(20).std()
X_multi = np.column_stack([log_returns.values, vol_20.values])  # (N, 2)

# Usar ATR normalizado como tercer feature
atr_norm = atr / close  # ATR ratio
X_multi3 = np.column_stack([log_returns.values, vol_20.values, atr_norm.values])
```

## Fuentes
- [QuantStart: Market Regime Detection with HMM](https://www.quantstart.com/articles/market-regime-detection-using-hidden-markov-models-in-qstrader/)
- [QuantInsti: Regime Adaptive Trading](https://blog.quantinsti.com/regime-adaptive-trading-python/)
- [QuantConnect: HMM docs](https://www.quantconnect.com/docs/v2/research-environment/applying-research/hidden-markov-models)
- Reporte completo: `research/reports/2026-03-01-hmm-adaptive-research.md`
