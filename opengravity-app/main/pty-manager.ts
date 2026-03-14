/**
 * PTY Manager — Spawns and manages Claude Code terminal sessions.
 *
 * Adapted from RBI's TerminalBridge (Python/winpty) to Node.js/node-pty.
 * Each terminal gets a real PTY running `claude --dangerously-skip-permissions`.
 */
import { spawn, IPty } from 'node-pty';
import { ipcMain, BrowserWindow } from 'electron';
import * as os from 'os';
import * as path from 'path';
import * as fs from 'fs';
import { AuditLog } from './security/audit';
import { Vault } from './security/vault';

// ── Active PTY sessions ──
const sessions: Map<string, IPty> = new Map();
const agentMap: Map<string, string> = new Map(); // termId → agentId

// ── Context persistence ──
const CONTEXT_DIR = path.join(process.cwd(), '.claude', 'agent-contexts');
const CLOUD_URL = 'https://chic-encouragement-production.up.railway.app';
const sessionBuffers: Map<string, string[]> = new Map(); // termId → recent lines
const MAX_BUFFER_LINES = 75;

function stripAnsi(str: string): string {
  return str
    // CSI sequences: ESC [ ... letter (includes ?2026h/l, cursor, color, etc.)
    .replace(/\x1B\[[0-9;?]*[a-zA-Z]/g, '')
    // OSC sequences: ESC ] ... BEL or ESC\ (e.g. ]0;title)
    .replace(/\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)/g, '')
    // Other 2-char escape sequences
    .replace(/\x1B[^[\]][a-zA-Z]/g, '')
    // Control characters (except \n and \r)
    .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '');
}

