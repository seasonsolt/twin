import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider, TooltipProvider } from '../components/ui';
import type { ChatReply, Turn } from '../features/chat/types';
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

// The person is 林舟, who took their twin and said it is all right; 许清禾 and 王屿 are colleagues' twins.
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status });
const when = '2026-10-20T10:00:00';
const twin = (id: string, name: string, extra: Partial<Persona> = {}) =>
  ({
    id,
    name,
    avatar_url: null,
    sources: 3,
    created_at: '',
    is_default: id === 'default',
    can_manage: true,
    ...extra,
  }) satisfies Persona;
const personas = [
  twin('default', '林舟', { mine: true, approved: true }),
  twin('p-qing', '许清禾'),
  twin('p-wang', '王屿'),
];
const base = {
  citations: [],
  confidence: 0.9,
  abstain: false,
  abstain_reason: '',
  retrieved_ids: [],
  cited: [],
  mode: 'general' as const,
};
const answer = (reply: Partial<ChatReply> & { reply: string }): ChatReply => ({
  ...base,
  ...reply,
});
const stream = (reply: ChatReply) =>
  new Response(`event: final\ndata: ${JSON.stringify(reply)}\n\n`, {
    headers: { 'Content-Type': 'text/event-stream' },
  });
const user = (id: string, content: string): Turn => ({
  id,
  role: 'user',
  content,
  timestamp: when,
});
const said = (id: string, reply: ChatReply): Turn => ({
  id,
  role: 'twin',
  content: reply.reply,
  reply,
  timestamp: when,
});

let server: ReturnType<typeof conversationServer>;
let fetcher: ReturnType<typeof vi.fn>;
let streamed: ReturnType<typeof answer>[];
const bodyOf = (url: string, method?: string) =>
  fetcher.mock.calls
    .filter(
      ([path, init]) => path === url && (!method || init?.method === method),
    )
    .map(([, init]) => JSON.parse(String(init?.body ?? 'null')) as unknown);

function mount(items: Persona[] = personas, entry = '/chat') {
  useAuth.setState({
    identity: {
      email: 'me@example.com',
      admin: false,
      auth_enabled: true,
      features: { work: true },
    },
  });
  usePersonas.setState({
    id: 'default',
    items,
    // Switching is the page going to the twin: what it does is not under test here.
    switchTo: vi.fn(async (id: string) => {
      setPersonaId(id);
      usePersonas.setState({ id });
    }),
  });
  return render(
    <TooltipProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={[entry]}>
          <Chat />
        </MemoryRouter>
      </ConfirmProvider>
    </TooltipProvider>,
  );
}

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  useChatLayout.setState({ sheet: undefined, stage: undefined });
  useStatus.setState({ data: null, error: null });
  setPersonaId('default');
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: query === '(min-width: 1280px)',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  server = conversationServer();
  server.own.mine = { persona_id: 'default', pending: 2 };
  server.rows.set('c-self', {
    id: 'c-self',
    title: '我上周答应过谁什么',
    turns: [
      user('u1', '我上周答应过谁什么'),
      said('t1', answer({ reply: '三件。' })),
    ],
    updated_at: '2026-10-20T11:00:00',
    persona: 'default',
    audience: 'self',
  });
  server.rows.set('c-qing', {
    id: 'c-qing',
    title: '评审定的接口',
    turns: [
      user('u2', '评审定了什么'),
      said('t2', answer({ reply: '接口先按 v2。' })),
    ],
    updated_at: '2026-10-20T09:00:00',
    persona: 'p-qing',
  });
  server.rows.set('c-wang', {
    id: 'c-wang',
    title: '招聘面试的问题',
    turns: [
      user('u3', '面试问什么'),
      said('t3', answer({ reply: '先问最近做的事。' })),
    ],
    updated_at: '2026-10-19T09:00:00',
    persona: 'p-wang',
  });
  server.tasks.push({
    task_id: 'w_bbbbbbbbbbbb',
    persona_id: 'p-qing',
    title: '整理周报',
    status: 'idle',
    updated_at: '2026-10-20T08:00:00',
  });
  streamed = [];
  fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const saved = server.respond(url, init);
    if (saved) return saved;
    if (url === '/api/persona/chat/stream') {
      const body = JSON.parse(String(init?.body)) as {
        conversation_id: string | null;
        preview?: boolean;
      };
      // A trial question is saved nowhere.
      if (body.conversation_id && !body.preview)
        server.append(init!, streamed[0] ?? answer({ reply: '好的。' }));
      return stream(streamed.shift() ?? answer({ reply: '好的。' }));
    }
    if (url === '/api/media/capabilities')
      return json({ available: false, video: { available: false } });
    if (url.startsWith('/api/persona/notes/')) return json({ ok: true });
    if (url.startsWith('/api/persona/ledger/')) return json({ ok: true });
    return json({ stale: false });
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => {
  setPersonaId('default');
  useAuth.setState({ identity: null });
  usePersonas.setState({ id: '', items: [] });
});

