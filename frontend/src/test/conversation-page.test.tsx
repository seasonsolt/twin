import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  MemoryRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
} from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider, TooltipProvider } from '../components/ui';
import { WorkRedirect } from '../App';
import { CURRENT_CHAT_KEY } from '../features/chat/useConversation';
import type { TeamAnswerCard } from '../features/answers/types';
import type { Turn } from '../features/chat/types';
import type { WorkTask } from '../features/work/types';
import { setPersonaId } from '../lib/persona';
import { Chat } from '../pages/Chat';
import { useAuth } from '../stores/auth';
import { useChatLayout } from '../stores/chatLayout';
import { usePersonas, type Persona } from '../stores/personas';
import { useStatus } from '../stores/status';
import { conversationServer } from './conversationServer';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status });
const when = '2026-10-20T10:00:00';
const cited = [
  { id: 'pi_1', kind: 'item' as const, facet: '价值观', text: '回款优先' },
];
const reply = {
  reply: '先收钱，再说扩张。',
  citations: ['pi_1'],
  cited,
  confidence: 0.6,
  abstain: false,
  abstain_reason: '',
  mode: 'grounded' as const,
  retrieved_ids: [],
};
const turns: Turn[] = [
  { id: 'u1', role: 'user', content: '怎么看扩张？', timestamp: when },
  { id: 't1', role: 'twin', content: reply.reply, reply, timestamp: when },
];
const task: WorkTask = {
  task_id: 'w_aaaaaaaaaaaa',
  title: '写周报',
  status: 'idle',
  error: null,
  job_id: null,
  created_at: when,
  updated_at: '2026-10-20T11:00:00',
  turns: [
    {
      role: 'user',
      content: '写周报',
      at: when,
      steps: [],
      files: [],
    },
    {
      role: 'assistant',
      content: '周报写好了。',
      at: when,
      steps: [],
      files: ['周报.docx'],
    },
  ],
  files: [{ path: '周报.docx', size: 2048 }],
  progress: [],
  stopping: false,
};
const summary = { ...task, turns: 2 };

let server: ReturnType<typeof conversationServer>;
let fetcher: ReturnType<typeof vi.fn>;
const requested = (prefix: string) =>
  fetcher.mock.calls.some(([url]) => String(url).startsWith(prefix));

function Where() {
  const location = useLocation();
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>;
}
function mount(
  entry = '/chat',
  options: { work?: boolean; twin?: Partial<Persona> } = {},
) {
  useAuth.setState({
    identity: {
      email: 'me@example.com',
      admin: false,
      auth_enabled: true,
      features: { work: options.work ?? true },
    },
  });
  usePersonas.setState({
    id: 'default',
    items: [
      {
        id: 'default',
        name: '林舟',
        avatar_url: null,
        sources: 3,
        created_at: '',
        is_default: true,
        ...options.twin,
      },
    ],
  });
  return render(
    <TooltipProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={[entry]}>
          <Where />
          <Routes>
            <Route path="chat" element={<Chat />} />
            <Route path="work" element={<WorkRedirect />} />
            <Route path="*" element={<Navigate to="/chat" replace />} />
          </Routes>
        </MemoryRouter>
      </ConfirmProvider>
    </TooltipProvider>,
  );
}
const media = (matching: string) =>
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: query === matching,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  useChatLayout.setState({ sheet: undefined, stage: undefined });
  useStatus.setState({ data: null, error: null });
  setPersonaId('default');
  media('(min-width: 1280px)');
  server = conversationServer();
  server.rows.set('c1', {
    id: 'c1',
    title: '下周发布怎么安排',
    turns,
    updated_at: '2026-10-20T09:00:00',
    persona: 'default',
  });
  server.tasks.push({
    task_id: task.task_id,
    persona_id: 'default',
    title: task.title,
    status: 'idle',
    updated_at: task.updated_at,
  });
  fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const saved = server.respond(url, init);
    if (saved) return saved;
    if (url === '/api/persona/work') return json({ tasks: [summary] });
    if (url === `/api/persona/work/${task.task_id}`) return json(task);
    if (url === '/api/media/capabilities')
      return json({ available: false, video: { available: false } });
    return json({ stale: false });
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => {
  setPersonaId('default');
  useAuth.setState({ identity: null });
  usePersonas.setState({ id: '', items: [] });
});

