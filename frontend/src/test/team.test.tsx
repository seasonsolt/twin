import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider, ToastViewport } from '../components/ui';
import type { ReviewUnit, UnitFix } from '../features/library/MixedSpeaker';
import { Team } from '../features/library/Team';
import { Recording, type Person, type Speaker } from '../pages/Recording';
import type { Recording as LibraryRecording } from '../pages/Library';
import { usePersonas } from '../stores/personas';

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
afterEach(() => vi.restoreAllMocks());

const emptyReview = { items: [], voices: [], fragments: [], unsorted: [] };
const teamView = (version = 0) => (
  <MemoryRouter>
    <ConfirmProvider>
      <Team version={version} recordings={[]} />
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
  const panel = () => within(screen.getByRole('tabpanel', { name: /人物/u }));
  expect(panel().getAllByRole('listitem')).toHaveLength(18);
  expect(
    screen.queryByText('人物41', { selector: 'p' }),
  ).not.toBeInTheDocument();
  await userEvent.type(screen.getByRole('textbox', { name: '找人' }), '人物41');
  expect(panel().getAllByRole('listitem')).toHaveLength(1);
  expect(screen.getByText('人物41', { selector: 'p' })).toBeVisible();
  await userEvent.clear(screen.getByRole('textbox', { name: '找人' }));
  expect(panel().getAllByRole('listitem')).toHaveLength(18);
  act(() => scrollTo('继续加载人物'));
  expect(panel().getAllByRole('listitem')).toHaveLength(36);
  view.rerender(teamView(1));
  await waitFor(() =>
    expect(panel().getAllByRole('listitem')).toHaveLength(36),
  );
  act(() => scrollTo('继续加载人物'));
  expect(panel().getAllByRole('listitem')).toHaveLength(41);
  expect(
    screen.queryByRole('button', { name: '继续加载人物' }),
  ).not.toBeInTheDocument();
});

it('pages a task category while its batch action still handles every recording', async () => {
  const scrollTo = mockScrolling();
  const retried: string[] = [];
  const failed = Array.from(
    { length: 22 },
    (_, i) =>
      ({
        id: `failed-${i}`,
        filename: `失败${i}.m4a`,
        status: 'failed',
      }) as LibraryRecording,
  );
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return json(emptyReview);
      if (url.endsWith('/retry') && init?.method === 'POST') {
        retried.push(url);
        return json({});
      }
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter initialEntries={['/?tab=todo&cat=failed']}>
      <ConfirmProvider>
        <Team version={0} recordings={failed} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  await screen.findByRole('button', { name: '全部重试' });
  expect(screen.getAllByRole('button', { name: '重试' })).toHaveLength(10);
  await userEvent.click(screen.getByRole('button', { name: '全部重试' }));
  await waitFor(() => expect(retried).toHaveLength(22));
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: '继续加载待处理事项' }),
    ).toBeEnabled(),
  );
  act(() => scrollTo('继续加载待处理事项'));
  expect(screen.getAllByRole('button', { name: '重试' })).toHaveLength(20);
  act(() => scrollTo('继续加载待处理事项'));
  expect(screen.getAllByRole('button', { name: '重试' })).toHaveLength(22);
  expect(
    screen.queryByRole('button', { name: '继续加载待处理事项' }),
  ).not.toBeInTheDocument();
});

it('shows people while review is pending and does not call the unloaded queue empty', async () => {
  let finish!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review')) return pending;
      throw new Error(url);
    }),
  );
  render(teamView());
  expect(await screen.findByText('张总', { selector: 'p' })).toBeVisible();
  await userEvent.click(screen.getByRole('tab', { name: /待处理/u }));
  expect(screen.getByRole('status')).toHaveTextContent('正在加载待处理事项');
  expect(
    screen.queryByText('现在没有需要你处理的事。'),
  ).not.toBeInTheDocument();
  await act(async () => {
    finish(json(emptyReview));
  });
  expect(await screen.findByText('现在没有需要你处理的事。')).toBeVisible();
});

it('keeps people usable when review fails and lets the owner retry in its tab', async () => {
  let failed = true;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return failed
          ? json({ detail: '复核暂时失败' }, 500)
          : json(emptyReview);
      throw new Error(url);
    }),
  );
  render(teamView());
  expect(await screen.findByText('张总', { selector: 'p' })).toBeVisible();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('tab', { name: /待处理/u }));
  expect(await screen.findByRole('alert')).toHaveTextContent('复核暂时失败');
  failed = false;
  await userEvent.click(screen.getByRole('button', { name: '重试' }));
  expect(await screen.findByText('现在没有需要你处理的事。')).toBeVisible();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('ignores an older review failure after a newer refresh has finished', async () => {
  let fail!: (error: Error) => void;
  const pending = new Promise<Response>((_, reject) => {
    fail = reject;
  });
  let reviews = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return ++reviews === 1 ? pending : json(emptyReview);
      throw new Error(url);
    }),
  );
  const view = render(teamView());
  await screen.findByText('张总', { selector: 'p' });
  view.rerender(teamView(1));
  await userEvent.click(screen.getByRole('tab', { name: /待处理/u }));
  expect(await screen.findByText('现在没有需要你处理的事。')).toBeVisible();
  await act(async () => {
    fail(new Error('older request failed'));
  });
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(screen.getByText('现在没有需要你处理的事。')).toBeVisible();
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
  render(
    <MemoryRouter initialEntries={['/?tab=todo']}>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const tasks = await screen.findByRole('region', { name: /新出现的声音/u });
  expect(await within(tasks).findByText('像张总')).toBeInTheDocument();
  expect(within(tasks).getByRole('link', { name: '打开录音' })).toHaveAttribute(
    'href',
    '/library/rec_9?speaker=S1',
  );
  await userEvent.click(screen.getByRole('tab', { name: /人物/u }));
  const row = screen.getByText('张总', { selector: 'p' }).closest('li')!;
  expect(within(row).getByText('还没有分身')).toBeInTheDocument();
  await userEvent.click(within(row).getByRole('button', { name: '生成分身' }));
  // Made for 张总's work e-mail (or employee number): they take it when they sign in.
  const dialog = await screen.findByRole('dialog', { name: '为张总建分身' });
  await userEvent.type(
    within(dialog).getByRole('textbox', { name: /企业邮箱或工号/u }),
    'zhang@acme.cn',
  );
  await userEvent.click(within(dialog).getByRole('button', { name: '建好' }));
  expect(await screen.findByText('记忆更新中')).toBeInTheDocument();
  // Until it can talk, the card shows the step the update is on and how far it has gone.
  expect(
    await screen.findByRole('progressbar', {
      name: '第 2/3 步 · 合并成记忆',
      // The dialog is still fading out over the page.
      hidden: true,
    }),
  ).toHaveAttribute('aria-valuenow', '30');
  expect(screen.getByText('23%')).toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: '和分身聊聊' }),
  ).not.toBeInTheDocument();
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

