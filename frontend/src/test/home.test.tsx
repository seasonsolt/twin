import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider } from '../components/ui';
import { Home } from '../pages/Home';
import type { LibraryState, Recording } from '../pages/Library';
import type { Person } from '../pages/Recording';
import { basePath } from '../lib/base';
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

it('starts an account without recordings from uploading one, with no card for making a twin of themselves', async () => {
  show();
  expect(
    await screen.findByRole('heading', { name: '从一段会议录音开始' }),
  ).toBeVisible();
  expect(
    screen.getByText(
      '不用先建档。传上来以后，系统分出每个人、认出已知的人，新出现的人自动建档。',
    ),
  ).toBeVisible();
  expect(screen.queryByRole('region', { name: '给自己建分身' })).toBeNull();
  expect(screen.queryByRole('textbox', { name: '分身名字' })).toBeNull();
  const drop = screen.getByRole('region', { name: '添加录音' });
  expect(within(drop).getByText('把会议录音拖到这里')).toBeVisible();
  expect(within(drop).getByRole('button', { name: '选择文件' })).toBeEnabled();
  expect(
    within(drop).getByText(
      '音频、视频都行，一次可以选多个。团队里参会的人也能看到。',
    ),
  ).toBeVisible();
  // What happens next, in order.
  const steps = screen.getByRole('list', { name: '接下来会发生什么' });
  expect(steps.tagName).toBe('OL');
  expect(
    within(steps)
      .getAllByRole('listitem')
      .map((step) => step.textContent),
  ).toEqual([
    '1转写，分出每个人每段录音只转写一次。',
    '2认人认得出的直接归位，拿不准的放进待处理请你听一下。',
    '3每人一个分身之后的录音自动补进他的记忆。',
  ]);
});

it('copies the site address as the invitation to colleagues', async () => {
  const writeText = vi.fn(async () => {});
  vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
  show();
  const invite = await screen.findByRole('region', { name: '邀请同事' });
  expect(within(invite).getByText('请同事来认自己')).toBeVisible();
  await userEvent.click(
    within(invite).getByRole('button', { name: '复制邀请链接' }),
  );
  expect(writeText).toHaveBeenCalledTimes(1);
  const [copied] = writeText.mock.calls[0] as unknown as [string];
  expect(copied).toBe(`${window.location.origin}${basePath()}/`);
  expect(copied).not.toContain('#');
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

it('shows the team and the way to upload more, with what waits left to the inbox', async () => {
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
  // Uploading is the side bar's button, said once.
  expect(screen.queryByRole('button', { name: '上传会议录音' })).toBeNull();
  // The people come first; what waits for the owner is the inbox's, not a tab of this page.
  const people_ = await screen.findByRole('tabpanel');
  expect(await within(people_).findByText('可以聊')).toBeInTheDocument();
  expect(within(people_).getByRole('button', { name: '聊天' })).toBeEnabled();
  expect(screen.getByRole('link', { name: '全部录音（2）' })).toHaveAttribute(
    'href',
    '/library',
  );
  expect(screen.queryByRole('tab', { name: /待处理/u })).toBeNull();
  expect(screen.queryByRole('region', { name: '正在处理' })).toBeNull();
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

it('renders neither queue when there are no actions or background work', async () => {
  state.recordings = [recording({})];
  show();
  await screen.findByRole('tab', { name: /成员/u });
  expect(screen.queryByText(/项待处理/u)).toBeNull();
  expect(screen.queryByRole('region', { name: '正在处理' })).toBeNull();
});

it('polls the library while recordings wait but asks for people and the review queue again only when one changes', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    state.recordings = [
      recording({}),
      recording({ id: 'rec_2', status: 'queued', speakers: 0 }),
    ];
    state.pending = 1;
    const fetcher = vi.mocked(fetch);
    const calls = (path: string) =>
      fetcher.mock.calls.filter(([url]) => url === path).length;
    show('/team');
    await vi.waitFor(() => expect(calls('/api/library/review')).toBe(1));
    await vi.advanceTimersByTimeAsync(9000);
    expect(calls('/api/library')).toBeGreaterThanOrEqual(3);
    expect(calls('/api/library/review')).toBe(1);
    expect(calls('/api/library/people')).toBe(1);
    state.recordings = [
      recording({}),
      recording({ id: 'rec_2', status: 'ready', unsettled: 2 }),
    ];
    state.pending = 0;
    await vi.advanceTimersByTimeAsync(3000);
    await vi.waitFor(() => expect(calls('/api/library/review')).toBe(2));
    expect(calls('/api/library/people')).toBe(2);
  } finally {
    vi.useRealTimers();
  }
});

it('keeps signing out and the palette on the team page of a phone, where there is no side bar', async () => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: query === '(max-width: 767px)',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  useAuth.setState({
    identity: {
      email: 'zhang@example.com',
      admin: false,
      auth_enabled: true,
    },
  });
  state.recordings = [recording({ people: ['张总'] })];
  show();
  await userEvent.click(await screen.findByRole('button', { name: '账户' }));
  const menu = await screen.findByRole('dialog', { name: '账户' });
  expect(
    within(menu).getByRole('button', { name: '退出登录' }),
  ).toBeInTheDocument();
});
