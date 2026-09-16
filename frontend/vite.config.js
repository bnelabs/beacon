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
          'query-vendor': ['@tanstack/react-query', 'zustand'],
          // deck.gl is ~90% of the risk-map chunk and changes when the
          // lockfile changes, not when app code does: splitting it out keeps
          // the route chunk small and the heavy vendor bytes cached across
          // releases. @deck.gl/aggregation-layers is deliberately NOT listed
          // -- RiskMap imports it dynamically (the heatmap is a toggle), so
          // Rollup keeps it as its own async chunk, fetched only when the
          // heatmap is on.
          'deck-vendor': ['@deck.gl/react', '@deck.gl/core', '@deck.gl/layers']
        }
      }
    },
    chunkSizeWarningLimit: 1000,
    sourcemap: false
  }
})
