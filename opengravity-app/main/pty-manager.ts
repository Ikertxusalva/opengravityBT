/**
 * PTY Manager — Spawns and manages Claude Code terminal sessions.
 *
 * Hardened for stability with 3+ concurrent terminals on Windows.
 * Key protections:
 * - All pty.write/kill/resize wrapped in try-catch (EPIPE protection)
 * - Robust Windows kill with taskkill /T /F fallback
 * - Global uncaughtException handler for native module crashes
 * - Async context saving (non-blocking main thread)
 * - Throttled resize IPC
 */
import { spawn, IPty } from 'node-pty';
import { ipcMain, BrowserWindow } from 'electron';
import * as os from 'os';
import * as path from 'path';
import * as fs from 'fs';
import { execFile } from 'child_process';
import { AuditLog } from './security/audit';
import { Vault } from './security/vault';
import { MemoryManager } from './memory-manager';
import * as SwarmBus from './lib/swarm-bus/bus';
import { resolve as resolveConflict, isWorthInvestigating } from './lib/swarm-bus/conflict-resolver';
import {
  SwarmEvent, AgentName, AgentResponse, CircuitState, Direction,
  THRESHOLDS,
} from './lib/swarm-bus/types';

// ── Active PTY sessions ──
const sessions: Map<string, IPty> = new Map();
const agentMap: Map<string, string> = new Map(); // termId → agentId

// ── Pending orders awaiting user confirmation ──
const pendingOrders: Map<string, any> = new Map();
let _mainWindow: BrowserWindow | null = null;

// ── Circuit Breaker (simple Map) ──
const circuitBreaker: Map<string, CircuitState> = new Map();

function onAgentError(agentName: string, error: string) {
  const state = circuitBreaker.get(agentName) || { errorCount: 0 };
  state.errorCount++;
  state.lastError = error;
  if (state.errorCount >= THRESHOLDS.CIRCUIT_BREAKER_MAX) {
    state.disabledAt = new Date().toISOString();
    console.error(`[Swarm] Circuit OPEN for ${agentName}: ${state.errorCount} consecutive errors`);
  }
  circuitBreaker.set(agentName, state);
}

function onAgentSuccess(agentName: string) {
  circuitBreaker.set(agentName, { errorCount: 0 });
}

function isAgentDisabled(agentName: string): boolean {
  const state = circuitBreaker.get(agentName);
  if (!state || state.errorCount < THRESHOLDS.CIRCUIT_BREAKER_MAX) return false;
  // Auto health-check: re-enable after 5 min
  if (state.disabledAt) {
    const elapsed = Date.now() - new Date(state.disabledAt).getTime();
    if (elapsed > THRESHOLDS.HEALTH_CHECK_INTERVAL) {
      state.errorCount = THRESHOLDS.CIRCUIT_BREAKER_MAX - 1; // HALF_OPEN: one more error re-disables
      state.lastHealthCheck = new Date().toISOString();
      circuitBreaker.set(agentName, state);
      console.log(`[Swarm] Circuit HALF_OPEN for ${agentName} (health check)`);
      return false;
    }
  }
  return true;
}

// ── Swarm Orchestration ──

/**
 * Invoke an agent by injecting a prompt into its running PTY.
 * If the agent is not running, falls back to deterministic analysis
 * using Railway API data. The swarm NEVER stops because a terminal is closed.
 */
function invokeAgent(
  agentName: AgentName,
  prompt: string,
  opts: { timeout: number } = { timeout: THRESHOLDS.AGENT_TIMEOUT }
): Promise<AgentResponse> {
  return new Promise((resolve) => {
    if (isAgentDisabled(agentName)) {
      console.log(`[Swarm] ${agentName} circuit OPEN — using deterministic fallback`);
      deterministicFallback(agentName, prompt).then(resolve);
      return;
    }

    // Find the agent's running PTY
    let targetTermId: string | null = null;
    for (const [termId, agId] of agentMap.entries()) {
      if (agId === agentName && sessions.has(termId)) {
        targetTermId = termId;
        break;
      }
    }

    if (!targetTermId) {
      console.log(`[Swarm] ${agentName} not running — using deterministic fallback`);
      deterministicFallback(agentName, prompt).then(resolve);
      return;
    }

    // Inject the analysis prompt
    const pty = sessions.get(targetTermId);
    const ok = safePtyWrite(pty, prompt + '\r');
    if (!ok) {
      onAgentError(agentName, 'PTY write failed');
      console.log(`[Swarm] ${agentName} PTY write failed — using deterministic fallback`);
      deterministicFallback(agentName, prompt).then(resolve);
      return;
    }

    console.log(`[Swarm] ${agentName} convoked via PTY — waiting for response...`);

    // Poll the bus for this agent's response
    const startTime = Date.now();
    const pollInterval = setInterval(() => {
      const events = SwarmBus.readFrom(agentName);
      const response = events.find(e =>
        new Date(e.timestamp).getTime() > startTime &&
        (e.type === 'analysis' || e.type === 'veto')
      );

      if (response) {
        clearInterval(pollInterval);
        onAgentSuccess(agentName);
        console.log(`[Swarm] ${agentName} responded via bus: ${response.payload.direction}@${response.payload.confidence}`);
        resolve({
          agent: agentName,
          type: response.type as any,
          direction: (response.payload.direction as Direction) || 'NEUTRAL',
          confidence: (response.payload.confidence as number) || 0,
          reason: (response.payload.reason as string) || '',
          timedOut: false,
          payload: response.payload,
        });
        return;
      }

      if (Date.now() - startTime > opts.timeout) {
        clearInterval(pollInterval);
        console.warn(`[Swarm] ${agentName} timed out after ${opts.timeout}ms — using deterministic fallback`);
        deterministicFallback(agentName, prompt).then(resolve);
      }
    }, 500);
  });
}

// ── Deterministic Fallback ──
// When an agent is not running or times out, use Railway API data
// and hardcoded rules to produce an analysis. No LLM needed.

