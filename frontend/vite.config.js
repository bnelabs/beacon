import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Single source of truth for the user-visible version: package.json, kept in
// step with the repository VERSION file by scripts/release.py.
const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url)))

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version)
  },
  server: {
    host: '0.0.0.0',
    port: 5173
  },
  build: {
    target: 'es2020',
    minify: 'esbuild',
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom'],
          'query-vendor': ['@tanstack/react-query', 'zustand']
        }
      }
    },
    chunkSizeWarningLimit: 1000,
    sourcemap: false
  }
})
