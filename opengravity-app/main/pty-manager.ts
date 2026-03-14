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

// ── Active PTY sessions ──
const sessions: Map<string, IPty> = new Map();

// ── Semaphore: max 2 concurrent Claude spawns (same as RBI) ──
let activeSpawns = 0;
const MAX_CONCURRENT_SPAWNS = 2;
const spawnQueue: Array<() => void> = [];

function acquireSpawnSlot(): Promise<void> {
  return new Promise((resolve) => {
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
    const next = spawnQueue.shift();
    next?.();
  }
}

// ── Build clean environment for Claude (same logic as RBI's _build_env) ──
function buildClaudeEnv(): Record<string, string> {
  const env: Record<string, string> = { ...process.env } as Record<string, string>;

  env['TERM'] = 'xterm-256color';
  env['COLORTERM'] = 'truecolor';
  env['FORCE_COLOR'] = '1';

  // Remove Claude Code session detection variables (prevents nested session errors)
  const cleanVars = [
    'CLAUDECODE', 'CLAUDE_CODE', 'ANTHROPIC_CLAUDE_CODE',
    'CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_CODE_SESSION_ID',
    'ANTHROPIC_CLAUDE_CODE_SESSION_ID',
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

// ── Find agent .md file (same logic as RBI's _find_agent_file) ──
function findAgentFile(agentId: string): string | null {
  if (agentId === 'main' || agentId === 'claude-main') return null;

  const projectDir = process.cwd();
  const searchDirs = [
    path.join(projectDir, '.claude', 'agents'),
    path.join(os.homedir(), '.claude', 'agents'),
  ];

  for (const dir of searchDirs) {
    for (const name of [`${agentId}.md`, `${agentId}-agent.md`, `${agentId}_agent.md`]) {
      const filePath = path.join(dir, name);
      if (fs.existsSync(filePath)) return filePath;
    }
  }
  return null;
}

// ── Extract agent name from frontmatter ──
function extractAgentName(filePath: string): string {
  try {
    const content = fs.readFileSync(filePath, 'utf-8');
    if (content.startsWith('---')) {
      const parts = content.split('---', 3);
      if (parts.length >= 2) {
        for (const line of parts[1].trim().split('\n')) {
          if (line.startsWith('name:')) {
            return line.split(':', 2)[1].trim().replace(/['"]/g, '');
          }
        }
      }
    }
  } catch {}
  return path.basename(filePath, '.md');
}

// ── Setup IPC handlers ──
export function setupPtyManager(mainWindow: BrowserWindow) {
  // Create a new terminal session
  ipcMain.handle('pty-create', async (_event, termId: string, agentId: string, rows: number, cols: number) => {
    await acquireSpawnSlot();

    const env = buildClaudeEnv();
    const shell = 'claude';
    const args = ['--dangerously-skip-permissions'];
    const cwd = process.cwd();

    try {
      const ptyProcess = spawn(shell, args, {
        name: 'xterm-256color',
        cols: cols || 80,
        rows: rows || 24,
        cwd,
        env,
      });

      sessions.set(termId, ptyProcess);

      // Forward PTY output to renderer
      ptyProcess.onData((data: string) => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('pty-data', termId, data);
        }
      });

      // Handle PTY exit with auto-restart (same as RBI)
      ptyProcess.onExit(({ exitCode }) => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('pty-data', termId,
            `\r\n\x1b[33m[Claude salió (code: ${exitCode}) · Reiniciando en 1s...]\x1b[0m\r\n`
          );

          // Auto-restart after 1 second
          setTimeout(async () => {
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

      // Agent init watcher (same as RBI's _start_agent_init_watcher)
      setTimeout(() => {
        releaseSpawnSlot();

        if (agentId === 'main' || agentId === 'claude-main') {
          // Send Enter to skip Claude's startup screen
          setTimeout(() => {
            if (sessions.has(termId)) {
              sessions.get(termId)?.write('\r');
            }
          }, 300);
        } else {
          const agentFile = findAgentFile(agentId);
          if (agentFile) {
            const agentName = extractAgentName(agentFile);
            const relPath = '.claude/agents/' + path.basename(agentFile);
            const initMsg = `Eres el agente '${agentName}'. Lee y aplica todas las instrucciones en ${relPath}.\r`;
            setTimeout(() => {
              if (sessions.has(termId)) {
                sessions.get(termId)?.write(initMsg);
              }
            }, 300);
          }
        }
      }, 5000); // Wait 5s for Claude to initialize

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

  // Resize PTY
  ipcMain.on('pty-resize', (_event, termId: string, cols: number, rows: number) => {
    const pty = sessions.get(termId);
    if (pty) {
      try {
        pty.resize(cols, rows);
      } catch {}
    }
  });

  // Kill PTY
  ipcMain.on('pty-kill', (_event, termId: string) => {
    const pty = sessions.get(termId);
    if (pty) {
      pty.kill();
      sessions.delete(termId);
    }
  });

  // Kill all on app quit
  ipcMain.on('pty-kill-all', () => {
    for (const [id, pty] of sessions) {
      try { pty.kill(); } catch {}
    }
    sessions.clear();
  });
}
