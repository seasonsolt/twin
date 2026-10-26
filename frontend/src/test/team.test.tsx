import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider, ToastViewport } from '../components/ui';
import { Team } from '../features/library/Team';
import { Recording, type Person, type Speaker } from '../pages/Recording';
import type { Recording as LibraryRecording } from '../pages/Library';
import { useNewTwinCard } from '../components/layout/NewTwin';
import { usePersonas, type Persona } from '../stores/personas';
import { useAuth } from '../stores/auth';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
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
let revision: number;
let people: Person[];
let puts: Record<string, unknown>[];
beforeEach(() => {
  revision = 3;
  people = [person({}), person({ id: 'per_2', name: '李总' })];
  puts = [];
  usePersonas.setState({ items: [] });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url === '/api/library/recordings/rec_1')
        return json({
          id: 'rec_1',
          filename: '周会.m4a',
          status: 'ready',
          transcript_id: 't1',
          revision,
          speakers: [
            speaker({
              candidates: [{ person_id: 'per_1', name: '张总', score: 0.82 }],
            }),
            speaker({ id: 'S2', decision: 'confirmed', person_id: 'per_2' }),
            speaker({
              id: 'S3',
              decision: 'confirmed',
              person_id: 'per_1',
              auto: true,
            }),
          ],
          segments: [
            { start: 0, end: 4, text: '先看预算。', speaker: 'S1' },
            { start: 4, end: 9, text: '我反对压缩研发。', speaker: 'S2' },
          ],
        });
      if (url.startsWith('/api/library/recordings/rec_1/speakers/')) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        puts.push({ url, ...body });
        if (body.revision !== revision)
          return json({ detail: '这段录音刚被修改过，请刷新后再确认' }, 409);
        revision += 1;
        return json({ revision, person_id: body.person_id ?? null });
      }
      throw new Error(url);
    }),
  );
});
afterEach(() => {
  vi.restoreAllMocks();
  useAuth.setState({ identity: null });
});

const emptyReview = { items: [], voices: [], fragments: [], unsorted: [] };
/** Where the page went: the chat names the twin it opens on. */
function Address() {
  const { pathname, search } = useLocation();
  return <output aria-label="地址">{pathname + search}</output>;
}

const teamView = (version = 0) => (
  <MemoryRouter>
    <ConfirmProvider>
      <Team version={version} recordings={[]} />
      <Address />
    </ConfirmProvider>
  </MemoryRouter>
);

function mockScrolling() {
  const watches: {
    notify: IntersectionObserverCallback;
    target?: Element;
    observer: IntersectionObserver;
    disconnected: boolean;
  }[] = [];
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      private watch: (typeof watches)[number];
      constructor(notify: IntersectionObserverCallback) {
        this.watch = {
          notify,
          observer: this as unknown as IntersectionObserver,
          disconnected: false,
        };
        watches.push(this.watch);
      }
      observe(target: Element) {
        this.watch.target = target;
      }
      disconnect() {
        this.watch.disconnected = true;
      }
    },
  );
  return (label: string) => {
    const watch = [...watches]
      .reverse()
      .find((item) => !item.disconnected && item.target?.textContent === label);
    expect(watch, `active scroll trigger: ${label}`).toBeDefined();
    watch!.notify(
      [{ isIntersecting: true } as IntersectionObserverEntry],
      watch!.observer,
    );
  };
}

it('pages people on scroll, searches the whole roster, and keeps the expanded list through refresh', async () => {
  const scrollTo = mockScrolling();
  people = Array.from({ length: 41 }, (_, i) =>
    person({
      id: `person-${i}`,
      name: `人物${String(i + 1).padStart(2, '0')}`,
      seconds: 5000 - i,
    }),
  );
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      throw new Error(url);
    }),
  );
  const view = render(teamView());
  await screen.findByText('人物01', { selector: 'p' });
  // One row per person under the table's header row.
  const panel = () => within(screen.getByRole('tabpanel', { name: /成员/u }));
  expect(panel().getAllByRole('row')).toHaveLength(19);
  expect(
    screen.queryByText('人物41', { selector: 'p' }),
  ).not.toBeInTheDocument();
  await userEvent.type(screen.getByRole('textbox', { name: '找人' }), '人物41');
  expect(panel().getAllByRole('row')).toHaveLength(2);
  expect(screen.getByText('人物41', { selector: 'p' })).toBeVisible();
  await userEvent.clear(screen.getByRole('textbox', { name: '找人' }));
  expect(panel().getAllByRole('row')).toHaveLength(19);
  act(() => scrollTo('继续加载人物'));
  expect(panel().getAllByRole('row')).toHaveLength(37);
  view.rerender(teamView(1));
  await waitFor(() => expect(panel().getAllByRole('row')).toHaveLength(37));
  act(() => scrollTo('继续加载人物'));
  expect(panel().getAllByRole('row')).toHaveLength(42);
  expect(
    screen.queryByRole('button', { name: '继续加载人物' }),
  ).not.toBeInTheDocument();
});

const showRecording = () =>
  render(
    <MemoryRouter initialEntries={['/library/rec_1']}>
      <Routes>
        <Route path="/library/:recordingId" element={<Recording />} />
      </Routes>
    </MemoryRouter>,
  );

it('lets the owner hear a speaker and confirm who it is, without picking for them', async () => {
  showRecording();
  const card = (
    await screen.findByRole('heading', { name: 'S1 是谁？' })
  ).closest('section')!;
  const scope = within(card);
  expect(scope.getAllByLabelText(/S1 试听/u)).toHaveLength(1);
  expect(scope.getByText('声音像 82%')).toBeInTheDocument();
  // A voice match is only a hint: nothing is chosen until the owner chooses.
  expect(scope.getByLabelText('这是谁')).toHaveValue('');
  expect(screen.getByRole('button', { name: '先选一个人' })).toBeDisabled();
  await userEvent.selectOptions(scope.getByLabelText('这是谁'), 'per_1');
  await userEvent.click(screen.getByLabelText(/用作这个人的声纹样本/u));
  await userEvent.click(screen.getByRole('button', { name: '确认是张总' }));
  await waitFor(() => expect(puts).toHaveLength(1));
  expect(puts[0]).toMatchObject({
    url: '/api/library/recordings/rec_1/speakers/S1',
    transcript_id: 't1',
    revision: 3,
    action: 'confirm',
    person_id: 'per_1',
    sample: true,
  });
  // The transcript names confirmed speakers.
  expect(screen.getByText(/李总：/u)).toBeInTheDocument();
});

