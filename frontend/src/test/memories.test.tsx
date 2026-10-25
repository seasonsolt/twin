import type { Processing } from '../features/memories/BuildProgress';
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider, toast } from '../components/ui';
import { addedOn, Memories, type Memory } from '../pages/Memories';
import { api } from '../lib/api';
import { useAuth } from '../stores/auth';
import { useStatus } from '../stores/status';
import { isSourcesUrl, sourcesPage } from './personaApi';

vi.mock('../lib/mediaUpload', async (original) => ({
  ...(await original<typeof import('../lib/mediaUpload')>()),
  uploadForm: (path: string, form: FormData, signal: AbortSignal) =>
    api(path, { method: 'POST', form, signal }),
}));

vi.mock('../components/ui', async (original) => ({
  ...(await original<typeof import('../components/ui')>()),
  toast: vi.fn(),
}));
vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const memory: Memory = {
  source_id: 's/1',
  title: '我的经历',
  first_date: '2024-01-01',
  detected_kind_label: '文档',
  status: 'remembered',
  remembered: 3,
};
let rows: Memory[];
let state: Processing & {
  last_error?: string;
  notice?: string;
  kernel_rebuild?: string;
  kernel_pending?: number;
};
const v4 = { schema: 1, prompt: 'persona-v4', taxonomy: 'v1' };
const v5 = { schema: 1, prompt: 'persona-v5', taxonomy: 'v1' };
let kernel: Record<string, unknown>;
let fetcher: ReturnType<typeof vi.fn>;
let importError: boolean;
beforeEach(() => {
  rows = [memory];
  state = { state: 'idle' };
  kernel = {
    version: v4,
    built: v4,
    scope: 'none',
    pending_chunks: 0,
    state: 'ready',
  };
  useStatus.setState({ data: null, error: null });
  importError = false;
  vi.mocked(toast).mockClear();
  fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (isSourcesUrl(url)) return json(sourcesPage(url, rows));
    if (url === '/api/persona/processing') return json(state);
    if (url === '/api/status')
      return json({
        counts: { sources: rows.length, items: 3 },
        egress: [],
        kernel,
      });
    if (url === '/api/persona/notes') {
      state = { state: 'queued' };
      return json(memory);
    }
    if (url === '/api/persona/import') {
      if (importError) return json({ detail: '上传失败，请重试' }, 400);
      state = { state: 'queued' };
      return json({
        imported: [memory],
        skipped: [{ file: '.hidden.txt', reason: '已跳过隐藏文件' }],
      });
    }
    if (url.endsWith('/text')) return new Response('隐私视图中的文字');
    if (url === '/api/persona/sources/s%2F1' && init.method === 'DELETE') {
      rows = [];
      state = { state: 'queued' };
      return json({ deleted: true });
    }
    if (url === '/api/persona/build') {
      state = { state: 'queued' };
      return json({ job_id: 'j1' }, 202);
    }
    if (url.endsWith('/reextract') && init.method === 'POST') {
      state = { state: 'queued' };
      return json({ chunks: 1 }, 202);
    }
    throw new Error(`Unexpected API ${url}`);
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => vi.useRealTimers());
function Where() {
  const location = useLocation();
  return <p aria-label="地址">{location.pathname + location.search}</p>;
}
function mount() {
  return render(
    <ConfirmProvider>
      <MemoryRouter initialEntries={['/memories']}>
        <Memories />
        <Where />
      </MemoryRouter>
    </ConfirmProvider>,
  );
}
async function loaded() {
  await screen.findByRole('heading', { name: memory.title });
}

it('puts the list first on mobile, adds through a bottom sheet, and exposes row actions in an overflow menu', async () => {
  vi.stubGlobal('innerWidth', 390);
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  mount();
  await loaded();
  expect(screen.queryByRole('tab')).not.toBeInTheDocument();
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  const user = userEvent.setup();
  const add = screen.getByRole('button', { name: '添加记忆' });
  expect(add).toHaveClass('fixed', 'size-12');
  await user.click(add);
  const sheet = screen.getByRole('dialog', { name: '添加记忆' });
  expect(sheet).toHaveClass('bottom-0', 'top-auto', 'w-full');
  expect(
    within(sheet)
      .getAllByRole('tab')
      .map((tab) => tab.textContent),
  ).toEqual(['写一段', '上传文件', '上传文件夹']);
  expect(within(sheet).getByRole('textbox')).not.toHaveClass('text-sm');
  await user.type(within(sheet).getByRole('textbox'), '手机上的记忆');
  await user.click(within(sheet).getByRole('button', { name: '保存' }));
  await waitFor(() =>
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
  );
  const summary = screen.getByLabelText('我的经历的操作');
  await user.click(summary);
  expect(summary.parentElement).toHaveAttribute('open');
  await user.click(screen.getByRole('button', { name: '查看' }));
  const preview = await screen.findByRole('dialog', { name: memory.title });
  await waitFor(() => expect(preview).toHaveTextContent('隐私视图中的文字'));
  await user.click(within(preview).getByRole('button', { name: '关闭' }));
  await waitFor(() =>
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
  );
  await user.click(summary);
  await user.click(screen.getByRole('button', { name: '删除' }));
  await user.click(screen.getByRole('button', { name: '确认删除' }));
  await waitFor(() =>
    expect(
      screen.queryByRole('heading', { name: memory.title }),
    ).not.toBeInTheDocument(),
  );
});
it('has three add tabs without kind, date or manual build controls; saves notes', async () => {
  mount();
  await loaded();
  const user = userEvent.setup();
  expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
    '写一段',
    '上传文件',
    '上传文件夹',
  ]);
  expect(screen.queryByRole('radio')).not.toBeInTheDocument();
  expect(screen.queryByText('构建人格档案')).not.toBeInTheDocument();
  await user.type(screen.getByLabelText('要记住的文字'), '我喜欢散步');
  await user.click(screen.getByRole('button', { name: '保存' }));
  await waitFor(() =>
    expect(toast).toHaveBeenCalledWith('已添加，等待整理结果', 'success'),
  );
  const init = fetcher.mock.calls.find(
    ([url]) => url === '/api/persona/notes',
  )![1];
  expect(JSON.parse(init.body)).toEqual({ text: '我喜欢散步' });
  expect(screen.getByLabelText('要记住的文字')).toHaveValue('');
  expect(new Headers(init.headers).get('X-Twin')).toBe('1');
});

