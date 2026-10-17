import { act, render, screen } from '@testing-library/react';
import { animate, useReducedMotion } from 'motion/react';
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
  PresenceRing,
  StreamText,
  TypingIndicator,
  segmentText,
  streamUnitDelay,
  usePresence,
  type PresenceState,
} from '../components/ui';

vi.mock('motion/react', async (original) => {
  const motion = await original<typeof import('motion/react')>();
  return {
    ...motion,
    useReducedMotion: vi.fn(),
    animate: vi.fn(motion.animate),
  };
});

const css = readFileSync('src/design/tokens.css', 'utf8');

function Ring({
  state,
  level = 0,
  variant,
}: {
  state: PresenceState;
  level?: number;
  variant?: 'glow' | 'ripple';
}) {
  const presence = usePresence(state, level);
  return (
    <div data-testid="intensity" data-value={presence.intensity.get()}>
      <PresenceRing presence={presence} variant={variant} />
    </div>
  );
}

beforeEach(() => vi.mocked(useReducedMotion).mockReturnValue(false));
afterEach(() => vi.useRealTimers());

it('spreads two rings while speaking and holds one still ring while thinking or listening', () => {
  const view = render(<Ring state="speaking" level={3} variant="ripple" />);
  expect(view.container.querySelectorAll('.presence-ripple')).toHaveLength(2);
  expect(
    view.container.querySelector('.presence-ripple[data-still]'),
  ).toBeNull();
  for (const state of ['thinking', 'listening'] as const) {
    view.rerender(<Ring state={state} variant="ripple" />);
    const rings = view.container.querySelectorAll('.presence-ripple');
    expect(rings).toHaveLength(1);
    expect(rings[0]).toHaveAttribute('data-still', '');
  }
  view.rerender(<Ring state="idle" variant="ripple" />);
  expect(view.container.querySelector('.presence-ripple')).toBeNull();
});

it('marks the glow with the state and the voice level while speaking', () => {
  const view = render(<Ring state="speaking" level={7} />);
  const glow = view.container.querySelector('[data-portrait-glow]');
  expect(glow).toHaveAttribute('data-presence', 'speaking');
  expect(glow).toHaveAttribute('data-glow-level', '3');
  expect(glow).toHaveAttribute('aria-hidden', 'true');
  view.rerender(<Ring state="thinking" level={2} />);
  expect(view.container.querySelector('[data-portrait-glow]')).toHaveAttribute(
    'data-glow-level',
    '0',
  );
});

it('drifts while thinking, each move easing slowly over a random wait, and settles when idle again', () => {
  vi.useFakeTimers();
  const random = vi.spyOn(Math, 'random').mockReturnValue(0);
  function Probe({ state }: { state: PresenceState }) {
    usePresence(state);
    return null;
  }
  const moves = () =>
    vi.mocked(animate).mock.calls.map((call) => [call[1], call[2]]);
  vi.mocked(animate).mockClear();
  const view = render(<Probe state="thinking" />);
  expect(moves()).toEqual([[0.12, { duration: 1.2, ease: 'easeInOut' }]]);
  random.mockReturnValue(1);
  act(() => vi.advanceTimersByTime(1200));
  expect(moves().at(-1)).toEqual([0.38, { duration: 2.6, ease: 'easeInOut' }]);
  // The next move waits as long as this one eases, so no two moves keep a beat.
  act(() => vi.advanceTimersByTime(2500));
  expect(moves()).toHaveLength(2);
  act(() => vi.advanceTimersByTime(100));
  expect(moves()).toHaveLength(3);
  view.rerender(<Probe state="idle" />);
  expect(moves().at(-1)?.[0]).toBe(0);
  act(() => vi.advanceTimersByTime(10_000));
  expect(moves()).toHaveLength(4);
  random.mockRestore();
});

it('names the state with a still dot under reduced motion and leaves the stage to say it', () => {
  vi.mocked(useReducedMotion).mockReturnValue(true);
  const view = render(<Ring state="thinking" />);
  expect(screen.getByRole('status', { name: '正在思考' })).toBeVisible();
  expect(view.container.querySelector('[data-portrait-glow]')).toBeNull();
  view.rerender(<Ring state="speaking" variant="ripple" />);
  expect(screen.queryByRole('status')).toBeNull();
  expect(view.container.querySelector('.presence-ripple')).toBeNull();
  view.rerender(<Ring state="idle" />);
  expect(screen.queryByRole('status')).toBeNull();
});

it('keeps the ripple still and the sheen off for reduced motion in CSS', () => {
  expect(css).toMatch(
    /\.presence-ripple\s*\{[^}]*inset: -5px;[^}]*border: 2px solid var\(--canvas\);[^}]*animation: presence-ripple 1\.6s ease-out infinite/s,
  );
  expect(css).toMatch(
    /\.presence-ripple\[data-still\]\s*\{[^}]*animation: none;[^}]*opacity: var\(--ring-opacity\)/s,
  );
  expect(css).toMatch(
    /prefers-reduced-motion: reduce\)\s*\{[^@]*\.typing-indicator\s*\{[^}]*animation: none;[^}]*color: var\(--text-secondary\)/s,
  );
  expect(css).toMatch(
    /prefers-reduced-motion: reduce\)\s*\{\s*\.presence-ripple,[^}]*animation: none/s,
  );
});

it('says "思考中…" once, as words a screen reader reads, with no inline styles', () => {
  render(<TypingIndicator />);
  const status = screen.getByRole('status');
  expect(status.textContent).toBe('思考中…');
  expect(status).toHaveClass('typing-indicator');
  expect(status.querySelector('*')).toBeNull();
  render(<TypingIndicator text="正在做…" />);
  expect(screen.getByText('正在做…')).toHaveAttribute('role', 'status');
});

it('reveals text word by word without movement, and gives screen readers the whole text once', () => {
  const text = '我会先听大家的意见。 Hello world!';
  const { container } = render(<StreamText text={text} />);
  const units = container.querySelectorAll('[data-stream-unit]');
  expect(units.length).toBeGreaterThan(4);
  expect(container.querySelector('.sr-only')?.textContent).toBe(text);
  expect(container.querySelector('[data-stream-text]')).toHaveAttribute(
    'aria-hidden',
    'true',
  );
  expect(container.querySelector('[data-stream-text]')?.textContent).toBe(text);
  for (const unit of units)
    expect((unit as HTMLElement).style.transform).not.toMatch(/translate/);
  expect(streamUnitDelay(1000) * 999 + 0.16).toBeLessThanOrEqual(1.200001);
});

it('shows long text and reduced-motion text whole at once', () => {
  const long = 'word '.repeat(100);
  const { container, rerender } = render(<StreamText text={long} />);
  expect(container.querySelector('[data-stream-unit]')).toBeNull();
  expect(container.textContent).toBe(long);
  vi.mocked(useReducedMotion).mockReturnValue(true);
  rerender(<StreamText key="reduced" text="一句话" />);
  expect(container.querySelector('.sr-only, [data-stream-unit]')).toBeNull();
  expect(container.textContent).toBe('一句话');
});

it('segments Chinese words, and falls back to CJK characters and Latin runs', () => {
  expect(segmentText('中文句子').length).toBeGreaterThan(1);
  vi.stubGlobal('Intl', { ...Intl, Segmenter: undefined });
  expect(segmentText('中文 hello world 日本語')).toEqual([
    '中',
    '文',
    ' ',
    'hello',
    ' ',
    'world',
    ' ',
    '日',
    '本',
    '語',
  ]);
  vi.unstubAllGlobals();
});
