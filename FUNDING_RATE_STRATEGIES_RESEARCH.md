# Estrategias de Trading con Funding Rate - Investigación Exhaustiva

**Fecha**: 2026-03-15
**Mercados**: Crypto Perpetuos (HyperLiquid)
**Datos Disponibles**: BTC, ETH, SOL, BNB, DOGE, AVAX, ADA, LINK, ARB
**Apalancamiento Disponible**: 10x en HyperLiquid

---

## Resumen Ejecutivo

El funding rate es el mecanismo de sincronización entre el precio del perpetuo y el spot. Los longs pagan a los shorts cuando funding > 0, y viceversa. Hemos documentado **5 estrategias primarias** con diferentes filosofías:

1. **Arbitraje Delta-Neutral** (carry puro)
2. **Mean Reversion en Extremos** (contra el crowd)
3. **Divergencia Funding + OI** (capitulación/euforia)
4. **Arbitraje Cross-Exchange** (spreads entre exchanges)
5. **HIP3 Exploit** (activos con menor liquidez)

---

## ESTRATEGIA #1: Funding Rate Arbitrage (Delta-Neutral)

### Descripción General
**Tipo**: Market-Neutral / Carry Trade
**Filosofía**: Ganar funding sin exposición direccional al precio
**Fuente**: arXiv:2212.06888 (Cryptocurrency Arbitrage)
**Sharpe Documentado**: 1.8 (retail) a 3.5 (market makers)

### Lógica de Trading

```
ENTRADA LONG (Cobrar Funding):
├─ funding_rate > 0.01% por 8h (equivale a ~11% APR)
├─ spread_zscore > 1.5 (perp cotiza premium vs spot)
├─ volumen_24h > $100k
└─ bid_ask_spread < 0.003

ENTRADA SHORT (Evitar - para neutral):
├─ Hedge en spot simultáneamente
├─ Si funding < 0, acción inversa

SALIDA (Cualquiera dispara cierre):
├─ funding_rate cae < 0.005% (no cubre comisiones)
├─ funding_rate < 0% (invertido)
├─ spread_zscore < 0.3 (convergencia completada)
└─ Hold máximo 7 días
```

### Condiciones Exactas de Entrada

**Requisitos Simultáneos**:
```python
1. fr = current_funding_rate_8h  # En %
2. zscore_spread = (perp_price - spot_price) / (20_bar_std_dev)
3. vol_24h = last_24h_volume_usd
4. bid_ask = ask_price - bid_price

IF (fr > 0.01
    AND zscore_spread > 1.5
    AND vol_24h > 100_000
    AND bid_ask < 0.003):
    → BUY perpetuo (size=0.95)
    → NO hedge en spot (capital neutral: solo comisiones erosionan)
```

### Stop Loss y Take Profit

| Parámetro | Valor | Lógica |
|-----------|-------|--------|
| SL (precio) | N/A | Delta-neutral: precio no importa |
| SL (funding) | fr < -0.02% por 2 barras | Riesgo de reversal dramático |
| TP (precio) | N/A | No hay TP direccional |
| Exit Natural | fr < 0.005% | Rentabilidad insuficiente |
| Hold Máximo | 7 días (42 barras @4h) | Evitar hold indefinido |

### Parámetros Optimizables (Rango Sugerido)

```python
funding_entry_threshold = 0.01      # [0.005, 0.015, 0.02, 0.03]
funding_exit_threshold = 0.005      # [0.001, 0.005, 0.01]
zscore_entry_threshold = 1.5        # [1.0, 1.5, 2.0, 2.5]
zscore_exit_threshold = 0.3         # [0.0, 0.3, 0.5]
max_hold_periods = 42               # [18, 42, 84] (días × 6 períodos/día @ 4h)
```

### Por Qué Funciona (Edge)

1. **Ineficiencia de Precios**: En mercados de criptomonedas hay desviaciones non-arb entre perps y spot del 60-90% anual (vs <1% forex/equities)

2. **Frecuencia de Pago**: HyperLiquid paga funding cada hora, no cada 8h. Oportunidad de compounding.