// Semantic filter: discard lines with zero informational value
function isUsefulLine(line: string): boolean {
  if (line.length < 4) return false;
  // Spinners and "Working…" animations
  if (/^[\s✻✶*✢·⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏▁▂▃▄▅▆▇█]+Working[….]?$/u.test(line)) return false;
  if (/^Working[….]?$/.test(line)) return false;
  // Voice mode noise
  if (/^Voice:\s*(processing|listening|recording)[….]?$/i.test(line)) return false;
  if (/^listening[….]?$/.test(line)) return false;
  // UI box-drawing lines (Claude splash screen)
  if (/^[─│╭╰╮╯├┤┬┴┼▛▜▝▘▟▙▗▖\s]+$/.test(line)) return false;
  // Escaped ANSI/control remnants that survived stripAnsi
  if (/^\[>[0-9]/.test(line)) return false;
  if (/^hift[+\s]/i.test(line)) return false;
  // Claude CLI status bar / UI chrome
  if (/hold\s*Space\s*to\s*speak/i.test(line)) return false;
  if (/bypasspermissions/i.test(line)) return false;
  if (/^◐\s*(low|medium|high)/u.test(line)) return false;
  if (/^[⏵⏵]+/u.test(line)) return false;
  if (/Checkingforupdates/i.test(line)) return false;
  if (/Welcomeback\w/i.test(line)) return false;
  if (/Tipsforgetting/i.test(line)) return false;
  if (/Norecentactivity/i.test(line)) return false;
  if (/Recentactivity$/i.test(line)) return false;
  // Lines dominated by box-drawing chars (>30%)
  const boxChars = (line.match(/[─│╭╰╮╯▛▜▝▘▟▙]/g) || []).length;
  if (boxChars > line.length * 0.3) return false;
  return true;
}

function ensureContextDir() {
  if (!fs.existsSync(CONTEXT_DIR)) fs.mkdirSync(CONTEXT_DIR, { recursive: true });
}


// Debounce guard: prevent overlapping saves for the same agent
const savingAgents = new Set<string>();

async function saveAgentContext(agentId: string, buffer: string[]) {
  if (buffer.length === 0) return;
  if (savingAgents.has(agentId)) return; // Skip if already saving
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

    // Read existing context to preserve history (keep last 2 sessions)
    let prevSessions = '';
    try {
      const existing = await fs.promises.readFile(contextFile, 'utf-8');
      const sections = existing.split(/^---$/m).filter(s => s.trim());
      if (sections.length > 0) {
        prevSessions = '\n---\n## Sesión anterior\n' + sections[0].trim().slice(0, 400) + '\n';
      }
    } catch {} // File doesn't exist yet — OK

    const content = `# Contexto del agente: ${agentId}\n## Última sesión: ${now}\n\n${cleanLines.slice(-40).join('\n')}${prevSessions}`;
    await fs.promises.writeFile(contextFile, content, 'utf-8');

    // Async backup to Railway (fire and forget)
    Vault.get('OPENGRAVITY_API_TOKEN').then(token => {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;
      fetch(`${CLOUD_URL}/api/agent/context/${agentId}`, {
        method: 'POST',
        headers,
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
    if (buf.length > 0) saveAgentContext(agId, buf);
  }
}

// ── Periodic auto-save: protects terminal work if app crashes ──
let autoSaveTimer: ReturnType<typeof setInterval> | null = null;
const AUTO_SAVE_INTERVAL_MS = 90_000; // 90s — reduce mid-work spinner saves

function startAutoSave() {
  if (autoSaveTimer) return;
  autoSaveTimer = setInterval(() => {
    for (const [termId, agId] of agentMap.entries()) {
      const buf = sessionBuffers.get(termId) || [];
      if (buf.length > 0) saveAgentContext(agId, buf);
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
  activeSpawns--;
  if (spawnQueue.length > 0) {
    const next: (() => void) | undefined = spawnQueue.shift();
    next?.();
  }
}

// ── Build clean environment for Claude (same logic as RBI's _build_env) ──
function buildClaudeEnv(): Record<string, string> {
  const env: Record<string, string> = { ...process.env } as Record<string, string>;

  env['TERM'] = 'xterm-256color';
  env['COLORTERM'] = 'truecolor';
  env['FORCE_COLOR'] = '1';
  // Increase memory limit for Claude Code (CLI)
  env['NODE_OPTIONS'] = '--max-old-space-size=4096';

  // OpenGravity Cloud API (public endpoints, no auth needed)
  env['OPENGRAVITY_CLOUD_URL'] = 'https://chic-encouragement-production.up.railway.app';

  // Remove sensitive variables from PTY environment
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

  // Add common paths
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
  // Create a new terminal session
  ipcMain.handle('pty-create', async (_event, termId: string, agentId: string, rows: number, cols: number) => {
    console.log(`[PTY] Creating session for ${agentId} (${termId})`);
    AuditLog.log({
      agent: agentId,
      action: 'PTY_CREATE',
      details: `Creating terminal session for agent ${agentId}`,
      level: 'INFO',
      result: 'ALLOWED'
    });
    await acquireSpawnSlot();

    const env = buildClaudeEnv();

    // Inject agent-specific secrets from Vault into PTY environment
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
      startAutoSave(); // Ensure periodic context saving is running

      // Forward PTY output to renderer + accumulate in buffer
      ptyProcess.onData((data: string) => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('pty-data', termId, data);
        }
        const lines = data.split('\n');
        const buf = sessionBuffers.get(termId) || [];
        buf.push(...lines);
        if (buf.length > MAX_BUFFER_LINES) buf.splice(0, buf.length - MAX_BUFFER_LINES);
        sessionBuffers.set(termId, buf);

      });

      // Handle PTY exit with auto-restart (same as RBI)
      ptyProcess.onExit(({ exitCode }: { exitCode: number }) => {
        // Save context asynchronously before cleanup
        const buf = sessionBuffers.get(termId) || [];
        if (buf.length > 0) saveAgentContext(agentId, [...buf]);
        sessionBuffers.delete(termId);

        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('pty-data', termId,
            `\r\n\x1b[33m[Claude salió (code: ${exitCode}) · Reiniciando en 1s...]\x1b[0m\r\n`
          );

          // Auto-restart after 1 second
          setTimeout(async () => {
            AuditLog.log({
              agent: agentId,
              action: 'PTY_EXIT',
              details: `PTY process exited with code ${exitCode}`,
              level: exitCode !== 0 ? 'WARNING' : 'INFO',
              result: 'ALLOWED'
            });
            if (sessions.has(termId)) {
              sessions.delete(termId);
              // Trigger re-create from renderer
              if (mainWindow && !mainWindow.isDestroyed()) {
                mainWindow.webContents.send('pty-restart', termId, agentId);
              }
            }
          }, 1000);
        }
      });

      // Release spawn slot after Claude initializes
      setTimeout(() => {
        releaseSpawnSlot();
      }, 5000);
      return { success: true };
    } catch (error) {
      releaseSpawnSlot();
      return { success: false, error: String(error) };
    }
  });

  // Send input to PTY
  ipcMain.on('pty-input', (_event, termId: string, data: string) => {
    const pty = sessions.get(termId);
    if (pty) {
      pty.write(data);
    }
  });

  // Resize PTY — throttled to prevent flooding from multiple terminals
  const resizeTimers: Map<string, ReturnType<typeof setTimeout>> = new Map();
  ipcMain.on('pty-resize', (_event, termId: string, cols: number, rows: number) => {
    if (resizeTimers.has(termId)) clearTimeout(resizeTimers.get(termId)!);
    resizeTimers.set(termId, setTimeout(() => {
      resizeTimers.delete(termId);
      const pty = sessions.get(termId);
      if (pty) {
        try { pty.resize(cols, rows); } catch {}
      }
    }, 50));
  });

  // Kill PTY
  ipcMain.on('pty-kill', (_event, termId: string) => {
    const agId = agentMap.get(termId);
    if (agId) {
      const buf = sessionBuffers.get(termId) || [];
      if (buf.length > 0) saveAgentContext(agId, [...buf]);
      sessionBuffers.delete(termId);
    }
    const pty = sessions.get(termId);
    if (pty) {
      pty.kill();
      sessions.delete(termId);
      agentMap.delete(termId);
    }
  });

  // Kill all on app quit (saves contexts first)
  ipcMain.on('pty-kill-all', () => {
    stopAutoSave();
    saveAllContexts();
    for (const pty of sessions.values()) {
      try { pty.kill(); } catch {}
    }
    sessions.clear();
    agentMap.clear();
    sessionBuffers.clear();
  });

  // Inject a prompt into a running agent's PTY by agentId
  ipcMain.handle('pty-inject', async (_event, targetAgentId: string, prompt: string) => {
    for (const [termId, agId] of agentMap.entries()) {
      if (agId === targetAgentId && sessions.has(termId)) {
        sessions.get(termId)?.write(prompt + '\r');
        return { success: true, termId };
      }
    }
    return { success: false, error: 'Agent not found' };
  });

  // Read swarm bus status
  ipcMain.handle('swarm-get-status', async () => {
    const statusPath = path.join(process.cwd(), '.claude', 'swarm-bus', 'status.json');
    try {
      if (fs.existsSync(statusPath)) {
        return JSON.parse(fs.readFileSync(statusPath, 'utf-8'));
      }
    } catch {}
    return { status: 'idle' };
  });
}