async function deterministicFallback(agentName: AgentName, prompt: string): Promise<AgentResponse> {
  // Extract symbol from the convocation prompt
  const symbolMatch = prompt.match(/symbol[:\s]*["']?(\w+)/i) || prompt.match(/para (\w+)/i);
  const symbol = symbolMatch?.[1]?.toUpperCase() || 'BTC';

  try {
    if (agentName === 'chart-agent') {
      return await fallbackChart(symbol);
    } else if (agentName === 'risk-agent') {
      return await fallbackRisk(symbol);
    } else if (agentName === 'funding-agent') {
      return await fallbackFunding(symbol);
    }
  } catch (e) {
    console.error(`[Swarm] Deterministic fallback failed for ${agentName}:`, e);
  }

  // Ultimate fallback: NEUTRAL with 0 confidence
  return {
    agent: agentName,
    type: 'analysis',
    direction: 'NEUTRAL',
    confidence: 0,
    reason: `Fallback: no data available for ${agentName}`,
    timedOut: false,
  };
}

/**
 * Chart fallback: fetch candles from Railway, compute SMA cross + RSI.
 * SMA20 > SMA50 = LONG, SMA20 < SMA50 = SHORT, else NEUTRAL.
 */
async function fallbackChart(symbol: string): Promise<AgentResponse> {
  const resp = await fetch(`${CLOUD}/api/hl/candles/${symbol}?interval=1h&count=60`);
  if (!resp.ok) throw new Error(`Candles API ${resp.status}`);
  const data = await resp.json();
  const candles: number[] = (data.candles || data || []).map((c: any) => parseFloat(c.close || c.c || c[4] || 0));

  if (candles.length < 50) {
    return { agent: 'chart-agent', type: 'analysis', direction: 'NEUTRAL', confidence: 0.2,
      reason: `Insufficient candles (${candles.length})`, timedOut: false };
  }

  // SMA20 vs SMA50
  const sma = (arr: number[], period: number) => {
    const slice = arr.slice(-period);
    return slice.reduce((a, b) => a + b, 0) / slice.length;
  };
  const sma20 = sma(candles, 20);
  const sma50 = sma(candles, 50);
  const price = candles[candles.length - 1];

  // RSI(14)
  const gains: number[] = [];
  const losses: number[] = [];
  for (let i = candles.length - 14; i < candles.length; i++) {
    const diff = candles[i] - candles[i - 1];
    gains.push(diff > 0 ? diff : 0);
    losses.push(diff < 0 ? -diff : 0);
  }
  const avgGain = gains.reduce((a, b) => a + b, 0) / 14;
  const avgLoss = losses.reduce((a, b) => a + b, 0) / 14;
  const rsi = avgLoss === 0 ? 100 : 100 - (100 / (1 + avgGain / avgLoss));

  let direction: Direction = 'NEUTRAL';
  let confidence = 0.4;
  const reasons: string[] = [];

  // Trend: SMA cross
  if (sma20 > sma50 * 1.002) {
    direction = 'LONG';
    reasons.push(`SMA20(${sma20.toFixed(0)}) > SMA50(${sma50.toFixed(0)})`);
    confidence += 0.15;
  } else if (sma20 < sma50 * 0.998) {
    direction = 'SHORT';
    reasons.push(`SMA20(${sma20.toFixed(0)}) < SMA50(${sma50.toFixed(0)})`);
    confidence += 0.15;
  }

  // RSI confirmation
  if (rsi < 30 && direction !== 'SHORT') {
    direction = 'LONG';
    reasons.push(`RSI oversold (${rsi.toFixed(0)})`);
    confidence += 0.15;
  } else if (rsi > 70 && direction !== 'LONG') {
    direction = 'SHORT';
    reasons.push(`RSI overbought (${rsi.toFixed(0)})`);
    confidence += 0.15;
  } else {
    reasons.push(`RSI neutral (${rsi.toFixed(0)})`);
  }

  // Price above/below SMAs
  if (price > sma20 && price > sma50 && direction === 'LONG') confidence += 0.1;
  if (price < sma20 && price < sma50 && direction === 'SHORT') confidence += 0.1;

  confidence = Math.min(confidence, 0.95);

  console.log(`[Swarm] chart-agent fallback: ${symbol} ${direction} @ ${confidence.toFixed(2)} — ${reasons.join(', ')}`);
  return {
    agent: 'chart-agent', type: 'analysis', direction,
    confidence: parseFloat(confidence.toFixed(2)),
    reason: `[Deterministic] ${reasons.join('; ')}`,
    timedOut: false,
  };
}

/**
 * Risk fallback: fetch stress index + funding from Railway.
 * Stress score > 80 = VETO. Funding extreme + high stress = lower confidence.
 */
async function fallbackRisk(symbol: string): Promise<AgentResponse> {
  const [stressResp, fundingResp] = await Promise.all([
    fetch(`${CLOUD}/api/market/snapshot`).catch(() => null),
    fetch(`${CLOUD}/api/hl/funding`).catch(() => null),
  ]);

  let stressScore = 0;
  let fundingAnnual = 0;

  if (stressResp?.ok) {
    const snapshot = await stressResp.json();
    const rankings = snapshot.stress || [];
    const coinStress = rankings.find((r: any) => r.coin === symbol || r.symbol === symbol);
    stressScore = coinStress?.stress_score || coinStress?.score || 0;
  }

  if (fundingResp?.ok) {
    const fundingData = await fundingResp.json();
    const rates = fundingData.rates || [];
    const coinFunding = rates.find((r: any) => r.coin === symbol);
    fundingAnnual = coinFunding?.annual_pct || 0;
  }

  // VETO conditions
  if (stressScore > 80) {
    console.log(`[Swarm] risk-agent fallback VETO: stress score ${stressScore} > 80`);
    return {
      agent: 'risk-agent', type: 'veto', direction: 'NEUTRAL',
      confidence: 0.9,
      reason: `[Deterministic VETO] Stress score ${stressScore}/100 exceeds safety threshold`,
      timedOut: false,
    };
  }

  if (Math.abs(fundingAnnual) > 200) {
    console.log(`[Swarm] risk-agent fallback VETO: extreme funding ${fundingAnnual}%`);
    return {
      agent: 'risk-agent', type: 'veto', direction: 'NEUTRAL',
      confidence: 0.85,
      reason: `[Deterministic VETO] Extreme funding ${fundingAnnual.toFixed(0)}% annual — liquidation risk`,
      timedOut: false,
    };
  }

  // Normal analysis
  let direction: Direction = 'NEUTRAL';
  let confidence = 0.5;
  const reasons: string[] = [`stress: ${stressScore}/100`, `funding: ${fundingAnnual.toFixed(1)}%`];

  // Low stress = safer to trade
  if (stressScore < 30) {
    confidence += 0.2;
    reasons.push('low stress environment');
  } else if (stressScore < 60) {
    confidence += 0.1;
    reasons.push('moderate stress');
  } else {
    confidence -= 0.1;
    reasons.push('elevated stress — reduced size recommended');
  }

  // Funding direction hint
  if (fundingAnnual < -10) {
    direction = 'LONG';
    reasons.push('negative funding favors longs');
  } else if (fundingAnnual > 50) {
    direction = 'SHORT';
    reasons.push('high funding pressure on longs');
  }

  confidence = Math.max(0.1, Math.min(confidence, 0.95));

  console.log(`[Swarm] risk-agent fallback: ${direction} @ ${confidence.toFixed(2)} — ${reasons.join(', ')}`);
  return {
    agent: 'risk-agent', type: 'analysis', direction,
    confidence: parseFloat(confidence.toFixed(2)),
    reason: `[Deterministic] ${reasons.join('; ')}`,
    timedOut: false,
  };
}

/**
 * Funding fallback: fetch funding rates from Railway.
 * Already a sensor, so this mainly confirms the signal with fresh data.
 */
async function fallbackFunding(symbol: string): Promise<AgentResponse> {
  const resp = await fetch(`${CLOUD}/api/hl/funding`);
  if (!resp.ok) throw new Error(`Funding API ${resp.status}`);
  const data = await resp.json();
  const rates = data.rates || [];
  const coin = rates.find((r: any) => r.coin === symbol);

  if (!coin) {
    return { agent: 'funding-agent', type: 'analysis', direction: 'NEUTRAL', confidence: 0.1,
      reason: `No funding data for ${symbol}`, timedOut: false };
  }

  const annual = coin.annual_pct || 0;
  let direction: Direction = 'NEUTRAL';
  let confidence = 0.5;
  const reasons: string[] = [`${symbol} funding: ${annual.toFixed(1)}% annual (${coin.sentiment})`];

  if (annual < -5) {
    direction = 'LONG';
    confidence = Math.min(0.9, 0.5 + Math.abs(annual) / 100);
    reasons.push('negative funding = shorts paying longs');
  } else if (annual > 50) {
    direction = 'SHORT';
    confidence = Math.min(0.9, 0.5 + annual / 200);
    reasons.push('extreme positive funding = overleveraged longs');
  } else if (annual > 20) {
    direction = 'SHORT';
    confidence = 0.4;
    reasons.push('elevated funding');
  }

  console.log(`[Swarm] funding-agent fallback: ${direction} @ ${confidence.toFixed(2)} — ${reasons.join(', ')}`);
  return {
    agent: 'funding-agent', type: 'analysis', direction,
    confidence: parseFloat(confidence.toFixed(2)),
    reason: `[Deterministic] ${reasons.join('; ')}`,
    timedOut: false,
  };
}

/**
 * Process a realtime signal event from the bus.
 * This is the core orchestration loop:
 * 1. Receive signal from sensor (funding/stress)
 * 2. Convoke chart + risk in parallel
 * 3. Apply conflict resolution rules
 * 4. Send order to trading-agent if approved
 */
async function processRealtimeSignal(event: SwarmEvent) {
  const symbol = (event.payload.symbol as string) || 'BTC';
  const direction = (event.payload.direction as Direction) || 'NEUTRAL';
  const confidence = (event.payload.confidence as number) || 0;

  // Pre-filter: skip weak signals
  if (!isWorthInvestigating({ direction, confidence })) {
    console.log(`[Swarm] Skipping weak signal from ${event.from}: ${direction} @ ${confidence}`);
    return;
  }

  console.log(`[Swarm] Processing signal: ${event.from} → ${symbol} ${direction} (${confidence})`);
  SwarmBus.setStatus('processing', `signal_${symbol}`);

  // Build analysis prompt for convoked agents
  const analysisPrompt = `[SWARM CONVOCATION] ${symbol} — señal ${direction} (${(confidence * 100).toFixed(0)}%) de ${event.from}.
Razón: ${event.payload.reason || 'N/A'}

RESPONDE EJECUTANDO ESTE COMANDO (cambia direction, confidence y reason):
echo '{"channel":"realtime","from":"TU_AGENT_ID","type":"analysis","timestamp":"${new Date().toISOString()}","ttl":300,"priority":2,"payload":{"symbol":"${symbol}","direction":"LONG","confidence":0.7,"reason":"tu análisis corto"}}' >> .claude/swarm-bus/events.jsonl

Si el riesgo es inaceptable, usa "type":"veto" en vez de "analysis".
Tienes 30 segundos. Solo ejecuta el echo, nada más.`;

  // Convoke chart + risk EN PARALELO (Promise.all)
  const [chartResult, riskResult] = await Promise.all([
    invokeAgent('chart-agent', analysisPrompt),
    invokeAgent('risk-agent', analysisPrompt),
  ]);

  console.log(`[Swarm] Responses: chart=${chartResult.direction}@${chartResult.confidence} risk=${riskResult.timedOut ? 'TIMEOUT' : riskResult.direction}@${riskResult.confidence}`);

  // Build funding response from the original signal
  const fundingResult: AgentResponse = {
    agent: event.from as AgentName,
    type: 'signal',
    direction,
    confidence,
    reason: (event.payload.reason as string) || '',
    timedOut: false,
  };

  // Apply conflict resolution (3 rules)
  const decision = resolveConflict({
    funding: fundingResult,
    chart: chartResult,
    risk: riskResult,
  });

  console.log(`[Swarm] Decision: ${decision.action} — ${decision.reason}`);

  // Publish decision to bus
  SwarmBus.publish({
    channel: 'realtime',
    from: 'claude-main',
    type: decision.action === 'EXECUTE' ? 'order' : 'result',
    priority: decision.action === 'EXECUTE' ? 1 : 3,
    payload: {
      symbol,
      action: decision.action,
      direction: decision.direction,
      size: decision.size,
      score: decision.score,
      reason: decision.reason,
      sources: decision.sources,
      funding: { direction: fundingResult.direction, confidence: fundingResult.confidence },
      chart: { direction: chartResult.direction, confidence: chartResult.confidence, timedOut: chartResult.timedOut },
      risk: { direction: riskResult.direction, confidence: riskResult.confidence, timedOut: riskResult.timedOut, type: riskResult.type },
    },
  });

  // If EXECUTE: request manual confirmation from user before executing
  if (decision.action === 'EXECUTE' && decision.direction && decision.size) {
    const pendingOrder = {
      id: `order-${Date.now()}`,
      symbol,
      direction: decision.direction,
      size: decision.size,
      score: decision.score,
      priority: event.priority || 2,  // Pass signal priority for order type selection
      reason: decision.reason,
      sources: decision.sources,
      funding: { direction: fundingResult.direction, confidence: fundingResult.confidence, reason: fundingResult.reason },
      chart: { direction: chartResult.direction, confidence: chartResult.confidence, reason: chartResult.reason },
      risk: { direction: riskResult.direction, confidence: riskResult.confidence, reason: riskResult.reason },
      timestamp: new Date().toISOString(),
    };

    // Store pending order for confirmation
    pendingOrders.set(pendingOrder.id, pendingOrder);
    console.log(`[Swarm] Order pending confirmation: ${pendingOrder.id} — ${symbol} ${decision.direction} ${decision.size}`);

    // Auto-confirm on testnet, manual on mainnet
    const isTestnet = !process.env.HL_MAINNET_MODE;
    if (isTestnet && process.env.HL_TESTNET_PRIVATE_KEY) {
      console.log(`[Swarm] Auto-confirming testnet order: ${pendingOrder.id}`);
      pendingOrders.delete(pendingOrder.id);
      const result = await executeHLOrder(pendingOrder);
      console.log(`[Swarm] Auto-execution result:`, JSON.stringify(result));
      if (_mainWindow && !_mainWindow.isDestroyed()) {
        _mainWindow.webContents.send('swarm-order-executed', { orderId: pendingOrder.id, result });
      }
    } else {
      // Notify frontend for manual confirmation (mainnet)
      if (_mainWindow && !_mainWindow.isDestroyed()) {
        _mainWindow.webContents.send('swarm-order-pending', pendingOrder);
      }
    }
  }

  // Sync decision to Railway
  try {
    const token = await Vault.get('OPENGRAVITY_API_TOKEN');
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    fetch(`${CLOUD}/api/swarm/decision`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        workflow: 'realtime_signal',
        symbol,
        decision: decision.action,
        consensus_score: decision.score || 0,
        confidence_avg: ((fundingResult.confidence + chartResult.confidence + riskResult.confidence) / 3) * 100,
        votes: JSON.stringify({
          [fundingResult.agent]: { vote: fundingResult.direction, confidence: fundingResult.confidence, reasoning: fundingResult.reason },
          [chartResult.agent]: { vote: chartResult.direction, confidence: chartResult.confidence, reasoning: chartResult.reason },
          [riskResult.agent]: { vote: riskResult.direction, confidence: riskResult.confidence, reasoning: riskResult.reason },
        }),
      }),
    }).catch(() => {});
  } catch {}

  SwarmBus.setStatus('idle');
}

