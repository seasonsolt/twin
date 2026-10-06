import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { readFileSync } from 'node:fs';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router';
import { useReducedMotion } from 'motion/react';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { ConfirmProvider } from '../components/ui';
import { Chat } from '../pages/Chat';
import { useStatus } from '../stores/status';
import { CHAT_KEY } from '../features/chat/useConversation';
import { Citations } from '../features/chat/Citations';
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
let fail = false;
let jobStatus = 'done';
beforeEach(async () => {
  vi.mocked(useReducedMotion).mockReturnValue(true);
  sessionStorage.clear();
  fail = false;
  jobStatus = 'done';
  fetchMock = vi.fn(async (url: string) => {
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
    if (url === '/api/persona/chat') {
      if (fail) {
        fail = false;
        return json({ detail: '还没有人格档案，请先构建' }, 400);
      }
      return json({ job_id: 'j/1' }, 202);
    }
    if (url === '/api/media/video') return json({ job_id: 'v1' });
    if (url === '/api/media/video/jobs/v1') return json({ status: 'running' });
    if (url === '/api/jobs/j%2F1')
      return json({ status: jobStatus, result: reply });
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
  ) => Promise<Response>;
  fetchMock.mockImplementation((url: string) =>
    url === '/api/persona/chat'
      ? Promise.resolve(
          json({
            ...reply,
            reply: '记忆还在处理中，等我记住后再聊吧。',
            abstain_reason: '记忆还在处理中，等我记住后再聊吧。',
            citations: [],
            cited: [],
          }),
        )
      : original(url),
  );
  mount();
  expect(screen.getByRole('link', { name: '添加记忆' })).toHaveAttribute(
    'href',
    '#/memories',
  );
  await submit();
  expect(
    await screen.findByRole('article', { name: '分身回复' }),
  ).toHaveTextContent('记忆还在处理中');
  expect(
    fetchMock.mock.calls.some(([url]) => url.startsWith('/api/jobs/')),
  ).toBe(false);
  expect(sessionStorage.getItem(CHAT_KEY)).toContain('记忆还在处理中');
});

it('sends, polls queued/running jobs, renders only the abstention reason and persists complete turns', async () => {
  vi.useFakeTimers();
  mount();
  await submit();
  expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();
  expect(screen.getByText(/新添加的记忆正在处理中/)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: '查看记忆' })).toHaveAttribute(
    'href',
    '#/memories',
  );
  expect(sessionStorage.getItem(CHAT_KEY)).toBeNull();
  const init = fetchMock.mock.calls.find(
    ([url]) => url === '/api/persona/chat',
  )![1] as RequestInit;
  expect(JSON.parse(init.body as string)).toEqual({
    messages: [{ role: 'user', content: '你怎么看？' }],
  });
  expect(new Headers(init.headers).get('X-Twin')).toBe('1');
  jobStatus = 'running';
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(
    screen
      .getAllByRole('status')
      .some((node) => node.textContent?.includes('思考中…')),
  ).toBe(true);
  jobStatus = 'done';
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  const abstention = screen.getByLabelText('分身回复');
  expect(abstention).toHaveTextContent(/^证据不足$/);
  expect(abstention.children).toHaveLength(1);
  expect(abstention).toHaveClass('text-secondary');
  expect(abstention.querySelector('time, button, img')).toBeNull();
  expect(
    screen.queryByText(/置信度|需要本人确认|通用回答/),
  ).not.toBeInTheDocument();
  expect(screen.queryByText(/资料截至/)).not.toBeInTheDocument();
  expect(document.querySelector('input[type="date"]')).toBeNull();
  expect(
    screen.queryByRole('button', { name: /语音|视频/ }),
  ).not.toBeInTheDocument();
  expect(
    JSON.parse(sessionStorage.getItem(CHAT_KEY)!).map(
      (turn: { role: string }) => turn.role,
    ),
  ).toEqual(['user', 'twin']);
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
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(screen.getByLabelText('分身回复')).toHaveTextContent(
    reply.abstain_reason,
  );
  expect(
    screen.getAllByLabelText('你说', { selector: 'article' }),
  ).toHaveLength(1);
  expect(
    fetchMock.mock.calls.filter(([url]) => url === '/api/persona/chat'),
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
    fetchMock.mock.calls.some(([url]) => url === '/api/persona/chat'),
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
it('stops polling on route change and aborts an in-flight poll on unmount', async () => {
  vi.useFakeTimers();
  jobStatus = 'running';
  const rendered = mount();
  await submit();
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '切换路由' }));
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });
  expect(
    fetchMock.mock.calls.some(([url]) => url.startsWith('/api/jobs/')),
  ).toBe(false);
  rendered.unmount();
  const second = mount();
  await submit();
  let signal: AbortSignal | undefined;
  fetchMock.mockImplementation(async (url: string, init: RequestInit) => {
    if (url.startsWith('/api/jobs/')) {
      signal = init.signal!;
      return new Promise<Response>(() => {});
    }
    return json({ stale: false });
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  second.unmount();
  expect(signal?.aborted).toBe(true);
});
it('renders job failure inline with retry', async () => {
  vi.useFakeTimers();
  fetchMock.mockImplementation(async (url: string) => {
    if (url.startsWith('/api/jobs/'))
      return json({ status: 'failed', error: '模型暂时不可用' });
    return json(
      url === '/api/persona/chat' ? { job_id: 'j/1' } : { stale: false },
    );
  });
  mount();
  await submit();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(screen.getByRole('alert')).toHaveTextContent('模型暂时不可用');
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
  await act(async () => vi.advanceTimersByTimeAsync(1000));
  expect(scroll.mock.calls.length).toBeGreaterThan(sent);
  delete (HTMLElement.prototype as Partial<HTMLElement>).scrollIntoView;
});
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