it('refuses a decision on an outdated page and reloads it', async () => {
  showRecording();
  await screen.findByRole('heading', { name: 'S1 是谁？' });
  revision = 4; // Changed elsewhere meanwhile.
  await userEvent.click(screen.getByRole('button', { name: '几个人混在一起' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('请刷新后再确认');
  await userEvent.click(screen.getByRole('button', { name: '不在名单里' }));
  await waitFor(() => expect(puts).toHaveLength(2));
  expect(puts[1]).toMatchObject({
    revision: 4,
    action: 'unknown',
  });
});

it('creates a twin for a confirmed person and shows when its memory is updating', async () => {
  const created: unknown[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({
          items: [],
          voices: [
            {
              id: 'voice_1',
              members: [
                {
                  recording_id: 'rec_9',
                  filename: '月会.m4a',
                  transcript_id: 't9',
                  speaker_id: 'S1',
                  seconds: 30,
                },
              ],
              seconds: 30,
              candidates: [
                { person_id: 'per_1', name: '张总', score: 0.8, sure: true },
              ],
              near: false,
            },
          ],
          fragments: [],
          unsorted: [],
        });
      if (
        url === '/api/library/people/per_1/persona' &&
        init?.method === 'POST'
      ) {
        created.push(JSON.parse(String(init.body)));
        people = [
          person({
            persona_id: 'p-1',
            updating: true,
            build: {
              state: 'running',
              progress: {
                phase: 'merge',
                done: 406,
                total: 406,
                merged: 30,
                to_merge: 130,
              },
            },
          }),
          people[1],
        ];
        return json({ persona_id: 'p-1', new: true });
      }
      if (url === '/api/personas') return json({ items: [], default: null });
      throw new Error(url);
    }),
  );
  render(teamView());
  const row = (await screen.findByText('张总', { selector: 'p' })).closest(
    'tr',
  )!;
  expect(within(row).getByText('没有分身')).toBeInTheDocument();
  await userEvent.click(within(row).getByRole('button', { name: '生成分身' }));
  // Made for 张总's work e-mail (or employee number): they take it when they sign in.
  const dialog = await screen.findByRole('dialog', { name: '为张总建分身' });
  await userEvent.type(
    within(dialog).getByRole('textbox', { name: /企业邮箱或工号/u }),
    'zhang@acme.cn',
  );
  await userEvent.click(within(dialog).getByRole('button', { name: '建好' }));
  expect(await screen.findByText('整理中')).toBeInTheDocument();
  // Until it can talk, the row shows the step the update is on and how far it has gone.
  expect(
    await screen.findByRole('progressbar', {
      name: '第 2/3 步 · 合并成记忆',
      // The dialog is still fading out over the page.
      hidden: true,
    }),
  ).toHaveAttribute('aria-valuenow', '30');
  expect(screen.getByText('23%')).toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: '聊天' }),
  ).not.toBeInTheDocument();
  // Nothing to talk to yet: the row offers their page instead.
  const updating = screen.getByText('张总', { selector: 'p' }).closest('tr')!;
  expect(
    within(updating).getByRole('button', { name: '查看', hidden: true }),
  ).toBeInTheDocument();
  expect(created).toEqual([{ claim: 'zhang@acme.cn' }]);
});

it('marks automatic matches and reopens them through the existing clear action', async () => {
  showRecording();
  await screen.findByRole('heading', { name: 'S1 是谁？' });
  const row = screen.getByRole('button', { name: '改 S3' }).closest('li')!;
  expect(within(row).getByText('按声音自动认出')).toBeInTheDocument();
  await userEvent.click(within(row).getByRole('button', { name: '改 S3' }));
  await waitFor(() => expect(puts).toHaveLength(1));
  expect(puts[0]).toMatchObject({
    url: '/api/library/recordings/rec_1/speakers/S3',
    action: 'clear',
  });
});

it('edits a person name and gender and opens the member page of their twin', async () => {
  const patches: unknown[] = [];
  const switched: string[] = [];
  people = [person({ persona_id: 'p-1' })];
  usePersonas.setState({
    items: [
      {
        id: 'p-1',
        name: '张总',
        avatar_url: null,
        avatar_preset: 'stone',
        sources: 1,
        created_at: '',
        is_default: false,
      },
    ],
    switchTo: async (id: string) => {
      switched.push(id);
    },
    refresh: async () => {},
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices: [], fragments: [], unsorted: [] });
      if (url === '/api/library/people/per_1' && init?.method === 'PATCH') {
        patches.push(JSON.parse(String(init.body)));
        people = [
          person({ persona_id: 'p-1', name: '张总监', gender: 'male' }),
        ];
        return json({ updated: true });
      }
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter initialEntries={['/team']}>
      <ConfirmProvider>
        <Routes>
          <Route path="/team" element={<Team version={0} recordings={[]} />} />
          <Route path="/team/:id" element={<p>成员页</p>} />
        </Routes>
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const row = (await screen.findByText('张总', { selector: 'p' })).closest(
    'tr',
  )!;
  // The twin's own illustration stands for them.
  expect(
    within(row).getByRole('img', { name: '插画形象：石', hidden: true }),
  ).toBeInTheDocument();
  await userEvent.click(within(row).getByLabelText('张总的更多操作'));
  expect(within(row).queryByRole('button', { name: '删除成员' })).toBeNull();
  await userEvent.click(within(row).getByRole('button', { name: '编辑资料' }));
  const dialog = await screen.findByRole('dialog', { name: '编辑「张总」' });
  await userEvent.clear(within(dialog).getByLabelText('名字'));
  await userEvent.type(within(dialog).getByLabelText('名字'), '张总监');
  await userEvent.click(within(dialog).getByLabelText('男'));
  await userEvent.click(within(dialog).getByRole('button', { name: '保存' }));
  await waitFor(() =>
    expect(patches).toEqual([{ name: '张总监', gender: 'male' }]),
  );
  expect(
    await screen.findByText('张总监', { selector: 'p' }),
  ).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  await userEvent.click(screen.getByRole('link', { name: '张总监的成员页' }));
  expect(await screen.findByText('成员页')).toBeInTheDocument();
  // The member page switches to the twin itself: the roster only goes there.
  expect(switched).toEqual([]);
});

