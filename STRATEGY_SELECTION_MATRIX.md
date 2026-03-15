# Strategy Selection Matrix — Mean Reversion Crypto
## Decision Tree para Elegir Qué Implementar

---

## NIVEL 1: ¿Qué es tu objetivo?

### Opción A: Máxima Velocidad (Proof of Concept)
→ **Ir a NIVEL 2A**

### Opción B: Máxima Rentabilidad (Sharpe Objetivo)
→ **Ir a NIVEL 2B**

### Opción C: Máxima Robustez (Diversificación)
→ **Ir a NIVEL 2C**

---

## NIVEL 2A: Velocidad (Implementar en Hoy)

```
START: "Quiero un prototipo en 2–4 horas"
  │
  ├─ Z-Score Reversion ✅
  │  Tiempo: 1–2 horas
  │  Parámetros: 6 (muy simple)
  │  Código: ~80 líneas
  │
  └─ SALIDA: Z-Score ready
```

### Por Qué
- Menos indicadores (solo media + std dev)
- Menos lógica condicional
- Fácil debuggear
- Validación rápida del pipeline completo

### Next Step
Una vez el Z-Score ande → copiar código base para agregar más indicadores

---

## NIVEL 2B: Rentabilidad (Máximo Sharpe)

```
START: "¿Cuál va a tener mejor Sharpe?"
  │
  ├─ ¿Tienes experiencia con RSI/BB?
  │  SÍ → Bollinger RSI V3 ✅ (Sharpe 0.6–1.0)
  │  NO → Z-Score ✅ (Sharpe 0.8–1.2, más predecible)
  │
  └─ ¿Quieres intraday trades?
     SÍ → Agrega VWAP ✅ (Sharpe 0.7–1.3)
     NO → Quédate con Z-Score o Bollinger
```

### Ranking Esperado (de mayor a menor Sharpe)
1. **Pairs Trading** (1.0–1.8) — si logras ejecutar 2 patas
2. **VWAP Intraday** (0.7–1.3) — si trades 1h timeframe
3. **Z-Score** (0.8–1.2) — simple, consistente
4. **Bollinger RSI V3** (0.6–1.0) — requiere tuning de ADX

### Decision: ¿Por Dónde Empezar?
```
IF (timeframe == 1h AND max_trades_per_day > 5):
  → VWAP Intraday
ELIF (capital > 2x para 2 patas):
  → Pairs Trading
ELIF (quieres máximo edge):
  → Z-Score
ELSE:
  → Bollinger RSI V3
```

---

## NIVEL 2C: Robustez (Diversificación)

```
START: "Quiero múltiples estrategias que no se correlacionen"
  │
  ├─ Estrategia 1: Z-Score (base confiable)
  ├─ Estrategia 2: Bollinger RSI V3 (RSI, regime-aware)
  └─ Estrategia 3: VWAP Intraday (ciclos diferentes)

  ENSEMBLE: Votación 2/3 para entrada
```

### Correlación Esperada de Señales
```
Z-Score vs Bollinger RSI: 0.4–0.6 (mediana)
Z-Score vs VWAP: 0.3–0.5 (baja)
Bollinger RSI vs VWAP: 0.2–0.4 (baja)
```

### Sharpe del Ensemble
```
Estimado: (Sharpe_Z + Sharpe_BB + Sharpe_VWAP) / 3
Mejora por votación: +15–25% (reducción de drawdowns)
```

---

## NIVEL 3: Trade-offs Específicos

### Quiero Máxima Simplicidad
```
GANADOR: Z-Score Reversion
├─ Parámetros: 6
├─ Indicadores: Media + StdDev
├─ Código: ~80 líneas
├─ Debugging: Trivial
└─ Sharpe Esperado: 0.8–1.2
```

### Quiero Máxima Comprobación
```
GANADOR: Bollinger RSI V3
├─ Backtests previos: ✅ (en codebase)
├─ Validación: Versión V2 falló → V3 mejora identificada
├─ Parámetros optimizados: Parcial (ADX nuevo)
├─ Sharpe Esperado: 0.6–1.0 (conservador)
└─ Risk: Conocido (whipsaws en crypto)
```