it('lists conversations and tasks together, newest first, and a task says it is one', async () => {
  mount();
  const list = await screen.findByRole('region', { name: '对话列表' });
  const rows = await within(list).findAllByRole('listitem');
  // Each says whom it is with, after its title.
  expect(rows.map((row) => row.textContent)).toEqual([
    expect.stringMatching(/^写周报林舟 · 任务/u),
    expect.stringMatching(/^下周发布怎么安排林舟(?!的更多操作)/u),
  ]);
  expect(within(rows[1]).queryByText('任务')).toBeNull();
});

it('names a fresh start after the kind of message, and marks a task still being done', async () => {
  const user = userEvent.setup();
  server.tasks[0].status = 'running';
  fetcher.mockImplementation(async (url: string, init?: RequestInit) => {
    const saved = server.respond(url, init);
    if (saved) return saved;
    if (url === '/api/persona/work')
      return json({ tasks: [{ ...summary, status: 'running' }] });
    if (url === '/api/media/capabilities')
      return json({ available: false, video: { available: false } });
    return json({ stale: false });
  });
  mount();
  const list = await screen.findByRole('region', { name: '对话列表' });
  expect(await within(list).findByText('任务 · 在做')).toBeVisible();
  expect(within(list).getByRole('button', { name: '新对话' })).toBeVisible();
  await user.click(screen.getByRole('radio', { name: '交代任务' }));
  expect(within(list).getByRole('button', { name: '新任务' })).toBeVisible();
  expect(within(list).queryByRole('button', { name: '新对话' })).toBeNull();
});

it('opens a task from the list in the same page and goes back to a conversation, with a draft kept when the kind of message changes', async () => {
  const user = userEvent.setup();
  mount();
  const list = await screen.findByRole('region', { name: '对话列表' });
  await user.click(
    await within(list).findByRole('button', {
      name: /^下周发布怎么安排(?!的更多操作)/u,
    }),
  );
  expect(await screen.findByText(reply.reply)).toBeVisible();
  // A message is a question or an instruction: one choice in the composer.
  const kind = screen.getByRole('radiogroup', { name: '这条消息是' });
  expect(within(kind).getByRole('radio', { name: '问答' })).toBeChecked();
  await user.type(screen.getByRole('textbox', { name: '你说' }), '顺便问一句');
  await user.click(within(kind).getByRole('radio', { name: '交代任务' }));
  expect(screen.getByTestId('where')).toHaveTextContent('/chat?mode=task');
  expect(screen.getByLabelText('要做的事')).toHaveValue('顺便问一句');
  expect(screen.getByRole('radio', { name: '交代任务' })).toBeChecked();
  await user.click(
    within(list).getByRole('button', { name: /^写周报\s*林舟\s*·\s*任务/u }),
  );
  expect(await screen.findByText('周报写好了。')).toBeVisible();
  expect(screen.getByRole('link', { name: /周报\.docx/u })).toHaveAttribute(
    'href',
    '/api/persona/work/w_aaaaaaaaaaaa/files/%E5%91%A8%E6%8A%A5.docx',
  );
  expect(
    screen.getByRole('heading', { level: 1, name: '写周报' }),
  ).toBeVisible();
  await user.click(
    within(list).getByRole('button', {
      name: /^下周发布怎么安排(?!的更多操作)/u,
    }),
  );
  expect(await screen.findByText(reply.reply)).toBeVisible();
  expect(screen.getByTestId('where')).toHaveTextContent(/^\/chat$/u);
  expect(screen.getByRole('radio', { name: '问答' })).toBeChecked();
});

