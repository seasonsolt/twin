import { defineConfig } from 'vitest/config';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  base: '/next/',
  plugins: [tailwindcss()],
  build: {
    outDir: '../src/twin/web/static/next',
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
  server: { proxy: { '/api': 'http://127.0.0.1:8765' } },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    clearMocks: true,
    restoreMocks: true,
  },
});
