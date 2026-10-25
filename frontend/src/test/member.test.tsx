import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import { CHAT_KEY } from '../features/chat/useConversation';
import { personaKey, setPersonaId } from '../lib/persona';
import { useAuth } from '../stores/auth';
import { usePersonas, type Persona } from '../stores/personas';
import { useStatus } from '../stores/status';
import { useWelcome } from '../stores/welcome';
import { isSourcesUrl, sourcesPage } from './personaApi';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
let items: Persona[];
let deleted: Persona | undefined;
let people: Record<string, unknown>[];
let handoffs: Record<string, unknown>[];
let team_answers: Record<string, unknown>[];
let fetcher: ReturnType<typeof vi.fn>;
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const twin = (change: Partial<Persona>): Persona => ({
  id: 'friend',
  name: '朋友',
  is_default: false,
  sources: 1,
  avatar_url: null,
  created_at: '',
  can_manage: true,
  ...change,
});
const person = (change: Record<string, unknown>) => ({
  id: 'per_1',
  name: '朋友',
  persona_id: 'friend',
  speakers: 3,
  seconds: 1800,
  samples: 1,
  updating: false,
  auto: false,
  gender: '',
  recording_id: null,
  speaker_id: null,
  ...change,
});
const pending = (id: string, question: string) => ({
  id,
  kind: 'decide',
  kind_label: '要你决定',
  status: 'delivered',
  status_label: '已送达',
  asker_name: '许清禾',
  question,
  context: '',
  ask: '',
  answer: null,
  source_known: true,
  created_at: '2026-10-14T09:00:00+00:00',
  expires_at: '2026-10-21T09:00:00+00:00',
  days_left: 3,
  commit: null,
  reply: null,
  replied_at: null,
});
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  items = [twin({ id: 'default', name: '本人', is_default: true }), twin({})];
  deleted = undefined;
  people = [];
  handoffs = [];
  team_answers = [];
  setPersonaId('friend');
  usePersonas.setState({ id: 'friend', items, pendingId: null });
  useAuth.setState({ identity: null });
  useStatus.setState({ data: null, error: null });
  useWelcome.getState().reset();
  window.location.hash = '#/team/twin/friend';
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  fetcher = vi.fn(async (path: string, init?: RequestInit) => {
    const id = new Headers(init?.headers).get('X-Twin-Persona');
    const persona = items.find((item) => item.id === id) ?? items[0];
    if (path === '/api/whoami')
      return json({ email: null, admin: true, auth_enabled: false });
    if (path === '/api/personas') return json(items);
    if (path === '/api/personas/trash') return json([]);
    if (path === '/api/personas/friend' && init?.method === 'DELETE') {
      deleted = items.find((item) => item.id === 'friend');
      items = items.filter((item) => item.id !== 'friend');
      return json({ deleted: true });
    }
    if (path === '/api/personas/friend/restore' && deleted) {
      items = [...items, deleted];
      deleted = undefined;
      return json({});
    }
    if (/^\/api\/personas\/[^/]+$/.test(path) && init?.method === 'PATCH') {
      const target = path.split('/').at(-1);
      items = items.map((item) =>
        item.id === target
          ? { ...item, ...JSON.parse(String(init.body)) }
          : item,
      );
      return json({});
    }
    if (path === '/api/library')
      return json({
        recordings: [
          {
            id: 'r-1',
            filename: '周会.m4a',
            size: 1,
            kind: 'audio',
            status: 'ready',
            error: '',
            duration_s: 60,
            transcribed_s: 60,
            speakers: 2,
            segments: 3,
            created_at: '2026-10-15T08:00:00Z',
            people: ['新同事'],
            unsettled: 0,
          },
        ],
        pending: 0,
        asr: true,
      });
    if (path === '/api/library/people') return json({ items: people });
    if (path.startsWith('/api/library/review'))
      return json({ items: [], voices: [], fragments: [], unsorted: [] });
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
        counts: { sources: 1, items: 12 },
        egress: [],
      });
    if (path === '/api/media/capabilities') return json({ available: false });
    if (path === '/api/persona/aliases')
      return json({ aliases: ['林总'], fixed: ['林沐'], not_me: 0 });
    if (path === '/api/channels') return json({ wecom: null });
    if (path === '/api/me/assets')
      return json({
        portrait: null,
        voice: null,
        speech_clone: false,
        video: false,
      });
    if (isSourcesUrl(path))
      return json(
        sourcesPage(path, [
          {
            source_id: 'audio',
            title: '访谈录音',
            status: 'needs_speaker',
            kind: 'audio',
            remembered: 0,
            detected_kind_label: '录音',
            first_date: null,
          },
        ]),
      );
    if (path === '/api/persona/processing') return json({ state: 'idle' });
    if (path === '/api/persona/items/summary')
      return json({ total: 12, conflicts: 0, dimensions: [] });
    if (path === '/api/persona/handoffs/count')
      return json({ pending: handoffs.length });
    if (path === '/api/persona/team-answers') return json({ team_answers });
    if (path === '/api/persona/handoffs')
      return json({
        waiting: handoffs,
        groups: [],
        often: [],
        answers: { total: team_answers.length, stale: 0 },
        guessed: [],
        sourced: [],
        sourced_count: 0,
        answered: 0,
        shelved: [],
        settled: [],
        pending: handoffs.length,
        days: 7,
      });
    if (path.startsWith('/api/persona/items'))
      return json({ items: [], total: 0 });
    if (path === '/api/persona/coverage')
      return json({ facets: [], suggestions: [], kind_labels: {} });
    if (path.startsWith('/api/persona/ledger'))
      return json({ entries: [], meetings: { total: 0, pending: 0 } });
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

