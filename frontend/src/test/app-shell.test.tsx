import { act, render, screen, within, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { expect, it, vi } from 'vitest';
import { AppShell } from '../components/layout/AppShell';
import { ConfirmProvider, TooltipProvider } from '../components/ui';
import { Member } from '../pages/Member';
import { memberTwin, showTwins } from './member';
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
                    ? [memberTwin()]
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
  showTwins();
  const rendered = render(
    <TooltipProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={['/team/twin/default']}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="team/twin/:twinId" element={<Member />} />
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
      header.queryByText(/mock-model|example.test|remote-provider|外部 ·/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText('大模型：example.test')).toBeNull();
    await act(async () =>
      screen.getByLabelText('身份测试人的更多操作').click(),
    );
    await act(async () =>
      screen.getByRole('button', { name: '外部服务' }).click(),
    );
    const settings = await screen.findByRole('dialog', { name: '分身设置' });
    // The dialog fades in from opacity 0, even with reduced motion.
    await waitFor(() => expect(settings).toBeVisible());
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
    expect(screen.getByRole('tab', { name: '档案' })).toBeInTheDocument();
    expect(
      screen.getByRole('navigation', { name: '主导航' }).querySelectorAll('a'),
    ).toHaveLength(5);
    for (const label of ['团队', '对话', '录音库', '待处理', '承诺']) {
      // The wide side bar: icon on the left, the words beside it, named by those words.
      const link = within(
        screen.getByRole('navigation', { name: '主导航' }),
      ).getByRole('link', { name: new RegExp(`^${label}`, 'u') });
      expect(link).toHaveClass('w-full', 'rounded-md');
      expect(within(link).getByText(label)).toBeVisible();
      expect(within(link).getByText(label)).not.toHaveClass('sr-only');
    }
    // The profile belongs to a twin, not to the team: no place in the side bar is current.
    expect(screen.getByRole('link', { name: '对话' })).not.toHaveAttribute(
      'aria-current',
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
      // The team's page counts its members (the twin whose page this is), the others nothing yet.
    ).toEqual(['团队1', '对话', '录音库', '待处理']);
  } finally {
    useAuth.setState({ identity: null });
    rendered.unmount();
    useStatus.setState({ data: previous.data, error: previous.error });
    vi.restoreAllMocks();
  }
});
