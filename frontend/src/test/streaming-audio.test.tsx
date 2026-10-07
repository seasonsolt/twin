import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import {
  AudioFrameParser,
  StreamingAudio,
  readAudioStream,
  type StreamingView,
} from '../features/chat/StreamingAudio';
import { useReplyAudio } from '../features/chat/useReplyAudio';
import type { ChatReply } from '../features/chat/types';

function frame(type: number, payload: object | Uint8Array) {
  const bytes =
    payload instanceof Uint8Array
      ? payload
      : new TextEncoder().encode(JSON.stringify(payload));
  const result = new Uint8Array(bytes.length + 5);
  result[0] = type;
  new DataView(result.buffer).setUint32(1, bytes.length);
  result.set(bytes, 5);
  return result;
}
const header = () => frame(1, { sample_rate: 24000, segments: 2 });
const caption = (segment: number, text: string) =>
  frame(1, { segment, caption: text });
const pcm = (seconds: number) =>
  frame(2, new Uint8Array(seconds * 24000 * 2).fill(32));
const end = () => frame(3, { duration_s: 0.4 });
const response = (chunks: Uint8Array[]) =>
  new Response(
    new ReadableStream({
      start(controller) {
        chunks.forEach((chunk) => controller.enqueue(chunk));
        controller.close();
      },
    }),
    { headers: { 'Content-Type': 'application/octet-stream' } },
  );

function sourceNode() {
  return {
    buffer: null as AudioBuffer | null,
    onended: null as (() => void) | null,
    start: vi.fn(),
    stop: vi.fn(),
    connect: vi.fn(),
    disconnect: vi.fn(),
  };
}
class Context extends EventTarget {
  state: AudioContextState = 'running';
  currentTime = 0;
  destination = {};
  sources: ReturnType<typeof sourceNode>[] = [];
  analyser = {
    fftSize: 512,
    connect: vi.fn(),
    disconnect: vi.fn(),
    getFloatTimeDomainData: (values: Float32Array) => values.fill(0.2),
  };
  resume = vi.fn(async () => {
    this.state = 'running';
    this.dispatchEvent(new Event('statechange'));
  });
  suspend = vi.fn(async () => {
    this.state = 'suspended';
    this.dispatchEvent(new Event('statechange'));
  });
  close = vi.fn(async () => {});
  createAnalyser = () => this.analyser;
  createBuffer(_channels: number, count: number, rate: number) {
    const data = new Float32Array(count);
    return {
      duration: count / rate,
      getChannelData: () => data,
    } as unknown as AudioBuffer;
  }
  createBufferSource() {
    const source = sourceNode();
    this.sources.push(source);
    return source;
  }
  decodeAudioData = async () => this.createBuffer(1, 4800, 24000);
}
function clock() {
  let callback!: FrameRequestCallback;
  vi.stubGlobal(
    'requestAnimationFrame',
    vi.fn((fn: FrameRequestCallback) => {
      callback = fn;
      return 1;
    }),
  );
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  return () => callback(0);
}
afterEach(() => vi.restoreAllMocks());

it('parses every arbitrary chunk boundary including split headers, JSON, and PCM samples', () => {
  const chunks = [header(), caption(0, '第一段中文'), pcm(0.2), end()];
  const data = new Uint8Array(
    chunks.reduce((sum, chunk) => sum + chunk.length, 0),
  );
  let offset = 0;
  for (const chunk of chunks) {
    data.set(chunk, offset);
    offset += chunk.length;
  }
  const expected = new AudioFrameParser().push(data);
  for (const size of [1, 2, 3, 4, 5, 7, 31, 4096]) {
    const parser = new AudioFrameParser();
    const actual = [];
    for (let index = 0; index < data.length; index += size)
      actual.push(...parser.push(data.slice(index, index + size)));
    parser.finish();
    expect(actual).toEqual(expected);
  }
  const truncated = new AudioFrameParser();
  truncated.push(data.slice(0, -1));
  expect(() => truncated.finish()).toThrow('不完整');
  expect(() =>
    new AudioFrameParser().push(new Uint8Array([9, 0, 0, 0, 0])),
  ).toThrow();
});

