import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider, toast } from '../components/ui';
import { Memories, type Memory } from '../pages/Memories';

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
let state: { state: 'idle' | 'queued' | 'running'; last_error?: string };
let fetcher: ReturnType<typeof vi.fn>;
let importError: boolean;
beforeEach(() => {
  rows = [memory];
  state = { state: 'idle' };
  importError = false;
  vi.mocked(toast).mockClear();
  fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (url === '/api/persona/sources') return json(rows);
    if (url === '/api/persona/processing') return json(state);
    if (url === '/api/status')
      return json({
        counts: { sources: rows.length, items: 3 },
        egress: [],
        labels: {},
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
    throw new Error(`Unexpected API ${url}`);
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => vi.useRealTimers());
function mount() {
  return render(
    <ConfirmProvider>
      <MemoryRouter initialEntries={['/memories']}>
        <Memories />
      </MemoryRouter>
    </ConfirmProvider>,
  );
}
async function loaded() {
  await screen.findByRole('heading', { name: memory.title });
}

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
    expect(toast).toHaveBeenCalledWith('已添加，正在记住…', 'success'),
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
  expect(input).toHaveAttribute(
    'accept',
    '.txt,.md,.pdf,.docx,.html,.htm,.csv,.json,.srt,.vtt',
  );
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
    { ...memory, source_id: 's4', title: '失败文档', status: 'failed' },
  ];
  mount();
  await loaded();
  const list = screen.getByRole('list', { name: '记忆列表' });
  expect(list).toHaveTextContent('2024-01-01 · 文档');
  expect(list).toHaveTextContent('已记住 3 条');
  expect(list).toHaveTextContent('正在记住…');
  expect(list).toHaveTextContent('没找到关于你的内容');
  expect(list).toHaveTextContent('处理失败');
  expect(list.textContent).not.toMatch(
    /本人|他人|原话|支撑档案|细项|自述|行为/,
  );
  fireEvent.click(within(list).getByRole('button', { name: '重试' }));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([url]) => url === '/api/persona/build'),
    ).toBe(true),
  );
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
  expect(screen.getByRole('status')).toHaveTextContent('等待记住…');
  expect(
    screen.queryByRole('button', { name: '重新处理' }),
  ).not.toBeInTheDocument();
  state = { state: 'running' };
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000);
  });
  expect(screen.getByRole('status')).toHaveTextContent('正在记住…');
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