it('searches people locally, edits them from the menu, and keeps deletion there', async () => {
  const calls: string[] = [];
  const originalFetch = fetch;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(url);
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices: [], fragments: [], unsorted: [] });
      return originalFetch(url, init);
    }),
  );
  render(
    <MemoryRouter>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  await screen.findByRole('link', { name: '张总的成员页' });
  const beforeSearch = calls.length;
  await userEvent.type(screen.getByRole('textbox', { name: '找人' }), '李');
  expect(screen.queryByRole('link', { name: '张总的成员页' })).toBeNull();
  expect(
    screen.getByRole('link', { name: '李总的成员页' }),
  ).toBeInTheDocument();
  expect(calls).toHaveLength(beforeSearch);
  await userEvent.click(screen.getByLabelText('李总的更多操作'));
  await userEvent.click(screen.getByRole('button', { name: '编辑资料' }));
  expect(
    await screen.findByRole('dialog', { name: '编辑「李总」' }),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: '取消' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  await userEvent.click(screen.getByLabelText('李总的更多操作'));
  // Deleting is set apart, last, in the danger colour.
  const remove = screen.getByRole('button', { name: '删除成员' });
  expect(remove).toHaveClass('text-danger');
  expect(remove.previousElementSibling?.tagName).toBe('HR');
  // Nobody of that name: the table says so instead of going blank.
  await userEvent.clear(screen.getByRole('textbox', { name: '找人' }));
  await userEvent.type(screen.getByRole('textbox', { name: '找人' }), '赵');
  expect(await screen.findByText('没有符合的人')).toBeInTheDocument();
  expect(screen.queryByRole('table')).toBeNull();
});

it('makes twins for several colleagues by e-mail or employee number, and shows one handed back', async () => {
  people = [
    person({}),
    person({ id: 'per_2', name: '李总', persona_id: 'p-li' }),
    person({ id: 'per_3', name: '王总', persona_id: 'p-wang' }),
  ];
  usePersonas.setState({
    items: [
      {
        id: 'p-li',
        name: '李总',
        avatar_url: null,
        sources: 1,
        created_at: 'x',
        is_default: false,
        claim: null,
        claimed: false,
      },
      {
        id: 'p-wang',
        name: '王总',
        avatar_url: null,
        sources: 1,
        created_at: 'x',
        is_default: false,
        claim: null,
        claimed: false,
        claim_rejected: 'wang@acme.cn',
      },
    ],
  });
  const sent: [string, string | undefined, unknown][] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices: [], fragments: [], unsorted: [] });
      if (url === '/api/personas') return json(usePersonas.getState().items);
      sent.push([url, init?.method, JSON.parse(String(init?.body))]);
      if (url === '/api/personas/p-li/claim')
        return json({ detail: '这个邮箱或工号已经用在另一个分身上' }, 409);
      return json({ persona_id: 'p-zhang', new: true });
    }),
  );
  render(teamView());
  // A twin not taken yet can be bound to an account from its row, which says it is not.
  const li = (
    await screen.findByRole('link', { name: '李总的成员页' })
  ).closest('tr')!;
  expect(
    within(li).getByRole('button', { name: '绑定企业账号 未绑定' }),
  ).toBeInTheDocument();
  const zhang = screen
    .getByRole('link', { name: '张总的成员页' })
    .closest('tr')!;
  expect(
    within(zhang).queryByRole('button', { name: /绑定企业账号/u }),
  ).toBeNull();
  await userEvent.click(await screen.findByText('添加'));
  await userEvent.click(
    screen.getByRole('button', { name: '批量建分身（3）' }),
  );
  const dialog = await screen.findByRole('dialog', { name: '为同事建分身' });
  expect(
    within(dialog).getByText('wang@acme.cn 说不是 TA，换一个'),
  ).toBeInTheDocument();
  await userEvent.type(
    within(dialog).getByRole('textbox', { name: '张总 · 1 段录音' }),
    'zhang@acme.cn',
  );
  await userEvent.type(
    within(dialog).getByRole('textbox', { name: '李总 · 1 段录音' }),
    '12345',
  );
  await userEvent.click(
    within(dialog).getByRole('button', { name: '为 2 位同事建分身' }),
  );
  await waitFor(() =>
    expect(sent).toEqual([
      ['/api/library/people/per_1/persona', 'POST', { claim: 'zhang@acme.cn' }],
      ['/api/personas/p-li/claim', 'PUT', { claim: '12345' }],
    ]),
  );
  // The one that did not go through stays, with why; the rest leave the list.
  expect(
    await within(dialog).findByText('这个邮箱或工号已经用在另一个分身上'),
  ).toBeInTheDocument();
  expect(
    within(dialog).getByRole('textbox', { name: '李总 · 1 段录音' }),
  ).toHaveValue('12345');
  expect(
    within(dialog).getByRole('textbox', { name: '张总 · 1 段录音' }),
  ).toHaveValue('');
});

it('keeps the dialog and what was typed when the e-mail of a twin to make is not saved', async () => {
  let taken = true;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices: [], fragments: [], unsorted: [] });
      if (url === '/api/personas') return json({ items: [], default: null });
      if (url === '/api/library/people/per_1/persona')
        return taken
          ? json({ detail: '这个邮箱或工号已经用在另一个分身上' }, 409)
          : json({ persona_id: 'p-1', new: true });
      throw new Error(url);
    }),
  );
  render(teamView());
  const row = (await screen.findByText('张总', { selector: 'p' })).closest(
    'tr',
  )!;
  await userEvent.click(within(row).getByRole('button', { name: '生成分身' }));
  const dialog = await screen.findByRole('dialog', { name: '为张总建分身' });
  const field = within(dialog).getByRole('textbox', {
    name: /企业邮箱或工号/u,
  });
  await userEvent.type(field, 'taken@acme.cn');
  await userEvent.click(within(dialog).getByRole('button', { name: '建好' }));
  expect(await within(dialog).findByRole('alert')).toHaveTextContent(
    '这个邮箱或工号已经用在另一个分身上',
  );
  expect(field).toHaveValue('taken@acme.cn');
  // Another try that goes through closes it.
  taken = false;
  await userEvent.click(within(dialog).getByRole('button', { name: '建好' }));
  await waitFor(() =>
    expect(screen.queryByRole('dialog', { name: '为张总建分身' })).toBeNull(),
  );
});

