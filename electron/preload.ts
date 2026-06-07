import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  getBackendUrl: () => ipcRenderer.invoke('get-backend-url'),
  getBackendPort: () => ipcRenderer.invoke('get-backend-port'),
  onBackendLog: (callback: (msg: string) => void) => {
    ipcRenderer.on('backend-log', (_event, msg) => callback(msg))
  },
  isElectron: true,
})
