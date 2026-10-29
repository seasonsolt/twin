import {
  act,
  cleanup,
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
import { ConfirmProvider, TooltipProvider } from '../components/ui';
import { useChatLayout } from '../stores/chatLayout';
import { Chat } from '../pages/Chat';
import { useAuth } from '../stores/auth';
import { useStatus } from '../stores/status';
import { CHAT_KEY, CURRENT_CHAT_KEY } from '../features/chat/useConversation';
import { conversationServer } from './conversationServer';
import { Citations } from '../features/chat/Citations';
import { MessageText } from '../features/chat/MessageText';
import { ReplyBasis, ReplyLine } from '../features/chat/ReplyDetails';
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
  useChatLayout.setState({
    sheet: undefined,
    stage: undefined,
    sheetWidth: undefined,
  });
  conversations = conversationServer();
  fail = false;
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const history = conversations.respond(url, init);
    if (history) return history;
    if (url === '/api/status')
      return json({
        target_name: '测试人',
        // Not a new twin: the setup card has its own tests (setup-card.test.tsx).
        counts: { sources: 1, items: 0 },
      });
    if (url === '/api/identity') return json({ about: '关注团队的协作方式。' });
    if (url === '/api/persona/state') return json({ stale: true });
    if (url === '/api/media/capabilities')
      return json({
        available: true,
        backend: null,
        video: { available: true },
      });
    if (
      url === '/api/persona/chat/stream' ||
      url === '/api/persona/chat/stream-with-files'
    ) {
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
    <TooltipProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={['/chat']}>
          <Navigation />
          <Routes>
            <Route path="/chat" element={<Chat />} />
            <Route path="/sources" element={<p>其他页面</p>} />
          </Routes>
        </MemoryRouter>
      </ConfirmProvider>
    </TooltipProvider>,
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
it('shows the real introduction and accepts a friendly no-profile reply without polling', async () => {
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
  expect(await screen.findByText('关注团队的协作方式。')).toBeVisible();
  expect(screen.getByRole('heading', { name: '和测试人聊聊' })).toBeVisible();
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

it('sends a selected file with the question and clears it after the reply', async () => {
  mount();
  const user = userEvent.setup();
  const file = new File(['合同期限是一年。'], '合同.txt', {
    type: 'text/plain',
  });
  await user.upload(screen.getByLabelText('选择附件'), file);
  expect(screen.getByText('合同.txt')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('你说'), {
    target: { value: '合同期限是多少？' },
  });
  await user.click(screen.getByRole('button', { name: '发送' }));

  const request = fetchMock.mock.calls.find(
    ([url]) => url === '/api/persona/chat/stream-with-files',
  )![1];
  expect(request.body).toBeInstanceOf(FormData);
  const form = request.body as FormData;
  expect(JSON.parse(String(form.get('payload'))).messages.at(-1)).toEqual({
    role: 'user',
    content: '合同期限是多少？',
  });
  expect((form.get('files') as File).name).toBe('合同.txt');
  expect(new Headers(request.headers).has('Content-Type')).toBe(false);

  await act(async () => {
    streamController.enqueue(encode('delta', { text: reply.reply }));
    streamController.enqueue(encode('final', reply));
    streamController.close();
  });
  await waitFor(() => expect(screen.queryByText('合同.txt')).toBeNull());
});

it('says which step the twin is on until its first words', async () => {
  mount();
  const user = userEvent.setup();
  fireEvent.change(screen.getByLabelText('你说'), {
    target: { value: '合同期限是多少？' },
  });
  await user.click(screen.getByRole('button', { name: '发送' }));
  expect(await screen.findByText('思考中…')).toBeInTheDocument();
  await act(async () => {
    streamController.enqueue(encode('step', { step: 'search' }));
  });
  expect(await screen.findByText('查资料…')).toBeInTheDocument();
  await act(async () => {
    streamController.enqueue(encode('step', { step: 'write' }));
  });
  expect(await screen.findByText('写回答…')).toBeInTheDocument();
  await act(async () => {
    streamController.enqueue(encode('delta', { text: reply.reply }));
    streamController.enqueue(encode('final', reply));
    streamController.close();
  });
  await waitFor(() => expect(screen.queryByText('写回答…')).toBeNull());
});

it('keeps a selected file for retry when the reply stream fails', async () => {
  mount();
  const user = userEvent.setup();
  const file = new File(['合同期限是一年。'], '合同.txt', {
    type: 'text/plain',
  });
  await user.upload(screen.getByLabelText('选择附件'), file);
  fireEvent.change(screen.getByLabelText('你说'), {
    target: { value: '合同期限是多少？' },
  });
  await user.click(screen.getByRole('button', { name: '发送' }));
  await act(async () => {
    streamController.enqueue(encode('error', { detail: '模型暂时不可用' }));
    streamController.close();
  });

  expect(screen.getByText('合同.txt')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '重试' }));

  const requests = fetchMock.mock.calls.filter(
    ([url]) => url === '/api/persona/chat/stream-with-files',
  );
  expect(requests).toHaveLength(2);
  const retriedForm = requests.at(-1)![1]!.body as FormData;
  const retriedFile = retriedForm.get('files') as File;
  expect(retriedFile.name).toBe('合同.txt');
  expect(retriedFile.size).toBe(file.size);
});

it('shows when the reply was made beside it, and what it rests on one click under it', async () => {
  mount();
  await submit();

  await act(async () => {
    streamController.enqueue(encode('delta', { text: reply.reply }));
    streamController.enqueue(
      encode('final', {
        ...reply,
        mode: 'grounded',
        abstain: false,
        elapsed_ms: 2350,
        completed_at: '2026-10-13T12:34:00.000Z',
        cited: [
          ...reply.cited!,
          {
            id: 'file_1_p0001',
            kind: 'file',
            file_name: '合同.txt',
            locator: '摘录 1',
            text: '合同期限是一年。',
          },
        ],
      }),
    );
    streamController.close();
  });

  const article = screen.getByRole('article', { name: '分身回复' });
  // The kind of answer and when it was made are read with it; what it rests on opens from the badge, in place.
  const badge = within(article).getByRole('button', {
    name: /^有本人资料支持/,
  });
  expect(badge).toBeVisible();
  expect(badge).toHaveAttribute('aria-expanded', 'false');
  expect(article).toHaveTextContent(/生成用时 2\.4 秒 · \d{2}:\d{2} 完成/);
  expect(within(article).queryByRole('list', { name: '回答依据' })).toBeNull();
  await userEvent.setup().click(badge);
  expect(badge).toHaveAttribute('aria-expanded', 'true');
  const evidence = within(article).getByRole('list', { name: '回答依据' });
  expect(within(evidence).getByText('先听听')).toBeVisible();
  expect(within(evidence).getByText('合同期限是一年。')).toBeVisible();
  // One layer: no dialog, no second disclosure.
  expect(screen.queryByRole('dialog')).toBeNull();
  await userEvent.setup().click(badge);
  expect(within(article).queryByRole('list', { name: '回答依据' })).toBeNull();
});

it('explains an abstaining reply without implying all source material is missing', () => {
  render(
    <ReplyBasis
      reply={{
        reply: '我先说能确定的部分。',
        citations: [],
        confidence: 0,
        abstain: true,
        abstain_reason: '',
        retrieved_ids: [],
        mode: 'abstain',
        elapsed_ms: 1250,
        completed_at: '2026-10-14T10:45:01.177Z',
      }}
    />,
  );

  expect(screen.getByText('资料不足，需要问本人')).toBeVisible();
  // No evidence to show: no evidence line, and nothing claims every source is missing.
  expect(screen.queryByRole('button', { name: /^依据/ })).toBeNull();
});

it('labels nothing under an unchecked reply and keeps the reason of an abstention behind its badge', async () => {
  const unchecked: ChatReply = {
    reply: '早上好，今天想聊什么？',
    citations: [],
    confidence: 0,
    abstain: false,
    abstain_reason: '',
    retrieved_ids: [],
    mode: 'general',
    verified: false,
    elapsed_ms: 800,
    completed_at: '2026-10-18T08:23:00.000Z',
  };
  const { unmount } = render(<ReplyLine reply={unchecked} />);
  // A greeting the model sent without metadata is not 资料不足, and not a general opinion either.
  expect(screen.queryByRole('group', { name: '回答依据摘要' })).toBeNull();
  // Only a way to see why there is nothing to check, with no label of its own.
  const why = screen.getByRole('button', { name: '处理详情' });
  expect(screen.queryByText('这条回答没有附带依据说明，无法核对')).toBeNull();
  await userEvent.setup().click(why);
  expect(screen.getByText('这条回答没有附带依据说明，无法核对')).toBeVisible();
  unmount();

  const abstained: ChatReply = {
    ...unchecked,
    abstain: true,
    abstain_reason: '回复没有给出所问内容：老家在哪',
    mode: 'abstain',
    verified: true,
  };
  render(<ReplyLine reply={abstained} />);
  const basis = screen.getByRole('group', { name: '回答依据摘要' });
  const badge = within(basis).getByRole('button', {
    name: /^资料不足，需要问本人/,
  });
  expect(basis).not.toHaveTextContent('老家在哪');
  await userEvent.setup().click(badge);
  expect(
    screen.getByText('没有作答的原因：回复没有给出所问内容：老家在哪'),
  ).toBeVisible();
});

it.each([false, true])(
  'hides video entries with video disabled and speech=%s',
  async (speech) => {
    const original = fetchMock.getMockImplementation()! as (
      url: string,
      init?: RequestInit,
    ) => Promise<Response>;
    fetchMock.mockImplementation((url: string, init?: RequestInit) =>
      url === '/api/media/capabilities'
        ? Promise.resolve(
            json({
              available: speech,
              backend: speech ? 'openai_compat' : 'silent',
              video: { available: false },
            }),
          )
        : url === '/api/persona/chat/stream'
          ? Promise.resolve(streamReply(reply))
          : original(url, init),
    );
    mount();
    await submit();
    await screen.findByRole('article', { name: '分身回复' });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '发送' })).toHaveAttribute(
        'aria-busy',
        'false',
      ),
    );
    expect(
      screen.queryByRole('button', { name: '让测试人说这句' }) !== null,
    ).toBe(speech);
    expect(
      screen.queryByRole('button', { name: '播放或暂停当前句' }),
    ).toBeNull();
    await userEvent.setup().click(screen.getByLabelText('更多：语音、形象'));
    await userEvent.setup().click(screen.getByRole('button', { name: '形象' }));
    expect(
      screen.queryByRole('button', { name: '播放或暂停当前句' }) !== null,
    ).toBe(speech);
    expect(screen.queryByText(/真人版生成失败/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '重试生成视频' }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText('舞台真人视频')).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([url]) => url.startsWith('/api/media/video')),
    ).toBe(false);
    if (!speech)
      expect(
        fetchMock.mock.calls.some(([url]) =>
          url.startsWith('/api/media/audio'),
        ),
      ).toBe(false);
  },
);