it('buffers 150ms, schedules contiguous PCM, derives RMS and captions by playback time, and completes', () => {
  const tick = clock();
  const context = new Context();
  let view!: StreamingView;
  const complete = vi.fn();
  const player = new StreamingAudio(
    context as unknown as AudioContext,
    (value) => {
      view = value;
    },
    complete,
  );
  const parser = new AudioFrameParser();
  const accept = (data: Uint8Array) =>
    parser.push(data).forEach((item) => player.accept(item));
  accept(header());
  accept(caption(0, '第一段'));
  accept(pcm(0.1));
  expect(context.sources).toHaveLength(0);
  expect(view.loading).toBe(true);
  accept(pcm(0.1));
  accept(caption(1, '第二段'));
  accept(pcm(0.2));
  accept(end());
  expect(
    context.sources.map((source) => source.start.mock.calls[0][0]),
  ).toEqual([0.015, 0.115, 0.21500000000000002]);
  expect(context.sources[0].buffer!.getChannelData(0)[0]).toBeCloseTo(
    0x2020 / 32768,
  );
  context.currentTime = 0.1;
  tick();
  expect(view.caption).toBe('第一段');
  expect(view.level).toBeCloseTo(2.4);
  expect(view.speaking).toBe(true);
  context.currentTime = 0.23;
  tick();
  expect(view.caption).toBe('第二段');
  expect(view.progress).toBeCloseTo(0.215 / 0.4);
  context.currentTime = 0.415;
  for (const source of context.sources) source.onended?.();
  expect(complete).toHaveBeenCalledTimes(1);
  expect(context.analyser.disconnect).toHaveBeenCalled();
});

it('freezes progress on underrun, waits for another jitter buffer, and resumes without skipping audio', () => {
  const tick = clock();
  const context = new Context();
  let view!: StreamingView;
  const player = new StreamingAudio(
    context as unknown as AudioContext,
    (value) => {
      view = value;
    },
    vi.fn(),
  );
  const accept = (data: Uint8Array) =>
    new AudioFrameParser().push(data).forEach((item) => player.accept(item));
  accept(header());
  accept(caption(0, '第一段'));
  accept(pcm(0.2));
  context.currentTime = 0.215;
  context.sources[0].onended!();
  tick();
  expect(view.loading).toBe(true);
  expect(view.speaking).toBe(false);
  const progress = view.progress;
  context.currentTime = 10;
  tick();
  expect(view.progress).toBe(progress);
  accept(caption(1, '第二段'));
  accept(pcm(0.1));
  tick();
  expect(context.sources).toHaveLength(1);
  accept(pcm(0.1));
  expect(context.sources[1].start).toHaveBeenCalledWith(10.015);
  expect(context.sources[2].start).toHaveBeenCalledWith(10.115);
  context.currentTime = 10.065;
  tick();
  expect(view.loading).toBe(false);
  expect(view.caption).toBe('第二段');
  player.stop();
  expect(context.sources[1].stop).toHaveBeenCalled();
});

it('handles suspended gesture contexts, pause/resume, and truncated/error streams', async () => {
  clock();
  const context = new Context();
  context.state = 'suspended';
  let view!: StreamingView;
  const player = new StreamingAudio(
    context as unknown as AudioContext,
    (value) => {
      view = value;
    },
    vi.fn(),
  );
  await readAudioStream(
    response([header(), caption(0, '内容'), pcm(0.2), end()]),
    player,
  );
  expect(context.sources).toHaveLength(0);
  expect(view.loading).toBe(true);
  const resumed = player.resume();
  expect(context.resume).toHaveBeenCalledTimes(1);
  await resumed;
  expect(context.sources).toHaveLength(1);
  await player.pause();
  expect(view.speaking).toBe(false);
  await player.resume();
  expect(context.sources).toHaveLength(1);
  player.stop();
  const missing = new StreamingAudio(
    context as unknown as AudioContext,
    vi.fn(),
    vi.fn(),
  );
  await expect(readAudioStream(response([header()]), missing)).rejects.toThrow(
    '不完整',
  );
  await expect(
    readAudioStream(response([frame(4, { detail: '合成失败' })]), missing),
  ).rejects.toThrow('合成失败');
  missing.stop();
});