const more = (name = '朋友') => screen.findByLabelText(`${name}的更多操作`);
// The toasts as seen, apart from the live region that reads the latest one out.
const toasts = () => within(screen.getByLabelText('通知'));

async function choose(
  user: ReturnType<typeof userEvent.setup>,
  name: string,
  who = '朋友',
) {
  await user.click(await more(who));
  await user.click(screen.getByRole('button', { name }));
}

it('opens on the 档案 of the twin its address names, with the way to talk to it and the rest under “⋯”', async () => {
  render(<App />);
  expect(
    await screen.findByRole('heading', { level: 1, name: '朋友' }),
  ).toBeVisible();
  expect(screen.getByText('喜欢徒步')).toBeVisible();
  expect(
    screen.getByRole('button', { name: '和朋友聊天' }),
  ).toBeInTheDocument();
  const crumb = screen.getByRole('navigation', { name: '位置' });
  expect(within(crumb).getByRole('link', { name: '团队' })).toHaveAttribute(
    'href',
    '#/team',
  );
  const nav = screen.getByRole('tablist', { name: '档案章节' });
  expect(
    within(nav)
      .getAllByRole('tab')
      .map((tab) => tab.textContent),
  ).toEqual(['档案', '记忆12', '承诺', '形象和声音']);
  expect(within(nav).getByRole('tab', { name: '档案' })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  // The old buttons are gone from the page: editing and the settings are under “⋯”.
  expect(screen.queryByRole('button', { name: '设置' })).toBeNull();
  expect(screen.queryByRole('button', { name: '删除这个分身' })).toBeNull();
  expect(screen.queryByText('企业微信')).toBeNull();
  expect(screen.queryByText('预置音色')).toBeNull();
  expect(screen.queryByRole('article')).toBeNull();
  expect(await screen.findByText('1 段录音待确认')).toBeVisible();
  const user = userEvent.setup();
  await user.click(screen.getByRole('link', { name: '去确认 →' }));
  await screen.findByRole('article');
  await waitFor(() =>
    expect(window.location.hash).toBe('#/team/twin/friend?section=memories'),
  );
  expect(screen.getByRole('tabpanel', { name: /记忆/u })).toHaveTextContent(
    '访谈录音',
  );
  await user.click(await more());
  await user.click(screen.getByRole('button', { name: '编辑' }));
  const dialog = await screen.findByRole('dialog', { name: '名字与介绍' });
  await waitFor(() => expect(dialog).toBeVisible());
  expect(screen.getByRole('textbox', { name: '名字' })).toHaveValue('朋友');
});

it('keeps the names the twin goes by in the settings, opened from “⋯”', async () => {
  render(<App />);
  const user = userEvent.setup();
  await screen.findByRole('heading', { level: 1, name: '朋友' });
  await choose(user, '别名');
  const settings = await screen.findByRole('dialog', { name: '分身设置' });
  expect(
    await within(settings).findByRole('button', { name: '删除称呼 林总' }),
  ).toBeInTheDocument();
});

it('switches panels with pointer and arrow keys, writes the panel to the address, and resets scroll', async () => {
  render(<App />);
  const nav = await screen.findByRole('tablist', { name: '档案章节' });
  const user = userEvent.setup();
  await user.click(within(nav).getByRole('tab', { name: '形象和声音' }));
  expect(window.location.hash).toBe('#/team/twin/friend?section=assets');
  expect(
    screen.getByRole('tabpanel', { name: '形象和声音' }),
  ).toHaveTextContent('预置音色');
  expect(window.scrollTo).toHaveBeenLastCalledWith({ top: 0 });
  within(nav).getByRole('tab', { name: '形象和声音' }).focus();
  await user.keyboard('{ArrowLeft}');
  expect(window.location.hash).toBe('#/team/twin/friend?section=ledger');
  await user.click(within(nav).getByRole('tab', { name: '档案' }));
  expect(window.location.hash).toBe('#/team/twin/friend');
  expect(await screen.findByText('1 段录音待确认')).toBeVisible();
  expect(HTMLElement.prototype.scrollIntoView).not.toHaveBeenCalled();
});

it.each([
  ['overview', '档案'],
  ['graph', '记忆'],
  ['memories', '记忆'],
  ['questions', '档案'],
  ['assets', '形象和声音'],
  ['channels', '档案'],
  ['unknown', '档案'],
])(
  'opens only the selected panel from the %s deep link',
  async (section, title) => {
    window.location.hash = `#/team/twin/friend?section=${section}`;
    render(<App />);
    // The channels link opens the twin's settings over the page, which hides the page behind it.
    const hidden = section === 'channels';
    const nav = await screen.findByRole('tablist', {
      name: '档案章节',
      hidden,
    });
    const tab = within(nav).getByRole('tab', {
      name: new RegExp(title, 'u'),
      hidden,
    });
    expect(tab).toHaveAttribute('aria-selected', 'true');
    const panel = await screen.findByRole('tabpanel', {
      name: new RegExp(title, 'u'),
      hidden,
    });
    expect(tab).toHaveAttribute('aria-controls', panel.id);
    if (section === 'graph') {
      expect(
        within(panel).getByRole('button', { name: '图谱' }),
      ).toHaveAttribute('aria-pressed', 'true');
      expect(
        await within(panel).findByRole('textbox', { name: '搜索记忆和原话' }),
      ).toBeVisible();
    }
    if (section === 'channels') {
      const settings = await screen.findByRole('dialog', { name: '分身设置' });
      expect(
        await within(settings).findByRole('button', { name: '绑定' }),
      ).toBeVisible();
      await waitFor(() =>
        expect(window.location.hash).toBe(
          '#/team/twin/friend?section=overview',
        ),
      );
    }
  },
);

it('mounts polling components only in their selected panel and aborts them when leaving', async () => {
  render(<App />);
  await screen.findByText('1 段录音待确认');
  expect(
    fetcher.mock.calls.some(
      ([path]) =>
        path === '/api/channels' || path === '/api/persona/processing',
    ),
  ).toBe(false);
  const nav = screen.getByRole('tablist', { name: '档案章节' });
  const user = userEvent.setup();
  await choose(user, '接入');
  await waitFor(() =>
    expect(fetcher.mock.calls.some(([path]) => path === '/api/channels')).toBe(
      true,
    ),
  );
  const channelRequest = fetcher.mock.calls.find(
    ([path]) => path === '/api/channels',
  )![1]!;
  const settings = screen.getByRole('dialog', { name: '分身设置' });
  await user.click(within(settings).getByRole('button', { name: '外部服务' }));
  expect(channelRequest.signal?.aborted).toBe(true);
  await user.keyboard('{Escape}');
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  await user.click(within(nav).getByRole('tab', { name: /记忆/u }));
  await screen.findByRole('article');
  const memoryRequest = fetcher.mock.calls.find(
    ([path]) => path === '/api/persona/processing',
  )![1]!;
  await user.click(within(nav).getByRole('tab', { name: '档案' }));
  expect(memoryRequest.signal?.aborted).toBe(true);
  expect(screen.queryByRole('article')).toBeNull();
});

it('deletes at once from “⋯”, returns to the team, and undoes it from the toast', async () => {
  sessionStorage.setItem(personaKey(CHAT_KEY, 'friend'), 'private');
  sessionStorage.setItem(CHAT_KEY, 'default history');
  render(<App />);
  const user = userEvent.setup();
  await screen.findByRole('heading', { level: 1, name: '朋友' });
  await choose(user, '删除分身');
  // A twin deleted waits a week in the trash: no confirmation, the toast undoes it.
  expect(screen.queryByRole('dialog')).toBeNull();
  await waitFor(() => expect(window.location.hash).toBe('#/team'));
  expect(usePersonas.getState().id).toBe('default');
  expect(sessionStorage.getItem(personaKey(CHAT_KEY, 'friend'))).toBeNull();
  expect(sessionStorage.getItem(CHAT_KEY)).toBe('default history');
  await screen.findByRole('heading', { name: '团队' });
  // The toast fades in: looked for at once, it may not have yet.
  await waitFor(() =>
    expect(toasts().getByText('已删除「朋友」')).toBeVisible(),
  );
  await user.click(toasts().getByRole('button', { name: '撤销' }));
  await waitFor(() =>
    expect(toasts().getByText('已恢复「朋友」')).toBeVisible(),
  );
  expect(
    fetcher.mock.calls.some(
      ([path, init]) =>
        path === '/api/personas/friend/restore' && init?.method === 'POST',
    ),
  ).toBe(true);
  expect(usePersonas.getState().items.map((item) => item.id)).toContain(
    'friend',
  );
});

it('protects the default twin: nothing to delete in its menu or its settings', async () => {
  window.location.hash = '#/team/twin/default';
  setPersonaId('default');
  usePersonas.setState({ id: 'default' });
  render(<App />);
  const user = userEvent.setup();
  await user.click(await more('本人'));
  expect(screen.queryByRole('button', { name: '删除分身' })).toBeNull();
  await user.click(screen.getByRole('button', { name: '别名' }));
  const settings = await screen.findByRole('dialog', { name: '分身设置' });
  expect(
    within(settings).queryByRole('button', { name: '删除分身' }),
  ).toBeNull();
});

it('asks once before deleting an empty leftover default twin, which cannot be restored', async () => {
  items[0] = { ...items[0], sources: 0, retirable: true };
  window.location.hash = '#/team/twin/default';
  setPersonaId('default');
  usePersonas.setState({ id: 'default', items });
  render(<App />);
  const user = userEvent.setup();
  await choose(user, '删除分身', '本人');
  const dialog = screen.getByRole('dialog', { name: '删除「本人」？' });
  expect(dialog).toHaveTextContent('它是空的，删除后不能恢复');
  await user.click(within(dialog).getByRole('button', { name: '取消' }));
  expect(fetcher.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(
    false,
  );
  expect(window.location.hash).toBe('#/team/twin/default');
});

it('keeps the page and reports a blocked deletion without clearing local data', async () => {
  sessionStorage.setItem(personaKey(CHAT_KEY, 'friend'), 'private');
  const original = fetcher.getMockImplementation()! as (
    path: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation((path: string, init?: RequestInit) =>
    path === '/api/personas/friend' && init?.method === 'DELETE'
      ? Promise.resolve(json({ detail: '这个分身还有任务在运行' }, 409))
      : original(path, init),
  );
  render(<App />);
  const user = userEvent.setup();
  await screen.findByRole('heading', { level: 1, name: '朋友' });
  await choose(user, '删除分身');
  // The toast fades in: refused at once, it is looked for before it has.
  await waitFor(() =>
    expect(toasts().getByText('这个分身还有任务在运行')).toBeVisible(),
  );
  expect(window.location.hash).toBe('#/team/twin/friend');
  expect(sessionStorage.getItem(personaKey(CHAT_KEY, 'friend'))).toBe(
    'private',
  );
});

it('makes a twin public or private from “⋯”', async () => {
  render(<App />);
  const user = userEvent.setup();
  await screen.findByRole('heading', { level: 1, name: '朋友' });
  expect(screen.queryByText('公开')).toBeNull();
  await choose(user, '设为公开');
  expect(await screen.findByText('公开')).toBeVisible();
  expect(
    JSON.parse(
      String(
        fetcher.mock.calls.find(
          ([path, init]) =>
            path === '/api/personas/friend' && init?.method === 'PATCH',
        )![1].body,
      ),
    ),
  ).toEqual({ public: true });
  await user.click(await more());
  expect(screen.getByRole('button', { name: '设为私有' })).toBeInTheDocument();
});

it('shows a colleague someone else’s public twin as its name and the way to talk to it, nothing to manage', async () => {
  // A colleague with a twin of their own: the team's places are theirs, another's twin is only to talk to.
  useAuth.setState({
    identity: {
      email: 'me@example.test',
      name: '我',
      admin: false,
      auth_enabled: true,
    },
  });
  items = [
    twin({ id: 'p-own', name: '我', mine: true, approved: true }),
    twin({ can_manage: false, public: true, owner: 'friend@example.test' }),
  ];
  usePersonas.setState({ items });
  render(<App />);
  expect(
    await screen.findByRole('heading', { level: 1, name: '朋友' }),
  ).toBeVisible();
  expect(screen.getByRole('button', { name: '和朋友聊天' })).toBeVisible();
  expect(screen.queryByRole('tablist')).toBeNull();
  expect(screen.queryByLabelText('朋友的更多操作')).toBeNull();
  // Nothing of its memory is asked for: a visitor may only talk to it.
  expect(
    fetcher.mock.calls.some(
      ([path]) =>
        String(path).startsWith('/api/persona/items') ||
        String(path).startsWith('/api/persona/sources'),
    ),
  ).toBe(false);
  await userEvent
    .setup()
    .click(screen.getByRole('button', { name: '和朋友聊天' }));
  // The chat opens on this twin, not on all conversations.
  await waitFor(() => expect(window.location.hash).toBe('#/chat?with=friend'));
});

it('lets the person themselves see what the twin could not answer, counted on the tab and on the account', async () => {
  useAuth.setState({
    identity: {
      email: 'me@example.test',
      name: '我',
      admin: false,
      auth_enabled: true,
    },
  });
  items = [twin({ id: 'friend', name: '我', mine: true, approved: true })];
  usePersonas.setState({ items });
  handoffs = [pending('q1', '需求评审里那组接口，这次就改还是下个版本？')];
  window.location.hash = '#/team/twin/friend';
  render(<App />);
  const user = userEvent.setup();
  const nav = await screen.findByRole('tablist', { name: '档案章节' });
  expect(
    within(nav)
      .getAllByRole('tab')
      .map((tab) => tab.textContent),
  ).toEqual(['档案', '记忆12', '你不在时1', '承诺', '赋能', '形象和声音']);
  expect(screen.getByText('（你）', { exact: false })).toBeVisible();
  // Their own twin is their assistant, which only they have: they ask it, not talk to it.
  expect(screen.getByRole('button', { name: '问问我的分身' })).toBeVisible();
  expect(
    await screen.findByRole('button', { name: '账户（1 条待决定）' }),
  ).toBeVisible();
  await user.click(within(nav).getByRole('tab', { name: /你不在时/u }));
  expect(window.location.hash).toBe('#/team/twin/friend?section=away');
  // The first question waits opened, with the box for the person's own words.
  const row = await screen.findByRole('article', {
    name: '需求评审里那组接口，这次就改还是下个版本？',
  });
  await user.type(within(row).getByRole('textbox'), '这次不改');
  handoffs = [];
  await user.click(within(row).getByRole('button', { name: '发送' }));
  expect(await screen.findByText('没有等你决定的事。')).toBeVisible();
  // The count on the account follows.
  expect(await screen.findByRole('button', { name: '账户' })).toBeVisible();
  // The card on the profile and the entry in the settings are gone: the questions live here.
  expect(screen.queryByRole('button', { name: '问过的问题' })).toBeNull();
});

it('keeps 你不在时 for the person themselves: an administrator looking after the twin does not see it', async () => {
  handoffs = [pending('q1', '这个问题只有本人能答')];
  render(<App />);
  await screen.findByRole('tablist', { name: '档案章节' });
  expect(screen.queryByRole('tab', { name: /你不在时/u })).toBeNull();
  // Without sign-in the first twin is the person's own; this one is not asked.
  expect(
    fetcher.mock.calls.some(
      ([path, init]) =>
        path.startsWith('/api/persona/handoffs') &&
        new Headers(init?.headers).get('X-Twin-Persona') === 'friend',
    ),
  ).toBe(false);
});

it('opens the member page of someone found in the recordings, switching to their twin', async () => {
  people = [person({})];
  window.location.hash = '#/team/per_1';
  setPersonaId('default');
  usePersonas.setState({ id: 'default' });
  render(<App />);
  expect(
    await screen.findByRole('heading', { level: 1, name: '朋友' }),
  ).toBeVisible();
  await waitFor(() => expect(usePersonas.getState().id).toBe('friend'));
  expect(window.location.hash).toBe('#/team/per_1');
  expect(screen.getByRole('tablist', { name: '档案章节' })).toBeVisible();
});

it('leads the address of a twin that has a person in the roster on to the person’s page', async () => {
  people = [person({})];
  window.location.hash = '#/team/twin/friend';
  render(<App />);
  await waitFor(() => expect(window.location.hash).toBe('#/team/per_1'));
  const heading = await screen.findByRole('heading', {
    level: 1,
    name: '朋友',
  });
  await waitFor(() => expect(heading).toBeVisible());
});

it('keeps the tab asked for when the address of a twin leads on to the person’s page', async () => {
  useAuth.setState({
    identity: {
      email: 'me@example.test',
      name: '我',
      admin: false,
      auth_enabled: true,
    },
  });
  items = [twin({ id: 'friend', name: '朋友', mine: true, approved: true })];
  usePersonas.setState({ items });
  people = [person({})];
  handoffs = [pending('q1', '需求评审里那组接口，这次就改还是下个版本？')];
  window.location.hash = '#/team/twin/friend?section=away';
  render(<App />);
  await waitFor(() =>
    expect(window.location.hash).toBe('#/team/per_1?section=away'),
  );
  expect(await screen.findByRole('tab', { name: /你不在时/u })).toHaveAttribute(
    'aria-selected',
    'true',
  );
});

it('opens the page of a person whose twin the viewer only talks to, by the twin the roster offers', async () => {
  useAuth.setState({
    identity: {
      email: 'me@example.test',
      name: '我',
      admin: false,
      auth_enabled: true,
    },
  });
  items = [
    twin({ id: 'p-own', name: '我', mine: true, approved: true }),
    twin({ can_manage: false, public: true, owner: 'friend@example.test' }),
  ];
  usePersonas.setState({ items });
  people = [person({ persona_id: null, talk: 'friend', twin_elsewhere: true })];
  window.location.hash = '#/team/twin/friend';
  render(<App />);
  await waitFor(() => expect(window.location.hash).toBe('#/team/per_1'));
  // The page fades in once the twin in view is the one it is about.
  await waitFor(() =>
    expect(screen.getByRole('button', { name: '和朋友聊天' })).toBeVisible(),
  );
  expect(screen.queryByText('还没有分身')).toBeNull();
});

it('keeps the address of a twin with no person in the roster, and does not wait for a roster that cannot be read', async () => {
  const original = fetcher.getMockImplementation()! as (
    path: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === '/api/library/people') throw new Error('人物读不出来');
    return original(path, init);
  });
  window.location.hash = '#/team/twin/friend';
  render(<App />);
  expect(
    await screen.findByRole('heading', { level: 1, name: '朋友' }),
  ).toBeVisible();
  expect(window.location.hash).toBe('#/team/twin/friend');
});

it('shows someone without a twin by the recordings they spoke in, and makes a twin for them', async () => {
  people = [
    person({ id: 'per_2', name: '新同事', persona_id: null, speakers: 2 }),
  ];
  let made: unknown;
  const original = fetcher.getMockImplementation()! as (
    path: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation((path: string, init?: RequestInit) => {
    if (
      path === '/api/library/people/per_2/persona' &&
      init?.method === 'POST'
    ) {
      made = JSON.parse(String(init.body));
      items = [...items, twin({ id: 'p-new', name: '新同事' })];
      people = [person({ id: 'per_2', name: '新同事', persona_id: 'p-new' })];
      return Promise.resolve(json({}));
    }
    return original(path, init);
  });
  window.location.hash = '#/team/per_2';
  render(<App />);
  const user = userEvent.setup();
  expect(
    await screen.findByRole('heading', { level: 1, name: '新同事' }),
  ).toBeVisible();
  expect(screen.getByText('没有分身')).toBeVisible();
  expect(screen.getByRole('link', { name: '周会.m4a' })).toHaveAttribute(
    'href',
    '#/library/r-1',
  );
  expect(screen.queryByRole('tablist')).toBeNull();
  await user.click(screen.getByRole('button', { name: '生成分身' }));
  const dialog = await screen.findByRole('dialog', { name: '为新同事建分身' });
  await user.type(
    within(dialog).getByRole('textbox', { name: /企业邮箱或工号/u }),
    'new@acme.cn',
  );
  await user.click(within(dialog).getByRole('button', { name: '建好' }));
  await waitFor(() => expect(made).toEqual({ claim: 'new@acme.cn' }));
  // Their page is then that of the twin made for them.
  await waitFor(() => expect(usePersonas.getState().id).toBe('p-new'));
  expect(
    await screen.findByRole('button', { name: '和新同事聊天' }),
  ).toBeVisible();
});

it.each([
  ['本人已认领', { self_claimed: true }],
  ['同事建了分身', { twin_elsewhere: true }],
])(
  'says %s of someone whose twin is not the viewer’s to make, and offers no way to make one',
  async (state, change) => {
    people = [
      person({
        id: 'per_2',
        name: '新同事',
        persona_id: null,
        speakers: 2,
        ...change,
      }),
    ];
    window.location.hash = '#/team/per_2';
    render(<App />);
    expect(
      await screen.findByRole('heading', { level: 1, name: '新同事' }),
    ).toBeVisible();
    expect(screen.getByText(state)).toBeVisible();
    expect(screen.queryByRole('button', { name: '生成分身' })).toBeNull();
    expect(screen.getByRole('link', { name: '周会.m4a' })).toBeVisible();
  },
);

it('says why making a twin failed inside the window it was asked in', async () => {
  people = [
    person({ id: 'per_2', name: '新同事', persona_id: null, speakers: 2 }),
  ];
  const original = fetcher.getMockImplementation()! as (
    path: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation((path: string, init?: RequestInit) => {
    if (path === '/api/library/people/per_2/persona' && init?.method === 'POST')
      return Promise.resolve(json({ detail: '已经有同事为 TA 建了分身' }, 409));
    return original(path, init);
  });
  window.location.hash = '#/team/per_2';
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: '生成分身' }));
  const dialog = await screen.findByRole('dialog', { name: '为新同事建分身' });
  await user.click(within(dialog).getByRole('button', { name: '建好' }));
  expect(await within(dialog).findByRole('alert')).toHaveTextContent(
    '已经有同事为 TA 建了分身',
  );
});

