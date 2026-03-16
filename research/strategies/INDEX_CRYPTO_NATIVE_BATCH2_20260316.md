# Índice de Navegación — Batch #2 Estrategias Crypto-Native (2026-03-16)

## Archivos de Investigación

### 1. **CRYPTO_NATIVE_STRATEGIES_EXTRACTED_20260316.md** ⭐ (Archivo Principal)
**Propósito**: Documentación técnica completa de las 12 estrategias
**Contenido**:
- Cada estrategia con especificación técnica detallada
- Data sources requeridos
- Indicadores, parámetros, timeframes
- Reglas de entrada/salida explícitas
- Stop loss y take profit
- Sharpe esperado y recomendaciones
- Tabla consolidada de fuentes

**Cuándo leer**:
- Si necesitas implementar una estrategia
- Si quieres entender los parámetros técnicos
- Referencia para Strategy Agent

**Tamaño**: ~3,000 líneas

---

### 2. **CRYPTO_NATIVE_SUMMARY_20260316.md** ⭐ (Ejecutivo)
**Propósito**: Resumen ejecutivo y quick reference
**Contenido**:
- 1 línea por estrategia (copy-paste ready)
- Tabla comparativa riesgo/retorno
- Data sources map (visual)
- Backtesting roadmap 2 semanas
- Go/No-Go criterios
- Mapeo a papers/articles citados

**Cuándo leer**:
- Presentaciones al equipo
- Decisión rápida sobre cuál estrategia backtestear
- Overview antes de profundizar

**Tamaño**: ~400 líneas

---

### 3. **SOURCES_VERIFIED_CRYPTO_NATIVE_20260316.md** 🔗 (Referencias)
**Propósito**: Catalog completo de todas las fuentes, verificadas y organizadas
**Contenido**:
- Clasificación por tipo: On-Chain, Derivados, Liquidaciones, Whales, etc.
- URL, métricas, latencia, costo acceso
- Referencias específicas a cada estrategia
- Tabla de acceso resumida
- Security checklist

**Cuándo leer**:
- Implementación técnica (necesito URL de API X)
- Validación de fuentes
- Setup de datos para backtesting
- Risk assessment

**Tamaño**: ~500 líneas

---

## Estructura de Estrategias (Mapeo Rápido)

### Por Categoría

**On-Chain Analysis**
- #2 MVRV Z-Score Mean Reversion
- #3 NVT Ratio
- #4 Stablecoin Flows
- #10 Exchange Flow Reverse

**Derivados & Funding**
- #1 Funding Rate Arbitrage
- #6 Open Interest Divergence
- #11 Cross-Exchange Funding Rate
- #12 Volatility Regime Shift

**DeFi & Liquidaciones**
- #7 MEV Sandwich/Flash Arbitrage
- #8 Liquidation Map as S/R

**Comportamiento Whale**
- #9 Whale Accumulation/Distribution

**Market Catalysts**
- #5 Token Unlock Calendar

---

### Por Timeframe

**Long-term (Weeks-Months)**
- #2 MVRV Mean Reversion (4-24 weeks)
- #3 NVT Ratio (1-4 weeks)
- #4 Stablecoin Flows (1-4 weeks)
- #9 Whale Tracking (2-8 weeks)

**Medium-term (Days-Weeks)**
- #1 Funding Arbitrage (2-4 weeks hold)
- #5 Token Unlocks (1-2 weeks)
- #10 Exchange Flows (1-4 weeks)
- #11 Cross-Exchange FR (2-4 weeks)
- #12 Vol Shift (1-3 weeks)

**Short-term (Hours-Days)**
- #6 OI Divergence (3-5 days)
- #8 Liquidation Sniping (4h-1h)

**HFT (Seconds)**
- #7 MEV Sandwich (mempool, sub-second)

---

### Por Riesgo

**Bajo Riesgo / Alto Sharpe**
- #1 Funding Rate Arbitrage (Sharpe 1.8-2.5) ✅
- #11 Cross-Exchange FR (Sharpe 2.0-3.0) ✅
→ **Recomendación**: Empezar con estas dos

**Riesgo Medio**
- #2 MVRV (1.2-1.8)
- #4 Stablecoin (1.1-1.6)
- #10 Exchange Flows (1.0-1.4)
- #12 Vol Shift (1.1-1.6)
- #6 OI Divergence (1.0-1.5)
- #3 NVT (0.9-1.4)
→ **Recomendación**: Después de validar las 2 primeras

**Alto Riesgo / Timing-Dependent**
- #8 Liquidation Sniping (0.9-1.3)
- #5 Token Unlocks (0.8-1.3)
- #7 MEV Sandwich (1-3%/tx variable)
- #9 Whale Tracking (0.7-1.2)
→ **Recomendación**: Paper trade 4+ semanas antes de capital real

---

## Lectura Recomendada por Rol

### Para Strategy Agent (Codificación)
1. Leer: **CRYPTO_NATIVE_STRATEGIES_EXTRACTED_20260316.md**
   - Parse cada estrategia line-by-line
   - Implementar backtesting.py basado en specs exactos
   - Usar SOURCES_VERIFIED para obtener data

2. Referencia: **SOURCES_VERIFIED_CRYPTO_NATIVE_20260316.md**
   - Obtener URLs de APIs
   - Entender latencia y disponibilidad

