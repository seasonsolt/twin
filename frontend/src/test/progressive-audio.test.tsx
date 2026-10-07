import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useReplyAudio } from '../features/chat/useReplyAudio';
import type { ChatReply } from '../features/chat/types';

const answer: ChatReply = {
  reply: '一。二。三。四。',
  confidence: 1,
  abstain: false,
  abstain_reason: '',
  citations: [],
  retrieved_ids: [],
  mode: 'grounded',
};
const json = (data: unknown) =>
  new Response(JSON.stringify(data), {
    headers: { 'Content-Type': 'application/json' },
  });
function Harness({ reply = answer }: { reply?: ChatReply }) {
  const audio = useReplyAudio(true);
  return (
    <>
      <audio ref={audio.audioRef} />
      <button onClick={() => audio.toggle('one', reply, '本人')}>
        {audio.playing ? '暂停' : '播放'}
      </button>
      <span data-testid="speaking">{String(audio.speaking)}</span>
      <span data-testid="loading">{String(audio.loading)}</span>
      <span data-testid="level">{audio.level}</span>
      {audio.errors.one && <p role="alert">{audio.errors.one}</p>}
    </>
  );
}
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it('bounds synthesis, schedules gapless buffers in script order, and falls back to live RMS when lipsync runs out or later segments lack levels', async () => {
  let now = 0;
  const sources: {
    buffer: AudioBuffer | null;
    onended: (() => void) | null;
    start: ReturnType<typeof vi.fn>;
    stop: ReturnType<typeof vi.fn>;
    connect: ReturnType<typeof vi.fn>;
    disconnect: ReturnType<typeof vi.fn>;
  }[] = [];
  let amplitude = 0.05;
  const analyser = {
    fftSize: 0,
    connect: vi.fn(),
    disconnect: vi.fn(),
    getFloatTimeDomainData: vi.fn((samples: Float32Array) => {
      samples.forEach((_, index) => {
        samples[index] = index % 2 ? amplitude : -amplitude;
      });
    }),
  };
  let sampleFrame!: FrameRequestCallback;
  const tick = () => act(() => sampleFrame(0));
  const resume = vi.fn(async () => {});
  const suspend = vi.fn(async () => {});
  const close = vi.fn(async () => {});
  vi.stubGlobal(
    'AudioContext',
    class {
      destination = {};
      get currentTime() {
        return now;
      }
      resume = resume;
      suspend = suspend;
      close = close;
      decodeAudioData = async () => ({ duration: 2 }) as AudioBuffer;
      createAnalyser = () => analyser;
      createBufferSource() {
        const source = {
          buffer: null,
          onended: null,
          start: vi.fn(),
          stop: vi.fn(),
          connect: vi.fn(),
          disconnect: vi.fn(),
        };
        sources.push(source);
        return source;
      }
    },
  );
  vi.stubGlobal(
    'requestAnimationFrame',
    vi.fn((callback: FrameRequestCallback) => {
      sampleFrame = callback;
      return 1;
    }),
  );
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
  const pending = new Map<number, (response: Response) => void>();
  const requested: number[] = [];
  const fetchMock = vi.fn((url: string, init: RequestInit) => {
    if (url === '/api/media/audio') {
      const index = JSON.parse(init.body as string).segments[0];
      requested.push(index);
      return new Promise<Response>((resolve) => pending.set(index, resolve));
    }
    return Promise.resolve(new Response(new Uint8Array([1, 2, 3])));
  });
  vi.stubGlobal('fetch', fetchMock);
  const resolve = async (index: number) => {
    await act(async () =>
      pending.get(index)!(
        json({
          segment_count: 4,
          segments: [
            {
              index,
              url: `/api/media/audio/${String(index).repeat(64)}.wav`,
              duration_s: 2,
              lipsync:
                index === 0
                  ? { fps: 2, levels: [0, 2] }
                  : index === 1
                    ? { fps: 2 }
                    : null,
            },
          ],
        }),
      ),
    );
  };
  const view = render(<Harness />);
  fireEvent.click(screen.getByText('播放'));
  expect(requested).toEqual([0]);
  expect(resume).toHaveBeenCalledTimes(1);
  await resolve(0);
  expect(sources).toHaveLength(1);
  expect(sources[0].start).toHaveBeenCalledWith(0);
  expect(analyser.connect).toHaveBeenCalledWith({});
  expect(sources[0].connect).toHaveBeenCalledWith(analyser);
  expect(screen.getByTestId('level')).toHaveTextContent('0');
  now = 0.5;
  tick();
  expect(screen.getByTestId('level')).toHaveTextContent('2');
  now = 1.5;
  tick();
  expect(Number(screen.getByTestId('level').textContent)).toBeCloseTo(0.6);
  expect(screen.getByTestId('speaking')).toHaveTextContent('true');
  expect(requested).toEqual([0, 1, 2]);
  await resolve(2);
  expect(requested).toEqual([0, 1, 2]);
  expect(sources).toHaveLength(1);
  await resolve(1);
  expect(sources).toHaveLength(3);
  expect(sources[1].start).toHaveBeenCalledWith(2);
  expect(sources[2].start).toHaveBeenCalledWith(4);
  now = 2;
  act(() => sources[0].onended!());
  expect(requested).toEqual([0, 1, 2, 3]);
  await resolve(3);
  expect(sources[3].start).toHaveBeenCalledWith(6);
  fireEvent.click(screen.getByText('暂停'));
  expect(suspend).toHaveBeenCalled();
  await act(async () => fireEvent.click(screen.getByText('播放')));
  expect(sources).toHaveLength(4);
  expect(requested).toEqual([0, 1, 2, 3]);
  for (let index = 1; index < 4; index++) {
    now = (index + 1) * 2;
    act(() => sources[index].onended!());
    if (index < 2) {
      for (const sample of [0.05, 0.2, 0.4, 0]) {
        amplitude = sample;
        tick();
        expect(Number(screen.getByTestId('level').textContent)).toBeCloseTo(
          Math.min(3, sample * 12),
        );
      }
    }
  }
  expect(screen.getByText('播放')).toBeVisible();
  expect(screen.getByTestId('speaking')).toHaveTextContent('false');
  await act(async () => fireEvent.click(screen.getByText('播放')));
  expect(sources).toHaveLength(7);
  expect(sources[4].start).toHaveBeenCalledWith(8);
  expect(fetchMock).toHaveBeenCalledTimes(8);
  view.unmount();
  expect(close).toHaveBeenCalled();
  expect(analyser.disconnect).toHaveBeenCalled();
  expect(sources[4].stop).toHaveBeenCalled();
});