// ── Bus listener (polls for new signals) ──
let busListenerTimer: ReturnType<typeof setInterval> | null = null;
const processedEvents = new Set<string>(); // Track processed event IDs

function eventKey(event: SwarmEvent): string {
  // Use id if available, otherwise hash from+timestamp+payload for dedup
  return event.id || `${event.from}:${event.timestamp}:${JSON.stringify(event.payload).slice(0, 80)}`;
}

function startBusListener() {
  if (busListenerTimer) return;
  busListenerTimer = setInterval(() => {
    const signals = SwarmBus.readByType('signal', 'realtime');
    for (const event of signals) {
      const key = eventKey(event);
      if (processedEvents.has(key)) continue;
      processedEvents.add(key);
      // Prune old keys (keep last 100)
      if (processedEvents.size > 100) {
        const arr = Array.from(processedEvents);
        for (let i = 0; i < arr.length - 100; i++) processedEvents.delete(arr[i]);
      }
      processRealtimeSignal(event).catch(e =>
        console.error('[Swarm] Error processing signal:', e)
      );
    }
  }, 2000); // Check every 2 seconds
  console.log('[Swarm] Bus listener started');
}

function stopBusListener() {
  if (busListenerTimer) {
    clearInterval(busListenerTimer);
    busListenerTimer = null;
    console.log('[Swarm] Bus listener stopped');
  }
}

