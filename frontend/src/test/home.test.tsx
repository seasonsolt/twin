import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider } from '../components/ui';
import { Home } from '../pages/Home';
import type { LibraryState, Recording } from '../pages/Library';
import type { Person } from '../pages/Recording';
import { useAuth } from '../stores/auth';
import { usePersonas } from '../stores/personas';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
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
let state: LibraryState;
let people: Person[];
let unsorted: unknown[];
beforeEach(() => {
  unsorted = [];
  state = {
    recordings: [],
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
  people = [];
  useAuth.setState({ identity: null });
  usePersonas.setState({ items: [] });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library') return json(state);
      if (url === '/api/personas') return json(usePersonas.getState().items);
      if (url === '/api/library/people') return json({ items: people });
      if (url === '/api/library/review')
        return json({ items: [], voices: [], fragments: [], unsorted });
      throw new Error(url);
    }),
  );
});
afterEach(() => vi.restoreAllMocks());

const show = (entry = '/') =>
  render(
    <MemoryRouter initialEntries={[entry]}>
      <ConfirmProvider>
        <Home />
      </ConfirmProvider>
    </MemoryRouter>,
  );

it('starts an account without recordings or a twin from two cards: a twin of themselves, or the team’s recordings', async () => {
  show();
  const self = await screen.findByRole('region', { name: '给自己建分身' });
  expect(
    within(self).getByRole('textbox', { name: '分身名字' }),
  ).toBeInTheDocument();
  expect(
    within(self).getByText('下一步：加一段会议录音，勾出哪位是你。'),
  ).toBeInTheDocument();
  const team = screen.getByRole('region', { name: '从团队会议录音开始' });
  expect(
    within(team).getByRole('region', { name: '添加录音' }),
  ).toBeInTheDocument();
  expect(within(team).getByRole('button', { name: '选择文件' })).toBeEnabled();
  expect(
    screen.getByRole('list', { name: '接下来会发生什么' }).children,
  ).toHaveLength(3);
});

it('starts an account that has its own twin from uploading a recording, not from another twin', async () => {
  usePersonas.setState({
    items: [
      {
        id: 'p-own',
        name: '我',
        avatar_url: null,
        sources: 3,
        created_at: '',
        is_default: false,
        can_manage: true,
      },
    ],
  });
  show();
  expect(
    await screen.findByRole('heading', { name: '从一段会议录音开始' }),
  ).toBeInTheDocument();
  expect(screen.getByRole('region', { name: '添加录音' })).toBeInTheDocument();
  expect(screen.queryByRole('region', { name: '给自己建分身' })).toBeNull();
});

it('shows the team, what needs settling and the way to upload more', async () => {
  state.pending = 1;
  state.recordings = [
    recording({ people: ['张总'], unsettled: 1 }),
    recording({
      id: 'rec_2',
      filename: '月会.m4a',
      status: 'transcribing',
      transcribed_s: 300,
    }),
  ];
  // A speaker without a voiceprint is in no voice: the server lists its recording.
  unsorted = [
    { recording_id: 'rec_1', filename: '周会.m4a', speakers: 1, total: 3 },
  ];
  people = [
    {
      id: 'per_1',
      name: '张总',
      persona_id: 'p-1',
      speakers: 2,
      seconds: 1200,
      samples: 1,
      updating: false,
      auto: false,
      gender: '',
      recording_id: 'rec_1',
      speaker_id: 'S1',
    },
  ];
  show();
  expect(await screen.findByRole('heading', { name: '团队' })).toBeVisible();
  expect(
    screen.getByRole('button', { name: '上传会议录音' }),
  ).toBeInTheDocument();
  // The people come first; what waits for the owner is one tab away, counted.
  const people_ = await screen.findByRole('tabpanel');
  expect(await within(people_).findByText('可以聊')).toBeInTheDocument();
  expect(
    within(people_).getByRole('button', { name: '和分身聊聊' }),
  ).toBeEnabled();
  expect(screen.getByRole('link', { name: '全部录音（2）' })).toHaveAttribute(
    'href',
    '/library',
  );
  expect(screen.getByRole('tab', { name: /待处理.*1/u })).toBeInTheDocument();
  await userEvent.click(
    within(people_).getByRole('button', { name: '去处理' }),
  );
  const tasks = await screen.findByRole('region', { name: /还没认人/u });
  const progress = screen.getByRole('region', { name: '正在处理' });
  expect(within(progress).getByRole('progressbar')).toHaveAttribute(
    'aria-valuenow',
    '300',
  );
  expect(within(progress).getByText('月会.m4a · 转写中')).toBeInTheDocument();
  expect(within(tasks).queryByText(/月会/u)).toBeNull();
  // A speaker no voice holds still asks for the owner, through its recording.
  expect(within(tasks).getByText('还有 1 位没认')).toBeInTheDocument();
  expect(
    within(tasks).getByRole('link', { name: '试听并确认' }),
  ).toHaveAttribute('href', '/library/rec_1');
});

