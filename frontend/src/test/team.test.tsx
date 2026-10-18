import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider } from '../components/ui';
import { Team } from '../features/library/Team';
import { Recording, type Person, type Speaker } from '../pages/Recording';
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
  const card = (await screen.findByRole('heading', { name: 'S1' })).closest(
    'li',
  )!;
  const scope = within(card);
  expect(scope.getAllByLabelText(/S1 试听/u)).toHaveLength(2);
  expect(scope.getByText('张总 82%')).toBeInTheDocument();
  // A voice match is only a hint: nothing is chosen until the owner chooses.
  expect(scope.getByLabelText('这是谁')).toHaveValue('');
  expect(scope.getByRole('button', { name: '确认' })).toBeDisabled();
  await userEvent.selectOptions(scope.getByLabelText('这是谁'), 'per_1');
  await userEvent.click(scope.getByLabelText(/用作声纹样本/u));
  await userEvent.click(scope.getByRole('button', { name: '确认' }));
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
  const card = (await screen.findByRole('heading', { name: 'S1' })).closest(
    'li',
  )!;
  revision = 4; // Changed elsewhere meanwhile.
  await userEvent.click(
    within(card).getByRole('button', { name: '几个人混在一起' }),
  );
  expect(await screen.findByRole('alert')).toHaveTextContent('请刷新后再确认');
  await userEvent.click(
    within(
      (await screen.findByRole('heading', { name: 'S1' })).closest('li')!,
    ).getByRole('button', { name: '不是张总' }),
  );
  await waitFor(() => expect(puts).toHaveLength(2));
  expect(puts[1]).toMatchObject({
    revision: 4,
    action: 'reject',
    person_id: 'per_1',
  });
});

it('creates a twin for a confirmed person and shows when its memory is updating', async () => {
  const created: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url === '/api/library/review')
        return json({
          items: [
            {
              ...speaker({
                candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
              }),
              recording_id: 'rec_9',
              filename: '月会.m4a',
            },
          ],
        });
      if (
        url === '/api/library/people/per_1/persona' &&
        init?.method === 'POST'
      ) {
        created.push(url);
        people = [person({ persona_id: 'p-1', updating: true }), people[1]];
        return json({ persona_id: 'p-1', new: true });
      }
      if (url === '/api/personas') return json({ items: [], default: null });
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
  const tasks = await screen.findByRole('region', { name: '需要你处理' });
  expect(await within(tasks).findByText(/S1 像张总/u)).toBeInTheDocument();
  expect(
    within(tasks).getByRole('link', { name: '试听并确认' }),
  ).toHaveAttribute('href', '/library/rec_9');
  const row = screen.getByText('张总', { selector: 'p' }).closest('li')!;
  expect(within(row).getByText('还没有分身')).toBeInTheDocument();
  await userEvent.click(within(row).getByRole('button', { name: '生成分身' }));
  expect(await screen.findByText('记忆更新中')).toBeInTheDocument();
  expect(created).toHaveLength(1);
});