it('lists new voices apart and names them before a twin can be made', async () => {
  const patches: unknown[] = [];
  people = [
    person({}),
    person({
      id: 'per_9',
      name: '未命名 1',
      auto: true,
      recording_id: 'rec_9',
    }),
  ];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices: [], fragments: [], unsorted: [] });
      if (url === '/api/library/people/per_9' && init?.method === 'PATCH') {
        patches.push(JSON.parse(String(init.body)));
        people = [person({}), person({ id: 'per_9', name: '李总' })];
        return json({ renamed: true });
      }
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter initialEntries={['/?tab=todo']}>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const fresh = await screen.findByRole('region', { name: /新出现的声音/u });
  expect(within(fresh).getByText(/未命名 1/u)).toBeInTheDocument();
  expect(
    within(fresh).queryByRole('button', { name: '生成分身' }),
  ).not.toBeInTheDocument();
  // The voice is heard in its row; the recording is one link away for the whole transcript.
  expect(
    within(fresh).getByRole('button', { name: '听未命名 1的声音' }),
  ).toBeInTheDocument();
  expect(fresh.querySelector('audio')).toHaveAttribute(
    'src',
    '/api/library/recordings/rec_9/speakers/S1/samples/0',
  );
  expect(within(fresh).getByRole('link', { name: '打开录音' })).toHaveAttribute(
    'href',
    '/library/rec_9?speaker=S1',
  );
  await userEvent.type(within(fresh).getByLabelText('未命名 1是谁'), '李总');
  await userEvent.click(within(fresh).getByRole('button', { name: '确认' }));
  await waitFor(() => expect(patches).toEqual([{ name: '李总' }]));
  // Named, they can have twins like anyone else.
  await screen.findByText('现在没有需要你处理的事。');
  await userEvent.click(screen.getByRole('tab', { name: /人物/u }));
  expect(
    await screen.findAllByRole('button', { name: '生成分身' }),
  ).toHaveLength(2);
  expect(screen.queryByText(/项待处理/u)).toBeNull();
});

it('edits a person name and gender and opens the profile of their twin', async () => {
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
          <Route path="/profile" element={<p>档案页</p>} />
        </Routes>
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const row = (await screen.findByText('张总', { selector: 'p' })).closest(
    'li',
  )!;
  // The twin's own illustration stands for them.
  expect(
    within(row).getByRole('img', { name: '插画形象：石', hidden: true }),
  ).toBeInTheDocument();
  await userEvent.click(within(row).getByLabelText('更多：张总'));
  expect(within(row).queryByRole('button', { name: '删除' })).toBeNull();
  await userEvent.click(
    within(row).getByRole('button', { name: '编辑名字和性别' }),
  );
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
  await userEvent.click(screen.getByRole('link', { name: '张总监的档案' }));
  expect(await screen.findByText('档案页')).toBeInTheDocument();
  expect(switched).toEqual(['p-1']);
});

it('stays where the owner is working after settling a voice, instead of jumping to the top', async () => {
  people = ['1', '2', '3'].map((n) =>
    person({ id: `p${n}`, name: `未命名 ${n}`, auto: true }),
  );
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices: [], fragments: [], unsorted: [] });
      if (init?.method === 'PATCH') {
        const id = url.split('/').at(-1);
        people = people.map((p) =>
          p.id === id
            ? { ...p, auto: false, name: JSON.parse(String(init.body)).name }
            : p,
        );
        return json({ renamed: true });
      }
      throw new Error(url);
    }),
  );
  // jsdom lays nothing out: each row sits a hundred pixels below the one before it.
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
    function (this: HTMLElement) {
      const rows = Array.from(document.querySelectorAll('li'));
      return { top: rows.indexOf(this as HTMLLIElement) * 100 } as DOMRect;
    },
  );
  const focus = vi.spyOn(HTMLElement.prototype, 'focus');
  render(
    <MemoryRouter initialEntries={['/?tab=todo']}>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  await userEvent.type(
    await screen.findByLabelText('未命名 2是谁'),
    '张总{Enter}',
  );
  // The next voice slid into the settled one's place; the first one, above, keeps its place too.
  await waitFor(() =>
    expect(screen.getByLabelText('未命名 3是谁')).toHaveFocus(),
  );
  expect(focus).toHaveBeenLastCalledWith({ preventScroll: true });
});

it('moves focus to the next voice after naming one, then hides the empty queue', async () => {
  people = [
    person({ id: 'first', name: '未命名 1', auto: true }),
    person({ id: 'second', name: '未命名 2', auto: true }),
  ];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices: [], fragments: [], unsorted: [] });
      if (init?.method === 'PATCH') {
        const id = url.split('/').at(-1);
        people = people.map((p) =>
          p.id === id
            ? { ...p, auto: false, name: JSON.parse(String(init.body)).name }
            : p,
        );
        return json({ renamed: true });
      }
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter initialEntries={['/?tab=todo']}>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  // Naming several is type, Enter, type, Enter.
  const first = await screen.findByLabelText('未命名 1是谁');
  await userEvent.type(first, '张总{Enter}');
  const next = screen.getByLabelText('未命名 2是谁');
  await waitFor(() => expect(next).toHaveFocus());
  await userEvent.type(next, '李总{Enter}');
  await screen.findByText('现在没有需要你处理的事。');
  expect(screen.queryByRole('region', { name: '正在处理' })).toBeNull();
});

