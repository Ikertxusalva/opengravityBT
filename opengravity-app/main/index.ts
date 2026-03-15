import path from 'path';
import * as fs from 'fs';
import { app, BrowserWindow, ipcMain, session } from 'electron';
import serve from 'electron-serve';
import { setupPtyManager, saveAllContexts } from './pty-manager';
import { Vault } from './security/vault';
import { AuditLog } from './security/audit';
import { WalletGuard } from './security/wallet-guard';
import * as crypto from 'crypto';

const isProd = process.env.NODE_ENV === 'production';

if (isProd) {
  serve({ directory: 'app' });
} else {
  app.setPath('userData', `${app.getPath('userData')} (development)`);
}

let mainWindow: BrowserWindow | null = null;

async function initializeSecurity() {
  try {
    const projectDir = process.cwd();
    let envPath = path.join(projectDir, '.env');

    // 0. Initialize Audit Log
    AuditLog.initialize();
    AuditLog.log({
      action: 'SYSTEM_STARTUP',
      details: 'OpenGravity security system initialized',
      level: 'INFO',
      result: 'ALLOWED'
    });

    // 1. Migrate .env to Secure Vault
    envPath = path.join(projectDir, '.env');
    if (!fs.existsSync(envPath)) {
      // Try parent directory (root of the project)
      envPath = path.join(projectDir, '..', '.env');
    }

    if (fs.existsSync(envPath)) {
      console.log(`[Security] Migrating ${envPath} secrets to OS Vault...`);
      try {
        const count = await Vault.migrateFromEnv(envPath);
        console.log(`[Security] Migrated ${count} keys.`);
        
        // Rename to .env.migrated in the same directory as the source .env
        const migratedPath = envPath + '.migrated';
        fs.renameSync(envPath, migratedPath);
        console.log(`[Security] .env renamed to ${migratedPath}`);
      } catch (e) {
        console.error('[Security] Migration error:', e);
      }
    }

    // 2. Generate OPENGRAVITY_API_TOKEN if it doesn't exist
    if (!(await Vault.exists('OPENGRAVITY_API_TOKEN'))) {
      console.log('[Security] Generating new OPENGRAVITY_API_TOKEN...');
      const token = crypto.randomBytes(32).toString('hex');
      await Vault.set('OPENGRAVITY_API_TOKEN', token);
      console.log('[Security] Token generated and saved to Vault.');
    }
  } catch (err) {
    console.error('[Security] Critical initialization failure:', err);
    // Continue anyway to allow app startup
  }
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    frame: false,
    titleBarStyle: 'hidden',
    backgroundColor: '#000000',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  // Setup PTY manager for terminal sessions
  setupPtyManager(mainWindow);

  // ── Content Security Policy ────────────────────────────────────────────────
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    const railwayBase = 'https://chic-encouragement-production.up.railway.app';
    const railwayWs = 'wss://chic-encouragement-production.up.railway.app';
    const apis = `${railwayBase} ${railwayWs} https://*.polymarket.com https://*.coingecko.com https://api.hyperliquid.xyz`;
    const fonts = 'https://cdn.jsdelivr.net https://fonts.googleapis.com https://fonts.gstatic.com';
    const csp = isProd
      ? `default-src 'self' app:; script-src 'self' app:; style-src 'self' app: 'unsafe-inline' ${fonts}; connect-src 'self' ${apis}; font-src 'self' app: ${fonts}; img-src 'self' app: data: https:;`
      : `default-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-eval' 'unsafe-inline'; style-src 'self' 'unsafe-inline' ${fonts}; connect-src 'self' ws://localhost:* http://localhost:* ${apis}; font-src 'self' ${fonts}; img-src 'self' data: https:;`;
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [csp],
      },
    });
  });

  if (isProd) {
    await mainWindow.loadURL('app://./');
  } else {
    const port = process.argv[2] || 8888;
    await mainWindow.loadURL(`http://localhost:${port}/`);
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }
}

app.on('ready', () => {
  console.log('[Main] App ready, initializing...');
  initializeSecurity().finally(() => {
    console.log('[Main] Security init done, creating window...');
    createWindow().catch(err => {
      console.error('[Main] Failed to create window:', err);
    });
  });
});

app.on('before-quit', () => {
  saveAllContexts();
});

app.on('window-all-closed', () => {
  app.quit();
});

