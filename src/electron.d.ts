interface ElectronAPI {
  getBackendUrl: () => Promise<string>
  getBackendPort: () => Promise<number>
  onBackendLog: (callback: (msg: string) => void) => void
  isElectron: true
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}

export {}
