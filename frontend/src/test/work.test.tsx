import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AppShell } from '../components/layout/AppShell';
import { ConfirmProvider, TooltipProvider, toast } from '../components/ui';
import { useChatLayout } from '../stores/chatLayout';
import { setPersonaId } from '../lib/persona';
import { Chat } from '../pages/Chat';
import { usePersonas, type Persona } from '../stores/personas';
import { useAuth } from '../stores/auth';
import type { WorkTask } from '../features/work/types';

vi.mock('../components/ui', async (original) => ({
  ...(await original<typeof import('../components/ui')>()),
  toast: vi.fn(),
}));
vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
vi.mock('../stores/status', () => ({
  startStatusPolling: vi.fn(),
  useStatus: (selector?: (state: { data: null; error: null }) => unknown) =>
    selector
      ? selector({ data: null, error: null })
      : { data: null, error: null },
}));

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status });

const turn = (role: 'user' | 'assistant', content: string, extra = {}) => ({
  role,
  content,
  at: '2026-10-15T10:00:00',
  steps: [],
  files: [],
  ...extra,
});

let task: WorkTask;
let tasks: unknown[];
let fetcher: ReturnType<typeof vi.fn>;
const calls = (method: string) =>
  fetcher.mock.calls
    .filter(([, options]) => (options?.method ?? 'GET') === method)
    .map(([url, options]) => [
      url,
      options?.body ? JSON.parse(String(options.body)) : null,
    ]);

beforeEach(() => {
  vi.mocked(toast).mockClear();
  task = {
    task_id: 'w_aaaaaaaaaaaa',
    title: '写周报',
    status: 'running',
    error: null,
    job_id: 'j1',
    created_at: '2026-10-15T10:00:00',
    updated_at: '2026-10-15T10:00:00',
    turns: [turn('user', '写周报')],
    files: [],
    progress: ['回想：本周的事'],
    stopping: false,
  };
  tasks = [];
  fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    const method = options?.method ?? 'GET';
    if (url === '/api/persona/work' && method === 'POST') {
      const body = JSON.parse(String(options?.body)) as { task_id?: string };
      tasks = [{ ...task, turns: 1 }];
      return json(
        {
          task: tasks[0],
          job_id: 'j1',
          steered: !!body.task_id && task.status === 'running',
        },
        202,
      );
    }
    if (url === `/api/persona/work/${task.task_id}/stop`) {
      task = { ...task, stopping: true };
      return json({ stopping: true }, 202);
    }
    if (url === '/api/persona/work') return json({ tasks });
    // The conversation page also holds the chat side: nothing said there yet. Its list is of everything, tasks too.
    if (url.startsWith('/api/conversations')) return json([]);
    if (url.startsWith('/api/personas/conversations'))
      return json({
        mine: null,
        conversations: [],
        tasks: (tasks as WorkTask[]).map((row) => ({
          task_id: row.task_id,
          persona_id: 'default',
          title: row.title,
          status: row.status,
          updated_at: row.updated_at,
        })),
        more: false,
      });
    if (url === `/api/persona/work/${task.task_id}` && method === 'DELETE') {
      tasks = [];
      return json({ deleted: true });
    }
    if (url === `/api/persona/work/${task.task_id}`) return json(task);
    return json({});
  });
  vi.stubGlobal('fetch', fetcher);
});

const media = (matching: string) =>
  vi.mocked(window.matchMedia).mockImplementation(
    (query: string) =>
      ({
        matches: query === matching,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }) as unknown as MediaQueryList,
  );

afterEach(() => {
  setPersonaId('default');
  media('');
  useChatLayout.setState({ sheet: undefined });
  useAuth.setState({ identity: null });
});

// Work is the conversation page with the task kind of message chosen (what `#/work` leads to).
const setup = (features?: { work: boolean }) => {
  useAuth.setState({
    identity: {
      email: 'me@example.com',
      admin: false,
      auth_enabled: true,
      ...(features ? { features } : {}),
    },
  });
  return render(
    <TooltipProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={['/chat?mode=task']}>
          <Routes>
            <Route path="chat" element={<Chat />} />
          </Routes>
        </MemoryRouter>
      </ConfirmProvider>
    </TooltipProvider>,
  );
};

