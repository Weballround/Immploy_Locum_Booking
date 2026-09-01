/// <reference types="vitest/config" />
import fs from 'node:fs'

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(() => {
  const lanHost = process.env.VITE_LAN_HOST
  const certificatePath = process.env.VITE_HTTPS_CERT
  const privateKeyPath = process.env.VITE_HTTPS_KEY
  const https = certificatePath && privateKeyPath
    ? {
        cert: fs.readFileSync(certificatePath),
        key: fs.readFileSync(privateKeyPath),
      }
    : undefined

  return {
    plugins: [react()],
    build: {
      // Browser code cannot be hidden, but production source maps would expose
      // the original TypeScript structure and source paths unnecessarily.
      sourcemap: false,
    },
    server: {
      host: lanHost || '127.0.0.1',
      https,
      proxy: {
        '/api': 'http://127.0.0.1:8000',
        '/admin': 'http://127.0.0.1:8000',
        '/static': 'http://127.0.0.1:8000',
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
    },
  }
})
