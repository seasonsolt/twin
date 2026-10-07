import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import { ConfirmProvider } from '../components/ui';
import { Twins } from '../pages/Twins';
import { CHAT_KEY } from '../features/chat/useConversation';
import { personaKey, setPersonaId } from '../lib/persona';
import { usePersonas, type Persona } from '../stores/personas';
import { useStatus } from '../stores/status';
import { useAuth } from '../stores/auth';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
const B = 'p-friend';
const NEW = 'p-new';
const account = {
  email: 'owner@example.test',
  admin: true,
  auth_enabled: true,
};
const json = (value: unknown) => new Response(JSON.stringify(value));
let items: Persona[];
let fetcher: ReturnType<typeof vi.fn>;
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  setPersonaId('default');
  items = [
    {
      id: 'default',
      name: '主人',
      sources: 2,
      avatar_url: null,
      created_at: 'now',
      is_default: true,
      owner: account.email,
    },
    {
      id: B,
      name: '朋友',
      sources: 3,
      avatar_url: '/api/media/avatar-image',
      created_at: 'now',
      is_default: false,
      owner: 'friend@example.test',
    },
  ];
  usePersonas.setState({ id: 'default', items });
  useAuth.setState({ identity: account });
  useStatus.setState({ data: null, error: null });
  window.location.hash = '#/twins';
  fetcher = vi.fn(async (path: string, init?: RequestInit) => {
    const selected = new Headers(init?.headers).get('X-Twin-Persona');
    const persona = items.find((item) => item.id === selected) ?? items[0];
    if (path === '/api/whoami') return json(account);
    if (path === '/api/personas') {
      if (init?.method === 'POST') {
        const created = {
          ...items[1],
          id: NEW,
          name: JSON.parse(init.body as string).name,
          sources: 0,
          avatar_url: null,
          owner: account.email,
        };
        items.push(created);
        return json(created);
      }
      return json(items);
    }
    if (path === '/api/identity')
      return json({
        name: persona.name,
        about: '',
        name_source: 'user',
        aliases: [],
        egress: [],
        onboarding_pending: persona.id === NEW,
      });
    if (path === '/api/status')
      return json({
        target_name: persona.name,
        counts: { sources: persona.sources, items: 0 },
        egress: [],
      });
    if (path === '/api/persona/sources')
      return json(
        Array.from({ length: selected === B ? 1 : 2 }, (_, index) => ({
          source_id: `s-${index}`,
          title: `录音 ${index}`,
          status: 'needs_speaker',
          detected_kind_label: '录音',
          remembered: 0,
          first_date: null,
        })),
      );
    if (path === '/api/persona/processing') return json({ state: 'idle' });
    if (path === '/api/media/capabilities')
      return json({ available: false, video: { available: false } });
    if (path === '/api/me/assets')
      return json({
        portrait: null,
        voice: null,
        speech_clone: false,
        video: false,
      });
    if (
      path.startsWith('/api/persona/items') ||
      path.startsWith('/api/conversations?') ||
      path === '/api/jobs'
    )
      return json([]);
    if (path === '/api/persona/coverage')
      return json({ facets: [], suggestions: [], kind_labels: {} });
    return json({ stale: false });
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => {
  setPersonaId('default');
  usePersonas.setState({ id: 'default', items: [] });
  useAuth.setState({ identity: null });
  useStatus.setState({ data: null, error: null });
});
function Destination() {
  const id = usePersonas((state) => state.id);
  return <p>聊天：{id}</p>;
}
function mountTwins() {
  return render(
    <ConfirmProvider>
      <MemoryRouter initialEntries={['/twins']}>
        <Routes>
          <Route path="twins" element={<Twins />} />
          <Route path="chat" element={<Destination />} />
        </Routes>
      </MemoryRouter>
    </ConfirmProvider>,
  );
}

it('lists twins with portraits, isolated last messages, confirmation counts, current marker, and admin owners', async () => {
  sessionStorage.setItem(
    CHAT_KEY,
    JSON.stringify([{ content: '主人的最后一句' }]),
  );
  sessionStorage.setItem(
    personaKey(CHAT_KEY, B),
    JSON.stringify([{ content: '朋友的最后一句' }]),
  );
  mountTwins();
  const owner = screen.getByRole('button', { name: '和主人聊天' });
  const friend = screen.getByRole('button', { name: '和朋友聊天' });
  expect(within(owner).getByText('2 条记忆')).toBeInTheDocument();
  expect(within(friend).getByText('3 条记忆')).toBeInTheDocument();
  expect(within(owner).getByText('主人的最后一句')).toBeInTheDocument();
  expect(within(friend).getByText('朋友的最后一句')).toBeInTheDocument();
  expect(within(owner).getByText('当前分身')).toBeInTheDocument();
  expect(within(friend).queryByText('当前分身')).not.toBeInTheDocument();
  expect(friend.querySelector('img')).toHaveAttribute(
    'src',
    `/api/media/avatar-image?persona=${B}`,
  );
  expect(within(friend).getByText('friend@example.test')).toBeInTheDocument();
  expect(within(owner).queryByText(account.email)).not.toBeInTheDocument();
  expect(await within(owner).findByText('有 2 段待确认')).toBeInTheDocument();
  expect(await within(friend).findByText('有 1 段待确认')).toBeInTheDocument();
  expect(
    fetcher.mock.calls
      .filter(([path]) => path === '/api/persona/sources')
      .every(([, init]) => new Headers(init.headers).has('X-Twin-Persona')),
  ).toBe(true);
});

it('selects a twin card and opens its chat', async () => {
  mountTwins();
  await userEvent
    .setup()
    .click(screen.getByRole('button', { name: '和朋友聊天' }));
  expect(await screen.findByText(`聊天：${B}`)).toBeVisible();
  expect(usePersonas.getState().id).toBe(B);
  expect(localStorage.getItem('twin:persona')).toBe(B);
});

it('creates from the new-twin card and opens the created twin', async () => {
  mountTwins();
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: '新建分身' }));
  await user.type(screen.getByRole('textbox', { name: '分身名字' }), '新伙伴');
  await user.click(screen.getByRole('button', { name: '创建并开始' }));
  expect(await screen.findByText(`聊天：${NEW}`)).toBeVisible();
  expect(usePersonas.getState().id).toBe(NEW);
  expect(
    JSON.parse(
      fetcher.mock.calls.find(
        ([path, init]) => path === '/api/personas' && init?.method === 'POST',
      )![1].body,
    ),
  ).toEqual({ name: '新伙伴' });
});