it('marks speakers recognised by voice and lets the owner say it is someone else', async () => {
  showRecording();
  const card = (await screen.findByRole('heading', { name: 'S3' })).closest(
    'li',
  )!;
  expect(within(card).getByText('按声音自动认出')).toBeInTheDocument();
  await userEvent.click(within(card).getByRole('button', { name: '不是张总' }));
  await waitFor(() => expect(puts).toHaveLength(1));
  expect(puts[0]).toMatchObject({
    url: '/api/library/recordings/rec_1/speakers/S3',
    action: 'reject',
    person_id: 'per_1',
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
      if (url === '/api/library/review') return json({ items: [] });
      if (url === '/api/library/people/per_9' && init?.method === 'PATCH') {
        patches.push(JSON.parse(String(init.body)));
        people = [person({}), person({ id: 'per_9', name: '李总' })];
        return json({ renamed: true });
      }
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
  const fresh = await screen.findByRole('region', { name: '需要你处理' });
  expect(within(fresh).getByText(/未命名 1/u)).toBeInTheDocument();
  expect(
    within(fresh).queryByRole('button', { name: '生成分身' }),
  ).not.toBeInTheDocument();
  expect(
    within(fresh).getByRole('link', { name: '试听并确认' }),
  ).toHaveAttribute('href', '/library/rec_9');
  await userEvent.type(within(fresh).getByLabelText('给未命名 1起名'), '李总');
  await userEvent.click(within(fresh).getByRole('button', { name: '起名' }));
  await waitFor(() => expect(patches).toEqual([{ name: '李总' }]));
  // Named, they can have twins like anyone else.
  expect(
    await screen.findAllByRole('button', { name: '生成分身' }),
  ).toHaveLength(2);
  expect(screen.queryByRole('region', { name: '需要你处理' })).toBeNull();
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
      if (url === '/api/library/review') return json({ items: [] });
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
  await userEvent.click(within(row).getByRole('button', { name: '编辑张总' }));
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
  await userEvent.click(screen.getByRole('button', { name: '张总监的档案' }));
  expect(await screen.findByText('档案页')).toBeInTheDocument();
  expect(switched).toEqual(['p-1']);
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
      if (url === '/api/library/review') return json({ items: [] });
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
    <MemoryRouter>
      <ConfirmProvider>
        <Team version={0} recordings={[]} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const first = await screen.findByLabelText('给未命名 1起名');
  await userEvent.type(first, '张总');
  await userEvent.click(
    within(first.closest('li')!).getByRole('button', { name: '起名' }),
  );
  const next = screen.getByLabelText('给未命名 2起名');
  await waitFor(() => expect(next).toHaveFocus());
  await userEvent.type(next, '李总');
  await userEvent.click(
    within(next.closest('li')!).getByRole('button', { name: '起名' }),
  );
  await waitFor(() =>
    expect(screen.queryByRole('region', { name: '需要你处理' })).toBeNull(),
  );
  expect(screen.queryByRole('region', { name: '正在处理' })).toBeNull();
  expect(screen.getAllByRole('region')[0]).toHaveAccessibleName('人物');
});

it('returns from a speaker confirmation to focus the next pending team item', async () => {
  const originalFetch = fetch;
  let reviewed = false;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/review')
        return json({
          items: reviewed
            ? []
            : [
                {
                  ...speaker({
                    candidates: [
                      { person_id: 'per_1', name: '张总', score: 0.7 },
                    ],
                  }),
                  recording_id: 'rec_1',
                  filename: '周会.m4a',
                },
              ],
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
    <MemoryRouter initialEntries={['/team']}>
      <ConfirmProvider>
        <Routes>
          <Route path="/team" element={<Team version={0} recordings={[]} />} />
          <Route path="/library/:recordingId" element={<Recording />} />
        </Routes>
      </ConfirmProvider>
    </MemoryRouter>,
  );
  const tasks = await screen.findByRole('region', { name: '需要你处理' });
  const waiting = within(tasks).getByText('拿不准是谁').closest('li')!;
  await userEvent.click(
    within(waiting).getByRole('link', { name: '试听并确认' }),
  );
  const card = (await screen.findByRole('heading', { name: 'S1' })).closest(
    'li',
  )!;
  await userEvent.selectOptions(within(card).getByLabelText('这是谁'), 'per_1');
  await userEvent.click(within(card).getByRole('button', { name: '确认' }));
  await waitFor(() =>
    expect(screen.getByLabelText('给未命名 1起名')).toHaveFocus(),
  );
  expect(screen.queryByText('拿不准是谁')).toBeNull();
});

it('keeps uploads in the quiet processing group with progress and a stop action', async () => {
  const stop = vi.fn();
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: [] });
      if (url === '/api/library/review') return json({ items: [] });
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter>
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
  expect(screen.queryByRole('region', { name: '需要你处理' })).toBeNull();
  await userEvent.click(
    within(progress).getByRole('button', { name: /停止上传/u }),
  );
  expect(stop).toHaveBeenCalledOnce();
});