it('settles a new voice as someone already known, or as nobody known, from its row', async () => {
  const resolved: unknown[] = [];
  people = [
    person({}),
    person({ id: 'first', name: '未命名 1', auto: true }),
    person({ id: 'second', name: '未命名 2', auto: true }),
  ];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices: [], fragments: [], unsorted: [] });
      const id = /people\/([^/]+)\/resolve$/u.exec(url)?.[1];
      if (id && init?.method === 'POST') {
        resolved.push({ id, ...JSON.parse(String(init.body)) });
        people = people.filter((p) => p.id !== id);
        return json({ resolved: true });
      }
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter initialEntries={['/?tab=todo']}>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const first = await screen.findByLabelText('未命名 1是谁');
  // Known people are offered as the owner types, and the button says what confirming does.
  const offered = document.getElementById(first.getAttribute('list')!)!;
  expect(
    Array.from(offered.querySelectorAll('option')).map((o) => o.value),
  ).toEqual(['张总']);
  await userEvent.type(first, '张总');
  await userEvent.click(screen.getAllByRole('button', { name: '确认' })[0]);
  await waitFor(() =>
    expect(resolved).toEqual([{ id: 'first', into: 'per_1' }]),
  );
  const next = screen.getByLabelText('未命名 2是谁');
  await waitFor(() => expect(next).toHaveFocus());
  await userEvent.click(screen.getByLabelText('更多选项：未命名 2'));
  await userEvent.click(screen.getByRole('button', { name: '不认识' }));
  await waitFor(() => expect(resolved).toHaveLength(2));
  expect(resolved[1]).toEqual({ id: 'second', into: null });
  await screen.findByText('现在没有需要你处理的事。');
});

it('returns from a speaker confirmation to focus the next pending team item', async () => {
  const originalFetch = fetch;
  let reviewed = false;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.startsWith('/api/library/review'))
        return json({
          items: reviewed
            ? []
            : [
                {
                  ...speaker({ disputed: true }),
                  recording_id: 'rec_1',
                  filename: '周会.m4a',
                },
              ],
          voices: [],
          fragments: [],
          unsorted: [],
        });
      if (url === '/api/library/people')
        return json({
          items: [
            ...people,
            person({ id: 'new', name: '未命名 1', auto: true }),
          ],
        });
      const result = await originalFetch(url, init);
      if (init?.method === 'PUT') reviewed = true;
      return result;
    }),
  );
  render(
    <MemoryRouter initialEntries={['/team?tab=todo&cat=disputed']}>
      <ConfirmProvider>
        <Routes>
          <Route path="/team" element={<Team version={0} recordings={[]} />} />
          <Route path="/library/:recordingId" element={<Recording />} />
        </Routes>
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const tasks = await screen.findByRole('region', { name: /有人说不是自己/u });
  await userEvent.click(
    within(tasks).getByRole('link', { name: '试听并确认' }),
  );
  const card = (
    await screen.findByRole('heading', { name: 'S1 是谁？' })
  ).closest('section')!;
  await userEvent.selectOptions(within(card).getByLabelText('这是谁'), 'per_1');
  await userEvent.click(screen.getByRole('button', { name: '确认是张总' }));
  await waitFor(() =>
    expect(screen.getByLabelText('未命名 1是谁')).toHaveFocus(),
  );
  expect(screen.queryByText('拿不准是谁')).toBeNull();
});

it('keeps uploads in the quiet processing group with progress and a stop action', async () => {
  const stop = vi.fn();
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: [] });
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices: [], fragments: [], unsorted: [] });
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter initialEntries={['/?tab=todo']}>
      <ConfirmProvider>
        <Team
          version={0}
          recordings={[]}
          uploads={[
            {
              file: new File(['audio'], '上传.m4a'),
              progress: {
                name: '上传.m4a',
                offset: 5,
                size: 10,
                paused: false,
              },
            },
          ]}
          onStopUpload={stop}
        />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const progress = screen.getByRole('region', { name: '正在处理' });
  expect(
    within(progress).getByText('上传.m4a · 上传中 50%'),
  ).toBeInTheDocument();
  expect(
    await screen.findByText('现在没有需要你处理的事。'),
  ).toBeInTheDocument();
  await userEvent.click(
    within(progress).getByRole('button', { name: /停止上传/u }),
  );
  expect(stop).toHaveBeenCalledOnce();
});