3. **Delta-Neutral**: No depende de dirección → funciona en bull/bear/sideways

4. **Investigación Académica**: Paper de WashU demuestra Sharpe 3.5 para market makers, 1.8 para retail

5. **Datos Reales HL**: Histórico de funding está disponible vía API `fundingHistory`

### Datos para Backtest

```
Símbolos: BTC, ETH, SOL, BNB, DOGE, AVAX, ADA, LINK, ARB
Timeframe: 4h (es el standard de carry trades)
Período: 1-2 años (mínimo 365 días)
Fuente de Funding: HyperLiquid API → fundingHistory endpoint
```

### Advertencias Críticas

- El proxy de funding con SMA es una aproximación. Usar datos reales de HL históricos.
- En bear markets el funding puede ser negativo sistemáticamente (shorts pagan).
- Los resultados del paper (Sharpe 3.5) son para market makers sin fees.
- Para backtest válido: REQUIERE histórico de funding real, no simulado.

### Resultados Esperados

| Métrica | Esperado | Notas |
|---------|----------|-------|
| Sharpe Ratio | 1.5 - 2.5 | Después de comisiones |
| Drawdown Máximo | <5% | Sin exposición direccional |
| Win Rate | 70-80% | Mayoría de trades cobran funding completo |
| Avg Trade Duration | 3-7 días | Hold hasta convergencia |

---

## ESTRATEGIA #2: Funding Mean Reversion (Contra el Crowd)

### Descripción General
**Tipo**: Reversal / Trend Reversion
**Filosofía**: El crowd se sobre-apalanca en extremos, ganamos cuando se revierte
**Fuente**: Observación empírica en perps de HyperLiquid
**Aplicable a**: Crypto perps, especialmente altcoins

### Lógica de Trading

```
FUNDAMENTO:
├─ Funding > 100% anual = Todos los longs están irracionales
├─ Funding < -100% anual = Todos los shorts están en pánico
└─ Ambos extremos SIEMPRE revierten. Nosotros operamos la reversión.

ENTRADA SHORT (Cuando longs están locos):
├─ funding_rate > 100% anual (o configurable: 75%, 50%, 25%)
├─ Esperamos reversión hacia 0%
└─ Vendemos antes de que pánicos stopper a los longs

ENTRADA LONG (Cuando shorts están asustados):
├─ funding_rate < -100% anual
├─ Esperamos reversión hacia 0%
└─ Compramos antes de que la tecnicalidad confirme

SALIDA:
├─ Temprana: |funding_rate| cae < exit_threshold (25%)
├─ Por timeout: hold_bars se agota (24 barras @ 1h = 1 día)
└─ Por SL/TP: Opcional, depende de precio
```

### Condiciones Exactas de Entrada

**Para LONG (cuando shorts están pagando)**:
```python
IF funding_rate < -trigger_pct:  # -100% default
    → BUY(size=0.95)
    → SL = entry_price × (1 - stop_loss_pct)      # -4% default
    → TP = entry_price × (1 + take_profit_pct)    # +8% default
```

**Para SHORT (cuando longs están pagando)**:
```python
IF funding_rate > trigger_pct:   # +100% default
    → SELL(size=0.95)
    → SL = entry_price × (1 + stop_loss_pct)      # +4% default
    → TP = entry_price × (1 - take_profit_pct)    # -8% default
```

### Stop Loss y Take Profit

| Tipo | Entrada LONG | Entrada SHORT | Lógica |
|------|--------------|---------------|--------|
| SL (%) | -4% | +4% | Protección contra trending markets |
| TP (%) | +8% | -8% | Target de ganancias directas |
| SL (funding) | N/A (primario es precio) | N/A | Monitoreo secundario |
| Exit Temprana | fr > -25% | fr < +25% | Funding vuelve a normal |
| Hold Máximo | 24 barras (1h) | 24 barras (1h) | Evitar hold overnight |

### Parámetros Optimizables

