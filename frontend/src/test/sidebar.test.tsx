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
      if (url === '/api/library/review')
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
  const dialog = await screen.findByRole('dialog', { name: '找人' });
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
    expect(screen.queryByRole('dialog', { name: '找人' })).toBeNull(),
  );

  await user.click(screen.getByRole('button', { name: '找人' }));
  const again = await screen.findByRole('dialog', { name: '找人' });
  await user.type(within(again).getByRole('combobox'), '本');
  await user.keyboard('{Enter}');
  expect(await screen.findByText('在/team/twin/p-self')).toBeInTheDocument();
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
  expect(screen.queryByRole('button', { name: '找人' })).toBeNull();
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