it('uploads multiple files and dropped files with no kind query', async () => {
  mount();
  await loaded();
  const user = userEvent.setup();
  await user.click(screen.getByRole('tab', { name: '上传文件' }));
  const input = screen.getByLabelText('选择文件');
  expect(input).toHaveAttribute('multiple');
  // Any file can be picked (some Windows machines grey .m4a out of a filtered picker); what is not supported is skipped.
  expect(input).not.toHaveAttribute('accept');
  await user.upload(input, [
    new File(['hello'], 'a.pdf'),
    new File(['hi'], 'b.docx'),
  ]);
  await screen.findByRole('list', { name: '跳过的文件' });
  let init = fetcher.mock.calls.find(
    ([url]) => url === '/api/persona/import',
  )![1];
  expect(init.body.getAll('files')).toHaveLength(2);
  expect(new Headers(init.headers).has('Content-Type')).toBe(false);
  await waitFor(() => expect(input).not.toBeDisabled());
  fireEvent.drop(input.parentElement!, {
    dataTransfer: { files: [new File(['abc'], 'drop.txt')] },
  });
  await waitFor(() =>
    expect(
      fetcher.mock.calls.filter(([url]) => url === '/api/persona/import'),
    ).toHaveLength(2),
  );
  init = fetcher.mock.calls
    .filter(([url]) => url === '/api/persona/import')
    .at(-1)![1];
  expect(init.body.get('files').name).toBe('drop.txt');
});

