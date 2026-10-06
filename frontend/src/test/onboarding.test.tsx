import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { useReducedMotion } from 'motion/react';
import { App } from '../App';
import { useStatus, type Status } from '../stores/status';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: vi.fn(),
}));
let identity: {
  name: string;
  about: string;
  name_source: 'config' | 'user';
  aliases: string[];
  voice: null;
  avatar: null;
};
let status: Status;
let processing: 'idle' | 'queued';
let fetcher: ReturnType<typeof vi.fn>;
const json = (value: unknown) => new Response(JSON.stringify(value));
beforeEach(() => {
  vi.mocked(useReducedMotion).mockReturnValue(true);
  window.location.hash = '#/chat';
  sessionStorage.clear();
  processing = 'idle';
  useStatus.setState({ data: null, error: null });
  identity = {
    name: '本人',
    about: '',
    name_source: 'config',
    aliases: [],
    voice: null,
    avatar: null,
  };
  status = {
    target_name: identity.name,
    counts: { sources: 0, items: 0 },
    llm: { provider: 'mock', model: 'mock' },
    embed: { provider: 'local' },
    egress: [],
  };
  fetcher = vi.fn((url: string, init: RequestInit) => {
    if (url === '/api/whoami')
      return Promise.resolve(
        json({ email: null, admin: true, auth_enabled: false }),
      );
    if (url === '/api/personas')
      return Promise.resolve(
        json([{ id: 'default', name: identity.name, is_default: true }]),
      );
    if (url === '/api/identity') {
      if (init.method === 'PUT') {
        identity = {
          ...identity,
          ...JSON.parse(init.body as string),
          name_source: 'user',
        };
        status.target_name = identity.name;
        if (identity.about) processing = 'queued';
      }
      return Promise.resolve(json(identity));
    }
    if (url === '/api/status') return Promise.resolve(json(status));
    if (url === '/api/persona/state')
      return Promise.resolve(json({ stale: false }));
    if (url === '/api/persona/sources' || url.startsWith('/api/persona/items'))
      return Promise.resolve(json([]));
    if (url === '/api/persona/processing')
      return Promise.resolve(json({ state: processing }));
    if (url === '/api/persona/coverage')
      return Promise.resolve(
        json({ facets: [], suggestions: [], kind_labels: {} }),
      );
    if (url === '/api/me/assets')
      return Promise.resolve(
        json({
          portrait: null,
          voice: null,
          speech_clone: false,
          video: false,
        }),
      );
    if (url === '/api/media/capabilities')
      return Promise.resolve(json({ available: false }));
    if (url === '/api/persona/notes')
      return Promise.resolve(json({ new: true }));
    throw new Error(url);
  });
  vi.stubGlobal('fetch', fetcher);
});

it.each([true, false])(
  'shows a padded four-step flow with one Chinese final action (reduced motion: %s), then never shows again',
  async (reduced) => {
    vi.mocked(useReducedMotion).mockReturnValue(reduced);
    const view = render(<App />);
    const heading = await screen.findByRole('heading', { name: '你是谁' });
    expect(heading.closest('.effects-stepper-body')).toHaveClass(
      'p-5',
      'sm:p-6',
    );
    expect(
      screen.queryByRole('navigation', { name: '主导航' }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '继续' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('名字'), {
      target: { value: '小林' },
    });
    fireEvent.change(screen.getByLabelText('介绍一下自己'), {
      target: { value: '喜欢徒步' },
    });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await screen.findByText('已保存，可以继续添加记忆。');
    fireEvent.click(screen.getByRole('button', { name: '继续' }));
    await screen.findByRole('heading', { name: '形象和声音' });
    expect(await screen.findByRole('button', { name: '换一张' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '录一段' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: '继续' }));
    await screen.findByRole('heading', { name: '添加记忆' });
    expect(await screen.findAllByText('等待记住…')).toHaveLength(1);
    expect(screen.getAllByRole('tab')).toHaveLength(3);
    const memoryInput = screen.getByLabelText('要记住的文字');
    fireEvent.change(memoryInput, {
      target: { value: '今天去散步了' },
    });
    fireEvent.click(
      within(memoryInput.closest('form')!).getByRole('button', {
        name: '保存',
      }),
    );
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(([url]) => url === '/api/persona/notes'),
      ).toBe(true),
    );
    fireEvent.click(screen.getByRole('button', { name: '继续' }));
    const start = await screen.findByRole('button', { name: '开始聊天' });
    expect(screen.getAllByRole('button', { name: '开始聊天' })).toHaveLength(1);
    expect(
      screen.queryByRole('button', { name: /Complete|Continue|Back|完成/ }),
    ).not.toBeInTheDocument();
    expect(start.textContent).toBe('开始聊天');
    fireEvent.click(start);
    await screen.findByRole('heading', { name: '小林' });
    view.unmount();
    render(<App />);
    await screen.findByRole('heading', { name: '小林' });
    expect(screen.queryByText('让我们认识一下')).not.toBeInTheDocument();
  },
);
it('skips persistently without adding a self-introduction', async () => {
  const view = render(<App />);
  await screen.findByRole('heading', { name: '你是谁' });
  fireEvent.click(screen.getByRole('button', { name: '跳过' }));
  await screen.findByRole('navigation', { name: '主导航' });
  expect(identity.name_source).toBe('user');
  expect(identity.about).toBe('');
  view.unmount();
  render(<App />);
  await screen.findByRole('navigation', { name: '主导航' });
  expect(screen.queryByText('让我们认识一下')).not.toBeInTheDocument();
});
it.each(['user', 'memories'])(
  'does not onboard when %s is already present; navigation has exactly three items',
  async (present) => {
    if (present === 'user') identity.name_source = 'user';
    else status.counts.sources = 1;
    render(<App />);
    const nav = await screen.findByRole('navigation', { name: '主导航' });
    expect(
      within(nav)
        .getAllByRole('link')
        .map((link) => link.textContent),
    ).toEqual(['聊天', '记忆', '关于你']);
    expect(screen.queryByText('让我们认识一下')).not.toBeInTheDocument();
  },
);
it.each(['persona', 'identity'])(
  'redirects legacy %s to About',
  async (route) => {
    identity.name_source = 'user';
    window.location.hash = `#/${route}`;
    render(<App />);
    await screen.findByRole('heading', { name: '关于你' });
    expect(window.location.hash).toBe('#/about');
  },
);
