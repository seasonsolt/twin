import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// The files run in parallel, and on a busy CI runner a lazy page or a chain of requests can take longer than the 1s
// findBy/waitFor wait for by default; they still go on as soon as what they wait for is there.
configure({ asyncUtilTimeout: 5000 });

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Node 25+ has its own localStorage/sessionStorage globals (undefined without --localstorage-file), and Vitest only
// copies jsdom's window keys that Node lacks, so point both back at jsdom's storage.
const { window: dom } = (globalThis as unknown as { jsdom: { window: Window } })
  .jsdom;
for (const key of ['localStorage', 'sessionStorage'] as const) {
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value: dom[key],
  });
}

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
Object.defineProperty(globalThis, 'ResizeObserver', {
  writable: true,
  value: ResizeObserverMock,
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
