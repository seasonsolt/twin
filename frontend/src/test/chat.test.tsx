import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { readFileSync } from 'node:fs';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router';
import { useReducedMotion } from 'motion/react';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { ConfirmProvider } from '../components/ui';
import { Chat } from '../pages/Chat';
import { useStatus } from '../stores/status';
import { CHAT_KEY, CURRENT_CHAT_KEY } from '../features/chat/useConversation';
import { conversationServer } from './conversationServer';
import { Citations } from '../features/chat/Citations';
import { MessageText } from '../features/chat/MessageText';
import type { ChatReply } from '../features/chat/types';

vi.mock('motion/react', async (original) => {
  const actual = await original<typeof import('motion/react')>();
  const { createElement } = await import('react');
  const cache = new Map();
  return {
    ...actual,
    useReducedMotion: vi.fn(),
    AnimatePresence: ({ children }: { children: import('react').ReactNode }) =>
      children,
    motion: new Proxy(
      {},
      {
        get: (_, tag: string) => {
          if (!cache.has(tag))
            cache.set(tag, (props: Record<string, unknown>) =>
              createElement(
                tag,
                Object.fromEntries(
                  Object.entries(props).filter(
                    ([key]) =>
                      key === 'style' || !actual.isValidMotionProp(key),
                  ),
                ),
              ),
            );
          return cache.get(tag);
        },
      },
    ),
  };
});
const reply: ChatReply = {
  reply: '我会先听大家的意见。',
  confidence: 0.6,
  abstain: true,
  abstain_reason: '证据不足',
  citations: ['p1'],
  retrieved_ids: ['p1'],
  as_of: '2025-01-01',
  cited: [
    {
      id: 'p1',
      kind: 'expression',
      text: '先听听',
      date: '2024-01-01',
      channel: '访谈',
    },
  ],
};
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
let fetchMock: ReturnType<typeof vi.fn>;
let conversations: ReturnType<typeof conversationServer>;
let fail = false;
let streamController: ReadableStreamDefaultController<Uint8Array>;
const encode = (event: string, data: unknown) =>
  new TextEncoder().encode(
    `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`,
  );
const streamReply = (answer: ChatReply) =>
  new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(encode('delta', { text: answer.reply }));
        controller.enqueue(encode('final', answer));
        controller.close();
      },
    }),
    { headers: { 'Content-Type': 'text/event-stream' } },
  );
