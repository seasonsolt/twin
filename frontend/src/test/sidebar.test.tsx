import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AppShell } from '../components/layout/AppShell';
import { ConfirmProvider, TooltipProvider } from '../components/ui';
import type { LibraryState, Recording } from '../pages/Library';
import type { Person } from '../pages/Recording';
import { useAuth } from '../stores/auth';
import { usePersonas, type Persona } from '../stores/personas';
import { useStatus } from '../stores/status';

const json = (value: unknown) =>
  new Response(JSON.stringify(value), { status: 200 });
const recording = (change: Partial<Recording>): Recording => ({
  id: 'rec_1',
  filename: '周会.m4a',
  size: 10,
  kind: 'audio',
  status: 'ready',
  error: '',
  duration_s: 600,
  transcribed_s: 600,
  speakers: 3,
  segments: 100,
  created_at: 'now',
  people: [],
  unsettled: 0,
  ...change,
});
const person = (change: Partial<Person>): Person => ({
  id: 'u-1',
  name: '林舟',
  persona_id: null,
  speakers: 1,
  seconds: 600,
  samples: 1,
  updating: false,
  auto: false,
  gender: '',
  recording_id: null,
  speaker_id: null,
  ...change,
});
const twin = (change: Partial<Persona>): Persona => ({
  id: 'default',
  name: '林舟',
  avatar_url: null,
  sources: 3,
  created_at: '',
  is_default: true,
  can_manage: true,
  ...change,
});

let library: LibraryState;
let people: Person[];
let voices: unknown[];
beforeEach(() => {
  library = {
    recordings: [recording({}), recording({ id: 'rec_2', status: 'failed' })],
    pending: 0,
    max_pending: 20,
    asr: true,
    capacity: {
      free_bytes: 50 * 1024 ** 3,
      arriving_bytes: 0,
      arriving: 0,
      headroom_bytes: 20 * 1024 ** 3,
    },
  };
  people = [
    person({ id: 'u-1', name: '林舟', persona_id: 'default' }),
    person({ id: 'u-2', name: '许清禾' }),
    person({ id: 'u-3', name: '未命名 1', auto: true }),
  ];
  voices = [{ id: 'v-1', members: [], seconds: 30, candidates: [] }];
  useAuth.setState({
    identity: { email: null, admin: false, auth_enabled: false },
  });
  useStatus.setState({ data: null, error: null });
  usePersonas.setState({ id: 'default', items: [twin({})] });
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library') return json(library);
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices, fragments: [], unsorted: [] });
      if (url === '/api/personas') return json(usePersonas.getState().items);
      return json({});
    }),
  );
});
afterEach(() => {
  useAuth.setState({ identity: null });
  vi.restoreAllMocks();
});

function Where() {
  const location = useLocation();
  return (
    <p>
      在{location.pathname}
      {location.search}
      {location.state?.search ? `找${location.state.search}` : ''}
      {location.state?.ask ? `问${location.state.ask}` : ''}
    </p>
  );
}

const show = (entry: string) =>
  render(
    <TooltipProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={[entry]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="team" element={<Where />} />
              <Route path="library" element={<Where />} />
              <Route path="library/:recordingId" element={<Where />} />
              <Route path="inbox" element={<Where />} />
              <Route path="team/:id" element={<Where />} />
              <Route path="team/twin/:twinId" element={<Where />} />
              <Route path="chat" element={<Where />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ConfirmProvider>
    </TooltipProvider>,
  );

it('counts the team and what waits as the team page does, and marks the tab in view as the place', async () => {
  show('/inbox');
  const nav = await screen.findByRole('navigation', { name: '主导航' });
  // Two named people (the unnamed voice is a task, not a member); waiting: that voice, the review's voice, the
  // failed recording.
  expect(
    await within(nav).findByRole('link', { name: '团队（2）' }),
  ).toHaveAttribute('href', '/team');
  const todo = within(nav).getByRole('link', { name: '待处理（3）' });
  expect(todo).toHaveAttribute('href', '/inbox');
  expect(todo).toHaveAttribute('aria-current', 'page');
  expect(
    within(nav).getByRole('link', { name: '团队（2）' }),
  ).not.toHaveAttribute('aria-current');
  expect(
    within(nav)
      .getAllByRole('link')
      .map((link) => link.textContent),
  ).toEqual(['团队2', '对话', '录音库', '待处理3', '承诺']);
  expect(screen.getByText('我的团队')).toBeVisible();
});

it('asks the queue only how much waits, and counts from its totals', async () => {
  const asked: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library') return json(library);
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) {
        asked.push(url);
        return json({
          items: [],
          voices: [],
          fragments: [],
          unsorted: [],
          suspects: [],
          totals: {
            voices: { count: 3, seconds: 90 },
            enough: { count: 1, seconds: 600 },
            strangers: { count: 0, seconds: 0 },
            items: { count: 0 },
            unsorted: { count: 2 },
            suspects: { count: 5 },
          },
        });
      }
      if (url === '/api/personas') return json(usePersonas.getState().items);
      return json({});
    }),
  );
  show('/chat');
  const nav = await screen.findByRole('navigation', { name: '主导航' });
  // The unnamed voice, four voices, two recordings to settle one by one and the failed recording; suspect
  // speakers can wait.
  expect(
    await within(nav).findByRole('link', { name: '待处理（8）' }),
  ).toBeVisible();
  expect(asked).toEqual([
    '/api/library/review?voices=0&enough=0&strangers=0&items=0&unsorted=0&suspects=0',
  ]);
});

