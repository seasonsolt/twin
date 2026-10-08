import { render, screen, waitFor, within } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { App } from '../App';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));

it.each([
  ['sources', 'memories'],
  ['memories', 'memories'],
  ['about', null],
  ['persona', null],
  ['identity', null],
])('redirects the old #/%s bookmark to the profile', async (route, section) => {
  window.location.hash = `#/${route}`;
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
                : url === '/api/persona/sources' ||
                    url.startsWith('/api/persona/items')
                  ? []
                  : url === '/api/persona/processing'
                    ? { state: 'idle' }
                    : url === '/api/persona/coverage'
                      ? { facets: [], suggestions: [], kind_labels: {} }
                      : url === '/api/identity'
                        ? {
                            name: '测试人',
                            name_source: 'user',
                            about: '',
                            aliases: [],
                            egress: [],
                          }
                        : url === '/api/media/capabilities'
                          ? { available: false }
                          : {
                              target_name: '测试人',
                              counts: { sources: 1, items: 0 },
                              egress: [],
                            },
          ),
        ),
    ),
  );
  render(<App />);
  await screen.findByRole('heading', {
    name: section === 'memories' ? '他记得的事' : '我了解到的他',
  });
  await waitFor(() =>
    expect(
      screen.getByRole('tabpanel', {
        name: section === 'memories' ? '记忆' : '概览',
      }),
    ).toBeVisible(),
  );
  await waitFor(() =>
    expect(window.location.hash).toBe(
      section ? `#/profile?section=${section}` : '#/profile',
    ),
  );
  expect(screen.getByRole('link', { name: '档案' })).toHaveAttribute(
    'href',
    '#/profile',
  );
  expect(
    within(screen.getByRole('navigation', { name: '主导航' })).getAllByRole(
      'link',
    ),
  ).toHaveLength(2);
  expect(screen.getAllByRole('button', { name: '切换分身' })).toHaveLength(1);
  expect(screen.getByRole('tablist', { name: '档案章节' })).toBeInTheDocument();
});