it('searches people locally, opens an untwinned header for editing, and keeps deletion in its menu', async () => {
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
  await screen.findByRole('button', { name: '编辑张总' });
  const beforeSearch = calls.length;
  await userEvent.type(screen.getByRole('textbox', { name: '找人' }), '李');
  expect(screen.queryByRole('button', { name: '编辑张总' })).toBeNull();
  expect(screen.getByRole('button', { name: '编辑李总' })).toBeInTheDocument();
  expect(screen.getByRole('tab', { name: /人物.*2/u })).toBeInTheDocument();
  expect(calls).toHaveLength(beforeSearch);
  await userEvent.click(screen.getByRole('button', { name: '编辑李总' }));
  expect(
    await screen.findByRole('dialog', { name: '编辑「李总」' }),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: '取消' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  await userEvent.click(screen.getByLabelText('更多：李总'));
  expect(screen.getByRole('button', { name: '删除' })).toBeInTheDocument();
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
  render(
    <MemoryRouter initialEntries={['/?tab=todo']}>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const tasks = await screen.findByRole('region', { name: /分身被退回/u });
  expect(within(tasks).getByText('王总')).toBeInTheDocument();
  expect(
    within(tasks).getByText('wang@acme.cn 说这不是 TA'),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole('tab', { name: /人物/u }));
  await userEvent.click(
    screen.getByRole('button', { name: '按邮箱或工号建分身（3）' }),
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
    '77845',
  );
  await userEvent.click(
    within(dialog).getByRole('button', { name: '为 2 位同事建分身' }),
  );
  await waitFor(() =>
    expect(sent).toEqual([
      ['/api/library/people/per_1/persona', 'POST', { claim: 'zhang@acme.cn' }],
      ['/api/personas/p-li/claim', 'PUT', { claim: '77845' }],
    ]),
  );
  // The one that did not go through stays, with why; the rest leave the list.
  expect(
    await within(dialog).findByText('这个邮箱或工号已经用在另一个分身上'),
  ).toBeInTheDocument();
  expect(
    within(dialog).getByRole('textbox', { name: '李总 · 1 段录音' }),
  ).toHaveValue('77845');
  expect(
    within(dialog).getByRole('textbox', { name: '张总 · 1 段录音' }),
  ).toHaveValue('');
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
  const row = name.closest('li')!;
  expect(within(row).getByText('本人已认领')).toBeInTheDocument();
  expect(
    within(row).getByRole('button', { name: '分身归 TA 自己' }),
  ).toBeDisabled();
  expect(within(row).queryByRole('button', { name: '生成分身' })).toBeNull();
  expect(within(row).queryByRole('link', { name: '张总的档案' })).toBeNull();
});

it('puts what someone said is not them first, and lets an administrator merge two people of one name', async () => {
  const user = userEvent.setup();
  people = [
    person({ similar: ['per_2'] }),
    person({ id: 'per_2', name: '张总（2）', speakers: 3, similar: ['per_1'] }),
    // Someone the viewer does not look after: on the roster for picking, not on this page.
    person({ id: 'per_3', name: '王五', can_manage: false }),
  ];
  const posts: [string, unknown][] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({
          items: [
            {
              ...speaker({ id: 'S4', disputed: true }),
              recording_id: 'rec_1',
              filename: '周会.m4a',
            },
          ],
          voices: [],
          fragments: [],
          unsorted: [],
        });
      if (url === '/api/personas') return json([]);
      if (init?.method === 'POST') {
        posts.push([url, JSON.parse(String(init.body))]);
        people = [person({}), people[1]!];
        return json({ merged: true });
      }
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter initialEntries={['/?tab=todo&cat=disputed']}>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const disputed = (await screen.findByText('周会.m4a · S4')).closest('li')!;
  expect(disputed).toHaveTextContent('原来标成的人说这不是 TA');
  // The tabs and the kinds are told apart by what each holds.
  expect(screen.getByRole('tab', { name: /待处理.*2/u })).toBeInTheDocument();
  await user.click(screen.getByRole('tab', { name: /可能是同一个人/u }));
  const hint = (await screen.findByText('张总 和 张总（2）')).closest('li')!;
  expect(hint).toHaveTextContent('1 段录音 · 3 段录音');
  // The one who spoke more is kept.
  await user.click(within(hint).getByRole('button', { name: '合并' }));
  await waitFor(() =>
    expect(posts).toEqual([
      ['/api/library/people/per_1/merge', { into: 'per_2' }],
    ]),
  );
  await waitFor(() =>
    expect(screen.queryByText('张总 和 张总（2）')).toBeNull(),
  );
  await user.click(screen.getByRole('tab', { name: /人物/u }));
  expect(screen.queryByText('王五', { selector: 'p' })).toBeNull();
});

it('settles a voice heard in several meetings once, and sets the fragments aside together', async () => {
  const user = userEvent.setup();
  const member = (
    recording_id: string,
    speaker_id: string,
    seconds: number,
  ) => ({
    recording_id,
    filename: `${recording_id}.m4a`,
    transcript_id: `t-${recording_id}`,
    speaker_id,
    seconds,
  });
  let voices = [
    {
      id: 'voice_1',
      members: [member('rec_1', 'S1', 300), member('rec_2', 'S3', 200)],
      seconds: 500,
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
      near: false,
    },
  ];
  let fragments = [member('rec_1', 'S5', 3), member('rec_3', 'S2', 4)];
  const posts: unknown[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices, fragments, unsorted: [] });
      if (url === '/api/library/voices' && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as { action: string };
        posts.push(body);
        if (body.action === 'confirm') voices = [];
        else fragments = [];
        return json({
          person_id: 'per_1',
          recognised: body.action === 'confirm' ? 3 : 0,
        });
      }
      if (url === '/api/personas') return json([]);
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter initialEntries={['/?tab=todo']}>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
        <ToastViewport />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const tasks = await screen.findByRole('region', { name: /新出现的声音/u });
  // Like 张总, but not so alike that Enter answers it: confirming him is a click of its own.
  const row = within(tasks).getByText('可能是张总').closest('li')!;
  expect(row).toHaveTextContent('2 段录音 · 共说了 8 分钟');
  expect(within(row).getByRole('button', { name: '确认' })).toBeDisabled();
  // Heard in each meeting in turn, to be sure it is one person throughout.
  expect(
    within(row).getByRole('button', { name: '听这个声音（rec_1.m4a）' }),
  ).toBeInTheDocument();
  await user.click(within(row).getByRole('button', { name: /^换一段录音听/u }));
  expect(
    within(row).getByRole('button', { name: '听这个声音（rec_2.m4a）' }),
  ).toBeInTheDocument();
  // The link opens the recording being heard, numbered like the button that turns to the next one.
  expect(
    within(row).getByRole('link', { name: '打开第 2 段' }),
  ).toHaveAttribute('href', '/library/rec_2?speaker=S3');
  await user.click(within(row).getByRole('button', { name: '是张总' }));
  await waitFor(() =>
    expect(posts).toEqual([
      {
        members: [
          { recording_id: 'rec_1', transcript_id: 't-rec_1', speaker_id: 'S1' },
          { recording_id: 'rec_2', transcript_id: 't-rec_2', speaker_id: 'S3' },
        ],
        action: 'confirm',
        person_id: 'per_1',
      },
    ]),
  );
  await waitFor(() => expect(screen.queryByText('可能是张总')).toBeNull());
  // The new voice samples recognised 张总 elsewhere: the owner hears it saved them questions.
  expect(await screen.findByRole('status')).toHaveTextContent(
    '又按声音认出了 3 位说话人，不用再问',
  );
  const scraps = await screen.findByRole('region', { name: /零碎的声音/u });
  expect(scraps).toHaveTextContent('2 段录音里有 2 段很短的声音');
  expect(scraps).toHaveTextContent('共 7 秒');
  await user.click(within(scraps).getByRole('button', { name: '都放一边' }));
  await screen.findByText('现在没有需要你处理的事。');
  expect(posts[1]).toMatchObject({ action: 'unknown' });
});

it('opens a voice at its own speaker, next to the samples of who it may be', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({
          items: [],
          voices: [
            {
              id: 'voice_1',
              members: [
                {
                  recording_id: 'rec_1',
                  filename: '周会.m4a',
                  transcript_id: 't1',
                  speaker_id: 'S2',
                  seconds: 300,
                },
              ],
              seconds: 300,
              candidates: [
                { person_id: 'per_1', name: '张总', score: 0.7 },
                { person_id: 'per_2', name: '李总', score: 0.68 },
              ],
              near: true,
            },
          ],
          fragments: [],
          unsorted: [],
        });
      if (url === '/api/library/recordings/rec_1')
        return json({
          id: 'rec_1',
          filename: '周会.m4a',
          status: 'ready',
          transcript_id: 't1',
          revision,
          speakers: [speaker({}), speaker({ id: 'S2' })],
          segments: [
            { start: 0, end: 4, text: '先看预算。', speaker: 'S1' },
            { start: 4, end: 9, text: '我反对压缩研发。', speaker: 'S2' },
          ],
        });
      if (url === '/api/personas') return json([]);
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter initialEntries={['/team?tab=todo']}>
      <ConfirmProvider>
        <Routes>
          <Route path="/team" element={<Team version={0} recordings={[]} />} />
          <Route path="/library/:recordingId" element={<Recording />} />
        </Routes>
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const row = (await screen.findByText('可能是张总或李总')).closest('li')!;
  // Both people it may be can be heard by the voice they were confirmed with.
  expect(
    within(row).getByRole('button', { name: '听张总确认过的声音' }),
  ).toBeInTheDocument();
  expect(
    within(row).getByRole('button', { name: '听李总确认过的声音' }),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole('tab', { name: /人物/u }));
  expect(
    within(screen.getByRole('tabpanel')).getAllByRole('button', {
      name: /确认过的声音/u,
    }),
  ).toHaveLength(2);
  await userEvent.click(screen.getByRole('tab', { name: /待处理/u }));
  // The recording opens at the voice's own speaker, not at its first undecided one.
  await userEvent.click(screen.getByRole('link', { name: '打开录音' }));
  expect(
    await screen.findByRole('heading', { name: 'S2 是谁？' }),
  ).toBeInTheDocument();
  expect(screen.queryByText(/这个声音还出现在/u)).not.toBeInTheDocument();
});