// IPC handlers for window controls
ipcMain.on('window-minimize', () => {
  if (mainWindow) mainWindow.minimize();
});
ipcMain.on('window-maximize', () => {
  if (mainWindow) {
    if (mainWindow.isMaximized()) {
      mainWindow.unmaximize();
    } else {
      mainWindow.maximize();
    }
  }
});
ipcMain.handle('vault-get', async (_event, key: string) => {
  return await Vault.get(key);
});

ipcMain.handle('vault-set', async (_event, key: string, value: string) => {
  // Only allow setting known, safe keys — never arbitrary env vars
  const ALLOWED_KEYS = [
    'POLYMARKET_PK', 'POLYMARKET_FUNDER',
    'POLYMARKET_API_KEY', 'POLYMARKET_API_SECRET', 'POLYMARKET_API_PASSPHRASE',
    'OPENGRAVITY_API_TOKEN',
    'ETHERSCAN_API_KEY',
  ];
  if (!ALLOWED_KEYS.includes(key)) return { ok: false, error: 'Key not allowed' };
  await Vault.set(key, value);
  AuditLog.log({ action: 'VAULT_SET', details: `Key stored: ${key}`, level: 'INFO', result: 'ALLOWED' });
  return { ok: true };
});

ipcMain.handle('wallet-request-approval', async (_event, request: any) => {
  if (mainWindow) {
    return await WalletGuard.requestApproval(mainWindow, request);
  }
  return false;
});

ipcMain.on('window-close', () => {
  if (mainWindow) mainWindow.close();
});

// ── Polymarket Data ──────────────────────────────────────────────────────────
const POLY_DATA_DIR = path.join(process.cwd(), 'scripts', 'polymarket', 'data');

function readPolymarketData() {
  let portfolio: any = {};
  try {
    portfolio = JSON.parse(fs.readFileSync(path.join(POLY_DATA_DIR, 'paper_positions.json'), 'utf-8'));
  } catch {}

  let log: any[] = [];
  try {
    const raw = fs.readFileSync(path.join(POLY_DATA_DIR, 'paper_log.jsonl'), 'utf-8');
    log = raw.trim().split('\n').filter(Boolean).map(line => {
      try { return JSON.parse(line); } catch { return null; }
    }).filter(Boolean);
  } catch {}

  let priors: any = {};
  try {
    priors = JSON.parse(fs.readFileSync(path.join(POLY_DATA_DIR, 'bayesian_priors.json'), 'utf-8'));
  } catch {}

  let scanReport: any = {};
  try {
    scanReport = JSON.parse(fs.readFileSync(path.join(POLY_DATA_DIR, 'market_analysis_report.json'), 'utf-8'));
  } catch {}

  let trackedWallets: any[] = [];
  try {
    trackedWallets = JSON.parse(fs.readFileSync(path.join(POLY_DATA_DIR, 'tracked_wallets.json'), 'utf-8'));
  } catch {}

  let walletPositions: any = {};
  try {
    walletPositions = JSON.parse(fs.readFileSync(path.join(POLY_DATA_DIR, 'wallet_positions.json'), 'utf-8'));
  } catch {}

  let copyPositions: any = {};
  try {
    copyPositions = JSON.parse(fs.readFileSync(path.join(POLY_DATA_DIR, 'copy_positions.json'), 'utf-8'));
  } catch {}

  let walletSummary: any = {};
  try {
    walletSummary = JSON.parse(fs.readFileSync(path.join(POLY_DATA_DIR, 'wallet_summary.json'), 'utf-8'));
  } catch {}

  return { portfolio, log, priors, scanReport, trackedWallets, walletPositions, copyPositions, walletSummary };
}

ipcMain.handle('polymarket-data', async () => readPolymarketData());

// ── Polymarket Bot Auto-Cycle ────────────────────────────────────────────────
const POLY_SCRIPT = path.join(process.cwd(), 'scripts', 'polymarket', 'paper_trader.py');
const POLY_CWD = path.join(process.cwd(), 'scripts', 'polymarket');
let polyCycleRunning = false;
const POLY_CYCLE_INTERVAL_MS = 15 * 60 * 1000; // 15 min

