import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Avatar } from '../features/avatar/Avatar';
import { presets } from '../features/avatar/presets';
import { illustratedPortrait } from '../features/profile/graph/portrait';

const preference = vi.hoisted(() => ({ reduced: false }));
vi.mock('../design/motion', async (original) => ({
  ...(await original<typeof import('../design/motion')>()),
  useMotionPreset: () => ({ reduced: preference.reduced }),
}));
beforeEach(() => {
  preference.reduced = false;
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it.each(Object.entries(presets))(
  'renders %s with intact eyes, resting mouth and square circle crop',
  (id, preset) => {
    const view = render(<Avatar preset={id} blinking={false} />);
    const svg = screen.getByRole('img', { name: `插画形象：${preset.name}` });
    expect(svg).toHaveAttribute('viewBox', '0 0 220 220');
    expect(svg).toHaveAttribute('data-mouth-level', '0');
    expect(view.container.querySelector('.eyes')).toHaveStyle({
      transform: 'scaleY(1)',
    });
    expect(view.container.querySelector('[data-mouth] .mouth')).not.toBeNull();
    expect(svg.parentElement).toHaveClass(
      'aspect-square',
      'rounded-full',
      'overflow-hidden',
    );
    const rasterSource = decodeURIComponent(
      illustratedPortrait(id).split(',')[1],
    );
    expect(rasterSource).toContain(`data-preset="${id}"`);
    expect(rasterSource).toContain('viewBox="0 0 220 220"');
    expect(rasterSource).toContain('class="eyes"');
  },
);

it.each(Object.entries(presets))(
  'squashes the whole %s eye group for exactly 140ms and opens its mouth progressively',
  (id) => {
    vi.useFakeTimers();
    vi.spyOn(Math, 'random').mockReturnValue(0);
    const view = render(<Avatar preset={id} />);
    const eyes = () => view.container.querySelector('.eyes');
    act(() => vi.advanceTimersByTime(3000));
    expect(eyes()).toHaveStyle({ transform: 'scaleY(0.1)' });
    expect(eyes()?.getAttribute('style')).toContain('transform-origin: 110px');
    act(() => vi.advanceTimersByTime(139));
    expect(eyes()).toHaveStyle({ transform: 'scaleY(0.1)' });
    act(() => vi.advanceTimersByTime(1));
    expect(eyes()).toHaveStyle({ transform: 'scaleY(1)' });
    let previous = 0;
    for (const level of [1, 2, 3]) {
      view.rerender(<Avatar preset={id} mouthLevel={level} />);
      const mouth = view.container.querySelector('ellipse.mouth')!;
      expect(Number(mouth.getAttribute('ry'))).toBeGreaterThan(previous);
      previous = Number(mouth.getAttribute('ry'));
      expect(mouth).toHaveAttribute('cx', '110');
      expect(view.container.querySelector('[data-mouth] > g')).toHaveAttribute(
        'visibility',
        'hidden',
      );
    }
    expect(
      view.container.querySelector('[data-mouth] ellipse[fill="#E8826B"]'),
    ).not.toBeNull();
    view.rerender(<Avatar preset={id} mouthLevel={0} />);
    expect(view.container.querySelector('[data-mouth] > g')).toHaveAttribute(
      'visibility',
      'visible',
    );
    expect(view.container.querySelector('ellipse.mouth')).toBeNull();
  },
);

it('accepts legacy specs and disables blinking/clamps motion for reduced motion', () => {
  vi.useFakeTimers();
  preference.reduced = true;
  const view = render(<Avatar preset="ink" mouthLevel={3} />);
  expect(screen.getByRole('img', { name: '插画形象：栗' })).toHaveAttribute(
    'data-mouth-level',
    '1',
  );
  act(() => vi.advanceTimersByTime(10000));
  expect(view.container.querySelector('.eyes')).toHaveStyle({
    transform: 'scaleY(1)',
  });
  preference.reduced = false;
  view.rerender(<Avatar preset="bun" blinking={false} mouthLevel={99} />);
  expect(screen.getByRole('img')).toHaveAttribute('data-mouth-level', '3');
  act(() => vi.advanceTimersByTime(10000));
  expect(view.container.querySelector('.eyes')).toHaveStyle({
    transform: 'scaleY(1)',
  });
});
