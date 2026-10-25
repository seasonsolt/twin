import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
  ConfirmProvider,
  ToastViewport,
  TooltipProvider,
} from '../components/ui';
import type { ReviewUnit, UnitFix } from '../features/library/MixedSpeaker';
import { Inbox } from '../pages/Inbox';
import { Recording, type Person, type Speaker } from '../pages/Recording';
import type {
  LibraryState,
  Recording as LibraryRecording,
} from '../pages/Library';
import { usePersonas, type Persona } from '../stores/personas';
import { useTeam } from '../stores/team';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const person = (change: Partial<Person>): Person => ({
  id: 'per_1',
  name: '张总',
  persona_id: null,
  speakers: 1,
  seconds: 600,
  samples: 1,
  updating: false,
  auto: false,
  gender: '',
  recording_id: 'rec_1',
  speaker_id: 'S1',
  ...change,
});
const member = (recording_id: string, speaker_id: string, seconds: number) => ({
  recording_id,
  filename: `${recording_id}.m4a`,
  transcript_id: `t-${recording_id}`,
  speaker_id,
  seconds,
});
const voice = (id: string, change: Record<string, unknown> = {}) => ({
  id,
  members: [member('rec_1', `S-${id}`, 300)],
  seconds: 300,
  candidates: [] as unknown[],
  near: false,
  ...change,
});
const fresh = (change: Partial<Person>) =>
  person({ id: 'new', name: '未命名 1', auto: true, ...change });

interface Server {
  people: Person[];
  voices: ReturnType<typeof voice>[];
  fragments: ReturnType<typeof member>[];
  unsorted: unknown[];
  items: unknown[];
  suspects: unknown[];
  heard?: { settled: number; total: number };
  recordings: Partial<LibraryRecording>[];
  posts: { url: string; method?: string; body?: Record<string, unknown> }[];
  /** Answers to review requests: a status other than 200 fails them. */
  review: number;
  /** Answers to settling voices, and to saving a work e-mail: a status other than 200 fails them. */
  voicesStatus: number;
  claim: number;
}
let server: Server;
const library = (): LibraryState => ({
  recordings: server.recordings as LibraryRecording[],
  pending: 0,
  max_pending: 20,
  asr: true,
  capacity: {
    free_bytes: 50 * 1024 ** 3,
    arriving_bytes: 0,
    arriving: 0,
    headroom_bytes: 20 * 1024 ** 3,
  },
});
const settle = (members: { speaker_id: string }[]) => {
  const gone = new Set(members.map((m) => m.speaker_id));
  server.voices = server.voices.filter(
    (v) => !v.members.some((m) => gone.has(m.speaker_id)),
  );
  server.fragments = server.fragments.filter((m) => !gone.has(m.speaker_id));
};
/** The queue as the server cuts it (``review_queue.page``): the first so many of each list asked for, and how many
 * each holds in all. */
const page = (url: string) => {
  const limits = new URL(url, 'http://localhost').searchParams;
  const cut = <T,>(name: string, rows: T[]) =>
    limits.has(name) ? rows.slice(0, Number(limits.get(name))) : rows;
  const is = (v: Server['voices'][number], flag: 'enough' | 'stranger') =>
    Boolean((v as Record<string, unknown>)[flag]);
  const groups = {
    voices: server.voices.filter((v) => !is(v, 'enough') && !is(v, 'stranger')),
    enough: server.voices.filter((v) => is(v, 'enough') && !is(v, 'stranger')),
    strangers: server.voices.filter((v) => is(v, 'stranger')),
  };
  const totals: Record<string, { count: number; seconds?: number }> = {
    items: { count: server.items.length },
    unsorted: { count: server.unsorted.length },
    suspects: { count: server.suspects.length },
  };
  for (const [name, rows] of Object.entries(groups))
    totals[name] = {
      count: rows.length,
      seconds: rows.reduce((sum, v) => sum + v.seconds, 0),
    };
  return {
    items: cut('items', server.items),
    voices: Object.entries(groups).flatMap(([name, rows]) => cut(name, rows)),
    fragments: server.fragments,
    unsorted: cut('unsorted', server.unsorted),
    suspects: cut('suspects', server.suspects),
    heard: server.heard,
    totals,
  };
};
const posted = (url: string) => server.posts.filter((call) => call.url === url);

beforeEach(() => {
  server = {
    people: [person({}), person({ id: 'per_2', name: '李总' })],
    voices: [],
    fragments: [],
    unsorted: [],
    items: [],
    suspects: [],
    recordings: [],
    posts: [],
    review: 200,
    voicesStatus: 200,
    claim: 200,
  };
  usePersonas.setState({ items: [] });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : undefined;
      if (method !== 'GET') server.posts.push({ url, method, body });
      if (url === '/api/library') return json(library());
      if (url === '/api/library/people') return json({ items: server.people });
      if (url.startsWith('/api/library/review'))
        return server.review === 200
          ? json(page(url))
          : json({ detail: '复核暂时失败' }, server.review);
      if (url === '/api/library/voices' && method === 'POST') {
        if (server.voicesStatus !== 200)
          return json(
            { detail: '这个声音刚被别人处理过了' },
            server.voicesStatus,
          );
        settle(body!.members as { speaker_id: string }[]);
        return json({ recognised: 0 });
      }
      const rename = /^\/api\/library\/people\/([^/]+)$/u.exec(url)?.[1];
      if (rename && method === 'PATCH') {
        server.people = server.people.map((p) =>
          p.id === rename ? { ...p, auto: false, name: String(body!.name) } : p,
        );
        return json({ renamed: true });
      }
      const resolve = /people\/([^/]+)\/resolve$/u.exec(url)?.[1];
      if (resolve && method === 'POST') {
        server.people = server.people.filter((p) => p.id !== resolve);
        return json({ resolved: true });
      }
      if (url.endsWith('/merge') && method === 'POST') {
        const gone = /people\/([^/]+)\/merge$/u.exec(url)![1];
        server.people = server.people.filter((p) => p.id !== gone);
        return json({ merged: true });
      }
      if (url.endsWith('/apart') && method === 'POST')
        return json({ apart: true });
      if (url.endsWith('/retry') && method === 'POST') {
        server.recordings = server.recordings.map((r) =>
          url.includes(String(r.id)) ? { ...r, status: 'queued' } : r,
        );
        return json({});
      }
      if (/^\/api\/personas\/[^/]+\/claim$/u.test(url) && method === 'PUT')
        return server.claim === 200
          ? json({})
          : json(
              { detail: '这个邮箱或工号已经用在另一个分身上' },
              server.claim,
            );
      if (url === '/api/personas') return json([]);
      throw new Error(`${method} ${url}`);
    }),
  );
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function Where() {
  const location = useLocation();
  return (
    <p>
      在{location.pathname}
      {location.search}
    </p>
  );
}
const view = (entry = '/inbox') =>
  render(
    <MemoryRouter initialEntries={[entry]}>
      <TooltipProvider>
        <ConfirmProvider>
          <Routes>
            <Route path="/inbox" element={<Inbox />} />
            <Route path="/library/:recordingId" element={<Recording />} />
            <Route path="/team" element={<Where />} />
          </Routes>
          <ToastViewport />
        </ConfirmProvider>
      </TooltipProvider>
    </MemoryRouter>,
  );
/** Time passes for a settled row: the server hears it once the few seconds to take it back are over. */
const later = async (ms = 6000) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};
const clock = () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  return userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
};

