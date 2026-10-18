import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider } from '../components/ui';
import { Home } from '../pages/Home';
import type { LibraryState, Recording } from '../pages/Library';
import type { Person } from '../pages/Recording';
import { useAuth } from '../stores/auth';

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
beforeEach(() => {
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
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library') return json(state);
      if (url === '/api/library/people') return json({ items: people });
      if (url === '/api/library/review') return json({ items: [] });
      throw new Error(url);
    }),
  );
});
afterEach(() => vi.restoreAllMocks());

const show = () =>
  render(
    <MemoryRouter>
      <ConfirmProvider>
        <Home />
      </ConfirmProvider>
    </MemoryRouter>,
  );

it('starts an account without recordings from uploading one, not from setting up a twin', async () => {
  show();
  expect(
    await screen.findByRole('heading', { name: '从一段会议录音开始' }),
  ).toBeInTheDocument();
  expect(screen.getByRole('region', { name: '添加录音' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '选择文件' })).toBeEnabled();
  expect(
    screen.getByRole('list', { name: '接下来会发生什么' }).children,
  ).toHaveLength(3);
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
    },
  ];
  show();
  expect(await screen.findByRole('heading', { name: '团队' })).toBeVisible();
  expect(
    screen.getByRole('button', { name: '上传会议录音' }),
  ).toBeInTheDocument();
  const tasks = await screen.findByRole('region', { name: '需要你处理' });
  const progress = screen.getByRole('region', { name: '正在处理' });
  expect(
    within(progress).getByText('月会.m4a · 转写中 50%'),
  ).toBeInTheDocument();
  expect(
    within(tasks).getByText('1', { selector: 'span' }),
  ).toBeInTheDocument();
  expect(within(tasks).queryByText(/月会/u)).toBeNull();
  // A speaker nobody resembles still asks for the owner, through its recording.
  expect(within(tasks).getByText('还有人没认')).toBeInTheDocument();
  expect(
    within(tasks).getByRole('link', { name: '试听并确认' }),
  ).toHaveAttribute('href', '/library/rec_1');
  const people_ = screen.getByRole('region', { name: '人物' });
  expect(await within(people_).findByText('可以聊')).toBeInTheDocument();
  expect(
    within(people_).getByRole('button', { name: '和分身聊聊' }),
  ).toBeEnabled();
  expect(screen.getByRole('link', { name: '全部录音（2）' })).toHaveAttribute(
    'href',
    '/library',
  );
});

it('keeps the service status off the team page, even for administrators', async () => {
  useAuth.setState({
    identity: { email: 'a@example.com', admin: true, auth_enabled: true },
  });
  show();
  await screen.findByRole('heading', { name: '从一段会议录音开始' });
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
    },
  ];
  state.recordings = [
    recording({ status: 'failed' }),
    recording({ id: 'queued', filename: '排队.m4a', status: 'queued' }),
    recording({ id: 'proofread', filename: '校对.m4a', proofread: 'waiting' }),
  ];
  show();
  const tasks = await screen.findByRole('region', { name: '需要你处理' });
  expect(await within(tasks).findByText('新出现的声音')).toBeInTheDocument();
  expect(
    within(tasks).getByText('2', { selector: 'span' }),
  ).toBeInTheDocument();
  expect(within(tasks).getAllByRole('listitem')).toHaveLength(2);
  expect(
    within(tasks).getByRole('button', { name: '重试' }),
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
  show();
  await userEvent.click(await screen.findByRole('button', { name: '重试' }));
  await waitFor(() =>
    expect(screen.queryByRole('region', { name: '需要你处理' })).toBeNull(),
  );
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
  await screen.findByRole('region', { name: '人物' });
  expect(screen.queryByRole('region', { name: '需要你处理' })).toBeNull();
  expect(screen.queryByRole('region', { name: '正在处理' })).toBeNull();
});