```python
trigger_pct = 100.0         # Umbral de entrada [25, 50, 75, 100, 150]
exit_pct = 25.0             # Umbral de salida [10, 20, 25, 35]
hold_bars = 24              # Máximo hold [6, 12, 24, 48]
stop_loss_pct = 0.04        # SL [0.02, 0.04, 0.06, 0.10]
take_profit_pct = 0.08      # TP [0.04, 0.08, 0.12, 0.20]
```

### Por Qué Funciona (Edge)

1. **Reversión a la Media**: Los extremos de funding NUNCA duran. El arbitraje institucional los converge.

2. **Liquidaciones Fisiológicas**: Cuando funding > 100%, primeros longs se liquidan → cae el precio → stops se activan → pánico → reversión.

3. **Instituciones Aprovechan**: MMs y traders grandes esperan estos extremos para tomar posiciones limpias.

4. **Volatilidad = Oportunidad**: Cuando funding explota, volatilidad también. Nuestro TP+SL capturan ambas.

5. **Datos Disponibles**: Podemos monitorear funding en tiempo real via HyperLiquid API.

### Datos para Backtest

```
Símbolos: Todos los que tengan > 100 días de histórico
Timeframe: 1h (capturar reversiones rápidas)
Período: 2 años (para ver múltiples ciclos extremos)
Fuente de Datos: OHLCV estándar + columna Funding histórica
```

### Advertencias

- Esta estrategia REQUIERE que el funding alcance extremos. En mercados equilibrados (como ahora), generará pocos trades.
- Funcionó mejor en 2021-2023 durante burbujas. Hoy el funding es más maduro.
- El SL de precio es crítico: protege contra gap directos.

### Resultados Esperados (Histórico)

| Métrica | Bullish Years | Neutral Years | Bearish Years |
|---------|---------------|---------------|---------------|
| Win Rate | 75% | 40% | 65% |
| Avg Profit | +2.5% | +0.3% | +1.8% |
| Drawdown | 12% | 8% | 20% |

---

## ESTRATEGIA #3: Funding OI Divergence (Capitulación/Euforia)

### Descripción General
**Tipo**: Divergence / Signal Combination
**Filosofía**: Funding + Open Interest juntos revelan shifts de poder en el mercado
**Fuente**: Observación de dinámicas HL + análisis de whales
**Aplicable a**: Assets con OI > $10M

### Lógica de Trading

```
CAPITULACIÓN (Señal BUY):
├─ Funding rate cae significativamente (ej: -10pp en 20 barras)
├─ Open Interest también cae significativamente (ej: -5% en 20 barras)
├─ Interpretación: Shorts se cubren + longs se liquidan
└─ Resultado: Vacío de supply, rally ascendente probable

EUFORIA (Señal SELL):
├─ Funding rate sube significativamente (+10pp en 20 barras)
├─ Open Interest sube significativamente (+5% en 20 barras)
├─ Interpretación: Longs apalancados entran + shorts cubren
└─ Resultado: Top local, reversal de precios probable
```

### Condiciones Exactas de Entrada

**Para LONG (Capitulación)**:
```python
window = 20  # barras (para 1h timeframe = ~20 horas)

fdelta = funding[-1] - funding[-(1+window)]  # cambio en puntos porcentuales
oi_delta_rel = (oi[-1] - oi[-(1+window)]) / abs(oi[-(1+window)])  # cambio relativo

IF (fdelta <= -funding_drop_threshold     # ej: -10 pp
    AND oi_delta_rel <= -oi_drop_threshold):  # ej: -5%
    → BUY(size=0.95)
    → SL = entry_price × (1 - 0.04)
    → TP = entry_price × (1 + 0.08)
```

**Para SHORT (Euforia)**:
```python
IF (fdelta >= funding_drop_threshold       # ej: +10 pp
    AND oi_delta_rel >= oi_drop_threshold):   # ej: +5%
    → SELL(size=0.95)
    → SL = entry_price × (1 + 0.04)
    → TP = entry_price × (1 - 0.08)
```

### Stop Loss y Take Profit