it('says where a twin stands as the team table does', async () => {
  people = [
    person({
      updating: true,
      build: { state: 'idle', last_error: '模型限流' },
    }),
  ];
  window.location.hash = '#/team/per_1';
  render(<App />);
  expect(await screen.findByText('更新没完成')).toBeVisible();
  expect(screen.queryByText('整理中')).toBeNull();
});

it('still says a twin is being rebuilt when its person claimed it by voice', async () => {
  people = [person({ self_claimed: true, updating: true })];
  window.location.hash = '#/team/per_1';
  render(<App />);
  expect(await screen.findByText('整理中')).toBeVisible();
  expect(screen.queryByText('本人已认领')).toBeNull();
});

it('counts the memories on the tab as the profile does, not as the whole server does', async () => {
  // The server-wide count also holds what only the twin’s person may use.
  useStatus.setState({
    data: {
      target_name: '朋友',
      counts: { sources: 1, items: 40 },
      llm: { provider: '', model: '' },
      embed: { provider: '' },
      egress: [],
    },
    error: null,
  });
  render(<App />);
  const nav = await screen.findByRole('tablist', { name: '档案章节' });
  expect(await within(nav).findByRole('tab', { name: '记忆12' })).toBeVisible();
});

it('leads the person back to the twin step they left for later', async () => {
  useAuth.setState({
    identity: {
      email: 'me@example.test',
      name: '我',
      admin: false,
      auth_enabled: true,
    },
  });
  items = [
    twin({
      id: 'friend',
      name: '我',
      mine: true,
      approved: false,
      from_meetings: true,
    }),
  ];
  usePersonas.setState({ items });
  useWelcome.getState().finishClaim();
  window.location.hash = '#/team/twin/friend';
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: '去确认' }));
  expect(useWelcome.getState().claimDone).toBe(false);
  await waitFor(() => expect(window.location.hash).toBe('#/welcome'));
});