it('lists only the kinds that have something, new voices first, longest speaking first', async () => {
  server.people = [
    person({}),
    fresh({ id: 'per_9', seconds: 60, recording_id: 'rec_9' }),
  ];
  server.voices = [
    voice('long', { seconds: 600 }),
    voice('stranger', { seconds: 900, stranger: true }),
  ];
  server.heard = { settled: 900, total: 3600 };
  view();
  const list = await screen.findByRole('list', { name: '新的声音' });
  // Whoever is a stranger waits last, folded away; the others by recorded speech.
  expect(
    within(list)
      .getAllByRole('listitem')
      .map((row) => row.textContent),
  ).toEqual([
    expect.stringContaining('没听过的声音'),
    expect.stringContaining('未命名 1'),
  ]);
  expect(screen.getByText('你标过不认识的声音')).not.toBeVisible();
  const kinds = screen.getByRole('group', { name: '类别' });
  expect(
    within(kinds)
      .getAllByRole('button')
      .map((b) => b.textContent),
  ).toEqual(['新的声音3']);
  expect(
    screen.getByRole('progressbar', { name: '已认出的发言' }),
  ).toHaveAttribute('aria-valuenow', '900');
  expect(screen.getAllByText('25%').length).toBeGreaterThan(0);
  // Whom the owner cannot name, the colleague can: an invitation to recognise their own voice.
  const user = userEvent.setup();
  const copy = vi.spyOn(navigator.clipboard, 'writeText');
  await user.click(screen.getByRole('button', { name: '复制邀请' }));
  expect(copy).toHaveBeenCalledWith(
    expect.stringMatching(/https?:\/\/[^#\s]+\/$/u),
  );
});

it('offers every name a voice may be as a button, the surest in the lead, and tells what the meeting calls it', async () => {
  server.voices = [
    voice('sure', {
      members: [member('rec_1', 'S1', 400)],
      seconds: 400,
      candidates: [
        { person_id: 'per_1', name: '张总', score: 0.9, sure: true },
      ],
    }),
    voice('two', {
      members: [member('rec_2', 'S2', 300)],
      seconds: 300,
      candidates: [
        { person_id: 'per_1', name: '张总', score: 0.7, split: true },
        { person_id: 'per_2', name: '李总', score: 0.68 },
      ],
      near: true,
    }),
    voice('called', {
      members: [member('rec_3', 'S3', 200)],
      seconds: 200,
      candidates: [],
      called: '宋明',
      quote: '那宋明你跟老夏解释一下',
    }),
    voice('mid', {
      members: [member('rec_4', 'S4', 100)],
      seconds: 100,
      candidates: [{ person_id: 'per_2', name: '李总', score: 0.66 }],
      tier: 'mid',
    }),
    voice('maybe', {
      members: [member('rec_5', 'S5', 50)],
      seconds: 50,
      candidates: [{ person_id: 'per_2', name: '李总', score: 0.5 }],
    }),
  ];
  view();
  const list = await screen.findByRole('list', { name: '新的声音' });
  const row = (title: string) =>
    within(list).getByText(title).closest('li') as HTMLElement;
  // Surely 张总: the button is the row's main action, and still a button like the others.
  const sure = within(row('像张总')).getByRole('group', { name: '这是谁' });
  expect(within(sure).getByRole('button', { name: '归给张总' })).toHaveClass(
    'bg-accent',
  );
  // Two it may be: both offered, and a note when it may be one person split in two.
  const two = row('像张总，也像李总');
  expect(within(two).getByText('可能被拆开')).toBeVisible();
  expect(within(two).getByRole('button', { name: '归给张总' })).toBeVisible();
  expect(within(two).getByRole('button', { name: '归给李总' })).toBeVisible();
  // A name the team does not have yet, with what was said that names it.
  const called = row('会上被叫作宋明');
  expect(called).toHaveTextContent('「那宋明你跟老夏解释一下」');
  expect(
    within(called).getByRole('button', { name: '新建成员：宋明' }),
  ).toHaveTextContent('+ 宋明');
  // Far ahead of everyone else without being surely them: still a button, first.
  expect(
    within(row('多半是李总')).getByRole('button', { name: '归给李总' }),
  ).toHaveClass('bg-accent');
  // One name it may be without being sure says so, and its button is no main action.
  expect(
    within(row('可能是李总')).getByRole('button', { name: '归给李总' }),
  ).not.toHaveClass('bg-accent');
  // Every voice has its recording one step away and a way to name anyone else.
  expect(
    within(called).getByLabelText(/^更多：会上被叫作宋明（\d+ 分钟）$/u),
  ).toBeVisible();
});

it('turns a settled row into what was done with 撤销, and tells the server only after a few seconds', async () => {
  const user = clock();
  server.voices = [
    voice('a', {
      members: [member('rec_1', 'S1', 400), member('rec_2', 'S3', 200)],
      seconds: 600,
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
    voice('b', { seconds: 100, members: [member('rec_3', 'S2', 100)] }),
  ];
  view();
  const list = await screen.findByRole('list', { name: '新的声音' });
  await user.click(screen.getByRole('button', { name: '归给张总' }));
  // The row's place now says what was done, and the count has gone down by one.
  const status = await within(list).findByRole('status');
  expect(status).toHaveTextContent('已归给张总');
  expect(
    screen.getByRole('button', { name: /^新的声音\s*1$/u }),
  ).toBeInTheDocument();
  expect(posted('/api/library/voices')).toHaveLength(0);
  await later(3000);
  expect(posted('/api/library/voices')).toHaveLength(0);
  await later(3000);
  // Every recording the voice was heard in is settled at once.
  await waitFor(() => expect(posted('/api/library/voices')).toHaveLength(1));
  expect(posted('/api/library/voices')[0].body).toEqual({
    members: [
      { recording_id: 'rec_1', transcript_id: 't-rec_1', speaker_id: 'S1' },
      { recording_id: 'rec_2', transcript_id: 't-rec_2', speaker_id: 'S3' },
    ],
    action: 'confirm',
    person_id: 'per_1',
  });
  await waitFor(() => expect(within(list).queryByRole('status')).toBeNull());
  expect(within(list).getAllByRole('listitem')).toHaveLength(1);
  void user;
});

it('leaves a settled row where its voice was, with what was done, and puts the voice back there on 撤销', async () => {
  const user = clock();
  server.voices = ['a', 'b', 'c'].map((id, i) =>
    voice(id, {
      members: [member('rec_1', `S${i}`, 300 - i)],
      seconds: 300 - i,
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
  );
  view();
  const list = await screen.findByRole('list', { name: '新的声音' });
  await user.click(screen.getAllByRole('button', { name: '归给张总' })[1]);
  const rows = within(list).getAllByRole('listitem');
  expect(rows).toHaveLength(3);
  expect(within(rows[1]).getByRole('status')).toHaveTextContent('已归给张总');
  expect(within(rows[0]).queryByRole('status')).toBeNull();
  await user.click(screen.getByRole('button', { name: '撤销：已归给张总' }));
  const back = within(list).getAllByRole('listitem');
  expect(
    within(back[1]).getByRole('button', { name: '归给张总' }),
  ).toBeVisible();
});

it('takes an answer back before the server hears it, without a request', async () => {
  const user = clock();
  server.voices = [
    voice('a', {
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
  ];
  view();
  const list = await screen.findByRole('list', { name: '新的声音' });
  await user.click(screen.getByRole('button', { name: '归给张总' }));
  await user.click(screen.getByRole('button', { name: '撤销：已归给张总' }));
  // The row is back with its answers, and nothing was ever sent.
  expect(screen.getByRole('button', { name: '归给张总' })).toBeVisible();
  expect(within(list).queryByRole('status')).toBeNull();
  await later(20000);
  expect(posted('/api/library/voices')).toHaveLength(0);
  expect(
    server.posts.filter(
      (call) => call.method === 'POST' || call.method === 'PATCH',
    ),
  ).toHaveLength(0);
});

it('asks for a name for a voice most like an unnamed one, and gives it to both', async () => {
  const user = clock();
  server.people = [...server.people, fresh({ id: 'per_9', name: '未命名 23' })];
  server.voices = [
    voice('a', {
      candidates: [{ person_id: 'per_9', name: '未命名 23', score: 0.7 }],
    }),
  ];
  view();
  const list = await screen.findByRole('list', { name: '新的声音' });
  const row = within(list)
    .getAllByRole('listitem')
    .find((item) => within(item).queryByText('和未命名 23像同一人'))!;
  // “未命名 23” is nobody to choose: no button, the row asks for a name.
  expect(
    within(row).queryByRole('button', { name: '归给未命名 23' }),
  ).toBeNull();
  await user.type(
    within(row).getByRole('combobox', { name: /像同一人.*是谁/u }),
    '王芳{Enter}',
  );
  expect(await screen.findByText('已新建王芳')).toBeVisible();
  await later();
  expect(posted('/api/library/voices')[0].body).toMatchObject({
    action: 'confirm',
    person_id: 'per_9',
  });
  expect(posted('/api/library/people/per_9')[0].body).toEqual({
    name: '王芳',
  });
});

it('tells the server every answer still waiting when the page is left', async () => {
  const user = clock();
  server.voices = ['a', 'b', 'c'].map((id, i) =>
    voice(id, {
      members: [member('rec_1', `S${i}`, 300 - i)],
      seconds: 300 - i,
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
  );
  const shown = view();
  await user.click(
    await screen
      .findAllByRole('button', { name: '归给张总' })
      .then((all) => all[0]),
  );
  await user.click(screen.getAllByRole('button', { name: '归给张总' })[0]);
  await user.click(screen.getAllByRole('button', { name: '归给张总' })[0]);
  expect(posted('/api/library/voices')).toHaveLength(0);
  shown.unmount();
  await waitFor(() => expect(posted('/api/library/voices')).toHaveLength(3));
  expect(
    posted('/api/library/voices').map((call) => call.body?.action),
  ).toEqual(['confirm', 'confirm', 'confirm']);
});

it('sends every answer still waiting at once, kept alive, when the tab is closed', async () => {
  const user = clock();
  server.voices = ['a', 'b', 'c'].map((id, i) =>
    voice(id, {
      members: [member('rec_1', `S${i}`, 300 - i)],
      seconds: 300 - i,
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
  );
  view();
  await user.click(
    await screen
      .findAllByRole('button', { name: '归给张总' })
      .then((all) => all[0]),
  );
  await user.click(screen.getAllByRole('button', { name: '归给张总' })[0]);
  await user.click(screen.getAllByRole('button', { name: '归给张总' })[0]);
  expect(posted('/api/library/voices')).toHaveLength(0);
  // No waiting for one to be answered before the next is sent: the page is gone by then.
  act(() => {
    window.dispatchEvent(new Event('pagehide'));
  });
  expect(posted('/api/library/voices')).toHaveLength(3);
  const sent = vi
    .mocked(fetch)
    .mock.calls.filter(([url]) => url === '/api/library/voices');
  expect(sent.map(([, init]) => init?.keepalive)).toEqual([true, true, true]);
  // Nothing else was sent kept alive.
  expect(
    vi
      .mocked(fetch)
      .mock.calls.filter(
        ([url, init]) => url !== '/api/library/voices' && init?.keepalive,
      ),
  ).toEqual([]);
});

it('adds a new person for a name the meeting called, or one typed, and settles an unnamed person from their row', async () => {
  const user = clock();
  server.people = [
    person({}),
    fresh({ id: 'first', name: '未命名 1', seconds: 700 }),
    fresh({ id: 'second', name: '未命名 2', seconds: 500 }),
    fresh({ id: 'third', name: '未命名 3', seconds: 300 }),
  ];
  server.voices = [
    voice('called', {
      seconds: 900,
      called: '宋明',
      quote: '那宋明你跟老夏解释一下',
    }),
  ];
  view();
  await user.click(
    await screen.findByRole('button', { name: '新建成员：宋明' }),
  );
  // An unnamed person is named in the row, among known people offered as the owner types.
  const first = screen.getByLabelText(/^未命名 1（.+），是谁$/u);
  const offered = document.getElementById(first.getAttribute('list')!)!;
  expect(
    Array.from(offered.querySelectorAll('option')).map((o) => o.value),
  ).toEqual(['张总']);
  await user.type(first, '王屿{Enter}');
  await user.type(
    screen.getByLabelText(/^未命名 2（.+），是谁$/u),
    '张总{Enter}',
  );
  await user.click(screen.getByLabelText(/^更多：未命名 3/u));
  await user.click(screen.getByRole('button', { name: '不在团队里' }));
  await later();
  await waitFor(() => expect(server.posts).toHaveLength(4));
  expect(posted('/api/library/voices')[0].body).toMatchObject({
    action: 'confirm',
    new_person: '宋明',
  });
  expect(posted('/api/library/people/first')[0]).toMatchObject({
    method: 'PATCH',
    body: { name: '王屿' },
  });
  // A name someone already has is given to that person.
  expect(posted('/api/library/people/second/resolve')[0].body).toEqual({
    into: 'per_1',
  });
  expect(posted('/api/library/people/third/resolve')[0].body).toEqual({
    into: null,
  });
  expect(await screen.findByText('现在没有需要你处理的事。')).toBeVisible();
});

it('sends the owner to the next row after an answer, so a run of answers is a run of keys', async () => {
  server.voices = [
    voice('a', {
      seconds: 400,
      members: [member('rec_1', 'S1', 400)],
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
    voice('b', {
      seconds: 300,
      members: [member('rec_1', 'S2', 300)],
      candidates: [{ person_id: 'per_2', name: '李总', score: 0.7 }],
    }),
    voice('c', { seconds: 200, members: [member('rec_1', 'S3', 200)] }),
  ];
  view();
  const user = userEvent.setup();
  const first = await screen.findByRole('button', { name: '归给张总' });
  first.focus();
  await user.keyboard('{Enter}');
  await waitFor(() =>
    expect(screen.getByRole('button', { name: '归给李总' })).toHaveFocus(),
  );
  await user.keyboard('{Enter}');
  // The third has no names to offer: the field for one is where the keys go.
  await waitFor(() =>
    expect(screen.getByLabelText(/^没听过的声音（.+），是谁$/u)).toHaveFocus(),
  );
});

it('settles two people of one name, putting off a merge as it does an answer', async () => {
  const user = clock();
  server.people = [
    person({ similar: ['per_2'] }),
    person({ id: 'per_2', name: '张总（2）', speakers: 3, similar: ['per_1'] }),
    // Someone the viewer does not look after: on the roster for picking, not among the tasks.
    person({ id: 'per_3', name: '王五', can_manage: false }),
  ];
  view('/inbox?cat=similar');
  const hint = (await screen.findByText('张总 和 张总（2）')).closest('li')!;
  expect(hint).toHaveTextContent('1 段录音 · 3 段录音');
  await user.click(within(hint).getByRole('button', { name: '合并' }));
  expect(await screen.findByText('已合并张总和张总（2）')).toBeVisible();
  expect(posted('/api/library/people/per_1/merge')).toHaveLength(0);
  await later();
  // The one who spoke more is kept.
  await waitFor(() =>
    expect(posted('/api/library/people/per_1/merge')[0].body).toEqual({
      into: 'per_2',
    }),
  );
  expect(await screen.findByText('现在没有需要你处理的事。')).toBeVisible();
});

it('settles a voice of several people apart, and short voices with whom they sound like, in one answer each', async () => {
  const user = clock();
  server.voices = [
    voice('stranger', {
      seconds: 50,
      members: [member('rec_7', 'S1', 50)],
      stranger: true,
    }),
    voice('new', { seconds: 30, members: [member('rec_8', 'S2', 30)] }),
  ];
  server.fragments = [
    { ...member('rec_8', 'S5', 6), like: { person_id: 'per_1', name: '张总' } },
    { ...member('rec_9', 'S4', 4), like: { person_id: 'per_1', name: '张总' } },
    { ...member('rec_9', 'S6', 3), like: null },
  ] as never;
  view();
  const list = await screen.findByRole('list', { name: '新的声音' });
  const first = list.querySelector('li')!;
  await user.click(within(first).getByLabelText(/^更多：/u));
  await user.click(
    within(first).getByRole('button', { name: '几个人混在一起' }),
  );
  await later();
  await waitFor(() => expect(posted('/api/library/voices')).toHaveLength(1));
  expect(posted('/api/library/voices')[0].body).toMatchObject({
    action: 'mixed',
    members: [{ recording_id: 'rec_8', speaker_id: 'S2' }],
  });
  // Short voices like 张总 are given in one click, without taking them as 张总's voice samples.
  await user.click(screen.getByRole('button', { name: /^零碎片段\s*1$/u }));
  expect(screen.getByText('2 段录音里有 3 段很短的声音')).toBeVisible();
  await user.click(
    await screen.findByRole('button', { name: '归给张总（2）' }),
  );
  expect(await screen.findByText('已归给张总')).toBeVisible();
  await later();
  await waitFor(() => expect(posted('/api/library/voices')).toHaveLength(2));
  expect(posted('/api/library/voices')[1].body).toEqual({
    action: 'confirm',
    person_id: 'per_1',
    sample: false,
    members: [
      { recording_id: 'rec_8', transcript_id: 't-rec_8', speaker_id: 'S5' },
      { recording_id: 'rec_9', transcript_id: 't-rec_9', speaker_id: 'S4' },
    ],
  });
});

it('keeps fragments for the owner to put aside together', async () => {
  const user = clock();
  server.fragments = [member('rec_1', 'S5', 3), member('rec_3', 'S2', 4)];
  view();
  const scraps = await screen.findByRole('list', { name: '零碎片段' });
  expect(scraps).toHaveTextContent('2 段录音里有 2 段很短的声音');
  expect(scraps).toHaveTextContent('共 7 秒，不像任何人');
  await user.click(within(scraps).getByRole('button', { name: '都放一边' }));
  await later();
  await waitFor(() => expect(posted('/api/library/voices')).toHaveLength(1));
  expect(posted('/api/library/voices')[0].body).toMatchObject({
    action: 'unknown',
  });
  expect(await screen.findByText('现在没有需要你处理的事。')).toBeVisible();
});

it('shows the earlier queue the server kept at once, then the current one in its place', async () => {
  server.voices = [
    voice('v_old', { members: [member('rec_1', 'S1', 300)], seconds: 300 }),
  ];
  const real = fetch;
  let release = () => {};
  const current = new Promise<void>((resolve) => {
    release = resolve;
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (!url.startsWith('/api/library/review')) return real(url, init);
      const answer = (await (await real(url, init)).json()) as Record<
        string,
        unknown
      >;
      if (url.endsWith('&stale=true')) return json({ ...answer, stale: true });
      await current;
      return json({ ...answer, voices: [], totals: undefined });
    }),
  );
  view();
  // The earlier reading is shown while the current one is worked out.
  const list = await screen.findByRole('list', { name: '新的声音' });
  expect(within(list).getAllByRole('listitem')).toHaveLength(1);
  const asked = vi
    .mocked(fetch)
    .mock.calls.map(([url]) => String(url))
    .filter((url) => url.startsWith('/api/library/review'));
  expect(asked.map((url) => url.endsWith('&stale=true'))).toEqual([
    true,
    false,
  ]);
  release();
  expect(await screen.findByText('现在没有需要你处理的事。')).toBeVisible();
});

it('shows twenty new voices at first and more on request, with what the rest add up to', async () => {
  server.voices = Array.from({ length: 27 }, (_, i) =>
    voice(`v${i}`, {
      members: [member('rec_1', `S${i}`, 600 - i * 10)],
      seconds: 600 - i * 10,
    }),
  );
  view();
  const list = await screen.findByRole('list', { name: '新的声音' });
  expect(within(list).getAllByRole('listitem')).toHaveLength(20);
  expect(screen.getByText(/还有 7 个说得更少（共 \d+ 分钟）/u)).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: '再显示 7 个' }));
  expect(within(list).getAllByRole('listitem')).toHaveLength(27);
});

it('asks for the first page of each list, counts the rest from the totals, and asks for more from the start', async () => {
  server.voices = Array.from({ length: 25 }, (_, i) =>
    voice(`v${i}`, {
      members: [member(`rec_${i}`, `S${i}`, 1200 - i * 10)],
      seconds: 1200 - i * 10,
    }),
  );
  // A new unnamed person, heard less than every voice: asked about last.
  server.people = [person({}), fresh({ id: 'per_new', seconds: 30 })];
  server.unsorted = Array.from({ length: 13 }, (_, i) => ({
    recording_id: `old_${i}`,
    filename: `旧会${i}.m4a`,
    speakers: 2,
    total: 2,
  }));
  const asked = () =>
    vi
      .mocked(fetch)
      .mock.calls.map(([url]) => String(url))
      .filter((url) => url.startsWith('/api/library/review'));
  const user = userEvent.setup();
  view();
  const list = await screen.findByRole('list', { name: '新的声音' });
  // Once, opened cold: the library arriving first is no change for the page to load again for.
  expect(asked()).toEqual([
    '/api/library/review?voices=20&enough=20&strangers=20&items=10&unsorted=10&suspects=10&stale=true',
  ]);
  expect(
    vi
      .mocked(fetch)
      .mock.calls.filter(([url]) => url === '/api/library/people'),
  ).toHaveLength(1);
  expect(within(list).getAllByRole('listitem')).toHaveLength(20);
  // Counted from the totals, not from the twenty loaded; the person still to ask about is among them.
  const kinds = screen.getByRole('group', { name: '类别' });
  expect(
    within(kinds)
      .getAllByRole('button')
      .map((b) => b.textContent),
  ).toEqual(['新的声音26', '还没认人13']);
  expect(screen.getByText(/还有 6 个说得更少（共 \d+ 分钟）/u)).toBeVisible();
  // Five voices still to load come before the new person: they are not shown past the last voice loaded.
  expect(screen.queryByText('未命名 1')).not.toBeInTheDocument();

  await user.click(screen.getByRole('button', { name: '再显示 6 个' }));
  await waitFor(() =>
    expect(within(list).getAllByRole('listitem')).toHaveLength(26),
  );
  expect(asked().at(-1)).toContain('voices=40&');
  expect(within(list).getAllByRole('listitem')[25]).toHaveTextContent(
    '未命名 1',
  );

  await user.click(within(kinds).getByRole('button', { name: /还没认人/u }));
  expect(screen.getAllByRole('link', { name: '试听并确认' })).toHaveLength(10);
  expect(screen.getByText('已显示 10 / 13')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: '再显示 3 个' }));
  await waitFor(() =>
    expect(screen.getAllByRole('link', { name: '试听并确认' })).toHaveLength(
      13,
    ),
  );
  expect(asked().at(-1)).toContain('unsorted=20');
});

it('asks for as many more voices as wait to be taken back, a page at a time, so a page stays open', async () => {
  const user = clock();
  server.voices = Array.from({ length: 30 }, (_, i) =>
    voice(`v${i}`, {
      members: [member(`rec_${i}`, `S${i}`, 1200 - i * 10)],
      seconds: 1200 - i * 10,
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
  );
  view();
  const list = await screen.findByRole('list', { name: '新的声音' });
  await user.click(
    within(within(list).getAllByRole('listitem')[0]).getByRole('button', {
      name: /张总/u,
    }),
  );
  // One answer waits to be taken back: it still comes with the queue, so the next page is asked for with it.
  await waitFor(() =>
    expect(
      vi
        .mocked(fetch)
        .mock.calls.map(([url]) => String(url))
        .filter((url) => url.startsWith('/api/library/review'))
        .at(-1),
    ).toContain('voices=40&'),
  );
  await waitFor(() =>
    expect(
      within(list)
        .getAllByRole('listitem')
        .filter((row) => !row.textContent?.includes('撤销')),
    ).toHaveLength(20),
  );
  // Opened, asked once more for the page, and told once the answer is told: settling it does not ask for the first
  // page again.
  const reviews = () =>
    vi
      .mocked(fetch)
      .mock.calls.filter(([url]) =>
        String(url).startsWith('/api/library/review'),
      );
  await later();
  await waitFor(() => expect(posted('/api/library/voices')).toHaveLength(1));
  await later(3000);
  expect(reviews()).toHaveLength(3);
  expect(String(reviews().at(-1)![0])).toContain('voices=40&');
});

it('does not ask for the queue again for answers waiting to be taken back when it is all loaded, until they are told', async () => {
  const user = clock();
  server.voices = Array.from({ length: 4 }, (_, i) =>
    voice(`v${i}`, {
      members: [member(`rec_${i}`, `S${i}`, 600 - i)],
      seconds: 600 - i,
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
  );
  view();
  const list = await screen.findByRole('list', { name: '新的声音' });
  const reviews = () =>
    vi
      .mocked(fetch)
      .mock.calls.filter(([url]) =>
        String(url).startsWith('/api/library/review'),
      );
  expect(reviews()).toHaveLength(1);
  for (let i = 0; i < 3; i++)
    await user.click(
      within(list).getAllByRole('button', { name: '归给张总' })[0],
    );
  expect(reviews()).toHaveLength(1);
  await later();
  await waitFor(() => expect(posted('/api/library/voices')).toHaveLength(3));
  await later(3000);
  expect(reviews()).toHaveLength(2);
});

it('shows why the queue failed to load, and lets the owner try again', async () => {
  server.review = 500;
  view();
  expect(await screen.findByRole('alert')).toHaveTextContent('复核暂时失败');
  expect(screen.queryByText('现在没有需要你处理的事。')).toBeNull();
  server.review = 200;
  await userEvent.click(screen.getByRole('button', { name: '重试' }));
  expect(await screen.findByText('现在没有需要你处理的事。')).toBeVisible();
  expect(screen.queryByRole('alert')).toBeNull();
});

it('says it is loading, not that nothing waits, until the queue has come', async () => {
  const real = fetch;
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.startsWith('/api/library/review')) await gate;
      return real(url, init);
    }),
  );
  view();
  expect(await screen.findByText('正在加载待处理事项…')).toBeVisible();
  expect(screen.queryByText('现在没有需要你处理的事。')).toBeNull();
  await act(async () => release());
  expect(await screen.findByText('现在没有需要你处理的事。')).toBeVisible();
});

it('retries failed recordings one by one or all at once, and asks before deleting one', async () => {
  const user = userEvent.setup();
  server.recordings = Array.from({ length: 12 }, (_, i) => ({
    id: `f${i}`,
    filename: `失败${i}.m4a`,
    status: 'failed' as const,
    error: '识别失败',
  }));
  view('/inbox?cat=failed');
  await screen.findByRole('button', { name: '全部重试' });
  // Ten at a time, but the batch handles every recording.
  expect(screen.getAllByRole('button', { name: '重试' })).toHaveLength(10);
  await user.click(screen.getByRole('button', { name: '全部重试' }));
  await waitFor(() =>
    expect(server.posts.filter((c) => c.url.endsWith('/retry'))).toHaveLength(
      12,
    ),
  );
  server.recordings = [
    { id: 'x', filename: '周会.m4a', status: 'failed', error: '失败' },
  ];
  view('/inbox?cat=failed');
  const rows = await screen.findAllByText('周会.m4a');
  await user.click(
    within(rows[0].closest('li')!).getByRole('button', { name: '删除' }),
  );
  const dialog = await screen.findByRole('dialog', {
    name: '删除「周会.m4a」？',
  });
  expect(posted('/api/library/recordings/x')).toHaveLength(0);
  await user.click(within(dialog).getByRole('button', { name: '删除录音' }));
  await waitFor(() =>
    expect(posted('/api/library/recordings/x')[0].method).toBe('DELETE'),
  );
});

const speaker = (change: Partial<Speaker>): Speaker => ({
  id: 'S1',
  seconds: 300,
  decision: 'none',
  person_id: null,
  rejected: [],
  sample: false,
  auto: false,
  candidates: [],
  near: false,
  samples: 2,
  ...change,
});

it('returns from settling a speaker in its recording to the kind it belongs to, and puts the keys in its first row', async () => {
  const real = fetch;
  let reviewed = false;
  server.items = [
    {
      ...speaker({ disputed: true }),
      recording_id: 'rec_1',
      filename: '周会.m4a',
    },
  ];
  server.people = [
    person({}),
    fresh({ id: 'new', name: '未命名 1', seconds: 100 }),
  ];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/recordings/rec_1')
        return json({
          id: 'rec_1',
          filename: '周会.m4a',
          status: 'ready',
          transcript_id: 't1',
          revision: 3,
          speakers: [speaker({ disputed: true })],
          segments: [{ start: 0, end: 4, text: '先看预算。', speaker: 'S1' }],
        });
      if (url.startsWith('/api/library/recordings/rec_1/speakers/')) {
        reviewed = true;
        server.items = [];
        return json({ revision: 4, person_id: 'per_1' });
      }
      return real(url, init);
    }),
  );
  view('/inbox?cat=disputed');
  const tasks = await screen.findByRole('list', { name: '有人说不是自己' });
  await userEvent.click(
    within(tasks).getByRole('link', { name: '试听并确认' }),
  );
  const card = (
    await screen.findByRole('heading', { name: 'S1 是谁？' })
  ).closest('section')!;
  await userEvent.selectOptions(within(card).getByLabelText('这是谁'), 'per_1');
  await userEvent.click(screen.getByRole('button', { name: '确认是张总' }));
  await waitFor(() => expect(reviewed).toBe(true));
  // Back in the inbox, on the new voices that are left, with the keys on the first one's field.
  await waitFor(() =>
    expect(screen.getByLabelText(/^未命名 1（.+），是谁$/u)).toHaveFocus(),
  );
  expect(screen.queryByRole('list', { name: '有人说不是自己' })).toBeNull();
});

it('opens the recording at the voice’s own speaker, and back to the inbox once it is settled', async () => {
  server.voices = [
    voice('a', {
      members: [member('rec_1', 'S2', 300)],
      candidates: [
        { person_id: 'per_1', name: '张总', score: 0.7 },
        { person_id: 'per_2', name: '李总', score: 0.68 },
      ],
      near: true,
    }),
  ];
  const real = fetch;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/recordings/rec_1')
        return json({
          id: 'rec_1',
          filename: '周会.m4a',
          status: 'ready',
          transcript_id: 't1',
          revision: 3,
          speakers: [speaker({}), speaker({ id: 'S2' })],
          segments: [
            { start: 0, end: 4, text: '先看预算。', speaker: 'S1' },
            { start: 4, end: 9, text: '我反对压缩研发。', speaker: 'S2' },
          ],
        });
      return real(url, init);
    }),
  );
  view();
  await userEvent.click(await screen.findByLabelText(/^更多：/u));
  await userEvent.click(screen.getByRole('button', { name: '打开录音' }));
  expect(
    await screen.findByRole('heading', { name: 'S2 是谁？' }),
  ).toBeInTheDocument();
});

const unit = (index: number, change: Partial<ReviewUnit>): ReviewUnit => ({
  index,
  segments: [index],
  start: index * 60,
  end: index * 60 + 5,
  seconds: 5,
  text: `第${index}段`,
  verdict: '',
  own: 0.7,
  other: 0.3,
  like: 'per_2',
  like_name: '李总',
  fix: null,
  to_person: null,
  to_name: null,
  ...change,
});

it('hears a confirmed voice again piece by piece under 有空再看, and gives what sounds like someone else to them', async () => {
  const user = userEvent.setup();
  let revision = 3;
  let units: ReviewUnit[] = [
    unit(0, {}),
    unit(1, { verdict: 'other', own: 0.2, other: 0.6, text: '研发不能砍。' }),
    unit(2, { verdict: 'other', own: 0.25, other: 0.5 }),
    // Left out by the review itself: still the owner's to decide.
    unit(3, {
      verdict: 'stranger',
      own: 0.1,
      other: 0.1,
      like: null,
      like_name: null,
      fix: 'exclude',
      auto: true,
    }),
  ];
  const summary = () => ({
    recording_id: 'rec_1',
    filename: '周会.m4a',
    transcript_id: 't1',
    revision,
    speaker_id: 'S8',
    person_id: 'per_1',
    name: '张总',
    status: 'ready',
    seconds: 20,
    suspect_seconds: 15,
    open_seconds:
      5 * units.filter((u) => u.verdict && (!u.fix || u.auto)).length,
    suspects: 3,
    open: units.filter((u) => u.verdict && (!u.fix || u.auto)).length,
    share: 0.75,
    likely: 'per_2',
    likely_name: '李总',
    units: [],
  });
  const puts: unknown[] = [];
  const real = fetch;
  server.suspects = [summary()];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.startsWith('/api/library/review')) {
        server.suspects = summary().open ? [summary()] : [];
        return real(url, init);
      }
      if (url === '/api/library/recordings/rec_1/speakers/S8/units') {
        if (init?.method === 'PUT') {
          const body = JSON.parse(String(init.body)) as {
            units: number[];
            action: string;
            person_id?: string;
          };
          puts.push(body);
          revision += 1;
          units = units.map((u) =>
            body.units.includes(u.index)
              ? {
                  ...u,
                  fix:
                    body.action === 'clear' ? null : (body.action as UnitFix),
                  auto: false,
                  to_person: body.person_id ?? null,
                  to_name: body.person_id ? '李总' : null,
                }
              : u,
          );
          return json({ revision });
        }
        return json({ ...summary(), units });
      }
      return real(url, init);
    }),
  );
  view();
  // Left out already, it harms nobody: it waits under 有空再看, and the sidebar does not count it.
  await user.click(
    await screen.findByRole('button', { name: /^有空再看\s*1$/u }),
  );
  const tasks = await screen.findByRole('list', { name: '有空再看' });
  expect(tasks).toHaveTextContent('张总 · 周会.m4a');
  expect(tasks).toHaveTextContent('75% 不像 · 15 秒');
  await user.click(within(tasks).getByRole('button', { name: '去听' }));
  const side = await screen.findByRole('dialog', { name: '周会.m4a · S8' });
  const pieces = await within(side).findByRole('list', { name: '代表片段' });
  expect(within(pieces).getAllByRole('listitem')).toHaveLength(3);
  await user.click(within(side).getByRole('button', { name: '都改给李总' }));
  await waitFor(() =>
    expect(puts).toEqual([
      {
        transcript_id: 't1',
        revision: 3,
        units: [1, 2],
        action: 'move',
        person_id: 'per_2',
      },
    ]),
  );
  const stranger = within(pieces).getByText('第3段').closest('li')!;
  await user.click(
    within(stranger).getByRole('button', { name: '确实不是张总' }),
  );
  await waitFor(() =>
    expect(puts[1]).toEqual({
      transcript_id: 't1',
      revision: 4,
      units: [3],
      action: 'exclude',
    }),
  );
  await waitFor(() => expect(screen.queryByText(/75% 不像/u)).toBeNull());
});