it('starts a task, shows its progress while it runs, then the reply and the files to download', async () => {
  const user = userEvent.setup();
  setup();
  expect(
    await screen.findByRole('heading', { name: '交给本人一件事' }),
  ).toBeInTheDocument();
  // A new task, like a new ChatGPT conversation, centres the greeting and the composer on a wide screen.
  expect(document.querySelector('.chat-page')).toHaveAttribute(
    'data-empty',
    'true',
  );
  await user.click(
    screen.getByRole('button', { name: '按我的口吻写一份本周周报' }),
  );
  expect(screen.getByLabelText('要做的事')).toHaveValue(
    '按我的口吻写一份本周周报',
  );
  await user.clear(screen.getByLabelText('要做的事'));
  await user.type(screen.getByLabelText('要做的事'), '写周报');
  await user.click(screen.getByRole('button', { name: '交代' }));
  expect(calls('POST')).toEqual([['/api/persona/work', { text: '写周报' }]]);
  expect(await screen.findByText('正在做…')).toBeInTheDocument();
  expect(
    within(screen.getByRole('list', { name: '进度' })).getByText(
      '回想：本周的事',
    ),
  ).toBeInTheDocument();
  expect(screen.getByRole('article', { name: '你说' })).toHaveTextContent(
    '写周报',
  );
  expect(screen.getByRole('article', { name: '你说' })).toHaveAttribute(
    'data-pin',
    'w_aaaaaaaaaaaa:0',
  );
  expect(document.querySelector('.chat-page')).toHaveAttribute(
    'data-empty',
    'false',
  );

  task = {
    ...task,
    status: 'idle',
    progress: [],
    turns: [
      ...task.turns,
      turn('assistant', '周报写好了。', {
        steps: ['回想：本周的事', '写 Word：周报.docx'],
        files: ['周报.docx'],
      }),
    ],
    files: [{ path: '周报.docx', size: 37_337 }],
  };
  const reply = await screen.findByRole(
    'article',
    { name: '回复' },
    { timeout: 4000 },
  );
  expect(within(reply).getByText('周报写好了。')).toBeInTheDocument();
  expect(within(reply).getByText('做了 2 步')).toBeInTheDocument();
  const file = within(reply).getByRole('link', { name: /周报\.docx/u });
  expect(file).toHaveAttribute(
    'href',
    '/api/persona/work/w_aaaaaaaaaaaa/files/%E5%91%A8%E6%8A%A5.docx',
  );
  expect(file).toHaveTextContent('36 KB');
  expect(screen.queryByText('正在做…')).not.toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: '停下' }),
  ).not.toBeInTheDocument();

  // Continuing sends the task id along.
  await user.type(screen.getByLabelText('要做的事'), '再短一点');
  await user.click(screen.getByRole('button', { name: '交代' }));
  expect(calls('POST').at(-1)).toEqual([
    '/api/persona/work',
    { text: '再短一点', task_id: 'w_aaaaaaaaaaaa' },
  ]);
}, 10_000);

it('shows what a directly answered reply rests on, as chat does', async () => {
  task = {
    ...task,
    status: 'idle',
    progress: [],
    turns: [
      turn('user', '你怎么看扩张？'),
      turn('assistant', '先收钱，再说扩张。', {
        cited: [
          { id: 'pi_1', kind: 'item', facet: '价值观', text: '回款优先' },
        ],
      }),
    ],
  };
  const user = userEvent.setup();
  setup();
  await user.type(await screen.findByLabelText('要做的事'), '你怎么看扩张？');
  await user.click(screen.getByRole('button', { name: '交代' }));
  const reply = await screen.findByRole('article', { name: '回复' });
  expect(within(reply).queryByText(/做了 \d+ 步/u)).toBeNull();
  await user.click(within(reply).getByRole('button', { name: /^依据 · / }));
  // The evidence opens in a layer beside the reply, not inside it.
  const evidence = within(
    await screen.findByRole('dialog', { name: '回答依据' }),
  ).getByRole('list', { name: '回答依据' });
  await waitFor(() =>
    expect(within(evidence).getByText('回款优先')).toBeVisible(),
  );
});

