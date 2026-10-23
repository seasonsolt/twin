import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
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
      return json({ items: [], voices: [], fragments: [], unsorted: [] });
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
  // Room and queue are the system settings' to show: the page itself keeps to the recordings.
  expect(screen.queryByText(/还能放约/u)).toBeNull();
  expect(screen.queryByText(/排队 0/u)).toBeNull();
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
        '排队',
      ),
    ).toHaveLength(2),
  );
  expect(
    fetcher.mock.calls.every(([url]) => String(url).startsWith('/api/library')),
  ).toBe(true);
});

it('takes more recordings while one is uploading, after it and only once', async () => {
  const order: string[] = [];
  let release!: () => void;
  const held = new Promise<void>((done) => {
    release = done;
  });
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/library') return json(state);
    if (url.startsWith('/api/library/people') || url === '/api/library/review')
      return json({ items: [], voices: [], fragments: [], unsorted: [] });
    if (url === '/api/library/uploads') {
      const { filename } = JSON.parse(String(init?.body)) as {
        filename: string;
      };
      order.push(filename);
      if (filename === '一.m4a') await held;
      return json({ id: filename === '一.m4a' ? 'u1' : 'u2', offset: 0 });
    }
    if (url.includes('?offset=0')) return json({ offset: 3 });
    if (url.endsWith('/finish')) return json({ id: url, new: true });
    throw new Error(url);
  });
  vi.stubGlobal('fetch', fetcher);
  show();
  expect(await screen.findByText('还没有录音')).toBeInTheDocument();
  const user = userEvent.setup({ applyAccept: false });
  const first = new File(['abc'], '一.m4a', { lastModified: 1 });
  await user.upload(screen.getByLabelText('选择录音文件'), [first]);
  await waitFor(() => expect(order).toEqual(['一.m4a']));
  await user.upload(screen.getByLabelText('选择录音文件'), [
    new File(['abc'], '一.m4a', { lastModified: 1 }),
    new File(['def'], '二.wav', { lastModified: 2 }),
  ]);
  expect(order).toEqual(['一.m4a']);
  release();
  await waitFor(() => expect(order).toEqual(['一.m4a', '二.wav']));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.filter(([url]) => String(url).endsWith('/finish')),
    ).toHaveLength(2),
  );
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
      return json({ items: [], voices: [], fragments: [], unsorted: [] });
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
  expect(await screen.findByText('排队')).toBeInTheDocument();
  await userEvent.click(screen.getByLabelText('更多：周会.m4a'));
  await userEvent.click(screen.getByRole('button', { name: '删除' }));
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
  expect(screen.queryByText(/排队 1 \/ 20/u)).toBeNull();
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
  // Whoever is not named yet is a "?", and the button says how many to settle.
  const unnamed = await row('周会.m4a');
  expect(unnamed.getByRole('link', { name: '认 4 位说话人' })).toHaveAttribute(
    'href',
    '/library/a',
  );
  expect(
    unnamed.getByRole('img', { name: '参会人：4 位没认出' }),
  ).toBeVisible();
  const partly = await row('月会.m4a');
  expect(partly.getByRole('link', { name: '认 2 位说话人' })).toBeVisible();
  expect(
    partly.getByRole('img', { name: '参会人：张总、李总，2 位没认出' }),
  ).toBeVisible();
  const done = await row('季会.m4a');
  expect(done.getByText('都认出来了')).toBeInTheDocument();
  expect(done.queryByRole('link', { name: /说话人/u })).toBeNull();
});

it('says when the batch quota holds proofreading and twin updates back', async () => {
  state.recordings = [
    recording({ id: 'a', filename: '周会.m4a', proofread: 'waiting' }),
    recording({ id: 'b', filename: '月会.m4a', proofread: 'done' }),
  ];
  state.quota = {
    limit: 20_000_000,
    hours: 24,
    used: 20_000_000,
    exhausted: true,
    resets_at: '2026-10-18T08:00:00+00:00',
    waiting_proofread: 1,
    waiting_twins: 2,
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      json(url === '/api/library' ? state : { items: [] }),
    ),
  );
  show();
  const notice = await screen.findByText(/本批次的大模型额度已用完/u);
  expect(notice).toHaveTextContent('24 小时内已用 2,000 万 / 2,000 万 token');
  expect(notice).toHaveTextContent('1 段录音的校对和 2 个分身的记忆更新已暂停');
  expect(notice).toHaveTextContent('联系管理员');
  const row = async (name: string) =>
    within((await screen.findByRole('link', { name })).closest('li')!);
  expect((await row('周会.m4a')).getByText(/待校对/u)).toBeInTheDocument();
  expect((await row('月会.m4a')).getByText(/已校对/u)).toBeInTheDocument();
});

