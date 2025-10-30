import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  return {
    plugins: [react()],
    server: {
      port: Number(env.PORT || 5173),
      host: '0.0.0.0'
    },
    preview: {
      port: 5173,
      host: '0.0.0.0'
    },
    build: {
      sourcemap: true
    },
    define: {
      __API_BASE_URL__: JSON.stringify(env.VITE_API_BASE_URL || 'http://localhost:3456')
    }
  }
})