function runPolyCycle(): Promise<{ ok: boolean; error?: string }> {
  const { execFile } = require('child_process');
  if (polyCycleRunning) return Promise.resolve({ ok: false, error: 'Cycle already running' });
  polyCycleRunning = true;

  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('polymarket-cycle-status', { running: true });
  }

  return new Promise((resolve) => {
    execFile('python', [POLY_SCRIPT, 'cycle'], {
      cwd: POLY_CWD,
      timeout: 180_000,
      env: { ...process.env },
    }, (error: any, _stdout: string) => {
      polyCycleRunning = false;
      const data = readPolymarketData();
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('polymarket-update', data);
        mainWindow.webContents.send('polymarket-cycle-status', {
          running: false,
          error: error?.message,
          lastCycle: new Date().toISOString(),
        });
      }
      resolve(error ? { ok: false, error: error.message } : { ok: true });
    });
  });
}

// Manual refresh — triggers a full cycle
ipcMain.handle('polymarket-run', async () => runPolyCycle());

// Auto-cycle loop
let polyCycleTimer: ReturnType<typeof setInterval> | null = null;
let polyBotEnabled = true;

function startPolyCycleLoop() {
  if (polyCycleTimer) return;
  // First cycle 30s after app start
  setTimeout(() => { if (polyBotEnabled) runPolyCycle().catch(() => {}); }, 30_000);
  // Then every 15 min
  polyCycleTimer = setInterval(() => { if (polyBotEnabled) runPolyCycle().catch(() => {}); }, POLY_CYCLE_INTERVAL_MS);
}

function stopPolyCycleLoop() {
  if (polyCycleTimer) {
    clearInterval(polyCycleTimer);
    polyCycleTimer = null;
  }
}

// Toggle bot on/off
ipcMain.handle('polymarket-toggle', async () => {
  polyBotEnabled = !polyBotEnabled;
  if (polyBotEnabled) {
    startPolyCycleLoop();
  } else {
    stopPolyCycleLoop();
  }
  return { enabled: polyBotEnabled };
});

// Get current bot status
ipcMain.handle('polymarket-status', async () => ({ enabled: polyBotEnabled }));

// ── Wallet Tracker ──────────────────────────────────────────────────────────
const WALLET_TRACKER_SCRIPT = path.join(process.cwd(), 'scripts', 'polymarket', 'wallet_tracker.py');

ipcMain.handle('polymarket-wallet-discover', async () => {
  const { execFile } = require('child_process');
  return new Promise((resolve) => {
    execFile('python', [WALLET_TRACKER_SCRIPT, 'discover'], {
      cwd: POLY_CWD, timeout: 120_000, env: { ...process.env },
    }, (error: any) => {
      if (!error && mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('polymarket-update', readPolymarketData());
      }
      resolve(error ? { ok: false, error: error.message } : { ok: true });
    });
  });
});

ipcMain.handle('polymarket-wallet-update', async () => {
  const { execFile } = require('child_process');
  return new Promise((resolve) => {
    execFile('python', [WALLET_TRACKER_SCRIPT, 'update'], {
      cwd: POLY_CWD, timeout: 120_000, env: { ...process.env },
    }, (error: any) => {
      if (!error && mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('polymarket-update', readPolymarketData());
      }
      resolve(error ? { ok: false, error: error.message } : { ok: true });
    });
  });
});

// ── Copy Trading Auto-Cycle (4h) ─────────────────────────────────────────────
let copyCycleRunning = false;
const COPY_CYCLE_INTERVAL_MS = 4 * 60 * 60 * 1000; // 4 hours
let copyCycleTimer: ReturnType<typeof setInterval> | null = null;

function runCopyCycle(): Promise<{ ok: boolean; error?: string }> {
  const { execFile } = require('child_process');
  if (copyCycleRunning) return Promise.resolve({ ok: false, error: 'Copy cycle already running' });
  copyCycleRunning = true;

  return new Promise((resolve) => {
    execFile('python', [WALLET_TRACKER_SCRIPT, 'full-cycle'], {
      cwd: POLY_CWD, timeout: 300_000, env: { ...process.env },
    }, (error: any) => {
      copyCycleRunning = false;
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('polymarket-update', readPolymarketData());
      }
      resolve(error ? { ok: false, error: error.message } : { ok: true });
    });
  });
}

ipcMain.handle('polymarket-copy-cycle', async () => runCopyCycle());

// ── Copy Daemon control (Task Scheduler) ─────────────────────────────────────
const COPY_DAEMON_SCRIPT = path.join(process.cwd(), 'scripts', 'polymarket', 'copy_daemon.py');

