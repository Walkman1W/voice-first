import { app, BrowserWindow, ipcMain } from 'electron'
import { spawn, ChildProcess } from 'child_process'
import path from 'path'
import net from 'net'

let mainWindow: BrowserWindow | null = null
let backendProcess: ChildProcess | null = null
const BACKEND_PORT = 8765

function getResourcePath(...segments: string[]): string {
  const base = app.isPackaged
    ? path.join(process.resourcesPath, 'app')
    : path.join(__dirname, '..')
  return path.join(base, ...segments)
}

function waitForPort(port: number, timeout = 10000): Promise<void> {
  const start = Date.now()
  return new Promise((resolve, reject) => {
    const check = () => {
      const socket = new net.Socket()
      socket.once('connect', () => {
        socket.destroy()
        resolve()
      })
      socket.once('error', () => {
        socket.destroy()
        if (Date.now() - start > timeout) {
          reject(new Error(`Backend did not start within ${timeout}ms`))
        } else {
          setTimeout(check, 200)
        }
      })
      socket.connect(port, '127.0.0.1')
    }
    check()
  })
}

function startBackend(): void {
  const backendScript = getResourcePath('backend', 'main.py')
  const env = { ...process.env, PORT: String(BACKEND_PORT), HOST: '127.0.0.1' }

  backendProcess = spawn('python3', [backendScript], {
    env,
    cwd: getResourcePath(),
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  backendProcess.stdout?.on('data', (data) => {
    const msg = data.toString().trim()
    if (msg) console.log('[backend]', msg)
    mainWindow?.webContents.send('backend-log', msg)
  })

  backendProcess.stderr?.on('data', (data) => {
    const msg = data.toString().trim()
    if (msg) console.error('[backend]', msg)
    mainWindow?.webContents.send('backend-log', msg)
  })

  backendProcess.on('exit', (code) => {
    console.log(`[backend] exited with code ${code}`)
    backendProcess = null
  })
}

function stopBackend(): void {
  if (backendProcess) {
    backendProcess.kill('SIGTERM')
    setTimeout(() => {
      if (backendProcess && !backendProcess.killed) {
        backendProcess.kill('SIGKILL')
      }
    }, 3000)
  }
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 440,
    height: 780,
    minWidth: 380,
    minHeight: 600,
    title: '小龙虾语音助手',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
    autoHideMenuBar: true,
    backgroundColor: '#1a1a2e',
    show: false,
  })

  mainWindow.once('ready-to-show', () => {
    mainWindow?.show()
  })

  if (process.env.VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL)
    mainWindow.webContents.openDevTools({ mode: 'detach' })
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'))
  }

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

ipcMain.handle('get-backend-url', () => {
  return `ws://127.0.0.1:${BACKEND_PORT}/ws`
})

ipcMain.handle('get-backend-port', () => BACKEND_PORT)

app.whenReady().then(async () => {
  startBackend()
  try {
    await waitForPort(BACKEND_PORT)
    console.log('[main] Backend is ready')
  } catch (e) {
    console.error('[main] Backend failed to start:', e)
  }
  createWindow()
})

app.on('window-all-closed', () => {
  stopBackend()
  app.quit()
})

app.on('before-quit', () => {
  stopBackend()
})

app.on('activate', () => {
  if (mainWindow === null) createWindow()
})