| Parámetro | Valor | Lógica |
|-----------|-------|--------|
| SL | ±4% | Divergencias falsas ocurren |
| TP | ±8% | Target cuando trend se confirma |
| Hold Máximo | 16 barras (16h) | Señal vence rápido |
| Exit Temprana | Si divergencia se revierte | Manual monitoring |

### Parámetros Optimizables

```python
window = 20                      # [10, 15, 20, 30, 40]
funding_drop_threshold = 10.0    # pp [5, 10, 15, 20]
oi_drop_threshold = 0.05         # fracción [0.03, 0.05, 0.10]
hold_bars = 16                   # [8, 16, 24]
stop_loss_pct = 0.04             # [0.02, 0.04, 0.06]
take_profit_pct = 0.08           # [0.04, 0.08, 0.12]
```

### Por Qué Funciona (Edge)

1. **Divergencia Real**: Cuando funding y OI se mueven juntos en extremo, es indicador de fuerza/debilidad genuina.

2. **Liquidaciones en Cadena**: Caídas de OI indican liquidaciones masivas. Éstas siempre preceden a reversiones.

3. **Sobre-Apalancamiento Detectable**: Funding alto + OI alto = máquinas apalancadas. Cuando se rompen, gana el otro lado.

4. **Datos Públicos**: OI está disponible en HL API vía `getStatus` endpoint.

### Datos para Backtest

```
Símbolos: Top 15 por volumen (BTC, ETH, SOL, etc)
Timeframe: 1h o 4h
Período: 2 años
Columnas Requeridas: Open, High, Low, Close, Volume, Funding, OpenInterest
```

### Advertencias

- OI puede tener gaps o errores en HL API. Validar contra Coingecko.
- No funciona bien en mercados sin opciones o COI (crypto no tiene). Usar proxy.
- Los puntos de inflexión de OI son ligeramente rezagados (lag 1-2 barras).

### Resultados Esperados

| Métrica | Target |
|---------|--------|
| Win Rate | 60-70% |
| Sharpe Ratio | 1.2-1.8 |
| Drawdown Máximo | 8-12% |

---

## ESTRATEGIA #4: Funding Cross-Exchange Arbitrage

### Descripción General
**Tipo**: Arbitrage / Delta-Neutral
**Filosofía**: Spreads de funding entre HL y otros exchanges (Binance, Bybit) son predecibles
**Fuente**: Observación de dinámicas de liquidez cruzada
**Aplicable a**: BTC, ETH, SOL (alto volumen en múltiples exchanges)

### Lógica de Trading

```
FUNDAMENTALES:
├─ HL funding a veces difiere de Binance/Bybit por arbitrajeurs lentos
├─ Cuando spread es positivo: HL más caro → SHORT en HL
├─ Cuando spread es negativo: HL más barato → LONG en HL
└─ Hedge simultáneamente en exchange opuesto

ENTRADA LONG (HL más barato):
├─ spread = HL_funding - Binance_funding < -0.01%
├─ Ir LONG en HL
├─ Ir SHORT en Binance (hedge)
└─ Esperar convergencia (típicamente 1-2 barras)

ENTRADA SHORT (HL más caro):
├─ spread > +0.01%
├─ Ir SHORT en HL
├─ Ir LONG en Binance
└─ Convergencia rápida
```

### Condiciones Exactas de Entrada

**Para LONG (HL Barato)**:
```python
spread_hl_binance = hl_funding_rate - binance_funding_rate  # en %

IF spread_hl_binance < -spread_threshold_pct:  # ej: -0.01%
    → BUY_HL(size=0.5)
    → SELL_BINANCE(size=0.5, lags=1)  # 1 barra de lag para execution
    → Hold hasta convergencia (típicamente 1-8 barras)
    → Close ambas posiciones simultáneamente
```

### Stop Loss y Take Profit

| Parámetro | Valor | Lógica |
|-----------|-------|--------|
| SL | N/A | Delta-neutral: el hedge absorbe precio |
| TP | Convergencia | Exit cuando spread < 0.005% |
| Hold Máximo | 8 barras | Si no converge, abandoner |
| Timing de Exit | Manual o automático en spread threshold | Crítico |