/** A row's button: its title, not the “…” of its menu. */
const row = (title: string) => new RegExp(`^${title}(?!的更多操作)`, 'u');
const list = () => screen.findByRole('region', { name: /的对话$/u });

it('sets the assistant apart above everyone’s conversations, with how many wait for the person, and keeps its list to itself', async () => {
  const person = userEvent.setup();
  mount();
  const sheet = await list();
  // Everyone's conversations, none of the assistant's among them.
  expect(
    await within(sheet).findByRole('button', { name: row('评审定的接口') }),
  ).toBeVisible();
  expect(
    within(sheet).getByRole('button', { name: row('招聘面试的问题') }),
  ).toBeVisible();
  expect(
    within(sheet).queryByRole('button', { name: row('我上周答应过谁什么') }),
  ).toBeNull();
  const pinned = within(sheet).getByRole('button', { name: /^我的分身/u });
  expect(within(pinned).getByTitle('2 条等你决定')).toHaveTextContent('2');
  await person.click(pinned);
  expect(
    await within(sheet).findByRole('button', {
      name: row('我上周答应过谁什么'),
    }),
  ).toBeVisible();
  expect(
    within(sheet).queryByRole('button', { name: row('评审定的接口') }),
  ).toBeNull();
  expect(pinned).toHaveAttribute('aria-pressed', 'true');
  // Asked for the person's own list, and only it.
  expect(
    fetcher.mock.calls.some(
      ([url]) => url === '/api/personas/conversations?mine=true',
    ),
  ).toBe(true);
  expect(screen.getByText('仅你可见')).toBeVisible();
  await person.click(pinned);
  expect(
    await within(sheet).findByRole('button', { name: row('评审定的接口') }),
  ).toBeVisible();
});

it('has no assistant to set apart for someone who is not the person of any twin', async () => {
  server.own.mine = null;
  mount([twin('default', '林舟'), personas[1]]);
  const sheet = await list();
  await within(sheet).findByRole('button', { name: row('评审定的接口') });
  expect(
    within(sheet).queryByRole('button', { name: /^我的分身/u }),
  ).toBeNull();
  expect(screen.queryByText('仅你可见')).toBeNull();
  expect(screen.queryByRole('button', { name: '看同事会得到什么' })).toBeNull();
});

it('narrows the list to a person or to the tasks, and says whom each row is with', async () => {
  const person = userEvent.setup();
  mount();
  const sheet = await list();
  const rows = await within(sheet).findAllByRole('listitem');
  expect(rows.map((row) => row.textContent)).toEqual([
    expect.stringMatching(/^评审定的接口许清禾/u),
    expect.stringMatching(/^整理周报\s*许清禾\s*·\s*任务/u),
    expect.stringMatching(/^招聘面试的问题王屿/u),
  ]);
  const scope = within(sheet).getByRole('group', { name: '对话范围' });
  expect(
    within(scope)
      .getAllByRole('button')
      .map((chip) => chip.textContent),
  ).toEqual(['全部', '许清禾', '王屿', '任务']);
  await person.click(within(scope).getByRole('button', { name: '王屿' }));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(
        ([url]) => url === '/api/personas/conversations?with=p-wang',
      ),
    ).toBe(true),
  );
  await waitFor(() =>
    expect(
      within(sheet).queryByRole('button', { name: row('评审定的接口') }),
    ).toBeNull(),
  );
  // Narrowed to one person, their name is no longer said on each row.
  expect(
    await within(sheet).findByRole('button', { name: /^招聘面试的问题\s/u }),
  ).toBeVisible();
  await person.click(within(scope).getByRole('button', { name: '任务' }));
  expect(
    await within(sheet).findByRole('button', {
      name: /^整理周报\s*许清禾\s*·\s*任务/u,
    }),
  ).toBeVisible();
  expect(
    within(sheet).queryByRole('button', { name: row('招聘面试的问题') }),
  ).toBeNull();
  await person.click(within(scope).getByRole('button', { name: '全部' }));
  expect(
    await within(sheet).findByRole('button', { name: row('评审定的接口') }),
  ).toBeVisible();
});

