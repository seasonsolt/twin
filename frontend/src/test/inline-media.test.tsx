import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { StrictMode } from 'react';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider } from '../components/ui';
import { Chat } from '../pages/Chat';
import { ChatAvatar } from '../features/chat/ChatAvatar';
import { ReplyVideo } from '../features/chat/ReplyVideo';
import { useReplyAudio } from '../features/chat/useReplyAudio';
import { useReplyVideos } from '../features/chat/useReplyVideos';
import type { Turn } from '../features/chat/types';
import { CHAT_KEY } from '../features/chat/useConversation';
import { useStatus } from '../stores/status';
import type { Capabilities } from '../features/avatar/types';
import type { ChatReply } from '../features/chat/types';

const preference = vi.hoisted(() => ({ reduced: false }));
vi.mock('../design/motion', async (original) => ({
  ...(await original<typeof import('../design/motion')>()),
  useMotionPreset: () => ({
    reduced: preference.reduced,
    transition: { duration: 0 },
    exit: { duration: 0 },
  }),
}));
vi.mock('../features/avatar/Avatar3D', () => ({
  default: (props: { still?: boolean; onFallback(): void }) => (
    <button
      aria-label="VRM 静态头像"
      data-still={props.still}
      onClick={props.onFallback}
    >
      模型
    </button>
  ),
}));
const answer: ChatReply = {
  reply: '先听听大家的意见。',
  confidence: 0.9,
  abstain: false,
  abstain_reason: '',
  citations: [],
  retrieved_ids: [],
  mode: 'grounded',
};
const caps: Capabilities = {
  available: true,
  backend: 'local',
  avatar_image: { url: '/api/media/avatar-image' },
  avatar_model: { format: 'vrm', url: '/api/media/avatar.vrm' },
  video: { available: true },
};
const parts = [
  {
    index: 0,
    url: '/api/media/audio/notice.wav',
    duration_s: 2,
    lipsync: { fps: 2, levels: [0, 1, 2, 3] },
  },
  { index: 1, url: '/api/media/audio/1a.wav', duration_s: 2, lipsync: null },
  { index: 1, url: '/api/media/audio/1b.wav', duration_s: 2, lipsync: null },
];
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
let fetchMock: ReturnType<typeof vi.fn>;
let paused: boolean;
let failPlay: boolean;
let frames: Map<number, FrameRequestCallback>;
let jobStatus: 'running' | 'done' | 'failed';
let audioFail: boolean;
let submitFail: boolean;
beforeEach(() => {
  sessionStorage.clear();
  preference.reduced = false;
  paused = true;
  failPlay = false;
  audioFail = false;
  submitFail = false;
  jobStatus = 'running';
  frames = new Map();
  let frame = 0;
  vi.stubGlobal(
    'requestAnimationFrame',
    vi.fn((callback: FrameRequestCallback) => {
      frames.set(++frame, callback);
      return frame;
    }),
  );
  vi.stubGlobal(
    'cancelAnimationFrame',
    vi.fn((id: number) => frames.delete(id)),
  );
  vi.spyOn(HTMLMediaElement.prototype, 'paused', 'get').mockImplementation(
    () => paused,
  );
  vi.spyOn(HTMLMediaElement.prototype, 'ended', 'get').mockReturnValue(false);
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(
    async function (this: HTMLMediaElement) {
      if (failPlay) throw new Error('blocked');
      paused = false;
      this.dispatchEvent(new Event('playing'));
    },
  );
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function (
    this: HTMLMediaElement,
  ) {
    paused = true;
    this.dispatchEvent(new Event('pause'));
  });
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
  useStatus.setState({ data: null, error: null });
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/persona/state') return json({ stale: false });
    if (url === '/api/media/capabilities') return json(caps);
    if (url === '/api/media/audio')
      return audioFail
        ? json({ detail: '语音暂不可用' }, 503)
        : json({
            segment_count: 2,
            segments: parts.filter((part) =>
              JSON.parse(init!.body as string).segments.includes(part.index),
            ),
          });
    if (url === '/api/media/video')
      return submitFail
        ? json({ detail: '无法提交视频任务' }, 503)
        : json({ job_id: 'video/1' });
    if (url === '/api/media/video/jobs/video%2F1')
      return json({
        job_id: 'video/1',
        kind: 'video',
        status: jobStatus,
        stage: { current: 2, total: 4, label: '生成' },
        error: '视频生成失败，请检查配置',
        result:
          jobStatus === 'done'
            ? {
                file: `${'a'.repeat(64)}.mp4`,
                duration_s: 6,
                warnings: ['s02: cer=0.1'],
              }
            : undefined,
      });
    throw new Error(`Unexpected API: ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});
const count = (path: string) =>
  fetchMock.mock.calls.filter(([url]) => url === path).length;
function AudioHarness({ active = true }: { active?: boolean }) {
  const audio = useReplyAudio(active);
  return (
    <>
      <audio ref={audio.audioRef} />
      {['one', 'two'].map((id) => (
        <article key={id} aria-label={id}>
          <ChatAvatar
            name="测试人"
            capabilities={caps}
            level={audio.id === id ? audio.level : 0}
            speaking={audio.id === id && audio.speaking}
          />
          <button
            aria-label={
              audio.id === id && audio.playing ? '暂停语音' : '播放语音'
            }
            onClick={() => audio.toggle(id, answer, '测试人')}
          >
            {audio.id === id && audio.playing ? '暂停' : '听'}
          </button>
          {audio.id === id && (
            <progress
              aria-label="语音播放进度"
              max={1}
              value={audio.progress}
            />
          )}
          {audio.errors[id] && <p role="alert">{audio.errors[id]}</p>}
        </article>
      ))}
    </>
  );
}
function tick() {
  act(() => {
    const pending = [...frames.values()];
    frames.clear();
    pending.forEach((callback) => callback(0));
  });
}

it.each(['grounded', 'general', 'abstain'] as const)(
  'shows inline actions by %s mode and video availability at 375px',
  async (mode) => {
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      value: 375,
    });
    sessionStorage.setItem(
      CHAT_KEY,
      JSON.stringify([
        {
          id: 'reply',
          role: 'twin',
          content: answer.reply,
          reply: { ...answer, mode, abstain: mode === 'abstain' },
          timestamp: '2025-01-01T12:00:00Z',
        },
      ]),
    );
    const view = render(
      <ConfirmProvider>
        <MemoryRouter initialEntries={['/chat']}>
          <Chat />
        </MemoryRouter>
      </ConfirmProvider>,
    );
    await screen.findByRole('img', { name: '本人的肖像' });
    const article = screen.getByRole('article', { name: '分身回复' });
    expect(article).toHaveClass('flex', 'w-full', 'min-w-0');
    expect(article.firstElementChild).toHaveAttribute('aria-label', '分身头像');
    if (mode === 'abstain') {
      expect(
        screen.queryByRole('group', { name: '回复媒体' }),
      ).not.toBeInTheDocument();
      expect(count('/api/media/video')).toBe(0);
    } else {
      expect(screen.getByRole('button', { name: '播放语音' })).toHaveClass(
        'min-h-11',
        'min-w-11',
      );
      expect(
        screen.getByRole('button', { name: '播放语音' }),
      ).toHaveTextContent('播放');
      expect(
        screen.queryByRole('button', { name: '生成视频' }),
      ).not.toBeInTheDocument();
      await waitFor(() => expect(count('/api/media/video')).toBe(1));
      expect(screen.getByText('真人版生成中…')).toBeVisible();
      expect(screen.getByRole('group', { name: '回复媒体' })).toHaveClass(
        'flex-wrap',
        'min-w-0',
      );
    }
    expect(view.container.querySelectorAll('audio')).toHaveLength(1);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  },
);
it('hides video without capability, but keeps the voice action', async () => {
  fetchMock.mockImplementation(async (url: string) =>
    json(
      url === '/api/media/capabilities'
        ? { ...caps, video: { available: false } }
        : { stale: false },
    ),
  );
  sessionStorage.setItem(
    CHAT_KEY,
    JSON.stringify([
      {
        id: 'reply',
        role: 'twin',
        content: answer.reply,
        reply: answer,
        timestamp: '2025-01-01T12:00:00Z',
      },
    ]),
  );
  render(
    <ConfirmProvider>
      <MemoryRouter initialEntries={['/chat']}>
        <Chat />
      </MemoryRouter>
    </ConfirmProvider>,
  );
  await screen.findByRole('img', { name: '本人的肖像' });
  expect(screen.getByRole('button', { name: '播放语音' })).toBeVisible();
  expect(
    screen.queryByRole('button', { name: '生成视频' }),
  ).not.toBeInTheDocument();
});
it('plays all ordered parts, pauses/resumes, follows lipsync with glow and tracks duration progress', async () => {
  const view = render(<AudioHarness />);
  const one = within(screen.getByRole('article', { name: 'one' }));
  fireEvent.click(one.getByRole('button', { name: '播放语音' }));
  await waitFor(() =>
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1),
  );
  const audio = view.container.querySelector('audio')!;
  expect(audio).toHaveAttribute('src', parts[0].url);
  const body = JSON.parse(
    fetchMock.mock.calls.find(([url]) => url === '/api/media/audio')![1].body,
  );
  expect(body).toEqual({
    kind: 'chat_reply',
    answer,
    persona_name: '测试人',
    segments: [0],
  });
  await waitFor(() => expect(count('/api/media/audio')).toBe(2));
  audio.currentTime = 1.5;
  tick();
  expect(one.getByRole('progressbar')).toHaveAttribute('value', '0.25');
  expect(
    screen
      .getByRole('article', { name: 'one' })
      .querySelector('[data-portrait-glow]'),
  ).toHaveAttribute('data-glow-level', '3');
  fireEvent.waiting(audio);
  expect(
    screen
      .getByRole('article', { name: 'one' })
      .querySelector('[data-portrait-glow]'),
  ).toHaveAttribute('data-glow-level', '0');
  expect(frames.size).toBe(0);
  fireEvent.playing(audio);
  expect(
    screen
      .getByRole('article', { name: 'one' })
      .querySelector('[data-portrait-glow]'),
  ).toHaveAttribute('data-glow-level', '3');
  fireEvent.click(one.getByRole('button', { name: '暂停语音' }));
  expect(paused).toBe(true);
  expect(frames.size).toBe(0);
  fireEvent.click(one.getByRole('button', { name: '播放语音' }));
  expect(audio.currentTime).toBe(1.5);
  expect(count('/api/media/audio')).toBe(2);
  fireEvent.ended(audio);
  expect(audio).toHaveAttribute('src', parts[1].url);
  fireEvent.ended(audio);
  expect(audio).toHaveAttribute('src', parts[2].url);
  fireEvent.ended(audio);
  expect(one.getByRole('button', { name: '播放语音' })).toHaveTextContent('听');
  expect(one.getByRole('progressbar')).toHaveAttribute('value', '1');
  fireEvent.timeUpdate(audio);
  expect(one.getByRole('progressbar')).toHaveAttribute('value', '1');
  fireEvent.click(one.getByRole('button', { name: '播放语音' }));
  expect(audio).toHaveAttribute('src', parts[0].url);
  expect(count('/api/media/audio')).toBe(2);
});
it('stops the previous reply and releases audio, requests and frames on leaving', async () => {
  const view = render(<AudioHarness />);
  const one = within(screen.getByRole('article', { name: 'one' }));
  const two = within(screen.getByRole('article', { name: 'two' }));
  fireEvent.click(one.getByRole('button', { name: '播放语音' }));
  await waitFor(() => expect(paused).toBe(false));
  fireEvent.click(two.getByRole('button', { name: '播放语音' }));
  await waitFor(() => expect(count('/api/media/audio')).toBe(4));
  expect(one.getByRole('button', { name: '播放语音' })).toHaveTextContent('听');
  expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  expect(one.queryByRole('progressbar')).not.toBeInTheDocument();
  view.rerender(<AudioHarness active={false} />);
  expect(paused).toBe(true);
  expect(frames.size).toBe(0);
  expect(view.container.querySelector('audio')).not.toHaveAttribute('src');
  expect(
    fetchMock.mock.calls
      .filter(([url]) => url === '/api/media/audio')
      .every(([, init]) => init.signal.aborted),
  ).toBe(true);
});
it('ignores a late audio response when another reply starts', async () => {
  let resolve!: (response: Response) => void;
  fetchMock.mockImplementationOnce(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  const view = render(<AudioHarness />);
  const one = within(screen.getByRole('article', { name: 'one' }));
  const two = within(screen.getByRole('article', { name: 'two' }));
  fireEvent.click(one.getByRole('button', { name: '播放语音' }));
  fireEvent.click(two.getByRole('button', { name: '播放语音' }));
  await waitFor(() =>
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1),
  );
  await act(async () =>
    resolve(json({ segments: [{ ...parts[0], url: '/late.wav' }] })),
  );
  expect(view.container.querySelector('audio')).toHaveAttribute(
    'src',
    parts[0].url,
  );
  expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1);
});
it('can pause while synthesis is pending and ignores the cancelled response', async () => {
  let resolve!: (response: Response) => void;
  fetchMock.mockImplementationOnce(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  render(<AudioHarness />);
  const one = within(screen.getByRole('article', { name: 'one' }));
  fireEvent.click(one.getByRole('button', { name: '播放语音' }));
  expect(HTMLMediaElement.prototype.load).toHaveBeenCalled();
  fireEvent.click(one.getByRole('button', { name: '暂停语音' }));
  expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true);
  await act(async () => resolve(json({ segments: parts })));
  expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
  fireEvent.click(one.getByRole('button', { name: '播放语音' }));
  await waitFor(() => expect(paused).toBe(false));
  expect(count('/api/media/audio')).toBe(3);
});

it.each(['request', 'play', 'element'])(
  'shows an inline Chinese audio error on %s failure, then retries',
  async (failure) => {
    audioFail = failure === 'request';
    failPlay = failure === 'play';
    const view = render(<AudioHarness />);
    const one = within(screen.getByRole('article', { name: 'one' }));
    fireEvent.click(one.getByRole('button', { name: '播放语音' }));
    if (failure === 'element') {
      await waitFor(() => expect(paused).toBe(false));
      fireEvent.error(view.container.querySelector('audio')!);
    }
    expect(await one.findByRole('alert')).toHaveTextContent(/语音/);
    audioFail = false;
    failPlay = false;
    fireEvent.click(one.getByRole('button', { name: '播放语音' }));
    await waitFor(() => expect(paused).toBe(false));
    expect(one.queryByRole('alert')).not.toBeInTheDocument();
  },
);
it('never animates glow with reduced motion, but keeps a static speaking cue', async () => {
  preference.reduced = true;
  const view = render(<AudioHarness />);
  fireEvent.click(screen.getAllByRole('button', { name: '播放语音' })[0]);
  expect(await screen.findByRole('status', { name: '正在说话' })).toBeVisible();
  expect(view.container.querySelector('[data-portrait-glow]')).toBeNull();
});
it('prefers portrait, then a VRM still, then an initial, never a cartoon', async () => {
  const view = render(<ChatAvatar name="测试人" capabilities={caps} />);
  const image = screen.getByRole('img', { name: '测试人的肖像' });
  expect(
    screen.queryByRole('button', { name: 'VRM 静态头像' }),
  ).not.toBeInTheDocument();
  fireEvent.error(image);
  const model = await screen.findByRole('button', { name: 'VRM 静态头像' });
  expect(model).toHaveAttribute('data-still', 'true');
  fireEvent.click(model);
  expect(screen.getByRole('img', { name: '测试人的头像' })).toHaveTextContent(
    '测',
  );
  view.rerender(<ChatAvatar name="张三" capabilities={null} />);
  expect(screen.getByRole('img', { name: '张三的头像' })).toHaveTextContent(
    '张',
  );
  expect(view.container.querySelector('svg')).toBeNull();
});
const videoTurns: Turn[] = [
  {
    id: 'one',
    role: 'twin',
    content: answer.reply,
    reply: answer,
    timestamp: '2025-01-01T12:00:00Z',
  },
];
function VideoHarness({
  speaking = false,
  turns = videoTurns,
}: {
  speaking?: boolean;
  turns?: Turn[];
}) {
  const video = useReplyVideos(true, turns, '测试人');
  return (
    <>
      {turns.map((turn) => (
        <ReplyVideo
          key={turn.id}
          id={turn.id}
          answer={turn.reply!}
          portrait={caps.avatar_image!.url}
          state={video.videos[turn.id]}
          speaking={speaking}
          onRetry={() => video.retry(turn.id)}
          onError={() => video.invalidate(turn.id)}
        />
      ))}
    </>
  );
}
function video() {
  return <VideoHarness />;
}
it('starts video automatically once, renders accessible inline video and caches it for the session', async () => {
  vi.useFakeTimers();
  const view = render(video());
  await act(async () => {});
  expect(count('/api/media/video')).toBe(1);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByText('真人版生成中…')).toBeVisible();
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  jobStatus = 'done';
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  const player = screen.getByLabelText('回复的真人视频');
  for (const attr of ['controls', 'playsinline'])
    expect(player).toHaveAttribute(attr);
  expect(player).toHaveAttribute('preload', 'metadata');
  expect(player).toHaveAttribute('poster', caps.avatar_image!.url);
  expect(player).toHaveClass('w-full', 'max-w-[360px]', 'rounded-lg');
  expect(player).toHaveAccessibleDescription(answer.reply);
  expect(screen.getByText(answer.reply)).toHaveClass('sr-only');
  expect(screen.getByRole('link', { name: '保存' })).toHaveAttribute(
    'download',
    'twin-video.mp4',
  );
  expect(screen.getByRole('link', { name: '保存' })).toHaveAttribute(
    'href',
    `/api/media/video/${'a'.repeat(64)}.mp4`,
  );
  expect(screen.getByText('第 1 句回听与原文有出入')).toBeVisible();
  view.rerender(video());
  expect(count('/api/media/video')).toBe(1);
  view.unmount();
  render(video());
  expect(screen.getByLabelText('回复的真人视频')).toBeVisible();
  expect(count('/api/media/video')).toBe(1);
});
it.each(['submit', 'job', 'poll'])(
  'offers inline video retry on %s failure',
  async (failure) => {
    const originalFetch = fetchMock.getMockImplementation()!;
    submitFail = failure === 'submit';
    jobStatus = 'failed';
    if (failure === 'poll')
      fetchMock.mockImplementation(async (url: string) =>
        url === '/api/media/video'
          ? json({ job_id: 'video/1' })
          : json({ detail: '视频任务不存在' }, 404),
      );
    render(video());
    expect(await screen.findByRole('alert')).toHaveTextContent(
      '真人版生成失败',
    );
    expect(screen.queryByText('真人版生成中…')).not.toBeInTheDocument();
    submitFail = false;
    jobStatus = 'done';
    fetchMock.mockImplementation(originalFetch);
    fireEvent.click(screen.getByRole('button', { name: '重试生成视频' }));
    expect(await screen.findByLabelText('回复的真人视频')).toBeVisible();
    expect(count('/api/media/video')).toBe(failure === 'job' ? 1 : 2);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  },
);
it('evicts an unavailable video from cache and lets the owner retry inline', async () => {
  jobStatus = 'done';
  render(video());
  fireEvent.error(await screen.findByLabelText('回复的真人视频'));
  expect(screen.getByRole('alert')).toHaveTextContent('真人版生成失败 · 重试');
  expect(
    JSON.parse(sessionStorage.getItem('twin.reply-video:one')!).status,
  ).toBe('failed');
  fireEvent.click(screen.getByRole('button', { name: '重试生成视频' }));
  expect(await screen.findByLabelText('回复的真人视频')).toBeVisible();
  expect(count('/api/media/video')).toBe(2);
});

it('cancels video polling and in-flight requests on unmount', async () => {
  vi.useFakeTimers();
  const view = render(video());
  await act(async () => {});
  view.unmount();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });
  expect(count('/api/media/video/jobs/video%2F1')).toBe(1);
  expect(
    fetchMock.mock.calls
      .filter(([url]) => url !== '/api/media/video')
      .every(([, init]) => init.signal.aborted),
  ).toBe(true);
});
it('defers the completed video until voice ends, then keeps it visible on replay', async () => {
  jobStatus = 'done';
  const view = render(<VideoHarness speaking />);
  await waitFor(() => expect(count('/api/media/video/jobs/video%2F1')).toBe(1));
  expect(screen.queryByLabelText('回复的真人视频')).not.toBeInTheDocument();
  expect(screen.getByText('真人版生成中…')).toBeVisible();
  view.rerender(<VideoHarness speaking={false} />);
  expect(await screen.findByLabelText('回复的真人视频')).toBeVisible();
  expect(screen.getByText('真人版')).toBeVisible();
  view.rerender(<VideoHarness speaking />);
  expect(screen.getByLabelText('回复的真人视频')).toBeVisible();
  expect(count('/api/media/video')).toBe(1);
});

it('serializes background jobs and chooses the newest queued reply, skipping both forms of abstention', async () => {
  vi.useFakeTimers();
  const submitted: string[] = [];
  const states = new Map<string, string>();
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === '/api/media/video') {
      const text = JSON.parse(init!.body as string).answer.reply;
      submitted.push(text);
      return json({ job_id: text });
    }
    const id = url.split('/').at(-1)!;
    return json({
      status: states.get(id) ?? 'running',
      result: { file: `${'a'.repeat(64)}.mp4`, warnings: [], duration_s: 2 },
    });
  });
  const turn = (id: string): Turn => ({
    ...videoTurns[0],
    id,
    content: id,
    reply: { ...answer, reply: id },
  });
  const one = turn('one');
  const view = render(<VideoHarness turns={[one]} />);
  await act(async () => {});
  const turns = [
    one,
    turn('two'),
    turn('three'),
    { ...turn('abstain'), reply: { ...answer, abstain: true } },
    { ...turn('mode-only'), reply: { ...answer, mode: 'abstain' as const } },
  ];
  view.rerender(<VideoHarness turns={turns} />);
  await act(async () => {});
  expect(submitted).toEqual(['one']);
  states.set('one', 'done');
  await act(async () => vi.advanceTimersByTimeAsync(1000));
  expect(submitted).toEqual(['one', 'three']);
  states.set('three', 'failed');
  await act(async () => vi.advanceTimersByTimeAsync(1000));
  expect(submitted).toEqual(['one', 'three', 'two']);
  states.set('two', 'done');
  await act(async () => vi.advanceTimersByTimeAsync(1000));
  view.rerender(<VideoHarness turns={[...turns]} />);
  await act(async () => {});
  expect(submitted).toEqual(['one', 'three', 'two']);
});

it('resumes an existing running session job before submitting a newer reply', async () => {
  sessionStorage.setItem(
    'twin.reply-video:one',
    JSON.stringify({ status: 'generating', jobId: 'video/1' }),
  );
  vi.useFakeTimers();
  render(
    <VideoHarness turns={[...videoTurns, { ...videoTurns[0], id: 'two' }]} />,
  );
  await act(async () => {});
  expect(count('/api/media/video')).toBe(0);
  expect(count('/api/media/video/jobs/video%2F1')).toBe(1);
  jobStatus = 'done';
  await act(async () => vi.advanceTimersByTimeAsync(1000));
  expect(count('/api/media/video')).toBe(1);
});

it('submits only once across StrictMode effects and rerenders', async () => {
  jobStatus = 'done';
  const view = render(
    <StrictMode>
      <VideoHarness />
    </StrictMode>,
  );
  expect(await screen.findByLabelText('回复的真人视频')).toBeVisible();
  view.rerender(
    <StrictMode>
      <VideoHarness turns={[...videoTurns]} />
    </StrictMode>,
  );
  expect(count('/api/media/video')).toBe(1);
});

it('retains a pending submission across unmount rather than starting a second GPU job', async () => {
  let resolve!: (response: Response) => void;
  const original = fetchMock.getMockImplementation() as (
    url: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetchMock.mockImplementation((url: string, init?: RequestInit) =>
    url === '/api/media/video'
      ? new Promise<Response>((done) => {
          resolve = done;
        })
      : original(url, init),
  );
  const view = render(video());
  await waitFor(() => expect(count('/api/media/video')).toBe(1));
  view.unmount();
  render(video());
  await act(async () => resolve(json({ job_id: 'video/1' })));
  expect(count('/api/media/video')).toBe(1);
  expect(count('/api/media/video/jobs/video%2F1')).toBe(1);
});

it.each(['network', 'abort', 500, 502, 503, 408, 429])(
  'keeps generating after a transient %s polling error, then shows the video without a failure flash',
  async (failure) => {
    vi.useFakeTimers();
    sessionStorage.setItem(
      'twin.reply-video:one',
      JSON.stringify({ status: 'generating', jobId: 'video/1' }),
    );
    const saved = vi.spyOn(Storage.prototype, 'setItem');
    if (failure === 'network')
      fetchMock.mockRejectedValueOnce(new TypeError('offline'));
    else if (failure === 'abort')
      fetchMock.mockRejectedValueOnce(
        new DOMException('background', 'AbortError'),
      );
    else fetchMock.mockResolvedValueOnce(json({}, failure as number));
    jobStatus = 'done';
    render(video());
    await act(async () => {});
    expect(screen.getByText('真人版生成中…')).toBeVisible();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(JSON.parse(sessionStorage.getItem('twin.reply-video:one')!)).toEqual(
      {
        status: 'generating',
        jobId: 'video/1',
      },
    );
    await act(async () => vi.advanceTimersByTimeAsync(999));
    expect(count('/api/media/video/jobs/video%2F1')).toBe(1);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(screen.getByLabelText('回复的真人视频')).toBeVisible();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(count('/api/media/video')).toBe(0);
    expect(
      saved.mock.calls.some(
        ([, value]) => JSON.parse(value).status === 'failed',
      ),
    ).toBe(false);
  },
);

it('backs off polling at 1s, 2s, 4s and at most 8s, then resets after a successful poll', async () => {
  vi.useFakeTimers();
  sessionStorage.setItem(
    'twin.reply-video:one',
    JSON.stringify({ status: 'generating', jobId: 'video/1' }),
  );
  fetchMock.mockRejectedValue(new TypeError('offline'));
  render(video());
  await act(async () => {});
  let polls = 1;
  for (const delay of [1000, 2000, 4000, 8000, 8000]) {
    await act(async () => vi.advanceTimersByTimeAsync(delay - 1));
    expect(fetchMock).toHaveBeenCalledTimes(polls);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(fetchMock).toHaveBeenCalledTimes(++polls);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  }
  fetchMock.mockResolvedValueOnce(json({ status: 'running' }));
  await act(async () => vi.advanceTimersByTimeAsync(8000));
  expect(fetchMock).toHaveBeenCalledTimes(++polls);
  await act(async () => vi.advanceTimersByTimeAsync(1000));
  expect(fetchMock).toHaveBeenCalledTimes(++polls);
  await act(async () => vi.advanceTimersByTimeAsync(1000));
  expect(fetchMock).toHaveBeenCalledTimes(++polls);
});

it('does not let a failed session job block the next generating reply', async () => {
  sessionStorage.setItem(
    'twin.reply-video:one',
    JSON.stringify({ status: 'failed', jobId: 'old-job' }),
  );
  jobStatus = 'done';
  render(
    <VideoHarness turns={[...videoTurns, { ...videoTurns[0], id: 'two' }]} />,
  );
  expect(await screen.findByLabelText('回复的真人视频')).toBeVisible();
  expect(screen.getByRole('alert')).toHaveTextContent('真人版生成失败');
  expect(count('/api/media/video')).toBe(1);
  expect(count('/api/media/video/jobs/old-job')).toBe(0);
});

it.each(['failed', 'unknown'])(
  'rechecks a failed record before replacing its %s job',
  async (status) => {
    sessionStorage.setItem(
      'twin.reply-video:one',
      JSON.stringify({ status: 'failed', jobId: 'old-job' }),
    );
    const original = fetchMock.getMockImplementation() as (
      url: string,
      init?: RequestInit,
    ) => Promise<Response>;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) =>
      url.endsWith('/old-job')
        ? json({ status: 'failed' }, status === 'unknown' ? 404 : 200)
        : original(url, init),
    );
    jobStatus = 'done';
    render(video());
    fireEvent.click(screen.getByRole('button', { name: '重试生成视频' }));
    expect(await screen.findByLabelText('回复的真人视频')).toBeVisible();
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/media/video/jobs/old-job',
      '/api/media/video',
      '/api/media/video/jobs/video%2F1',
    ]);
  },
);

it('reuses a finished job when retrying a persisted failed record', async () => {
  sessionStorage.setItem(
    'twin.reply-video:one',
    JSON.stringify({ status: 'failed', jobId: 'video/1' }),
  );
  jobStatus = 'done';
  render(video());
  fireEvent.click(screen.getByRole('button', { name: '重试生成视频' }));
  expect(await screen.findByLabelText('回复的真人视频')).toBeVisible();
  expect(count('/api/media/video')).toBe(0);
  expect(count('/api/media/video/jobs/video%2F1')).toBe(1);
});

it.each(['running', 'backoff', 'in-flight'])(
  'polls immediately on visibility resume during %s',
  async (phase) => {
    vi.useFakeTimers();
    const visibility = vi.spyOn(document, 'visibilityState', 'get');
    visibility.mockReturnValue('visible');
    sessionStorage.setItem(
      'twin.reply-video:one',
      JSON.stringify({ status: 'generating', jobId: 'video/1' }),
    );
    if (phase === 'backoff')
      fetchMock.mockRejectedValue(new TypeError('offline'));
    if (phase === 'in-flight')
      fetchMock.mockImplementationOnce(
        (_url: string, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init!.signal!.addEventListener('abort', () =>
              reject(new DOMException('cancelled', 'AbortError')),
            );
          }),
      );
    render(video());
    await act(async () => {});
    if (phase === 'backoff') {
      await act(async () => vi.advanceTimersByTimeAsync(3000));
      expect(count('/api/media/video/jobs/video%2F1')).toBe(3);
    }
    const polls = count('/api/media/video/jobs/video%2F1');
    visibility.mockReturnValue('hidden');
    fireEvent(document, new Event('visibilitychange'));
    await act(async () => {});
    expect(count('/api/media/video/jobs/video%2F1')).toBe(polls);
    jobStatus = 'done';
    fetchMock.mockResolvedValue(
      json({
        status: 'done',
        result: { file: `${'a'.repeat(64)}.mp4`, duration_s: 6, warnings: [] },
      }),
    );
    visibility.mockReturnValue('visible');
    fireEvent(document, new Event('visibilitychange'));
    await act(async () => {});
    expect(count('/api/media/video/jobs/video%2F1')).toBe(polls + 1);
    expect(screen.getByLabelText('回复的真人视频')).toBeVisible();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  },
);

it('has no legacy playback dialog or panel references anywhere in frontend source', () => {
  const forbidden = [
    ['Playback', 'Dialog'].join(''),
    ['RemoteVideo', 'Panel'].join(''),
    'features/' + 'playback/',
  ];
  const walk = (directory: string) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) walk(path);
      else if (/\.(tsx?|css)$/.test(entry.name)) {
        const source = readFileSync(path, 'utf8');
        for (const term of forbidden) expect(source, path).not.toContain(term);
      }
    }
  };
  walk('src');
});