it('shows no choice of kind, and no task request, where work is switched off', async () => {
  mount('/chat?mode=task', { work: false });
  expect(await screen.findByLabelText('你说')).toBeVisible();
  expect(screen.queryByRole('radiogroup', { name: '这条消息是' })).toBeNull();
  expect(screen.queryByLabelText('要做的事')).toBeNull();
  await waitFor(() =>
    expect(requested('/api/personas/conversations')).toBe(true),
  );
  expect(requested('/api/persona/work')).toBe(false);
  const list = screen.getByRole('region', { name: '对话列表' });
  expect(within(list).queryByText('任务')).toBeNull();
});

it('leads the old work address to the conversation on tasks, or on plain chat where work is off', async () => {
  const first = mount('/work');
  await waitFor(() =>
    expect(screen.getByTestId('where')).toHaveTextContent('/chat?mode=task'),
  );
  expect(await screen.findByLabelText('要做的事')).toBeVisible();
  first.unmount();
  mount('/work', { work: false });
  await waitFor(() =>
    expect(screen.getByTestId('where')).toHaveTextContent(/^\/chat$/u),
  );
  expect(await screen.findByLabelText('你说')).toBeVisible();
});

it('picks the twin in one place, beside the box a message is written in, whether the list is open or folded away', async () => {
  const user = userEvent.setup();
  const view = mount();
  const picks = () => screen.getAllByRole('button', { name: /^切换分身/ });
  const list = await screen.findByRole('region', { name: '对话列表' });
  expect(picks()).toHaveLength(1);
  expect(within(list).queryByRole('button', { name: /^切换分身/ })).toBeNull();
  expect(
    within(screen.getByRole('form', { name: '消息输入' })).getByRole('button', {
      name: /^切换分身/,
    }),
  ).toBeVisible();
  await user.click(screen.getByRole('button', { name: '收起对话列表' }));
  expect(screen.queryByRole('region', { name: '对话列表' })).toBeNull();
  expect(picks()).toHaveLength(1);
  view.unmount();
  media('(max-width: 767px)');
  mount();
  expect(
    await screen.findAllByRole('button', { name: /^切换分身/ }),
  ).toHaveLength(1);
});

it('opens what an answer rests on under it, where the person behind the twin can correct a memory and a visitor cannot', async () => {
  localStorage.setItem(CURRENT_CHAT_KEY, 'c1');
  const user = userEvent.setup();
  const view = mount();
  await user.click(
    await screen.findByRole('button', { name: /^有本人资料支持/ }),
  );
  const evidence = screen.getByRole('list', { name: '回答依据' });
  expect(within(evidence).getByText('回款优先')).toBeVisible();
  expect(
    within(evidence).getByRole('button', { name: '改一下' }),
  ).toBeVisible();
  view.unmount();
  localStorage.setItem(CURRENT_CHAT_KEY, 'c1');
  mount('/chat', { twin: { can_manage: false } });
  await user.click(
    await screen.findByRole('button', { name: /^有本人资料支持/ }),
  );
  const seen = screen.getByRole('list', { name: '回答依据' });
  expect(within(seen).getByText('回款优先')).toBeVisible();
  expect(within(seen).queryByRole('button', { name: '改一下' })).toBeNull();
});

it('renames a conversation from its menu, and a task has no rename', async () => {
  const user = userEvent.setup();
  mount();
  const list = await screen.findByRole('region', { name: '对话列表' });
  await user.click(
    await within(list).findByRole('button', { name: '写周报的更多操作' }),
  );
  expect(within(list).queryByRole('menuitem', { name: '重命名' })).toBeNull();
  await user.keyboard('{Escape}');
  await user.click(
    within(list).getByRole('button', { name: '下周发布怎么安排的更多操作' }),
  );
  await user.click(within(list).getByRole('menuitem', { name: '重命名' }));
  const field = within(list).getByRole('textbox', { name: '对话标题' });
  await user.clear(field);
  await user.type(field, '发布排期');
  await user.click(within(list).getByRole('button', { name: '保存' }));
  expect(
    await within(list).findByRole('button', {
      name: /^发布排期(?!的更多操作)/u,
    }),
  ).toBeVisible();
  expect(server.rows.get('c1')?.title).toBe('发布排期');
});

