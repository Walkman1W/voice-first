import { defineConfig, Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import electron from 'vite-plugin-electron'
import renderer from 'vite-plugin-electron-renderer'
import path from 'path'
import fs from 'fs'

function ortWasmPlugin(): Plugin {
  return {
    name: 'vite-plugin-ort-wasm',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = req.url?.split('?')[0]
        if (url && /\/vad\/ort-wasm.*\.mjs$/.test(url)) {
          const fileName = url.replace('/vad/', '')
          const filePath = path.join(__dirname, 'node_modules/onnxruntime-web/dist', fileName)
          if (fs.existsSync(filePath)) {
            res.setHeader('Content-Type', 'application/javascript')
            res.setHeader('Cache-Control', 'no-cache')
            fs.createReadStream(filePath).pipe(res)
            return
          }
        }
        next()
      })
    },
  }
}

export default defineConfig(({ mode }) => {
  const isElectron = mode === 'electron'

  return {
    plugins: [
      ortWasmPlugin(),
      react(),
      ...(isElectron
        ? [
            electron([
              {
                entry: 'electron/main.ts',
                vite: {
                  build: {
                    outDir: 'dist-electron',
                    rollupOptions: {
                      external: ['electron'],
                    },
                  },
                },
              },
            ]),
            renderer(),
          ]
        : []),
    ],
    root: '.',
    build: {
      outDir: 'dist',
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, 'src'),
      },
    },
    optimizeDeps: {
      include: ['onnxruntime-web'],
    },
    server: {
      port: 5173,
      proxy: {
        '/ws': {
          target: 'http://127.0.0.1:3456',
          ws: true,
        },
      },
    },
  }
})