// ── Periodic bus compaction ──
let compactTimer: ReturnType<typeof setInterval> | null = null;

function startBusCompaction() {
  if (compactTimer) return;
  compactTimer = setInterval(() => SwarmBus.compact(), 600_000); // Every 10 min
}

function stopBusCompaction() {
  if (compactTimer) {
    clearInterval(compactTimer);
    compactTimer = null;
  }
}

// ── Signal Scanner — Deterministic signal generation from Railway data ──
let scannerTimer: ReturnType<typeof setInterval> | null = null;
const SCAN_INTERVAL = 5 * 60_000; // Every 5 minutes
const SCAN_COOLDOWN = 15 * 60_000; // 15 min cooldown per symbol after signal
const lastSignalTime: Map<string, number> = new Map();

// Thresholds for signal generation
const FUNDING_EXTREME_APY = 35; // ±35% annual = strong signal
const STRESS_HIGH = 40; // stress score > 40 = elevated risk
const FUNDING_CONFIDENCE_BASE = 0.65;

async function runSignalScan() {
  try {
    const [fundingResp, snapshotResp] = await Promise.all([
      fetch(`${CLOUD}/api/hl/funding`).catch(() => null),
      fetch(`${CLOUD}/api/market/snapshot`).catch(() => null),
    ]);

    if (!fundingResp?.ok) return;
    const fundingData = await fundingResp.json();
    const snapshotData = snapshotResp?.ok ? await snapshotResp.json() : null;

    // Build stress map from snapshot
    const stressMap: Map<string, number> = new Map();
    if (snapshotData?.stress) {
      for (const s of snapshotData.stress) {
        stressMap.set(s.coin, s.score || 0);
      }
    }

    // Scan monitored tokens for extreme conditions
    const tokens = ['BTC', 'ETH', 'SOL'];
    for (const rate of (fundingData.rates || [])) {
      const coin = rate.coin;
      if (!tokens.includes(coin)) continue;

      // Cooldown check
      const lastTime = lastSignalTime.get(coin) || 0;
      if (Date.now() - lastTime < SCAN_COOLDOWN) continue;

      const annualPct = Math.abs(rate.annual_pct || 0);
      const fundingPct = rate.funding_8h_pct || 0;
      const stress = stressMap.get(coin) || 0;

      // Skip if funding is not extreme enough
      if (annualPct < FUNDING_EXTREME_APY) continue;

      // Determine direction based on funding
      // Negative funding = shorts paying longs → LONG opportunity
      // Positive funding = longs paying shorts → SHORT opportunity
      const direction = fundingPct < 0 ? 'LONG' : 'SHORT';

      // Calculate confidence: higher annual % and lower stress = more confident
      let confidence = FUNDING_CONFIDENCE_BASE;
      if (annualPct > 60) confidence += 0.10;
      if (annualPct > 100) confidence += 0.05;
      if (stress > STRESS_HIGH) confidence -= 0.10; // Reduce confidence in stressed markets
      confidence = Math.min(0.90, Math.max(0.50, confidence));

      const reason = `Funding ${fundingPct > 0 ? '+' : ''}${(fundingPct * 100).toFixed(4)}% (${rate.annual_pct?.toFixed(1)}% APY). ` +
        `OI: $${(parseFloat(rate.open_interest || '0') * parseFloat(rate.mark_px || '0') / 1e6).toFixed(0)}M. ` +
        (stress > 0 ? `Stress: ${stress}/100.` : '');

      // Publish signal to bus
      SwarmBus.publish({
        channel: 'realtime',
        from: 'signal-scanner',
        type: 'signal',
        priority: 1,
        payload: { symbol: coin, direction, confidence, reason },
        ttl: 300,
      });

      lastSignalTime.set(coin, Date.now());
      console.log(`[Scanner] Signal: ${coin} ${direction} @ ${(confidence * 100).toFixed(0)}% — ${reason}`);
    }
  } catch (e) {
    console.warn('[Scanner] Scan failed:', e);
  }
}

function startSignalScanner() {
  if (scannerTimer) return;
  // First scan after 30s (let app stabilize), then every 5 min
  setTimeout(() => {
    runSignalScan();
    scannerTimer = setInterval(runSignalScan, SCAN_INTERVAL);
  }, 30_000);
  console.log('[Scanner] Signal scanner started (every 5 min)');
}

function stopSignalScanner() {
  if (scannerTimer) {
    clearInterval(scannerTimer);
    scannerTimer = null;
  }
}

// ── Strategy Scanner — Runs backtested strategies on live data via Python ──
let stratScannerTimer: ReturnType<typeof setInterval> | null = null;
const STRAT_SCAN_INTERVAL = 5 * 60_000; // Every 5 minutes
const STRAT_SCAN_COOLDOWN = 60 * 60_000; // 1 hour cooldown per strategy signal (avoid spam)
const lastStratSignalTime: Map<string, number> = new Map();

