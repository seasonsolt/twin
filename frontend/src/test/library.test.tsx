import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider } from '../components/ui';
import { Library, type LibraryState, type Recording } from '../pages/Library';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const recording = (change: Partial<Recording>): Recording => ({
  id: 'rec_1',
  filename: '周会.m4a',
  size: 10,
  kind: 'audio',
  status: 'ready',
  error: '',
  duration_s: 3000,
  transcribed_s: 3000,
  speakers: 4,
  segments: 900,
  created_at: 'now',
  people: [],
  unsettled: 0,
  ...change,
});
let state: LibraryState;
beforeEach(() => {
  localStorage.clear();
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
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
});
afterEach(() => vi.restoreAllMocks());

const show = () =>
  render(
    <MemoryRouter>
      <ConfirmProvider>
        <Library />
      </ConfirmProvider>
    </MemoryRouter>,
  );

it('uploads several recordings to the account library one after another', async () => {
  const order: string[] = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/library') return json(state);
    if (url.startsWith('/api/library/people') || url === '/api/library/review')
      return json({ items: [] });
    if (url === '/api/library/uploads') {
      const { filename } = JSON.parse(String(init?.body)) as {
        filename: string;
      };
      order.push(filename);
      if (filename === '超额.mp3')
        return json({ detail: '最多同时排队 20 个文件' }, 409);
      return json({ id: filename === '一.m4a' ? 'u1' : 'u2', offset: 0 });
    }
    if (url.includes('?offset=0')) return json({ offset: 3 });
    if (url.endsWith('/finish')) {
      state.recordings.push(recording({ id: url, status: 'queued' }));
      return json({ id: url, new: true });
    }
    throw new Error(url);
  });
  vi.stubGlobal('fetch', fetcher);
  show();
  expect(await screen.findByText('还没有录音')).toBeInTheDocument();
  expect(screen.getByText(/还可添加约 30.0 GB/u)).toBeInTheDocument();
  await userEvent
    .setup({ applyAccept: false })
    .upload(screen.getByLabelText('选择录音文件'), [
      new File(['abc'], '一.m4a'),
      new File(['def'], '二.wav'),
      new File(['x'], '笔记.txt'),
    ]);
  await waitFor(() => expect(order).toEqual(['一.m4a', '二.wav']));
  expect(screen.getByText('已跳过 1 个不是音视频的文件')).toBeInTheDocument();
  await waitFor(() =>
    expect(
      within(screen.getByRole('list', { name: '录音列表' })).getAllByText(
        '排队中',
      ),
    ).toHaveLength(2),
  );
  expect(
    fetcher.mock.calls.every(([url]) => String(url).startsWith('/api/library')),
  ).toBe(true);
});

it('shows failures with a retry and asks before deleting', async () => {
  state.recordings = [
    recording({
      status: 'failed',
      error: '语音识别失败，请检查转写服务后重试',
    }),
  ];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/library') return json(state);
    if (url.startsWith('/api/library/people') || url === '/api/library/review')
      return json({ items: [] });
    if (url.endsWith('/retry')) {
      state.recordings = [recording({ status: 'queued', error: '' })];
      return json(state.recordings[0], 202);
    }
    if (init?.method === 'DELETE') {
      state.recordings = [];
      return json({ deleted: true });
    }
    throw new Error(url);
  });
  vi.stubGlobal('fetch', fetcher);
  show();
  expect(
    await screen.findByText('语音识别失败，请检查转写服务后重试'),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: '重试' }));
  expect(await screen.findByText('排队中')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: '删除周会.m4a' }));
  await userEvent.click(
    within(await screen.findByRole('dialog')).getByRole('button', {
      name: '删除录音',
    }),
  );
  expect(await screen.findByText('还没有录音')).toBeInTheDocument();
});

it('says recordings wait when no diarizing transcription service is set up', async () => {
  state.asr = false;
  state.pending = 1;
  state.recordings = [recording({ status: 'queued', duration_s: null })];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      json(url === '/api/library' ? state : { items: [] }),
    ),
  );
  show();
  expect(
    await screen.findByText(/还没有配置能区分说话人的转写服务/u),
  ).toBeInTheDocument();
  expect(screen.getByText(/排队 1 \/ 20 个/u)).toBeInTheDocument();
});

it('tells for each transcribed recording whether its speakers are identified', async () => {
  state.recordings = [
    recording({ id: 'a', filename: '周会.m4a', unsettled: 4 }),
    recording({
      id: 'b',
      filename: '月会.m4a',
      people: ['张总', '李总'],
      unsettled: 2,
    }),
    recording({
      id: 'c',
      filename: '季会.m4a',
      people: ['张总'],
      unsettled: 0,
    }),
  ];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      json(url === '/api/library' ? state : { items: [] }),
    ),
  );
  show();
  const row = async (name: string) =>
    within((await screen.findByRole('link', { name })).closest('li')!);
  expect((await row('周会.m4a')).getByText('还没认人')).toBeInTheDocument();
  const partly = await row('月会.m4a');
  expect(partly.getByText('2 位待确认')).toBeInTheDocument();
  expect(partly.getByText(/张总、李总/u)).toBeInTheDocument();
  expect((await row('季会.m4a')).getByText('已认人')).toBeInTheDocument();
});