it('takes a message and a stop while the task runs', async () => {
  const user = userEvent.setup();
  setup();
  await user.type(await screen.findByLabelText('要做的事'), '写周报');
  await user.click(screen.getByRole('button', { name: '交代' }));
  expect(await screen.findByText('正在做…')).toBeInTheDocument();
  const input = screen.getByLabelText('要做的事');
  expect(input).toBeEnabled();
  expect(input).toHaveAttribute('placeholder', '插一句，下一步就会看到');
  task = { ...task, turns: [...task.turns, turn('user', '顺便列个待办')] };
  await user.type(input, '顺便列个待办');
  await user.click(screen.getByRole('button', { name: '插话' }));
  expect(calls('POST').at(-1)).toEqual([
    '/api/persona/work',
    { text: '顺便列个待办', task_id: 'w_aaaaaaaaaaaa' },
  ]);
  await waitFor(() =>
    expect(screen.getAllByRole('article', { name: '你说' })).toHaveLength(2),
  );

  await user.click(screen.getByRole('button', { name: '停下' }));
  expect(calls('POST').at(-1)?.[0]).toBe(
    '/api/persona/work/w_aaaaaaaaaaaa/stop',
  );
  expect(await screen.findByText('正在停下…')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '停下' })).toBeDisabled();
});

it('deletes a task from the task list after confirming, and says why a task did not get done', async () => {
  task = {
    ...task,
    status: 'failed',
    error: '这件事没做成，可以换个说法再试一次',
    progress: [],
  };
  // On a phone the task list opens as a sheet from the top bar.
  media('(max-width: 767px)');
  const user = userEvent.setup();
  setup();
  await user.type(await screen.findByLabelText('要做的事'), '写周报');
  await user.click(screen.getByRole('button', { name: '交代' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('没做成');
  await user.click(screen.getByRole('button', { name: '对话列表' }));
  const sheet = await screen.findByRole('dialog', { name: '对话记录' });
  const row = within(sheet).getByRole('button', { name: /^写周报任务/u });
  expect(row).toHaveAttribute('aria-current', 'true');
  // A task is deleted from its "…" like a conversation, and it is said in the list to be a task.
  expect(within(row).getByText('任务')).toBeVisible();
  await user.click(
    within(sheet).getByRole('button', { name: '写周报的更多操作' }),
  );
  expect(within(sheet).queryByRole('menuitem', { name: '重命名' })).toBeNull();
  await user.click(within(sheet).getByRole('menuitem', { name: '删除' }));
  await user.click(
    within(await screen.findByRole('dialog', { name: '删除任务？' })).getByRole(
      'button',
      { name: '删除' },
    ),
  );
  await waitFor(() =>
    expect(calls('DELETE')).toEqual([
      [`/api/persona/work/${task.task_id}`, null],
    ]),
  );
  expect(
    await screen.findByRole('heading', { name: '交给本人一件事' }),
  ).toBeInTheDocument();
}, 10_000);

it('names the twin in a download link, which cannot send the persona header', async () => {
  setPersonaId('p2');
  const { fileUrl } = await import('../features/work/WorkThread');
  expect(fileUrl('w_aaaaaaaaaaaa', '草稿/要点 1.md')).toBe(
    '/api/persona/work/w_aaaaaaaaaaaa/files/%E8%8D%89%E7%A8%BF/%E8%A6%81%E7%82%B9%201.md?persona=p2',
  );
});

it('gives a visitor of a public twin the conversation alone, and nothing to manage; work is still there', async () => {
  const previous = usePersonas.getState();
  usePersonas.setState({
    id: 'p2',
    items: [{ id: 'p2', name: '朋友', can_manage: false } as Persona],
  });
  setPersonaId('p2');
  try {
    render(
      <TooltipProvider>
        <ConfirmProvider>
          <MemoryRouter initialEntries={['/work']}>
            <Routes>
              <Route element={<AppShell />}>
                <Route path="work" element={<p>Work destination</p>} />
                <Route path="chat" element={<p>Chat destination</p>} />
              </Route>
            </Routes>
          </MemoryRouter>
        </ConfirmProvider>
      </TooltipProvider>,
    );
    expect(await screen.findByText('Work destination')).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: '主导航' });
    expect(
      within(nav)
        .getAllByRole('link')
        .map((link) => link.textContent),
    ).toEqual(['对话']);
    expect(
      screen.queryByRole('button', { name: '上传会议录音' }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '问一句、找人' })).toBeNull();
  } finally {
    usePersonas.setState(previous);
  }
});

