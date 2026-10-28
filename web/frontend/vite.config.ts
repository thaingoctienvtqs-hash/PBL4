import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Integration settings are opt-in; the existing launch profile keeps its defaults.
const env = (globalThis as typeof globalThis & { process?: { env: Record<string, string | undefined> } }).process?.env ?? {}
const integration = env.ARTGUARD_INTEGRATION_TEST === '1'
const backend = integration ? env.ARTGUARD_BACKEND_ORIGIN ?? 'http://127.0.0.1:8101' : 'http://127.0.0.1:8000'
const port = integration ? Number(env.ARTGUARD_FRONTEND_PORT ?? '5175') : 5173
if (integration && !/^http:\/\/(127\.0\.0\.1|localhost):[0-9]+$/.test(backend)) throw new Error('TEST backend must use loopback HTTP')
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Invalid frontend port')

export default defineConfig({
  plugins: [react()],
  ...(integration && env.ARTGUARD_FRONTEND_CACHE_DIR ? { cacheDir: env.ARTGUARD_FRONTEND_CACHE_DIR } : {}),
  server: { host: '127.0.0.1', port, strictPort: integration, proxy: { '/api': backend, '/uploads': backend, '/health': backend } },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('recharts') || id.includes('/d3-')) return 'charts'
          if (id.includes('lucide-react')) return 'icons'
          if (id.includes('react-router') || id.includes('@remix-run/router') || id.includes('/react-dom/') || id.includes('/react/') || id.includes('/scheduler/') || id.includes('/react-is/')) return 'react-vendor'
          return 'vendor'
        },
      },
    },
  },
})