it('omits invented suggestions and keeps the empty composer ready without sending', async () => {
  mount();
  expect(screen.getByRole('heading', { name: '和测试人聊聊' })).toBeVisible();
  expect(screen.queryByLabelText('聊天开场白')).toBeNull();
  expect(screen.getByRole('textbox', { name: '你说' })).toHaveValue('');
  expect(screen.getByRole('textbox', { name: '你说' })).toHaveAttribute(
    'rows',
    '2',
  );
  expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();
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
  expect(within(abstention).getByText('资料不足，需要问本人')).toBeVisible();
  await userEvent
    .setup()
    .click(
      within(abstention).getByRole('button', { name: /^资料不足，需要问本人/ }),
    );
  expect(within(abstention).getByText('先听听')).toBeVisible();
  expect(
    within(abstention).getByText('没有作答的原因：证据不足'),
  ).toBeVisible();
  expect(screen.queryByText(/置信度|%/)).not.toBeInTheDocument();
  expect(screen.queryByText(/资料截至/)).not.toBeInTheDocument();
  expect(document.querySelector('input[type="date"]')).toBeNull();
  await userEvent.setup().click(screen.getByLabelText('更多：语音、形象'));
  expect(screen.getByRole('button', { name: '语音' })).toBeEnabled();
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
  expect(
    screen.getByRole('button', { name: /^有本人资料支持/ }),
  ).toBeInTheDocument();
  expect(sessionStorage.getItem(CHAT_KEY)).toBeNull();
  expect(localStorage.getItem(CURRENT_CHAT_KEY)).toBeTruthy();
  expect(
    fetchMock.mock.calls.filter(([url]) => url === '/api/media/audio'),
  ).toHaveLength(1);
});