it('gives a visitor of a public twin the same page: the conversation, and the instruction where work is on', async () => {
  mount('/chat', { twin: { can_manage: false } });
  expect(await screen.findByRole('textbox', { name: '你说' })).toBeVisible();
  expect(screen.getByRole('radiogroup', { name: '这条消息是' })).toBeVisible();
  // The name in the header is not a way into the team's pages, which are not a visitor's.
  expect(
    within(screen.getByRole('banner')).queryByRole('link', { name: '林舟' }),
  ).toBeNull();
});

it('says once under the box that the person behind a twin reads what it answers, and not to the person themselves', async () => {
  const note = '本人看得到分身的回答';
  const view = mount();
  expect(await screen.findByText(note)).toBeVisible();
  view.unmount();
  // The person themselves, who took the twin and said it is all right.
  mount('/chat', { twin: { mine: true, approved: true } });
  await screen.findByRole('form', { name: '消息输入' });
  expect(screen.queryByText(note)).toBeNull();
});

it('says nothing of it where the twin has no person yet, or on a machine with one person and no sign-in', async () => {
  const note = '本人看得到分身的回答';
  const view = mount('/chat', { twin: { can_manage: true, claimed: false } });
  await screen.findByRole('form', { name: '消息输入' });
  expect(screen.queryByText(note)).toBeNull();
  view.unmount();
  mount();
  act(() =>
    useAuth.setState({
      identity: { email: null, admin: true, auth_enabled: false },
    }),
  );
  await waitFor(() => expect(screen.queryByText(note)).toBeNull());
});

const handed = (status: 'delivered' | 'replied' = 'replied') =>
  ({
    id: 'h_1',
    kind: 'commit' as const,
    status,
    status_label: status === 'replied' ? '已回复' : '已送达',
    owner_name: '林舟',
  }) satisfies Turn['handoff'];
const own: Turn = {
  id: 's1',
  role: 'self',
  content: '周五前给你方案',
  timestamp: when,
  handoff_id: 'h_1',
};

it('shows what the person answered themself as theirs, apart from the twin’s answer, with where the handoff stands', async () => {
  server.rows.get('c1')!.turns = [
    turns[0],
    { ...turns[1], handoff: handed() },
    own,
  ];
  localStorage.setItem(CURRENT_CHAT_KEY, 'c1');
  mount();
  expect(await screen.findByText('先收钱，再说扩张。')).toBeVisible();
  const mine = screen.getByRole('article', { name: '本人回复' });
  expect(within(mine).getByText('本人')).toBeVisible();
  expect(within(mine).getByText('周五前给你方案')).toBeVisible();
  const twin = screen.getByRole('article', { name: '分身回复' });
  expect(within(twin).getByText('林舟的分身')).toBeVisible();
  // Her words stand right under it: the line under the answer does not say "replied" a second time.
  expect(within(twin).queryByRole('status')).toBeNull();
  expect(within(mine).queryByText('林舟')).toBeNull();
});