### Quiero Máxima Diferenciación
```
GANADOR: VWAP Intraday
├─ Menos saturado que RSI/BB
├─ Opera en ciclo diferente (intraday)
├─ Parámetros: 8 (mediano)
├─ Sharpe Esperado: 0.7–1.3
└─ Ventaja: Stop/TP natural (VWAP touch)
```

### Quiero Máxima Rentabilidad
```
GANADOR: Pairs Trading ETH/BTC
├─ Sharpe Teórico: 1.0–1.8 (más alto)
├─ Delta-neutral: No importa dirección
├─ Correlación: 0.75–0.85 (estable)
├─ Riesgo: Ejecución de 2 patas simultáneamente
└─ Capital: Requiere 2 posiciones
```

---

## NIVEL 4: Matriz de Viabilidad

### ¿Puedo implementar en 4 horas?
| Estrategia | 4h | 8h | 24h |
|---|---|---|---|
| Z-Score | ✅ | ✅ | ✅ |
| Bollinger RSI V3 | ✅ | ✅ | ✅ |
| VWAP | ❌ | ✅ | ✅ |
| Pairs | ❌ | ❌ | ✅ |

### ¿Tengo experiencia con?
| Indicador | Z-Score | Bollinger RSI | VWAP | Pairs |
|---|---|---|---|---|
| Media/StdDev | ✅ | ✅ | ✅ | ✅ |
| RSI | ❌ | ✅ | ❌ | ❌ |
| Bollinger | ❌ | ✅ | ❌ | ❌ |
| ADX | ❌ | ✅ | ✅ | ❌ |
| VWAP | ❌ | ❌ | ✅ | ❌ |
| Pairs Trading | ❌ | ❌ | ❌ | ✅ |

### ¿Cuál es mi timeframe?
| Timeframe | Z-Score | Bollinger RSI | VWAP | Pairs |
|---|---|---|---|---|
| 1h (Intraday) | ✅ | ✅ | ✅✅ | ✅ |
| 4h (Swing) | ✅ | ✅ | ⚠️ | ✅ |
| 1d (Trend) | ✅ | ⚠️ | ❌ | ✅ |

---

## NIVEL 5: Decisión Final

### ESCENARIO 1: Principiante, 4 horas, quiero ver si funciona
```
RECOMENDACIÓN: Z-Score Reversion
RAZÓN: Simple, validación rápida
SIGUIENTE: Si Sharpe > 0.5 → Bollinger RSI V3
```

### ESCENARIO 2: Tengo experiencia, quiero máximo Sharpe
```
RECOMENDACIÓN: Pairs Trading ETH/BTC
RAZÓN: Sharpe teórico 1.0–1.8, delta-neutral
SIGUIENTE: En paralelo Z-Score para single assets
```

### ESCENARIO 3: Quiero jugar seguro (diversificación)
```
RECOMENDACIÓN: Z-Score + Bollinger RSI V3
RAZÓN: Baja correlación, ambas viables
SIGUIENTE: Agregar VWAP si tiempo permite
```

### ESCENARIO 4: Quiero máxima velocidad a producción
```
RECOMENDACIÓN: Z-Score Reversion
RAZÓN: Implementación trivial
TIMING: Hoy mismo (4h)
SIGUIENTE: Pairs Trading en paralelo (1–2 semanas)
```

### ESCENARIO 5: Quiero máxima robustez
```
RECOMENDACIÓN: Ensemble (Z-Score + Bollinger + VWAP)
RAZÓN: 3 señales independientes
VOTING: 2/3 para entrada
SHARPE ESPERADO: +15–25% vs individual
```

---

## ÁRBOL DE DECISIÓN COMPACTO

```
START
  │
  ├─ Tiempo disponible?
  │  ├─ 2h → Z-Score ✅
  │  ├─ 4h → Z-Score + Bollinger ✅
  │  └─ 8h+ → Agrega VWAP + Pairs ✅
  │
  ├─ Objetivo financiero?
  │  ├─ Max Sharpe → Pairs (1.0–1.8)
  │  ├─ Max Consistencia → Z-Score (0.8–1.2)
  │  └─ Max Robustez → Ensemble 3+ ✅
  │
  ├─ Timeframe?
  │  ├─ 1h → VWAP ✅✅ (best fit)
  │  ├─ 4h → Bollinger RSI ✅
  │  └─ 1d → Z-Score ✅
  │
  └─ FIN: Escoge estrategia arriba
```