it('uploads a folder over 100 MiB as separate document requests', async () => {
  mount();
  await loaded();
  const user = userEvent.setup();
  await user.click(screen.getByRole('tab', { name: '上传文件夹' }));
  const input = screen.getByLabelText('选择文件夹');
  const files = ['a.txt', 'b.txt', 'c.txt'].map((name) => {
    const file = new File(['x'], name);
    Object.defineProperty(file, 'size', { value: 40 * 1024 * 1024 });
    Object.defineProperty(file, 'webkitRelativePath', {
      value: `folder/${name}`,
    });
    return file;
  });
  Object.defineProperty(input, 'files', { configurable: true, value: files });
  fireEvent.change(input);

  await waitFor(() =>
    expect(
      fetcher.mock.calls.filter(([url]) => url === '/api/persona/import'),
    ).toHaveLength(3),
  );
  const requests = fetcher.mock.calls.filter(
    ([url]) => url === '/api/persona/import',
  );
  expect(requests.map(([, init]) => init.body.get('files').name)).toEqual([
    'folder/a.txt',
    'folder/b.txt',
    'folder/c.txt',
  ]);
});

it('rejects a folder larger than 500 MiB before sending any files', async () => {
  mount();
  await loaded();
  const user = userEvent.setup();
  await user.click(screen.getByRole('tab', { name: '上传文件夹' }));
  const input = screen.getByLabelText('选择文件夹');
  const file = new File(['x'], 'large.txt');
  Object.defineProperty(file, 'size', { value: 500 * 1024 * 1024 + 1 });
  Object.defineProperty(file, 'webkitRelativePath', {
    value: 'folder/large.txt',
  });
  Object.defineProperty(input, 'files', { configurable: true, value: [file] });
  fireEvent.change(input);

  expect(await screen.findByRole('alert')).toHaveTextContent(
    '文件夹内容超过 500 MB，请分批上传',
  );
  expect(
    fetcher.mock.calls.filter(([url]) => url === '/api/persona/import'),
  ).toHaveLength(0);
});

it('uploads folders with relative names and displays skipped reasons', async () => {
  mount();
  await loaded();
  const user = userEvent.setup();
  await user.click(screen.getByRole('tab', { name: '上传文件夹' }));
  const input = screen.getByLabelText('选择文件夹');
  expect(input).toHaveAttribute('webkitdirectory');
  const file = new File(['hi'], 'a.txt');
  Object.defineProperty(file, 'webkitRelativePath', { value: 'folder/a.txt' });
  await user.upload(input, file);
  expect(
    await screen.findByRole('list', { name: '跳过的文件' }),
  ).toHaveTextContent('.hidden.txt：已跳过隐藏文件');
  const init = fetcher.mock.calls.find(
    ([url]) => url === '/api/persona/import',
  )![1];
  expect(init.body.get('files').name).toBe('folder/a.txt');
});

