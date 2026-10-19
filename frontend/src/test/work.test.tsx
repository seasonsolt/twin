import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AppShell } from '../components/layout/AppShell';
import { ConfirmProvider, TooltipProvider, toast } from '../components/ui';
import { useChatLayout } from '../stores/chatLayout';
import { setPersonaId } from '../lib/persona';
import { Work } from '../pages/Work';
import { usePersonas, type Persona } from '../stores/personas';
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
  let tasks: unknown[] = [];
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
});

const setup = () =>
  render(
    <ConfirmProvider>
      <MemoryRouter initialEntries={['/work']}>
        <Routes>
          <Route path="work" element={<Work />} />
        </Routes>
      </MemoryRouter>
    </ConfirmProvider>,
  );

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
  await user.click(screen.getByRole('button', { name: '任务列表' }));
  const sheet = await screen.findByRole('dialog', { name: '任务记录' });
  expect(
    within(sheet).getByRole('button', { name: /^写周报/u }),
  ).toHaveAttribute('aria-current', 'true');
  await user.click(within(sheet).getByRole('button', { name: '删除写周报' }));
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
});

it('names the twin in a download link, which cannot send the persona header', async () => {
  setPersonaId('p2');
  const { fileUrl } = await import('../pages/Work');
  expect(fileUrl('w_aaaaaaaaaaaa', '草稿/要点 1.md')).toBe(
    '/api/persona/work/w_aaaaaaaaaaaa/files/%E8%8D%89%E7%A8%BF/%E8%A6%81%E7%82%B9%201.md?persona=p2',
  );
});

it('gives a visitor of a public twin chat and work, and nothing to manage', async () => {
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
    ).toEqual(['聊天', '工作']);
  } finally {
    usePersonas.setState(previous);
  }
});

it('keeps the task list where chat keeps its conversations: open on a wide screen, folded away and back on a narrower one', async () => {
  media('(min-width: 1280px)');
  const user = userEvent.setup();
  const view = setup();
  const list = await screen.findByRole('region', { name: '交给本人的事' });
  expect(
    screen.queryByRole('button', { name: '展开任务列表' }),
  ).not.toBeInTheDocument();
  await user.type(screen.getByLabelText('要做的事'), '写周报');
  await user.click(screen.getByRole('button', { name: '交代' }));
  expect(
    await within(list).findByRole('button', { name: /^写周报/u }),
  ).toHaveAttribute('aria-current', 'true');
  expect(
    await screen.findByRole('heading', { level: 1, name: '写周报' }),
  ).toBeInTheDocument();
  await user.click(within(list).getByRole('button', { name: '新任务' }));
  expect(
    await screen.findByRole('heading', { name: '交给本人一件事' }),
  ).toBeInTheDocument();
  expect(list).toBeInTheDocument();
  await user.click(within(list).getByRole('button', { name: '收起任务列表' }));
  expect(screen.queryByRole('region', { name: '交给本人的事' })).toBeNull();
  expect(useChatLayout.getState().sheet).toBe(false);
  view.unmount();
  media('');
  setup();
  await user.click(await screen.findByRole('button', { name: '展开任务列表' }));
  expect(
    await screen.findByRole('region', { name: '交给本人的事' }),
  ).toBeInTheDocument();
});