it('keeps tasks in the list of conversations: open on a wide screen, folded away and back on a narrower one', async () => {
  media('(min-width: 1280px)');
  const user = userEvent.setup();
  const view = setup();
  const list = await screen.findByRole('region', { name: '对话列表' });
  expect(
    screen.queryByRole('button', { name: '展开对话列表' }),
  ).not.toBeInTheDocument();
  await user.type(screen.getByLabelText('要做的事'), '写周报');
  await user.click(screen.getByRole('button', { name: '交代' }));
  expect(
    await within(list).findByRole('button', { name: /^写周报任务/u }),
  ).toHaveAttribute('aria-current', 'true');
  expect(
    await screen.findByRole('heading', { level: 1, name: '写周报' }),
  ).toBeInTheDocument();
  await user.click(within(list).getByRole('button', { name: '新任务' }));
  expect(
    await screen.findByRole('heading', { name: '交给本人一件事' }),
  ).toBeInTheDocument();
  expect(list).toBeInTheDocument();
  await user.click(within(list).getByRole('button', { name: '收起对话列表' }));
  expect(screen.queryByRole('region', { name: '对话列表' })).toBeNull();
  expect(useChatLayout.getState().sheet).toBe(false);
  view.unmount();
  media('');
  setup();
  await user.click(await screen.findByRole('button', { name: '展开对话列表' }));
  expect(
    await screen.findByRole('region', { name: '对话列表' }),
  ).toBeInTheDocument();
});

/** The task list has the task and the page is wide enough to show it. */
const withListedTask = () => {
  media('(min-width: 1280px)');
  task = { ...task, status: 'idle', progress: [] };
  tasks = [{ ...task, turns: 1 }];
};
const openedTask = (answer: (url: string) => Response | undefined) => {
  const base = fetcher.getMockImplementation() as (
    url: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation(async (url: string, options?: RequestInit) => {
    const mine =
      url === `/api/persona/work/${task.task_id}` &&
      (options?.method ?? 'GET') === 'GET'
        ? answer(url)
        : undefined;
    return mine ?? base(url, options);
  });
};

it('says why a task could not be opened and reads it again on request, instead of waiting for it for good', async () => {
  withListedTask();
  let down = true;
  openedTask(() =>
    down ? json({ detail: '任务暂时读不了' }, 500) : undefined,
  );
  const user = userEvent.setup();
  setup();
  const list = await screen.findByRole('region', { name: '对话列表' });
  await user.click(
    await within(list).findByRole('button', { name: /^写周报任务/u }),
  );
  expect(await screen.findByRole('alert')).toHaveTextContent('任务暂时读不了');
  expect(screen.queryByText('正在加载任务…')).toBeNull();
  down = false;
  await user.click(screen.getByRole('button', { name: '重试' }));
  expect(
    await screen.findByRole('article', { name: '你说' }),
  ).toHaveTextContent('写周报');
  expect(screen.queryByRole('alert')).toBeNull();
});

it('goes back to a new task, and says so, when the task opened is gone', async () => {
  withListedTask();
  openedTask(() => json({ detail: '找不到这个任务' }, 404));
  const user = userEvent.setup();
  setup();
  const list = await screen.findByRole('region', { name: '对话列表' });
  await user.click(
    await within(list).findByRole('button', { name: /^写周报任务/u }),
  );
  expect(
    await screen.findByRole('heading', { name: '交给本人一件事' }),
  ).toBeInTheDocument();
  expect(toast).toHaveBeenCalledWith('找不到这个任务，可能已被删除', 'danger');
  expect(screen.queryByText('正在加载任务…')).toBeNull();
});

it('starts a new task when the person comes back to tasks from chat, not the one opened last', async () => {
  withListedTask();
  const user = userEvent.setup();
  setup();
  const list = await screen.findByRole('region', { name: '对话列表' });
  await user.click(
    await within(list).findByRole('button', { name: /^写周报任务/u }),
  );
  expect(
    await screen.findByRole('heading', { level: 1, name: '写周报' }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole('radio', { name: '问答' }));
  await user.click(screen.getByRole('radio', { name: '交代任务' }));
  expect(
    await screen.findByRole('heading', { name: '交给本人一件事' }),
  ).toBeInTheDocument();
  // What is said now is a new task, not a follow-up to the old one.
  await user.type(screen.getByLabelText('要做的事'), '再写一份');
  await user.click(screen.getByRole('button', { name: '交代' }));
  expect(calls('POST').at(-1)).toEqual([
    '/api/persona/work',
    { text: '再写一份' },
  ]);
});
