const fs = require('fs')
const path = require('path')

const publicDir = path.join(__dirname, '..', 'public', 'vad')
const distDir = path.join(__dirname, '..', 'dist', 'vad')

const commonFiles = [
  ['@ricky0123/vad-web/dist/silero_vad_v5.onnx', 'silero_vad_v5.onnx'],
  ['@ricky0123/vad-web/dist/vad.worklet.bundle.min.js', 'vad.worklet.bundle.min.js'],
  ['onnxruntime-web/dist/ort-wasm-simd-threaded.wasm', 'ort-wasm-simd-threaded.wasm'],
  ['onnxruntime-web/dist/ort-wasm-simd-threaded.jsep.wasm', 'ort-wasm-simd-threaded.jsep.wasm'],
]

// .mjs only goes to dist (production), NOT public (Vite blocks import() from public/)
const distOnlyFiles = [
  ['onnxruntime-web/dist/ort-wasm-simd-threaded.mjs', 'ort-wasm-simd-threaded.mjs'],
  ['onnxruntime-web/dist/ort-wasm-simd-threaded.jsep.mjs', 'ort-wasm-simd-threaded.jsep.mjs'],
  ['onnxruntime-web/dist/ort-wasm-simd-threaded.jspi.mjs', 'ort-wasm-simd-threaded.jspi.mjs'],
  ['onnxruntime-web/dist/ort-wasm-simd-threaded.asyncify.mjs', 'ort-wasm-simd-threaded.asyncify.mjs'],
]

function copyFiles(files, targetDir) {
  fs.mkdirSync(targetDir, { recursive: true })
  for (const [src, dest] of files) {
    const srcPath = path.join(__dirname, '..', 'node_modules', src)
    const destPath = path.join(targetDir, dest)
    if (fs.existsSync(srcPath)) {
      fs.copyFileSync(srcPath, destPath)
      console.log(`Copied: ${dest} -> ${path.relative(path.join(__dirname, '..'), targetDir)}`)
    } else {
      console.warn(`Skip (not found): ${src}`)
    }
  }
}

copyFiles(commonFiles, publicDir)
copyFiles(commonFiles, distDir)
copyFiles(distOnlyFiles, distDir)