beforeEach(async () => {
  vi.mocked(useReducedMotion).mockReturnValue(true);
  sessionStorage.clear();
  localStorage.clear();
  conversations = conversationServer();
  fail = false;
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const history = conversations.respond(url, init);
    if (history) return history;
    if (url === '/api/status')
      return json({
        target_name: '测试人',
        counts: { sources: 0, items: 0 },
      });
    if (url === '/api/persona/state') return json({ stale: true });
    if (url === '/api/media/capabilities')
      return json({
        available: true,
        backend: null,
        video: { available: true },
      });
    if (url === '/api/persona/chat/stream') {
      if (fail) {
        fail = false;
        return json({ detail: '还没有人格档案，请先构建' }, 400);
      }
      return new Response(
        new ReadableStream<Uint8Array>({
          start(controller) {
            streamController = controller;
          },
        }),
        { headers: { 'Content-Type': 'text/event-stream' } },
      );
    }
    if (url === '/api/media/video') return json({ job_id: 'v1' });
    if (url === '/api/media/video/jobs/v1') return json({ status: 'running' });
    throw new Error(`Unexpected API: ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  await useStatus.getState().refresh();
});
afterEach(() => vi.useRealTimers());
function Navigation() {
  const navigate = useNavigate();
  return <button onClick={() => navigate('/sources')}>切换路由</button>;
}
function mount() {
  return render(
    <ConfirmProvider>
      <MemoryRouter initialEntries={['/chat']}>
        <Navigation />
        <Routes>
          <Route path="/chat" element={<Chat />} />
          <Route path="/sources" element={<p>其他页面</p>} />
        </Routes>
      </MemoryRouter>
    </ConfirmProvider>,
  );
}
async function submit() {
  fireEvent.change(screen.getByLabelText('你说'), {
    target: { value: '你怎么看？' },
  });
  await act(async () => {
    fireEvent.keyDown(screen.getByLabelText('你说'), { key: 'Enter' });
  });
}
it('links empty chat to memories and accepts a friendly no-profile reply without polling', async () => {
  const original = fetchMock.getMockImplementation()! as (
    url: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetchMock.mockImplementation((url: string, init?: RequestInit) =>
    url === '/api/persona/chat/stream'
      ? Promise.resolve(
          streamReply({
            ...reply,
            reply: '记忆还在处理中，等我记住后再聊吧。',
            abstain_reason: '记忆还在处理中，等我记住后再聊吧。',
            citations: [],
            cited: [],
          }),
        )
      : original(url, init),
  );
  mount();
  expect(screen.getByRole('link', { name: '添加记忆' })).toHaveAttribute(
    'href',
    '#/profile?section=memories',
  );
  await submit();
  expect(
    await screen.findByRole('article', { name: '分身回复' }),
  ).toHaveTextContent('记忆还在处理中');
  expect(
    fetchMock.mock.calls.some(([url]) => url.startsWith('/api/jobs/')),
  ).toBe(false);
  expect(sessionStorage.getItem(CHAT_KEY)).toBeNull();
  expect(localStorage.getItem(CURRENT_CHAT_KEY)).toBeTruthy();
});

it('fills and focuses the composer from each starter without sending', async () => {
  mount();
  expect(screen.getByRole('heading', { name: '和测试人聊聊' })).toBeVisible();
  const user = userEvent.setup();
  for (const starter of [
    '你最近在忙什么？',
    '你周末一般怎么过？',
    '遇到难事你会怎么做？',
  ]) {
    await user.click(screen.getByRole('button', { name: starter }));
    expect(screen.getByRole('textbox', { name: '你说' })).toHaveValue(starter);
    expect(screen.getByRole('textbox', { name: '你说' })).toHaveFocus();
  }
  expect(
    fetchMock.mock.calls.some(([url]) => url === '/api/persona/chat/stream'),
  ).toBe(false);
});

it('streams progressively, hides thinking on the first delta, then replaces text and persists metadata', async () => {
  mount();
  await submit();
  expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();
  expect(screen.getByText(/新添加的记忆正在处理中/)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: '查看记忆' })).toHaveAttribute(
    'href',
    '#/profile?section=memories',
  );
  expect(sessionStorage.getItem(CHAT_KEY)).toBeNull();
  const init = fetchMock.mock.calls.find(
    ([url]) => url === '/api/persona/chat/stream',
  )![1] as RequestInit;
  expect(JSON.parse(init.body as string)).toEqual({
    conversation_id: localStorage.getItem(CURRENT_CHAT_KEY),
    messages: [{ role: 'user', content: '你怎么看？' }],
  });
  expect(new Headers(init.headers).get('X-Twin')).toBe('1');
  expect(
    screen
      .getAllByRole('status')
      .some((node) => node.textContent?.includes('思考中…')),
  ).toBe(true);
  await act(async () =>
    streamController.enqueue(encode('delta', { text: '先听' })),
  );
  expect(screen.getByLabelText('分身回复')).toHaveTextContent('先听');
  expect(screen.queryByText('思考中…')).not.toBeInTheDocument();
  await act(async () =>
    streamController.enqueue(encode('delta', { text: '大家' })),
  );
  expect(screen.getByLabelText('分身回复')).toHaveTextContent('先听大家');
  expect(sessionStorage.getItem(CHAT_KEY)).toBeNull();
  await act(async () => {
    streamController.enqueue(encode('final', reply));
    streamController.close();
  });
  const abstention = screen.getByLabelText('分身回复');
  expect(abstention).toHaveTextContent(reply.reply);
  expect(abstention.querySelector('.twin-bubble')).not.toBeNull();
  expect(abstention).not.toHaveClass('text-secondary');
  expect(
    within(abstention).getByRole('button', { name: '让测试人说这句' }),
  ).toBeVisible();
  expect(
    within(abstention).getByRole('button', { name: '依据 1' }),
  ).toBeVisible();
  expect(
    screen.queryByText(/置信度|需要本人确认|通用回答/),
  ).not.toBeInTheDocument();
  expect(screen.queryByText(/资料截至/)).not.toBeInTheDocument();
  expect(document.querySelector('input[type="date"]')).toBeNull();
  expect(
    screen.queryByRole('button', { name: /语音|视频/ }),
  ).not.toBeInTheDocument();
  expect(sessionStorage.getItem(CHAT_KEY)).toBeNull();
  expect(conversations.rows.has(localStorage.getItem(CURRENT_CHAT_KEY)!)).toBe(
    true,
  );
});
it('replaces draft text with guarded final text, attaches citations and starts voice only on final', async () => {
  const original = fetchMock.getMockImplementation()! as (
    url: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetchMock.mockImplementation((url: string, init: RequestInit) =>
    url === '/api/media/audio'
      ? new Promise<Response>(() => {})
      : original(url, init),
  );
  mount();
  await submit();
  await act(async () =>
    streamController.enqueue(encode('delta', { text: '不正确的初稿' })),
  );
  expect(screen.getByLabelText('分身回复')).toHaveTextContent('不正确的初稿');
  expect(fetchMock.mock.calls.some(([url]) => url === '/api/media/audio')).toBe(
    false,
  );
  const final = {
    ...reply,
    reply: '修正后的回复',
    abstain: false,
    abstain_reason: '',
    mode: 'grounded',
  };
  await act(async () => {
    streamController.enqueue(encode('final', final));
    streamController.close();
  });
  expect(screen.getByLabelText('分身回复')).toHaveTextContent('修正后的回复');
  expect(screen.queryByText('不正确的初稿')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '依据 1' })).toBeInTheDocument();
  expect(sessionStorage.getItem(CHAT_KEY)).toBeNull();
  expect(localStorage.getItem(CURRENT_CHAT_KEY)).toBeTruthy();
  expect(
    fetchMock.mock.calls.filter(([url]) => url === '/api/media/audio'),
  ).toHaveLength(1);
});

it('marks an inferred reply with a neutral badge and no confidence', async () => {
  sessionStorage.setItem(
    CHAT_KEY,
    JSON.stringify([
      {
        id: 'inferred',
        role: 'twin',
        content: '我没直接说过，但按我的习惯，大概会选 B。',
        reply: {
          ...reply,
          mode: 'inferred',
          abstain: false,
          abstain_reason: '',
          confidence: 0.5,
        },
        timestamp: '2025-01-01T12:00:00Z',
      },
    ]),
  );
  mount();
  expect(screen.getByLabelText('分身回复')).toHaveTextContent(
    '我没直接说过，但按我的习惯，大概会选 B。',
  );
  expect(screen.getByText('推测 · 非本人表达')).toBeVisible();
  expect(
    screen.queryByText(/通用回答|置信度|需要本人确认/),
  ).not.toBeInTheDocument();
});

it('renders general reply text without mode or confidence badges', async () => {
  sessionStorage.setItem(
    CHAT_KEY,
    JSON.stringify([
      {
        id: 'general',
        role: 'twin',
        content: '这不是我本人的经验，一般来说先做预算。',
        reply: {
          ...reply,
          mode: 'general',
          abstain: false,
          abstain_reason: '',
          confidence: 0.5,
        },
        timestamp: '2025-01-01T12:00:00Z',
      },
    ]),
  );
  mount();
  expect(screen.getByLabelText('分身回复')).toHaveTextContent(
    '这不是我本人的经验，一般来说先做预算。',
  );
  expect(
    screen.queryByText(/通用回答|置信度|需要本人确认/),
  ).not.toBeInTheDocument();
  expect(document.querySelector('time')).toBeNull();
  expect(
    await screen.findByRole('button', { name: '让测试人说这句' }),
  ).toBeVisible();
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: '让测试人说这句' }),
    ).toHaveAttribute('data-generating', 'true'),
  );
  expect(
    screen.queryByRole('button', { name: '生成视频' }),
  ).not.toBeInTheDocument();
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.filter(([url]) => url === '/api/media/video'),
    ).toHaveLength(1),
  );
});
it('shows Chinese detail and retries without duplicating the failed user turn', async () => {
  fail = true;
  mount();
  await submit();
  await waitFor(() =>
    expect(
      screen.queryByLabelText('你说', { selector: 'article' }),
    ).not.toBeInTheDocument(),
  );
  vi.useFakeTimers();
  expect(screen.getByRole('alert')).toHaveTextContent(
    '还没有人格档案，请先构建',
  );
  expect(screen.getByLabelText('你说', { selector: 'textarea' })).toHaveValue(
    '你怎么看？',
  );
  expect(
    screen.queryByLabelText('你说', { selector: 'article' }),
  ).not.toBeInTheDocument();
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
  });
  await act(async () => {
    streamController.enqueue(encode('final', reply));
    streamController.close();
  });
  expect(screen.getByLabelText('分身回复')).toHaveTextContent(reply.reply);
  expect(
    screen.getAllByLabelText('你说', { selector: 'article' }),
  ).toHaveLength(1);
  expect(
    fetchMock.mock.calls.filter(([url]) => url === '/api/persona/chat/stream'),
  ).toHaveLength(2);
});
it('does not send on composition, keyCode 229, or Shift+Enter', async () => {
  mount();
  const input = screen.getByLabelText('你说');
  fireEvent.change(input, { target: { value: '输入法测试' } });
  fireEvent.compositionStart(input);
  fireEvent.keyDown(input, { key: 'Enter' });
  fireEvent.compositionEnd(input);
  fireEvent.keyDown(input, { key: 'Enter', isComposing: true });
  fireEvent.keyDown(input, { key: 'Enter', keyCode: 229 });
  fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
  expect(
    fetchMock.mock.calls.some(([url]) => url === '/api/persona/chat/stream'),
  ).toBe(false);
});
it('restores static history and clears immediately without confirmation', async () => {
  sessionStorage.setItem(
    CHAT_KEY,
    JSON.stringify([
      {
        id: 'old',
        role: 'twin',
        content: reply.reply,
        reply,
        timestamp: '2025-01-01T12:00:00Z',
      },
    ]),
  );
  const { container } = mount();
  const user = userEvent.setup();
  expect(container.querySelector('.blur-text')).toBeNull();
  await user.click(screen.getByRole('button', { name: '新对话' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  await waitFor(() =>
    expect(screen.queryByLabelText('分身回复')).not.toBeInTheDocument(),
  );
  expect(sessionStorage.getItem(CHAT_KEY)).toBeNull();
});
it('aborts streaming on route change and unmount without polling', async () => {
  const rendered = mount();
  await submit();
  const signal = fetchMock.mock.calls.find(
    ([url]) => url === '/api/persona/chat/stream',
  )![1].signal;
  await act(async () =>
    fireEvent.click(screen.getByRole('button', { name: '切换路由' })),
  );
  expect(signal.aborted).toBe(true);
  expect(
    fetchMock.mock.calls.some(([url]) => url.startsWith('/api/jobs/')),
  ).toBe(false);
  rendered.unmount();
  const second = mount();
  await submit();
  const secondSignal = fetchMock.mock.calls
    .filter(([url]) => url === '/api/persona/chat/stream')
    .at(-1)![1].signal;
  second.unmount();
  expect(secondSignal.aborted).toBe(true);
});
it('renders stream failure inline with retry', async () => {
  mount();
  await submit();
  await act(async () => {
    streamController.enqueue(encode('delta', { text: '部分回复' }));
    streamController.enqueue(encode('error', { detail: '模型暂时不可用' }));
    streamController.close();
  });
  expect(screen.getByRole('alert')).toHaveTextContent('模型暂时不可用');
  expect(screen.queryByLabelText('分身回复')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '重试' })).toBeEnabled();
});
it('uses page scrolling, a fixed one-line composer and mobile-safe font sizes', () => {
  const view = mount();
  const messages = screen.getByTestId('chat-messages');
  expect(messages.className).not.toMatch(/overflow-y|(?:max-)?h-\[/);
  for (
    let parent = messages.parentElement;
    parent;
    parent = parent.parentElement
  ) {
    expect(parent.className).not.toMatch(/overflow-y-(auto|scroll)/);
  }
  expect(screen.getByRole('form', { name: '消息输入' })).toHaveClass(
    'fixed',
    'chat-composer',
  );
  const input = screen.getByRole('textbox', { name: '你说' });
  expect(input).toHaveAttribute('rows', '1');
  expect(input).toHaveClass('text-md');
  expect(input).not.toHaveClass('md:text-base');
  expect(view.container.querySelector('time')).toBeNull();
  const css = readFileSync('src/design/tokens.css', 'utf8');
  expect(css).toContain('font-size: 16px !important');
  expect(css).toContain('env(safe-area-inset-bottom');
  expect(css).toContain('-webkit-tap-highlight-color: transparent');
});
it('shares a bounded 760px desktop grid between conversation and composer', () => {
  const view = mount();
  expect(
    view.container.querySelector(
      '.chat-scroll > .chat-column-grid .chat-conversation',
    ),
  ).not.toBeNull();
  expect(screen.getByRole('form', { name: '消息输入' })).toHaveClass(
    'chat-column-grid',
  );
  const css = readFileSync('src/design/tokens.css', 'utf8');
  expect(css).toMatch(/\.chat-column-grid\s*\{\s*display: grid;/);
  expect(css).toContain('clamp(32px, calc((100% - 760px) / 2), 96px)');
  expect(css).toContain('minmax(0, 760px) minmax(32px, 1fr)');
  expect(css).toMatch(/\.stage-decorations\s*\{[^}]*overflow: hidden;/);
  expect(readFileSync('src/features/chat/history.css', 'utf8')).toMatch(
    /\.stage-history\s*\{[^}]*background: var\(--accent\);/,
  );
});
it('caps composer growth at five lines', () => {
  mount();
  const input = screen.getByRole('textbox', { name: '你说' });
  Object.defineProperty(input, 'scrollHeight', {
    configurable: true,
    value: 600,
  });
  fireEvent.change(input, {
    target: { value: 'one\ntwo\nthree\nfour\nfive\nsix' },
  });
  const style = getComputedStyle(input);
  const line = parseFloat(style.lineHeight) || 24;
  const padding =
    (parseFloat(style.paddingTop) || 0) +
    (parseFloat(style.paddingBottom) || 0);
  expect(parseFloat(input.style.height)).toBe(line * 5 + padding + 2);
});
it('moves the composer above the visual viewport keyboard and cleans up on leaving', () => {
  vi.stubGlobal('innerHeight', 800);
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  const viewport = Object.assign(new EventTarget(), {
    height: 800,
    offsetTop: 0,
  });
  vi.stubGlobal('visualViewport', viewport);
  const view = mount();
  const input = screen.getByRole('textbox', { name: '你说' });
  act(() => input.focus());
  viewport.height = 460;
  act(() => viewport.dispatchEvent(new Event('resize')));
  expect(document.documentElement).toHaveAttribute('data-keyboard', 'true');
  expect(
    document.documentElement.style.getPropertyValue('--keyboard-inset'),
  ).toBe('340px');
  viewport.height = 800;
  act(() => viewport.dispatchEvent(new Event('resize')));
  expect(document.documentElement).toHaveAttribute('data-keyboard', 'false');
  view.unmount();
  expect(document.documentElement).not.toHaveAttribute('data-keyboard');
  expect(
    document.documentElement.style.getPropertyValue('--keyboard-inset'),
  ).toBe('');
});
it('scrolls to the newest message on both send and receive', async () => {
  vi.useFakeTimers();
  const scroll = vi.fn();
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: scroll,
  });
  mount();
  const initial = scroll.mock.calls.length;
  await submit();
  expect(scroll.mock.calls.length).toBeGreaterThan(initial);
  const sent = scroll.mock.calls.length;
  await act(async () => {
    streamController.enqueue(encode('final', reply));
    streamController.close();
  });
  expect(scroll.mock.calls.length).toBeGreaterThan(sent);
  delete (HTMLElement.prototype as Partial<HTMLElement>).scrollIntoView;
});
it('keeps user messages plain and applies strict CJK typography', () => {
  const view = render(
    <MessageText
      plain
      text={
        '开头，标点正常。\r\n第二段。\n\n1. <img src=x onerror=alert(1)>\n2. &lt;script&gt;\n\n- <script>alert(1)</script>\n- 一个项目\n\n第一步：先听。\n第二步：再做。\n结尾。'
      }
    />,
  );
  expect(view.container.querySelector('p, ol, ul, img, script')).toBeNull();
  expect(view.container.textContent).toContain('<img src=x onerror=alert(1)>');
  expect(view.container.textContent).toContain('&lt;script&gt;');
  expect(view.container.firstElementChild).toHaveClass('message-plain');
  const rule = readFileSync('src/design/tokens.css', 'utf8').match(
    /\.message-text\s*\{[^}]*\}/,
  )![0];
  const style = document.createElement('style');
  style.textContent = rule;
  document.head.append(style);
  try {
    const computed = getComputedStyle(view.container.firstElementChild!);
    expect(computed.lineBreak).toBe('strict');
    expect(computed.wordBreak).toBe('normal');
    expect(computed.overflowWrap).toBe('break-word');
    expect(computed.fontSize).toBe('16px');
    expect(computed.lineHeight).toBe('1.75');
  } finally {
    style.remove();
  }
});

it.each([true, false])(
  'keeps reply actions outside the bubble on mobile: %s',
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
    sessionStorage.setItem(
      CHAT_KEY,
      JSON.stringify([
        {
          id: 'structured',
          role: 'twin',
          content: '第一段。\n\n第二段。',
          reply: {
            ...reply,
            abstain: false,
            mode: 'grounded',
            abstain_reason: '',
          },
          timestamp: '2025-01-01T12:00:00Z',
        },
      ]),
    );
    const view = mount();
    const article = screen.getByRole('article', { name: '分身回复' });
    const bubble = article.querySelector('.twin-bubble')!;
    const row = screen.getByRole('group', { name: '回复媒体' });
    const play = await screen.findByRole('button', { name: '让测试人说这句' });
    const citations = screen.getByRole('button', { name: '依据 1' });
    expect(bubble.querySelector('button')).toBeNull();
    expect(row.parentElement).toBe(article);
    expect(row).toContainElement(play);
    expect(row).toContainElement(citations);
    expect(row).toHaveClass('flex', 'justify-end', 'items-center');
    expect(play).toHaveClass('min-h-11', 'min-w-11');
    expect(citations.querySelector('span')).toHaveClass(
      'border',
      'rounded-full',
    );
    expect(bubble.querySelectorAll('p')).toHaveLength(2);
    expect(view.container.querySelector('.chat-conversation')).toHaveClass(
      'flex',
      'flex-col',
      'justify-end',
    );
    await userEvent.setup().click(citations);
    expect(screen.getByRole('list', { name: '回答依据' })).toBeVisible();
  },
);

it('citation disclosure expands and collapses using keyboard and shows both citation kinds', async () => {
  render(
    <Citations
      cited={[
        ...reply.cited!,
        { id: 'i1', kind: 'item', facet: '价值观', text: '档案内容' },
      ]}
    />,
  );
  const user = userEvent.setup();
  const disclosure = screen.getByRole('button', { name: '依据 2' });
  expect(disclosure).toHaveAttribute('aria-expanded', 'false');
  await user.tab();
  await user.keyboard('{Enter}');
  expect(disclosure).toHaveAttribute('aria-expanded', 'true');
  expect(screen.getByRole('list', { name: '回答依据' })).toHaveAttribute(
    'aria-label',
    '回答依据',
  );
  await waitFor(() =>
    expect(screen.getByText('2024-01-01 · 访谈')).toBeVisible(),
  );
  expect(screen.getByText('价值观')).toBeVisible();
  await user.keyboard(' ');
  expect(disclosure).toHaveAttribute('aria-expanded', 'false');
  await waitFor(() =>
    expect(screen.queryByRole('list')).not.toBeInTheDocument(),
  );
});