---

## CHECKLIST PRE-IMPLEMENTACIÓN

```
Antes de codificar, responder:

[ ] ¿Qué timeframe voy a usar? (1h, 4h, 1d)
[ ] ¿Cuántos activos voy a backtestear? (3, 9, todas)
[ ] ¿Qué es "éxito" para mí? (Sharpe, Profit, DD)
[ ] ¿Cuántas horas tengo? (2h, 4h, 8h, 24h)
[ ] ¿Qué tan cómodo estoy con parámetros? (bajo, medio, alto)
[ ] ¿Es para producción o research? (producción, research)
[ ] ¿Qué capital disponible? (pequeño, mediano, grande)
[ ] ¿Risk tolerance? (baja, media, alta)

Una vez respondidas, vuelve a NIVEL 5 y ejecuta.
```

---

## HOJA RÁPIDA: PUNTUACIONES

### Z-Score Reversion
```
Velocidad de implementación:    ⭐⭐⭐⭐⭐ (1–2h)
Complejidad del código:         ⭐⭐☆☆☆ (muy simple)
Sharpe esperado:                ⭐⭐⭐⭐☆ (0.8–1.2)
Robustez en producción:         ⭐⭐⭐⭐☆ (estadística pura)
Número de trades:               ⭐⭐⭐☆☆ (10–30 por mes)
─────────────────────────────────────────
OVERALL: ⭐⭐⭐⭐☆ (4/5) — RECOMENDADO PRIMERO
```

### Bollinger RSI V3
```
Velocidad de implementación:    ⭐⭐⭐⭐☆ (3–4h)
Complejidad del código:         ⭐⭐⭐☆☆ (media)
Sharpe esperado:                ⭐⭐⭐⭐☆ (0.6–1.0)
Robustez en producción:         ⭐⭐⭐⭐☆ (validado en codebase)
Número de trades:               ⭐⭐⭐☆☆ (10–20 por mes)
─────────────────────────────────────────
OVERALL: ⭐⭐⭐⭐☆ (4/5) — RECOMENDADO SEGUNDA
```

### VWAP Intraday
```
Velocidad de implementación:    ⭐⭐⭐☆☆ (2–3h)
Complejidad del código:         ⭐⭐⭐☆☆ (media)
Sharpe esperado:                ⭐⭐⭐⭐☆ (0.7–1.3)
Robustez en producción:         ⭐⭐⭐☆☆ (ciclos intraday)
Número de trades:               ⭐⭐⭐⭐⭐ (20–50 por mes)
─────────────────────────────────────────
OVERALL: ⭐⭐⭐⭐☆ (4/5) — RECOMENDADO TERCERA
```

### Pairs Trading
```
Velocidad de implementación:    ⭐⭐⭐☆☆ (5–6h)
Complejidad del código:         ⭐⭐⭐⭐☆ (alta, 2 patas)
Sharpe esperado:                ⭐⭐⭐⭐⭐ (1.0–1.8)
Robustez en producción:         ⭐⭐⭐⭐⭐ (delta-neutral)
Número de trades:               ⭐⭐☆☆☆ (5–10 por mes)
─────────────────────────────────────────
OVERALL: ⭐⭐⭐⭐⭐ (5/5) — MÁXIMA RENTABILIDAD
```

---

## RECOMENDACIÓN FINAL (RBI Agent)

**Si hoy es tu PRIMER día**: Z-Score
**Si ya tienes backtester**: Z-Score + Bollinger en paralelo
**Si buscas máximo edge**: Pairs Trading
**Si quieres máximo robustez**: Ensemble de 3+

**Ejecución Semanal Sugerida**:
- Lunes: Z-Score
- Miércoles: Bollinger RSI V3
- Viernes: VWAP Intraday
- Semana 2: Pairs Trading

---

**Último update**: 2026-03-15, 04:15 UTC
**Documento**: Decision Matrix v1.0
**Status**: READY TO USE