function runStrategyScanner() {
  const scriptPath = path.join(process.cwd(), 'scripts', 'strategy_scanner.py');
  if (!fs.existsSync(scriptPath)) {
    console.warn('[StratScanner] strategy_scanner.py not found at', scriptPath);
    return;
  }

  // Find Python executable
  const venvPython = path.resolve(process.cwd(), '..', '.venv', 'Scripts', 'python.exe');
  const pythonCmd = fs.existsSync(venvPython) ? venvPython : 'python';

  // Bus file path
  const busFile = path.resolve(process.cwd(), '..', '.claude', 'swarm-bus', 'events.jsonl');

  console.log('[StratScanner] Running strategy evaluation...');

  execFile(pythonCmd, [scriptPath], {
    cwd: path.resolve(process.cwd(), '..'),
    env: {
      ...process.env,
      RAILWAY_URL: 'https://chic-encouragement-production.up.railway.app',
      BUS_FILE: busFile,
    },
    timeout: 30_000, // 30s max
  }, (error, stdout, stderr) => {
    if (stdout) {
      // Print Python output to console
      for (const line of stdout.split('\n')) {
        if (line.trim()) console.log(`[StratScanner] ${line}`);
      }
    }
    if (stderr) {
      console.warn('[StratScanner] stderr:', stderr.slice(0, 200));
    }

    if (error) {
      // Exit code 10 = signals written (not an error)
      if ((error as any).code === 10) {
        console.log('[StratScanner] Strategy signals detected and written to bus');
        // The bus listener will pick them up automatically on next tick
      } else if ((error as any).code !== 0) {
        console.warn('[StratScanner] Script error:', error.message?.slice(0, 200));
      }
    } else {
      console.log('[StratScanner] No strategy signals (market idle)');
    }
  });
}

function startStrategyScanner() {
  if (stratScannerTimer) return;
  // First scan after 45s (let funding scanner go first), then every 5 min
  setTimeout(() => {
    runStrategyScanner();
    stratScannerTimer = setInterval(runStrategyScanner, STRAT_SCAN_INTERVAL);
  }, 45_000);
  console.log('[StratScanner] Strategy scanner started (every 5 min)');
}

function stopStrategyScanner() {
  if (stratScannerTimer) {
    clearInterval(stratScannerTimer);
    stratScannerTimer = null;
  }
}

// ── Data API context por agente ──
const CLOUD = 'https://chic-encouragement-production.up.railway.app';

function buildDataContextBlock(agentId: string): string {
  const base: Record<string, string[]> = {
    'trading-agent': [
      `GET ${CLOUD}/api/hl/funding          → funding rates todos los perps (annual_pct, sentiment)`,
      `GET ${CLOUD}/api/hl/prices           → precios mid de todos los perps HyperLiquid`,
      `GET ${CLOUD}/api/hl/candles?symbol=BTC&interval=1h&limit=100  → velas OHLCV`,
      `GET ${CLOUD}/api/market/snapshot     → snapshot completo: funding stress, liquidaciones, top movers`,
    ],
    'chart-agent': [
      `GET ${CLOUD}/api/hl/candles?symbol=BTC&interval=1h&limit=200  → velas OHLCV (cambia symbol/interval)`,
      `GET ${CLOUD}/api/hl/prices           → precios actuales`,
      `GET ${CLOUD}/api/hl/orderbook?symbol=BTC  → order book L2`,
    ],
    'risk-agent': [
      `GET ${CLOUD}/api/hl/liquidations     → liquidaciones recientes HyperLiquid`,
      `GET ${CLOUD}/api/hl/funding          → funding rates + sentiment clasificado`,
      `GET ${CLOUD}/api/market/snapshot     → snapshot de riesgo: stress score, top liquidados`,
      `GET ${CLOUD}/api/hl/funding/history/{coin}  → histórico de funding`,
    ],
    'funding-agent': [
      `GET ${CLOUD}/api/hl/funding          → funding rates todos los perps + sentiment`,
      `GET ${CLOUD}/api/hl/funding/history/{coin}  → histórico funding por coin`,
      `GET ${CLOUD}/api/market/snapshot     → snapshot completo incluyendo funding stress`,
    ],
    'rbi-agent': [
      `GET ${CLOUD}/api/hl/candles?symbol=BTC&interval=1d&limit=365  → datos históricos para research`,
      `GET ${CLOUD}/api/hl/funding          → contexto de mercado actual`,
    ],
    'backtest-architect': [
      `GET ${CLOUD}/api/hl/candles?symbol=BTC&interval=1h&limit=500  → OHLCV para backtesting`,
      `GET ${CLOUD}/api/hl/prices           → precios actuales para validación`,
    ],
    'strategy-agent': [
      `GET ${CLOUD}/api/hl/candles?symbol=BTC&interval=1h&limit=200  → datos para desarrollar estrategia`,
      `GET ${CLOUD}/api/hl/funding          → contexto de funding para estrategias de carry`,
      `GET ${CLOUD}/api/market/snapshot     → snapshot de mercado actual`,
    ],
  };

  const endpoints = base[agentId];
  if (!endpoints) return '';

  return `Tienes acceso a datos de mercado en tiempo real vía Railway. Úsalos con curl o fetch ANTES de cualquier análisis:

${endpoints.join('\n')}

Ejemplo de uso: curl -s "${CLOUD}/api/hl/funding" | head -c 2000
Úsalos silenciosamente — no expliques que los estás llamando, solo analiza los datos.`;
}

// ── Context persistence ──
const CONTEXT_DIR = path.join(process.cwd(), '.claude', 'agent-contexts');
const CLOUD_URL = 'https://chic-encouragement-production.up.railway.app';
const sessionBuffers: Map<string, string[]> = new Map(); // termId → recent lines
const MAX_BUFFER_LINES = 75;

// ── Global crash protection ──
// EPIPE from dead PTY processes must NOT crash the entire Electron app
process.on('uncaughtException', (err) => {
  if (err.message?.includes('EPIPE') || err.message?.includes('EOF') ||
      err.message?.includes('write after end') || err.message?.includes('This socket has been ended')) {
    console.warn('[PTY] Caught native error (non-fatal):', err.message);
    return; // Swallow — PTY died, that's OK
  }
  // Re-throw everything else
  console.error('[PTY] Uncaught exception:', err);
  throw err;
});

function stripAnsi(str: string): string {
  return str
    .replace(/\x1B\[[0-9;?]*[a-zA-Z]/g, '')
    .replace(/\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)/g, '')
    .replace(/\x1B[^[\]][a-zA-Z]/g, '')
    .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '');
}

