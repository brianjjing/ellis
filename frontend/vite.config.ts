import { defineConfig } from 'vite'

const api = process.env.ELLIS_API ?? 'http://localhost:8000'

// The Case API serves /api, /tools and /files; the dev server proxies them (including WebSockets).
export default defineConfig({
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': { target: api, ws: true, changeOrigin: true },
      '/files': { target: api, changeOrigin: true },
    },
  },
  preview: {
    proxy: {
      '/api': { target: api, ws: true, changeOrigin: true },
      '/files': { target: api, changeOrigin: true },
    },
  },
})
