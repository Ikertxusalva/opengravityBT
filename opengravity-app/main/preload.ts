import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('electron', {
  // Window controls
  minimize: () => ipcRenderer.send('window-minimize'),
  maximize: () => ipcRenderer.send('window-maximize'),
  close: () => ipcRenderer.send('window-close'),

  // PTY terminal management
  pty: {
    create: (termId: string, agentId: string, rows: number, cols: number) =>
      ipcRenderer.invoke('pty-create', termId, agentId, rows, cols),
    write: (termId: string, data: string) =>
      ipcRenderer.send('pty-input', termId, data),
    resize: (termId: string, cols: number, rows: number) =>
      ipcRenderer.send('pty-resize', termId, cols, rows),
    kill: (termId: string) =>
      ipcRenderer.send('pty-kill', termId),
    killAll: () =>
      ipcRenderer.send('pty-kill-all'),
    onData: (callback: (termId: string, data: string) => void) => {
      const handler = (_event: any, termId: string, data: string) => callback(termId, data);
      ipcRenderer.on('pty-data', handler);
      return () => { ipcRenderer.removeListener('pty-data', handler); };
    },
    onRestart: (callback: (termId: string, agentId: string) => void) => {
      const handler = (_event: any, termId: string, agentId: string) => callback(termId, agentId);
      ipcRenderer.on('pty-restart', handler);
      return () => { ipcRenderer.removeListener('pty-restart', handler); };
    },
  },

  // Vault/Security
  vault: {
    get: (key: string) => ipcRenderer.invoke('vault-get', key),
    set: (key: string, value: string) => ipcRenderer.invoke('vault-set', key, value),
  },

  // Swarm orchestration
  swarm: {
    getStatus: () => ipcRenderer.invoke('swarm-get-status'),
    inject: (agentId: string, prompt: string) =>
      ipcRenderer.invoke('pty-inject', agentId, prompt),
    confirmOrder: (orderId: string) =>
      ipcRenderer.invoke('swarm-confirm-order', orderId),
    rejectOrder: (orderId: string) =>
      ipcRenderer.invoke('swarm-reject-order', orderId),
    getPendingOrders: () =>
      ipcRenderer.invoke('swarm-pending-orders'),
    onOrderPending: (callback: (order: any) => void) => {
      const handler = (_event: any, order: any) => callback(order);
      ipcRenderer.on('swarm-order-pending', handler);
      return () => { ipcRenderer.removeListener('swarm-order-pending', handler); };
    },
    onOrderExecuted: (callback: (result: any) => void) => {
      const handler = (_event: any, result: any) => callback(result);
      ipcRenderer.on('swarm-order-executed', handler);
      return () => { ipcRenderer.removeListener('swarm-order-executed', handler); };
    },
  },

  // Strategy results leaderboard
  strategies: {
    getResults: () => ipcRenderer.invoke('strategy-results'),
    onUpdate: (callback: () => void) => {
      const handler = () => callback();
      ipcRenderer.on('strategy-results-update', handler);
      return () => { ipcRenderer.removeListener('strategy-results-update', handler); };
    },
  },

  // Agent Memory system
  memory: {
    getStats: (agentId: string) => ipcRenderer.invoke('memory-get-stats', agentId),
    getAll: (agentId: string) => ipcRenderer.invoke('memory-get-all', agentId),
    search: (agentId: string, query: string) => ipcRenderer.invoke('memory-search', agentId, query),
    save: (params: any) => ipcRenderer.invoke('memory-save', params),
    delete: (memoryId: string, agentId: string) => ipcRenderer.invoke('memory-delete', memoryId, agentId),
  },

  // Polymarket paper trading dashboard
  polymarket: {
    getData: () => ipcRenderer.invoke('polymarket-data'),
    runCycle: () => ipcRenderer.invoke('polymarket-run'),
    toggle: () => ipcRenderer.invoke('polymarket-toggle'),
    getStatus: () => ipcRenderer.invoke('polymarket-status'),
    walletDiscover: () => ipcRenderer.invoke('polymarket-wallet-discover'),
    walletUpdate: () => ipcRenderer.invoke('polymarket-wallet-update'),
    copyCycle: () => ipcRenderer.invoke('polymarket-copy-cycle'),
    daemonInstall: () => ipcRenderer.invoke('copy-daemon-install'),
    daemonUninstall: () => ipcRenderer.invoke('copy-daemon-uninstall'),
    daemonStatus: () => ipcRenderer.invoke('copy-daemon-status'),
    daemonStart: () => ipcRenderer.invoke('copy-daemon-start'),
    daemonStop: () => ipcRenderer.invoke('copy-daemon-stop'),
    daemonRunning: () => ipcRenderer.invoke('copy-daemon-running'),
    onUpdate: (callback: (data: any) => void) => {
      const handler = (_event: any, data: any) => callback(data);
      ipcRenderer.on('polymarket-update', handler);
      return () => { ipcRenderer.removeListener('polymarket-update', handler); };
    },
    onCycleStatus: (callback: (status: { running: boolean; error?: string; lastCycle?: string }) => void) => {
      const handler = (_event: any, status: any) => callback(status);
      ipcRenderer.on('polymarket-cycle-status', handler);
      return () => { ipcRenderer.removeListener('polymarket-cycle-status', handler); };
    },
  },
});
