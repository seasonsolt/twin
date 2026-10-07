import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { readFileSync } from 'node:fs';
import { beforeEach, expect, it, vi } from 'vitest';
import { ChatStage } from '../features/chat/ChatStage';
import { ChatAvatar } from '../features/chat/ChatAvatar';
import type { Capabilities } from '../features/avatar/types';
import type { Turn } from '../features/chat/types';
import type { ReplyVideoState } from '../features/chat/useReplyVideos';

const preference = vi.hoisted(() => ({ reduced: false, width: 390 }));
vi.mock('../design/motion', async (original) => ({
  ...(await original<typeof import('../design/motion')>()),
  useMotionPreset: () => ({ reduced: preference.reduced }),
}));
vi.mock('../lib/useMobile', () => ({
  useMobile: () => preference.width < 768,
  useDesktop: () => preference.width >= 1200,
}));
const caps: Capabilities = {
  available: true,
  backend: 'local',
  avatar_image: { url: '/api/media/avatar-image' },
  video: { available: true },
};
const turn: Turn = {
  id: 'reply',
  role: 'twin',
  content: '你好。',
  timestamp: '2025-01-01T12:00:00Z',
  reply: {
    reply: '你好。',
    confidence: 1,
    abstain: false,
    abstain_reason: '',
    mode: 'grounded',
    citations: [],
    retrieved_ids: [],
  },
};
const props = {
  name: '本人',
  capabilities: caps,
  turn,
  videoPlaying: false,
  voiceCaption: '你好。',
  level: 0,
  speaking: true,
  onToggle: vi.fn(),
  onVideoPlaying: vi.fn(),
  onVideoError: vi.fn(),
  onClear: vi.fn(),
};
const css = readFileSync('src/design/tokens.css', 'utf8');
beforeEach(() => {
  preference.reduced = false;
  preference.width = 390;
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
});

it.each([390, 768, 1200])(
  'renders two unclipped ground-colour rings and spring-driven breathing at %spx',
  async (width) => {
    preference.width = width;
    const view = render(
      <MemoryRouter>
        <ChatStage {...props} />
      </MemoryRouter>,
    );
    const wrapper =
      view.container.querySelector<HTMLElement>('.stage-speaking')!;
    const circle = view.container.querySelector<HTMLElement>('.stage-circle')!;
    const rings = wrapper.querySelectorAll('.stage-speaking-ring');
    expect(rings).toHaveLength(2);
    rings.forEach((ring) => {
      expect(ring.parentElement).toBe(wrapper);
      expect(circle.contains(ring)).toBe(false);
    });
    expect(circle.querySelector('[data-portrait-glow]')).toBeNull();
    const expansion = () =>
      Number(wrapper.style.getPropertyValue('--ring-expansion'));
    const opacity = () =>
      Number(wrapper.style.getPropertyValue('--ring-opacity'));
    await waitFor(() => expect(expansion()).toBeCloseTo(1.12, 2));
    await waitFor(() => expect(opacity()).toBeCloseTo(0.4125, 2));
    expect(circle.style.transform).toContain('scale(');
    view.rerender(
      <MemoryRouter>
        <ChatStage {...props} level={3} />
      </MemoryRouter>,
    );
    expect(expansion()).toBeLessThan(1.24);
    await waitFor(() => expect(expansion()).toBeCloseTo(1.24, 2));
    await waitFor(() => expect(opacity()).toBeCloseTo(0.75, 2));
    await waitFor(() =>
      expect(
        Number(circle.style.transform.match(/scale\(([^)]+)\)/)?.[1]),
      ).toBeCloseTo(1.03, 2),
    );
    fireEvent.focus(
      document.body.appendChild(
        Object.assign(document.createElement('textarea'), {
          className: 'chat-composer',
        }),
      ),
    );
    expect(screen.getByRole('banner')).toHaveAttribute(
      'data-collapsed',
      String(width < 1200),
    );
    expect(wrapper.querySelectorAll('.stage-speaking-ring')).toHaveLength(2);
    document.querySelector('textarea.chat-composer')?.remove();
    view.rerender(
      <MemoryRouter>
        <ChatStage {...props} speaking={false} />
      </MemoryRouter>,
    );
    expect(wrapper.querySelector('.stage-speaking-ring')).toBeNull();
    await waitFor(() => expect(circle.style.transform).toBe('none'));
    expect(css).toMatch(/\.stage-speaking\s*\{[^}]*overflow: visible/s);
    expect(css).toMatch(
      /\.stage-speaking-ring\s*\{[^}]*inset: -5px;[^}]*border: 2px solid var\(--canvas\);[^}]*animation: stage-speaking-ring 1\.6s ease-out infinite/s,
    );
    expect(css).toContain('animation-delay: -0.8s');
  },
);

