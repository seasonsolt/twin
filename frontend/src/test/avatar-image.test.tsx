import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { AvatarPreview } from '../features/avatar/AvatarPreview';
import type { Capabilities } from '../features/avatar/types';

const preference = vi.hoisted(() => ({ reduced: false }));
vi.mock('../design/motion', async (original) => ({
  ...(await original<typeof import('../design/motion')>()),
  useMotionPreset: () => ({ reduced: preference.reduced }),
}));
const capabilities: Capabilities = {
  available: false,
  backend: null,
  avatar_image: { url: '/api/media/avatar-image' },
  avatar: {
    schema_version: 1,
    avatar_id: 'default',
    palette: {},
    mouth_states: 4,
    stylized: true,
  },
};
beforeEach(() => {
  preference.reduced = false;
});

it('prefers a static portrait to the preset and falls back on image error', () => {
  const view = render(<AvatarPreview capabilities={capabilities} />);
  const image = screen.getByRole('img', { name: '肖像形象' });
  expect(image).toHaveAttribute('src', '/api/media/avatar-image');
  expect(image).toHaveClass('object-cover', 'object-[50%_30%]');
  expect(screen.queryByRole('note')).not.toBeInTheDocument();
  expect(
    screen.queryByRole('img', { name: '风格化插画' }),
  ).not.toBeInTheDocument();
  fireEvent.error(image);
  expect(screen.getByRole('img', { name: '风格化插画' })).toBeVisible();
  view.rerender(
    <AvatarPreview capabilities={{ ...capabilities, avatar_image: null }} />,
  );
  expect(screen.getByRole('img', { name: '风格化插画' })).toBeVisible();
});

it('spring-smooths glow intensity from the lipsync level and fades it when not speaking', async () => {
  const view = render(
    <AvatarPreview capabilities={capabilities} mouth={0} speaking />,
  );
  const glow = view.container.querySelector<HTMLElement>(
    '[data-portrait-glow]',
  )!;
  const opacity = () => Number(glow.style.opacity);
  await waitFor(() => expect(opacity()).toBeCloseTo(0.25, 2));
  view.rerender(
    <AvatarPreview capabilities={capabilities} mouth={3} speaking />,
  );
  expect(opacity()).toBeLessThan(0.9);
  await waitFor(() => expect(opacity()).toBeGreaterThan(0.3));
  expect(opacity()).toBeLessThan(0.9);
  await waitFor(() => expect(opacity()).toBeCloseTo(0.9, 2));
  view.rerender(
    <AvatarPreview capabilities={capabilities} mouth={1} speaking />,
  );
  await waitFor(() => expect(opacity()).toBeCloseTo(0.25 + 0.65 / 3, 2));
  view.rerender(<AvatarPreview capabilities={capabilities} mouth={3} />);
  await waitFor(() => expect(opacity()).toBeCloseTo(0, 2));
  expect(screen.getByRole('img')).not.toHaveAttribute('data-mouth-level');
});

it('uses only a static speaking dot for reduced motion', () => {
  preference.reduced = true;
  const view = render(
    <AvatarPreview capabilities={capabilities} mouth={3} speaking />,
  );
  expect(view.container.querySelector('[data-portrait-glow]')).toBeNull();
  expect(screen.getByRole('status', { name: '正在说话' })).toBeVisible();
  view.rerender(<AvatarPreview capabilities={capabilities} mouth={3} />);
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
});