const answer: ChatReply = {
  reply: '回答。',
  citations: [],
  confidence: 1,
  abstain: false,
  abstain_reason: '',
  retrieved_ids: [],
  mode: 'grounded',
};
function Harness({ reply = answer }: { reply?: ChatReply }) {
  const audio = useReplyAudio(true);
  return (
    <>
      <audio ref={audio.audioRef} />
      <button onClick={() => audio.unlock()}>发送</button>
      <button onClick={() => audio.toggle('one', reply, '本人')}>播放一</button>
      <button onClick={() => audio.toggle('two', reply, '本人')}>播放二</button>
      <span data-testid="playing">{String(audio.playing)}</span>
      <span data-testid="loading">{String(audio.loading)}</span>
    </>
  );
}

it.each(['grounded', 'abstain'] as const)(
  'unlocks, streams %s replies, pauses/resumes, and aborts on reply/persona switch',
  async (mode) => {
    const reply = { ...answer, mode, abstain: mode === 'abstain' };
    const tick = clock();
    const contexts: Context[] = [];
    vi.stubGlobal(
      'AudioContext',
      class extends Context {
        constructor() {
          super();
          contexts.push(this);
        }
      },
    );
    vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
      void url;
      void init;
      return new Response(
        new ReadableStream<Uint8Array>({
          start(value) {
            controller = value;
          },
        }),
        { headers: { 'Content-Type': 'application/octet-stream' } },
      );
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<Harness reply={reply} />);
    fireEvent.click(screen.getByText('发送'));
    expect(contexts).toHaveLength(1);
    expect(contexts[0].resume).toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('播放一'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][0]).toBe('/api/media/audio/stream');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get('X-Twin')).toBe('1');
    expect(JSON.parse(init.body as string).answer).toEqual(reply);
    await act(async () => {
      controller.enqueue(header());
      controller.enqueue(caption(0, '内容'));
      controller.enqueue(pcm(0.2));
    });
    contexts[0].currentTime = 0.05;
    act(() => tick());
    expect(screen.getByTestId('loading')).toHaveTextContent('false');
    fireEvent.click(screen.getByText('播放一'));
    expect(screen.getByTestId('playing')).toHaveTextContent('false');
    fireEvent.click(screen.getByText('播放一'));
    expect(screen.getByTestId('playing')).toHaveTextContent('true');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText('播放二'));
    expect(init.signal?.aborted).toBe(true);
    expect(contexts[0].sources[0].stop).toHaveBeenCalled();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const second = fetchMock.mock.calls[1][1] as RequestInit;
    act(() => window.dispatchEvent(new Event('twin-persona-switch')));
    expect(second.signal?.aborted).toBe(true);
  },
);

it.each(['network', '404', '500', 'error-frame'])(
  'automatically falls back to segmented playback before audio on %s',
  async (failure) => {
    clock();
    vi.stubGlobal('AudioContext', Context);
    vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('/stream')) {
        if (failure === 'network') throw new TypeError('network');
        if (failure === 'error-frame')
          return response([header(), frame(4, { detail: '失败' })]);
        return new Response('{}', { status: Number(failure) });
      }
      if (url === '/api/media/audio')
        return new Response(
          JSON.stringify({
            segment_count: 1,
            segments: [
              {
                index: 0,
                url: `/api/media/audio/${'a'.repeat(64)}.wav`,
                duration_s: 0.2,
              },
            ],
          }),
          { headers: { 'Content-Type': 'application/json' } },
        );
      return new Response(new Uint8Array([1, 2]));
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<Harness />);
    fireEvent.click(screen.getByText('播放一'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[1][0]).toBe('/api/media/audio');
    expect(screen.getByTestId('playing')).toHaveTextContent('true');
  },
);