it('says a voice opened from the team settles its one recording, heard in clips of that recording', async () => {
  const member = (recording: string, speakerId: string) => ({
    recording_id: recording,
    filename: `${recording}.m4a`,
    transcript_id: `t-${recording}`,
    speaker_id: speakerId,
    seconds: 300,
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url === '/api/library/review')
        return json({
          items: [],
          voices: [
            {
              id: 'voice_1',
              members: [
                member('rec_1', 'S2'),
                member('rec_2', 'S1'),
                member('rec_3', 'S4'),
              ],
              seconds: 900,
              candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
              near: false,
            },
          ],
          fragments: [],
          unsorted: [],
        });
      if (url === '/api/library/recordings/rec_1')
        return json({
          id: 'rec_1',
          filename: '周会.m4a',
          status: 'ready',
          transcript_id: 't1',
          revision,
          speakers: [speaker({}), speaker({ id: 'S2', samples: 3 })],
          segments: [
            { start: 0, end: 4, text: '先看预算。', speaker: 'S1' },
            { start: 4, end: 9, text: '我反对压缩研发。', speaker: 'S2' },
          ],
        });
      if (url === '/api/personas') return json([]);
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter initialEntries={['/team?tab=todo']}>
      <ConfirmProvider>
        <Routes>
          <Route path="/team" element={<Team version={0} recordings={[]} />} />
          <Route path="/library/:recordingId" element={<Recording />} />
        </Routes>
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const row = (await screen.findByText('可能是张总')).closest('li')!;
  expect(row).toHaveTextContent('3 段录音 · 共说了 15 分钟');
  await userEvent.click(within(row).getByRole('link', { name: '打开第 1 段' }));
  expect(
    await screen.findByRole('heading', { name: 'S2 是谁？' }),
  ).toBeInTheDocument();
  // Its minutes and clips are this recording's, and deciding here leaves the voice's other recordings waiting.
  expect(screen.getByText('这段录音里说了 5 分钟')).toBeInTheDocument();
  expect(screen.getByText('这段录音里的 3 个片段')).toBeInTheDocument();
  expect(screen.getAllByRole('button', { name: /^片段 \d/u })).toHaveLength(3);
  expect(
    screen.getByText(
      '这个声音还出现在另外 2 段录音里。这里只确认这一段，其余的回到待处理一起确认。',
    ),
  ).toBeInTheDocument();
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
  await screen.findByRole('tab', { name: /人物/u });
  expect(screen.queryByText('还有人没认')).toBeNull();
  expect(screen.queryByText(/项待处理/u)).toBeNull();
});

it('asks about whoever speaks longest first, and measures progress by speech settled', async () => {
  people = [
    person({}),
    person({
      id: 'per_9',
      name: '未命名 1',
      auto: true,
      recording_id: 'rec_9',
      seconds: 60,
    }),
  ];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({
          items: [],
          voices: [
            {
              id: 'voice_1',
              members: [
                {
                  recording_id: 'rec_1',
                  filename: '周会.m4a',
                  transcript_id: 't1',
                  speaker_id: 'S2',
                  seconds: 600,
                },
              ],
              seconds: 600,
              candidates: [],
              near: false,
            },
            {
              id: 'voice_2',
              members: [
                {
                  recording_id: 'rec_2',
                  filename: '月会.m4a',
                  transcript_id: 't2',
                  speaker_id: 'S5',
                  seconds: 30,
                },
              ],
              seconds: 30,
              candidates: [],
              near: false,
              stranger: true,
            },
          ],
          fragments: [],
          unsorted: [],
          heard: { settled: 900, total: 3600 },
        });
      if (url === '/api/personas') return json([]);
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter initialEntries={['/?tab=todo']}>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const list = await screen.findByRole('list', { name: '新出现的声音' });
  const [first, second] = within(list).getAllByRole('listitem');
  expect(first).toHaveTextContent('没听过的声音');
  expect(second).toHaveTextContent('未命名 1');
  // A voice the owner could not name before waits folded away last, and is set aside again in a click.
  const third = screen.getByText('你标过不认识的声音').closest('li')!;
  expect(within(list).queryByText('你标过不认识的声音')).toBeNull();
  await userEvent.click(within(third).getByLabelText(/^更多选项/u));
  expect(
    within(third).getByRole('button', { name: '仍不认识' }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole('progressbar', { name: '已知是谁说的发言' }),
  ).toHaveAttribute('aria-valuenow', '900');
  // Whom the owner cannot name, the colleague can: an invitation to recognise their own voice.
  const copy = vi.spyOn(navigator.clipboard, 'writeText');
  await userEvent.click(screen.getByRole('button', { name: '复制邀请' }));
  expect(copy).toHaveBeenCalledWith(expect.stringMatching(/\/#\/voice$/u));
});

it('offers the name a meeting calls a voice, and asks about whoever a twin still lacks first', async () => {
  const user = userEvent.setup();
  people = [person({})];
  const member = (
    recording_id: string,
    speaker_id: string,
    seconds: number,
  ) => ({
    recording_id,
    filename: `${recording_id}.m4a`,
    transcript_id: `t-${recording_id}`,
    speaker_id,
    seconds,
  });
  let voices = [
    {
      id: 'voice_new',
      members: [member('rec_1', 'S3', 120)],
      seconds: 120,
      candidates: [],
      near: false,
      called: '宋明',
      quote: '那宋明你跟老夏解释一下',
    },
    {
      id: 'voice_enough',
      members: [member('rec_1', 'S2', 900)],
      seconds: 900,
      candidates: [
        { person_id: 'per_1', name: '张总', score: 0.9, sure: true },
      ],
      near: false,
      had: 2400,
      enough: true,
    },
    {
      id: 'voice_called',
      members: [member('rec_1', 'S4', 60)],
      seconds: 60,
      candidates: [
        { person_id: 'per_1', name: '张总', score: 0.3, called: true },
      ],
      near: false,
      called: '张总',
      quote: '张总说两句',
    },
  ];
  const posts: unknown[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices, fragments: [], unsorted: [] });
      if (url === '/api/library/voices' && init?.method === 'POST') {
        posts.push(JSON.parse(String(init.body)));
        voices = voices.filter((v) => v.id !== 'voice_new');
        return json({ person_id: 'per_2', recognised: 0 });
      }
      if (url === '/api/personas') return json([]);
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter initialEntries={['/?tab=todo']}>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const list = await screen.findByRole('list', { name: '新出现的声音' });
  const [first, second] = within(list).getAllByRole('listitem');
  // Someone the meeting names but the team does not know yet: added in one click.
  expect(first).toHaveTextContent('会上被叫作宋明');
  expect(first).toHaveTextContent('「那宋明你跟老夏解释一下」');
  // A name with a voice that does not agree is no default.
  expect(second).toHaveTextContent('会上被叫作张总');
  expect(within(second).getByRole('button', { name: '确认' })).toBeDisabled();
  // Surely 张总, who has enough to learn from already: last, whatever its length.
  const third = screen.getByText('像张总').closest('li')!;
  expect(within(list).queryByText('像张总')).toBeNull();
  expect(third).toHaveTextContent('像张总');
  expect(third).toHaveTextContent('张总已经有 40 分钟发言，够建分身了');
  await user.click(within(first).getByRole('button', { name: '是宋明' }));
  await waitFor(() =>
    expect(posts).toEqual([
      {
        members: [
          { recording_id: 'rec_1', transcript_id: 't-rec_1', speaker_id: 'S3' },
        ],
        action: 'confirm',
        new_person: '宋明',
      },
    ]),
  );
});

it('settles a voice of several people and gives short voices to whom they sound like, strangers last', async () => {
  const posts: Record<string, unknown>[] = [];
  const member = (
    recording_id: string,
    speaker_id: string,
    seconds: number,
  ) => ({
    recording_id,
    filename: `${recording_id}.m4a`,
    transcript_id: `t-${recording_id}`,
    speaker_id,
    seconds,
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({
          items: [],
          voices: [
            {
              id: 'voice_stranger',
              members: [member('rec_7', 'S1', 50)],
              seconds: 50,
              candidates: [],
              near: false,
              stranger: true,
            },
            {
              id: 'voice_new',
              members: [member('rec_8', 'S2', 30)],
              seconds: 30,
              candidates: [],
              near: false,
            },
          ],
          fragments: [
            {
              ...member('rec_8', 'S5', 6),
              like: { person_id: 'per_1', name: '张总' },
            },
            {
              ...member('rec_9', 'S4', 4),
              like: { person_id: 'per_1', name: '张总' },
            },
            { ...member('rec_9', 'S6', 3), like: null },
          ],
          unsorted: [],
        });
      if (url === '/api/library/voices' && init?.method === 'POST') {
        posts.push(JSON.parse(String(init.body)));
        return json({});
      }
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter initialEntries={['/?tab=todo']}>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const tasks = await screen.findByRole('region', { name: /新出现的声音/u });
  // A voice like one the owner could not name waits behind a voice nobody has heard yet.
  const titles = within(tasks)
    .getAllByText(/^(没听过的声音|你标过不认识的声音)$/u)
    .map((t) => t.textContent);
  expect(titles).toEqual(['没听过的声音', '你标过不认识的声音']);
  const [first] = within(tasks).getAllByRole('button', {
    name: '几个人混在一起',
  });
  await userEvent.click(first);
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0]).toMatchObject({
    action: 'mixed',
    members: [{ recording_id: 'rec_8', speaker_id: 'S2' }],
  });
  // Short voices like 张总 are given in one click, without taking them as 张总's voice samples.
  await userEvent.click(screen.getByRole('tab', { name: /零碎的声音/u }));
  await userEvent.click(
    await screen.findByRole('button', { name: '2 段像张总：都是张总' }),
  );
  await waitFor(() => expect(posts).toHaveLength(2));
  expect(posts[1]).toEqual({
    action: 'confirm',
    person_id: 'per_1',
    sample: false,
    members: [
      { recording_id: 'rec_8', transcript_id: 't-rec_8', speaker_id: 'S5' },
      { recording_id: 'rec_9', transcript_id: 't-rec_9', speaker_id: 'S4' },
    ],
  });
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

it('shows the first five new voices, continues on scroll, and retries every failed recording', async () => {
  const scrollTo = mockScrolling();
  const retried: string[] = [];
  const voices = Array.from({ length: 7 }, (_, i) => ({
    id: `voice_${i}`,
    members: [
      {
        recording_id: 'rec_1',
        filename: '周会.m4a',
        transcript_id: 't1',
        speaker_id: `S${i}`,
        seconds: 600 - i * 10,
      },
    ],
    seconds: 600 - i * 10,
    candidates: [],
    near: false,
  }));
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices, fragments: [], unsorted: [] });
      if (url.endsWith('/retry') && init?.method === 'POST') {
        retried.push(url);
        return json({});
      }
      throw new Error(url);
    }),
  );
  const failed = ['a', 'b'].map(
    (id) =>
      ({ id, filename: `${id}.m4a`, status: 'failed' }) as LibraryRecording,
  );
  render(
    <MemoryRouter initialEntries={['/?tab=todo']}>
      <ConfirmProvider>
        <Team version={0} recordings={failed} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const list = await screen.findByRole('list', { name: '新出现的声音' });
  expect(within(list).getAllByRole('listitem')).toHaveLength(5);
  expect(
    screen.getByText(/还有 2 个说得更少（共 18 分钟）/u),
  ).toBeInTheDocument();
  act(() => scrollTo('再看 2 个'));
  expect(within(list).getAllByRole('listitem')).toHaveLength(7);
  await userEvent.click(screen.getByRole('tab', { name: /转写失败/u }));
  await userEvent.click(screen.getByRole('button', { name: '全部重试' }));
  await waitFor(() =>
    expect(retried).toEqual([
      '/api/library/recordings/a/retry',
      '/api/library/recordings/b/retry',
    ]),
  );
});

it('asks for the first page of each list, and for more from the start as the owner scrolls', async () => {
  const scrollTo = mockScrolling();
  const voices = Array.from({ length: 12 }, (_, i) => ({
    id: `voice_${i}`,
    members: [
      {
        recording_id: `rec_${i}`,
        filename: `周会${i}.m4a`,
        transcript_id: 't1',
        speaker_id: 'S1',
        seconds: 1200 - i * 60,
      },
    ],
    seconds: 1200 - i * 60,
    candidates: [],
    near: false,
  }));
  const unsorted = Array.from({ length: 13 }, (_, i) => ({
    recording_id: `old_${i}`,
    filename: `旧会${i}.m4a`,
    speakers: 2,
    total: 2,
  }));
  // A new unnamed person, heard less than every voice: asked about last.
  people = [
    person({ id: 'per_new', name: '未命名 1', auto: true, seconds: 30 }),
  ];
  const asked: string[] = [];
  let hold: Promise<void> | null = null;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') {
        asked.push(url);
        return json({ items: people });
      }
      if (url.startsWith('/api/library/review?')) {
        asked.push(url);
        await hold;
        // As the server cuts a page (``review_queue.page``): the first so many of each list, and how many in all.
        const limits = new URL(url, 'http://localhost').searchParams;
        const first = <T,>(name: string, rows: T[]) =>
          rows.slice(0, Number(limits.get(name)));
        return json({
          items: [],
          voices: first('voices', voices),
          fragments: [],
          unsorted: first('unsorted', unsorted),
          suspects: [],
          totals: {
            voices: { count: 12, seconds: 10440 },
            enough: { count: 0, seconds: 0 },
            strangers: { count: 0, seconds: 0 },
            items: { count: 0 },
            unsorted: { count: 13 },
            suspects: { count: 0 },
          },
        });
      }
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter initialEntries={['/?tab=todo']}>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const list = await screen.findByRole('list', { name: '新出现的声音' });
  expect(asked).toEqual([
    '/api/library/people',
    '/api/library/review?voices=5&enough=5&strangers=5&items=10&unsorted=10&suspects=10',
  ]);
  expect(within(list).getAllByRole('listitem')).toHaveLength(5);
  // Counted from the totals, not from the five loaded.
  expect(screen.getByRole('tab', { name: /待处理/u })).toHaveTextContent(
    '待处理26',
  );
  expect(
    screen.getByText(/还有 8 个说得更少（共 85 分钟）/u),
  ).toBeInTheDocument();

  // The next page is asked for from the start; until it arrives the trigger waits instead of asking again.
  let release = () => {};
  hold = new Promise((resolve) => (release = resolve));
  act(() => scrollTo('再看 5 个'));
  await waitFor(() => expect(asked).toHaveLength(3));
  expect(asked[2]).toContain('voices=10&');
  expect(screen.getByRole('button', { name: '再看 5 个' })).toBeDisabled();
  act(() => release());
  await waitFor(() =>
    expect(within(list).getAllByRole('listitem')).toHaveLength(10),
  );
  // Two voices still to load may come before the new person: they are not shown past the last voice loaded.
  expect(screen.queryByText('未命名 1')).not.toBeInTheDocument();
  hold = null;
  act(() => scrollTo('再看 3 个'));
  await waitFor(() =>
    expect(within(list).getAllByRole('listitem')).toHaveLength(13),
  );
  expect(within(list).getAllByRole('listitem')[12]).toHaveTextContent(
    '未命名 1',
  );
  expect(asked.filter((url) => url === '/api/library/people')).toHaveLength(1);

  await userEvent.click(screen.getByRole('tab', { name: /还没认人/u }));
  expect(screen.getByRole('tab', { name: /还没认人/u })).toHaveTextContent(
    '13',
  );
  expect(screen.getAllByRole('link', { name: '试听并确认' })).toHaveLength(10);
  expect(screen.getByText('已显示 10 / 13')).toBeInTheDocument();
  act(() => scrollTo('继续加载待处理事项'));
  await waitFor(() =>
    expect(screen.getAllByRole('link', { name: '试听并确认' })).toHaveLength(
      13,
    ),
  );
  expect(asked.at(-1)).toContain('unsorted=20');
});