it.each([
  'chat',
  'profile',
  'profile?section=memories',
  'profile?section=assets',
])('switches from the rail while staying on %s', async (route) => {
  window.location.hash = `#/${route}`;
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: '切换分身' }));
  await user.click(
    await screen.findByRole('button', { name: /朋友.*3 条记忆/ }),
  );
  expect(usePersonas.getState().id).toBe(B);
  expect(window.location.hash).toBe(`#/${route}`);
  expect(
    await screen.findByRole('banner', { name: '朋友的舞台' }),
  ).toBeVisible();
  expect(screen.getAllByRole('button', { name: '切换分身' })).toHaveLength(1);
  expect(
    screen.getByRole('button', { name: '切换分身' }).querySelector('img'),
  ).toHaveAttribute('src', `/api/media/avatar-image?persona=${B}`);
});

it('keeps one rail portrait, offers all twins and creation in its popover, and shows the account', async () => {
  items.push(
    ...Array.from({ length: 6 }, (_, index) => ({
      ...items[1],
      id: `p-extra-${index}`,
      name: `分身${index}`,
    })),
  );
  window.location.hash = '#/chat';
  render(<App />);
  const switcher = await screen.findByRole('button', { name: '切换分身' });
  expect(screen.getAllByRole('button', { name: '切换分身' })).toHaveLength(1);
  const aside = switcher.closest('aside')!;
  expect(aside).toHaveClass('bg-canvas', 'text-primary', 'border-r');
  expect(aside).not.toHaveClass('bg-accent');
  expect(within(aside).queryByText(account.email)).not.toBeInTheDocument();
  const user = userEvent.setup();
  const accountButton = screen.getByRole('button', { name: '账户' });
  await user.click(accountButton);
  const popover = screen.getByRole('dialog', { name: '账户' });
  expect(within(popover).getByText(account.email)).toBeVisible();
  expect(
    within(popover).getByRole('button', { name: '退出登录' }),
  ).toBeVisible();
  await user.keyboard('{Escape}');
  await waitFor(() =>
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
  );
  expect(accountButton).toHaveFocus();
  await user.click(switcher);
  const twins = screen.getByRole('dialog', { name: '切换分身' });
  expect(within(twins).getAllByRole('button', { name: /条记忆/ })).toHaveLength(
    8,
  );
  expect(within(twins).getByRole('link', { name: '全部分身' })).toHaveAttribute(
    'href',
    '#/twins',
  );
  await user.click(within(twins).getByRole('link', { name: '＋ 新建分身' }));
  expect(
    await screen.findByRole('dialog', { name: '新建分身' }),
  ).toBeInTheDocument();
});

