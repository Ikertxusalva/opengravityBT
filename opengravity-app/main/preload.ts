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
  },
});
