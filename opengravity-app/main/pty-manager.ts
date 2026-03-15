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
 * Returns a promise that resolves when the agent writes a response
 * to the swarm bus, or rejects on timeout.
 */
function invokeAgent(
  agentName: AgentName,
  prompt: string,
  opts: { timeout: number } = { timeout: THRESHOLDS.AGENT_TIMEOUT }
): Promise<AgentResponse> {
  return new Promise((resolve) => {
    if (isAgentDisabled(agentName)) {
      resolve({
        agent: agentName,
        type: 'analysis',
        direction: 'NEUTRAL',
        confidence: 0,
        reason: `Circuit breaker OPEN — agent disabled after ${THRESHOLDS.CIRCUIT_BREAKER_MAX} errors`,
        timedOut: true,
      });
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
      console.log(`[Swarm] ⚠ ${agentName} not running — skipping convocation`);
      resolve({
        agent: agentName,
        type: 'analysis',
        direction: 'NEUTRAL',
        confidence: 0,
        reason: `Agent ${agentName} not running — open its terminal to participate in swarm`,
        timedOut: true,
      });
      return;
    }

    // Inject the analysis prompt
    const pty = sessions.get(targetTermId);
    const ok = safePtyWrite(pty, prompt + '\r');
    if (!ok) {
      onAgentError(agentName, 'PTY write failed');
      resolve({
        agent: agentName,
        type: 'analysis',
        direction: 'NEUTRAL',
        confidence: 0,
        reason: 'PTY write failed',
        timedOut: true,
      });
      return;
    }

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
        onAgentError(agentName, 'Timeout');
        console.warn(`[Swarm] ${agentName} timed out after ${opts.timeout}ms`);
        resolve({
          agent: agentName,
          type: 'analysis',
          direction: 'NEUTRAL',
          confidence: 0,
          reason: `Timeout after ${opts.timeout}ms`,
          timedOut: true,
        });
      }
    }, 500); // Check every 500ms
  });
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

  // If EXECUTE: send order to trading-agent
  if (decision.action === 'EXECUTE' && decision.direction && decision.size) {
    const orderPrompt = `[SWARM ORDER] Ejecutar operación:
Símbolo: ${symbol}
Dirección: ${decision.direction}
Tamaño: ${decision.size} (score: ${decision.score?.toFixed(2)})
Fuentes: ${decision.sources.join(', ')}
Razón: ${decision.reason}

Ejecuta la orden y reporta el resultado al bus.`;

    // Fire and forget to trading-agent
    invokeAgent('trading-agent', orderPrompt, { timeout: 15_000 }).then(result => {
      console.log(`[Swarm] Trading agent response: ${result.timedOut ? 'TIMEOUT' : 'OK'}`);
    });
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

function startBusListener() {
  if (busListenerTimer) return;
  busListenerTimer = setInterval(() => {
    const signals = SwarmBus.readByType('signal', 'realtime');
    for (const event of signals) {
      if (processedEvents.has(event.id)) continue;
      processedEvents.add(event.id);
      // Prune old IDs (keep last 100)
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
    path.join(os.homedir(), '.local', 'bin'),
    'C:\\Users\\Public\\node-v22.15.0-win-x64',
    'C:\\Program Files\\GitHub CLI',
  ];
  const currentPath = env['PATH'] || '';
  for (const p of extraPaths) {
    if (!currentPath.includes(p)) {
      env['PATH'] = p + ';' + currentPath;
    }
  }

  return env;
}


// ── Setup IPC handlers ──
export function setupPtyManager(mainWindow: BrowserWindow) {

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
      startAutoSave();
      MemoryManager.startMaintenance();
      startBusListener();
      startBusCompaction();

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
        releaseSpawnSlot();
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
            safePtyWrite(ptyProcess, prompt + '\r');
            console.log(`[Memory] Injected ${MemoryManager.getStats(agentId).total} memories + data context for ${agentId}`);
          }
        } catch (e) {
          console.warn(`[Memory] Failed to inject memories for ${agentId}:`, e);
        }
      }, 8000); // Wait 8s for Claude to fully boot
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