it('keeps the service status off the team page, even for administrators', async () => {
  useAuth.setState({
    identity: { email: 'a@example.com', admin: true, auth_enabled: true },
  });
  show();
  await screen.findByRole('heading', { name: '从团队会议录音开始' });
  expect(screen.queryByText('GPU 服务')).toBeNull();
  expect(
    vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('admin')),
  ).toBe(false);
});

it('counts only actions while keeping queued work and memory organisation quiet', async () => {
  people = [
    {
      id: 'new',
      name: '未命名 1',
      persona_id: null,
      speakers: 1,
      seconds: 600,
      samples: 1,
      updating: false,
      auto: true,
      gender: '',
      recording_id: 'rec_1',
      speaker_id: 'S1',
    },
    {
      id: 'known',
      name: '张总',
      persona_id: 'p-1',
      speakers: 1,
      seconds: 600,
      samples: 1,
      updating: true,
      auto: false,
      gender: '',
      recording_id: 'rec_1',
      speaker_id: 'S1',
    },
  ];
  state.recordings = [
    recording({ status: 'failed' }),
    recording({ id: 'queued', filename: '排队.m4a', status: 'queued' }),
    recording({ id: 'proofread', filename: '校对.m4a', proofread: 'waiting' }),
  ];
  show('/?tab=todo');
  const tasks = await screen.findByRole('region', { name: /新出现的声音/u });
  expect(
    await within(tasks).findByRole('list', { name: '新出现的声音' }),
  ).toBeInTheDocument();
  // Only what asks for the owner is counted: not the queued, proofread or organising work.
  expect(screen.getByRole('tab', { name: /待处理.*2/u })).toBeInTheDocument();
  expect(within(tasks).getAllByRole('listitem')).toHaveLength(1);
  await userEvent.click(screen.getByRole('tab', { name: /转写失败/u }));
  expect(
    await screen.findByRole('button', { name: '重试' }),
  ).toBeInTheDocument();
  const progress = screen.getByRole('region', { name: '正在处理' });
  expect(within(progress).getByText('正在处理 3 项')).toBeInTheDocument();
  expect(within(progress).getByText('排队.m4a · 排队转写')).toBeInTheDocument();
  expect(within(progress).getByText('校对.m4a · 等待校对')).toBeInTheDocument();
  expect(within(progress).getByText('张总 · 整理记忆中')).toBeInTheDocument();
});

it('retries through the existing endpoint and moves the recording into processing', async () => {
  state.recordings = [recording({ status: 'failed' })];
  const originalFetch = fetch;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (
        url === '/api/library/recordings/rec_1/retry' &&
        init?.method === 'POST'
      ) {
        state = {
          ...state,
          pending: 1,
          recordings: [recording({ status: 'queued' })],
        };
        return json(state.recordings[0]);
      }
      return originalFetch(url, init);
    }),
  );
  show('/?tab=todo');
  await userEvent.click(await screen.findByRole('button', { name: '重试' }));
  await screen.findByText('现在没有需要你处理的事。');
  expect(
    within(screen.getByRole('region', { name: '正在处理' })).getByText(
      '周会.m4a · 排队转写',
    ),
  ).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith(
    '/api/library/recordings/rec_1/retry',
    expect.objectContaining({ method: 'POST' }),
  );
});

it('renders neither queue when there are no actions or background work', async () => {
  state.recordings = [recording({})];
  show();
  await screen.findByRole('tab', { name: /人物/u });
  expect(screen.queryByText(/项待处理/u)).toBeNull();
  expect(screen.queryByRole('region', { name: '正在处理' })).toBeNull();
});

it('deletes a failed recording only after confirmation and reloads the team', async () => {
  state.recordings = [recording({ status: 'failed' })];
  const originalFetch = fetch;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (
        url === '/api/library/recordings/rec_1' &&
        init?.method === 'DELETE'
      ) {
        state.recordings = [recording({ id: 'keep', filename: '保留.m4a' })];
        return json({ deleted: true });
      }
      return originalFetch(url, init);
    }),
  );
  show('/?tab=todo');
  const tasks = await screen.findByRole('region', { name: /转写失败/u });
  await userEvent.click(within(tasks).getByRole('button', { name: '删除' }));
  const dialog = await screen.findByRole('dialog', {
    name: '删除「周会.m4a」？',
  });
  expect(
    vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === 'DELETE'),
  ).toBe(false);
  await userEvent.click(
    within(dialog).getByRole('button', { name: '删除录音' }),
  );
  await screen.findByText('现在没有需要你处理的事。');
  expect(fetch).toHaveBeenCalledWith(
    '/api/library/recordings/rec_1',
    expect.objectContaining({ method: 'DELETE' }),
  );
});