it('goes to another twin to open its conversation, and writes to the twin it opened', async () => {
  const person = userEvent.setup();
  mount();
  const sheet = await list();
  await person.click(
    await within(sheet).findByRole('button', { name: row('评审定的接口') }),
  );
  expect(await screen.findByText('接口先按 v2。')).toBeVisible();
  expect(usePersonas.getState().id).toBe('p-qing');
  expect(
    screen.getByRole('button', { name: '切换分身（当前：许清禾）' }),
  ).toBeVisible();
  // It was opened from the list, not asked of the twin the page had.
  expect(
    fetcher.mock.calls.some(
      ([url, init]) =>
        url === '/api/conversations/c-qing' &&
        new Headers(init?.headers).get('X-Twin-Persona') === 'p-qing',
    ),
  ).toBe(true);
  // Not the person's own twin: nothing of the assistant is offered.
  expect(screen.queryByRole('button', { name: '看同事会得到什么' })).toBeNull();
});

it('is the assistant only in the person’s own twin, and offers to try a question as a colleague would be answered', async () => {
  const person = userEvent.setup();
  streamed.push(
    answer({
      reply: '这个我回头答复你。',
      preview: {
        withheld: [{ id: 'pi_1', facet: '家庭', text: '陪家人复查' }],
      },
    }),
    answer({
      reply: '三件：给许清禾重算留存口径。',
      mode: 'grounded',
      citations: ['x'],
    }),
  );
  mount();
  const sheet = await list();
  await person.click(within(sheet).getByRole('button', { name: /^我的分身/u }));
  await screen.findByText('仅你可见');
  expect(screen.getByRole('textbox', { name: '你说' })).toHaveAttribute(
    'placeholder',
    '问问我的分身，或说“记一下…”“帮我问问…”',
  );
  // Asked as a colleague would be: the one question alone, marked, and what it left out named.
  const trial = screen.getByRole('button', { name: '看同事会得到什么' });
  await person.click(trial);
  expect(trial).toHaveAttribute('aria-pressed', 'true');
  await person.type(
    screen.getByRole('textbox', { name: '你说' }),
    '下周三你在吗？',
  );
  await person.click(screen.getByRole('button', { name: '发送' }));
  expect(await screen.findByText('这个我回头答复你。')).toBeVisible();
  expect(bodyOf('/api/persona/chat/stream')[0]).toMatchObject({
    preview: true,
    messages: [{ role: 'user', content: '下周三你在吗？' }],
  });
  expect(screen.getByText('同事会得到')).toBeVisible();
  expect(screen.getByText('试问')).toBeVisible();
  expect(screen.getByText('未用 · 家庭')).toBeVisible();
  // No conversation was made of it, and it is not sent on as part of what was said.
  expect(server.rows.size).toBe(3);
  await person.click(trial);
  await person.type(
    screen.getByRole('textbox', { name: '你说' }),
    '我上周答应过谁什么',
  );
  await person.click(screen.getByRole('button', { name: '发送' }));
  expect(await screen.findByText('三件：给许清禾重算留存口径。')).toBeVisible();
  const sent = bodyOf('/api/persona/chat/stream')[1] as {
    preview?: boolean;
    messages: { content: string }[];
  };
  expect(sent.preview).toBeUndefined();
  expect(sent.messages.map((m) => m.content)).toEqual(['我上周答应过谁什么']);
});

