import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import { CHAT_KEY } from '../features/chat/useConversation';
import { personaKey, setPersonaId } from '../lib/persona';
import { useAuth } from '../stores/auth';
import { usePersonas, type Persona } from '../stores/personas';
import { useStatus } from '../stores/status';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
let items: Persona[];
let fetcher: ReturnType<typeof vi.fn>;
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  items = [
    {
      id: 'default',
      name: '本人',
      is_default: true,
      sources: 1,
      avatar_url: null,
      created_at: '',
    },
    {
      id: 'friend',
      name: '朋友',
      is_default: false,
      sources: 1,
      avatar_url: null,
      created_at: '',
    },
  ];
  setPersonaId('friend');
  usePersonas.setState({ id: 'friend', items, pendingId: null });
  useAuth.setState({ identity: null });
  useStatus.setState({ data: null, error: null });
  window.location.hash = '#/profile';
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  fetcher = vi.fn(async (path: string, init?: RequestInit) => {
    const id = new Headers(init?.headers).get('X-Twin-Persona');
    const persona = items.find((item) => item.id === id) ?? items[0];
    if (path === '/api/whoami')
      return json({ email: null, admin: true, auth_enabled: false });
    if (path === '/api/personas') return json(items);
    if (path === '/api/personas/friend' && init?.method === 'DELETE') {
      items = items.filter((item) => item.id !== 'friend');
      return json({ deleted: true });
    }
    if (path === '/api/identity')
      return json({
        name: persona.name,
        about: '喜欢徒步',
        name_source: 'user',
        aliases: [],
        egress: [],
      });
    if (path === '/api/status')
      return json({
        target_name: persona.name,
        counts: { sources: 1, items: 1 },
        egress: [],
      });
    if (path === '/api/media/capabilities') return json({ available: false });
    if (path === '/api/channels') return json({ wecom: null });
    if (path === '/api/me/assets')
      return json({
        portrait: null,
        voice: null,
        speech_clone: false,
        video: false,
      });
    if (path === '/api/persona/sources')
      return json([
        {
          source_id: 'audio',
          title: '访谈录音',
          status: 'needs_speaker',
          kind: 'audio',
          remembered: 0,
          detected_kind_label: '录音',
          first_date: null,
        },
      ]);
    if (path === '/api/persona/processing') return json({ state: 'idle' });
    if (path.startsWith('/api/persona/items')) return json([]);
    if (path === '/api/persona/coverage')
      return json({ facets: [], suggestions: [], kind_labels: {} });
    return json({});
  });
  vi.stubGlobal('fetch', fetcher);
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: vi.fn(),
  });
});
afterEach(() => {
  setPersonaId('default');
  usePersonas.setState({ id: 'default', items: [], pendingId: null });
  useAuth.setState({ identity: null });
  useStatus.setState({ data: null, error: null });
  Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView');
});

it('renders only overview by default, keeps the header, and supports section links and identity editing', async () => {
  const view = render(<App />);
  await screen.findByRole('heading', { name: '我了解到的他' });
  const panel = screen.getByRole('tabpanel', { name: '概览' });
  expect(panel).toHaveTextContent('删除这个分身');
  const nav = screen.getByRole('tablist', { name: '档案章节' });
  expect(
    within(nav)
      .getAllByRole('tab')
      .map((tab) => tab.textContent),
  ).toEqual(['概览', '记忆', '形象和声音', '接入']);
  expect(within(nav).getByRole('tab', { name: '概览' })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  expect(screen.queryByText('企业微信')).toBeNull();
  expect(screen.queryByText('预置音色')).toBeNull();
  expect(screen.queryByRole('article')).toBeNull();
  const header = view.container.querySelector('.stage-header');
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole('link', { name: '有 1 段录音需要确认哪位是你' }),
  );
  await screen.findByRole('article');
  expect(screen.getByRole('tabpanel', { name: '记忆' })).toHaveTextContent(
    '访谈录音',
  );
  expect(screen.queryByRole('heading', { name: '我了解到的他' })).toBeNull();
  expect(screen.queryByRole('button', { name: '删除这个分身' })).toBeNull();
  expect(view.container.querySelector('.stage-header')).toBe(header);
  expect(screen.queryByRole('textbox', { name: '名字' })).toBeNull();
  await userEvent.setup().click(screen.getByRole('button', { name: '编辑' }));
  expect(
    await screen.findByRole('dialog', { name: '名字与介绍' }),
  ).toBeVisible();
  expect(screen.getByRole('textbox', { name: '名字' })).toHaveValue('朋友');
});

