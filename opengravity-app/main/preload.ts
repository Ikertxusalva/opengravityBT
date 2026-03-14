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
      ipcRenderer.on('pty-data', (_event, termId, data) => callback(termId, data));
    },
    onRestart: (callback: (termId: string, agentId: string) => void) => {
      ipcRenderer.on('pty-restart', (_event, termId, agentId) => callback(termId, agentId));
    },
  },
});
