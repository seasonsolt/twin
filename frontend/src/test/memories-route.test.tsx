import { render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { expect, it, vi } from 'vitest';

const { mountRoot } = vi.hoisted(() => ({ mountRoot: vi.fn() }));
vi.mock('react-dom/client', () => ({
  createRoot: () => ({ render: mountRoot }),
}));
vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));

it('redirects the old #/sources bookmark to #/memories and labels navigation 记忆', async () => {
  window.location.hash = '#/sources';
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (url: string) =>
        new Response(
          JSON.stringify(
            url === '/api/whoami'
              ? { email: null, admin: true, auth_enabled: false }
              : url === '/api/personas'
                ? [{ id: 'default', name: '测试人', is_default: true }]
                : url === '/api/persona/sources'
                  ? []
                  : url === '/api/persona/processing'
                    ? { state: 'idle' }
                    : {
                        target_name: '测试人',
                        counts: { sources: 0, items: 0 },
                        llm: { provider: 'mock', model: 'mock' },
                        embed: { provider: 'local' },
                        egress: [],
                      },
          ),
        ),
    ),
  );
  await import('../main');
  const page = render(mountRoot.mock.calls[0][0] as ReactNode);
  try {
    await screen.findByRole('heading', { name: '他记得的事', level: 2 });
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: '他记得的事', level: 2 }),
      ).toBeVisible(),
    );
    await waitFor(() => expect(window.location.hash).toBe('#/memories'));
    expect(screen.getByRole('link', { name: '记忆' })).toHaveAttribute(
      'href',
      '#/memories',
    );
  } finally {
    page.unmount();
    window.location.hash = '';
  }
});