it('hears a confirmed voice again piece by piece, and gives what sounds like someone else to them', async () => {
  const user = userEvent.setup();
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
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({
          items: [],
          voices: [],
          fragments: [],
          unsorted: [],
          suspects: summary().open ? [summary()] : [],
        });
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
      if (url === '/api/personas') return json([]);
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter initialEntries={['/?tab=todo&cat=mixed']}>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const tasks = await screen.findByRole('region', {
    name: /可以补认的声音/u,
  });
  expect(tasks).toHaveTextContent('75% 不像张总（15 秒），已自动排除');
  expect(tasks).toHaveTextContent('多数像李总');
  // Left out already, it harms nobody: it waits under 有空再看 and is not counted as something to handle.
  expect(screen.getByText('有空再看')).toBeInTheDocument();
  expect(screen.getByRole('tab', { name: '待处理' })).toBeInTheDocument();
  await user.click(
    within(tasks).getByRole('button', { name: '听一听，决定是谁' }),
  );
  const side = await screen.findByRole('dialog', { name: '周会.m4a · S8' });
  const pieces = await within(side).findByRole('list', { name: '代表片段' });
  expect(within(pieces).getAllByRole('listitem')).toHaveLength(3);
  const first = within(pieces).getByText('研发不能砍。').closest('li')!;
  expect(first).toHaveTextContent('1:00 · 5 秒 · 更像李总研发不能砍。');
  expect(
    within(first).getByRole('button', { name: '听 1:00 这段' }),
  ).toBeInTheDocument();
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
  expect(await within(side).findAllByText(/已改给李总/u)).toHaveLength(2);
  const stranger = within(pieces).getByText('第3段').closest('li')!;
  expect(stranger).toHaveTextContent('不像团队里的任何人，已自动排除');
  expect(
    within(side).getByRole('button', { name: '其实都是张总' }),
  ).toBeInTheDocument();
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
  // Settled in full: the task leaves the team page; an undo is still a click away beside it.
  await waitFor(() => expect(screen.queryByText(/不像张总（/u)).toBeNull());
  await user.click(within(stranger).getByRole('button', { name: '撤销' }));
  await waitFor(() =>
    expect(puts[2]).toMatchObject({ units: [3], action: 'clear' }),
  );
});