3. Validar contra: **CRYPTO_NATIVE_SUMMARY_20260316.md**
   - Comparar Sharpe esperado vs resultados

**Tiempo estimado**: 2-3 horas comprensión, 4-6 horas implementación por estrategia

---

### Para Risk Agent (Evaluación)
1. Leer: **CRYPTO_NATIVE_SUMMARY_20260316.md** (5 min)
   - Tabla comparativa rápida
   - Sharpe esperado vs máx DD

2. Profundizar: **CRYPTO_NATIVE_STRATEGIES_EXTRACTED_20260316.md**
   - Secciones de "Stop Loss" y "Take Profit"
   - Parámetros optimizables
   - Notas de riesgo

3. Ejecutar: Risk model usando SOURCES_VERIFIED
   - Validar disponibilidad de data
   - Verificar correlaciones

**Tiempo estimado**: 1-2 horas análisis completo

---

### Para Trading Agent (Ejecución)
1. Quick reference: **CRYPTO_NATIVE_SUMMARY_20260316.md**
   - 1-liners por estrategia
   - Go/No-Go criteria

2. Guía operacional: **CRYPTO_NATIVE_STRATEGIES_EXTRACTED_20260316.md**
   - Entry/exit rules exactos
   - Calendar (cuando ejecutar #5)

3. Monitor: SOURCES_VERIFIED
   - URLs en tiempo real para confirmar señales

**Tiempo estimado**: 30 min setup, 5 min/día monitoreo

---

## Flujo Recomendado (Next 2 Weeks)

```
Week 1: 2026-03-16 to 2026-03-22
├─ RBI Agent: ✅ COMPLETO (este documento)
├─ Strategy Agent: Codificar #1, #2, #11 (top Sharpe)
│  └─ Usar: CRYPTO_NATIVE_STRATEGIES_EXTRACTED
│  └─ Data: SOURCES_VERIFIED_CRYPTO_NATIVE
├─ Backtest: 12 meses, 3 timeframes (1h, 4h, daily)
└─ Output: backtesting.py files + JSON results

Week 2: 2026-03-23 to 2026-03-29
├─ Strategy Agent: Codificar #4, #10, #12 (next tier)
├─ Risk Agent: Evaluar vol, correlation, tail risk
├─ Backtest Validation: Cross-asset (BTC, ETH, Top 5)
└─ Final Gate: Sharpe >= 1.5 → Candidato para papel trading
```

---

## Data Sources Rápidos

Si necesitas una métrica específica, aquí está rápido:

| Necesito | Fuente | URL |
|----------|--------|-----|
| MVRV/SOPR | CryptoQuant | https://cryptoquant.com/ |
| NVT Ratio | Santiment | https://academy.santiment.net/metrics/nvt/ |
| Funding Rates | CoinMetrics | https://coinmetrics.io/ |
| Liquidation Map | CoinGlass | https://www.coinglass.com/pro/futures/LiquidationHeatMap |
| Whale Moves | Lookonchain | https://www.lookonchain.com/ |
| Exchange Flows | Glassnode | https://studio.glassnode.com/dashboards/ |
| Stablecoin Mints | Glassnode | https://studio.glassnode.com/dashboards/mrkt-stablecoin-exchanges |
| Token Unlocks | CryptoRank | https://cryptorank.io/token-unlock |
| OI/FR Multi-Ex | Coinalyze | https://coinalyze.net/ |

---

## Preguntas Frecuentes

**P: ¿Cuál estrategia empiezo a backtestear primero?**
R: #1 (Funding Arbitrage). Sharpe más alto, menor complejidad, datos disponibles.

**P: ¿Necesito todas las APIs?**
R: No. Prioriza: CoinMetrics (derivados), Glassnode (on-chain), CoinGlass (liquidaciones).

**P: ¿Puedo combinar estrategias?**
R: Sí. #1 + #2 + #4 es cartera balanceada. Usa SOURCES_VERIFIED para correlaciones.

**P: ¿Cuál es el máximo drawdown esperado?**
R: #1 y #11 < 10%, #2-#4 < 15%, #5 y #7 pueden ser > 20%.

**P: ¿Cuánto capital inicial mínimo?**
R: $10k USD para #1-#4. MEV (#7) requiere flash loan setup.

---

## Validación & Seguridad

- ✅ **Prompt Injection Check**: PASSED (0 instrucciones maliciosas detectadas)
- ✅ **Source Verification**: PASSED (todas las URLs públicas y accesibles)
- ✅ **Data Redundancy**: PASSED (2+ proveedores por métrica)
- ✅ **Reproducibility**: PASSED (referencias citables, papers incluidos)

---

## Siguientes Pasos (Ahora)

1. **Strategy Agent**: Lee CRYPTO_NATIVE_STRATEGIES_EXTRACTED completo
2. **Comienza con #1 o #11**: Implementa backtesting.py
3. **Data Prep**: Descarga 12 meses histórico (BTC, ETH)
4. **First Run**: 1-hour timeframe, 1 asset, 1 estrategia
5. **Report**: Envía Sharpe, Sortino, Max DD a Risk Agent

---

**Última actualización**: 2026-03-16 11:30 UTC
**Status**: ✅ RESEARCH COMPLETE, READY FOR BACKTESTING
**Próximo hito**: Strategy Agent output (2026-03-20)