it('shows under the person’s reply that the promise they took on is in the commitments, a link for those who see them', async () => {
  const taken = {
    ...handed(),
    status: 'accepted' as const,
    status_label: '已接受',
  };
  server.rows.get('c1')!.turns = [
    turns[0],
    { ...turns[1], handoff: taken },
    own,
  ];
  localStorage.setItem(CURRENT_CHAT_KEY, 'c1');
  const view = mount('/chat', { twin: { can_manage: true } });
  const mine = await screen.findByRole('article', { name: '本人回复' });
  expect(
    within(mine).getByRole('link', { name: '已记为承诺 ›' }),
  ).toHaveAttribute('href', '/commitments');
  view.unmount();
  mount();
  const theirs = await screen.findByRole('article', { name: '本人回复' });
  expect(within(theirs).getByText('已记为承诺')).toBeVisible();
  expect(within(theirs).queryByRole('link')).toBeNull();
});

it('says nothing of a commitment under a reply that only answered in words', async () => {
  server.rows.get('c1')!.turns = [
    turns[0],
    { ...turns[1], handoff: handed() },
    own,
  ];
  localStorage.setItem(CURRENT_CHAT_KEY, 'c1');
  mount();
  const mine = await screen.findByRole('article', { name: '本人回复' });
  expect(within(mine).queryByText(/已记为承诺/u)).toBeNull();
});

it('marks nothing apart in a conversation where nothing was handed to the person', async () => {
  localStorage.setItem(CURRENT_CHAT_KEY, 'c1');
  mount();
  expect(await screen.findByText('先收钱，再说扩张。')).toBeVisible();
  expect(screen.queryByText('林舟的分身')).toBeNull();
  expect(screen.queryByRole('article', { name: '本人回复' })).toBeNull();
});

it('does not send the person’s words back as part of what was said, and folds the server’s view of a handoff into the page', async () => {
  const { spoken, withHandoffs } = await import('../features/chat/types');
  expect([...turns, own].filter(spoken).map((turn) => turn.role)).toEqual([
    'user',
    'twin',
  ]);
  // The answer arrives after the page was opened: it is placed right under the answer it belongs to, once, and the
  // state of the handoff follows; what the page has and the server lacks stays.
  const waiting = [turns[0], { ...turns[1], handoff: handed('delivered') }];
  const remote = [turns[0], { ...turns[1], handoff: handed() }, own];
  const merged = withHandoffs(waiting, remote);
  expect(merged.map((turn) => turn.role)).toEqual(['user', 'twin', 'self']);
  expect(merged[1].handoff?.status).toBe('replied');
  // Nothing new in it: the very same turns come back, so the page is not moved for nothing.
  expect(withHandoffs(merged, remote)).toBe(merged);
  const unsaved: Turn = { ...turns[0], id: 'u9', content: '还没存的一句' };
  expect(withHandoffs([...waiting, unsaved], remote).at(-1)).toBe(unsaved);
});

it('asks again while the person’s answer is awaited, and shows it under the answer when it comes', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
  try {
    server.rows.get('c1')!.turns = [
      turns[0],
      { ...turns[1], handoff: handed('delivered') },
    ];
    localStorage.setItem(CURRENT_CHAT_KEY, 'c1');
    mount();
    const waiting = await screen.findByRole('status');
    expect(waiting).toHaveTextContent('已转给林舟本人 · 等回复');
    expect(screen.queryByRole('article', { name: '本人回复' })).toBeNull();
    // The person answers.
    server.rows.get('c1')!.turns = [
      turns[0],
      { ...turns[1], handoff: handed() },
      own,
    ];
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    expect(
      await screen.findByRole('article', { name: '本人回复' }),
    ).toHaveTextContent('周五前给你方案');
    expect(screen.queryByRole('status')).toBeNull();
  } finally {
    vi.useRealTimers();
  }
});