it('lets an administrator point a taken twin at another account, after saying what its person loses', async () => {
  people = [person({ persona_id: 'p-zhang' })];
  const taken: Persona = {
    id: 'p-zhang',
    name: '张总',
    avatar_url: null,
    sources: 1,
    created_at: 'x',
    is_default: false,
    claim: '12345',
    claimed: true,
  };
  usePersonas.setState({ items: [taken] });
  const sent: [string, string | undefined, unknown][] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      if (url === '/api/library/voice-clashes') return json([]);
      if (url === '/api/personas') return json([taken]);
      sent.push([url, init?.method, JSON.parse(String(init?.body))]);
      return json(taken);
    }),
  );
  render(teamView());
  const row = (
    await screen.findByRole('link', { name: '张总的成员页' })
  ).closest('tr')!;
  // Only an administrator may take it from its person.
  expect(within(row).queryByRole('button', { name: /企业账号/u })).toBeNull();
  act(() =>
    useAuth.setState({
      identity: { email: 'admin@example.com', admin: true, auth_enabled: true },
    }),
  );
  await userEvent.click(
    await within(row).findByRole('button', { name: '改绑企业账号 已认领' }),
  );
  const dialog = await screen.findByRole('dialog', {
    name: '张总的企业邮箱或工号',
  });
  const field = within(dialog).getByLabelText('企业邮箱或工号');
  await userEvent.clear(field);
  await userEvent.type(field, '67890');
  await userEvent.click(within(dialog).getByRole('button', { name: '保存' }));
  const asked = await screen.findByRole('dialog', {
    name: '改绑这个分身？',
  });
  expect(sent).toEqual([]);
  await userEvent.click(within(asked).getByRole('button', { name: '改绑' }));
  await waitFor(() =>
    expect(sent).toEqual([
      ['/api/personas/p-zhang/claim', 'PUT', { claim: '67890' }],
    ]),
  );
});

it('shows a person who found themselves by voice as having their own twin', async () => {
  people = [person({ self_claimed: true }), people[1]!];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices: [], fragments: [], unsorted: [] });
      if (url === '/api/personas') return json([]);
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const name = await screen.findByText('张总', { selector: 'p' });
  const row = name.closest('tr')!;
  // Their twin is theirs, not the library's to open: the row says so and offers nothing to do.
  expect(within(row).getByText('本人已认领')).toBeInTheDocument();
  expect(within(row).queryByRole('button', { name: '聊天' })).toBeNull();
  expect(within(row).queryByRole('button', { name: '生成分身' })).toBeNull();
  expect(within(row).queryByRole('link', { name: '张总的档案' })).toBeNull();
});

it('keeps listening to a person out of their row, which has one thing to do and the menu', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      throw new Error(url);
    }),
  );
  render(teamView());
  await screen.findByText('张总', { selector: 'p' });
  expect(
    within(screen.getByRole('tabpanel')).queryByRole('button', {
      name: /确认过的声音/u,
    }),
  ).toBeNull();
  expect(screen.queryByText(/段可抽查/u)).toBeNull();
  await userEvent.click(screen.getByLabelText('张总的更多操作'));
  const row = screen.getByRole('link', { name: '张总的成员页' }).closest('tr')!;
  expect(within(row).getByRole('button', { name: '抽查声线' })).toBeVisible();
});

it('has no voice to check for someone only a twin was made for, and writes no recordings of them', async () => {
  people = [person({ speakers: 0, seconds: 0 })];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      throw new Error(url);
    }),
  );
  render(teamView());
  const row = (
    await screen.findByRole('link', { name: '张总的成员页' })
  ).closest('tr')!;
  expect(within(row).queryByText(/段 ·/u)).toBeNull();
  expect(within(row).queryByText(/分钟/u)).toBeNull();
  await userEvent.click(within(row).getByLabelText('张总的更多操作'));
  expect(screen.getByRole('button', { name: '编辑资料' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /抽查声线/u })).toBeNull();
});

it('keeps off the roster people the viewer neither looks after nor can talk to', async () => {
  people = [
    person({}),
    person({ id: 'per_3', name: '王五', can_manage: false }),
  ];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      throw new Error(url);
    }),
  );
  render(teamView());
  await screen.findByText('张总', { selector: 'p' });
  expect(screen.queryByText('王五', { selector: 'p' })).toBeNull();
});

it('leads the old tab of what waits to the inbox, which has its own place now', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => json({ items: [] })),
  );
  render(
    <MemoryRouter initialEntries={['/team?tab=todo']}>
      <ConfirmProvider>
        <Routes>
          <Route path="/team" element={<Team version={0} recordings={[]} />} />
          <Route path="/inbox" element={<p>在待处理</p>} />
        </Routes>
      </ConfirmProvider>
    </MemoryRouter>,
  );
  expect(await screen.findByText('在待处理')).toBeInTheDocument();
  expect(screen.queryByRole('tab', { name: /待处理/u })).toBeNull();
});

it('asks about recordings only as the server lists them, so an older list never flashes', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices: [], fragments: [], unsorted: [] });
      if (url === '/api/personas') return json([]);
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter>
      <ConfirmProvider>
        <Team
          version={0}
          recordings={[
            {
              id: 'rec_1',
              filename: '周会.m4a',
              status: 'ready',
              unsettled: 4,
              speakers: 11,
            } as LibraryRecording,
          ]}
        />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  await screen.findByRole('tab', { name: /成员/u });
  expect(screen.queryByText('还有人没认')).toBeNull();
  expect(screen.queryByText(/项待处理/u)).toBeNull();
});

it('opens the speaker a link points at, even one already given to someone automatically', async () => {
  // In the address, not only the page's history: a recording opened in a new tab opens on the same voice.
  render(
    <MemoryRouter initialEntries={['/library/rec_1?speaker=S3']}>
      <Routes>
        <Route path="/library/:recordingId" element={<Recording />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(
    await screen.findByRole('heading', { name: 'S3 是谁？' }),
  ).toBeInTheDocument();
  expect(screen.getByText('现在算作张总，听一下是谁。')).toBeInTheDocument();
  // Still counted as settled while it is heard again.
  expect(screen.getByText('已确认 2 / 3 位')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '改 S3' })).toBeNull();
});

it('lists people heard longest first', async () => {
  people = [
    person({ id: 'per_a', name: '短的', seconds: 60 }),
    person({ id: 'per_b', name: '长的', seconds: 3600 }),
    person({ id: 'per_c', name: '中的', seconds: 600 }),
  ];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices: [], fragments: [], unsorted: [] });
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  await screen.findByText('长的', { selector: 'p' });
  expect(
    screen
      .getAllByText(/^(短的|长的|中的)$/u, { selector: 'p' })
      .map((p) => p.textContent),
  ).toEqual(['长的', '中的', '短的']);
});

it('adds a person by hand from a small dialog, and keeps the people list where it was', async () => {
  const posts: unknown[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people' && init?.method === 'POST') {
        posts.push(JSON.parse(String(init.body)));
        people = [...people, person({ id: 'per_5', name: '赵总' })];
        return json({ id: 'per_5' }, 201);
      }
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices: [], fragments: [], unsorted: [] });
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  await userEvent.click(
    await screen.findByRole('button', { name: '添加人物' }),
  );
  const dialog = await screen.findByRole('dialog', { name: '添加人物' });
  await userEvent.type(within(dialog).getByRole('textbox'), '赵总{Enter}');
  await waitFor(() => expect(posts).toEqual([{ name: '赵总' }]));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(
    await screen.findByText('赵总', { selector: 'p' }),
  ).toBeInTheDocument();
});