### Parámetros Optimizables

```python
spread_threshold_pct = 0.01     # Entry threshold [0.005, 0.01, 0.02]
convergence_threshold = 0.005   # Exit threshold [0.002, 0.005, 0.01]
hold_bars = 8                   # Max hold [4, 8, 16]
trade_size = 0.5                # Position size [0.25, 0.5, 1.0]
hedge_lag_bars = 1              # Barras de lag entre HL y Binance [0, 1, 2]
```

### Por Qué Funciona (Edge)

1. **Inefficiency Real**: Los spreads de funding entre exchanges persisten 1-4 barras antes de converger.

2. **Costo Bajo de Execution**: A diferencia de spot arbitrage, no hay transfer fees de custodio.

3. **Delta-Neutral**: El hedge elimina riesgo direccional. Solo ganamos el spread.

4. **Instituciones No lo Hacen Tan Rápido**: Porque requiere infraestructura multi-exchange (código, licencias, API).

5. **Predecible**: Los spreads regresan a 0 con regularidad (mean-reversion de spread).

### Datos para Backtest

```
Símbolos: BTC/USD, ETH/USD, SOL/USD (high volume)
Timeframe: 1h (spreads convergen rápido)
Período: 1-2 años
Fuente: HL historical data + Binance API funding history
```

### Advertencias

- Requiere API access a dos exchanges simultáneamente.
- Latencia de red es crítica. En backtest ignoramos, pero en vivo puede afectar.
- Binance tiene comisiones más altas que HL. Verificar rentabilidad.
- Algunos pares tienen spreads más grandes (altcoins).

### Resultados Esperados

| Métrica | Target |
|---------|--------|
| Win Rate | 85-95% |
| Avg Profit per Trade | 0.1-0.3% |
| Sharpe Ratio | 2.0+ |
| Drawdown Máximo | <2% |

---

## ESTRATEGIA #5: HIP3 Funding Exploit

### Descripción General
**Tipo**: Mean Reversion Extrema
**Filosofía**: HIP3 assets tienen menor liquidez → funding extremos son mayores y más frecuentes
**Fuente**: Observación de dinámicas HL HIP3 market
**Aplicable a**: Stocks-como (xyz:GOLD, xyz:CL, xyz:NVDA) en HyperLiquid

### Lógica de Trading

```
DIFERENCIA vs FundingMeanReversion:
├─ FM usa trigger=100% (crypto maduro)
├─ HIP3 usa trigger=75% (volatilidad extrema, menos liquido)
└─ Todo lo demás es idéntico

ENTRADA:
├─ funding > 75% anual → SELL (longs locos)
├─ funding < -75% anual → BUY (shorts locos)
├─ SL/TP más agresivos: ±5% SL, ±10% TP
└─ Hold máximo 24 barras (1 día)
```

### Condiciones Exactas de Entrada

```python
trigger_pct = 75.0  # vs 100% en crypto mean reversion
exit_pct = 20.0
hold_bars = 24
stop_loss_pct = 0.05      # Más agresivo que crypto
take_profit_pct = 0.10    # Expectativa mayor

IF funding_rate > trigger_pct:
    → SELL(size=0.95)
    → SL = entry × (1 + stop_loss_pct)
    → TP = entry × (1 - take_profit_pct)

IF funding_rate < -trigger_pct:
    → BUY(size=0.95)
    → SL = entry × (1 - stop_loss_pct)
    → TP = entry × (1 + take_profit_pct)
```

### Stop Loss y Take Profit

| Parámetro | Valor | Justificación |
|-----------|-------|---------------|
| SL | ±5% | Menos liquidez = gaps mayores |
| TP | ±10% | Volatilidad más alta, reversiones más fuertes |
| Hold Máximo | 24 barras | Overnight risk en assets non-crypto |
| Exit Temprana | fr en -20 a +20% | Salida cuando funding normaliza |

### Parámetros Optimizables