it('offers the middle tier’s candidate for Enter, and says once when the voice sounds like someone else', async () => {
  const user = userEvent.setup();
  let voices = [
    {
      id: 'voice_mid',
      members: [
        {
          recording_id: 'rec_1',
          filename: 'rec_1.m4a',
          transcript_id: 't-rec_1',
          speaker_id: 'S1',
          seconds: 300,
        },
      ],
      seconds: 300,
      // Not so close that it is surely 张总, but far ahead of everyone else.
      candidates: [{ person_id: 'per_1', name: '张总', score: 0.66 }],
      near: false,
      tier: 'mid',
    },
  ];
  const posts: unknown[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices, fragments: [], unsorted: [] });
      if (url === '/api/library/voices' && init?.method === 'POST') {
        posts.push(JSON.parse(String(init.body)));
        voices = [];
        return json({
          person_id: 'per_1',
          recognised: 0,
          unlike: { person_id: 'per_2', name: '李总', score: 0.8 },
        });
      }
      if (url === '/api/personas') return json([]);
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter initialEntries={['/?tab=todo']}>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
        <ToastViewport />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const tasks = await screen.findByRole('region', { name: /新出现的声音/u });
  const row = within(tasks).getByText('多半是张总').closest('li')!;
  const field = within(row).getByRole('combobox');
  expect(field).toHaveValue('张总');
  await user.click(field);
  await user.keyboard('{Enter}');
  await waitFor(() =>
    expect(posts).toEqual([
      {
        members: [
          { recording_id: 'rec_1', transcript_id: 't-rec_1', speaker_id: 'S1' },
        ],
        action: 'confirm',
        person_id: 'per_1',
      },
    ]),
  );
  expect(await screen.findByRole('status')).toHaveTextContent(
    '这组声音听起来更像李总，已按你的选择记下',
  );
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
  await user.click(await screen.findByRole('button', { name: '2 段可抽查' }));
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
