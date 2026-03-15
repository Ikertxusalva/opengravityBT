# Visual Strategy Guide — Mean Reversion Crypto
## One-Page Visual Decision Framework

---

## 🎯 DECISION TREE (ASCII)

```
╔════════════════════════════════════════════════════════════════╗
║          ¿QUÉ ESTRATEGIA DEBO IMPLEMENTAR?                    ║
╚════════════════════════════════════════════════════════════════╝

                          START
                            │
                            │
            ┌───────────────┴───────────────┐
            │                               │
        ¿Cuánto    ┌──────────────┐         │
       tiempo?     │              │      ¿Qué es lo
            │      │   2–4 HORAS  │      más importante?
            │      │              │         │
         ┌──┴──┐   └──────────────┘      ┌──┴──┐
         │     │                        │      │
      POCO   MUCHO                 SHARPE  SPEED
      │        │                     │       │
      │        │                  ┌──┴──┐  ┌─┴──┐
      │        │                  │    │  │    │
      ▼        ▼                  ▼    ▼  ▼    ▼
    Z-Score Ensemble          Pairs Z-Score
      │        │            Trading  │
      │        │              │      │
      └────┬───┘              │      │
           │              (SÍ) │ (SÍ) │
           │                  ▼      ▼
           │              1.0–1.8  0.8–1.2
           │              Sharpe  Sharpe
           │
           ▼
    EMPEZAR AQUÍ

═══════════════════════════════════════════════════════════════════
```

---

## 📊 COMPARACIÓN VISUAL (Gráfico de Burbujas)

```
┌─────────────────────────────────────────────────────────────┐
│  COMPLEJIDAD vs SHARPE ESPERADO                             │
│                                                              │
│  Complejidad                                                │
│      ▲                                                       │
│      │                                                       │
│   5  │                                                       │
│      │                           • Pairs Trading (1.0–1.8)   │
│   4  │               • VWAP (0.7–1.3)                       │
│      │               • Bollinger (0.6–1.0)                  │
│   3  │                                                       │
│      │           • Z-Score (0.8–1.2)                        │
│   2  │                                                       │
│      │                                                       │
│   1  │ ★ START HERE                                         │
│      │                                                       │
│      └────────────────────────────────────────────────────── ▶
│        0.5      1.0      1.5      2.0
│                    Sharpe Esperado                           │
│                                                              │
│  Leyenda:                                                    │
│  ★ = Recomendación para comenzar                            │
│  • = Opciones después (por sharpe)                          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## ⚡ TIMELINE DE IMPLEMENTACIÓN

```
SEMANA 1         SEMANA 2         SEMANA 3         SEMANA 4
(BASE)          (VALIDAR)        (EXPANDIR)       (PRODUCCIÓN)

┌─────────┐    ┌─────────┐      ┌─────────┐     ┌─────────┐
│Z-SCORE  │    │GRID     │      │VWAP     │     │PAPER    │
│START    │───▶│SEARCH   │──┐   │TRADING  │    │TRADING  │
│(1h)     │    │ADX/BB   │  │   │START    │    │LIVE 0.1%│
└─────────┘    │PARAMS   │  │   │(1h)     │    │MICRO    │
                │(3 assets)│  │   └─────────┘   │LEVERAGE │
               └─────────┘  │                   └─────────┘
                            │
                            │   ┌─────────┐
                            └──▶│PAIRS    │
                                │TRADING  │
                                │(IF OK)  │
                                └─────────┘
                                    │
                                    ▼
                            ┌─────────────┐
                            │ENSEMBLE OR  │
                            │SINGLE BEST  │
                            │TO PRODUCTION│
                            └─────────────┘

HITO 1: Z-Score viable (Sharpe > 0.5)
HITO 2: Bollinger + Z-Score comparados
HITO 3: VWAP agregado (si tiempo)
HITO 4: Live pequeño si Sharpe ≥ 0.8
```

---

## 🎲 PAYOFF MATRIX (Ganancias por Escenario)

```
┌────────────────────────────────────────────────────────┐
│          RESULTADO ESPERADO POR ESTRATEGIA             │
├────────────────────────────────────────────────────────┤
│ ESTRATEGIA          │ BEST CASE  │ BASE CASE │ WORST   │
├────────────────────────────────────────────────────────┤
│ Z-Score            │  1.2       │  0.8      │  0.5    │
│ Bollinger V3       │  1.0       │  0.6      │  0.3    │
│ VWAP Intraday      │  1.3       │  0.7      │  0.4    │
│ Pairs Trading      │  1.8       │  1.0      │  0.6    │
├────────────────────────────────────────────────────────┤
│ Ensemble (3+)      │  1.5       │  0.9      │  0.7    │
└────────────────────────────────────────────────────────┘