it('opens the quick sheet from the mobile top-left portrait and opens all twins from that sheet', async () => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: query === '(max-width: 767px)',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  window.location.hash = '#/chat';
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: '切换分身' }));
  const quick = await screen.findByRole('dialog', { name: '切换分身' });
  await user.click(
    within(quick).getByRole('button', { name: /朋友.*3 条记忆/ }),
  );
  await screen.findByRole('banner', { name: '朋友的舞台' });
  await waitFor(() =>
    expect(screen.queryByRole('dialog', { name: '切换分身' })).toBeNull(),
  );
  expect(window.location.hash).toBe('#/chat');
  expect(
    screen.getByRole('navigation', { name: '底部导航' }),
  ).toBeInTheDocument();
  expect(screen.getAllByRole('button', { name: '切换分身' })).toHaveLength(1);
  await user.click(screen.getByRole('button', { name: '切换分身' }));
  await user.click(screen.getByRole('link', { name: '全部分身' }));
  expect(
    await screen.findByRole('heading', { name: '我的分身' }),
  ).toBeVisible();
  expect(window.location.hash).toBe('#/twins');
});

it('lets the owner reach all twins even when the selected twin needs onboarding', async () => {
  items[0] = { ...items[0], id: NEW };
  setPersonaId(NEW);
  usePersonas.setState({ id: NEW, items });
  render(<App />);
  expect(
    await screen.findByRole('heading', { name: '我的分身' }),
  ).toBeVisible();
  expect(
    screen.queryByRole('heading', { name: '你是谁' }),
  ).not.toBeInTheDocument();
});

it('lets the owner publish a twin and lists other members’ public twins without management', async () => {
  items[1] = { ...items[1], public: true, can_manage: false };
  const original = fetcher.getMockImplementation() as (
    path: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === '/api/personas/default' && init?.method === 'PATCH') {
      items[0] = { ...items[0], ...JSON.parse(init.body as string) };
      return json(items[0]);
    }
    return original(path, init);
  });
  mountTwins();
  const mine = screen.getByLabelText('分身列表');
  const shared = screen.getByLabelText('公开分身列表');
  const friend = within(shared).getByRole('button', { name: '和朋友聊天' });
  expect(friend.closest('article')?.querySelector('details')).toBeNull();
  expect(within(friend).queryByText('公开')).not.toBeInTheDocument();
  await waitFor(() =>
    expect(
      fetcher.mock.calls
        .filter(([path]) => path === '/api/persona/sources')
        .map(([, init]) => new Headers(init.headers).get('X-Twin-Persona')),
    ).toEqual(['default']),
  );
  const user = userEvent.setup();
  await user.click(within(mine).getByLabelText('管理主人'));
  await user.click(within(mine).getByRole('button', { name: '设为公开' }));
  expect(await within(mine).findByText('公开')).toBeInTheDocument();
  await user.click(within(mine).getByLabelText('管理主人'));
  expect(
    within(mine).getByRole('button', { name: '设为私有' }),
  ).toBeInTheDocument();
});
