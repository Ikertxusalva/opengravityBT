# Swarm Bus Protocol v2.1

## Reglas del Event Bus

Eres parte de un sistema multi-agente coordinado. El orquestador es código TypeScript en `pty-manager.ts`, NO un LLM.

### Cómo escribir al bus

Cuando detectes una señal relevante, escribe al bus usando este comando en tu terminal:

```bash
echo '{"channel":"realtime","from":"TU_AGENT_ID","type":"signal","symbol":"BTC","direction":"LONG","confidence":0.85,"reason":"descripción corta"}' >> .claude/swarm-bus/events.jsonl
```

### Campos obligatorios

| Campo | Tipo | Valores |
|-------|------|---------|
| channel | string | `realtime` (urgente) o `research` (puede esperar) |
| from | string | Tu agent ID exacto (ej: `funding-agent`) |
| type | string | `signal`, `analysis`, `veto`, `result`, `finding` |
| symbol | string | Ticker del activo (ej: `BTC`, `ETH`, `SOL`) |
| direction | string | `LONG`, `SHORT`, o `NEUTRAL` |
| confidence | number | 0.0 a 1.0 |
| reason | string | Explicación concisa de la señal |

### Cuándo escribir al bus

**Sensor (funding-agent, liquidation-agent, top-mover-agent):**
- Funding APY > 100% anualizado → signal con priority 2
- Cambio de funding > 50% en 1h → signal con priority 1
- Liquidación masiva (> $10M) → signal con priority 1
- Top mover > 15% en 24h → signal con priority 3

**Confirmador (chart-agent):**
- Solo cuando el orquestador te convoque con `[SWARM CONVOCATION]`
- Responde con `type: "analysis"` y tu evaluación técnica

**Validador (risk-agent):**
- Solo cuando el orquestador te convoque con `[SWARM CONVOCATION]`
- Si el riesgo es inaceptable: `type: "veto"` con razón
- Si el riesgo es aceptable: `type: "analysis"` con tu evaluación

**Ejecutor (trading-agent):**
- Solo cuando recibas `[SWARM ORDER]` del orquestador
- Ejecuta la operación y escribe `type: "result"` al bus

**Investigador (rbi-agent, strategy-agent):**
- Usa `channel: "research"` para hallazgos
- `type: "finding"` con la estrategia o variación descubierta

### TTL (Time To Live)

- Realtime: 300 segundos (5 min). Si tu señal no se procesa en 5 min, se descarta.
- Research: 86400 segundos (24h).

### Reglas de conflicto (ejecuta el orquestador, NO tú)

1. **Veto de Risk = absoluto.** Si risk-agent dice NO, se cancela. Sin excepciones.
2. **Consenso 2/3.** Se necesitan 2+ de 3 fuentes (funding, chart, stress) coincidiendo.
3. **Weighted scoring.** funding 40%, chart 35%, stress 25%.

### NO hagas esto

- NO intentes orquestar a otros agentes
- NO esperes respuestas de otros agentes
- NO modifiques archivos de otros agentes
- NO ignores las convocatorias `[SWARM CONVOCATION]`
- NO escribas múltiples señales por la misma anomalía (una señal por evento)