it('goes back to the team from an address that names nobody', async () => {
  window.location.hash = '#/team/nobody';
  render(<App />);
  await screen.findByRole('heading', { name: '团队' });
  expect(window.location.hash).toBe('#/team');
  act(() => {
    window.location.hash = '#/team/twin/ghost';
  });
  await waitFor(() => expect(window.location.hash).toBe('#/team'));
});

it('leads the old profile addresses to the member page of the twin in view, on the tab they named', async () => {
  const cases: [string, string][] = [
    ['#/profile', '#/team/twin/friend'],
    ['#/profile?section=assets', '#/team/twin/friend?section=assets'],
    ['#/profile?section=memories', '#/team/twin/friend?section=memories'],
    ['#/profile?tab=away', '#/team/twin/friend?section=away'],
    ['#/memories', '#/team/twin/friend?section=memories'],
    ['#/sources', '#/team/twin/friend?section=memories'],
    ['#/about', '#/team/twin/friend'],
    ['#/persona', '#/team/twin/friend'],
    ['#/identity', '#/team/twin/friend'],
    // The fixed questions became 补一补, on the member page.
    ['#/questionnaire', '#/team/twin/friend'],
    [
      '#/profile?section=memories&view=graph',
      '#/team/twin/friend?section=memories&view=graph',
    ],
  ];
  render(<App />);
  for (const [from, to] of cases) {
    act(() => {
      window.location.hash = from;
    });
    await waitFor(() => expect(window.location.hash).toBe(to), {
      timeout: 4000,
    });
  }
  act(() => {
    window.location.hash = '#/twins';
  });
  await waitFor(() => expect(window.location.hash).toBe('#/team'));
});

