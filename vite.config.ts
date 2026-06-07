import { defineConfig, Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

function serveVadWasm(): Plugin {
  return {
    name: 'serve-vad-wasm',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.startsWith('/vad/') && req.url.includes('.mjs')) {
          const clean = req.url.split('?')[0]
          req.url = clean
          req.originalUrl = clean
        }
        next()
      })
    },
  }
}

export default defineConfig({
  plugins: [serveVadWasm(), react()],
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
    include: ['@ricky0123/vad-web'],
  },
  server: {
    port: 5173,
    proxy: {
      '/ws': {
        target: 'http://127.0.0.1:8765',
        ws: true,
      },
    },
    headers: {
      'Cross-Origin-Embedder-Policy': 'require-corp',
      'Cross-Origin-Opener-Policy': 'same-origin',
    },
  },
})
