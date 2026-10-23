import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import { setPersonaId } from '../lib/persona';
import { usePersonas, type Persona } from '../stores/personas';
import { useStatus } from '../stores/status';
import { useAuth } from '../stores/auth';
import { isSourcesUrl, sourcesPage } from './personaApi';

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
  window.location.hash = '#/team';
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
    if (isSourcesUrl(path))
      return json(
        sourcesPage(
          path,
          Array.from({ length: selected === B ? 1 : 2 }, (_, index) => ({
            source_id: `s-${index}`,
            title: `录音 ${index}`,
            status: 'needs_speaker',
            detected_kind_label: '录音',
            remembered: 0,
            first_date: null,
          })),
        ),
      );
    if (path === '/api/persona/processing') return json({ state: 'idle' });
    if (/^\/api\/persona\/sources\/[^/]+\/speakers$/.test(path))
      return json({
        diarized: true,
        speakers: [{ id: 'S1', seconds: 600, suggested: false, samples: [] }],
      });
    if (path === '/api/media/capabilities')
      return json({ available: false, video: { available: false } });
    if (path === '/api/me/assets')
      return json({
        portrait: null,
        voice: null,
        speech_clone: false,
        video: false,
      });
    if (path === '/api/persona/items/summary')
      return json({ total: 0, conflicts: 0, dimensions: [] });
    if (path.startsWith('/api/persona/items'))
      return json({ items: [], total: 0 });
    if (path.startsWith('/api/conversations?') || path === '/api/jobs')
      return json([]);
    if (path === '/api/persona/coverage')
      return json({ facets: [], suggestions: [], kind_labels: {} });
    // A team with a recording, so the team page is the table and not the first-run page.
    if (path === '/api/library')
      return json({
        recordings: [
          {
            id: 'r-1',
            filename: '周会.m4a',
            status: 'ready',
            people: [],
            unsettled: 0,
          },
        ],
        pending: 0,
        asr: true,
      });
    if (path === '/api/library/people') return json({ items: [] });
    if (path === '/api/library/review')
      return json({ items: [], voices: [], fragments: [], unsorted: [] });
    if (path === '/api/personas/trash') return json([]);
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
it('switches twins while staying on the chat', async () => {
  window.location.hash = '#/chat';
  render(<App />);
  const user = userEvent.setup();
  // On chat the twin's portrait in the header opens the switcher.
  await user.click(await screen.findByRole('button', { name: /^切换分身/ }));
  await user.click(
    within(screen.getByRole('dialog', { name: '切换分身' })).getByRole(
      'button',
      { name: /^朋友/ },
    ),
  );
  expect(usePersonas.getState().id).toBe(B);
  expect(window.location.hash).toBe('#/chat');
  expect(
    await screen.findByRole('banner', { name: '朋友的聊天' }),
  ).toBeVisible();
  expect(
    screen.getByRole('heading', { level: 1, name: '新对话' }),
  ).toBeVisible();
  expect(
    screen.getByRole('button', { name: /^切换分身/ }).querySelector('img'),
  ).toHaveAttribute('src', `/api/media/avatar-image?persona=${B}`);
});

it('makes a twin from the team page and opens its chat', async () => {
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByText('添加'));
  await user.click(screen.getByRole('button', { name: '新建分身' }));
  await user.type(
    await screen.findByRole('textbox', { name: '分身名字' }),
    '新伙伴',
  );
  await user.click(screen.getByRole('button', { name: '创建并开始' }));
  await waitFor(() => expect(window.location.hash).toBe('#/chat'));
  await waitFor(() => expect(usePersonas.getState().id).toBe(NEW));
  expect(usePersonas.getState().items.map((persona) => persona.id)).toEqual([
    'default',
    B,
    NEW,
  ]);
  expect(
    JSON.parse(
      fetcher.mock.calls.find(
        ([path, init]) => path === '/api/personas' && init?.method === 'POST',
      )![1].body,
    ),
  ).toEqual({ name: '新伙伴' });
});