function runDaemonCmd(arg: string): Promise<{ ok: boolean; output: string }> {
  const { execFile } = require('child_process');
  return new Promise((resolve) => {
    execFile('python', [COPY_DAEMON_SCRIPT, arg], {
      cwd: POLY_CWD, timeout: 30_000, env: { ...process.env },
    }, (error: any, stdout: string, stderr: string) => {
      resolve({ ok: !error, output: stdout || stderr || error?.message || '' });
    });
  });
}

ipcMain.handle('copy-daemon-install', async () => runDaemonCmd('--install'));
ipcMain.handle('copy-daemon-uninstall', async () => runDaemonCmd('--uninstall'));
ipcMain.handle('copy-daemon-status', async () => runDaemonCmd('--status'));

// ── Strategy Results (lee JSONs de moondev/results/) ──
const RESULTS_DIR = path.join(process.cwd(), '..', 'moondev', 'results');

ipcMain.handle('strategy-results', async () => {
  try {
    if (!fs.existsSync(RESULTS_DIR)) return { leaderboard: [], error: 'Directorio no encontrado: ' + RESULTS_DIR };
    const files = fs.readdirSync(RESULTS_DIR).filter(f => f.endsWith('.json') && f.startsWith('multi_'));
    const bestByStrategy: Record<string, any> = {};
    for (const file of files) {
      try {
        const data = JSON.parse(fs.readFileSync(path.join(RESULTS_DIR, file), 'utf8'));
        const strategy = data.strategy;
        for (const sym of (data.symbols || [])) {
          const existing = bestByStrategy[strategy];
          if (!existing || sym.sharpe > existing.sharpe) {
            bestByStrategy[strategy] = {
              strategy,
              period: data.period,
              interval: data.interval,
              generated_at: data.generated_at,
              global_verdict: data.summary?.global_verdict || 'NO_VIABLE',
              passing: data.summary?.passing || 0,
              total_assets: data.symbols?.length || 0,
              best_symbol: sym.symbol,
              return_pct: sym.return_pct,
              sharpe: sym.sharpe,
              max_dd: sym.max_dd,
              trades: sym.trades,
              win_rate: sym.win_rate,
              verdict: sym.verdict,
            };
          }
        }
      } catch {}
    }
    const leaderboard = Object.values(bestByStrategy).sort((a: any, b: any) => b.sharpe - a.sharpe);
    return { leaderboard, total_files: files.length };
  } catch (e) {
    return { leaderboard: [], error: String(e) };
  }
});

// Watcher: notifica al renderer cuando llegan nuevos resultados
let resultsWatcher: fs.FSWatcher | null = null;
let resultsDebounce: ReturnType<typeof setTimeout> | null = null;

function startResultsWatcher() {
  if (resultsWatcher || !fs.existsSync(RESULTS_DIR)) return;
  try {
    resultsWatcher = fs.watch(RESULTS_DIR, (_evt, filename) => {
      if (!filename?.endsWith('.json')) return;
      if (resultsDebounce) clearTimeout(resultsDebounce);
      resultsDebounce = setTimeout(() => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('strategy-results-update');
        }
      }, 800);
    });
  } catch {}
}

function startCopyCycleLoop() {
  if (copyCycleTimer) return;
  // First copy cycle 2 min after app start
  setTimeout(() => { if (polyBotEnabled) runCopyCycle().catch(() => {}); }, 120_000);
  // Then every 4 hours
  copyCycleTimer = setInterval(() => { if (polyBotEnabled) runCopyCycle().catch(() => {}); }, COPY_CYCLE_INTERVAL_MS);
}

// Watch data files for real-time push to renderer
let polyWatcher: fs.FSWatcher | null = null;
let polyDebounce: ReturnType<typeof setTimeout> | null = null;

function startPolymarketWatcher() {
  if (polyWatcher) return;
  try {
    fs.mkdirSync(POLY_DATA_DIR, { recursive: true });
    polyWatcher = fs.watch(POLY_DATA_DIR, (_eventType, filename) => {
      if (!filename || (!filename.endsWith('.json') && !filename.endsWith('.jsonl'))) return;
      if (polyDebounce) clearTimeout(polyDebounce);
      polyDebounce = setTimeout(() => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('polymarket-update', readPolymarketData());
        }
      }, 500);
    });
  } catch {}
}

app.whenReady().then(() => {
  startPolymarketWatcher();
  startPolyCycleLoop();
  startCopyCycleLoop();
  startResultsWatcher();
});