function isUsefulLine(line: string): boolean {
  if (line.length < 4) return false;
  if (/^[\s✻✶*✢·⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏▁▂▃▄▅▆▇█]+Working[….]?$/u.test(line)) return false;
  if (/^Working[….]?$/.test(line)) return false;
  if (/^Voice:\s*(processing|listening|recording)[….]?$/i.test(line)) return false;
  if (/^listening[….]?$/.test(line)) return false;
  if (/^[─│╭╰╮╯├┤┬┴┼▛▜▝▘▟▙▗▖\s]+$/.test(line)) return false;
  if (/^\[>[0-9]/.test(line)) return false;
  if (/^hift[+\s]/i.test(line)) return false;
  if (/hold\s*Space\s*to\s*speak/i.test(line)) return false;
  if (/bypasspermissions/i.test(line)) return false;
  if (/^◐\s*(low|medium|high)/u.test(line)) return false;
  if (/^[⏵⏵]+/u.test(line)) return false;
  if (/Checkingforupdates/i.test(line)) return false;
  if (/Welcomeback\w/i.test(line)) return false;
  if (/Tipsforgetting/i.test(line)) return false;
  if (/Norecentactivity/i.test(line)) return false;
  if (/Recentactivity$/i.test(line)) return false;
  const boxChars = (line.match(/[─│╭╰╮╯▛▜▝▘▟▙]/g) || []).length;
  if (boxChars > line.length * 0.3) return false;
  return true;
}

function ensureContextDir() {
  if (!fs.existsSync(CONTEXT_DIR)) fs.mkdirSync(CONTEXT_DIR, { recursive: true });
}

// ── Safe PTY operations (never throw) ──

function safeSend(mainWindow: BrowserWindow, channel: string, ...args: any[]) {
  try {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send(channel, ...args);
    }
  } catch {}
}

function safePtyWrite(pty: IPty | undefined, data: string): boolean {
  if (!pty) return false;
  try {
    pty.write(data);
    return true;
  } catch (e: any) {
    console.warn('[PTY] Write failed (process likely dead):', e.message);
    return false;
  }
}

function safePtyResize(pty: IPty | undefined, cols: number, rows: number): boolean {
  if (!pty) return false;
  try {
    pty.resize(cols, rows);
    return true;
  } catch {
    return false;
  }
}

function safePtyKill(pty: IPty | undefined) {
  if (!pty) return;
  const pid = pty.pid;
  try {
    pty.kill();
  } catch (e: any) {
    console.warn(`[PTY] kill() failed for PID ${pid}:`, e.message);
  }
  // Windows fallback: force-kill the process tree
  if (pid && process.platform === 'win32') {
    try {
      require('child_process').exec(`taskkill /PID ${pid} /T /F`, () => {});
    } catch {}
  }
}

// ── Context saving (async, non-blocking) ──

const savingAgents = new Set<string>();

/**
 * Extract explicit memory commands from terminal output.
 * Agents can emit: [MEMORY:semantic] content here [/MEMORY]
 * Or:              [REMEMBER] content here [/REMEMBER] (defaults to semantic)
 */
function extractMemories(agentId: string, lines: string[]) {
  const fullText = lines.join('\n');

  // Pattern 1: [MEMORY:type] content [/MEMORY]
  const memoryRegex = /\[MEMORY:(\w+)\]\s*([\s\S]*?)\s*\[\/MEMORY\]/g;
  let match;
  while ((match = memoryRegex.exec(fullText)) !== null) {
    const type = match[1] as any;
    const content = match[2].trim();
    if (content && ['semantic', 'episodic', 'procedural'].includes(type)) {
      MemoryManager.save({ agent_id: agentId, type, content, importance: 0.7 });
      console.log(`[Memory] Extracted ${type} memory for ${agentId}: ${content.slice(0, 60)}...`);
    }
  }

  // Pattern 2: [REMEMBER] content [/REMEMBER] → semantic
  const rememberRegex = /\[REMEMBER\]\s*([\s\S]*?)\s*\[\/REMEMBER\]/g;
  while ((match = rememberRegex.exec(fullText)) !== null) {
    const content = match[1].trim();
    if (content) {
      MemoryManager.save({ agent_id: agentId, type: 'semantic', content, importance: 0.6 });
      console.log(`[Memory] Extracted remembered memory for ${agentId}: ${content.slice(0, 60)}...`);
    }
  }
}

async function saveAgentContext(agentId: string, buffer: string[]) {
  if (buffer.length === 0) return;
  if (savingAgents.has(agentId)) return;
  savingAgents.add(agentId);

  try {
    ensureContextDir();
    const contextFile = path.join(CONTEXT_DIR, `${agentId}.md`);
    const now = new Date().toISOString();
    const cleanLines = buffer
      .map(stripAnsi)
      .map(l => l.trim())
      .filter(isUsefulLine);
    if (cleanLines.length === 0) return;

    // Extract explicit memory commands from output
    try { extractMemories(agentId, cleanLines); } catch {}

    let prevSessions = '';
    try {
      const existing = await fs.promises.readFile(contextFile, 'utf-8');
      const sections = existing.split(/^---$/m).filter(s => s.trim());
      if (sections.length > 0) {
        prevSessions = '\n---\n## Sesión anterior\n' + sections[0].trim().slice(0, 400) + '\n';
      }
    } catch {}

    const content = `# Contexto del agente: ${agentId}\n## Última sesión: ${now}\n\n${cleanLines.slice(-40).join('\n')}${prevSessions}`;
    await fs.promises.writeFile(contextFile, content, 'utf-8');

    Vault.get('OPENGRAVITY_API_TOKEN').then(token => {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;
      fetch(`${CLOUD_URL}/api/agent/context/${agentId}`, {
        method: 'POST', headers,
        body: JSON.stringify({ context_summary: content }),
      }).catch(() => {});
    }).catch(() => {});
  } catch (e) {
    console.warn(`[Context] Failed to write context for ${agentId}:`, e);
  } finally {
    savingAgents.delete(agentId);
  }
}

export function saveAllContexts() {
  for (const [termId, agId] of agentMap.entries()) {
    const buf = sessionBuffers.get(termId) || [];
    if (buf.length > 0) saveAgentContext(agId, [...buf]);
  }
}

// ── Periodic auto-save ──
let autoSaveTimer: ReturnType<typeof setInterval> | null = null;
const AUTO_SAVE_INTERVAL_MS = 90_000;

function startAutoSave() {
  if (autoSaveTimer) return;
  autoSaveTimer = setInterval(() => {
    for (const [termId, agId] of agentMap.entries()) {
      const buf = sessionBuffers.get(termId) || [];
      if (buf.length > 0) saveAgentContext(agId, [...buf]);
    }
  }, AUTO_SAVE_INTERVAL_MS);
}

function stopAutoSave() {
  if (autoSaveTimer) {
    clearInterval(autoSaveTimer);
    autoSaveTimer = null;
  }
}

// ── Semaphore: max 3 concurrent Claude spawns ──
let activeSpawns = 0;
const MAX_CONCURRENT_SPAWNS = 3;
const spawnQueue: Array<() => void> = [];

function acquireSpawnSlot(): Promise<void> {
  return new Promise<void>((resolve) => {
    if (activeSpawns < MAX_CONCURRENT_SPAWNS) {
      activeSpawns++;
      resolve();
    } else {
      spawnQueue.push(() => {
        activeSpawns++;
        resolve();
      });
    }
  });
}

function releaseSpawnSlot() {
  activeSpawns = Math.max(0, activeSpawns - 1);
  if (spawnQueue.length > 0) {
    const next = spawnQueue.shift();
    next?.();
  }
}