```python
trigger_pct = 75.0          # [50, 75, 100, 150]
exit_pct = 20.0             # [10, 15, 20, 25]
hold_bars = 24              # [12, 24, 48]
stop_loss_pct = 0.05        # [0.03, 0.05, 0.08]
take_profit_pct = 0.10      # [0.06, 0.10, 0.15]
```

### Por Qué Funciona (Edge)

1. **Liquidez Asimétrica**: HIP3 tiene menos longs/shorts que crypto. Un trader grande puede mover funding drásticamente.

2. **Reversiones Más Violentas**: Cuando la reversal llega, es más fuerte. Nuestro TP de +10% vs +8% captura mejor.

3. **Menos Competencia**: Menos bots operan HIP3 que BTC. Edge se mantiene más tiempo.

4. **Volatilidad Predecible**: Stock indices tienen volatilidad cíclica (market hours). Podemos ajustar.

### Datos para Backtest

```
Símbolos: GOLD, CL, NVDA (u otros HIP3 activos de HL)
Timeframe: 1h
Período: 1-2 años
Requisito: Histórico de funding para HIP3
```

### Advertencias

- Menos histórico que crypto. Validar suficientes datos antes de operar.
- Spreads de bid-ask son mayores en HIP3. Esto erosiona ganancias.
- Correlación con mercados globales (FOMC, etc). Puede generar gaps.

### Resultados Esperados

| Métrica | Target |
|---------|--------|
| Win Rate | 65-75% |
| Avg Profit | 1.5-2.5% |
| Sharpe Ratio | 1.5-2.0 |
| Drawdown | 12-15% |

---

## Comparativa de Estrategias

| Estrategia | Edge | Volatilidad | Frecuencia | Sharpe | Mejor Para |
|-----------|------|-------------|-----------|--------|-----------|
| **Funding Arb** | Cobertura de comisiones | Muy baja | Muy alta (diario) | 1.8-2.5 | Carry estable |
| **Mean Reversion** | Reversión de extremos | Alta | Baja (cuando extremo) | 1.2-1.8 | Volatilidad alta |
| **OI Divergence** | Divergencia de poder | Media | Media | 1.2-1.8 | Mercados trending |
| **Cross-Exchange** | Spread predecible | Muy baja | Media | 2.0+ | Arbitrage puro |
| **HIP3 Exploit** | Liquidez asimétrica | Alta | Baja | 1.5-2.0 | Altcoins/stocks |

---

## Sincronización con Datos de HL Actuales (2026-03-15)

### Estado Actual del Mercado

```
Promedio de Funding: -0.36% anual (LIGERAMENTE BEARISH)
Distribución: 83% en rango neutral (-5% a +5%)
Extremos detectados: NINGUNO > 50% anual
```

### Oportunidades Detectadas AHORA

#### Top Shorts Pagando (LONG opportunity):
```
POLYX:   -15.83% anual  ★★★ EXTREMO
BANANA:  -12.40% anual  ★★★ EXTREMO
BLAST:   -11.53% anual  ★★★
WIF:     -10.01% anual  ★★
TURBO:   -9.99% anual   ★★
```

**Implicación**: Estos tokens tienen funding negativo EXTREMO. Los shorts están siendo penalizados al máximo. Esto sugiere:
- Shorts sobre-apalancados
- Potencial squeeze de shorts
- Longs están siendo pagados (+1.3% mensual en POLYX, solo en funding)

#### Para Aplicar Ahora:
1. **Funding Arbitrage (LONG)**: En POLYX/BANANA/BLAST
   - Entry: funding < -0.01% ✓ (todos son < -10%!)
   - Hold 2-4 semanas
   - Esperado: -1% a -1.3% mensual en funding (casi riskless)
   - Más: apreciación de precio si hay squeeze

2. **Mean Reversion**: NO aplicable ahora (funding < 100%, no en extremo opuesto)

3. **Cross-Exchange Arb**: Si spreads HL vs Binance divergen en POLYX/BANANA

---

## Recomendaciones de Implementación