it('clears stale skipped-file notices when a later upload starts', async () => {
  mount();
  await loaded();
  const user = userEvent.setup();
  await user.click(screen.getByRole('tab', { name: '上传文件' }));
  await user.upload(
    screen.getByLabelText('选择文件'),
    new File(['旧文件'], 'old.txt'),
  );
  expect(
    await screen.findByRole('list', { name: '跳过的文件' }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole('tab', { name: '写一段' }));
  await user.type(screen.getByLabelText('要记住的文字'), '我喜欢散步');
  await user.click(screen.getByRole('button', { name: '保存' }));

  await waitFor(() =>
    expect(screen.queryByRole('list', { name: '跳过的文件' })).toBeNull(),
  );
});

it('renders all four memory statuses in plain words', async () => {
  rows = [
    memory,
    {
      ...memory,
      source_id: 's2',
      title: '新笔记',
      detected_kind_label: '笔记',
      status: 'processing',
    },
    {
      ...memory,
      source_id: 's3',
      title: '空文档',
      status: 'nothing_found',
      remembered: 0,
    },
    {
      ...memory,
      source_id: 's7',
      title: '对不上的文档',
      status: 'nothing_found',
      remembered: 0,
      extraction: { returned: 2, kept: 0 },
    },
    { ...memory, source_id: 's4', title: '失败文档', status: 'failed' },
    {
      ...memory,
      source_id: 's5',
      title: '长文档',
      status: 'processing',
      chunks_done: 2,
      chunks_total: 5,
    },
    {
      ...memory,
      source_id: 's6',
      title: '读完的文档',
      status: 'processing',
      chunks_done: 3,
      chunks_total: 3,
    },
  ];
  mount();
  await loaded();
  const list = screen.getByRole('list', { name: '记忆列表' });
  expect(list).toHaveTextContent('文档 · 2024-01-01');
  expect(list).toHaveTextContent('已记住 3 条');
  expect(list).toHaveTextContent('正在记住…');
  expect(list).toHaveTextContent('没找到关于你的内容');
  expect(list).toHaveTextContent('找到一些内容，但没通过核对');
  expect(list).toHaveTextContent('处理失败');
  expect(list).toHaveTextContent('正在记住… 2/5 段');
  expect(list).toHaveTextContent('已读完，等待合并');
  expect(list.textContent).not.toMatch(
    /本人|他人|原话|支撑档案|细项|自述|行为/,
  );
  fireEvent.click(within(list).getByRole('button', { name: '重试' }));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([url]) => url === '/api/persona/build'),
    ).toBe(true),
  );
  const reextract = within(list).getAllByRole('button', { name: '重新整理' });
  expect(reextract).toHaveLength(2); // only the two rows that found nothing
  await waitFor(() => expect(reextract[1]).toBeEnabled());
  fireEvent.click(reextract[1]);
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(
        ([url]) => url === '/api/persona/sources/s7/reextract',
      ),
    ).toBe(true),
  );
});

it('renders dateless rows without a leading separator', async () => {
  rows = [{ ...memory, first_date: null }];
  mount();
  await loaded();
  expect(
    screen.getByRole('list', { name: '记忆列表' }).querySelector('article p'),
  ).toHaveTextContent(/^文档$/);
});

it('opens a read-only privacy preview and confirms deletion', async () => {
  mount();
  await loaded();
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: '查看' }));
  const dialog = screen.getByRole('dialog', { name: memory.title });
  await waitFor(() => expect(dialog).toHaveTextContent('隐私视图中的文字'));
  expect(within(dialog).queryByRole('textbox')).not.toBeInTheDocument();
  await user.click(within(dialog).getByRole('button', { name: '关闭' }));
  await user.click(await screen.findByRole('button', { name: '删除' }));
  expect(screen.getByRole('button', { name: '取消' })).toHaveFocus();
  await user.click(screen.getByRole('button', { name: '取消' }));
  expect(fetcher.mock.calls.some(([, init]) => init.method === 'DELETE')).toBe(
    false,
  );
  await user.click(await screen.findByRole('button', { name: '删除' }));
  await user.click(screen.getByRole('button', { name: '确认删除' }));
  await waitFor(() =>
    expect(
      screen.queryByRole('heading', { name: memory.title }),
    ).not.toBeInTheDocument(),
  );
  expect(screen.getByText('还没有记忆')).toBeVisible();
});