// ── Build clean environment for Claude ──
function buildClaudeEnv(): Record<string, string> {
  const env: Record<string, string> = { ...process.env } as Record<string, string>;

  env['TERM'] = 'xterm-256color';
  env['COLORTERM'] = 'truecolor';
  env['FORCE_COLOR'] = '1';
  env['NODE_OPTIONS'] = '--max-old-space-size=4096';
  env['OPENGRAVITY_CLOUD_URL'] = 'https://chic-encouragement-production.up.railway.app';

  const cleanVars = [
    'CLAUDECODE', 'CLAUDE_CODE', 'ANTHROPIC_CLAUDE_CODE',
    'CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_CODE_SESSION_ID',
    'ANTHROPIC_CLAUDE_CODE_SESSION_ID',
    'OPENGRAVITY_API_TOKEN', 'SECRET_KEY', 'DATABASE_URL',
    'ANTHROPIC_API_KEY', 'HELIUS_API_KEY', 'OPENAI_API_KEY',
  ];
  for (const v of cleanVars) {
    delete env[v];
  }

  const extraPaths = [
    path.join(os.homedir(), '.local', 'bin'),           // uv, claude
    'C:\\Users\\Public\\node-v22.15.0-win-x64',         // node, npm
    'C:\\Program Files\\Python313',                      // python3
    'C:\\Program Files\\Python313\\Scripts',              // pip
    path.join(os.homedir(), 'AppData', 'Local', 'Programs', 'Python', 'Python312'),
    path.join(os.homedir(), 'AppData', 'Local', 'Programs', 'Python', 'Python312', 'Scripts'),
    path.join(os.homedir(), 'AppData', 'Local', 'Microsoft', 'WindowsApps'), // python3 alias
    'C:\\Program Files\\GitHub CLI',
    'C:\\WINDOWS\\system32',                             // standard Windows tools
  ];
  let currentPath = env['PATH'] || '';
  for (const p of extraPaths) {
    if (!currentPath.includes(p)) {
      currentPath = p + ';' + currentPath;
    }
  }
  env['PATH'] = currentPath;

  return env;
}


// ── Execute order via Python HLConnector ──
function executeHLOrder(order: any): Promise<any> {
  return new Promise((resolve) => {
    const scriptPath = path.join(process.cwd(), 'scripts', 'hl_execute.py');
    const pythonPaths = [
      'python',
      'python3',
      'C:\\Program Files\\Python313\\python.exe',
      path.join(os.homedir(), 'AppData', 'Local', 'Programs', 'Python', 'Python312', 'python.exe'),
    ];

    // Try to find a working Python
    const tryPython = (idx: number) => {
      if (idx >= pythonPaths.length) {
        resolve({ success: false, error: 'Python not found' });
        return;
      }

      const args = [
        scriptPath,
        '--symbol', order.symbol,
        '--direction', order.direction,
        '--size', order.size || 'quarter',
        '--score', String(order.score || 0),
        '--priority', String(order.priority || 2),
      ];

      // Testnet by default — only add --mainnet if explicitly requested
      if (order.mainnet) args.push('--mainnet');

      // Pass key via env (read from Vault or process.env)
      const execEnv = { ...process.env };
      Vault.get('HL_TESTNET_PRIVATE_KEY').then(vaultKey => {
        if (vaultKey) execEnv['HL_TESTNET_PRIVATE_KEY'] = vaultKey;
        return Vault.get('HL_PRIVATE_KEY');
      }).then(mainKey => {
        if (mainKey) execEnv['HL_PRIVATE_KEY'] = mainKey;
      }).catch(() => {}).finally(() => {

      execFile(pythonPaths[idx], args, { timeout: 90_000, env: execEnv }, (err, stdout, stderr) => {
        if (err && (err as any).code === 'ENOENT') {
          tryPython(idx + 1); // Try next Python
          return;
        }
        if (err) {
          console.error(`[Swarm] HL execution error:`, err.message, stderr);
          resolve({ success: false, error: err.message });
          return;
        }
        try {
          const result = JSON.parse(stdout.trim());
          resolve(result);
        } catch {
          resolve({ success: false, error: `Invalid output: ${stdout.slice(0, 200)}` });
        }
      });

      }); // end .finally()
    };

    tryPython(0);
  });
}