it('spot-checks what voice alone gave a person, least sure first, and takes a voice sample away', async () => {
  const user = userEvent.setup();
  people = [person({ checks: 2 }), person({ id: 'per_2', name: '李总' })];
  const check = (recording_id: string, lead: number) => ({
    recording_id,
    filename: `${recording_id}.m4a`,
    transcript_id: `t-${recording_id}`,
    revision: 1,
    speaker_id: 'S4',
    seconds: 90,
    tier: 'high',
    score: 0.7,
    lead,
  });
  let voice = {
    checks: [check('rec_8', 0.11), check('rec_9', 0.4)],
    samples: [
      {
        id: 7,
        recording_id: 'rec_1',
        filename: '周会.m4a',
        transcript_id: 't1',
        speaker_id: 'S1',
        seconds: 300,
        source: 'speaker',
        created_at: '2026-10-01',
        claims: 2,
        corrected: 1,
      },
    ],
  };
  const calls: { url: string; method?: string; body?: unknown }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices: [], fragments: [], unsorted: [] });
      if (url === '/api/library/people/per_1/voice') return json(voice);
      if (url === '/api/personas') return json([]);
      if (url === '/api/personas/trash') return json([]);
      calls.push({
        url,
        method: init?.method,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      if (url === '/api/library/recordings/rec_8/speakers/S4') {
        voice = { ...voice, checks: voice.checks.slice(1) };
        return json({ revision: 2, person_id: 'per_1', unlike: null });
      }
      if (url === '/api/library/people/per_1/samples/7') {
        voice = { checks: [], samples: [] };
        return json({ returned: 1 });
      }
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
        <ToastViewport />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  await user.click(await screen.findByLabelText('张总的更多操作'));
  // How many wait is a badge on the item, not words in its name.
  await user.click(screen.getByRole('button', { name: '抽查声线 2' }));
  const layer = await screen.findByRole('dialog', { name: '张总的声音' });
  const listed = await within(layer).findByRole('list', {
    name: '可抽查的发言',
  });
  const rows = within(listed).getAllByRole('listitem');
  // The least sure first: the likeliest mistake is heard first.
  expect(rows[0]).toHaveTextContent('rec_8.m4a');
  expect(rows[0]).toHaveTextContent('把握不大');
  expect(rows[1]).toHaveTextContent('很有把握');
  await user.click(within(rows[0]).getByRole('button', { name: '是张总' }));
  await waitFor(() =>
    expect(calls[0]).toEqual({
      url: '/api/library/recordings/rec_8/speakers/S4',
      method: 'PUT',
      body: {
        transcript_id: 't-rec_8',
        revision: 1,
        action: 'confirm',
        person_id: 'per_1',
      },
    }),
  );
  await waitFor(() =>
    expect(within(listed).getAllByRole('listitem')).toHaveLength(1),
  );
  const samples = within(layer).getByRole('list', { name: '声线' });
  expect(samples).toHaveTextContent('打标时留下 · 认出 2 段 · 被改过 1 次');
  await user.click(within(samples).getByRole('button', { name: '移除' }));
  const asked = await screen.findByRole('dialog', { name: '移除这段声线？' });
  expect(asked).toHaveTextContent('靠它认出的 2 段发言会退回待处理');
  await user.click(within(asked).getByRole('button', { name: '移除' }));
  await waitFor(() =>
    expect(calls[1]).toMatchObject({
      url: '/api/library/people/per_1/samples/7',
      method: 'DELETE',
    }),
  );
  expect(
    (await screen.findAllByText('已移除，1 段发言退回待处理')).length,
  ).toBeGreaterThan(0);
  expect(await within(layer).findByText(/还没有声音样本/u)).toBeVisible();
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

it('lists twins made by hand and public ones in the same table, each opening its member page', async () => {
  const switched: string[] = [];
  people = [person({ persona_id: 'p-1' })];
  usePersonas.setState({
    items: [
      twinOf({}),
      twinOf({ id: 'p-own', name: '我的助手', owner: 'me@acme.cn' }),
      twinOf({
        id: 'p-pub',
        name: '王总',
        owner: 'wang@acme.cn',
        public: true,
        can_manage: false,
      }),
    ],
    switchTo: async (id: string) => {
      switched.push(id);
    },
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter initialEntries={['/team']}>
      <ConfirmProvider>
        <Routes>
          <Route path="/team" element={<Team version={0} recordings={[]} />} />
          <Route path="/team/twin/:twinId" element={<p>分身成员页</p>} />
          <Route path="/chat" element={<Address />} />
        </Routes>
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const own = await screen.findByRole('link', { name: '我的助手的成员页' });
  expect(own).toHaveAttribute('href', '/team/twin/p-own');
  expect(screen.getByRole('link', { name: '张总的成员页' })).toHaveAttribute(
    'href',
    '/team/per_1',
  );
  const row = screen.getByText('王总', { selector: 'p' }).closest('tr')!;
  expect(within(row).getByText('wang@acme.cn')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /^全部 3$/u })).toBeInTheDocument();
  // Someone else's public twin is for talking to: no menu of things to manage.
  expect(within(row).queryByLabelText('王总的更多操作')).toBeNull();
  await userEvent.click(within(row).getByRole('button', { name: '聊天' }));
  // The chat opens on the twin itself (and switches to it), at an address that can be shared.
  expect(await screen.findByRole('status', { name: '地址' })).toHaveTextContent(
    '/chat?with=p-pub',
  );
  expect(switched).toEqual([]);
});

it('lets a twin made by hand be found by name and filtered with the rest', async () => {
  people = [person({ persona_id: 'p-1' })];
  usePersonas.setState({
    items: [twinOf({}), twinOf({ id: 'p-own', name: '我的助手' })],
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      throw new Error(url);
    }),
  );
  render(teamView());
  await screen.findByRole('link', { name: '我的助手的成员页' });
  await userEvent.type(screen.getByRole('textbox', { name: '找人' }), '助手');
  expect(screen.queryByRole('link', { name: '张总的成员页' })).toBeNull();
  expect(
    screen.getByRole('link', { name: '我的助手的成员页' }),
  ).toBeInTheDocument();
});

it('brings a deleted twin back from the 已删除 tab, and shows the tab only while something is there', async () => {
  const restored: string[] = [];
  let trash = [
    {
      id: 'p-gone',
      name: '旧分身',
      deleted_at: '2026-10-10T02:00:00Z',
      expires_at: '2026-10-17T02:00:00Z',
    },
  ];
  const refresh = vi.fn(async () => {});
  usePersonas.setState({ items: [], refresh });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      if (url === '/api/personas/trash') return json(trash);
      if (url === '/api/personas/p-gone/restore' && init?.method === 'POST') {
        restored.push(url);
        trash = [];
        return json({});
      }
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
        <ToastViewport />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  await userEvent.click(await screen.findByRole('tab', { name: /已删除.*1/u }));
  expect(await screen.findByText('旧分身')).toBeInTheDocument();
  // What the date means is said with it.
  expect(screen.getByText(/月\d+日前可恢复/u)).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: '恢复旧分身' }));
  await waitFor(() => expect(restored).toHaveLength(1));
  expect(refresh).toHaveBeenCalled();
  expect(await screen.findByText('没有已删除的分身。')).toBeInTheDocument();
  expect(await screen.findByText('已恢复「旧分身」')).toBeInTheDocument();
});