it.each(['overview', 'memories', 'assets', 'channels'])(
  'keeps the mobile profile and %s section mounted when switching twins',
  async (section) => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn((query: string) => ({
        matches: query === '(max-width: 767px)',
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    );
    window.location.hash = `#/profile?section=${section}`;
    const view = render(<App />);
    const switcher = await screen.findByRole('button', { name: '切换分身' });
    expect(switcher.closest('.stage-actions')).not.toBeNull();
    expect(
      view.container.querySelectorAll('button[aria-label="切换分身"]'),
    ).toHaveLength(1);
    const page = view.container.querySelector('.profile-page');
    const panel = view.container.querySelector(`#profile-${section}`);
    const user = userEvent.setup();
    await user.click(switcher);
    await user.click(
      await screen.findByRole('button', { name: /本人.*1 条记忆/ }),
    );
    await waitFor(() => expect(usePersonas.getState().id).toBe('default'));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(window.location.hash).toBe(`#/profile?section=${section}`);
    expect(view.container.querySelector('.profile-page')).toBe(page);
    expect(view.container.querySelector(`#profile-${section}`)).toBe(panel);
    expect(view.container.querySelectorAll('.profile-section')).toHaveLength(1);
    expect(
      view.container.querySelectorAll('button[aria-label="切换分身"]'),
    ).toHaveLength(1);
    expect(
      within(screen.getByRole('navigation', { name: '底部导航' })).getAllByRole(
        'link',
      ),
    ).toHaveLength(2);
  },
);

it('switches panels with pointer and arrow keys, resets scroll, and never scroll-spies', async () => {
  const view = render(<App />);
  const nav = await screen.findByRole('tablist', { name: '档案章节' });
  const user = userEvent.setup();
  await user.click(within(nav).getByRole('tab', { name: '形象和声音' }));
  expect(window.location.hash).toBe('#/profile?section=assets');
  expect(
    screen.getByRole('tabpanel', { name: '形象和声音' }),
  ).toHaveTextContent('预置音色');
  expect(window.scrollTo).toHaveBeenLastCalledWith({ top: 0 });
  within(nav).getByRole('tab', { name: '形象和声音' }).focus();
  await user.keyboard('{ArrowRight}');
  expect(window.location.hash).toBe('#/profile?section=channels');
  expect(
    await screen.findByRole('tabpanel', { name: '接入' }),
  ).toHaveTextContent('企业微信');
  expect(view.container.querySelectorAll('.profile-section')).toHaveLength(1);
  act(() => fireEvent.scroll(window));
  expect(window.location.hash).toBe('#/profile?section=channels');
  expect(HTMLElement.prototype.scrollIntoView).not.toHaveBeenCalled();
});

it.each([
  ['overview', '概览'],
  ['memories', '记忆'],
  ['assets', '形象和声音'],
  ['channels', '接入'],
  ['unknown', '概览'],
])(
  'opens only the selected panel from the %s deep link',
  async (section, title) => {
    window.location.hash = `#/profile?section=${section}`;
    const view = render(<App />);
    const panel = await screen.findByRole('tabpanel', { name: title });
    const nav = screen.getByRole('tablist', { name: '档案章节' });
    const tab = within(nav).getByRole('tab', { name: title });
    expect(tab).toHaveAttribute('aria-selected', 'true');
    expect(tab).toHaveAttribute('aria-controls', panel.id);
    expect(panel).toHaveAttribute('aria-labelledby', tab.id);
    expect(view.container.querySelectorAll('.profile-section')).toHaveLength(1);
    if (section === 'channels') {
      expect(within(panel).getByRole('button', { name: '绑定' })).toBeVisible();
      expect(
        within(panel).getByRole('heading', { name: '接入', level: 2 }),
      ).toBeVisible();
    }
  },
);

it('mounts polling components only in their selected panel and aborts them when leaving', async () => {
  render(<App />);
  await screen.findByRole('heading', { name: '我了解到的他' });
  expect(
    fetcher.mock.calls.some(
      ([path]) =>
        path === '/api/channels' || path === '/api/persona/processing',
    ),
  ).toBe(false);
  const nav = screen.getByRole('tablist', { name: '档案章节' });
  const user = userEvent.setup();
  await user.click(within(nav).getByRole('tab', { name: '接入' }));
  await waitFor(() =>
    expect(fetcher.mock.calls.some(([path]) => path === '/api/channels')).toBe(
      true,
    ),
  );
  const channelRequest = fetcher.mock.calls.find(
    ([path]) => path === '/api/channels',
  )![1]!;
  await user.click(within(nav).getByRole('tab', { name: '记忆' }));
  expect(channelRequest.signal?.aborted).toBe(true);
  await screen.findByRole('article');
  const memoryRequest = fetcher.mock.calls.find(
    ([path]) => path === '/api/persona/processing',
  )![1]!;
  await user.click(within(nav).getByRole('tab', { name: '概览' }));
  expect(memoryRequest.signal?.aborted).toBe(true);
  expect(screen.queryByRole('article')).toBeNull();
});

it('protects the default twin and confirms deletion before clearing only the deleted twin and returning to all twins', async () => {
  sessionStorage.setItem(personaKey(CHAT_KEY, 'friend'), 'private');
  sessionStorage.setItem(CHAT_KEY, 'default history');
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: '删除这个分身' }));
  let dialog = screen.getByRole('dialog', { name: '删除「朋友」？' });
  await user.click(within(dialog).getByRole('button', { name: '取消' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(fetcher.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(
    false,
  );
  await user.click(screen.getByRole('button', { name: '删除这个分身' }));
  dialog = screen.getByRole('dialog', { name: '删除「朋友」？' });
  expect(dialog).toHaveTextContent('删除后 7 天内可以在「最近删除」里恢复');
  await user.click(within(dialog).getByRole('button', { name: '删除分身' }));
  await waitFor(() => expect(window.location.hash).toBe('#/twins'));
  expect(usePersonas.getState().id).toBe('default');
  expect(sessionStorage.getItem(personaKey(CHAT_KEY, 'friend'))).toBeNull();
  expect(sessionStorage.getItem(CHAT_KEY)).toBe('default history');
  await screen.findByRole('heading', { name: '我的分身' });
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  await user.click(await screen.findByRole('link', { name: '档案' }));
  await screen.findByText('默认分身不能删除');
  await waitFor(() =>
    expect(screen.getByText('默认分身不能删除')).toBeVisible(),
  );
  expect(screen.queryByRole('button', { name: '删除这个分身' })).toBeNull();
});

it('keeps the profile and reports a blocked deletion without clearing local data', async () => {
  sessionStorage.setItem(personaKey(CHAT_KEY, 'friend'), 'private');
  const original = fetcher.getMockImplementation()! as (
    path: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation((path: string, init?: RequestInit) =>
    path === '/api/personas/friend'
      ? Promise.resolve(json({ detail: '这个分身还有任务在运行' }, 409))
      : original(path, init),
  );
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: '删除这个分身' }));
  await user.click(screen.getByRole('button', { name: '删除分身' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '这个分身还有任务在运行',
  );
  expect(window.location.hash).toBe('#/profile');
  expect(sessionStorage.getItem(personaKey(CHAT_KEY, 'friend'))).toBe(
    'private',
  );
});
