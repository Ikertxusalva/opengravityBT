import path from 'path';
import * as fs from 'fs';
import { app, BrowserWindow, ipcMain } from 'electron';
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