it('keeps a two-segment lookahead while Web Audio waits for a late segment, then continues in order', async () => {
  let now = 0;
  const sources: {
    buffer: AudioBuffer | null;
    onended: (() => void) | null;
    start: ReturnType<typeof vi.fn>;
    connect: ReturnType<typeof vi.fn>;
    disconnect: ReturnType<typeof vi.fn>;
    stop: ReturnType<typeof vi.fn>;
  }[] = [];
  vi.stubGlobal(
    'AudioContext',
    class {
      destination = {};
      get currentTime() {
        return now;
      }
      resume = async () => {};
      suspend = async () => {};
      close = async () => {};
      decodeAudioData = async () => ({ duration: 2 }) as AudioBuffer;
      createAnalyser = () => ({
        fftSize: 0,
        connect: vi.fn(),
        disconnect: vi.fn(),
        getFloatTimeDomainData: vi.fn(),
      });
      createBufferSource() {
        const source = {
          buffer: null,
          onended: null,
          start: vi.fn(),
          connect: vi.fn(),
          disconnect: vi.fn(),
          stop: vi.fn(),
        };
        sources.push(source);
        return source;
      }
    },
  );
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
  const pending = new Map<number, (response: Response) => void>();
  const requested: number[] = [];
  let inFlight = 0;
  let maximum = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init: RequestInit) => {
      if (url !== '/api/media/audio')
        return Promise.resolve(new Response(new Uint8Array([1])));
      const index = JSON.parse(init.body as string).segments[0];
      requested.push(index);
      maximum = Math.max(maximum, ++inFlight);
      return new Promise<Response>((resolve) => pending.set(index, resolve));
    }),
  );
  const resolve = async (index: number) => {
    inFlight--;
    await act(async () =>
      pending.get(index)!(
        json({
          segment_count: 6,
          segments: [
            {
              index,
              url: `/api/media/audio/${String(index).repeat(64)}.wav`,
              duration_s: 2,
            },
          ],
        }),
      ),
    );
  };
  render(<Harness />);
  fireEvent.click(screen.getByText('播放'));
  await resolve(0);
  expect(requested).toEqual([0, 1, 2]);
  await resolve(2);
  expect(requested).toEqual([0, 1, 2]);
  expect(sources).toHaveLength(1);
  now = 2;
  act(() => sources[0].onended!());
  expect(screen.getByTestId('loading')).toHaveTextContent('true');
  expect(screen.getByTestId('speaking')).toHaveTextContent('false');
  expect(screen.getByTestId('level')).toHaveTextContent('0');
  expect(requested).toEqual([0, 1, 2, 3]);
  await resolve(3);
  expect(sources).toHaveLength(1);
  expect(requested).toEqual([0, 1, 2, 3]);
  now = 3;
  await resolve(1);
  expect(sources).toHaveLength(4);
  expect(sources.map((source) => source.start.mock.calls[0][0])).toEqual([
    0, 3, 5, 7,
  ]);
  expect(screen.getByTestId('loading')).toHaveTextContent('false');
  expect(screen.getByTestId('speaking')).toHaveTextContent('true');
  now = 5;
  act(() => sources[1].onended!());
  expect(requested).toEqual([0, 1, 2, 3, 4]);
  await resolve(4);
  now = 7;
  act(() => sources[2].onended!());
  expect(requested).toEqual([0, 1, 2, 3, 4, 5]);
  await resolve(5);
  for (let index = 3; index < 6; index++) {
    now = 3 + index * 2;
    act(() => sources[index].onended!());
  }
  expect(maximum).toBe(2);
  expect(sources.map((source) => source.start.mock.calls[0][0])).toEqual([
    0, 3, 5, 7, 9, 11,
  ]);
  expect(sources.every((source) => !source.stop.mock.calls.length)).toBe(true);
  expect(screen.getByText('播放')).toBeVisible();
  expect(screen.getByTestId('loading')).toHaveTextContent('false');
});

