import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StrictMode } from 'react';
import { MemoryRouter } from 'react-router';
import { beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider } from '../components/ui';
import { Chat } from '../pages/Chat';
import { CHAT_KEY, CURRENT_CHAT_KEY } from '../features/chat/useConversation';
import { setPersonaId } from '../lib/persona';
import { useStatus } from '../stores/status';
import { conversationServer } from './conversationServer';

const reply = {
  reply: '保存的回答',
  citations: ['p1'],
  cited: [
    { id: 'p1', kind: 'item' as const, text: '保存的依据', facet: '价值观' },
  ],
  confidence: 0.6,
  abstain: false,
  abstain_reason: '',
  mode: 'grounded' as const,
  retrieved_ids: [],
};
const legacy = [
  {
    id: 'u',
    role: 'user',
    content: '以前的问题',
    timestamp: '2025-01-01T12:00:00Z',
  },
  {
    id: 't',
    role: 'twin',
    content: reply.reply,
    reply,
    timestamp: '2025-01-01T12:01:00Z',
  },
];
let server: ReturnType<typeof conversationServer>;
let fetcher: ReturnType<typeof vi.fn>;
beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  setPersonaId('default');
  server = conversationServer();
  useStatus.setState({ data: null, error: null });
  fetcher = vi.fn(async (path: string, init?: RequestInit) => {
    const history = server.respond(path, init);
    if (history) return history;
    if (path === '/api/persona/chat/stream') {
      server.append(init!, reply);
      return new Response(`event: final\ndata: ${JSON.stringify(reply)}\n\n`, {
        headers: { 'Content-Type': 'text/event-stream' },
      });
    }
    const data =
      path === '/api/media/capabilities'
        ? { available: false, video: { available: false } }
        : { stale: false };
    return new Response(JSON.stringify(data));
  });
  vi.stubGlobal('fetch', fetcher);
});
function mount(strict = false) {
  const page = (
    <ConfirmProvider>
      <MemoryRouter initialEntries={['/chat']}>
        <Chat />
      </MemoryRouter>
    </ConfirmProvider>
  );
  return render(strict ? <StrictMode>{page}</StrictMode> : page);
}
async function send(text = '第一个问题') {
  fireEvent.change(screen.getByRole('textbox', { name: '你说' }), {
    target: { value: text },
  });
  await act(async () =>
    fireEvent.click(screen.getByRole('button', { name: '发送' })),
  );
  await screen.findAllByText(reply.reply);
}
async function history() {
  fireEvent.click(screen.getAllByRole('button', { name: '对话记录' })[0]);
  return screen.findByRole('dialog', { name: '对话记录' });
}
it('creates on first send, sends the id, starts fresh without deleting, and reopens after reload', async () => {
  const view = mount();
  expect(server.rows.size).toBe(0);
  await send();
  const cid = localStorage.getItem(CURRENT_CHAT_KEY)!;
  expect(server.rows.has(cid)).toBe(true);
  const stream = fetcher.mock.calls.find(
    ([path]) => path === '/api/persona/chat/stream',
  )![1];
  expect(JSON.parse(stream.body as string).conversation_id).toBe(cid);
  expect(sessionStorage.getItem(CHAT_KEY)).toBeNull();
  view.unmount();
  const reloaded = mount();
  await waitFor(() => expect(screen.getByText(reply.reply)).toBeVisible());
  expect(screen.getByRole('button', { name: '让本人说这句' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: '依据 1' }));
  expect(await screen.findByText('保存的依据')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: '新对话' }));
  expect(localStorage.getItem(CURRENT_CHAT_KEY)).toBeNull();
  expect(server.rows.size).toBe(1);
  await waitFor(() => expect(screen.queryAllByRole('article')).toHaveLength(0));
  await send('第二个问题');
  expect(server.rows.size).toBe(2);
  expect(localStorage.getItem(CURRENT_CHAT_KEY)).not.toBe(cid);
  reloaded.unmount();
});
it.each([false, true])(
  'lists and resumes history in the panel/sheet, mobile=%s',
  async (mobile) => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn((query: string) => ({
        matches: mobile
          ? query === '(max-width: 767px)'
          : query === '(min-width: 1200px)',
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    );
    mount();
    await send();
    const cid = localStorage.getItem(CURRENT_CHAT_KEY)!;
    fireEvent.click(screen.getByRole('button', { name: '新对话' }));
    const panel = await history();
    expect(panel).toHaveClass(mobile ? 'history-sheet' : 'history-panel');
    const entry = await within(panel).findByRole('button', {
      name: /第一个问题.*保存的回答/,
    });
    await waitFor(() => expect(within(panel).getByText('今天')).toBeVisible());
    await userEvent.setup().click(entry);
    await waitFor(() =>
      expect(localStorage.getItem(CURRENT_CHAT_KEY)).toBe(cid),
    );
    expect(
      await screen.findByRole('article', { name: '分身回复' }),
    ).toHaveTextContent(reply.reply);
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
    );
    await send('继续聊');
    expect(server.rows.get(cid)!.turns).toHaveLength(4);
    const reopened = await history();
    expect(
      await within(reopened).findByRole('button', {
        name: /第一个问题.*保存的回答/,
      }),
    ).toHaveAttribute('aria-current', 'true');
  },
);
it('renames and confirms deletion, including the current conversation', async () => {
  mount();
  await send();
  const panel = await history();
  const user = userEvent.setup();
  await user.click(
    await within(panel).findByRole('button', { name: '第一个问题的更多操作' }),
  );
  await user.click(within(panel).getByRole('menuitem', { name: '重命名' }));
  const input = within(panel).getByRole('textbox', { name: '对话标题' });
  await user.clear(input);
  await user.type(input, '改名后的对话');
  await user.click(within(panel).getByRole('button', { name: '保存' }));
  expect(
    await within(panel).findByRole('button', {
      name: '改名后的对话的更多操作',
    }),
  ).toBeVisible();
  expect([...server.rows.values()][0].title).toBe('改名后的对话');
  await user.click(
    within(panel).getByRole('button', { name: '改名后的对话的更多操作' }),
  );
  await user.click(within(panel).getByRole('menuitem', { name: '删除' }));
  const confirm = await screen.findByRole('dialog', { name: '删除对话？' });
  expect(server.rows.size).toBe(1);
  await user.click(within(confirm).getByRole('button', { name: '删除' }));
  await waitFor(() => expect(server.rows.size).toBe(0));
  expect(localStorage.getItem(CURRENT_CHAT_KEY)).toBeNull();
  expect(await within(panel).findByText('还没有对话记录')).toBeVisible();
  await waitFor(() => expect(screen.queryAllByRole('article')).toHaveLength(0));
});
it('groups by local day and pages through older conversations', async () => {
  for (let index = 0; index < 52; index++) {
    const date = new Date();
    date.setDate(date.getDate() - index);
    const timestamp = date.toISOString();
    const id = `saved-${index}`;
    server.rows.set(id, {
      id,
      title: `历史 ${index}`,
      updated_at: timestamp,
      persona: 'default',
      turns: [
        { id: `${id}:1`, role: 'user', content: `预览 ${index}`, timestamp },
      ],
    });
  }
  mount();
  const panel = await history();
  await within(panel).findByText('今天');
  expect(within(panel).getByText('昨天')).toBeInTheDocument();
  expect(within(panel).getByText('更早')).toBeInTheDocument();
  expect(within(panel).getByText('预览 0')).toBeInTheDocument();
  expect(panel.querySelectorAll('time')).toHaveLength(50);
  fireEvent.click(within(panel).getByRole('button', { name: '更多对话' }));
  await within(panel).findByText('历史 51');
  expect(panel.querySelectorAll('time')).toHaveLength(52);
  expect(
    within(panel).queryByRole('button', { name: '更多对话' }),
  ).not.toBeInTheDocument();
});
it('imports legacy turns once in StrictMode and preserves reply metadata', async () => {
  sessionStorage.setItem(CHAT_KEY, JSON.stringify(legacy));
  mount(true);
  await waitFor(() => expect(sessionStorage.getItem(CHAT_KEY)).toBeNull());
  const cid = localStorage.getItem(CURRENT_CHAT_KEY)!;
  await waitFor(() =>
    expect(localStorage.getItem(CURRENT_CHAT_KEY)).toBeTruthy(),
  );
  expect(server.rows.size).toBe(1);
  expect([...server.rows.values()][0].turns[1].reply).toEqual(reply);
  expect(
    fetcher.mock.calls.filter(
      ([path, init]) => path === '/api/conversations' && init.method === 'POST',
    ),
  ).toHaveLength(1);
  expect(server.rows.has(cid)).toBe(true);
  await send('导入后继续');
  expect(server.rows.get(cid)!.turns).toHaveLength(4);
});
it('keeps the old copy when migration fails and forgets a deleted saved id', async () => {
  sessionStorage.setItem(CHAT_KEY, JSON.stringify(legacy));
  const original = fetcher.getMockImplementation()! as (
    path: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation(async (path: string, init?: RequestInit) =>
    path === '/api/conversations' && init?.method === 'POST'
      ? new Response(JSON.stringify({ detail: '暂时不可用' }), { status: 503 })
      : original(path, init),
  );
  const view = mount();
  expect(await screen.findByRole('alert')).toHaveTextContent('暂时不可用');
  expect(sessionStorage.getItem(CHAT_KEY)).not.toBeNull();
  fetcher.mockImplementation(original);
  fireEvent.click(screen.getByRole('button', { name: '重试' }));
  await waitFor(() =>
    expect(localStorage.getItem(CURRENT_CHAT_KEY)).toBeTruthy(),
  );
  expect(sessionStorage.getItem(CHAT_KEY)).toBeNull();
  expect(server.rows.size).toBe(1);
  view.unmount();
  sessionStorage.clear();
  localStorage.setItem(CURRENT_CHAT_KEY, 'deleted');
  mount();
  await waitFor(() =>
    expect(localStorage.getItem(CURRENT_CHAT_KEY)).toBeNull(),
  );
  expect(screen.queryByRole('article')).not.toBeInTheDocument();
});