it('polls processing every two seconds and stops at idle, with retry only on error', async () => {
  vi.useFakeTimers();
  state = { state: 'queued' };
  mount();
  await act(async () => {});
  expect(screen.getByRole('status')).toHaveTextContent('记忆整理排队中');
  expect(
    screen.queryByRole('button', { name: '重新处理' }),
  ).not.toBeInTheDocument();
  state = { state: 'running' };
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000);
  });
  expect(screen.getByRole('status')).toHaveTextContent('正在记住…');
  state = {
    state: 'running',
    progress: { phase: 'extract', done: 812, total: 4300 },
  };
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000);
  });
  expect(screen.getByRole('status')).toHaveTextContent(
    '正在记住… 已读 812/4300 段',
  );
  state = {
    state: 'running',
    progress: { phase: 'merge', done: 4300, total: 4300 },
  };
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000);
  });
  expect(screen.getByRole('status')).toHaveTextContent('正在合并记忆…');
  state = {
    state: 'running',
    progress: {
      phase: 'merge',
      done: 4300,
      total: 4300,
      merged: 37,
      to_merge: 120,
    },
  };
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000);
  });
  expect(screen.getByRole('status')).toHaveTextContent(
    '正在合并记忆… 已合并 37/120 批',
  );
  state = { state: 'idle', last_error: '模型暂时不可用' };
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000);
  });
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '重新处理' })).toBeInTheDocument();
  const calls = fetcher.mock.calls.filter(
    ([url]) => url === '/api/persona/processing',
  ).length;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(4000);
  });
  expect(
    fetcher.mock.calls.filter(([url]) => url === '/api/persona/processing'),
  ).toHaveLength(calls);
});

it('shows the whole build live: its steps, what it waits on and that it is still moving', async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-16T10:05:00Z'));
  rows = [
    memory,
    {
      ...memory,
      source_id: 's/2',
      title: '待整理资料',
      status: 'processing',
      remembered: 0,
      chunks_done: 3,
      chunks_total: 3,
    },
  ];
  state = {
    state: 'running',
    stage: { current: 1, total: 2, label: '抽取并合并人格档案' },
    tally: { done: 4, failed: 1, total: null },
    progress: { phase: 'extract', done: 118, total: 127 },
    started: '2026-10-16T10:00:00Z',
    now: '2026-10-16T10:05:00Z',
    activity: {
      waiting: 3,
      longest_s: 48,
      retries: 0,
      last_progress_at: '2026-10-16T10:04:58Z',
    },
  };
  mount();
  await act(async () => {});

  const steps = screen.getByRole('list', { name: '整理步骤' });
  expect(steps).toHaveTextContent('读资料（进行中）118/127 段');
  expect(steps).toHaveTextContent('合并成记忆（未开始）');
  expect(steps).toHaveTextContent('更新检索（未开始）');
  expect(
    screen.getByRole('progressbar', { name: '读资料进度' }),
  ).toHaveAttribute('aria-valuenow', '118');
  expect(screen.getByText(/^共 2 份/)).toHaveTextContent(
    '共 2 份 · 已记住 1 份 · 整理中 1 份',
  );
  const live = screen.getByRole('list', { name: '实时状态' });
  expect(live).toHaveTextContent('正在等模型回复 · 3 个请求 · 最久已等 48 秒');
  expect(live).toHaveTextContent('刚刚有进展');
  expect(screen.getByText(/已用时/)).toHaveTextContent('已用时 5 分 0 秒');
  // the card says what the read material waits for
  expect(screen.getByRole('list', { name: '记忆列表' })).toHaveTextContent(
    '已读完，等其余 9 段读完后合并',
  );

  // between polls the clocks keep ticking
  fetcher.mockClear();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(screen.getByText(/已用时/)).toHaveTextContent('已用时 5 分 1 秒');
  expect(live).toHaveTextContent('最久已等 49 秒');

  // merging, with a retry and a long quiet spell
  state = {
    ...state,
    progress: {
      phase: 'merge',
      done: 127,
      total: 127,
      merged: 37,
      to_merge: 120,
    },
    now: '2026-10-16T10:20:00Z',
    activity: {
      waiting: 0,
      longest_s: 0,
      retries: 2,
      last_progress_at: '2026-10-16T10:13:00Z',
    },
  };
  vi.setSystemTime(new Date('2026-10-16T10:20:00Z'));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000);
  });
  const merging = screen.getByRole('list', { name: '整理步骤' });
  expect(merging).toHaveTextContent('读资料（已完成）');
  expect(merging).toHaveTextContent('合并成记忆（进行中）37/120 批');
  const quiet = screen.getByRole('list', { name: '实时状态' });
  expect(quiet).toHaveTextContent('有请求超时或出错，正在自动重试（2 次）');
  expect(quiet).toHaveTextContent('上次进展在 7 分');
  expect(quiet).toHaveTextContent('已经有一阵没有进展');
  expect(screen.getByRole('list', { name: '记忆列表' })).toHaveTextContent(
    '合并中 · 已合并 37/120 批',
  );

  // embedding for retrieval, counted in the stage's tally
  state = {
    ...state,
    progress: undefined,
    stage: { current: 2, total: 2, label: '更新检索向量' },
    tally: { done: 512, failed: 0, total: 2000 },
  };
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000);
  });
  expect(screen.getByRole('list', { name: '整理步骤' })).toHaveTextContent(
    '合并成记忆（已完成）更新检索（进行中）512/2000 条',
  );
  expect(screen.getByRole('list', { name: '记忆列表' })).toHaveTextContent(
    '正在更新检索向量',
  );
  vi.useRealTimers();
});