it('shows what runs in the background only while something does', async () => {
  const view = show('/team');
  await screen.findByRole('link', { name: '团队（2）' });
  expect(screen.queryByRole('link', { name: /^后台/ })).toBeNull();
  view.unmount();
  library.recordings = [
    recording({ status: 'transcribing', transcribed_s: 150 }),
    recording({ id: 'rec_2', status: 'queued' }),
    recording({ id: 'rec_3', status: 'queued' }),
  ];
  people = [person({ updating: true, persona_id: 'default' })];
  const { useTeam } = await import('../stores/team');
  await useTeam.getState().refresh(true);
  show('/chat');
  const card = await screen.findByRole('link', { name: /^后台 4 项/ });
  expect(card).toHaveAttribute('href', '/library');
  expect(card).toHaveTextContent('1 项转写中 · 2 项排队 · 1 人整理中');
  expect(
    within(card).getByRole('progressbar', { name: '当前一项的进度' }),
  ).toHaveAttribute('aria-valuenow', '150');
});

it('finds someone by name with ⌘K: each opens on their member page, a twin made by hand on its own address', async () => {
  usePersonas.setState({
    id: 'default',
    items: [twin({}), twin({ id: 'p-self', name: '本人', is_default: false })],
  });
  const user = userEvent.setup();
  show('/chat');
  await screen.findByRole('link', { name: '团队（3）' });
  await user.keyboard('{Meta>}k{/Meta}');
  const dialog = await screen.findByRole('dialog', { name: '问一句、找人' });
  const options = within(dialog).getAllByRole('option');
  // The team's people, then twins made without recordings.
  expect(options.map((option) => option.textContent)).toEqual([
    '林舟看档案',
    '许清禾没有分身',
    '本人看档案',
  ]);
  await user.type(within(dialog).getByRole('combobox'), '许');
  await user.keyboard('{Enter}');
  expect(await screen.findByText('在/team/u-2')).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.queryByRole('dialog', { name: '问一句、找人' })).toBeNull(),
  );

  await user.click(screen.getByRole('button', { name: '问一句、找人' }));
  const again = await screen.findByRole('dialog', { name: '问一句、找人' });
  await user.type(within(again).getByRole('combobox'), '本');
  await user.keyboard('{Enter}');
  expect(await screen.findByText('在/team/twin/p-self')).toBeInTheDocument();
});

it("finds a colleague's public twin once, as the person it belongs to, and counts it once", async () => {
  people = [
    person({ id: 'u-1', name: '林舟', persona_id: 'default' }),
    person({
      id: 'u-2',
      name: '许清禾',
      persona_id: null,
      talk: 'p-pub',
      twin_id: 'p-pub',
      can_manage: false,
    }),
  ];
  usePersonas.setState({
    id: 'default',
    items: [twin({}), twin({ id: 'p-pub', name: '许清禾', is_default: false })],
  });
  const user = userEvent.setup();
  show('/chat');
  await screen.findByRole('link', { name: '团队（2）' });
  await user.keyboard('{Meta>}k{/Meta}');
  const dialog = await screen.findByRole('dialog', { name: '问一句、找人' });
  expect(
    within(dialog)
      .getAllByRole('option')
      .map((option) => option.textContent),
  ).toEqual(['林舟看档案', '许清禾看档案']);
});

