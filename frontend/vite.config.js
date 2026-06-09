import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  base: '/competitive-database/',
  plugins: [react()],
  server: {
    port: 8501,
    strictPort: true,
  },
})
