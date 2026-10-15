import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', port: 5173, proxy: { '/api': 'http://127.0.0.1:8000', '/uploads': 'http://127.0.0.1:8000', '/health': 'http://127.0.0.1:8000' } },
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