it('asks now and then after the person has answered or the question ran out, for a promise taken on or a late reply', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
  try {
    // They answered in words; the promise is taken on later, in the commitments.
    server.rows.get('c1')!.turns = [
      turns[0],
      { ...turns[1], handoff: handed() },
      own,
    ];
    localStorage.setItem(CURRENT_CHAT_KEY, 'c1');
    const view = mount();
    const mine = await screen.findByRole('article', { name: '本人回复' });
    expect(within(mine).queryByText(/已记为承诺/u)).toBeNull();
    server.rows.get('c1')!.turns = [
      turns[0],
      {
        ...turns[1],
        handoff: { ...handed(), status: 'accepted', status_label: '已接受' },
      },
      own,
    ];
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000);
    });
    expect(
      within(
        await screen.findByRole('article', { name: '本人回复' }),
      ).getByText('已记为承诺'),
    ).toBeVisible();
    view.unmount();
    // It ran out, and the person answered after all.
    server.rows.get('c1')!.turns = [
      turns[0],
      {
        ...turns[1],
        handoff: { ...handed(), status: 'expired', status_label: '已过期' },
      },
    ];
    mount();
    expect(await screen.findByRole('status')).toHaveTextContent(
      '已转给林舟本人 · 已过期',
    );
    server.rows.get('c1')!.turns = [
      turns[0],
      { ...turns[1], handoff: handed() },
      own,
    ];
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000);
    });
    expect(
      await screen.findByRole('article', { name: '本人回复' }),
    ).toHaveTextContent('周五前给你方案');
  } finally {
    vi.useRealTimers();
  }
});

it('leaves the page where the person reads it when asking again brings nothing new', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
  const scroll = vi.fn();
  Element.prototype.scrollIntoView = scroll;
  try {
    server.rows.get('c1')!.turns = [
      turns[0],
      { ...turns[1], handoff: handed('delivered') },
    ];
    localStorage.setItem(CURRENT_CHAT_KEY, 'c1');
    mount();
    await screen.findByRole('status');
    const asked = () =>
      fetcher.mock.calls.filter(([url]) => url === '/api/conversations/c1')
        .length;
    const before = { asked: asked(), scrolled: scroll.mock.calls.length };
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    expect(asked()).toBeGreaterThan(before.asked);
    expect(scroll.mock.calls.length).toBe(before.scrolled);
  } finally {
    Reflect.deleteProperty(Element.prototype, 'scrollIntoView');
    vi.useRealTimers();
  }
});

const answerCard = (
  overrides: Partial<TeamAnswerCard> = {},
): TeamAnswerCard => ({
  id: 'ta_1',
  persona_id: 'p_lin',
  owner_name: '林舟',
  title: '旧版 Word 模板导出，这次之后还支持吗？',
  body: '旧版 Word 模板支持到 12 月 31 日，之后导出只保留新模板。',
  confirmed_at: '2026-10-22T09:00:00+00:00',
  status: 'valid',
  stale_note: '',
  partial: false,
  ...overrides,
});