it('keeps files added for an ordinary message out of a trial question, and says so', async () => {
  const person = userEvent.setup();
  streamed.push(answer({ reply: '这个我回头答复你。' }));
  mount();
  const sheet = await list();
  await person.click(within(sheet).getByRole('button', { name: /^我的分身/u }));
  await screen.findByText('仅你可见');
  await person.upload(
    screen.getByLabelText('选择附件'),
    new File(['合同期限是一年。'], '合同.txt', { type: 'text/plain' }),
  );
  expect(screen.getByText('合同.txt')).toBeVisible();
  await person.click(screen.getByRole('button', { name: '看同事会得到什么' }));
  // The files wait: not shown as going with the question, and none can be added to it.
  expect(screen.queryByText('合同.txt')).toBeNull();
  expect(
    screen.getByText(/看同事会得到什么不带附件，已添加的 1 个附件留到/u),
  ).toBeVisible();
  expect(screen.getByRole('button', { name: /^添加附件/u })).toBeDisabled();
  expect(screen.getByLabelText('选择附件')).toBeDisabled();
  await person.type(
    screen.getByRole('textbox', { name: '你说' }),
    '下周三你在吗？',
  );
  await person.click(screen.getByRole('button', { name: '发送' }));
  expect(await screen.findByText('这个我回头答复你。')).toBeVisible();
  expect(
    fetcher.mock.calls.some(
      ([url]) => url === '/api/persona/chat/stream-with-files',
    ),
  ).toBe(false);
  // Back to an ordinary message, they are there to go with it.
  await person.click(screen.getByRole('button', { name: '看同事会得到什么' }));
  expect(screen.getByText('合同.txt')).toBeVisible();
  expect(screen.getByRole('button', { name: /^添加附件/u })).toBeEnabled();
});

it('shows what the assistant took down, with the choice of who may use it, and takes it back when asked', async () => {
  const person = userEvent.setup();
  streamed.push(
    answer({
      reply: '记下了，先设为只有你能用。',
      note: { id: 'src_n1', text: '下周三请假，陪家人复查', tier: 'self' },
    }),
  );
  mount();
  const sheet = await list();
  await person.click(within(sheet).getByRole('button', { name: /^我的分身/u }));
  await screen.findByText('仅你可见');
  await person.type(
    screen.getByRole('textbox', { name: '你说' }),
    '记一下，下周三我请假陪家人复查',
  );
  await person.click(screen.getByRole('button', { name: '发送' }));
  const card = await screen.findByLabelText('记下的内容');
  expect(within(card).getByText('下周三请假，陪家人复查')).toBeVisible();
  const tiers = within(card).getByRole('radiogroup', {
    name: '谁能用这条记忆',
  });
  expect(within(tiers).getByRole('radio', { name: '只有我' })).toBeChecked();
  await person.click(within(tiers).getByRole('radio', { name: '同事能用' }));
  await waitFor(() =>
    expect(
      within(tiers).getByRole('radio', { name: '同事能用' }),
    ).toBeChecked(),
  );
  expect(bodyOf('/api/persona/notes/src_n1/tier', 'PUT')).toEqual([
    { tier: 'colleague' },
  ]);
  await person.click(within(tiers).getByRole('radio', { name: '不存' }));
  await waitFor(() =>
    expect(within(tiers).getByRole('radio', { name: '不存' })).toBeChecked(),
  );
  expect(bodyOf('/api/persona/notes/src_n1/tier', 'PUT').at(-1)).toEqual({
    tier: 'none',
  });
});

it('says a promise the person made was written into their commitments, and takes it back when asked', async () => {
  const person = userEvent.setup();
  streamed.push(
    answer({
      reply: '记下了：周五前给王屿发布方案。',
      commitment: {
        entry_id: 'le_1',
        what: '周五前给王屿发布方案',
        to: '王屿',
        due: '2026-10-30',
      },
    }),
  );
  mount();
  const sheet = await list();
  await person.click(within(sheet).getByRole('button', { name: /^我的分身/u }));
  await screen.findByText('仅你可见');
  await person.type(
    screen.getByRole('textbox', { name: '你说' }),
    '我答应王屿周五前给方案',
  );
  await person.click(screen.getByRole('button', { name: '发送' }));
  const line = await screen.findByText(
    /已记入承诺：周五前给王屿发布方案 · 2026-10-30前/u,
  );
  await person.click(within(line).getByRole('button', { name: '撤销' }));
  await waitFor(() => expect(screen.queryByText(/已记入承诺/u)).toBeNull());
  expect(bodyOf('/api/persona/ledger/le_1/review', 'POST')).toEqual([
    { action: 'reject' },
  ]);
});