👍 Si esperas Sharpe ≥ 0.8 → Go for Pairs o Ensemble
⚠️ Si esperas rápido viability → Z-Score o VWAP
🚀 Si quieres máximo upside → Pairs Trading
```

---

## 📈 CURVA DE LEARNING

```
EXPERTISE REQUERIDA vs TIEMPO GANADO

            │
Sharpe      │          ● Ensemble
            │         /
            │        /
        1.0 │       /  ● Pairs Trading
            │      /
            │     /
        0.8 │    ●─── VWAP
            │   /  ●
            │  /   │ Bollinger RSI
        0.6 │ /    │
            │/     │
        0.4 │      │ Z-Score ★ START
            │      │
        0.2 │──────┴────────────────────
            │  4h     8h     16h    24h+
            │         TIEMPO INVERTIDO

MORALEJA:
- 4h   → Z-Score (risk-free, quick validation)
- 8h   → + Bollinger (comparativa)
- 16h  → + VWAP (intraday diversity)
- 24h+ → Pairs (máximo reward)
```

---

## 🔴 SEÑALES DE ALERTA

```
┌─────────────────────────────────────────┐
│ STOP: No procedas si ves esto:          │
├─────────────────────────────────────────┤
│ ✗ Sharpe > 1.5 en backtest              │
│   → Probable overfitting                │
│                                          │
│ ✗ Win Rate > 70%                        │
│   → Demasiados pequeños + 1–2 losses    │
│                                          │
│ ✗ Max DD > 40%                          │
│   → Risk inmanejable                    │
│                                          │
│ ✗ Total Trades < 10 por activo          │
│   → Señal demasiado rara                │
│                                          │
│ ✗ SIN ADX filter (ANY estrategia)       │
│   → Garantizado fail en crypto trending │
└─────────────────────────────────────────┘
```

---

## ✅ SEÑALES DE PROCEDER

```
┌─────────────────────────────────────────┐
│ GO: Procede si ves esto:                │
├─────────────────────────────────────────┤
│ ✓ Sharpe 0.5–1.0                        │
│   → Viable, margen para mejora          │
│                                          │
│ ✓ Win Rate 50–55%                       │
│   → Realista, algo de edge              │
│                                          │
│ ✓ Max DD < 30%                          │
│   → Manejable, dormir tranquilo         │
│                                          │
│ ✓ Trades ≥ 20 por activo                │
│   → Muestra estadísticamente válida     │
│                                          │
│ ✓ ADX filter PRESENTE (critico)         │
│   → Reduces whipsaws en trending        │
└─────────────────────────────────────────┘
```

---

## 🎯 QUICK SELECTION (2-Minute Decision)

```
¿Cuál soy?              │ RECOMENDACIÓN
────────────────────────┼───────────────────────────────
Principiante, 4h        │ Z-Score
Tengo experiencia       │ Bollinger RSI V3
Quiero máximo Sharpe    │ Pairs Trading
Quiero máximo speed     │ Z-Score
Quiero máxima robustez  │ Ensemble (3+)
Quiero intraday trades  │ VWAP
Buscoy jugar seguro     │ Z-Score + Bollinger
Tengo tiempo limitado   │ Z-Score ONLY
Tengo capital 2x        │ Pairs Trading
────────────────────────┴───────────────────────────────
```

---

## 📱 CHEAT SHEET (Para tener en escritorio)

```
╔══════════════════════════════════════════════════════════╗
║ MEAN REVERSION CRYPTO — CHEAT SHEET                      ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║ ALWAYS:                                                  ║
║ ☐ ADX > 22 filter (CRITICAL)                             ║
║ ☐ SMA200 direction (CRITICAL)                            ║
║ ☐ Position timeout (40–100 bars)                        ║
║ ☐ ATR-based stops (2× ATR SL, 3× ATR TP)                ║
║                                                          ║
║ FIRST STRATEGY:                                          ║
║ ☐ Z-Score (lookback=20, z=-1.5/+1.5, exit z=0)          ║
║                                                          ║
║ SECOND STRATEGY:                                         ║
║ ☐ Bollinger RSI (BB=20, RSI=14, overbought=65)           ║
║                                                          ║
║ EXPECTED RESULTS:                                        ║
║ ☐ Sharpe ≥ 0.5 (viable)                                  ║
║ ☐ Sharpe ≥ 0.8 (good)                                    ║
║ ☐ Max DD < 30% (comfortable)                             ║
║                                                          ║
║ NEXT STEPS:                                              ║
║ ☐ Paper trade if Sharpe ≥ 0.8                            ║
║ ☐ Live 0.1% micro if consistent 2 weeks                  ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
```

---

## 🔄 ITERACIÓN CYCLE (Per-Week)

```
WEEK 1              WEEK 2              WEEK 3
────────────────    ────────────────    ────────────────