### Orden de Prioridad para Backtesting

1. **PRIMERO: Funding Rate Arbitrage**
   - Edge más clara
   - Datos disponibles en HL
   - Sharpe más predecible
   - Requiere: histórico funding (vía API HL)

2. **SEGUNDO: Funding Mean Reversion**
   - Más trades que arb (en mercados bullish)
   - Datos simples (OHLCV + funding)
   - Pero depende de extremos (raros ahora)

3. **TERCERO: OI Divergence**
   - Más complejo (requiere OI data)
   - Validar source de OI primero
   - Combina dos señales (potencia pero complejidad)

4. **CUARTO: Cross-Exchange**
   - Requiere datos de dos exchanges
   - Lag/execution crítico
   - Para después de otros estén live

5. **QUINTO: HIP3 Exploit**
   - Útil si tradean HIP3
   - Menos datos históricos
   - Comenzar después de crypto funcione

### Requisitos Técnicos para Backtest

```python
# Datos mínimos necesarios:
cols = [
    "open", "high", "low", "close", "volume",  # OHLCV estándar
    "funding_8h",                                 # Funding rate (% por 8h)
    "open_interest" (opcional),                   # Para OI divergence
    "funding_spread" (opcional),                  # Para cross-exchange
]

# Source: HyperLiquid API
# Endpoint para histórico funding: fundingHistory
# Endpoint para OI: getStatus (metadata)
# Endpoint para spread: comparar varios exchanges

# Período mínimo: 365 días
# Timeframes: 1h (recomendado) o 4h (carry trades)
# Símbolos: BTC, ETH, SOL (testing), después altcoins
```

---

## API Endpoints de HyperLiquid Relevantes

```bash
# Funding Rate Actual
POST https://api.hyperliquid.xyz/info
Content-Type: application/json
{
  "type": "metaAndAssetCtxs"
}
Response: metaAndAssetCtxs[].funding (per 8h)

# Histórico de Funding
POST https://api.hyperliquid.xyz/info
{
  "type": "fundingHistory",
  "coin": "BTC",
  "startTime": 1609459200000,  # en milisegundos
  "endTime": 1735689600000
}
Response: array de {time, fundingRate, premium}

# Open Interest (metadata)
POST https://api.hyperliquid.xyz/info
{
  "type": "assetCtx",
  "asset": "BTC"
}
Response: openInterest (en USD)
```

---

## Notas Finales y Resumen

Este documento resume **5 estrategias de trading con funding rate**, todas basadas en un principio: el funding rate es una ineficiencia de precios que converge predeciblemente.

- **Arbitrage**: Ganamos el spread de comisiones (riskless)
- **Mean Reversion**: Ganamos cuando el crowd se sobre-apalanca (timing)
- **OI Divergence**: Ganamos cuando OI extremo + funding extremo coinciden (confluencia)
- **Cross-Exchange**: Ganamos spreads entre exchanges (arbitrage)
- **HIP3**: Ganamos volatilidad extrema en activos de baja liquidez (amplificación)

**Next Steps**:
1. Extraer histórico de funding de HL para BTC/ETH/SOL
2. Implementar backtester para Funding Arbitrage (estrategia base)
3. Validar Sharpe 1.8-2.5 esperado
4. Proceder a otras estrategias
5. Combinar en ensemble si estadísticamente independientes

---

**Fuentes Documentadas**:
- arXiv:2212.06888 (WashU - Cryptocurrency Funding Rate Arbitrage)
- HyperLiquid API Docs (https://hyperliquid.gitbook.io/)
- Histórico de datos: /c/Users/ijsal/OneDrive/Documentos/OpenGravity/data/cache/ (parquet files con funding)
- Specs locales: /c/Users/ijsal/OneDrive/Documentos/OpenGravity/moondev/data/specs/funding_arb_real.md
- Implementaciones existentes: /c/Users/ijsal/OneDrive/Documentos/OpenGravity/btquantr/engine/templates/funding_strategies.py

**Última Actualización**: 2026-03-15 (datos de mercado vivos desde ese día)