it('shows a team answer as a card of its own above what the twin said, who confirmed it and when, never who asked', async () => {
  server.rows.get('c1')!.turns = [
    turns[0],
    {
      ...turns[1],
      reply: { ...reply, team_answers: [answerCard()] },
    },
  ];
  localStorage.setItem(CURRENT_CHAT_KEY, 'c1');
  mount();
  const card = await screen.findByRole('article', { name: '团队答案' });
  expect(within(card).getByText('林舟 10 月 22 日确认')).toBeVisible();
  expect(within(card).getByText(/支持到 12 月 31 日/u)).toBeVisible();
  expect(within(card).queryByText('可能过期')).toBeNull();
  // The twin's own words stand apart from the card.
  const twin = screen.getByRole('article', { name: '分身回复' });
  expect(within(twin).getByText('先收钱，再说扩张。')).toBeVisible();
  expect(
    card.compareDocumentPosition(screen.getByText('先收钱，再说扩张。')),
  ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
});

it('hands the asker’s question to the person who confirmed the answer, once, in the asker’s name', async () => {
  const user = userEvent.setup();
  const respond = fetcher.getMockImplementation() as (
    url: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation(async (url: string, init?: RequestInit) =>
    String(url).endsWith('/team-answers/ta_1/ask')
      ? json({ persona_id: 'p-lin', conversation_id: 'c9', handoff: {} })
      : respond(url, init),
  );
  server.rows.get('c1')!.turns = [
    turns[0],
    { ...turns[1], reply: { ...reply, team_answers: [answerCard()] } },
  ];
  localStorage.setItem(CURRENT_CHAT_KEY, 'c1');
  mount();
  const card = await screen.findByRole('article', { name: '团队答案' });
  await user.click(within(card).getByRole('button', { name: '问林舟本人' }));
  expect(
    await within(card).findByText('已转给林舟本人 · 等回复'),
  ).toBeVisible();
  expect(within(card).queryByRole('button')).toBeNull();
  // Where the reply will come, so that it can be looked for.
  expect(within(card).getByRole('link', { name: '去看 ›' })).toHaveAttribute(
    'href',
    '/chat?with=p-lin&open=c9',
  );
  const asks = fetcher.mock.calls.filter(([url]) =>
    String(url).endsWith('/team-answers/ta_1/ask'),
  );
  expect(asks).toHaveLength(1);
  expect(JSON.parse(String(asks[0][1].body))).toEqual({
    question: '怎么看扩张？',
  });
});

it('dashes a team answer the person has since said otherwise to, says what and when, and asks the person themself', async () => {
  const user = userEvent.setup();
  server.rows.get('c1')!.turns = [
    turns[0],
    {
      ...turns[1],
      reply: {
        ...reply,
        team_answers: [
          answerCard({
            status: 'stale',
            stale_note: '10 月 27 日「周会」里说：旧模板 10 月底就停了',
          }),
        ],
      },
    },
  ];
  localStorage.setItem(CURRENT_CHAT_KEY, 'c1');
  mount();
  const card = await screen.findByRole('article', { name: '团队答案' });
  expect(within(card).getByText('可能过期')).toBeVisible();
  expect(within(card).getByText(/10 月底就停了/u)).toBeVisible();
  await user.click(within(card).getByRole('button', { name: '问林舟本人' }));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([url]) =>
        String(url).endsWith('/team-answers/ta_1/ask'),
      ),
    ).toBe(true),
  );
});

it('tells the asker when the question could not be handed on, and lets them try again', async () => {
  const user = userEvent.setup();
  server.rows.get('c1')!.turns = [
    turns[0],
    { ...turns[1], reply: { ...reply, team_answers: [answerCard()] } },
  ];
  const respond = fetcher.getMockImplementation() as (
    url: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation(async (url: string, init?: RequestInit) =>
    String(url).endsWith('/ask')
      ? json({ detail: '林舟还没认领分身，请直接联系本人' }, 409)
      : respond(url, init),
  );
  localStorage.setItem(CURRENT_CHAT_KEY, 'c1');
  mount();
  const card = await screen.findByRole('article', { name: '团队答案' });
  await user.click(within(card).getByRole('button', { name: '问林舟本人' }));
  expect(await within(card).findByRole('alert')).toHaveTextContent(
    '还没认领分身',
  );
  expect(
    within(card).getByRole('button', { name: '问林舟本人' }),
  ).toBeEnabled();
});

it('does not say a team answer was a general one under the card, which is the person’s own confirmed word', async () => {
  server.rows.get('c1')!.turns = [
    turns[0],
    {
      ...turns[1],
      content: '团队里已经有确认过的答案，见上面的团队答案。',
      reply: {
        ...reply,
        mode: 'general',
        cited: [],
        reply: '团队里已经有确认过的答案，见上面的团队答案。',
        team_answers: [answerCard()],
      },
    },
  ];
  localStorage.setItem(CURRENT_CHAT_KEY, 'c1');
  mount();
  await screen.findByRole('article', { name: '团队答案' });
  const twin = screen.getByRole('article', { name: '分身回复' });
  expect(within(twin).getByText(/见上面的团队答案/u)).toBeVisible();
  expect(within(twin).queryByText('通用建议，不代表本人观点')).toBeNull();
});