it("says an inferred reply is not the person's own words, with no confidence", async () => {
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
  expect(screen.getByText('根据资料推测，不是本人原话')).toBeVisible();
  expect(screen.queryByText(/置信度|%/)).not.toBeInTheDocument();
});

it("says a general reply is not the person's view, with no confidence", async () => {
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
  expect(screen.getByText('通用建议，不代表本人观点')).toBeVisible();
  expect(screen.queryByText(/置信度|%/)).not.toBeInTheDocument();
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
  await user.click(screen.getByRole('button', { name: '展开对话列表' }));
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
it('uses a bounded thread, a two-line composer and mobile-safe font sizes', () => {
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
    'chat-composer',
  );
  const input = screen.getByRole('textbox', { name: '你说' });
  expect(input).toHaveAttribute('rows', '2');
  // Phones get 16px from the global mobile rule below, so iOS does not zoom in.
  expect(input).not.toHaveClass('text-sm', 'text-xs');
  expect(view.container.querySelector('time')).toBeNull();
  const css = readFileSync('src/design/tokens.css', 'utf8');
  expect(css).toContain('font-size: 16px !important');
  expect(css).toContain('env(safe-area-inset-bottom');
  expect(css).toContain('-webkit-tap-highlight-color: transparent');
});
it('shares a centered, bounded 720px desktop grid between conversation and composer', () => {
  const view = mount();
  expect(
    view.container.querySelector(
      '.chat-scroll > .chat-column-grid .chat-conversation',
    ),
  ).not.toBeNull();
  expect(screen.getByRole('form', { name: '消息输入' })).toHaveClass(
    'chat-column-grid',
  );
  const css = readFileSync('src/components/ui/chat.css', 'utf8');
  expect(css).toMatch(/minmax\(\s*0,\s*var\(--spacing-chat-column\)\s*\)/);
  expect(css).toMatch(
    /\.chat-redesign \.chat-composer\s*\{\s*position: static/,
  );
  expect(css).toContain('.chat-surface-sheet');
  expect(view.container.querySelector('.chat-surface-stage')).toBeNull();
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
it('puts a sent message at the top and lets the reply grow below it instead of chasing it', async () => {
  vi.useFakeTimers();
  const scroll = vi.fn();
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: scroll,
  });
  mount();
  await submit();
  await act(async () => {
    vi.advanceTimersByTime(50);
  });
  const starts = scroll.mock.contexts.filter(
    (_: unknown, index: number) =>
      (scroll.mock.calls[index][0] as ScrollIntoViewOptions | undefined)
        ?.block === 'start',
  );
  const pinned = starts.at(-1) as HTMLElement | undefined;
  expect(pinned).toHaveAttribute('aria-label', '你说');
  expect(pinned).toHaveAttribute('data-pin');
  expect(document.querySelector('.chat-page')).toHaveAttribute(
    'data-empty',
    'false',
  );
  const sent = scroll.mock.calls.length;
  await act(async () => {
    streamController.enqueue(encode('final', reply));
    streamController.close();
  });
  await act(async () => {
    vi.advanceTimersByTime(50);
  });
  expect(
    scroll.mock.calls
      .slice(sent)
      .filter(
        ([options]) => (options as ScrollIntoViewOptions)?.block === 'end',
      ),
  ).toEqual([]);
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
    const basis = screen.getByRole('group', { name: '回答依据摘要' });
    const citations = within(basis).getByRole('button', {
      name: /^有本人资料支持/,
    });
    expect(bubble.querySelector('button')).toBeNull();
    // Under the bubble, one line: what kind of answer it is, then the voice and the copy button at the end.
    expect(row.parentElement?.parentElement).toBe(article);
    expect(row.parentElement).toContainElement(basis);
    expect(row).toContainElement(play);
    expect(row).toHaveClass('ml-auto', 'items-center');
    expect(play).toHaveClass('min-h-11', 'min-w-11');
    expect(bubble.querySelectorAll('p')).toHaveLength(2);
    // Top-aligned like ChatGPT: the thread starts at the top, not above the composer.
    const conversation = view.container.querySelector('.chat-conversation');
    expect(conversation).toHaveClass('flex', 'flex-col');
    expect(conversation).not.toHaveClass('justify-end');
    await userEvent.setup().click(citations);
    expect(
      within(article).getByRole('list', { name: '回答依据' }),
    ).toBeVisible();
  },
);

it('opens the evidence in a side layer from the keyboard, shows every citation kind, and returns focus on close', async () => {
  render(
    <Citations
      cited={[
        ...reply.cited!,
        { id: 'i1', kind: 'item', facet: '价值观', text: '档案内容' },
        {
          id: 'le_1',
          kind: 'ledger',
          ledger_kind: '承诺',
          date: '2023-10-12',
          channel: '周一经营会',
          text: '我周五前给您一版新报价方案',
        },
        {
          id: 'file_1_p0001',
          kind: 'file',
          file_name: '合同.txt',
          locator: '摘录 1',
          text: '合同期限是一年。',
        },
      ]}
    />,
  );
  const user = userEvent.setup();
  const evidence = screen.getByRole('button', {
    name: '依据 · 访谈 · 2024 年 1 月 1 日 等 4 处',
  });
  expect(evidence).toHaveAttribute('aria-haspopup', 'dialog');
  await user.tab();
  expect(evidence).toHaveFocus();
  await user.keyboard('{Enter}');
  const layer = await screen.findByRole('dialog', { name: '回答依据' });
  // The layer fades in; wait until it is shown before checking what it holds.
  await waitFor(() => expect(layer).toBeVisible());
  expect(within(layer).getByRole('list', { name: '回答依据' })).toBeVisible();
  expect(within(layer).getByText('访谈 · 2024 年 1 月 1 日')).toBeVisible();
  expect(within(layer).getByText('价值观')).toBeVisible();
  expect(
    within(layer).getByText(
      '承诺账本 · 承诺 · 周一经营会 · 2023 年 10 月 12 日',
    ),
  ).toBeVisible();
  expect(within(layer).getByText('合同.txt · 摘录 1')).toBeVisible();
  expect(within(layer).getByText('我周五前给您一版新报价方案')).toBeVisible();
  await user.keyboard('{Escape}');
  await waitFor(() =>
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
  );
  expect(evidence).toHaveFocus();
});

it('collapses and expands the sheet, preserves the draft and remembers the choice', async () => {
  const view = mount();
  fireEvent.change(screen.getByRole('textbox', { name: '你说' }), {
    target: { value: '还没发出的想法' },
  });
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: '展开对话列表' }));
  expect(screen.getByRole('region', { name: '对话列表' })).toBeVisible();
  await user.click(screen.getByRole('button', { name: '搜索对话' }));
  expect(screen.getByRole('searchbox', { name: '搜索对话' })).toHaveFocus();
  await user.click(screen.getByRole('button', { name: '收起对话列表' }));
  expect(screen.queryByRole('region', { name: '对话列表' })).toBeNull();
  expect(screen.getByRole('textbox', { name: '你说' })).toHaveValue(
    '还没发出的想法',
  );
  expect(JSON.parse(localStorage.getItem('twin:chat-layout')!)).toMatchObject({
    sheet: false,
  });
  view.unmount();
  mount();
  expect(screen.getByRole('button', { name: '展开对话列表' })).toBeVisible();
});

