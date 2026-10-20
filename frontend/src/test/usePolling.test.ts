import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { usePolling } from '../lib/usePolling';

let hidden = false;
beforeEach(() => {
  vi.useFakeTimers();
  hidden = false;
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden);
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const show = (value: boolean) => {
  hidden = !value;
  document.dispatchEvent(new Event('visibilitychange'));
};

it('polls only while the page is in view, and loads at once on coming back', () => {
  const load = vi.fn();
  renderHook(() => usePolling(load, 15000));
  vi.advanceTimersByTime(30000);
  expect(load).toHaveBeenCalledTimes(2);
  show(false);
  vi.advanceTimersByTime(120000);
  expect(load).toHaveBeenCalledTimes(2);
  show(true);
  expect(load).toHaveBeenCalledTimes(3);
  vi.advanceTimersByTime(15000);
  expect(load).toHaveBeenCalledTimes(4);
});

it('does not poll at all with no interval, nor start in a background tab', () => {
  const load = vi.fn();
  const { rerender } = renderHook(({ every }) => usePolling(load, every), {
    initialProps: { every: 0 },
  });
  vi.advanceTimersByTime(60000);
  expect(load).not.toHaveBeenCalled();
  hidden = true;
  rerender({ every: 3000 });
  vi.advanceTimersByTime(60000);
  expect(load).not.toHaveBeenCalled();
});
