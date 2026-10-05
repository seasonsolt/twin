import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { useReducedMotion } from 'motion/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { PlaybackDialog } from '../features/playback/PlaybackDialog';
import * as ui from '../components/ui';
import { Avatar } from '../features/playback/Avatar';
import { useStatus } from '../stores/status';
import type { ChatReply } from '../features/chat/types';
import type { AvatarSpec } from '../features/playback/types';

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
const answer: ChatReply = {
  reply: '一句。二句。',
  confidence: 0.9,
  abstain: false,
  abstain_reason: '',
  citations: ['p1'],
  retrieved_ids: ['p1'],
};
const spec: AvatarSpec = {
  schema_version: 1,
  avatar_id: 'mock',
  label: 'API形象标识',
  palette: {
    skin: '#F4CFAC',
    hair: '#57477D',
    outfit: '#447B91',
    background: '#E8F1F3',
    accent: '#C55C7D',
  },
  mouth_states: 4,
  stylized: true,
};
const script = {
  persona_name: '测试人',
  explicit_label: 'API脚本标识',
  abstain: false,
  segments: [
    { index: 0, kind: 'notice', text: 'API开头提示' },
    { index: 1, kind: 'speech', text: '一句。' },
    { index: 2, kind: 'speech', text: '二句。' },
  ],
  citations: [{ ref_id: 'p1', reason: '证据' }],
};
const parts = [
  {
    index: 0,
    url: '/api/media/audio/0.wav',
    lipsync: { fps: 2, levels: [0, 1, 2, 3] },
  },
  { index: 1, url: '/api/media/audio/1a.wav', lipsync: null },
  { index: 1, url: '/api/media/audio/1b.wav', lipsync: null },
  { index: 2, url: '/api/media/audio/2.wav', lipsync: null },
];
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
let fetchMock: ReturnType<typeof vi.fn>;
let audio: HTMLAudioElement;
let paused = true;
let frames: Map<number, FrameRequestCallback>;
let cancelled: ReturnType<typeof vi.fn>;
let voiceFail = false;
let scriptFail = false;
let exportFail = false;
let failPlay = false;
let frameId = 0;
beforeEach(() => {
  vi.mocked(useReducedMotion).mockReturnValue(false);
  useStatus.setState({ data: null, error: null });
  voiceFail = false;
  scriptFail = false;
  exportFail = false;
  failPlay = false;
  paused = true;
  fetchMock = vi.fn(async (url: string) => {
    if (url === '/api/media/script')
      return scriptFail ? json({ detail: '无法准备回放' }, 400) : json(script);
    if (url === '/api/media/capabilities')
      return json({
        available: true,
        backend: 'mock-tts',
        label: 'API能力标识',
        avatar: spec,
      });
    if (url === '/api/media/audio')
      return voiceFail
        ? json({ detail: '语音合成超时，请稍后重试' }, 504)
        : json({ segments: parts });
    if (url === '/api/media/export')
      return exportFail
        ? json({ detail: '导出失败，请重试' }, 400)
        : new Response('<html>API导出</html>', {
            headers: { 'Content-Type': 'text/html' },
          });
    if (url === '/api/status')
      return json({
        target_name: '测试人',
        labels: {
          explicit: 'API状态标识',
          chat_notice: 'API聊天说明',
          disclaimer: 'API免责声明',
        },
      });
    throw new Error(`Unexpected API: ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal(
    'Audio',
    vi.fn(function () {
      audio = document.createElement('audio');
      Object.defineProperty(audio, 'paused', { get: () => paused });
      Object.defineProperty(audio, 'ended', { get: () => false });
      audio.play = vi.fn(async () => {
        if (failPlay) throw new Error('blocked');
        paused = false;
        audio.dispatchEvent(new Event('playing'));
      });
      audio.pause = vi.fn(() => {
        paused = true;
        audio.dispatchEvent(new Event('pause'));
      });
      audio.load = vi.fn();
      return audio;
    }),
  );
  frames = new Map();
});
function mockFrames() {
  vi.stubGlobal(
    'requestAnimationFrame',
    vi.fn((callback: FrameRequestCallback) => {
      frames.set(++frameId, callback);
      return frameId;
    }),
  );
  cancelled = vi.fn((id: number) => frames.delete(id));
  vi.stubGlobal('cancelAnimationFrame', cancelled);
}
afterEach(() => vi.useRealTimers());
function Harness({ reply = answer }: { reply?: ChatReply }) {
  const [open, setOpen] = useState(false);
  const [trigger, setTrigger] = useState<HTMLElement | null>(null);
  return (
    <>
      <button
        onClick={(event) => {
          setTrigger(event.currentTarget);
          setOpen(true);
        }}
      >
        回放
      </button>
      <PlaybackDialog
        open={open}
        onOpenChange={setOpen}
        answer={reply}
        personaName="测试人"
        trigger={trigger}
      />
    </>
  );
}
async function open(reply = answer) {
  const result = render(<Harness reply={reply} />);
  fireEvent.click(screen.getByRole('button', { name: '回放' }));
  await screen.findByRole('button', { name: '下一句' });
  expect(screen.getByRole('dialog')).toBeVisible();
  return result;
}
function panel() {
  return screen.getByLabelText('回放控制');
}
function current() {
  return screen
    .getByRole('list', { name: '已展示的句子' })
    .querySelector('[aria-current="step"]');
}
function tick() {
  act(() => {
    const callbacks = [...frames.entries()];
    frames.clear();
    callbacks.forEach(([, callback]) => callback(0));
  });
}
it('opens with API labels and opening notice, supports Space/arrows/Escape and restores trigger focus', async () => {
  await useStatus.getState().refresh();
  await open();
  expect(panel()).toHaveFocus();
  expect(screen.getByText('API状态标识')).toBeVisible();
  expect(screen.getByText('API形象标识')).toBeVisible();
  expect(current()).toHaveTextContent('API开头提示');
  expect(screen.getByText('证据', { exact: false })).toBeVisible();
  fireEvent.keyDown(panel(), { key: ' ' });
  expect(screen.getByRole('button', { name: '暂停' })).toBeVisible();
  fireEvent.keyDown(panel(), { key: ' ' });
  expect(screen.getByRole('button', { name: '播放' })).toBeVisible();
  fireEvent.keyDown(panel(), { key: 'ArrowRight' });
  expect(current()).toHaveTextContent('一句。');
  fireEvent.keyDown(panel(), { key: 'ArrowLeft' });
  expect(current()).toHaveTextContent('API开头提示');
  await userEvent.setup().keyboard('{Escape}');
  await waitFor(() =>
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
  );
  expect(screen.getByRole('button', { name: '回放' })).toHaveFocus();
});
it('uses shared quote cards for matched citations and falls back to IDs only for unmatched references', async () => {
  const originalFetch = fetchMock.getMockImplementation() as (
    url: string,
    init: RequestInit,
  ) => Promise<Response>;
  fetchMock.mockImplementation((url: string, init: RequestInit) =>
    url === '/api/media/script'
      ? Promise.resolve(
          json({
            ...script,
            citations: [
              { ref_id: 'pi_demo1', reason: '档案依据' },
              { ref_id: 'p1', reason: '原话依据' },
              { ref_id: 'missing_ref', reason: '缺失展示字段的依据' },
            ],
          }),
        )
      : originalFetch(url, init),
  );
  await open({
    ...answer,
    citations: ['pi_demo1', 'p1', 'missing_ref'],
    cited: [
      {
        id: 'p1',
        kind: 'expression',
        text: '先听大家的意见。',
        date: '2025-01-01',
        channel: '访谈',
      },
      {
        id: 'pi_demo1',
        kind: 'item',
        text: '优先听取不同意见。',
        facet: '决策习惯',
      },
      { id: 'unrelated', kind: 'expression', text: '不属于脚本引用的内容' },
    ],
  });
  const list = screen.getByRole('list', { name: '回答依据' });
  const cards = within(list).getAllByRole('listitem');
  expect(cards).toHaveLength(3);
  expect(cards[0]).toHaveTextContent('决策习惯');
  expect(cards[0].querySelector('blockquote')).toHaveTextContent(
    '优先听取不同意见。',
  );
  expect(cards[1]).toHaveTextContent('2025-01-01 · 访谈');
  expect(cards[1].querySelector('blockquote')).toHaveTextContent(
    '先听大家的意见。',
  );
  expect(cards[2]).toHaveTextContent('missing_ref：缺失展示字段的依据');
  expect(cards[2].querySelector('blockquote')).toBeNull();
  expect(within(list).queryByText('pi_demo1')).not.toBeInTheDocument();
  expect(within(list).queryByText('p1')).not.toBeInTheDocument();
  expect(
    within(list).queryByText('不属于脚本引用的内容'),
  ).not.toBeInTheDocument();
});
it('plays ordered audio parts, pauses/resumes without resetting time and advances segment indices', async () => {
  await open();
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '朗读' }));
  });
  expect(audio.getAttribute('src')).toBe(parts[0].url);
  expect(screen.getByRole('button', { name: '朗读' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  const init = fetchMock.mock.calls.find(
    ([url]) => url === '/api/media/audio',
  )![1] as RequestInit;
  expect(JSON.parse(init.body as string)).toEqual({
    kind: 'chat_reply',
    answer,
    persona_name: '测试人',
  });
  expect(new Headers(init.headers).get('X-Twin')).toBe('1');
  audio.currentTime = 1.5;
  fireEvent.click(screen.getByRole('button', { name: '暂停' }));
  expect(audio.currentTime).toBe(1.5);
  expect(screen.getByRole('img')).toHaveAttribute('data-mouth-level', '0');
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '播放' }));
  });
  expect(audio.currentTime).toBe(1.5);
  act(() => audio.dispatchEvent(new Event('ended')));
  expect(audio.getAttribute('src')).toBe(parts[1].url);
  expect(current()).toHaveTextContent('一句。');
  act(() => audio.dispatchEvent(new Event('ended')));
  expect(audio.getAttribute('src')).toBe(parts[2].url);
  expect(current()).toHaveTextContent('一句。');
  act(() => audio.dispatchEvent(new Event('ended')));
  expect(audio.getAttribute('src')).toBe(parts[3].url);
  expect(current()).toHaveTextContent('二句。');
  act(() => audio.dispatchEvent(new Event('ended')));
  expect(screen.getByRole('button', { name: '播放' })).toBeVisible();
  expect(audio.pause).toHaveBeenCalled();
});
it('drives all four mouth states from audio.currentTime and cancels rAF and audio on close', async () => {
  await open();
  mockFrames();
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '朗读' }));
  });
  for (const [time, level] of [
    [0, 0],
    [0.5, 1],
    [1, 2],
    [1.5, 3],
    [3, 0],
  ]) {
    audio.currentTime = time;
    tick();
    expect(screen.getByRole('img')).toHaveAttribute(
      'data-mouth-level',
      String(level),
    );
  }
  const pending = [...frames.keys()];
  fireEvent.click(screen.getByRole('button', { name: '关闭' }));
  expect(
    pending.every((id) =>
      cancelled.mock.calls.some(([cancelledId]) => cancelledId === id),
    ),
  ).toBe(true);
  expect(frames.size).toBe(0);
  expect(audio.getAttribute('src')).toBeNull();
  expect(audio.load).toHaveBeenCalledOnce();
});
it('leaves the mouth idle when voice is turned off or waiting, and cancels on unmount', async () => {
  const mounted = await open();
  mockFrames();
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '朗读' }));
  });
  audio.currentTime = 1.5;
  tick();
  act(() => audio.dispatchEvent(new Event('waiting')));
  expect(screen.getByRole('img')).toHaveAttribute('data-mouth-level', '0');
  expect(frames.size).toBe(0);
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '朗读' }));
  });
  expect(screen.getByRole('button', { name: '朗读' })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
  expect(screen.getByRole('img')).toHaveAttribute('data-mouth-level', '0');
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '朗读' }));
  });
  mounted.unmount();
  expect(frames.size).toBe(0);
  expect(audio.getAttribute('src')).toBeNull();
});
it('reduced motion disables automatic text playback, blink and mouth levels above one but allows audio advancement', async () => {
  vi.mocked(useReducedMotion).mockReturnValue(true);
  await open();
  expect(screen.getByRole('button', { name: '手动逐句回放' })).toBeDisabled();
  fireEvent.keyDown(panel(), { key: 'ArrowRight' });
  expect(current()).toHaveTextContent('一句。');
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
  mockFrames();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000);
  });
  expect(current()).toHaveTextContent('一句。');
  expect(
    [...screen.getByRole('img').querySelectorAll('[data-eye]')].every(
      (eye) => eye.getAttribute('ry') === '7',
    ),
  ).toBe(true);
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '朗读' }));
  });
  audio.currentTime = 1.5;
  tick();
  expect(screen.getByRole('img')).toHaveAttribute('data-mouth-level', '1');
  act(() => audio.dispatchEvent(new Event('ended')));
  expect(current()).toHaveTextContent('一句。');
});
it('stops audio and blink on a live reduced-motion change without refetching the script', async () => {
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  vi.stubGlobal('matchMedia', () => ({
    matches: false,
    addEventListener: (
      _type: string,
      listener: (event: MediaQueryListEvent) => void,
    ) => listeners.add(listener),
    removeEventListener: (
      _type: string,
      listener: (event: MediaQueryListEvent) => void,
    ) => listeners.delete(listener),
  }));
  const mounted = await open();
  mockFrames();
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '朗读' }));
  });
  audio.currentTime = 1.5;
  tick();
  expect(screen.getByRole('img')).toHaveAttribute('data-mouth-level', '3');
  act(() =>
    listeners.forEach((listener) =>
      listener({ matches: true } as MediaQueryListEvent),
    ),
  );
  expect(audio.paused).toBe(true);
  expect(audio.currentTime).toBe(1.5);
  expect(frames.size).toBe(0);
  expect(screen.getByRole('img')).toHaveAttribute('data-mouth-level', '0');
  expect(
    fetchMock.mock.calls.filter(([url]) => url === '/api/media/script'),
  ).toHaveLength(1);
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '播放' }));
  });
  tick();
  expect(screen.getByRole('img')).toHaveAttribute('data-mouth-level', '1');
  mounted.unmount();
  expect(listeners.size).toBe(0);
});
it('blinks in normal motion and clears blink timers on unmount', async () => {
  vi.useFakeTimers();
  vi.spyOn(Math, 'random').mockReturnValue(0);
  const mounted = render(<Avatar spec={spec} mouthLevel={3} />);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  expect(screen.getByRole('img').querySelector('[data-eye]')).toHaveAttribute(
    'ry',
    '1',
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(140);
  });
  expect(screen.getByRole('img').querySelector('[data-eye]')).toHaveAttribute(
    'ry',
    '7',
  );
  mounted.unmount();
  expect(vi.getTimerCount()).toBe(0);
  vi.mocked(Math.random).mockRestore();
});
it('audio errors retain Chinese API detail, fall back to text and can retry synthesis', async () => {
  voiceFail = true;
  await open();
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '朗读' }));
  });
  expect(
    screen.getByText('语音合成超时，请稍后重试，已切换为文字回放。'),
  ).toBeVisible();
  expect(screen.getByRole('button', { name: '朗读' })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
  voiceFail = false;
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '朗读' }));
  });
  expect(audio.getAttribute('src')).toBe(parts[0].url);
  expect(
    fetchMock.mock.calls.filter(([url]) => url === '/api/media/audio'),
  ).toHaveLength(2);
});
it('audio.play rejection safely falls back to manual text in reduced motion', async () => {
  vi.mocked(useReducedMotion).mockReturnValue(true);
  failPlay = true;
  await open();
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '朗读' }));
  });
  expect(screen.getByText('语音暂不可用，已切换为文字回放。')).toBeVisible();
  expect(screen.getByRole('button', { name: '手动逐句回放' })).toBeDisabled();
});
it('retries script failures and uses capabilities label without status fallback text', async () => {
  scriptFail = true;
  render(<Harness />);
  fireEvent.click(screen.getByRole('button', { name: '回放' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('无法准备回放');
  scriptFail = false;
  fireEvent.click(screen.getByRole('button', { name: '重试' }));
  await screen.findByRole('button', { name: '下一句' });
  await waitFor(() => expect(screen.getByText('API能力标识')).toBeVisible());
});
it('downloads the returned HTML through the API client and revokes URLs on close', async () => {
  const create = vi.fn((_blob: Blob) => {
    void _blob;
    return 'blob:export';
  });
  const revoke = vi.fn();
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    value: create,
  });
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    value: revoke,
  });
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, 'click')
    .mockImplementation(() => {});
  await open();
  exportFail = true;
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '导出' }));
  });
  expect(screen.getByRole('alert')).toHaveTextContent('导出失败，请重试');
  exportFail = false;
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '导出' }));
  });
  expect(create).toHaveBeenCalledOnce();
  expect(click).toHaveBeenCalledOnce();
  const blob = create.mock.calls[0][0] as Blob;
  expect(blob.type).toBe('text/html;charset=utf-8');
  const init = fetchMock.mock.calls.find(
    ([url]) => url === '/api/media/export',
  )![1] as RequestInit;
  expect(new Headers(init.headers).get('X-Twin')).toBe('1');
  fireEvent.click(screen.getByRole('button', { name: '关闭' }));
  expect(revoke).toHaveBeenCalledWith('blob:export');
  click.mockRestore();
});
it('exports video with a loading state, download, Chinese error toast and URL cleanup', async () => {
  const create = vi.fn((blob: Blob) => {
    void blob;
    return 'blob:video';
  });
  const revoke = vi.fn();
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    value: create,
  });
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    value: revoke,
  });
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, 'click')
    .mockImplementation(() => {});
  const toast = vi.spyOn(ui, 'toast').mockImplementation(() => () => {});
  await open();
  let resolve: (response: Response) => void = () => {};
  fetchMock.mockImplementation(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  fireEvent.click(screen.getByRole('button', { name: '导出视频' }));
  expect(screen.getByRole('button', { name: '导出视频' })).toBeDisabled();
  expect(screen.getByRole('button', { name: '导出' })).toBeDisabled();
  const init = fetchMock.mock.calls.find(
    ([url]) => url === '/api/media/clip',
  )![1] as RequestInit;
  expect(init.method).toBe('POST');
  expect(new Headers(init.headers).get('X-Twin')).toBe('1');
  expect(JSON.parse(init.body as string)).toEqual({
    kind: 'chat_reply',
    answer,
    persona_name: '测试人',
  });
  await act(async () => {
    resolve(
      new Response('mp4 bytes', { headers: { 'Content-Type': 'video/mp4' } }),
    );
  });
  expect(create.mock.calls[0][0].type).toBe('video/mp4');
  expect((click.mock.instances[0] as HTMLAnchorElement).download).toBe(
    'twin-media.mp4',
  );
  expect(screen.getByRole('button', { name: '导出视频' })).toBeEnabled();
  fetchMock.mockResolvedValue(
    json({ detail: 'private backend response' }, 503),
  );
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '导出视频' }));
  });
  expect(toast).toHaveBeenCalledWith(
    '视频导出失败，请检查 ffmpeg、字体和语音配置后重试',
    'danger',
  );
  expect(screen.getByRole('button', { name: '导出视频' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: '关闭' }));
  expect(revoke).toHaveBeenCalledWith('blob:video');
});
it('aborts pending requests on close and does not play late audio', async () => {
  await open();
  let signal: AbortSignal | undefined;
  let resolve: (response: Response) => void = () => {};
  fetchMock.mockImplementation((url: string, init: RequestInit) => {
    if (url === '/api/media/audio') {
      signal = init.signal!;
      return new Promise<Response>((done) => {
        resolve = done;
      });
    }
    return Promise.resolve(json(script));
  });
  fireEvent.click(screen.getByRole('button', { name: '朗读' }));
  fireEvent.click(screen.getByRole('button', { name: '关闭' }));
  expect(signal?.aborted).toBe(true);
  await act(async () => {
    resolve(json({ segments: parts }));
  });
  expect(audio.play).not.toHaveBeenCalled();
});
it('contains no hard-coded explicit labels or opening notices in playback or Chat', () => {
  const paths = readdirSync('src/features/playback').filter((path) =>
    /\.tsx?$/.test(path),
  );
  const source =
    paths
      .map((path) => readFileSync(`src/features/playback/${path}`, 'utf8'))
      .join('\n') + readFileSync('src/pages/Chat.tsx', 'utf8');
  expect(source).not.toContain('不代表本人意见');
  expect(source).not.toContain('以下内容由 AI 合成');
  expect(source).not.toContain('AI 合成 · 模拟推演');
});
it('text playback advances automatically and stops at the end', async () => {
  await open();
  vi.useFakeTimers();
  fireEvent.keyDown(panel(), { key: ' ' });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000);
  });
  expect(current()).toHaveTextContent('二句。');
  expect(
    within(screen.getByRole('dialog')).getByRole('button', { name: '播放' }),
  ).toBeVisible();
});
