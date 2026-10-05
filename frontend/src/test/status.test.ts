import { afterEach, expect, it, vi } from 'vitest';
import { startStatusPolling, useStatus, type Status } from '../stores/status';

const status: Status = {
  target_name: '测试人',
  counts: { sources: 1, items: 2 },
  llm: { provider: 'mock', model: 'mock-model' },
  embed: { provider: 'local' },
  egress: [
    {
      kind: 'llm',
      provider: 'mock',
      host: 'example.test',
      external: true,
      declared: true,
    },
  ],
  labels: {
    explicit: 'API 标识',
    disclaimer: 'API 页脚',
    chat_notice: 'API 聊天说明',
  },
};

let stop: (() => void) | undefined;
afterEach(() => {
  stop?.();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it('loads initial status even when hidden, then pauses periodic refresh until visible', async () => {
  vi.useFakeTimers();
  let hidden = true;
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden);
  const previous = useStatus.getState();
  useStatus.setState({ data: null, error: null });
  const fetcher = vi
    .fn()
    .mockImplementation(async () => new Response(JSON.stringify(status)));
  vi.stubGlobal('fetch', fetcher);
  try {
    stop = startStatusPolling();
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(useStatus.getState().data).toEqual(status);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(fetcher).toHaveBeenCalledTimes(1);
    hidden = false;
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetcher).toHaveBeenCalledTimes(3);
    stop();
    await vi.advanceTimersByTimeAsync(20_000);
    expect(fetcher).toHaveBeenCalledTimes(3);
  } finally {
    useStatus.setState({ data: previous.data, error: previous.error });
  }
});

it('does not cancel an in-flight initial load when the tab becomes hidden', async () => {
  vi.useFakeTimers();
  let hidden = false;
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden);
  const previous = useStatus.getState();
  useStatus.setState({ data: null, error: null });
  let resolve!: (response: Response) => void;
  const fetcher = vi.fn().mockImplementation(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  vi.stubGlobal('fetch', fetcher);
  try {
    stop = startStatusPolling();
    const signal = fetcher.mock.calls[0][1].signal as AbortSignal;
    hidden = true;
    document.dispatchEvent(new Event('visibilitychange'));
    expect(signal.aborted).toBe(false);
    resolve(new Response(JSON.stringify(status)));
    await vi.advanceTimersByTimeAsync(0);
    expect(useStatus.getState().data).toEqual(status);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(fetcher).toHaveBeenCalledTimes(1);
  } finally {
    stop?.();
    useStatus.setState({ data: previous.data, error: previous.error });
  }
});

it('refreshes every 10 seconds while visible, pauses while hidden, and cleans up', async () => {
  vi.useFakeTimers();
  let hidden = false;
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden);
  const refresh = vi.fn().mockResolvedValue(undefined);
  const original = useStatus.getState().refresh;
  useStatus.setState({ refresh });
  try {
    stop = startStatusPolling();
    await vi.advanceTimersByTimeAsync(0);
    expect(refresh).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(refresh).toHaveBeenCalledTimes(2);
    hidden = true;
    document.dispatchEvent(new Event('visibilitychange'));
    expect(refresh.mock.calls[1][0].aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(refresh).toHaveBeenCalledTimes(2);
    hidden = false;
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(0);
    expect(refresh).toHaveBeenCalledTimes(3);
    stop();
    await vi.advanceTimersByTimeAsync(20_000);
    expect(refresh).toHaveBeenCalledTimes(3);
  } finally {
    useStatus.setState({ refresh: original });
  }
});