it('shows the progress of the voices answered in the one-by-one view', async () => {
  const user = clock();
  server.voices = [1, 2, 3].map((i) =>
    voice(`v${i}`, {
      members: [member('rec_1', `S${i}`, 400 - i)],
      seconds: 400 - i,
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
  );
  view('/inbox?view=focus');
  expect(await screen.findByText('1 / 3')).toBeVisible();
  expect(screen.getByRole('heading', { name: '这是谁？' })).toBeVisible();
  await user.click(screen.getByRole('button', { name: '是张总' }));
  expect(await screen.findByText('2 / 3')).toBeVisible();
  expect(
    screen.getByRole('progressbar', { name: '已处理 1 / 3' }),
  ).toBeVisible();
  // Taken back, it is the one to hear again.
  await user.click(screen.getByRole('button', { name: '撤销' }));
  expect(await screen.findByText('1 / 3')).toBeVisible();
  await later(20000);
  expect(posted('/api/library/voices')).toHaveLength(0);
});

it('hears who it may be beside the voice, and answers with a key or a name, one voice at a time', async () => {
  const user = clock();
  server.people = [
    person({ speakers: 14 }),
    person({ id: 'per_2', name: '李总', speakers: 6 }),
  ];
  server.voices = [
    voice('a', {
      seconds: 500,
      members: [member('rec_1', 'S1', 300), member('rec_2', 'S3', 200)],
      candidates: [
        { person_id: 'per_1', name: '张总', score: 0.7, split: true },
        { person_id: 'per_2', name: '李总', score: 0.68 },
      ],
      near: true,
    }),
    voice('b', {
      seconds: 200,
      members: [member('rec_3', 'S2', 200)],
      called: '宋明',
      quote: '那宋明你跟老夏解释一下',
    }),
    voice('c', { seconds: 100, members: [member('rec_4', 'S4', 100)] }),
  ];
  view('/inbox?view=focus');
  const compare = await screen.findByRole('region', { name: '对比听' });
  // Both can be heard by the voice they were confirmed with, and chosen with a button.
  expect(
    within(compare).getByRole('button', { name: '听张总确认过的声音' }),
  ).toBeVisible();
  expect(
    within(compare).getByRole('button', { name: '听李总确认过的声音' }),
  ).toBeVisible();
  expect(compare).toHaveTextContent('14 段录音');
  expect(compare).toHaveTextContent('可能被拆开');
  const heard = screen.getByRole('region', { name: '这个声音' });
  expect(heard.querySelector('audio')).toHaveAttribute(
    'src',
    '/api/library/recordings/rec_1/speakers/S-a/samples/0'.replace('S-a', 'S1'),
  );
  // ← → hear it in another recording; the footer names what comes next.
  await user.keyboard('{ArrowRight}');
  expect(heard.querySelector('audio')).toHaveAttribute(
    'src',
    '/api/library/recordings/rec_2/speakers/S3/samples/0',
  );
  expect(screen.getByText('下一个：会上被叫作宋明')).toBeVisible();
  // 1 answers with the first name, and the next voice is up at once.
  await user.keyboard('2');
  expect(await screen.findByText('2 / 3')).toBeVisible();
  expect(screen.getByText('已归给李总')).toBeVisible();
  expect(screen.getByRole('button', { name: '新建宋明' })).toBeVisible();
  // S leaves one for later: it goes behind the others.
  await user.keyboard('s');
  expect(screen.getByLabelText('都不是，输入名字')).toBeVisible();
  expect(screen.queryByRole('button', { name: '新建宋明' })).toBeNull();
  // N is the way to a name, Enter answers it.
  await user.keyboard('n');
  expect(screen.getByLabelText('都不是，输入名字')).toHaveFocus();
  await user.type(screen.getByLabelText('都不是，输入名字'), '王屿{Enter}');
  await user.keyboard('{Escape}');
  expect(screen.getByRole('button', { name: '新建宋明' })).toBeVisible();
  await user.keyboard('1');
  await later();
  await waitFor(() => expect(posted('/api/library/voices')).toHaveLength(3));
  expect(posted('/api/library/voices').map((c) => c.body)).toEqual([
    expect.objectContaining({ action: 'confirm', person_id: 'per_2' }),
    expect.objectContaining({ action: 'confirm', new_person: '王屿' }),
    expect.objectContaining({ action: 'confirm', new_person: '宋明' }),
  ]);
});

it('leaves the keys to a dialog or menu open over the one-by-one view', async () => {
  const user = clock();
  server.voices = [
    voice('a', {
      seconds: 300,
      members: [member('rec_1', 'S1', 300)],
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
    voice('b', { seconds: 100, members: [member('rec_2', 'S2', 100)] }),
  ];
  view('/inbox?view=focus');
  expect(await screen.findByText('1 / 2')).toBeVisible();
  const dialog = document.createElement('div');
  dialog.setAttribute('role', 'dialog');
  document.body.append(dialog);
  await user.keyboard('1s');
  expect(screen.getByText('1 / 2')).toBeVisible();
  expect(screen.queryByText('已归给张总')).toBeNull();
  dialog.remove();
  // A key something else already took is not the queue's either.
  const taken = (event: KeyboardEvent) => event.preventDefault();
  window.addEventListener('keydown', taken, { capture: true });
  await user.keyboard('1');
  window.removeEventListener('keydown', taken, { capture: true });
  expect(screen.queryByText('已归给张总')).toBeNull();
  await user.keyboard('1');
  expect(await screen.findByText('已归给张总')).toBeVisible();
});

it('takes back the last answer with U, and leaves the voice to be heard again', async () => {
  const user = clock();
  server.voices = [
    voice('a', {
      seconds: 300,
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
    voice('b', {
      seconds: 200,
      members: [member('rec_2', 'S2', 200)],
      candidates: [{ person_id: 'per_2', name: '李总', score: 0.7 }],
    }),
  ];
  view('/inbox?view=focus');
  await screen.findByText('1 / 2');
  await user.keyboard('1');
  expect(await screen.findByText('2 / 2')).toBeVisible();
  expect(screen.getByRole('button', { name: '是李总' })).toBeVisible();
  await user.keyboard('u');
  expect(await screen.findByText('1 / 2')).toBeVisible();
  expect(screen.getByRole('button', { name: '是张总' })).toBeVisible();
  await later(20000);
  expect(posted('/api/library/voices')).toHaveLength(0);
});

it('takes the whole run of seventy answers from the keyboard alone, and tells the server once each', async () => {
  const user = clock();
  server.voices = Array.from({ length: 70 }, (_, i) =>
    voice(`v${i}`, {
      members: [member('rec_1', `S${i}`, 1000 - i)],
      seconds: 1000 - i,
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
  );
  const play = vi
    .spyOn(HTMLMediaElement.prototype, 'play')
    .mockResolvedValue(undefined);
  view('/inbox?view=focus');
  expect(await screen.findByText('1 / 70')).toBeVisible();
  for (let i = 0; i < 70; i++) {
    expect(await screen.findByText(`${i + 1} / 70`)).toBeVisible();
    // Space plays, → hears another, then 1 answers: no pointer anywhere.
    await user.keyboard(' ');
    await user.keyboard('1');
  }
  expect(await screen.findByText('新的声音都处理完了')).toBeVisible();
  // Space played each voice before it was answered.
  expect(play).toHaveBeenCalledTimes(70);
  // Nothing was told yet but what had waited its few seconds; the rest follows by itself.
  await later(20000);
  await waitFor(() => expect(posted('/api/library/voices')).toHaveLength(70));
  const heard = posted('/api/library/voices').map(
    (call) => (call.body?.members as { speaker_id: string }[])[0].speaker_id,
  );
  expect(new Set(heard).size).toBe(70);
  expect(
    posted('/api/library/voices').every((c) => c.body?.person_id === 'per_1'),
  ).toBe(true);
  // The queue was loaded again once the run was told, not after each answer.
  const loads = vi
    .mocked(fetch)
    .mock.calls.filter(([url]) =>
      String(url).startsWith('/api/library/review'),
    ).length;
  expect(loads).toBeLessThan(10);
});

it('takes a voice from a keyboard-only owner into the list again', async () => {
  const user = userEvent.setup();
  server.voices = [voice('a')];
  view('/inbox?view=focus');
  await screen.findByText('1 / 1');
  await user.click(screen.getByRole('radio', { name: '列表' }));
  expect(await screen.findByRole('list', { name: '新的声音' })).toBeVisible();
  await user.click(screen.getByRole('radio', { name: '逐个听' }));
  expect(await screen.findByText('1 / 1')).toBeVisible();
});

it('leads the old team tab to the inbox, keeping the kind', async () => {
  const { Team } = await import('../features/library/Team');
  render(
    <MemoryRouter initialEntries={['/team?tab=todo&cat=failed']}>
      <ConfirmProvider>
        <Routes>
          <Route path="/team" element={<Team version={0} recordings={[]} />} />
          <Route path="/inbox" element={<Where />} />
        </Routes>
      </ConfirmProvider>
    </MemoryRouter>,
  );
  expect(await screen.findByText('在/inbox?cat=failed')).toBeVisible();
});

const twinOf = (change: Partial<Persona>): Persona => ({
  id: 'p-1',
  name: '张总',
  avatar_url: null,
  sources: 1,
  created_at: '',
  is_default: false,
  can_manage: true,
  ...change,
});

it('lists a twin a colleague sent back, and points it at another e-mail or employee number', async () => {
  const user = userEvent.setup();
  server.people = [person({ persona_id: 'p-1' })];
  usePersonas.setState({
    items: [
      twinOf({ claimed: false, claim: 'old@x.cn', claim_rejected: 'old@x.cn' }),
    ],
  });
  view('/inbox?cat=disowned');
  const row = (await screen.findByText('old@x.cn 说这不是 TA')).closest('li')!;
  await user.click(within(row).getByRole('button', { name: '换个邮箱或工号' }));
  expect(
    await screen.findByRole('dialog', { name: '张总的企业邮箱或工号' }),
  ).toBeInTheDocument();
});

it('lists a recording whose speakers have no voice to group by, and goes to it to settle them', async () => {
  server.unsorted = [
    { recording_id: 'rec_1', filename: '周会.m4a', speakers: 1, total: 3 },
  ];
  view('/inbox?cat=unsorted');
  const tasks = await screen.findByRole('list', { name: '还没认人' });
  expect(within(tasks).getByText('还有 1 位没认')).toBeVisible();
  expect(
    within(tasks).getByRole('link', { name: '试听并确认' }),
  ).toHaveAttribute('href', '/library/rec_1');
});

it('says nothing waits when nothing does, and offers no kinds', async () => {
  view();
  expect(await screen.findByText('现在没有需要你处理的事。')).toBeVisible();
  expect(screen.queryByRole('group', { name: '类别' })).toBeNull();
  expect(screen.queryByRole('radio', { name: '逐个听' })).toBeNull();
});

it('counts only what asks for the owner: not queued, proofread or organising work', async () => {
  server.people = [
    fresh({ id: 'new', seconds: 600 }),
    person({ id: 'known', name: '张总', persona_id: 'p-1', updating: true }),
  ];
  server.recordings = [
    { id: 'f', filename: '周会.m4a', status: 'failed', error: '识别失败' },
    { id: 'q', filename: '排队.m4a', status: 'queued' },
    { id: 'p', filename: '校对.m4a', status: 'ready', proofread: 'waiting' },
  ];
  view();
  const kinds = await screen.findByRole('group', { name: '类别' });
  expect(
    within(kinds)
      .getAllByRole('button')
      .map((b) => b.textContent),
  ).toEqual(['新的声音1', '转写失败1']);
});

it('retries a failed recording through its own endpoint, and it leaves what waits', async () => {
  const user = userEvent.setup();
  server.recordings = [
    { id: 'f', filename: '周会.m4a', status: 'failed', error: '识别失败' },
  ];
  view('/inbox?cat=failed');
  await user.click(await screen.findByRole('button', { name: '重试' }));
  await waitFor(() =>
    expect(posted('/api/library/recordings/f/retry')).toHaveLength(1),
  );
  expect(await screen.findByText('现在没有需要你处理的事。')).toBeVisible();
});

it('ignores an older failure of the queue after a newer load has come', async () => {
  const real = fetch;
  let fail!: (error: Error) => void;
  const older = new Promise<Response>((_, reject) => {
    fail = reject;
  });
  let reviews = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) =>
      url.startsWith('/api/library/review') && ++reviews === 1
        ? older
        : real(url, init),
    ),
  );
  view();
  await waitFor(() => expect(reviews).toBe(1));
  // The recordings changed meanwhile: the page asks again, and that answer comes first.
  act(() => useTeam.setState((state) => ({ version: state.version + 1 })));
  expect(await screen.findByText('现在没有需要你处理的事。')).toBeVisible();
  await act(async () => {
    fail(new Error('older request failed'));
  });
  expect(screen.queryByRole('alert')).toBeNull();
  expect(screen.getByText('现在没有需要你处理的事。')).toBeVisible();
});

it('keeps the dialog and what was typed when the e-mail or employee number is not saved, and closes it when it is', async () => {
  const user = userEvent.setup();
  server.people = [person({ persona_id: 'p-1' })];
  usePersonas.setState({
    items: [
      twinOf({ claimed: false, claim: 'old@x.cn', claim_rejected: 'old@x.cn' }),
    ],
  });
  server.claim = 409;
  view('/inbox?cat=disowned');
  await user.click(
    await screen.findByRole('button', { name: '换个邮箱或工号' }),
  );
  const dialog = await screen.findByRole('dialog', {
    name: '张总的企业邮箱或工号',
  });
  const field = within(dialog).getByLabelText('企业邮箱或工号');
  await user.clear(field);
  await user.type(field, 'taken@x.cn');
  await user.click(within(dialog).getByRole('button', { name: '保存' }));
  // Said where the owner is looking, with the dialog still open on what was typed.
  expect(await within(dialog).findByRole('alert')).toHaveTextContent(
    '这个邮箱或工号已经用在另一个分身上',
  );
  expect(posted('/api/personas/p-1/claim')[0]).toMatchObject({
    method: 'PUT',
    body: { claim: 'taken@x.cn' },
  });
  expect(dialog).toBeInTheDocument();
  expect(field).toHaveValue('taken@x.cn');
  // Another try that is saved closes it.
  server.claim = 200;
  await user.click(within(dialog).getByRole('button', { name: '保存' }));
  await waitFor(() =>
    expect(
      screen.queryByRole('dialog', { name: '张总的企业邮箱或工号' }),
    ).toBeNull(),
  );
  expect(posted('/api/personas/p-1/claim')).toHaveLength(2);
});

it('does not ask a transcript brought in as text to be heard', async () => {
  server.recordings = [
    { id: 'rec_t', filename: '纪要.txt', kind: 'transcript', status: 'ready' },
    { id: 'rec_a', filename: '周会.m4a', kind: 'audio', status: 'ready' },
  ];
  server.unsorted = [
    { recording_id: 'rec_t', filename: '纪要.txt', speakers: 2, total: 2 },
    { recording_id: 'rec_a', filename: '周会.m4a', speakers: 1, total: 3 },
  ];
  view('/inbox?cat=unsorted');
  const tasks = await screen.findByRole('list', { name: '还没认人' });
  const rows = within(tasks).getAllByRole('listitem');
  expect(within(rows[0]).getByRole('link', { name: '确认' })).toHaveAttribute(
    'href',
    '/library/rec_t',
  );
  expect(
    within(rows[1]).getByRole('link', { name: '试听并确认' }),
  ).toHaveAttribute('href', '/library/rec_a');
});

it('shows on the page why an answer was not kept while the owner is still there', async () => {
  const user = clock();
  server.voices = [
    voice('a', {
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
  ];
  server.voicesStatus = 409;
  view();
  await user.click(await screen.findByRole('button', { name: '归给张总' }));
  await later();
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '这个声音刚被别人处理过了',
  );
  expect(screen.queryByText(/刚才的答案没有记下/u)).toBeNull();
});

it('says on its own that an answer given before the page was left was not kept', async () => {
  const user = clock();
  server.voices = [
    voice('a', {
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
  ];
  server.voicesStatus = 409;
  // The page that told it is gone, so the notice cannot be on it.
  render(<ToastViewport />);
  const shown = view();
  await user.click(await screen.findByRole('button', { name: '归给张总' }));
  shown.unmount();
  expect(
    (await screen.findAllByText('刚才的答案没有记下：这个声音刚被别人处理过了'))
      .length,
  ).toBeGreaterThan(0);
});

const sureVoice = (id: string, speaker: string, extra = {}) =>
  voice(id, {
    members: [member('rec_1', speaker, 300)],
    candidates: [
      { person_id: 'per_1', name: '张总', score: 0.9, sure: true },
      { person_id: 'per_2', name: '李总', score: 0.3 },
    ],
    ...extra,
  });

it('answers the sure name with Enter and hears the previous recording with ←, in the one-by-one view', async () => {
  const user = clock();
  server.voices = [
    voice('a', {
      seconds: 600,
      members: [member('rec_1', 'S1', 300), member('rec_2', 'S3', 300)],
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
    sureVoice('b', 'S2', { seconds: 100 }),
  ];
  view('/inbox?view=focus');
  const heard = await screen.findByRole('region', { name: '这个声音' });
  expect(heard.querySelector('audio')).toHaveAttribute(
    'src',
    '/api/library/recordings/rec_1/speakers/S1/samples/0',
  );
  // From the first recording back to the last.
  await user.keyboard('{ArrowLeft}');
  expect(heard.querySelector('audio')).toHaveAttribute(
    'src',
    '/api/library/recordings/rec_2/speakers/S3/samples/0',
  );
  await user.keyboard('{ArrowRight}');
  expect(heard.querySelector('audio')).toHaveAttribute(
    'src',
    '/api/library/recordings/rec_1/speakers/S1/samples/0',
  );
  // Nothing is sure for the first voice: Enter leaves it be. Then 1 answers it, and Enter the sure name of the next.
  await user.keyboard('{Enter}');
  expect(screen.getByText('1 / 2')).toBeVisible();
  await user.keyboard('1');
  expect(await screen.findByText('2 / 2')).toBeVisible();
  await user.keyboard('{Enter}');
  expect(await screen.findByText('新的声音都处理完了')).toBeVisible();
  expect(screen.getByText('已归给张总')).toBeVisible();
});

it('tells the keys of the one-by-one view, Enter among them', async () => {
  const user = userEvent.setup();
  server.voices = [voice('a')];
  view('/inbox?view=focus');
  await user.hover(await screen.findByRole('button', { name: '快捷键' }));
  expect(await screen.findAllByText(/Enter 确认/u)).not.toHaveLength(0);
});

it('keeps the voice in front, and a name half typed, while new recordings change what the voices are', async () => {
  const user = userEvent.setup();
  server.voices = [
    voice('a', { seconds: 300, members: [member('rec_1', 'S1', 300)] }),
    voice('b', { seconds: 200, members: [member('rec_2', 'S2', 200)] }),
  ];
  view('/inbox?view=focus');
  await screen.findByText('1 / 2');
  const field = screen.getByLabelText('都不是，输入名字');
  await user.type(field, '王');
  // A recording now has the first voice in it too, and a third voice, heard in two recordings, outranks both.
  server.voices = [
    voice('c', {
      seconds: 900,
      members: [member('rec_5', 'S5', 450), member('rec_6', 'S6', 450)],
    }),
    voice('a2', {
      seconds: 400,
      members: [member('rec_1', 'S1', 300), member('rec_9', 'S9', 100)],
    }),
    voice('b', { seconds: 200, members: [member('rec_2', 'S2', 200)] }),
  ];
  act(() => useTeam.setState((state) => ({ version: state.version + 1 })));
  await waitFor(() => expect(screen.getByText('1 / 3')).toBeVisible());
  expect(screen.getByText('rec_1.m4a')).toBeVisible();
  expect(screen.getByLabelText('都不是，输入名字')).toHaveValue('王');
  expect(screen.queryByText('rec_5.m4a')).toBeNull();
});

const recordingStub = () => {
  const real = fetch;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/recordings/rec_1')
        return json({
          id: 'rec_1',
          filename: '周会.m4a',
          status: 'ready',
          transcript_id: 't1',
          revision: 3,
          speakers: [speaker({}), speaker({ id: 'S2' })],
          segments: [
            { start: 0, end: 4, text: '先看预算。', speaker: 'S1' },
            { start: 4, end: 9, text: '我反对压缩研发。', speaker: 'S2' },
          ],
        });
      if (url.startsWith('/api/library/recordings/rec_1/speakers/')) {
        server.voices = server.voices.filter((v) => v.id !== 'b');
        return json({ revision: 4, person_id: 'per_1' });
      }
      return real(url, init);
    }),
  );
};

it('names which recording of a voice heard in several it opens, in the list and in the one-by-one view, and says how many more wait there', async () => {
  const user = userEvent.setup();
  server.voices = [
    voice('a', {
      members: [member('rec_2', 'S3', 200), member('rec_1', 'S2', 300)],
      seconds: 500,
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
  ];
  recordingStub();
  const shown = view();
  await user.click(await screen.findByLabelText(/^更多：/u));
  await user.click(screen.getByRole('button', { name: '换一段（1/2）' }));
  await user.click(screen.getByLabelText(/^更多：/u));
  // The one heard now is the second: the menu says so.
  expect(screen.getByRole('button', { name: '打开第 2 段' })).toBeVisible();
  await user.keyboard('{Escape}');
  shown.unmount();

  view('/inbox?view=focus');
  const heard = await screen.findByRole('region', { name: '这个声音' });
  await user.keyboard('{ArrowRight}');
  expect(heard.querySelector('audio')).toHaveAttribute(
    'src',
    '/api/library/recordings/rec_1/speakers/S2/samples/0',
  );
  await user.click(screen.getByLabelText('更多'));
  await user.click(screen.getByRole('button', { name: '打开第 2 段' }));
  expect(
    await screen.findByRole('heading', { name: 'S2 是谁？' }),
  ).toBeVisible();
  expect(screen.getByText(/这个声音还出现在另外 1\s+段录音里/u)).toBeVisible();
});

it('does not say an unnamed person is heard elsewhere: only a voice heard in several recordings is settled across them', async () => {
  const user = userEvent.setup();
  server.people = [
    person({}),
    fresh({ id: 'new', speakers: 3, recording_id: 'rec_1', speaker_id: 'S2' }),
  ];
  recordingStub();
  view();
  await user.click(await screen.findByLabelText(/^更多：未命名 1/u));
  await user.click(screen.getByRole('button', { name: '打开录音' }));
  expect(
    await screen.findByRole('heading', { name: 'S2 是谁？' }),
  ).toBeVisible();
  expect(screen.queryByText(/这个声音还出现在另外/u)).toBeNull();
});

it('plays the voices as recorded, in the list and in the one-by-one view, when the owner chose the original', async () => {
  const { useListening } = await import('../stores/listening');
  useListening.setState({ original: true });
  try {
    server.voices = [sureVoice('a', 'S1')];
    const shown = view();
    const list = await screen.findByRole('list', { name: '新的声音' });
    expect(list.querySelector('audio')).toHaveAttribute(
      'src',
      '/api/library/recordings/rec_1/speakers/S1/samples/0?original=true',
    );
    shown.unmount();
    view('/inbox?view=focus');
    const heard = await screen.findByRole('region', { name: '这个声音' });
    expect(heard.querySelector('audio')).toHaveAttribute(
      'src',
      '/api/library/recordings/rec_1/speakers/S1/samples/0?original=true',
    );
  } finally {
    useListening.setState({ original: false });
  }
});

it('leads the old team address to the inbox through the page the team address really is', async () => {
  const { Home } = await import('../pages/Home');
  server.recordings = [
    { id: 'f', filename: '周会.m4a', status: 'failed', error: '识别失败' },
  ];
  render(
    <MemoryRouter initialEntries={['/team?tab=todo&cat=failed']}>
      <TooltipProvider>
        <ConfirmProvider>
          <Routes>
            <Route path="/team" element={<Home />} />
            <Route path="/inbox" element={<Where />} />
          </Routes>
        </ConfirmProvider>
      </TooltipProvider>
    </MemoryRouter>,
  );
  expect(await screen.findByText('在/inbox?cat=failed')).toBeVisible();
});

it('returns from a recording opened in the one-by-one view to that view, with the run kept', async () => {
  const user = clock();
  server.voices = [
    voice('a', {
      seconds: 400,
      members: [member('rec_1', 'S1', 400)],
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
    voice('b', {
      seconds: 300,
      members: [member('rec_1', 'S2', 300)],
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
    voice('c', { seconds: 200, members: [member('rec_1', 'S3', 200)] }),
  ];
  recordingStub();
  view('/inbox?view=focus');
  expect(await screen.findByText('1 / 3')).toBeVisible();
  await user.click(screen.getByRole('button', { name: '是张总' }));
  expect(await screen.findByText('2 / 3')).toBeVisible();
  await user.click(screen.getByLabelText('更多'));
  await user.click(screen.getByRole('button', { name: '打开录音' }));
  const card = (
    await screen.findByRole('heading', { name: 'S2 是谁？' })
  ).closest('section')!;
  await user.selectOptions(within(card).getByLabelText('这是谁'), 'per_1');
  await user.click(screen.getByRole('button', { name: '确认是张总' }));
  // Still the voices one by one, on the next, with the two answered counted.
  expect(await screen.findByText('3 / 3')).toBeVisible();
  expect(screen.getByRole('heading', { name: '这是谁？' })).toBeVisible();
});

it('puts the keys on the row after the one settled in its recording, not the first', async () => {
  server.voices = [
    voice('a', {
      seconds: 400,
      members: [member('rec_1', 'S1', 400)],
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
    voice('b', {
      seconds: 300,
      members: [member('rec_1', 'S2', 300)],
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
    }),
    voice('c', { seconds: 200, members: [member('rec_1', 'S3', 200)] }),
  ];
  recordingStub();
  view();
  const user = userEvent.setup();
  await screen.findByRole('list', { name: '新的声音' });
  await user.click((await screen.findAllByLabelText(/^更多：/u))[1]);
  await user.click(screen.getAllByRole('button', { name: '打开录音' })[1]);
  const card = (
    await screen.findByRole('heading', { name: 'S2 是谁？' })
  ).closest('section')!;
  await user.selectOptions(within(card).getByLabelText('这是谁'), 'per_1');
  await user.click(screen.getByRole('button', { name: '确认是张总' }));
  // The third has no names to offer: the field for one is where the keys go.
  await waitFor(() =>
    expect(screen.getByLabelText(/^没听过的声音（.+），是谁$/u)).toHaveFocus(),
  );
});
