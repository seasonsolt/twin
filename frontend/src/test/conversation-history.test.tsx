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
import { dayGroup, relativeTime } from '../features/chat/ConversationHistory';
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
it.each(['desktop', 'tablet', 'mobile'])(
  'lists and resumes history in the stage/sheet, viewport=%s',
  async (viewport) => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn((query: string) => ({
        matches:
          (viewport === 'mobile' && query === '(max-width: 767px)') ||
          (viewport === 'desktop' && query === '(min-width: 1200px)'),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    );
    mount();
    await send();
    const cid = localStorage.getItem(CURRENT_CHAT_KEY)!;
    fireEvent.click(screen.getByRole('button', { name: '新对话' }));
    const panel =
      viewport === 'desktop'
        ? screen.getByRole('region', { name: '和本人的对话' })
        : await history();
    expect(panel).toHaveClass(
      viewport === 'desktop' ? 'stage-history' : 'history-sheet',
    );
    if (viewport === 'desktop') {
      expect(panel.closest('.chat-stage')).not.toBeNull();
      expect(screen.queryByRole('button', { name: '对话记录' })).toBeNull();
      expect(screen.queryByRole('dialog')).toBeNull();
    } else {
      expect(
        screen
          .getByRole('button', { name: '对话记录', hidden: true })
          .closest('.stage-actions'),
      ).not.toBeNull();
      expect(within(panel).queryByText('找到以前的对话，接着聊。')).toBeNull();
      await waitFor(() =>
        expect(
          within(panel).getByRole('button', { name: '关闭' }),
        ).toBeVisible(),
      );
    }
    const entry = await within(panel).findByRole('button', {
      name: /^第一个问题\s/,
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
    const reopened = viewport === 'desktop' ? panel : await history();
    const current = await within(reopened).findByRole('button', {
      name: /^第一个问题\s/,
    });
    expect(current).toHaveAttribute('aria-current', 'true');
    expect(current.closest('li')).toHaveAttribute('data-current', 'true');
    const input = within(reopened).getByRole('searchbox', { name: '搜索对话' });
    fireEvent.change(input, { target: { value: '保存的回答' } });
    await waitFor(() => expect(current).toBeVisible());
    fireEvent.change(input, { target: { value: '不存在' } });
    expect(
      within(reopened).queryByRole('button', { name: /^第一个问题\s/ }),
    ).toBeNull();
    expect(within(reopened).getByText('没有找到匹配的对话')).toBeVisible();
    fireEvent.change(input, { target: { value: '第一个' } });
    expect(
      within(reopened).getByRole('button', { name: /^第一个问题\s/ }),
    ).toBeVisible();
    fireEvent.click(within(reopened).getByRole('button', { name: '新对话' }));
    expect(localStorage.getItem(CURRENT_CHAT_KEY)).toBeNull();
    await waitFor(() =>
      expect(screen.queryAllByRole('article')).toHaveLength(0),
    );
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
    );
    await send('另一段对话');
    expect(server.rows.size).toBe(2);
  },
);
it.each([false, true])(
  'renames and confirms deletion, including the current conversation, desktop=%s',
  async (desktop) => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn((query: string) => ({
        matches: desktop && query === '(min-width: 1200px)',
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    );
    mount();
    await send();
    const panel = desktop
      ? screen.getByRole('region', { name: '和本人的对话' })
      : await history();
    const user = userEvent.setup();
    await user.click(
      await within(panel).findByRole('button', {
        name: '第一个问题的更多操作',
      }),
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
    expect(
      await within(panel).findByText('还没有对话，问他点什么吧'),
    ).toBeVisible();
    await waitFor(() =>
      expect(screen.queryAllByRole('article')).toHaveLength(0),
    );
  },
);
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
  expect(
    within(panel).getByRole('heading', { name: '昨天' }),
  ).toBeInTheDocument();
  expect(within(panel).getByText('更早')).toBeInTheDocument();
  fireEvent.change(within(panel).getByRole('searchbox', { name: '搜索对话' }), {
    target: { value: '预览 0' },
  });
  expect(within(panel).getByText('历史 0')).toBeInTheDocument();
  expect(panel.querySelectorAll('time')).toHaveLength(1);
  fireEvent.change(within(panel).getByRole('searchbox', { name: '搜索对话' }), {
    target: { value: '' },
  });
  expect(panel.querySelectorAll('time')).toHaveLength(50);
  fireEvent.click(within(panel).getByRole('button', { name: '更多对话' }));
  await within(panel).findByText('历史 51');
  expect(panel.querySelectorAll('time')).toHaveLength(52);
  expect(
    within(panel).queryByRole('button', { name: '更多对话' }),
  ).not.toBeInTheDocument();
});
it('shows a fade only while more rows are below the internal scroll position', async () => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: query === '(min-width: 1200px)',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  mount();
  await send();
  const region = screen.getByRole('region', { name: '和本人的对话' });
  const list = region.querySelector('.history-scroll')!;
  const frame = region.querySelector('.history-list-frame')!;
  expect(frame).toHaveAttribute('data-fade', 'false');
  Object.defineProperties(list, {
    scrollHeight: { configurable: true, value: 600 },
    clientHeight: { configurable: true, value: 200 },
  });
  fireEvent.scroll(list, { target: { scrollTop: 0 } });
  expect(frame).toHaveAttribute('data-fade', 'true');
  fireEvent.scroll(list, { target: { scrollTop: 400 } });
  expect(frame).toHaveAttribute('data-fade', 'false');
});

it('supports keyboard overflow actions and restores focus after closing the sheet', async () => {
  mount();
  await send();
  const user = userEvent.setup();
  const trigger = screen.getByRole('button', { name: '对话记录' });
  await user.click(trigger);
  const sheet = await screen.findByRole('dialog', { name: '对话记录' });
  const more = await within(sheet).findByRole('button', {
    name: '第一个问题的更多操作',
  });
  more.focus();
  await user.keyboard('{Enter}');
  expect(within(sheet).getByRole('menuitem', { name: '重命名' })).toHaveFocus();
  await user.keyboard('{ArrowDown}');
  expect(within(sheet).getByRole('menuitem', { name: '删除' })).toHaveFocus();
  await user.keyboard('{Escape}');
  expect(within(sheet).queryByRole('menu')).toBeNull();
  expect(more).toHaveFocus();
  await user.keyboard('{Escape}');
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(trigger).toHaveFocus();
});

it('formats relative times against an injectable local clock across month/year boundaries', () => {
  const now = new Date(2026, 0, 1, 15, 30);
  const today = new Date(2026, 0, 1, 11, 49).toISOString();
  const yesterday = new Date(2025, 11, 31, 23, 59).toISOString();
  const older = new Date(2025, 9, 3, 8, 5).toISOString();
  expect(dayGroup(today, now)).toBe('今天');
  expect(relativeTime(today, now)).toBe('11:49');
  expect(dayGroup(yesterday, now)).toBe('昨天');
  expect(relativeTime(yesterday, now)).toBe('昨天');
  expect(dayGroup(older, now)).toBe('更早');
  expect(relativeTime(older, now)).toBe('10月3日');
  expect(now).toEqual(new Date(2026, 0, 1, 15, 30));
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