it('keeps the side bar about the team, and switches among many twins from the chat header', async () => {
  items.push(
    ...Array.from({ length: 6 }, (_, index) => ({
      ...items[1],
      id: `p-extra-${index}`,
      name: `分身${index}`,
    })),
  );
  window.location.hash = '#/chat';
  render(<App />);
  const nav = await screen.findByRole('navigation', { name: '主导航' });
  const aside = nav.closest('aside')!;
  expect(aside).toHaveClass('nav-sidebar');
  expect(aside).not.toHaveClass('border-r');
  // No twin is picked in the side bar: the twins are reached through the team, find (⌘K) and the chat header.
  expect(aside.querySelectorAll('.persona-portrait')).toHaveLength(0);
  expect(
    within(aside).queryByRole('button', { name: /^切换/u }),
  ).not.toBeInTheDocument();
  expect(within(aside).getByRole('button', { name: '找人' })).toBeVisible();
  expect(
    within(aside).getByRole('button', { name: '上传会议录音' }),
  ).toBeVisible();
  expect(within(aside).getByRole('button', { name: '账户' })).toHaveTextContent(
    account.email,
  );
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
  await user.click(screen.getByRole('button', { name: /^切换分身/ }));
  const twins = screen.getByRole('dialog', { name: '切换分身' });
  expect(within(twins).getAllByRole('button', { name: /条记忆/ })).toHaveLength(
    8,
  );
  await user.type(within(twins).getByLabelText('搜索分身'), '分身5');
  expect(within(twins).getAllByRole('button', { name: /条记忆/ })).toHaveLength(
    1,
  );
  await user.clear(within(twins).getByLabelText('搜索分身'));
  // The twin's own pages, which left the side bar, are a click away here.
  expect(within(twins).getByRole('link', { name: '档案' })).toHaveAttribute(
    'href',
    '#/profile',
  );
  expect(within(twins).getByRole('link', { name: '全部分身' })).toHaveAttribute(
    'href',
    '#/team',
  );
  await user.click(within(twins).getByRole('button', { name: '＋ 新建分身' }));
  expect(
    await screen.findByRole('form', { name: '新建分身' }),
  ).toBeInTheDocument();
});

it('opens the quick sheet from the mobile top-left portrait and opens all twins from that sheet', async () => {
  items.push(
    ...Array.from({ length: 6 }, (_, index) => ({
      ...items[1],
      id: `p-mobile-${index}`,
      name: `手机分身${index}`,
    })),
  );
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
  await user.click(await screen.findByRole('button', { name: /^切换分身/ }));
  const quick = await screen.findByRole('dialog', { name: '切换分身' });
  await waitFor(() =>
    expect(
      within(quick).getByRole('searchbox', { name: '搜索分身' }),
    ).toBeVisible(),
  );
  expect(
    within(quick).getAllByRole('button', { name: /条记忆/u }),
  ).toHaveLength(items.length);
  await user.click(
    within(quick).getByRole('button', { name: /朋友.*3 条记忆/ }),
  );
  await screen.findByRole('heading', { name: '朋友' });
  await waitFor(() =>
    expect(screen.queryByRole('dialog', { name: '切换分身' })).toBeNull(),
  );
  expect(window.location.hash).toBe('#/chat');
  expect(
    screen.getByRole('navigation', { name: '底部导航' }),
  ).toBeInTheDocument();
  expect(screen.getAllByRole('button', { name: /^切换分身/ })).toHaveLength(1);
  await user.click(screen.getByRole('button', { name: /^切换分身/ }));
  await user.click(screen.getByRole('link', { name: '全部分身' }));
  expect(await screen.findByRole('heading', { name: '团队' })).toBeVisible();
  expect(window.location.hash).toBe('#/team');
});

it('lets the owner reach all twins even when the selected twin needs onboarding', async () => {
  items[0] = { ...items[0], id: NEW };
  setPersonaId(NEW);
  usePersonas.setState({ id: NEW, items });
  render(<App />);
  expect(await screen.findByRole('heading', { name: '团队' })).toBeVisible();
  expect(
    screen.queryByRole('heading', { name: '你是谁' }),
  ).not.toBeInTheDocument();
});

it('sets up a new twin from a card in its chat, with the side bar still around it', async () => {
  items.push({ ...items[1], id: NEW, name: '新伙伴' });
  setPersonaId(NEW);
  usePersonas.setState({ id: NEW, items });
  window.location.hash = '#/chat';
  render(<App />);
  const card = await screen.findByRole('region', { name: '让新伙伴认识你' });
  expect(await within(card).findByText('哪位是你？')).toBeVisible();
  expect(
    await within(card).findByRole('button', { name: '说话人 1 是我' }),
  ).toBeVisible();
  expect(screen.getByRole('navigation', { name: '主导航' })).toBeVisible();
  expect(
    screen.queryByRole('link', { name: '返回我的分身' }),
  ).not.toBeInTheDocument();
});