it('deletes a twin from its row in one step, and the toast undoes it', async () => {
  const calls: string[] = [];
  let deleted = false;
  people = [person({ persona_id: 'p-1' })];
  const refresh = vi.fn(async () => {});
  usePersonas.setState({ items: [twinOf({})], refresh });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      if (url === '/api/personas/trash')
        return json(
          deleted
            ? [
                {
                  id: 'p-1',
                  name: '张总',
                  deleted_at: '2026-10-25T02:00:00Z',
                  expires_at: '2026-11-01T02:00:00Z',
                },
              ]
            : [],
        );
      if (url === '/api/personas/p-1' && init?.method === 'DELETE') {
        calls.push('delete');
        deleted = true;
        return json({ deleted: true });
      }
      if (url === '/api/personas/p-1/restore' && init?.method === 'POST') {
        calls.push('restore');
        deleted = false;
        return json({});
      }
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
        <ToastViewport />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const toasts = () => within(screen.getByLabelText('通知'));
  await userEvent.click(await screen.findByLabelText('张总的更多操作'));
  await userEvent.click(screen.getByRole('button', { name: '删除分身' }));
  // It waits a week in the trash: no confirmation, it goes at once.
  expect(screen.queryByRole('dialog')).toBeNull();
  await waitFor(() => expect(calls).toEqual(['delete']));
  // The toast fades in: looked for at once, it may not have yet.
  await waitFor(() =>
    expect(toasts().getByText('已删除「张总」')).toBeVisible(),
  );
  expect(
    await screen.findByRole('tab', { name: /已删除.*1/u }),
  ).toBeInTheDocument();
  await userEvent.click(toasts().getByRole('button', { name: '撤销' }));
  await waitFor(() => expect(calls).toEqual(['delete', 'restore']));
  await waitFor(() =>
    expect(toasts().getByText('已恢复「张总」')).toBeVisible(),
  );
  await waitFor(() =>
    expect(screen.queryByRole('tab', { name: /已删除/u })).toBeNull(),
  );
  expect(refresh).toHaveBeenCalledTimes(2);
});

it('offers no 删除分身 for a default twin still in use', async () => {
  people = [person({ persona_id: 'p-1' })];
  usePersonas.setState({ items: [twinOf({ is_default: true })] });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      if (url === '/api/personas/trash') return json([]);
      throw new Error(url);
    }),
  );
  render(teamView());
  await userEvent.click(await screen.findByLabelText('张总的更多操作'));
  expect(screen.getByRole('button', { name: '编辑资料' })).toBeVisible();
  expect(screen.queryByRole('button', { name: '删除分身' })).toBeNull();
});

it('keeps the 已删除 tab away while nothing is deleted, and offers 新建分身 among the additions', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      if (url === '/api/personas/trash') return json([]);
      throw new Error(url);
    }),
  );
  render(teamView());
  await screen.findByRole('link', { name: '张总的成员页' });
  expect(screen.queryByRole('tab', { name: /已删除/u })).toBeNull();
  await userEvent.click(screen.getByText('添加'));
  await userEvent.click(screen.getByRole('button', { name: '新建分身' }));
  expect(useNewTwinCard.getState().open).toBe(true);
  useNewTwinCard.getState().set(false);
});

it('names the latest meeting of each person in its own column, and a line about them where they wrote one', async () => {
  people = [
    person({
      persona_id: 'p-1',
      about: '产品负责人',
      last_meeting: {
        recording_id: 'r1',
        title: '产品周会',
        date: '2026-10-15',
      },
    }),
    person({ id: 'per_2', name: '李总', last_meeting: null }),
  ];
  usePersonas.setState({ items: [twinOf({})] });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      throw new Error(url);
    }),
  );
  render(teamView());
  const table = await screen.findByRole('table', { name: '成员' });
  expect(
    within(table)
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent),
  ).toEqual(['成员', '录音', '分身', '最近', '操作']);
  const first = screen
    .getByRole('link', { name: '张总的成员页' })
    .closest('tr')!;
  expect(within(first).getByText('产品负责人')).toBeVisible();
  expect(within(first).getByText('10月15日 产品周会')).toBeVisible();
  const second = screen
    .getByRole('link', { name: '李总的成员页' })
    .closest('tr')!;
  expect(within(second).getByText('—')).toBeVisible();
});

it('lets someone talk to a public twin of a person from the table, though the twin is not theirs to look after', async () => {
  people = [
    person({
      persona_id: null,
      talk: 'p-pub',
      twin_elsewhere: true,
      can_manage: false,
    }),
  ];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      throw new Error(url);
    }),
  );
  usePersonas.setState({ items: [] });
  render(teamView());
  const row = (
    await screen.findByRole('link', { name: '张总的成员页' })
  ).closest('tr')!;
  expect(within(row).getByText('可以聊')).toBeVisible();
  await userEvent.click(within(row).getByRole('button', { name: '聊天' }));
  expect(screen.getByRole('status', { name: '地址' })).toHaveTextContent(
    '/chat?with=p-pub',
  );
});