it('filters locally with counts, including proofreading in processing, and shows empty filter results', async () => {
  state.recordings = [
    recording({ id: 'a', filename: '待确认.m4a', unsettled: 2 }),
    recording({ id: 'b', filename: '完成.m4a' }),
    recording({ id: 'c', filename: '校对.m4a', proofread: 'waiting' }),
    recording({ id: 'd', filename: '排队.m4a', status: 'queued' }),
    recording({
      id: 'e',
      filename: '转写.m4a',
      status: 'transcribing',
      transcribed_s: 1500,
    }),
    recording({
      id: 'f',
      filename: '失败.m4a',
      status: 'failed',
      error: '识别失败',
    }),
  ];
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => json(state)),
  );
  show();
  const group = await screen.findByRole('group', { name: '录音分类' });
  await screen.findByRole('button', { name: '全部 6' });
  const calls = vi.mocked(fetch).mock.calls.length;
  expect(
    within(group).getByRole('button', { name: '处理中 3' }),
  ).toBeInTheDocument();
  await userEvent.click(
    within(group).getByRole('button', { name: '待确认 1' }),
  );
  expect(screen.getByRole('list', { name: '录音列表' }).children).toHaveLength(
    1,
  );
  expect(screen.getByRole('link', { name: '认 2 位说话人' })).toHaveAttribute(
    'href',
    '/library/a',
  );
  expect(screen.queryByText('完成.m4a')).toBeNull();
  await userEvent.click(
    within(group).getByRole('button', { name: '处理中 3' }),
  );
  expect(screen.getByRole('list', { name: '录音列表' }).children).toHaveLength(
    3,
  );
  expect(
    screen.getByRole('progressbar', { name: '转写.m4a转写进度' }),
  ).toHaveAttribute('aria-valuenow', '1500');
  await userEvent.click(within(group).getByRole('button', { name: '失败 1' }));
  expect(screen.getByText('识别失败')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls).toHaveLength(calls);
});

it('shows an empty category, and finds recordings by title or by who was in them', async () => {
  state.recordings = [
    recording({
      id: 'a',
      filename: '产品周会.m4a',
      people: ['林舟', '许清禾'],
    }),
    recording({ id: 'b', filename: '迭代复盘.m4a', people: ['周越'] }),
  ];
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => json(state)),
  );
  show();
  await screen.findByRole('button', { name: '全部 2' });
  await userEvent.click(screen.getByRole('button', { name: '失败 0' }));
  expect(screen.getByText('这一类里没有录音。')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: '全部 2' }));
  const list = () => screen.getByRole('list', { name: '录音列表' }).children;
  const search = screen.getByRole('searchbox', { name: '找录音' });
  await userEvent.type(search, '复盘');
  expect(list()).toHaveLength(1);
  expect(screen.getByText('迭代复盘.m4a')).toBeInTheDocument();
  await userEvent.clear(search);
  await userEvent.type(search, '许清禾');
  expect(list()).toHaveLength(1);
  expect(screen.getByText('产品周会.m4a')).toBeInTheDocument();
  await userEvent.clear(search);
  await userEvent.type(search, '没有这个人');
  expect(screen.getByText('没有找到。')).toBeInTheDocument();
});

it('takes files from the picker and dropped on the page, with the upload button only where there is no side bar', async () => {
  const order: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library') return json(state);
      if (url === '/api/library/uploads') {
        order.push(JSON.parse(String(init?.body)).filename);
        return json({ id: 'drop', offset: 0 });
      }
      if (url.includes('?offset=0')) return json({ offset: 3 });
      if (url.endsWith('/finish')) return json({ id: 'rec', new: true });
      throw new Error(url);
    }),
  );
  show();
  await screen.findByText('还没有录音');
  // Any file can be picked (some Windows machines grey .m4a out of a filtered picker); the page skips what is not media.
  expect(screen.getByLabelText('选择录音文件')).not.toHaveAttribute('accept');
  // The side bar uploads; the page has no second button for it.
  expect(screen.queryByRole('button', { name: '上传录音' })).toBeNull();
  fireEvent.drop(screen.getByRole('region', { name: '拖放上传录音' }), {
    dataTransfer: {
      files: [new File(['abc'], '拖入.m4a', { type: 'audio/mp4' })],
    },
  });
  await waitFor(() => expect(order).toEqual(['拖入.m4a']));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      '/api/library/uploads/drop/finish',
      expect.anything(),
    ),
  );
});

it('shows a colleague’s meeting one was in without its controls, and says when a colleague uploaded a file first', async () => {
  state.recordings = [
    recording({
      id: 'rec_2',
      filename: '客户会.m4a',
      unsettled: 2,
      can_edit: false,
    }),
  ];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library') return json(state);
      if (url === '/api/library/uploads') return json({ id: 'u1', offset: 0 });
      if (url.includes('?offset=0')) return json({ offset: 3 });
      if (url.endsWith('/finish'))
        return json({
          id: 'rec_9',
          filename: '周会.m4a',
          new: false,
          mine: false,
        });
      throw new Error(url);
    }),
  );
  show();
  const row = (await screen.findByText('客户会.m4a')).closest('li')!;
  expect(within(row).getByText('你参加的')).toBeInTheDocument();
  expect(within(row).queryByRole('button')).toBeNull();
  expect(within(row).queryByRole('link', { name: '确认说话人' })).toBeNull();
  await userEvent
    .setup({ applyAccept: false })
    .upload(screen.getByLabelText('选择录音文件'), [
      new File(['abc'], '周会.m4a'),
    ]);
  expect(
    await screen.findByText('「周会.m4a」已经有同事上传过，由 TA 整理'),
  ).toBeInTheDocument();
});

