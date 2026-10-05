import { afterEach, expect, it, vi } from 'vitest';
import { startStatusPolling, useStatus } from '../stores/status';

let stop: (() => void) | undefined;
afterEach(() => {
  stop?.();
  vi.useRealTimers();
  vi.restoreAllMocks();
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
