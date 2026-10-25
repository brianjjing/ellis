import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',
  timeout: 60_000,
  use: { baseURL: process.env.ELLIS_WEB ?? 'http://localhost:5173' },
})
