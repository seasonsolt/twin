import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { expect, it, vi } from 'vitest';
import { AppShell } from '../components/layout/AppShell';
import { TooltipProvider } from '../components/ui';
import { Placeholder } from '../pages/Placeholder';
import { useStatus, type Status } from '../stores/status';

it('loads labels in a background tab, shows only external hosts, and names identity consistently', async () => {
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
    labels: {
      explicit: 'API 标识',
      disclaimer: 'API 页脚',
      chat_notice: 'API 聊天说明',
    },
  };
  const previous = useStatus.getState();
  useStatus.setState({ data: null, error: null });
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response(JSON.stringify(status))),
  );
  const rendered = render(
    <TooltipProvider>
      <MemoryRouter initialEntries={['/identity']}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="identity" element={<Placeholder route="identity" />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </TooltipProvider>,
  );
  try {
    expect(await screen.findByText('API 标识')).toBeVisible();
    expect(screen.getByText('API 页脚')).toBeVisible();
    expect(screen.getByText('测试人')).toBeVisible();
    const chip = screen.getByText('外部 · example.test');
    expect(chip).toHaveClass('text-info');
    expect(chip).toHaveAttribute(
      'title',
      'llm · remote-provider · example.test',
    );
    expect(
      screen.queryByText(/localhost|local-provider/),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '身份' })).toHaveAttribute(
      'href',
      '/identity',
    );
    expect(screen.getByRole('heading', { name: '身份' })).toBeInTheDocument();
  } finally {
    rendered.unmount();
    useStatus.setState({ data: previous.data, error: previous.error });
    vi.restoreAllMocks();
  }
});