it('resizes the sheet by dragging or with the keyboard, within limits, and remembers the width', async () => {
  // jsdom has no pointer capture; the handle only needs it to keep the drag past its edge.
  Object.assign(HTMLElement.prototype, {
    setPointerCapture: vi.fn(),
    releasePointerCapture: vi.fn(),
    hasPointerCapture: vi.fn(() => true),
  });
  const view = mount();
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: '展开对话列表' }));
  const handle = screen.getByRole('separator', { name: '调整对话列表宽度' });
  const sheet = () =>
    screen
      .getByRole('region', { name: '对话列表' })
      .closest('.chat-surface-sheet') as HTMLElement;
  expect(handle).toHaveAttribute('aria-valuenow', '280');
  expect(sheet().style.getPropertyValue('--chat-sheet-width')).toBe('');

  fireEvent.pointerDown(handle, { button: 0, clientX: 300, pointerId: 1 });
  fireEvent.pointerMove(handle, { clientX: 400, pointerId: 1 });
  fireEvent.pointerUp(handle, { clientX: 400, pointerId: 1 });
  expect(handle).toHaveAttribute('aria-valuenow', '380');
  expect(sheet().style.getPropertyValue('--chat-sheet-width')).toBe('380px');
  // Moving without a press does nothing.
  fireEvent.pointerMove(handle, { clientX: 100, pointerId: 1 });
  expect(handle).toHaveAttribute('aria-valuenow', '380');

  fireEvent.pointerDown(handle, { button: 0, clientX: 380, pointerId: 2 });
  fireEvent.pointerMove(handle, { clientX: 2000, pointerId: 2 });
  fireEvent.pointerUp(handle, { pointerId: 2 });
  expect(handle).toHaveAttribute('aria-valuenow', '440');

  handle.focus();
  await user.keyboard('{ArrowLeft}');
  expect(handle).toHaveAttribute('aria-valuenow', '424');
  await user.keyboard('{Home}');
  expect(handle).toHaveAttribute('aria-valuenow', '220');
  await user.keyboard('{ArrowLeft}');
  expect(handle).toHaveAttribute('aria-valuenow', '220');
  await user.keyboard('{Shift>}{ArrowRight}{/Shift}');
  expect(handle).toHaveAttribute('aria-valuenow', '284');
  expect(JSON.parse(localStorage.getItem('twin:chat-layout')!)).toMatchObject({
    sheetWidth: 284,
  });

  view.unmount();
  useChatLayout.setState({ sheetWidth: undefined });
  localStorage.setItem(
    'twin:chat-layout',
    JSON.stringify({ sheet: true, sheetWidth: 9999 }),
  );
  vi.resetModules();
  const { useChatLayout: reread } = await import('../stores/chatLayout');
  expect(reread.getState().sheetWidth).toBe(440);

  useChatLayout.setState({ sheetWidth: 284 });
  mount();
  const again = screen.getByRole('separator', { name: '调整对话列表宽度' });
  expect(again).toHaveAttribute('aria-valuenow', '284');
  await user.dblClick(again);
  expect(again).toHaveAttribute('aria-valuenow', '280');
});