it('offers to fill in what the profile did not have, and speaks of the person as "你"', async () => {
  const person = userEvent.setup();
  streamed.push(
    answer({
      reply: '资料里没有这条，要补一句吗？',
      abstain: true,
      mode: 'abstain',
      abstain_reason: '没有相关资料',
    }),
  );
  mount();
  const sheet = await list();
  await person.click(within(sheet).getByRole('button', { name: /^我的分身/u }));
  await screen.findByText('仅你可见');
  await person.type(
    screen.getByRole('textbox', { name: '你说' }),
    '我对海鲜过敏吗',
  );
  await person.click(screen.getByRole('button', { name: '发送' }));
  await screen.findByText('资料里没有这条，要补一句吗？');
  // Not "需要问本人": in their own conversation the person is the one asked.
  expect(screen.queryByText('资料不足，需要问本人')).toBeNull();
  expect(screen.getByText('资料里没有')).toBeVisible();
  await person.click(screen.getByRole('button', { name: '补一句' }));
  expect(screen.getByRole('textbox', { name: '你说' })).toHaveValue('记一下，');
});

it('marks what the assistant asked in the person’s name, and lists it apart with the assistant’s own conversations', async () => {
  const person = userEvent.setup();
  server.rows.get('c-qing')!.via = 'delegate';
  server.rows.get('c-self')!.delegated = 2;
  mount();
  const sheet = await list();
  // Among everyone's, it says who it was with and that the assistant asked.
  expect(
    await within(sheet).findByRole('button', {
      name: /^评审定的接口\s*许清禾\s*·\s*助手代问/u,
    }),
  ).toBeVisible();
  expect(within(sheet).queryByRole('region', { name: '问同事' })).toBeNull();
  // With the assistant's own: its conversation says how many it asked, and what it asked is under 问同事.
  await person.click(within(sheet).getByRole('button', { name: /^我的分身/u }));
  expect(
    await within(sheet).findByRole('button', {
      name: /^我上周答应过谁什么\s*代问 2 人/u,
    }),
  ).toBeVisible();
  const asked = within(sheet).getByRole('region', { name: '问同事' });
  expect(
    within(asked).getByRole('button', {
      name: /^评审定的接口\s*许清禾\s*·\s*助手代问/u,
    }),
  ).toBeVisible();
  expect(within(asked).queryByText('我上周答应过谁什么')).toBeNull();
});

it('opens a conversation of another twin from its address: the twin it is with, then the conversation', async () => {
  mount(personas, '/chat?with=p-wang&open=c-wang');
  expect(await screen.findByText('先问最近做的事。')).toBeVisible();
  expect(usePersonas.getState().id).toBe('p-wang');
});

it('opens on the person’s own twin from ``?with=me``', async () => {
  // The page starts on another twin (``default``); the person's own is 王屿 here.
  mount(
    [
      twin('default', '林舟'),
      twin('p-wang', '王屿', { mine: true, approved: true }),
    ],
    '/chat?with=me',
  );
  await waitFor(() => expect(usePersonas.getState().id).toBe('p-wang'));
});

it('keeps to the assistant’s list while the page is still on its way to the person’s own twin', async () => {
  const person = userEvent.setup();
  // The page is on 林舟's twin (``default``), which is not theirs; the person's own is 王屿 here.
  server.own.mine = { persona_id: 'p-wang', pending: 0 };
  mount([
    twin('default', '林舟'),
    twin('p-wang', '王屿', { mine: true, approved: true }),
  ]);
  // Going to a twin takes a while: it arrives only when ``arrive`` is called.
  let arrive = () => {};
  usePersonas.setState({
    switchTo: vi.fn(
      (id: string) =>
        new Promise<void>((resolve) => {
          arrive = () => {
            setPersonaId(id);
            usePersonas.setState({ id });
            resolve();
          };
        }),
    ),
  });
  const sheet = await list();
  const pinned = await within(sheet).findByRole('button', {
    name: /^我的分身/u,
  });
  await person.click(pinned);
  expect(pinned).toHaveAttribute('aria-pressed', 'true');
  await act(async () => arrive());
  expect(usePersonas.getState().id).toBe('p-wang');
  expect(
    await within(sheet).findByRole('button', { name: row('招聘面试的问题') }),
  ).toBeVisible();
  expect(
    within(sheet).getByRole('button', { name: /^我的分身/u }),
  ).toHaveAttribute('aria-pressed', 'true');
});