const asked = (overrides: Record<string, unknown> = {}) => ({
  team_answers: [
    {
      id: 'ta_1',
      persona_id: 'p-shen',
      owner_name: '沈从',
      title: '续约折扣谁能批？',
      body: '15% 以内销售负责人自己定，超过 15% 报沈从批，当天回复。',
      confirmed_at: '2026-10-09T09:00:00+00:00',
      status: 'valid',
      stale_note: '',
      partial: false,
    },
  ],
  people: [
    {
      persona_id: 'p-wang',
      name: '王屿',
      level: 3,
      label: '了解较多',
      occasions: 7,
      last_seen: '2026-10-18',
      facets: ['熟悉领域的看法'],
    },
    {
      persona_id: 'p-chen',
      name: '陈一',
      level: 1,
      label: '提到过',
      occasions: 2,
      last_seen: '2026-10-01',
      facets: ['拿手的事'],
    },
  ],
  meetings: [
    {
      recording_id: 'rec_9',
      title: '季度复盘',
      date: '2026-10-18',
      speaker: '王屿',
      quote: '续约这两家我都让到了 12%',
      start: 12,
      line: 4,
    },
  ],
  decision: true,
  degraded: false,
  ...overrides,
});
const askRequests = () =>
  vi
    .mocked(fetch)
    .mock.calls.filter(([url]) => String(url).startsWith('/api/personas/ask'));

it('puts a question to the whole team with ⌘K: the answer it has, whom to ask, the meetings; Enter opens a talk with the first', async () => {
  usePersonas.setState({
    id: 'default',
    items: [twin({}), twin({ id: 'p-wang', name: '王屿', is_default: false })],
  });
  const respond = vi.mocked(fetch).getMockImplementation() as (
    url: string,
  ) => Promise<Response>;
  vi.mocked(fetch).mockImplementation(async (url) =>
    String(url).startsWith('/api/personas/ask')
      ? json(asked())
      : respond(String(url)),
  );
  const user = userEvent.setup();
  show('/chat');
  await screen.findByRole('link', { name: '团队（3）' });
  await user.keyboard('{Meta>}k{/Meta}');
  const dialog = await screen.findByRole('dialog', { name: '问一句、找人' });
  await user.type(within(dialog).getByRole('combobox'), '续约折扣谁能批？');
  // The team's answer first, as a card; then whom to ask, with how well they know it; then the meetings.
  const answer = await within(dialog).findByRole('article', {
    name: '团队答案',
  });
  expect(within(answer).getByText('沈从 10 月 9 日确认')).toBeVisible();
  expect(within(answer).getByText(/超过 15% 报沈从批/u)).toBeVisible();
  expect(within(answer).queryByRole('button')).toBeNull();
  const people = within(dialog).getByRole('region', { name: '该问谁' });
  expect(
    within(people).getByText('具体要他拍板，他的分身会转给本人'),
  ).toBeVisible();
  const rows = within(dialog).getAllByRole('option');
  expect(rows.map((row) => row.textContent)).toEqual([
    '王屿了解较多 · 熟悉领域的看法 · 7 场问分身',
    '陈一提到过 · 拿手的事 · 2 场问分身',
    '季度复盘 · 10/18王屿：“续约这两家我都让到了 12%”看录音',
  ]);
  expect(askRequests()).toHaveLength(1);
  expect(String(askRequests()[0][0])).toContain(
    encodeURIComponent('续约折扣谁能批？'),
  );
  // Enter goes to the first: their twin, with the question already in the box.
  await user.keyboard('{Enter}');
  expect(
    await screen.findByText('在/chat?with=p-wang问续约折扣谁能批？'),
  ).toBeInTheDocument();
});

it('opens the recording of a meeting the question came up in', async () => {
  const respond = vi.mocked(fetch).getMockImplementation() as (
    url: string,
  ) => Promise<Response>;
  vi.mocked(fetch).mockImplementation(async (url) =>
    String(url).startsWith('/api/personas/ask')
      ? json(asked({ team_answers: [], people: [], decision: false }))
      : respond(String(url)),
  );
  const user = userEvent.setup();
  show('/team');
  await screen.findByRole('link', { name: /^团队/u });
  await user.keyboard('{Meta>}k{/Meta}');
  const dialog = await screen.findByRole('dialog', { name: '问一句、找人' });
  await user.type(within(dialog).getByRole('combobox'), '续约折扣怎么让');
  await user.click(
    await within(dialog).findByRole('option', { name: /季度复盘/u }),
  );
  expect(
    await screen.findByText('在/library/rec_9?line=4'),
  ).toBeInTheDocument();
});

