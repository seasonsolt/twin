import { render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { expect, it, vi } from 'vitest';
import { AppShell } from '../components/layout/AppShell';
import { ConfirmProvider, TooltipProvider } from '../components/ui';
import { About } from '../pages/About';
import { useStatus, type Status } from '../stores/status';

it('keeps only name/AI label in the header and describes external hosts only on About', async () => {
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
  const status: Status = {
    target_name: '测试人',
    counts: { sources: 1, items: 2 },
    llm: { provider: 'mock', model: 'mock-model' },
    embed: { provider: 'local' },
    egress: [
      {
        kind: 'llm',
        provider: 'remote-provider',
        host: 'example.test',
        external: true,
        declared: true,
      },
      {
        kind: 'embed',
        provider: 'local-provider',
        host: 'localhost',
        external: false,
        declared: false,
      },
    ],
  };
  const previous = useStatus.getState();
  useStatus.setState({ data: null, error: null });
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            path.startsWith('/api/persona/items')
              ? []
              : path.startsWith('/api/persona/coverage')
                ? { facets: [], suggestions: [], kind_labels: {} }
                : path === '/api/status'
                  ? status
                  : path === '/api/identity'
                    ? {
                        name: '身份测试人',
                        aliases: [],
                        voice: null,
                        avatar: null,
                        egress: [],
                      }
                    : { available: false, backend: null },
          ),
        ),
      ),
    ),
  );
  const rendered = render(
    <TooltipProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={['/about']}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="about" element={<About />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ConfirmProvider>
    </TooltipProvider>,
  );
  try {
    expect(
      await screen.findByRole('heading', { name: '身份测试人' }),
    ).toBeVisible();
    expect(rendered.container.querySelector('footer')).toBeNull();
    const header = within(rendered.container.querySelector('header')!);
    expect(header.getByText('身份测试人')).toBeVisible();
    expect(
      header.queryByText(/mock-model|example.test|remote-provider|外部/),
    ).not.toBeInTheDocument();
    expect(screen.getByText('大模型：example.test')).toBeVisible();
    expect(
      screen.queryByText(/外部 ·|remote-provider/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/localhost|local-provider/),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '关于你' })).toHaveAttribute(
      'href',
      '/about',
    );
    expect(screen.getByRole('heading', { name: '关于你' })).toBeInTheDocument();
    expect(
      screen.getByRole('navigation', { name: '主导航' }).querySelectorAll('a'),
    ).toHaveLength(3);
  } finally {
    rendered.unmount();
    useStatus.setState({ data: previous.data, error: previous.error });
    vi.restoreAllMocks();
  }
});