it('leads the old addresses to the person’s page when the twin in view belongs to someone in the recordings', async () => {
  people = [person({})];
  window.location.hash = '#/profile?section=assets';
  render(<App />);
  await waitFor(() =>
    expect(window.location.hash).toBe('#/team/per_1?section=assets'),
  );
  const heading = await screen.findByRole('heading', {
    level: 1,
    name: '朋友',
  });
  await waitFor(() => expect(heading).toBeVisible());
});

it('leaves the old addresses for the team when there is no twin at all', async () => {
  items = [];
  usePersonas.setState({ items: [], id: '' });
  window.location.hash = '#/profile';
  render(<App />);
  await waitFor(() => expect(window.location.hash).toBe('#/team'));
});

it('lets the person themselves look through the answers they made the team’s, among their memories', async () => {
  useAuth.setState({
    identity: {
      email: 'me@example.test',
      name: '我',
      admin: false,
      auth_enabled: true,
    },
  });
  items = [twin({ id: 'friend', name: '我', mine: true, approved: true })];
  usePersonas.setState({ items });
  team_answers = [
    {
      id: 'ta_1',
      persona_id: 'friend',
      owner_name: '我',
      title: '旧版 Word 模板还支持吗？',
      body: '支持到 12 月 31 日。',
      confirmed_at: '2026-10-22T09:00:00+00:00',
      status: 'valid',
      stale_note: '',
      partial: false,
      handoff_id: 'h1',
    },
  ];
  window.location.hash = '#/team/twin/friend?section=memories&view=answers';
  render(<App />);
  expect(await screen.findByText('旧版 Word 模板还支持吗？')).toBeVisible();
  const views = screen.getByRole('group', { name: '记忆的看法' });
  expect(
    within(views)
      .getAllByRole('button')
      .map((button) => button.textContent),
  ).toEqual(['列表', '图谱', '我的团队答案']);
  expect(
    within(views).getByRole('button', { name: '我的团队答案' }),
  ).toHaveAttribute('aria-pressed', 'true');
});

it('keeps the team answers to the person themselves: an administrator looking after the twin sees the list only', async () => {
  window.location.hash = '#/team/twin/friend?section=memories&view=answers';
  render(<App />);
  const views = await screen.findByRole('group', { name: '记忆的看法' });
  expect(
    within(views)
      .getAllByRole('button')
      .map((button) => button.textContent),
  ).toEqual(['列表', '图谱']);
  expect(
    fetcher.mock.calls.some(([path]) => path === '/api/persona/team-answers'),
  ).toBe(false);
});