it('does not ask the team for a name that is just a person’s, and says when nobody has talked about a matter', async () => {
  const respond = vi.mocked(fetch).getMockImplementation() as (
    url: string,
  ) => Promise<Response>;
  vi.mocked(fetch).mockImplementation(async (url) =>
    String(url).startsWith('/api/personas/ask')
      ? json(asked({ team_answers: [], people: [], meetings: [] }))
      : respond(String(url)),
  );
  const user = userEvent.setup();
  show('/chat');
  await screen.findByRole('link', { name: /^团队/u });
  await user.keyboard('{Meta>}k{/Meta}');
  const dialog = await screen.findByRole('dialog', { name: '问一句、找人' });
  await user.type(within(dialog).getByRole('combobox'), '许清禾');
  await new Promise((done) => setTimeout(done, 500));
  expect(askRequests()).toHaveLength(0);
  expect(within(dialog).getAllByRole('option')).toHaveLength(1);
  await user.clear(within(dialog).getByRole('combobox'));
  await user.type(within(dialog).getByRole('combobox'), '年会在哪办');
  expect(
    await within(dialog).findByText('团队里还没人谈过这件事，可以按名字找人'),
  ).toBeVisible();
  expect(askRequests()).toHaveLength(1);
});

it('says when only the meetings could be searched', async () => {
  const respond = vi.mocked(fetch).getMockImplementation() as (
    url: string,
  ) => Promise<Response>;
  vi.mocked(fetch).mockImplementation(async (url) =>
    String(url).startsWith('/api/personas/ask')
      ? json(asked({ team_answers: [], people: [], degraded: true }))
      : respond(String(url)),
  );
  const user = userEvent.setup();
  show('/chat');
  await screen.findByRole('link', { name: /^团队/u });
  await user.keyboard('{Meta>}k{/Meta}');
  const dialog = await screen.findByRole('dialog', { name: '问一句、找人' });
  await user.type(within(dialog).getByRole('combobox'), '续约折扣怎么让');
  expect(
    await within(dialog).findByText('向量模型没有配置好，只找到了会议'),
  ).toBeVisible();
});

it('does not count for the person what an earlier twin of theirs had waiting, answered late', async () => {
  let late: (value: Response) => void = () => {};
  const asked: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/persona/handoffs/count') {
        const twinId = new Headers(init?.headers).get('X-Twin-Persona') ?? '';
        asked.push(twinId);
        if (twinId === 'default')
          return new Promise<Response>((resolve) => {
            late = resolve;
          });
        return json({ pending: 0 });
      }
      if (url === '/api/personas') return json(usePersonas.getState().items);
      return json({});
    }),
  );
  show('/chat');
  await waitFor(() => expect(asked).toContain('default'));
  // Their own twin is another one now, which has nothing waiting.
  act(() => {
    usePersonas.setState({
      id: 'p-new',
      items: [twin({ id: 'p-new', name: '林舟' })],
    });
  });
  await waitFor(() => expect(asked).toContain('p-new'));
  await act(async () => {
    late(json({ pending: 5 }));
  });
  expect(screen.getByRole('button', { name: '账户' })).toBeVisible();
  expect(screen.queryByRole('button', { name: /条待决定/u })).toBeNull();
});

it('gives a guest the conversation alone: no counts, finding, uploading or background', async () => {
  usePersonas.setState({
    id: 'p-public',
    items: [twin({ id: 'p-public', name: '朋友', can_manage: false })],
  });
  show('/chat');
  const nav = await screen.findByRole('navigation', { name: '主导航' });
  expect(
    within(nav)
      .getAllByRole('link')
      .map((link) => link.textContent),
  ).toEqual(['对话']);
  expect(screen.queryByRole('button', { name: '问一句、找人' })).toBeNull();
  expect(screen.queryByRole('button', { name: '上传会议录音' })).toBeNull();
  expect(
    vi.mocked(fetch).mock.calls.some(([url]) => url === '/api/library'),
  ).toBe(false);
});

it('names the space after the team once an administrator has named it, and follows a rename at once', async () => {
  useAuth.setState({
    identity: {
      email: null,
      admin: true,
      auth_enabled: false,
      team_name: '产品研发部',
    },
  });
  show('/team');
  expect(await screen.findByText('产品研发部')).toBeVisible();
  expect(screen.queryByText('我的团队')).toBeNull();
  const { setTeamName } = await import('../stores/auth');
  act(() => setTeamName('增长组'));
  expect(await screen.findByText('增长组')).toBeVisible();
  act(() => setTeamName(null));
  expect(await screen.findByText('我的团队')).toBeVisible();
});
