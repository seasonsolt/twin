import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router';
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
let media: object;
const bodyOf = (url: string, method?: string) =>
  fetcher.mock.calls
    .filter(
      ([path, init]) => path === url && (!method || init?.method === method),
    )
    .map(([, init]) => JSON.parse(String(init?.body ?? 'null')) as unknown);

// The state of the page's history entry, which a reload of the page brings back.
let entryState: unknown;
function EntryState() {
  entryState = useLocation().state;
  return null;
}

function mount(
  items: Persona[] = personas,
  entry: string | { pathname: string; state: unknown } = '/chat',
  features: { work: boolean; ledger?: boolean } = { work: true },
  edition: 'persona' | 'team' = 'team',
) {
  useAuth.setState({
    identity: {
      email: 'me@example.com',
      admin: false,
      auth_enabled: true,
      features,
      edition,
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
          <EntryState />
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
  media = { available: false, video: { available: false } };
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
    if (url === '/api/media/capabilities') return json(media);
    if (url.startsWith('/api/persona/notes/')) return json({ ok: true });
    if (url.startsWith('/api/persona/ledger/')) return json({ ok: true });
    return json({ stale: false });
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => {
  vi.useRealTimers();
  setPersonaId('default');
  useAuth.setState({ identity: null });
  usePersonas.setState({ id: '', items: [] });
});

/** A row's button: its title, not the “…” of its menu. */
const row = (title: string) => new RegExp(`^${title}(?!的更多操作)`, 'u');
const list = () => screen.findByRole('region', { name: '对话列表' });
/** On the person’s own twin the page opens on the assistant’s list; this goes on to everyone’s. */
async function everyone(sheet: HTMLElement) {
  const pinned = await within(sheet).findByRole('button', {
    name: /^我的分身/u,
  });
  await waitFor(() => expect(pinned).toHaveAttribute('aria-pressed', 'true'));
  await userEvent.click(pinned);
  await waitFor(() => expect(pinned).toHaveAttribute('aria-pressed', 'false'));
}

it('opens on the assistant’s list on the person’s own twin, with how many wait for the person, and leaves it for everyone’s', async () => {
  const person = userEvent.setup();
  mount();
  const sheet = await list();
  const pinned = await within(sheet).findByRole('button', {
    name: /^我的分身/u,
  });
  // The twin the page is on is the person’s own: the conversations had here are the assistant’s, and they are listed.
  expect(
    await within(sheet).findByRole('button', {
      name: row('我上周答应过谁什么'),
    }),
  ).toBeVisible();
  expect(
    within(sheet).queryByRole('button', { name: row('评审定的接口') }),
  ).toBeNull();
  expect(pinned).toHaveAttribute('aria-pressed', 'true');
  expect(within(pinned).getByTitle('2 条等你决定')).toHaveTextContent('2');
  // Asked for the person's own list, and only it.
  expect(
    fetcher.mock.calls.some(
      ([url]) => url === '/api/personas/conversations?mine=true',
    ),
  ).toBe(true);
  expect(screen.getByText('仅你可见')).toBeVisible();
  // Everyone's conversations: none of the assistant's among them.
  await person.click(pinned);
  expect(
    await within(sheet).findByRole('button', { name: row('评审定的接口') }),
  ).toBeVisible();
  expect(
    within(sheet).getByRole('button', { name: row('招聘面试的问题') }),
  ).toBeVisible();
  expect(
    within(sheet).queryByRole('button', { name: row('我上周答应过谁什么') }),
  ).toBeNull();
  expect(pinned).toHaveAttribute('aria-pressed', 'false');
  await person.click(pinned);
  expect(
    await within(sheet).findByRole('button', {
      name: row('我上周答应过谁什么'),
    }),
  ).toBeVisible();
});

it('follows the twin the page is on: a list narrowed to one person is dropped for another twin, and the assistant’s list comes with the person’s own', async () => {
  const person = userEvent.setup();
  mount();
  const sheet = await list();
  await everyone(sheet);
  const scope = within(sheet).getByRole('group', { name: '对话范围' });
  await person.click(within(scope).getByRole('button', { name: '王屿' }));
  expect(within(scope).getByRole('button', { name: '王屿' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  // Another twin to write to: not the list of the person it was narrowed to.
  await act(async () => {
    await usePersonas.getState().switchTo('p-qing');
  });
  await waitFor(() =>
    expect(within(scope).getByRole('button', { name: '全部' })).toHaveAttribute(
      'aria-pressed',
      'true',
    ),
  );
  // And back on their own: the assistant’s.
  await act(async () => {
    await usePersonas.getState().switchTo('default');
  });
  await waitFor(() =>
    expect(
      within(sheet).getByRole('button', { name: /^我的分身/u }),
    ).toHaveAttribute('aria-pressed', 'true'),
  );
  expect(
    await within(sheet).findByRole('button', {
      name: row('我上周答应过谁什么'),
    }),
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
  expect(screen.queryByRole('button', { name: '试问' })).toBeNull();
});

it('narrows the list to a person or to the tasks, and says whom each row is with', async () => {
  const person = userEvent.setup();
  mount();
  const sheet = await list();
  await everyone(sheet);
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
  await everyone(sheet);
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
  expect(screen.queryByRole('button', { name: '试问' })).toBeNull();
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
  await list();
  await screen.findByText('仅你可见');
  expect(screen.getByRole('textbox', { name: '你说' })).toHaveAttribute(
    'placeholder',
    '问问我的分身，或说“记一下…”“帮我问问…”',
  );
  // Asked as a colleague would be: the one question alone, marked, and what it left out named.
  const trial = screen.getByRole('button', { name: '试问' });
  // The short word says what it does when the pointer rests on it.
  await person.hover(trial);
  expect(await screen.findByRole('tooltip')).toHaveTextContent(
    '看同事问同一句会得到什么',
  );
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
  expect(screen.getAllByText('试问')).toHaveLength(2);
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
  await list();
  await screen.findByText('仅你可见');
  await person.upload(
    screen.getByLabelText('选择附件'),
    new File(['合同期限是一年。'], '合同.txt', { type: 'text/plain' }),
  );
  expect(screen.getByText('合同.txt')).toBeVisible();
  await person.click(screen.getByRole('button', { name: '试问' }));
  // The files wait: not shown as going with the question, and none can be added to it.
  expect(screen.queryByText('合同.txt')).toBeNull();
  expect(
    screen.getByText(/试问不带附件，已添加的 1 个附件留到/u),
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
  await person.click(screen.getByRole('button', { name: '试问' }));
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
  await list();
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
  // In the order of the page where the same choice is made for what was asked while they were away.
  expect(
    within(tiers)
      .getAllByRole('radio')
      .map((radio) => radio.getAttribute('aria-label') ?? radio.textContent),
  ).toEqual(['同事能用', '只有我', '不存']);
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
  // Taken back, it is gone: nothing is left to choose, so no choice that would only fail.
  expect(await within(card).findByText('已不存')).toBeVisible();
  expect(within(card).queryByRole('radiogroup')).toBeNull();
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
  await list();
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
  await list();
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
  const box = screen.getByRole('textbox', { name: '你说' });
  expect(box).toHaveValue('记一下，');
  // The words are meant to be gone on from: the box has the cursor, after them.
  await waitFor(() => expect(box).toHaveFocus());
  expect((box as HTMLTextAreaElement).selectionStart).toBe('记一下，'.length);
});

it('says nothing of a promise written into the commitments where that page is switched off', async () => {
  const person = userEvent.setup();
  streamed.push(
    answer({
      reply: '记下了：周五前给王屿发布方案。',
      commitment: {
        entry_id: 'le_1',
        what: '周五前给王屿发布方案',
        to: '王屿',
        due: null,
      },
    }),
  );
  mount(personas, '/chat', { work: true, ledger: false });
  await list();
  await screen.findByText('仅你可见');
  await person.type(
    screen.getByRole('textbox', { name: '你说' }),
    '我答应王屿周五前给方案',
  );
  await person.click(screen.getByRole('button', { name: '发送' }));
  expect(
    await screen.findByText('记下了：周五前给王屿发布方案。'),
  ).toBeVisible();
  expect(screen.queryByText(/已记入承诺/u)).toBeNull();
  expect(screen.queryByRole('button', { name: '撤销' })).toBeNull();
});

it('puts no "how it answered" badge or copy button under what the assistant asked colleagues, but keeps them under an answer', async () => {
  const person = userEvent.setup();
  const original = fetcher.getMockImplementation() as (
    url: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation(async (url: string, init?: RequestInit) =>
    url === '/api/persona/delegations/d1'
      ? json({ id: 'd1', question: '问', targets: [], limit: 3 })
      : original(url, init),
  );
  streamed.push(
    answer({
      reply: '已向许清禾提了问题。',
      delegation: { id: 'd1', summary: '' },
    }),
    answer({ reply: '三件。' }),
  );
  mount();
  await list();
  await screen.findByText('仅你可见');
  await person.type(
    screen.getByRole('textbox', { name: '你说' }),
    '帮我问问许清禾',
  );
  await person.click(screen.getByRole('button', { name: '发送' }));
  const asked = await screen.findByText('已向许清禾提了问题。');
  const message = asked.closest('article')!;
  expect(within(message).queryByText('通用回答')).toBeNull();
  expect(within(message).queryByRole('button', { name: '复制' })).toBeNull();
  await person.type(
    screen.getByRole('textbox', { name: '你说' }),
    '我上周答应过谁什么',
  );
  await person.click(screen.getByRole('button', { name: '发送' }));
  const answered = (await screen.findByText('三件。')).closest('article')!;
  expect(within(answered).getByText('通用回答')).toBeVisible();
  expect(within(answered).getByRole('button', { name: '复制' })).toBeVisible();
});

it('marks what the assistant asked in the person’s name, and lists it apart with the assistant’s own conversations', async () => {
  const person = userEvent.setup();
  server.rows.get('c-qing')!.via = 'delegate';
  server.rows.get('c-self')!.delegated = 2;
  mount();
  const sheet = await list();
  await everyone(sheet);
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
  // In the conversation itself: the list holds the same words as a preview, hidden. The page fades in on the twin
  // it switched to, so the words are visible once the fade is over.
  const said = await within(
    await screen.findByTestId('chat-messages'),
  ).findByText('先问最近做的事。');
  await waitFor(() => expect(said).toBeVisible());
  expect(usePersonas.getState().id).toBe('p-wang');
});

it('opens on the person’s own twin from ``?with=me``, with the assistant’s list', async () => {
  // The page starts on another twin (``default``); the person's own is 王屿 here.
  server.own.mine = { persona_id: 'p-wang', pending: 0 };
  mount(
    [
      twin('default', '林舟'),
      twin('p-wang', '王屿', { mine: true, approved: true }),
    ],
    '/chat?with=me',
  );
  await waitFor(() => expect(usePersonas.getState().id).toBe('p-wang'));
  const sheet = await list();
  // Their conversations with it are the assistant's: they are listed, and the pinned choice is on.
  expect(
    await within(sheet).findByRole('button', { name: row('招聘面试的问题') }),
  ).toBeVisible();
  expect(
    within(sheet).queryByRole('button', { name: row('评审定的接口') }),
  ).toBeNull();
  expect(
    within(sheet).getByRole('button', { name: /^我的分身/u }),
  ).toHaveAttribute('aria-pressed', 'true');
});

it('goes nowhere on ``?with=me`` for someone with no twin of their own, and waits for the twins to be known', async () => {
  // No twin is theirs: the page stays where it is, on everyone's.
  server.own.mine = null;
  mount([twin('default', '林舟'), personas[1]], '/chat?with=me');
  const sheet = await list();
  await within(sheet).findByRole('button', { name: row('评审定的接口') });
  expect(usePersonas.getState().id).toBe('default');
  expect(usePersonas.getState().switchTo).not.toHaveBeenCalled();
  expect(within(sheet).getByRole('button', { name: '全部' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
});

it('waits for the twins to be known before ``?with=me`` goes to the person’s own', async () => {
  server.own.mine = { persona_id: 'p-wang', pending: 0 };
  mount([], '/chat?with=me');
  await list();
  expect(usePersonas.getState().switchTo).not.toHaveBeenCalled();
  act(() =>
    usePersonas.setState({
      items: [
        twin('default', '林舟'),
        twin('p-wang', '王屿', { mine: true, approved: true }),
      ],
    }),
  );
  await waitFor(() => expect(usePersonas.getState().id).toBe('p-wang'));
});

it('pages the assistant’s list from where its own conversations end, not counting what it asked colleagues', async () => {
  const person = userEvent.setup();
  server.paging.size = 1;
  server.rows.set('c-self-2', {
    id: 'c-self-2',
    title: '更早问过的事',
    turns: [user('u9', '更早问过的事'), said('t9', answer({ reply: '嗯。' }))],
    updated_at: '2026-10-18T09:00:00',
    persona: 'default',
    audience: 'self',
  });
  server.rows.get('c-qing')!.via = 'delegate';
  mount();
  const sheet = await list();
  expect(
    await within(sheet).findByRole('button', {
      name: row('我上周答应过谁什么'),
    }),
  ).toBeVisible();
  expect(within(sheet).getByRole('region', { name: '问同事' })).toBeVisible();
  await person.click(within(sheet).getByRole('button', { name: '显示更多' }));
  expect(
    await within(sheet).findByRole('button', { name: row('更早问过的事') }),
  ).toBeVisible();
  expect(
    fetcher.mock.calls.some(
      ([url]) => url === '/api/personas/conversations?offset=1&mine=true',
    ),
  ).toBe(true);
  expect(within(sheet).queryByRole('button', { name: '显示更多' })).toBeNull();
});

it('shows more tasks than a page holds from the task list', async () => {
  const person = userEvent.setup();
  server.paging.size = 1;
  server.tasks.push({
    task_id: 'w_cccccccccccc',
    persona_id: 'p-qing',
    title: '整理会议纪要',
    status: 'idle',
    updated_at: '2026-10-19T08:00:00',
  });
  mount();
  const sheet = await list();
  await everyone(sheet);
  await person.click(within(sheet).getByRole('button', { name: '任务' }));
  expect(
    await within(sheet).findByRole('button', { name: row('整理周报') }),
  ).toBeVisible();
  expect(
    within(sheet).queryByRole('button', { name: row('整理会议纪要') }),
  ).toBeNull();
  await person.click(within(sheet).getByRole('button', { name: '显示更多' }));
  expect(
    await within(sheet).findByRole('button', { name: row('整理会议纪要') }),
  ).toBeVisible();
  expect(
    fetcher.mock.calls.some(
      ([url]) => url === '/api/personas/conversations?task_offset=1',
    ),
  ).toBe(true);
  // The first of them stays where it was.
  expect(
    within(sheet).getByRole('button', { name: row('整理周报') }),
  ).toBeVisible();
});

it('renames and deletes another twin’s conversation and task as that twin, and the list follows', async () => {
  const person = userEvent.setup();
  mount();
  const sheet = await list();
  await everyone(sheet);
  const headerOf = (url: string, method: string) =>
    new Headers(
      fetcher.mock.calls.find(
        ([path, init]) => path === url && init?.method === method,
      )?.[1]?.headers,
    ).get('X-Twin-Persona');
  await person.click(
    await within(sheet).findByRole('button', {
      name: '评审定的接口的更多操作',
    }),
  );
  await person.click(within(sheet).getByRole('menuitem', { name: '重命名' }));
  const box = within(sheet).getByRole('textbox', { name: '对话标题' });
  await person.clear(box);
  await person.type(box, '接口评审结论');
  await person.click(within(sheet).getByRole('button', { name: '保存' }));
  expect(
    await within(sheet).findByRole('button', { name: row('接口评审结论') }),
  ).toBeVisible();
  expect(headerOf('/api/conversations/c-qing', 'PATCH')).toBe('p-qing');
  expect(bodyOf('/api/conversations/c-qing', 'PATCH')).toEqual([
    { title: '接口评审结论' },
  ]);
  await person.click(
    within(sheet).getByRole('button', { name: '接口评审结论的更多操作' }),
  );
  await person.click(within(sheet).getByRole('menuitem', { name: '删除' }));
  await person.click(
    within(await screen.findByRole('dialog', { name: '删除对话？' })).getByRole(
      'button',
      { name: '删除' },
    ),
  );
  await waitFor(() =>
    expect(
      within(sheet).queryByRole('button', { name: row('接口评审结论') }),
    ).toBeNull(),
  );
  expect(headerOf('/api/conversations/c-qing', 'DELETE')).toBe('p-qing');
  // A task of theirs: deleted on its own twin too.
  await within(sheet).findByRole('button', { name: row('整理周报') });
  await person.click(
    within(sheet).getByRole('button', { name: '整理周报的更多操作' }),
  );
  await person.click(within(sheet).getByRole('menuitem', { name: '删除' }));
  server.tasks.length = 0;
  await person.click(
    within(await screen.findByRole('dialog', { name: '删除任务？' })).getByRole(
      'button',
      { name: '删除' },
    ),
  );
  await waitFor(() =>
    expect(
      within(sheet).queryByRole('button', { name: row('整理周报') }),
    ).toBeNull(),
  );
  expect(headerOf('/api/persona/work/w_bbbbbbbbbbbb', 'DELETE')).toBe('p-qing');
});

it('keeps naming the conversation that is open when the list is of others, and when it is renamed', async () => {
  const person = userEvent.setup();
  mount();
  const sheet = await list();
  await person.click(
    await within(sheet).findByRole('button', {
      name: row('我上周答应过谁什么'),
    }),
  );
  const heading = await screen.findByRole('heading', {
    level: 1,
    name: '我上周答应过谁什么',
  });
  // Everyone's list does not hold the assistant's conversations: the one open is called what it is all the same.
  await everyone(sheet);
  expect(
    within(sheet).queryByRole('button', { name: row('我上周答应过谁什么') }),
  ).toBeNull();
  expect(heading).toHaveTextContent('我上周答应过谁什么');
  await person.click(within(sheet).getByRole('button', { name: /^我的分身/u }));
  await person.click(
    await within(sheet).findByRole('button', {
      name: '我上周答应过谁什么的更多操作',
    }),
  );
  await person.click(within(sheet).getByRole('menuitem', { name: '重命名' }));
  const box = within(sheet).getByRole('textbox', { name: '对话标题' });
  await person.clear(box);
  await person.type(box, '答应过的事');
  await person.click(within(sheet).getByRole('button', { name: '保存' }));
  await waitFor(() => expect(heading).toHaveTextContent('答应过的事'));
});

it('asks for the list again when a task of the twin in view is deleted, though the page did not read it itself', async () => {
  const person = userEvent.setup();
  server.tasks.push({
    task_id: 'w_dddddddddddd',
    persona_id: 'default',
    title: '汇总访谈',
    status: 'idle',
    updated_at: '2026-10-20T07:00:00',
  });
  mount();
  const sheet = await list();
  await person.click(
    await within(sheet).findByRole('button', { name: '汇总访谈的更多操作' }),
  );
  await person.click(within(sheet).getByRole('menuitem', { name: '删除' }));
  server.tasks.splice(
    server.tasks.findIndex((task) => task.task_id === 'w_dddddddddddd'),
    1,
  );
  await person.click(
    within(await screen.findByRole('dialog', { name: '删除任务？' })).getByRole(
      'button',
      { name: '删除' },
    ),
  );
  await waitFor(() =>
    expect(
      within(sheet).queryByRole('button', { name: row('汇总访谈') }),
    ).toBeNull(),
  );
});

it('asks for the list again when a conversation of the twin in view is renamed, whichever page of the list it is on', async () => {
  const person = userEvent.setup();
  server.paging.size = 1;
  server.rows.set('c-self-2', {
    id: 'c-self-2',
    title: '更早问过的事',
    turns: [user('u9', '更早问过的事'), said('t9', answer({ reply: '嗯。' }))],
    updated_at: '2026-10-18T09:00:00',
    persona: 'default',
    audience: 'self',
  });
  mount();
  const sheet = await list();
  await person.click(
    await within(sheet).findByRole('button', { name: '显示更多' }),
  );
  await within(sheet).findByRole('button', { name: row('更早问过的事') });
  await person.click(
    within(sheet).getByRole('button', { name: '更早问过的事的更多操作' }),
  );
  await person.click(within(sheet).getByRole('menuitem', { name: '重命名' }));
  const box = within(sheet).getByRole('textbox', { name: '对话标题' });
  await person.clear(box);
  await person.type(box, '换了个说法');
  await person.click(within(sheet).getByRole('button', { name: '保存' }));
  // The list was asked for again: from its first page, where the old title is no longer, and the new one is found
  // where the conversation is.
  await waitFor(() =>
    expect(
      within(sheet).queryByRole('button', { name: row('更早问过的事') }),
    ).toBeNull(),
  );
  await person.click(
    await within(sheet).findByRole('button', { name: '显示更多' }),
  );
  expect(
    await within(sheet).findByRole('button', { name: row('换了个说法') }),
  ).toBeVisible();
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

it('leads the top bar with the face of whom the conversation is with, the person’s own on their assistant', async () => {
  mount([
    twin('default', '林舟', {
      mine: true,
      approved: true,
      avatar_url: '/api/personas/default/avatar?persona=default',
    }),
    personas[1],
  ]);
  await list();
  const bar = (await screen.findByText('仅你可见')).closest('.chat-topbar')!;
  expect(bar.querySelector('img')).toHaveAttribute(
    'src',
    '/api/personas/default/avatar?persona=default',
  );
});

it('lets the person look at themself instead of asking in their own conversation, where work is off', async () => {
  const person = userEvent.setup();
  streamed.push(answer({ reply: '你 3 月说过想留下一个书房。你怎么看？' }));
  mount(personas, '/chat', { work: false });
  await list();
  await screen.findByText('仅你可见');
  const ways = screen.getByRole('radiogroup', { name: '这一轮' });
  expect(
    within(ways)
      .getAllByRole('radio')
      .map((way) => way.textContent),
  ).toEqual(['问答', '照镜子', '随便说', '记梦', '内在声音']);
  await person.click(within(ways).getByRole('radio', { name: '照镜子' }));
  await person.type(
    screen.getByRole('textbox', { name: '你说' }),
    '我为什么总想留下点什么',
  );
  await person.click(screen.getByRole('button', { name: '发送' }));
  expect(
    await screen.findByText('你 3 月说过想留下一个书房。你怎么看？'),
  ).toBeVisible();
  expect(bodyOf('/api/persona/chat/stream')[0]).toMatchObject({
    reflection: 'mirror',
  });
  // 像我 / 不像我 is the persona edition's.
  expect(screen.queryByRole('group', { name: '像不像我' })).toBeNull();
});

it('lets the person hear their own principles said back as their inner voice', async () => {
  const person = userEvent.setup();
  streamed.push(
    answer({
      reply: '你说过：“钱的事先说清楚再谈感情”（2024-03-02）。你会怎么选？',
    }),
  );
  mount(personas, '/chat', { work: false });
  await list();
  await screen.findByText('仅你可见');
  const ways = screen.getByRole('radiogroup', { name: '这一轮' });
  await person.click(within(ways).getByRole('radio', { name: '内在声音' }));
  await person.type(
    screen.getByRole('textbox', { name: '你说' }),
    '朋友找我借钱，我很纠结',
  );
  await person.click(screen.getByRole('button', { name: '发送' }));
  expect(await screen.findByText(/你会怎么选？/)).toBeVisible();
  expect(bodyOf('/api/persona/chat/stream')[0]).toMatchObject({
    reflection: 'voice',
  });
});

it.each([false, true])(
  'never reads the inner voice by itself nor makes it a video, and reads it in the person’s agreed voice only (own voice %s)',
  async (ownVoice) => {
    const person = userEvent.setup();
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
    media = {
      available: true,
      own_voice: ownVoice,
      video: { available: true },
    };
    streamed.push(
      answer({
        reply: '你说过：“先说清楚”。你会怎么选？',
        reflection: 'voice',
      }),
    );
    mount(personas, '/chat', { work: false });
    await list();
    await screen.findByText('仅你可见');
    const ways = screen.getByRole('radiogroup', { name: '这一轮' });
    await person.click(within(ways).getByRole('radio', { name: '内在声音' }));
    await person.type(screen.getByRole('textbox', { name: '你说' }), '纠结');
    await person.click(screen.getByRole('button', { name: '发送' }));
    const reply = (await screen.findByText(/你会怎么选？/)).closest('article')!;
    const called = (path: string) =>
      fetcher.mock.calls.some(([url]) => url === path);
    expect(called('/api/media/audio')).toBe(false);
    expect(called('/api/media/video')).toBe(false);
    const play = within(reply).queryByRole('button', { name: /说这句/ });
    if (!ownVoice) {
      expect(play).toBeNull();
      expect(
        within(reply).getByRole('button', { name: '怎么朗读内在声音' }),
      ).toBeVisible();
      return;
    }
    expect(
      within(reply).queryByRole('button', { name: '怎么朗读内在声音' }),
    ).toBeNull();
    await person.click(play!);
    await waitFor(() => expect(called('/api/media/audio')).toBe(true));
    expect(called('/api/media/video')).toBe(false);
  },
);

it('in the persona edition offers no colleague’s answer to try, and says where help is with no word on how it answered', async () => {
  const person = userEvent.setup();
  streamed.push(
    answer({
      reply: '听到你这样说，我很在意你现在的安全。',
      crisis: true,
      mode: 'general',
    }),
  );
  mount(personas, '/chat', { work: false }, 'persona');
  await list();
  await screen.findByText('仅你可见');
  const box = screen.getByRole('textbox', { name: '你说' });
  expect(box).toHaveAttribute('placeholder', '问问我的分身，或说“记一下…”');
  expect(screen.queryByRole('button', { name: '试问' })).toBeNull();
  await person.type(box, '我不想活了');
  await person.click(screen.getByRole('button', { name: '发送' }));
  expect(
    await screen.findByText('听到你这样说，我很在意你现在的安全。'),
  ).toBeVisible();
  expect(screen.queryByText('通用回答')).toBeNull();
  // Where help is, is no answer to say is like one or not.
  expect(screen.queryByRole('group', { name: '像不像我' })).toBeNull();
});

it('in the persona edition lets the person say of an answer whether it is like them, and take it back', async () => {
  const person = userEvent.setup();
  streamed.push(answer({ reply: '我会先把手头的事做完再说。' }));
  mount(personas, '/chat', { work: false }, 'persona');
  await list();
  await screen.findByText('仅你可见');
  await person.type(
    screen.getByRole('textbox', { name: '你说' }),
    '要是同事临时加活，你怎么办',
  );
  await person.click(screen.getByRole('button', { name: '发送' }));
  await screen.findByText('我会先把手头的事做完再说。');
  const marks = await screen.findByRole('group', { name: '像不像我' });
  const unlike = within(marks).getByRole('button', { name: '不像我' });
  await person.click(unlike);
  await waitFor(() => expect(unlike).toHaveAttribute('aria-pressed', 'true'));
  const [rated] = bodyOf('/api/persona/self-ratings', 'PUT') as {
    conversation_id: string;
  }[];
  expect(rated).toMatchObject({
    reply: '我会先把手头的事做完再说。',
    rating: 'unlike',
  });
  expect(rated.conversation_id).toBeTruthy();
  // Pressed again, the mark is taken back.
  await person.click(unlike);
  await waitFor(() => expect(unlike).toHaveAttribute('aria-pressed', 'false'));
  expect(bodyOf('/api/persona/self-ratings', 'PUT')[1]).toMatchObject({
    rating: null,
  });
});

it('opens 照镜子 in a new conversation with the two sides of a memory waiting to be sent', async () => {
  const person = userEvent.setup();
  streamed.push(
    answer({ reply: '你 3 月说想早睡，4 月三次凌晨还在写。你怎么看？' }),
  );
  const draft = '我想看看这两种说法：他说要早睡\n不一致的地方：常常熬夜';
  mount(
    personas,
    { pathname: '/chat', state: { ask: draft, reflection: 'mirror' } },
    { work: false },
    'persona',
  );
  await list();
  await screen.findByText('仅你可见');
  const box = screen.getByRole('textbox', { name: '你说' });
  await waitFor(() => expect(box).toHaveValue(draft));
  expect(
    within(screen.getByRole('radiogroup', { name: '这一轮' })).getByRole(
      'radio',
      { name: '照镜子' },
    ),
  ).toBeChecked();
  await person.click(screen.getByRole('button', { name: '发送' }));
  expect(
    await screen.findByText('你 3 月说想早睡，4 月三次凌晨还在写。你怎么看？'),
  ).toBeVisible();
  expect(bodyOf('/api/persona/chat/stream')[0]).toMatchObject({
    reflection: 'mirror',
    messages: [{ role: 'user', content: draft }],
  });
});

/** 时间切片: the first year anything is known as of, as the life line says. */
function knownSince(since: number | null) {
  // Which years are gone by depends on this one.
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-10-30T10:00:00'));
  const answering = fetcher.getMockImplementation() as (
    url: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation(async (url: string, init?: RequestInit) =>
    url === '/api/persona/life-story'
      ? json({ years: [], undated: [], since })
      : answering(url, init),
  );
}

it('opens a new conversation with the person as they were in a year chosen on the life line, and asks as of its end', async () => {
  const person = userEvent.setup();
  knownSince(2015);
  streamed.push(answer({ reply: '那年我刚辞职。', as_of: '2018-12-31' }));
  mount(
    personas,
    { pathname: '/chat', state: { asOfYear: 2018 } },
    { work: false },
    'persona',
  );
  await list();
  const year = await screen.findByRole('combobox', {
    name: '和哪一年的自己聊',
  });
  await waitFor(() => expect(year).toHaveValue('2018'));
  expect(year).toHaveDisplayValue('2018 年的你');
  // Taken up once, the year is gone from the history entry, so reloading the page does not open another conversation.
  expect(entryState).toBeNull();
  // From the first year anything is known of to last year; this year is the person as they are.
  expect(
    within(year)
      .getAllByRole('option')
      .map((option) => option.textContent),
  ).toEqual([
    '现在的你',
    ...[2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016, 2015].map(
      (y) => `${y} 年的你`,
    ),
  ]);
  await person.type(
    screen.getByRole('textbox', { name: '你说' }),
    '你在忙什么',
  );
  await person.click(screen.getByRole('button', { name: '发送' }));
  const said = (await screen.findByText('那年我刚辞职。')).closest('article')!;
  // 和过去的自己说话 (P3.5): said once, above the answer, who is answering.
  expect(
    within(said).getByText('这是 2018 年的你，只知道那年以前的事'),
  ).toBeVisible();
  expect(bodyOf('/api/persona/chat/stream')[0]).toMatchObject({
    as_of: '2018-12-31',
    messages: [{ role: 'user', content: '你在忙什么' }],
  });
});

it('says once above the person’s own conversation that their pace is reached, and lets them go on', async () => {
  const person = userEvent.setup();
  let reminder: string | null = '今天聊了挺久了，要不要先停一停？';
  const answering = fetcher.getMockImplementation() as (
    url: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === '/api/persona/pace/go-on') reminder = null;
    return url.startsWith('/api/persona/pace')
      ? json({
          pace: { kind: 'daily_minutes', limit: 30 },
          used: null,
          reminder,
        })
      : answering(url, init);
  });
  mount(personas, '/chat', { work: false }, 'persona');
  await list();
  const line = await screen.findByText('今天聊了挺久了，要不要先停一停？');
  await person.click(screen.getByRole('button', { name: '继续聊' }));
  expect(line).not.toBeInTheDocument();
  expect(
    fetcher.mock.calls.some(([url]) => url === '/api/persona/pace/go-on'),
  ).toBe(true);
  // An answer later, it stays away: the day's word was to go on.
  await person.type(screen.getByRole('textbox', { name: '你说' }), '再聊聊');
  await person.click(screen.getByRole('button', { name: '发送' }));
  await screen.findByText('好的。');
  expect(screen.queryByText('今天聊了挺久了，要不要先停一停？')).toBeNull();
});

it('lets the person use the ways of looking at themself with the self of a past year', async () => {
  const person = userEvent.setup();
  knownSince(2015);
  streamed.push(
    answer({
      reply: '你说过：“先说清楚”（2017-05-01）。你会怎么选？',
      as_of: '2018-12-31',
      reflection: 'voice',
    }),
  );
  mount(
    personas,
    { pathname: '/chat', state: { asOfYear: 2018 } },
    { work: false },
    'persona',
  );
  await list();
  const year = await screen.findByRole('combobox', {
    name: '和哪一年的自己聊',
  });
  await waitFor(() => expect(year).toHaveValue('2018'));
  const ways = screen.getByRole('radiogroup', { name: '这一轮' });
  await person.click(within(ways).getByRole('radio', { name: '内在声音' }));
  await person.type(screen.getByRole('textbox', { name: '你说' }), '纠结');
  await person.click(screen.getByRole('button', { name: '发送' }));
  const said = (await screen.findByText(/你会怎么选？/)).closest('article')!;
  expect(
    within(said).getByText('这是 2018 年的你，只知道那年以前的事'),
  ).toBeVisible();
  expect(bodyOf('/api/persona/chat/stream')[0]).toMatchObject({
    as_of: '2018-12-31',
    reflection: 'voice',
  });
});

it('goes on looking back to the year a conversation was had with when it is opened again, until the person chooses now', async () => {
  const person = userEvent.setup();
  knownSince(2019);
  server.rows.get('c-self')!.as_of = '2020-12-31';
  mount(personas, '/chat', { work: false }, 'persona');
  const sheet = await list();
  await person.click(
    await within(sheet).findByRole('button', {
      name: row('我上周答应过谁什么'),
    }),
  );
  const year = await screen.findByRole('combobox', {
    name: '和哪一年的自己聊',
  });
  await waitFor(() => expect(year).toHaveDisplayValue('2020 年的你'));
  const box = screen.getByRole('textbox', { name: '你说' });
  await person.type(box, '还记得吗');
  await person.click(screen.getByRole('button', { name: '发送' }));
  await screen.findByText('好的。');
  expect(bodyOf('/api/persona/chat/stream')[0]).toMatchObject({
    conversation_id: 'c-self',
    as_of: '2020-12-31',
  });
  await person.selectOptions(year, '现在的你');
  await person.type(box, '现在呢');
  await person.click(screen.getByRole('button', { name: '发送' }));
  await waitFor(() =>
    expect(bodyOf('/api/persona/chat/stream')).toHaveLength(2),
  );
  expect(bodyOf('/api/persona/chat/stream')[1]).not.toHaveProperty('as_of');
});

it('offers no year to look back to where nothing of the person is dated', async () => {
  knownSince(null);
  mount(personas, '/chat', { work: false }, 'persona');
  await list();
  await screen.findByText('仅你可见');
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([url]) => url === '/api/persona/life-story'),
    ).toBe(true),
  );
  expect(
    screen.queryByRole('combobox', { name: '和哪一年的自己聊' }),
  ).toBeNull();
});