it('keeps the portrait closed initially, toggles it and remembers the choice', async () => {
  const view = mount();
  expect(
    screen.queryByRole('complementary', { name: '测试人的形象' }),
  ).toBeNull();
  const user = userEvent.setup();
  await user.click(screen.getByLabelText('更多：语音、形象'));
  await user.click(screen.getByRole('button', { name: '形象' }));
  expect(
    screen.getByRole('complementary', { name: '测试人的形象' }),
  ).toBeVisible();
  // The menu entry says what it does next.
  expect(screen.getByRole('button', { name: '收起形象' })).toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem('twin:chat-layout')!)).toMatchObject({
    stage: true,
  });
  view.unmount();
  mount();
  expect(
    screen.getByRole('complementary', { name: '测试人的形象' }),
  ).toBeVisible();
  await user.click(screen.getByRole('button', { name: '关闭形象' }));
  expect(
    screen.queryByRole('complementary', { name: '测试人的形象' }),
  ).toBeNull();
  expect(screen.getByRole('button', { name: '形象' })).toBeInTheDocument();
});

it('puts attachment limits in the accessible tooltip, not in a permanent hint', async () => {
  mount();
  const hint = 'TXT、PDF、Word、EPUB 等，最多 5 个，共 50 MiB';
  const attach = screen.getByRole('button', { name: `添加附件（${hint}）` });
  expect(screen.queryByText(hint)).toBeNull();
  await userEvent.setup().hover(attach);
  expect(await screen.findByRole('tooltip')).toHaveTextContent(hint);
});