it('shows a twin with nothing in it yet as waiting for a recording, to open rather than to talk to', async () => {
  people = [person({ persona_id: 'p-1' })];
  usePersonas.setState({
    items: [twinOf({}), twinOf({ id: 'p-new', name: '陈一', sources: 0 })],
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      throw new Error(url);
    }),
  );
  render(teamView());
  const row = (
    await screen.findByRole('link', { name: '陈一的成员页' })
  ).closest('tr')!;
  expect(within(row).getByText('等录音')).toBeVisible();
  expect(within(row).queryByText('可以聊')).toBeNull();
  // Talking to it would only get "I don't know": its page is where something to learn from is added.
  expect(within(row).queryByRole('button', { name: '聊天' })).toBeNull();
  expect(screen.getByRole('button', { name: '等录音 1' })).toBeVisible();
  await userEvent.click(within(row).getByRole('button', { name: '查看' }));
  expect(screen.getByRole('status', { name: '地址' })).toHaveTextContent(
    '/team/twin/p-new',
  );
});

it("lists a colleague's public twin and a twin that is one's own by voice once, as the person they belong to", async () => {
  people = [
    person({
      persona_id: null,
      talk: 'p-pub',
      twin_id: 'p-pub',
      twin_elsewhere: true,
      can_manage: false,
    }),
    person({
      id: 'per_2',
      name: '李总',
      persona_id: null,
      twin_id: 'p-voice',
      self_claimed: true,
      can_manage: false,
    }),
  ];
  usePersonas.setState({
    items: [
      twinOf({
        id: 'p-pub',
        name: '张总',
        owner: 'wang@acme.cn',
        public: true,
      }),
      twinOf({ id: 'p-voice', name: '李总' }),
    ],
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      throw new Error(url);
    }),
  );
  render(teamView());
  const table = await screen.findByRole('table', { name: '成员' });
  expect(
    within(table).getAllByRole('link', { name: /的成员页$/u }),
  ).toHaveLength(2);
  expect(within(table).getAllByText('张总')).toHaveLength(1);
  expect(within(table).getAllByText('李总')).toHaveLength(1);
});

it('asks whoever keeps a twin made by hand whether it is the person of the same name in the meetings', async () => {
  people = [person({ id: 'per_9', name: '王总', persona_id: null })];
  const matches = [{ persona_id: 'p-own', person_id: 'per_9', name: '王总' }];
  const answers: Record<string, unknown>[] = [];
  usePersonas.setState({
    items: [twinOf({ id: 'p-own', name: '王总', owner: 'me@acme.cn' })],
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people')
        return json({ items: people, matches });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      if (url === '/api/library/people/per_9/same') {
        answers.push(JSON.parse(String(init?.body)));
        return json({ same: true });
      }
      if (url === '/api/personas') return json([]);
      throw new Error(url);
    }),
  );
  render(teamView());
  // The table also lists the person of that name from the meetings: this is the twin's own row.
  const link = (
    await screen.findAllByRole('link', { name: '王总的成员页' })
  ).find((anchor) => anchor.getAttribute('href') === '/team/twin/p-own');
  const row = link!.closest('tr');
  expect(row).not.toBeNull();
  expect(within(row!).getByText('会议里有同名的人')).toBeVisible();
  await userEvent.click(within(row!).getByLabelText('王总是不是会议里的人'));
  await userEvent.click(screen.getByRole('button', { name: '是同一人' }));
  await waitFor(() =>
    expect(answers).toEqual([{ persona_id: 'p-own', same: true }]),
  );
});

it('says where a twin whose update waits stands, and builds it again from its row', async () => {
  const build = {
    state: 'idle',
    step: '',
    done: 0,
    total: 0,
    last_error: '模型限流，整理中断',
    retry_at: '2026-10-23T03:30:00Z',
  } as unknown as NonNullable<Person['build']>;
  people = [
    person({
      id: 'per_1',
      name: '张总',
      persona_id: 'p-1',
      updating: true,
      build,
    }),
    person({
      id: 'per_2',
      name: '李总',
      persona_id: 'p-2',
      updating: true,
      held: true,
    }),
    person({
      id: 'per_3',
      name: '王总',
      persona_id: 'p-3',
      updating: true,
      answers_behind: true,
      held: true,
    }),
  ];
  const rebuilt: string[] = [];
  const base = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    const path = String(url);
    if (path.startsWith('/api/library/review')) return json(emptyReview);
    if (path.endsWith('/rebuild')) {
      rebuilt.push(path);
      return json({ ok: true });
    }
    return base(url, init);
  });
  const user = userEvent.setup();
  render(teamView());
  const row = async (name: string) =>
    (await screen.findByRole('link', { name: `${name}的成员页` })).closest(
      'tr',
    )!;
  // The update stopped: why on hover, when it is tried again by itself, and 重试 now.
  const stalled = await row('张总');
  expect(within(stalled).getByText('更新没完成')).toHaveAttribute(
    'title',
    '模型限流，整理中断',
  );
  expect(within(stalled).getByText(/自动重试$/u)).toBeInTheDocument();
  // Held by the switched-off automatic rebuild: 立即整理.
  const held = await row('李总');
  expect(within(held).getByText('整理已暂停')).toBeInTheDocument();
  await user.click(within(held).getByRole('button', { name: '立即整理' }));
  // New recordings wait while it answers from what it has: it can be talked to, and built now from “⋯”.
  const behind = await row('王总');
  expect(within(behind).getByText('有新录音')).toBeInTheDocument();
  expect(within(behind).getByRole('button', { name: '聊天' })).toBeEnabled();
  await user.click(within(stalled).getByRole('button', { name: '重试' }));
  await waitFor(() =>
    expect(rebuilt).toEqual([
      '/api/library/people/per_2/rebuild',
      '/api/library/people/per_1/rebuild',
    ]),
  );
});

it('lets go of a filter nobody is in any more, and offers the retry to whoever can open the twin though not manage the person', async () => {
  const stalled = {
    state: 'idle',
    step: '',
    done: 0,
    total: 0,
    last_error: '模型限流，整理中断',
    retry_at: null,
  } as unknown as NonNullable<Person['build']>;
  people = [
    person({
      id: 'per_1',
      name: '张总',
      persona_id: 'p-1',
      updating: true,
      build: stalled,
      can_manage: false,
    }),
    person({ id: 'per_2', name: '李总', persona_id: 'p-2' }),
  ];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      throw new Error(url);
    }),
  );
  const view = (version: number) => (
    <MemoryRouter>
      <ConfirmProvider>
        <Team version={version} recordings={[]} />
      </ConfirmProvider>
    </MemoryRouter>
  );
  const { rerender } = render(view(0));
  const row = (
    await screen.findByRole('link', { name: '张总的成员页' })
  ).closest('tr')!;
  expect(within(row).getByRole('button', { name: '重试' })).toBeEnabled();
  await userEvent.click(screen.getByRole('button', { name: /^更新没完成/u }));
  expect(screen.queryByRole('link', { name: '李总的成员页' })).toBeNull();
  // Retried: it is updating now, and the filter that held only it has nobody left.
  people = [{ ...people[0]!, build: null }, people[1]!];
  rerender(view(1));
  await waitFor(() =>
    expect(screen.queryByRole('button', { name: /^更新没完成/u })).toBeNull(),
  );
  expect(screen.getByRole('button', { name: /^全部/u })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  expect(
    await screen.findByRole('link', { name: '李总的成员页' }),
  ).toBeInTheDocument();
});