Mon:                Mon:                Mon:
 Z-Score            Grid Search         VWAP Testing
 (1h, 3 assets)     (9 assets)

Wed:                Wed:                Wed:
 Bollinger V3       Parameter Opt       Pairs Trading
 (1h, 3 assets)     (adx, bb period)

Fri:                Fri:                Fri:
 Comparar           Select BEST 2       Ensemble Setup
 Resultados         Strategies          (voting logic)

═══════════════════════════════════════════════════════════

OUTPUT:                OUTPUT:             OUTPUT:
 ✓ 2 strategies       ✓ 1 best strategy    ✓ Ready for
   viable?            per asset?            Paper Trade?
 ✓ Params locked      ✓ Sharpe ≥ 0.8?
 ✓ Edge confirmed     ✓ Robust across
                       9 assets?
```

---

## 💰 POSITION SIZING (Quick Reference)

```
Capital Total = $10,000 (ejemplo)

PER-ASSET ALLOCATION:
  Single Strategy:    $10,000 / 9 assets = ~$1,111/asset
  Dual Strategy:      $10,000 / (9×2) = ~$555/strategy
  Ensemble:           $10,000 / (9×3) = ~$370/strategy

RISK PER TRADE:
  Position Size = 0.95 (95% capital per asset)
  SL = ATR × 2.0 → Risk ~1.5–2% per trade
  TP = ATR × 3.0 → Expected 2.5–3% gain

KELLY CRITERION (if Win Rate known):
  f = (Win% × AvgWin – Loss% × AvgLoss) / AvgWin
  Position Sizing = f / 2 (conservative)

EJEMPLO (Sharpe 0.8):
  ≈ 50–55% Win Rate
  ≈ 1.5:1 Win/Loss Ratio
  → Kelly position ≈ 8–12% capital per asset
  → Conservative: 3–6% per asset
```

---

## 🚨 RED FLAGS vs GREEN LIGHTS

```
RED FLAGS (STOP)      │ GREEN LIGHTS (GO)
──────────────────────┼──────────────────────
X No ADX filter       │ ✓ ADX filter present
X Sharpe > 1.5        │ ✓ Sharpe 0.5–1.0
X Win Rate > 70%      │ ✓ Win Rate 50–55%
X Max DD > 40%        │ ✓ Max DD < 30%
X Trades < 10         │ ✓ Trades ≥ 20
X No SMA200 check     │ ✓ SMA200 direction OK
X No position timeout │ ✓ Max hold implemented
X No stop loss        │ ✓ ATR-based SL/TP
──────────────────────┼──────────────────────
           FAIL       │           PASS
```

---

## 📞 FREQUENTLY ASKED

```
Q: "¿Cuál estrategia elegir?"
A: Z-Score primero (fastest), luego Bollinger V3

Q: "¿Cuánto tiempo toma?"
A: Z-Score: 1–2h | Bollinger: 3–4h | VWAP: 2–3h | Pairs: 5–6h

Q: "¿Cuál tiene mejor Sharpe?"
A: Pairs (1.0–1.8) > VWAP (0.7–1.3) > Z-Score (0.8–1.2) = Bollinger (0.6–1.0)

Q: "¿Puedo implementar todas?"
A: SÍ, pero comenzar con Z-Score solo, agregar otras gradualmente

Q: "¿Cuándo voy live?"
A: Solo si Sharpe ≥ 0.8 + Paper trading 2 semanas OK + Max DD < 20%

Q: "¿ADX filter es obligatorio?"
A: SÍ. Sin él, crypto trending te destruye.
```

---

**Visual Guide v1.0**
**Generated**: 2026-03-15
**Status**: READY TO PRINT & PIN TO WALL

