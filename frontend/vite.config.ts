import { defineConfig } from 'vitest/config';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  base: './',
  plugins: [tailwindcss()],
  build: {
    outDir: '../src/twin/web/static',
    emptyOutDir: true,
    sourcemap: false,
    modulePreload: { polyfill: false },
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router'],
          motion: ['motion/react'],
        },
      },
    },
  },
  server: {
    proxy: { '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true } },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    clearMocks: true,
    restoreMocks: true,
    // Room for the longer waits in src/test/setup.ts, several of which a test may make in a row.
    testTimeout: 20000,
    // Half the cores on a shared machine (scripts/check.py passes its own share); CI keeps all of its own.
    maxWorkers: process.env.CI ? undefined : '50%',
  },
});
