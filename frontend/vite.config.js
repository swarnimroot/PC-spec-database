import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Backend (FastAPI) target for the dev-server proxy. Override for non-default setups.
const API_TARGET = process.env.VITE_API_TARGET || 'http://localhost:8011'

// https://vite.dev/config/
export default defineConfig({
  base: '/competitive-database/',
  plugins: [react()],
  server: {
    port: 8501,
    strictPort: true,
    // Let the Tailscale Funnel hostname reach the dev server (Vite blocks
    // non-localhost Host headers by default). '.ts.net' = any tailnet host.
    allowedHosts: ['.ts.net'],
    // Browser calls /competitive-database/api/* on its own origin; forward to
    // the backend and strip the base prefix. Keeps the API same-origin so it
    // works locally AND through the Funnel with no hardcoded host in the bundle.
    proxy: {
      '/competitive-database/api': {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/competitive-database/, ''),
      },
    },
  },
})
