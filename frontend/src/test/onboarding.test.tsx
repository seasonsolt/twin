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
import {
  isItemSummaryUrl,
  isSourcesUrl,
  itemSummary,
  itemsPage,
  sourcesPage,
} from './personaApi';

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
let sources: object[];
let fetcher: ReturnType<typeof vi.fn>;
const json = (value: unknown) => new Response(JSON.stringify(value));
beforeEach(() => {
  vi.mocked(useReducedMotion).mockReturnValue(true);
  window.location.hash = '#/chat';
  sessionStorage.clear();
  processing = 'idle';
  sources = [];
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
    if (isSourcesUrl(url))
      return Promise.resolve(json(sourcesPage(url, sources)));
    if (isItemSummaryUrl(url)) return Promise.resolve(json(itemSummary([])));
    if (url.startsWith('/api/persona/items'))
      return Promise.resolve(json(itemsPage(url, [])));
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
    if (url === '/api/persona/notes') {
      sources = [
        {
          source_id: 'note',
          title: '笔记',
          status: 'processing',
          detected_kind_label: '笔记',
          remembered: 0,
          first_date: null,
        },
      ];
      return Promise.resolve(json({ new: true }));
    }
    throw new Error(url);
  });
  vi.stubGlobal('fetch', fetcher);
});

it.each([true, false])(
  'opens a twin without memory on its chat, rail and all, with the setup card instead of a full-page flow (reduced motion: %s)',
  async (reduced) => {
    vi.mocked(useReducedMotion).mockReturnValue(reduced);
    render(<App />);
    // The whole app mounts first; give a loaded machine time.
    const card = await screen.findByRole(
      'region',
      { name: '让本人认识你' },
      { timeout: 5000 },
    );
    expect(
      screen.getByRole('navigation', { name: '主导航' }),
    ).toBeInTheDocument();
    expect(
      within(card).getByRole('region', { name: '添加会议录音' }),
    ).toBeVisible();
    expect(screen.queryByRole('heading', { name: '你是谁' })).toBeNull();
    expect(screen.queryByRole('button', { name: '跳过' })).toBeNull();
    // Writing a few lines stands in for a recording; the card follows it into 整理记忆.
    fireEvent.click(
      within(card).getByRole('button', { name: '没有录音？写一段或上传文档' }),
    );
    fireEvent.change(
      within(card).getByRole('textbox', { name: '写一段关于你的事' }),
      { target: { value: '今天去散步了' } },
    );
    processing = 'queued';
    fireEvent.click(within(card).getByRole('button', { name: '保存' }));
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(([url]) => url === '/api/persona/notes'),
      ).toBe(true),
    );
    expect(
      await within(card).findByText(
        '正在从你说的话里整理，好了会在这里告诉你。',
      ),
    ).toBeVisible();
  },
);
it.each(['user', 'memories'])(
  'shows no setup card when %s is already present; navigation has the team, chat, library, tasks and promises',
  async (present) => {
    if (present === 'user') identity.name_source = 'user';
    else status.counts.sources = 1;
    render(<App />);
    const nav = await screen.findByRole('navigation', { name: '主导航' });
    expect(
      within(nav)
        .getAllByRole('link')
        .map((link) => link.textContent),
    ).toEqual(['团队', '对话', '录音库', '待处理', '承诺']);
    expect(screen.queryByText('让我们认识一下')).not.toBeInTheDocument();
    if (present === 'memories')
      expect(screen.queryByRole('region', { name: /认识你$/ })).toBeNull();
  },
);
it.each(['persona', 'identity'])(
  'redirects legacy %s to Profile',
  async (route) => {
    identity.name_source = 'user';
    window.location.hash = `#/${route}`;
    render(<App />);
    await screen.findByRole('heading', { name: '人格' });
    expect(window.location.hash).toBe('#/profile');
  },
);
