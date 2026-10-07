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
  window.location.hash = '#/profile?section=memories';
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

it('renders overview, memories, assets, speaker confirmation, and identity editing in one profile', async () => {
  render(<App />);
  await screen.findByRole('heading', { name: '我了解到的他' });
  expect(screen.getByRole('article')).toHaveTextContent('访谈录音');
  expect(screen.getByRole('region', { name: '概览' })).toHaveTextContent(
    '有 1 段录音需要确认哪位是你',
  );
  expect(screen.getByRole('region', { name: '形象和声音' })).toHaveTextContent(
    '预置音色',
  );
  const nav = screen.getByRole('navigation', { name: '档案章节' });
  expect(within(nav).getAllByRole('link')).toHaveLength(3);
  expect(within(nav).getByRole('link', { name: '记忆' })).toHaveAttribute(
    'aria-current',
    'location',
  );
  expect(screen.queryByRole('textbox', { name: '名字' })).toBeNull();
  await userEvent.setup().click(screen.getByRole('button', { name: '编辑' }));
  expect(
    await screen.findByRole('dialog', { name: '名字与介绍' }),
  ).toBeVisible();
  expect(screen.getByRole('textbox', { name: '名字' })).toHaveValue('朋友');
});

it.each(['overview', 'memories', 'assets'])(
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
    const memorySection = view.container.querySelector('#profile-memories');
    const user = userEvent.setup();
    await user.click(switcher);
    await user.click(
      await screen.findByRole('button', { name: /本人.*1 条记忆/ }),
    );
    await waitFor(() => expect(usePersonas.getState().id).toBe('default'));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(window.location.hash).toBe(`#/profile?section=${section}`);
    expect(view.container.querySelector('.profile-page')).toBe(page);
    expect(view.container.querySelector('#profile-memories')).toBe(
      memorySection,
    );
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

it('updates the active anchor and deep link on scroll without remounting content', async () => {
  const view = render(<App />);
  const nav = await screen.findByRole('navigation', { name: '档案章节' });
  const bounds = (top: number) => ({
    top,
    bottom: top + 64,
    left: 0,
    right: 400,
    width: 400,
    height: 64,
    x: 0,
    y: top,
    toJSON: () => ({}),
  });
  vi.spyOn(nav, 'getBoundingClientRect').mockReturnValue(bounds(0));
  vi.spyOn(
    view.container.querySelector('#profile-overview')!,
    'getBoundingClientRect',
  ).mockReturnValue(bounds(-800));
  vi.spyOn(
    view.container.querySelector('#profile-memories')!,
    'getBoundingClientRect',
  ).mockReturnValue(bounds(-400));
  vi.spyOn(
    view.container.querySelector('#profile-assets')!,
    'getBoundingClientRect',
  ).mockReturnValue(bounds(70));
  act(() => fireEvent.scroll(window));
  await waitFor(() =>
    expect(window.location.hash).toBe('#/profile?section=assets'),
  );
  expect(within(nav).getByRole('link', { name: '形象和声音' })).toHaveAttribute(
    'aria-current',
    'location',
  );
  await userEvent
    .setup()
    .click(within(nav).getByRole('link', { name: '记忆' }));
  expect(window.location.hash).toBe('#/profile?section=memories');
  expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalled();
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
  expect(window.location.hash).toBe('#/profile?section=memories');
  expect(sessionStorage.getItem(personaKey(CHAT_KEY, 'friend'))).toBe(
    'private',
  );
});