it('offers recordings a newer transcription would collect again, and goes back to the earlier one', async () => {
  const user = userEvent.setup();
  state.recordings = [
    recording({ id: 'a', filename: '周会.m4a' }),
    recording({ id: 'b', filename: '月会.m4a', previous: 't-old' }),
  ];
  let recollect = {
    service: '1.4.1/overlap',
    recordings: [
      {
        id: 'a',
        filename: '周会.m4a',
        asr: null,
        asked: null as string | null,
      },
      {
        id: 'c',
        filename: '季会.m4a',
        asr: '1.3.3',
        asked: null as string | null,
      },
    ],
  };
  const posts: { url: string; body?: unknown }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library') return json(state);
      if (url === '/api/library/recollect' && init?.method === 'POST') {
        posts.push({ url, body: JSON.parse(String(init.body)) });
        recollect = {
          ...recollect,
          recordings: recollect.recordings.map((r) =>
            r.id === 'a' ? { ...r, asked: 'now' } : r,
          ),
        };
        return json({ asked: 1 });
      }
      if (url === '/api/library/recollect') return json(recollect);
      if (url === '/api/library/recordings/b/rollback') {
        posts.push({ url });
        return json({});
      }
      return json({ items: [] });
    }),
  );
  show();
  // No banner: one recording at a time from its own menu, or all that are offered from the page's.
  expect(screen.queryByText(/可以用新版转写重新采集/u)).toBeNull();
  await user.click(await screen.findByLabelText('更多'));
  await user.click(
    screen.getByRole('button', { name: '用新版转写重新采集（2）' }),
  );
  const dialog = await screen.findByRole('dialog', {
    name: '用新版转写重新采集',
  });
  // Every one is chosen at first; the owner leaves out what they want kept as it is.
  await user.click(within(dialog).getByRole('checkbox', { name: '季会.m4a' }));
  await user.click(
    within(dialog).getByRole('button', { name: '重新采集 1 份' }),
  );
  await waitFor(() =>
    expect(posts).toEqual([
      { url: '/api/library/recollect', body: { recordings: ['a'] } },
    ]),
  );
  // Asked for, the recording is in 处理中 and says so.
  await user.click(await screen.findByRole('button', { name: '处理中 1' }));
  expect(await screen.findByText('重新采集中')).toBeVisible();
  await user.click(screen.getByRole('button', { name: '全部 2' }));

  await user.click(await screen.findByLabelText('更多：月会.m4a'));
  await user.click(
    await screen.findByRole('button', { name: '回到上一版转写' }),
  );
  const asked = await screen.findByRole('dialog', {
    name: '「月会.m4a」回到上一版转写？',
  });
  await user.click(within(asked).getByRole('button', { name: '回到上一版' }));
  await waitFor(() =>
    expect(posts[1]).toEqual({ url: '/api/library/recordings/b/rollback' }),
  );
});

it('keeps an upload button on a phone, where there is no side bar', async () => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => json(state)),
  );
  show();
  await screen.findByText('还没有录音');
  const click = vi.spyOn(screen.getByLabelText('选择录音文件'), 'click');
  await userEvent.click(screen.getByRole('button', { name: '上传录音' }));
  expect(click).toHaveBeenCalledOnce();
});

it('offers to collect one recording again from its own menu, after asking', async () => {
  const user = userEvent.setup();
  state.recordings = [recording({ id: 'a', filename: '周会.m4a' })];
  const posts: unknown[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library') return json(state);
      if (url === '/api/library/recollect' && init?.method === 'POST') {
        posts.push(JSON.parse(String(init.body)));
        return json({ asked: 1 });
      }
      if (url === '/api/library/recollect')
        return json({
          service: '1.5.0',
          recordings: [
            { id: 'a', filename: '周会.m4a', asr: null, asked: null },
          ],
        });
      return json({ items: [] });
    }),
  );
  show();
  await user.click(await screen.findByLabelText('更多：周会.m4a'));
  await user.click(screen.getByRole('button', { name: '重新采集' }));
  const ask = await screen.findByRole('dialog', {
    name: '重新采集「周会.m4a」？',
  });
  await user.click(within(ask).getByRole('button', { name: '重新采集' }));
  await waitFor(() => expect(posts).toEqual([{ recordings: ['a'] }]));
});