it('keeps Chinese upload errors and aborts uploads on unmount', async () => {
  const page = mount();
  await loaded();
  const user = userEvent.setup();
  await user.click(screen.getByRole('tab', { name: '上传文件' }));
  importError = true;
  await user.upload(
    screen.getByLabelText('选择文件'),
    new File(['hello'], 'a.txt'),
  );
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '上传失败，请重试',
  );
  fetcher.mockImplementation((url: string) =>
    url === '/api/persona/import'
      ? new Promise(() => {})
      : Promise.resolve(json([])),
  );
  await user.upload(
    screen.getByLabelText('选择文件'),
    new File(['hello'], 'b.txt'),
  );
  const init = fetcher.mock.calls
    .filter(([url]) => url === '/api/persona/import')
    .at(-1)![1];
  page.unmount();
  expect(init.signal.aborted).toBe(true);
});

it('says nothing about the kernel when memories are on the current one', async () => {
  mount();
  expect(await screen.findByText(/写一段话/)).toBeInTheDocument();
  expect(screen.queryByText(/记忆内核/)).toBeNull();
});

it.each([true, false])(
  'says in one line that an older kernel is in use, and points an administrator to the settings (admin %s)',
  async (admin) => {
    useAuth.setState({
      identity: { email: null, admin, auth_enabled: false },
    });
    kernel = {
      version: v5,
      built: v4,
      scope: 'full',
      pending_chunks: 512,
      state: 'awaiting_confirmation',
    };
    mount();
    const line = await screen.findByText(
      /记忆内核有新版本 persona-v5 · 分类 v1/,
    );
    // Upgrading is the system settings' task: no upgrade button on the page.
    expect(screen.queryByRole('button', { name: '升级记忆内核' })).toBeNull();
    const go = screen.queryByRole('button', { name: '去设置里升级' });
    if (!admin) {
      expect(line).toHaveTextContent('管理员升级前沿用旧档案');
      expect(go).toBeNull();
      return;
    }
    expect(line).toHaveTextContent('升级前沿用旧档案');
    await userEvent.click(go!);
    expect(await screen.findByLabelText('地址')).toHaveTextContent(
      'system=upgrades',
    );
    useAuth.setState({ identity: null });
  },
);

it('says when a memory was added, with the year only when it is not this one', () => {
  const now = new Date('2026-10-25T12:00:00');
  expect(addedOn('2026-03-16T18:48:00', now)).toBe('3月16日加入');
  expect(addedOn('2025-11-10T19:15:00', now)).toBe('2025年11月10日加入');
  expect(addedOn(undefined, now)).toBeNull();
  expect(addedOn('not a date', now)).toBeNull();
});