it('waits only for the missing next segment and resumes immediately when it arrives', async () => {
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(
    async function (this: HTMLMediaElement) {
      this.dispatchEvent(new Event('playing'));
    },
  );
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  let remaining!: (response: Response) => void;
  vi.stubGlobal(
    'fetch',
    vi.fn((_url: string, init: RequestInit) => {
      const index = JSON.parse(init.body as string).segments[0];
      if (index === 1)
        return new Promise<Response>((resolve) => {
          remaining = resolve;
        });
      return Promise.resolve(
        json({
          segment_count: 2,
          segments: [
            { index, url: '/first.wav', duration_s: 2, lipsync: null },
          ],
        }),
      );
    }),
  );
  const view = render(<Harness />);
  fireEvent.click(screen.getByText('播放'));
  await waitFor(() =>
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1),
  );
  fireEvent.ended(view.container.querySelector('audio')!);
  expect(screen.getByText('暂停')).toBeVisible();
  expect(screen.getByTestId('loading')).toHaveTextContent('true');
  await act(async () =>
    remaining(
      json({
        segment_count: 2,
        segments: [
          { index: 1, url: '/next.wav', duration_s: 2, lipsync: null },
        ],
      }),
    ),
  );
  expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(2);
  expect(view.container.querySelector('audio')).toHaveAttribute(
    'src',
    '/next.wav',
  );
  expect(screen.getByTestId('loading')).toHaveTextContent('false');
});

it.each([
  { ...answer, abstain: true },
  { ...answer, mode: 'abstain' as const },
])('never requests speech for abstention', (reply) => {
  const fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  render(<Harness reply={reply} />);
  fireEvent.click(screen.getByText('播放'));
  expect(fetchMock).not.toHaveBeenCalled();
});
