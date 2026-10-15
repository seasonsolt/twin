import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AppShell } from '../components/layout/AppShell';
import { ConfirmProvider, TooltipProvider, toast } from '../components/ui';
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
  };
  let tasks: unknown[] = [];
  fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    const method = options?.method ?? 'GET';
    if (url === '/api/persona/work' && method === 'POST') {
      tasks = [{ ...task, turns: 1 }];
      return json({ task: tasks[0], job_id: 'j1' }, 202);
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

afterEach(() => {
  setPersonaId('default');
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
  expect(await screen.findByText('还没有任务')).toBeInTheDocument();
  await user.type(screen.getByLabelText('要做的事'), '写周报');
  await user.click(screen.getByRole('button', { name: '交代' }));
  expect(calls('POST')).toEqual([['/api/persona/work', { text: '写周报' }]]);
  expect(await screen.findByText('正在做')).toBeInTheDocument();
  expect(screen.getByText('回想：本周的事')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '交代' })).toBeDisabled();

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
  expect(screen.queryByText('正在做')).not.toBeInTheDocument();
  expect(
    within(screen.getByRole('navigation', { name: '任务' })).getByRole(
      'button',
      { name: /写周报/u },
    ),
  ).toHaveAttribute('aria-current', 'page');

  // Continuing sends the task id along.
  await user.type(screen.getByLabelText('要做的事'), '再短一点');
  await user.click(screen.getByRole('button', { name: '交代' }));
  expect(calls('POST').at(-1)).toEqual([
    '/api/persona/work',
    { text: '再短一点', task_id: 'w_aaaaaaaaaaaa' },
  ]);
}, 10_000);

it('deletes a task after confirming, and says why a task did not get done', async () => {
  task = {
    ...task,
    status: 'failed',
    error: '这件事没做成，可以换个说法再试一次',
    progress: [],
  };
  const user = userEvent.setup();
  setup();
  await user.type(await screen.findByLabelText('要做的事'), '写周报');
  await user.click(screen.getByRole('button', { name: '交代' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('没做成');
  await user.click(screen.getByRole('button', { name: '删除任务' }));
  await user.click(
    within(await screen.findByRole('dialog')).getByRole('button', {
      name: '删除',
    }),
  );
  await waitFor(() =>
    expect(calls('DELETE')).toEqual([
      [`/api/persona/work/${task.task_id}`, null],
    ]),
  );
  expect(await screen.findByText('交代一件事')).toBeInTheDocument();
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