it('uses a static speaking chip with no rings or breathing for reduced motion, including live changes', async () => {
  const view = render(
    <MemoryRouter>
      <ChatStage {...props} level={3} />
    </MemoryRouter>,
  );
  preference.reduced = true;
  view.rerender(
    <MemoryRouter>
      <ChatStage {...props} level={3} />
    </MemoryRouter>,
  );
  expect(view.container.querySelector('.stage-speaking-ring')).toBeNull();
  expect(screen.getByRole('status', { name: '正在说话' })).toHaveTextContent(
    '正在说',
  );
  expect(
    view.container.querySelector<HTMLElement>('.stage-circle')!.style.transform,
  ).toBe('none');
  view.rerender(
    <MemoryRouter>
      <ChatStage {...props} speaking={false} />
    </MemoryRouter>,
  );
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
});

it('shows the current reply video status below the circle and keeps the portrait until video playback', () => {
  const generating: ReplyVideoState = { status: 'generating' };
  const ready: ReplyVideoState = {
    status: 'done',
    result: { file: `${'a'.repeat(64)}.mp4`, duration_s: 6, warnings: [] },
  };
  const view = render(
    <MemoryRouter>
      <ChatStage {...props} videoState={generating} />
    </MemoryRouter>,
  );
  const circle = view.container.querySelector('.stage-circle')!;
  const status = screen.getByText('真人视频生成中');
  expect(circle.contains(status)).toBe(false);
  expect(status.querySelector('.stage-video-spinner')).not.toBeNull();
  view.rerender(
    <MemoryRouter>
      <ChatStage {...props} speaking={false} videoState={generating} />
    </MemoryRouter>,
  );
  expect(status).toBeVisible();
  fireEvent.focus(
    document.body.appendChild(
      Object.assign(document.createElement('textarea'), {
        className: 'chat-composer',
      }),
    ),
  );
  expect(screen.getByRole('banner')).toHaveAttribute('data-collapsed', 'true');
  expect(status).toBeVisible();
  document.querySelector('textarea.chat-composer')?.remove();
  view.rerender(
    <MemoryRouter>
      <ChatStage {...props} videoState={ready} />
    </MemoryRouter>,
  );
  expect(screen.getByText('真人视频已就绪 · 点头像播放')).toBeVisible();
  expect(screen.getByRole('img', { name: '本人的肖像' })).toBeVisible();
  expect(screen.queryByLabelText('舞台真人视频')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '展开舞台' }));
  expect(props.onToggle).toHaveBeenCalled();
  view.rerender(
    <MemoryRouter>
      <ChatStage {...props} speaking={false} videoState={ready} videoPlaying />
    </MemoryRouter>,
  );
  expect(screen.getByLabelText('舞台真人视频')).toHaveAttribute(
    'src',
    `/api/media/video/${'a'.repeat(64)}.mp4?persona=default`,
  );
  expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
  expect(css).toMatch(
    /\.stage-speaking-chip,\s*\.stage-video-status\s*\{[^}]*background: var\(--text-primary\);[^}]*color: var\(--canvas\)/s,
  );
});

it.each([
  {
    capabilities: { ...caps, video: { available: false } },
    videoState: { status: 'generating' },
  },
  { capabilities: caps, videoState: { status: 'failed' } },
  { capabilities: caps, videoState: undefined },
  {
    capabilities: caps,
    videoState: {
      status: 'done',
      result: { file: 'invalid.mp4', duration_s: 1, warnings: [] },
    },
  },
] as { capabilities: Capabilities; videoState?: ReplyVideoState }[])(
  'does not show video status for unavailable, failed or invalid video',
  (state) => {
    const view = render(
      <MemoryRouter>
        <ChatStage {...props} {...state} />
      </MemoryRouter>,
    );
    expect(view.container.querySelector('.stage-video-status')).toBeNull();
  },
);

it('keeps the accent glow for non-stage avatars on light backgrounds', () => {
  const view = render(
    <ChatAvatar name="本人" capabilities={caps} speaking level={3} />,
  );
  expect(view.container.querySelector('[data-portrait-glow]')).toHaveClass(
    'border-accent',
  );
  expect(view.container.querySelector('[data-portrait-glow]')).toHaveAttribute(
    'data-glow-level',
    '3',
  );
  expect(view.container.querySelector('.stage-speaking-ring')).toBeNull();
});