it('says that an action on a row failed where the person is, not at the top of the table', async () => {
  const stalled = {
    state: 'idle',
    step: '',
    done: 0,
    total: 0,
    last_error: '模型限流，整理中断',
    retry_at: null,
  } as unknown as NonNullable<Person['build']>;
  people = [person({ persona_id: 'p-1', updating: true, build: stalled })];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      if (url === '/api/personas/trash') return json([]);
      if (init?.method === 'POST')
        return json({ detail: '已经在整理了，稍后再试' }, 409);
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
        <ToastViewport />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  await userEvent.click(await screen.findByRole('button', { name: '重试' }));
  expect(
    (await screen.findAllByText('已经在整理了，稍后再试')).length,
  ).toBeGreaterThan(0);
  expect(screen.queryByRole('alert')).toBeNull();
});

it('shows nothing, for the page around it, while no one is on the team and nothing was deleted', async () => {
  people = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      if (url === '/api/personas/trash') return json([]);
      throw new Error(url);
    }),
  );
  const { container } = render(
    <MemoryRouter>
      <ConfirmProvider>
        <Team quietWhenEmpty version={0} recordings={[]} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  await waitFor(() =>
    expect(vi.mocked(fetch).mock.calls.map(([url]) => url)).toContain(
      '/api/personas/trash',
    ),
  );
  expect(container).toBeEmptyDOMElement();
});

it('shows an administrator people whose voice samples sound alike, to hear them and take the wrong one away', async () => {
  useAuth.setState({
    identity: { email: 'admin@example.com', admin: true, auth_enabled: true },
  });
  const sample = (id: number, who: Person, wrong = false, gone = false) => ({
    id,
    person_id: who.id,
    name: who.name,
    recording_id: `rec_${id}`,
    filename: `rec_${id}.m4a`,
    speaker_id: 'S1',
    seconds: 300,
    unlike_own: wrong,
    gone,
  });
  const [zhang, li] = people;
  const wang = person({ id: 'per_3', name: '王总' });
  people = [zhang, li, wang];
  let clashes = [
    {
      score: 0.93,
      together: false,
      samples: [sample(1, zhang), sample(2, li, true)],
    },
    {
      score: 0.88,
      together: true,
      samples: [sample(3, zhang), sample(4, wang, false, true)],
    },
  ];
  const posts: { url: string; body: unknown }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      if (url === '/api/library/voice-clashes') return json(clashes);
      if (url === '/api/library/voice-clashes/remove') {
        posts.push({ url, body: JSON.parse(String(init?.body)) });
        clashes = clashes.slice(1);
        return json({ returned: 2, recognised: 3 });
      }
      if (url === '/api/library/voice-clashes/apart') {
        posts.push({ url, body: JSON.parse(String(init?.body)) });
        clashes = [];
        return json({ apart: true });
      }
      if (url === '/api/personas/trash') return json([]);
      throw new Error(url);
    }),
  );
  const user = userEvent.setup();
  render(teamView());
  expect(await screen.findByText('2 对成员的声线几乎一样')).toBeVisible();
  await user.click(screen.getByRole('button', { name: '核对' }));
  const layer = await screen.findByRole('dialog', { name: '核对声线' });
  const pair = within(layer).getByRole('list', { name: '张总 和 李总的声线' });
  const rows = within(pair).getAllByRole('listitem');
  // The sample more like the other person than like their own is the likely mistake.
  await waitFor(() =>
    expect(within(rows[1]).getByText('更像对方')).toBeVisible(),
  );
  expect(within(rows[0]).queryByText('更像对方')).toBeNull();
  expect(
    within(rows[1]).getByRole('button', { name: '听李总的声线（rec_2.m4a）' }),
  ).toBeVisible();
  // Two people heard in one meeting are not one person: no merging them.
  expect(within(layer).getAllByRole('button', { name: '合并' })).toHaveLength(
    1,
  );
  // A sample whose recording was transcribed again cannot be heard: it says so in place of playing.
  const other = within(
    within(layer).getByRole('list', { name: '张总 和 王总的声线' }),
  ).getAllByRole('listitem');
  expect(within(other[1]).getByText('听不到')).toBeVisible();
  expect(
    within(other[1]).queryByRole('button', { name: /^听王总/u }),
  ).toBeNull();
  expect(
    within(other[0]).getByRole('button', { name: /^听张总/u }),
  ).toBeVisible();

  await user.click(within(rows[1]).getByRole('button', { name: '移除这段' }));
  await user.click(await screen.findByRole('button', { name: '移除' }));
  await waitFor(() =>
    expect(posts[0]).toEqual({
      url: '/api/library/voice-clashes/remove',
      body: { sample_id: 2 },
    }),
  );
  expect(await screen.findByText('1 对成员的声线几乎一样')).toBeVisible();
  // The layer stays open on the next pair once the confirmation closed.
  const still = await screen.findByRole('dialog', { name: '核对声线' });
  await user.click(
    await within(still).findByRole('button', { name: '都没错' }),
  );
  await waitFor(() =>
    expect(posts[1]).toEqual({
      url: '/api/library/voice-clashes/apart',
      body: { samples: [3, 4] },
    }),
  );
  expect(await within(still).findByText('都核对完了')).toBeVisible();
  expect(screen.queryByText(/对成员的声线几乎一样/u)).toBeNull();
});

it('shows nobody but an administrator voice samples that sound alike', async () => {
  useAuth.setState({
    identity: { email: 'member@example.com', admin: false, auth_enabled: true },
  });
  const fetch = vi.fn(async (url: string) => {
    if (url === '/api/library/people') return json({ items: people });
    if (url.startsWith('/api/library/review')) return json(emptyReview);
    if (url === '/api/personas/trash') return json([]);
    throw new Error(url);
  });
  vi.stubGlobal('fetch', fetch);
  render(teamView());
  await screen.findByText('张总', { selector: 'p' });
  expect(
    fetch.mock.calls.some(([url]) => url === '/api/library/voice-clashes'),
  ).toBe(false);
  expect(screen.queryByText(/声线几乎一样/u)).toBeNull();
});