it('keeps last-answer actions visible and copies the answer', async () => {
  sessionStorage.setItem(
    CHAT_KEY,
    JSON.stringify([
      {
        id: 'older',
        role: 'twin',
        content: '较早的回答',
        reply,
        timestamp: '2025-01-01T12:00:00Z',
      },
      {
        id: 'last',
        role: 'twin',
        content: reply.reply,
        reply,
        timestamp: '2025-01-01T12:01:00Z',
      },
    ]),
  );
  const user = userEvent.setup();
  const copy = vi.spyOn(navigator.clipboard, 'writeText');
  mount();
  const answers = await screen.findAllByRole('article', { name: '分身回复' });
  expect(answers[0]).not.toHaveAttribute('data-last-answer');
  expect(answers[1]).toHaveAttribute('data-last-answer', 'true');
  const button = within(answers[1]).getByRole('button', { name: '复制' });
  expect(button).toBeVisible();
  await user.click(button);
  expect(copy).toHaveBeenCalledWith(reply.reply);
});

it('honours choices without writable localStorage', async () => {
  mount();
  const write = vi
    .spyOn(Storage.prototype, 'setItem')
    .mockImplementation(() => {
      throw new Error('denied');
    });
  try {
    await userEvent
      .setup()
      .click(screen.getByRole('button', { name: '展开对话列表' }));
    expect(screen.getByRole('region', { name: '对话列表' })).toBeVisible();
  } finally {
    write.mockRestore();
  }
});

