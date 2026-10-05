import { act, renderHook } from '@testing-library/react';
import { useReducedMotion } from 'motion/react';
import { describe, expect, it, vi } from 'vitest';
import { crossfade, springs, useMotionPreset } from '../design/motion';
import { shouldDismissDrag } from '../components/motion';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: vi.fn(),
}));

it.each([
  [101, 0, true],
  [-101, 0, true],
  [50, 650, true],
  [-50, -650, true],
  [50, 500, false],
  [5, 900, false],
  [50, -650, false],
  [100, 0, false],
])(
  'drag threshold: offset %s velocity %s resolves %s',
  (offset, velocity, result) => {
    expect(shouldDismissDrag(offset as number, velocity as number)).toBe(
      result,
    );
  },
);

describe('motion presets', () => {
  it.each(['snappy', 'gentle', 'bouncy', 'layout'] as const)(
    'uses crossfade only for reduced %s',
    (name) => {
      vi.mocked(useReducedMotion).mockReturnValue(true);
      const { result } = renderHook(() => useMotionPreset(name));
      expect(result.current.reduced).toBe(true);
      expect(result.current.transition).toEqual(crossfade);
      expect(result.current.transition).not.toHaveProperty('stiffness');
    },
  );
  it('reacts to live preference changes and removes the media listener', () => {
    vi.mocked(useReducedMotion).mockReturnValue(false);
    let change: (event: MediaQueryListEvent) => void = () => {};
    const remove = vi.fn();
    vi.stubGlobal('matchMedia', () => ({
      matches: false,
      addEventListener: (_type: string, listener: typeof change) => {
        change = listener;
      },
      removeEventListener: remove,
    }));
    const { result, unmount } = renderHook(() => useMotionPreset('layout'));
    act(() => change({ matches: true } as MediaQueryListEvent));
    expect(result.current.reduced).toBe(true);
    expect(result.current.transition).toEqual(crossfade);
    act(() => change({ matches: false } as MediaQueryListEvent));
    expect(result.current.transition).toEqual(springs.layout);
    unmount();
    expect(remove).toHaveBeenCalledWith('change', change);
  });
  it('uses springs when motion is allowed', () => {
    vi.mocked(useReducedMotion).mockReturnValue(false);
    const { result } = renderHook(() => useMotionPreset('snappy'));
    expect(result.current.transition).toEqual(springs.snappy);
  });
});
