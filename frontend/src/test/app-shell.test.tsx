import { act, render, screen, within, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { expect, it, vi } from 'vitest';
import { AppShell } from '../components/layout/AppShell';
import { ConfirmProvider, TooltipProvider } from '../components/ui';
import { Profile } from '../pages/Profile';
import { useStatus, type Status } from '../stores/status';
import { useAuth } from '../stores/auth';
import {
  isItemSummaryUrl,
  isSourcesUrl,
  itemSummary,
  itemsPage,
  sourcesPage,
} from './personaApi';

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
            isSourcesUrl(path)
              ? sourcesPage(path, [])
              : isItemSummaryUrl(path)
                ? itemSummary([])
                : path.startsWith('/api/persona/items')
                  ? itemsPage(path, [])
                  : path === '/api/personas'
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
        <MemoryRouter initialEntries={['/profile']}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="profile" element={<Profile />} />
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
    expect(header.getByRole('heading', { name: '身份测试人' })).toBeVisible();
    expect(
      header.queryByText(/mock-model|example.test|remote-provider|外部/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText('大模型：example.test')).toBeNull();
    await act(async () => screen.getByRole('button', { name: '设置' }).click());
    const settings = await screen.findByRole('dialog', { name: '分身设置' });
    await act(async () =>
      within(settings).getByRole('button', { name: '外部服务' }).click(),
    );
    expect(
      await within(settings).findByText('大模型：example.test'),
    ).toBeVisible();
    await act(async () =>
      within(settings).getAllByRole('button', { name: '关闭' })[0].click(),
    );
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: '分身设置' })).toBeNull(),
    );
    expect(
      screen.queryByText(/外部 ·|remote-provider/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/localhost|local-provider/),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '档案' })).toHaveAttribute(
      'href',
      '/profile',
    );
    expect(screen.getByRole('heading', { name: '人格' })).toBeInTheDocument();
    expect(
      screen.getByRole('navigation', { name: '主导航' }).querySelectorAll('a'),
    ).toHaveLength(4);
    for (const label of [
      '团队',
      '录音库',
      '聊天',
      '工作',
      '档案',
      '承诺账本',
    ]) {
      const link = screen.getByRole('link', { name: label });
      expect(link).toHaveAttribute('aria-label', label);
      expect(link).toHaveClass('size-11', 'rounded-md');
      expect(within(link).getByText(label)).toHaveClass('sr-only');
    }
    expect(screen.getByRole('link', { name: '档案' })).toHaveClass(
      'bg-surface',
      'shadow-elevation-1',
    );
    const switcher = screen.getByRole('button', {
      name: '切换分身（当前：本人）',
    });
    await act(async () => switcher.click());
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: '切换分身' })).toBeVisible(),
    );
    await act(async () =>
      within(screen.getByRole('dialog', { name: '切换分身' }))
        .getByRole('button', { name: '关闭' })
        .click(),
    );
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: '切换分身' })).toBeNull(),
    );
    // Pages an administrator switched off leave the menu at once; chat always stays.
    act(() =>
      useAuth.setState({
        identity: {
          email: null,
          admin: true,
          auth_enabled: false,
          features: { work: false, ledger: false },
        },
      }),
    );
    expect(
      [
        ...screen
          .getByRole('navigation', { name: '主导航' })
          .querySelectorAll('a'),
      ].map((link) => link.textContent),
    ).toEqual(['聊天', '档案']);
  } finally {
    useAuth.setState({ identity: null });
    rendered.unmount();
    useStatus.setState({ data: previous.data, error: previous.error });
    vi.restoreAllMocks();
  }
});