it('does not label unverified answers even if stale citation metadata is present', () => {
  render(<ReplyBasis reply={{ ...reply, verified: false }} />);
  expect(screen.queryByRole('group', { name: '回答依据摘要' })).toBeNull();
  expect(screen.queryByText('资料不足，需要问本人')).toBeNull();
});

it('uses the remembered collapsed choice even on a wide screen', () => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: query === '(min-width: 1280px)',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  useChatLayout.setState({ sheet: false });
  mount();
  expect(screen.getByRole('button', { name: '展开对话列表' })).toBeVisible();
  expect(screen.queryByRole('region', { name: '对话列表' })).toBeNull();
});

const twoAnswers = () =>
  sessionStorage.setItem(
    CHAT_KEY,
    JSON.stringify([
      {
        id: 'older',
        role: 'twin',
        content: '较早的回答',
        reply: { ...reply, reply: '较早的回答' },
        timestamp: '2025-01-01T12:00:00Z',
      },
      {
        id: 'last',
        role: 'twin',
        content: '最近的回答',
        reply: { ...reply, reply: '最近的回答' },
        timestamp: '2025-01-01T12:01:00Z',
      },
    ]),
  );
const hangAudio = () => {
  const original = fetchMock.getMockImplementation()! as (
    url: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetchMock.mockImplementation((url: string, init?: RequestInit) =>
    url === '/api/media/audio'
      ? new Promise<Response>(() => {})
      : original(url, init),
  );
};
const spoken = () =>
  fetchMock.mock.calls
    .filter(([url]) => url === '/api/media/audio')
    .map(([, init]) => JSON.parse(String(init.body)).answer.reply as string);

it('reads the latest answer aloud from the menu', async () => {
  twoAnswers();
  hangAudio();
  const user = userEvent.setup();
  mount();
  await screen.findAllByRole('article', { name: '分身回复' });
  await user.click(screen.getByLabelText('更多：语音、形象'));
  await user.click(screen.getByRole('button', { name: '语音' }));
  await waitFor(() => expect(spoken()).toEqual(['最近的回答']));
});

it('has nothing to read aloud from the menu before there is an answer, or where there is no voice', async () => {
  const user = userEvent.setup();
  mount();
  await screen.findByLabelText('你说');
  await user.click(screen.getByLabelText('更多：语音、形象'));
  expect(screen.getByRole('button', { name: '语音' })).toBeDisabled();
  await user.keyboard('{Escape}');
  cleanup();
  sessionStorage.clear();
  localStorage.clear();
  twoAnswers();
  const original = fetchMock.getMockImplementation()! as (
    url: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetchMock.mockImplementation((url: string, init?: RequestInit) =>
    url === '/api/media/capabilities'
      ? Promise.resolve(json({ available: false, video: { available: false } }))
      : original(url, init),
  );
  mount();
  await screen.findAllByRole('article', { name: '分身回复' });
  await user.click(screen.getByLabelText('更多：语音、形象'));
  expect(screen.getByRole('button', { name: '语音' })).toBeDisabled();
});

it('stops reading aloud when the person goes on to give a task, which has no way to stop it', async () => {
  useAuth.setState({
    identity: {
      email: 'me@example.com',
      admin: false,
      auth_enabled: true,
      features: { work: true },
    },
  });
  try {
    twoAnswers();
    hangAudio();
    const user = userEvent.setup();
    mount();
    const answers = await screen.findAllByRole('article', { name: '分身回复' });
    await user.click(
      within(answers[1]).getByRole('button', { name: '让测试人说这句' }),
    );
    expect(
      await within(answers[1]).findByRole('button', {
        name: '正在说这句，点击暂停',
      }),
    ).toBeVisible();
    await user.click(screen.getByRole('radio', { name: '交代任务' }));
    await user.click(screen.getByRole('radio', { name: '问答' }));
    const back = await screen.findAllByRole('article', { name: '分身回复' });
    expect(
      await within(back[1]).findByRole('button', { name: '让测试人说这句' }),
    ).toBeVisible();
  } finally {
    useAuth.setState({ identity: null });
  }
});

it('brings what an answer rests on into view when it is opened', async () => {
  const scroll = vi.fn();
  Element.prototype.scrollIntoView = scroll;
  try {
    mount();
    await submit();
    await act(async () => {
      streamController.enqueue(encode('final', reply));
      streamController.close();
    });
    const answer = await screen.findByLabelText('分身回复');
    scroll.mockClear();
    await userEvent
      .setup()
      .click(
        within(answer).getByRole('button', { name: /^资料不足，需要问本人/ }),
      );
    expect(within(answer).getByText('先听听')).toBeVisible();
    expect(scroll).toHaveBeenCalledWith({ block: 'nearest' });
  } finally {
    Reflect.deleteProperty(Element.prototype, 'scrollIntoView');
  }
});

it("puts the twin's core over a persona twin's chat in place of its portrait, and lets it think while it answers", async () => {
  useAuth.setState({
    identity: {
      email: null,
      admin: true,
      auth_enabled: false,
      edition: 'persona',
    },
  });
  try {
    mount();
    expect(
      await screen.findByRole('img', { name: '分身的心核' }),
    ).toBeVisible();
    expect(screen.getByRole('heading', { name: '和测试人聊聊' })).toBeVisible();
    await submit();
    expect(screen.getByRole('img', { name: '分身正在想' })).toBeVisible();
  } finally {
    useAuth.setState({ identity: null });
  }
});

it('keeps the portrait and no core over a team twin’s chat', async () => {
  mount();
  expect(
    await screen.findByRole('heading', { name: '和测试人聊聊' }),
  ).toBeVisible();
  expect(screen.queryByRole('img', { name: '分身的心核' })).toBeNull();
});