// ── Setup IPC handlers ──
export function setupPtyManager(mainWindow: BrowserWindow) {
  _mainWindow = mainWindow;

  // ── Start bus listener + compaction immediately (don't wait for terminal open) ──
  startBusListener();
  startBusCompaction();
  startSignalScanner();
  startStrategyScanner();
  console.log('[Swarm] Orchestrator ready — bus listener + funding scanner + strategy scanner active');

  // ── Swarm order confirmation IPC ──

  ipcMain.handle('swarm-confirm-order', async (_event, orderId: string) => {
    const order = pendingOrders.get(orderId);
    if (!order) return { success: false, error: 'Order not found or expired' };

    console.log(`[Swarm] User CONFIRMED order ${orderId}: ${order.symbol} ${order.direction} ${order.size}`);
    pendingOrders.delete(orderId);

    // Execute via HLConnector (testnet)
    const result = await executeHLOrder(order);
    console.log(`[Swarm] Execution result:`, JSON.stringify(result));

    // Publish result to bus
    SwarmBus.publish({
      channel: 'realtime',
      from: 'claude-main',
      type: 'result',
      priority: 1,
      payload: {
        symbol: order.symbol,
        direction: order.direction,
        size: order.size,
        execution: result,
        confirmed_by: 'user',
      },
    });

    // Notify frontend
    if (_mainWindow && !_mainWindow.isDestroyed()) {
      _mainWindow.webContents.send('swarm-order-executed', { orderId, result });
    }

    return result;
  });

  ipcMain.handle('swarm-reject-order', async (_event, orderId: string) => {
    const order = pendingOrders.get(orderId);
    if (!order) return { success: false, error: 'Order not found' };

    console.log(`[Swarm] User REJECTED order ${orderId}: ${order.symbol} ${order.direction}`);
    pendingOrders.delete(orderId);

    SwarmBus.publish({
      channel: 'realtime',
      from: 'claude-main',
      type: 'result',
      priority: 3,
      payload: { symbol: order.symbol, action: 'REJECTED', reason: 'User rejected order' },
    });

    return { success: true, action: 'rejected' };
  });

  ipcMain.handle('swarm-pending-orders', async () => {
    return Array.from(pendingOrders.values());
  });

  // ── Helper: clean up a terminal session ──
  function cleanupSession(termId: string) {
    const pty = sessions.get(termId);
    if (pty) {
      safePtyKill(pty);
      sessions.delete(termId);
    }
    agentMap.delete(termId);
    sessionBuffers.delete(termId);
  }

  // Create a new terminal session
  ipcMain.handle('pty-create', async (_event, termId: string, agentId: string, rows: number, cols: number) => {
    console.log(`[PTY] Creating session for ${agentId} (${termId})`);

    // If session already exists for this termId, clean it up first
    if (sessions.has(termId)) {
      console.warn(`[PTY] Session ${termId} already exists, cleaning up first`);
      cleanupSession(termId);
    }

    AuditLog.log({
      agent: agentId,
      action: 'PTY_CREATE',
      details: `Creating terminal session for agent ${agentId}`,
      level: 'INFO',
      result: 'ALLOWED'
    });
    await acquireSpawnSlot();

    const env = buildClaudeEnv();

    if (agentId === 'polymarket-agent') {
      const polyKeys = ['POLYMARKET_PK', 'POLYMARKET_FUNDER', 'POLYMARKET_API_KEY',
                        'POLYMARKET_API_SECRET', 'POLYMARKET_API_PASSPHRASE'];
      for (const key of polyKeys) {
        const val = await Vault.get(key);
        if (val) env[key] = val;
      }
    }

    const isWin = process.platform === 'win32';
    const shell = isWin ? 'cmd.exe' : 'claude';
    const args = isWin
      ? ['/c', 'claude', '--dangerously-skip-permissions']
      : ['--dangerously-skip-permissions'];
    const cwd = process.cwd();

    try {
      console.log(`[PTY] Spawning shell: ${shell} with args:`, args);
      const ptyProcess = spawn(shell, args, {
        name: 'xterm-256color',
        cols: cols || 80,
        rows: rows || 24,
        cwd,
        env,
      });

      console.log(`[PTY] Session created: ${termId} (PID: ${ptyProcess.pid})`);
      sessions.set(termId, ptyProcess);
      agentMap.set(termId, agentId);
      releaseSpawnSlot(); // Release immediately after spawn so queued agents don't wait 8s
      startAutoSave();
      MemoryManager.startMaintenance();

      // Forward PTY output to renderer + accumulate in buffer
      ptyProcess.onData((data: string) => {
        safeSend(mainWindow, 'pty-data', termId, data);
        const lines = data.split('\n');
        const buf = sessionBuffers.get(termId) || [];
        buf.push(...lines);
        if (buf.length > MAX_BUFFER_LINES) buf.splice(0, buf.length - MAX_BUFFER_LINES);
        sessionBuffers.set(termId, buf);
      });

      // Handle PTY exit with auto-restart
      ptyProcess.onExit(({ exitCode }: { exitCode: number }) => {
        try {
          // Save context asynchronously
          const buf = sessionBuffers.get(termId) || [];
          if (buf.length > 0) saveAgentContext(agentId, [...buf]);
          sessionBuffers.delete(termId);

          safeSend(mainWindow, 'pty-data', termId,
            `\r\n\x1b[33m[Claude salió (code: ${exitCode}) · Reiniciando en 2s...]\x1b[0m\r\n`
          );

          // Clean up and trigger restart after 2 seconds (gives time for cleanup)
          setTimeout(() => {
            try {
              AuditLog.log({
                agent: agentId,
                action: 'PTY_EXIT',
                details: `PTY process exited with code ${exitCode}`,
                level: exitCode !== 0 ? 'WARNING' : 'INFO',
                result: 'ALLOWED'
              });
            } catch {}
            sessions.delete(termId);
            safeSend(mainWindow, 'pty-restart', termId, agentId);
          }, 2000);
        } catch (e) {
          console.warn(`[PTY] Error in onExit handler for ${termId}:`, e);
          sessions.delete(termId);
        }
      });

      // Hydrate memories from cloud + inject memory context after Claude boots
      setTimeout(async () => {
        try {
          await MemoryManager.hydrateFromCloud(agentId);
          const memoryBlock = MemoryManager.buildPromptBlock(agentId);
          const dataBlock = buildDataContextBlock(agentId);

          if (memoryBlock || dataBlock) {
            let prompt = '';
            if (memoryBlock) {
              prompt += `Tienes las siguientes memorias de sesiones anteriores. Úsalas como contexto:\n\n${memoryBlock}\n\n`;
            }
            if (dataBlock) {
              prompt += dataBlock + '\n\n';
            }
            prompt += 'No respondas a esto, simplemente tenlo en cuenta.';
            safePtyWrite(ptyProcess, prompt);
            // Send Enter separately with small delay to ensure Claude's input buffer is ready
            setTimeout(() => safePtyWrite(ptyProcess, '\r'), 500);
            console.log(`[Memory] Injected ${MemoryManager.getStats(agentId).total} memories + data context for ${agentId}`);
          }
        } catch (e) {
          console.warn(`[Memory] Failed to inject memories for ${agentId}:`, e);
        }
      }, 15000); // Wait 15s for Claude to fully boot
      return { success: true };
    } catch (error) {
      releaseSpawnSlot();
      console.error(`[PTY] Failed to spawn for ${agentId}:`, error);
      return { success: false, error: String(error) };
    }
  });

  // Send input to PTY — protected against EPIPE
  ipcMain.on('pty-input', (_event, termId: string, data: string) => {
    const pty = sessions.get(termId);
    if (!safePtyWrite(pty, data) && pty) {
      // Write failed → PTY is dead, remove stale session
      console.warn(`[PTY] Removing dead session ${termId} after write failure`);
      sessions.delete(termId);
    }
  });

  // Resize PTY — throttled + protected
  const resizeTimers: Map<string, ReturnType<typeof setTimeout>> = new Map();
  ipcMain.on('pty-resize', (_event, termId: string, cols: number, rows: number) => {
    if (resizeTimers.has(termId)) clearTimeout(resizeTimers.get(termId)!);
    resizeTimers.set(termId, setTimeout(() => {
      resizeTimers.delete(termId);
      safePtyResize(sessions.get(termId), cols, rows);
    }, 50));
  });

  // Kill PTY — robust with Windows fallback
  ipcMain.on('pty-kill', (_event, termId: string) => {
    const agId = agentMap.get(termId);
    if (agId) {
      const buf = sessionBuffers.get(termId) || [];
      if (buf.length > 0) saveAgentContext(agId, [...buf]);
    }
    cleanupSession(termId);
  });

  // Kill all on app quit
  ipcMain.on('pty-kill-all', () => {
    stopAutoSave();
    stopBusListener();
    stopBusCompaction();
    stopSignalScanner();
    stopStrategyScanner();
    SwarmBus.compact(); // Final cleanup
    MemoryManager.stopMaintenance();
    MemoryManager.runMaintenance();
    saveAllContexts();
    for (const [termId] of sessions) {
      cleanupSession(termId);
    }
  });

  // Inject a prompt into a running agent's PTY by agentId
  ipcMain.handle('pty-inject', async (_event, targetAgentId: string, prompt: string) => {
    for (const [termId, agId] of agentMap.entries()) {
      if (agId === targetAgentId && sessions.has(termId)) {
        const ok = safePtyWrite(sessions.get(termId), prompt + '\r');
        return { success: ok, termId };
      }
    }
    return { success: false, error: 'Agent not found' };
  });

  // Read swarm bus status
  ipcMain.handle('swarm-get-status', async () => {
    const status = SwarmBus.getStatus();
    const busStats = SwarmBus.stats();
    const circuits: Record<string, CircuitState> = {};
    for (const [agent, state] of circuitBreaker.entries()) {
      if (state.errorCount > 0) circuits[agent] = state;
    }
    return { ...status, bus: busStats, circuits };
  });
}
