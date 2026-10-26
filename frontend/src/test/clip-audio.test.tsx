import { StrictMode } from 'react';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AudioPlayer, ClipButton } from '../components/ui';

interface Playback {
  element: HTMLMediaElement;
  resolve: () => void;
  reject: (error: Error) => void;
}
let attempts: Playback[];
let paused: WeakMap<HTMLMediaElement, boolean>;
let ended: WeakMap<HTMLMediaElement, boolean>;
beforeEach(() => {
  attempts = [];
  paused = new WeakMap();
  ended = new WeakMap();
  vi.spyOn(HTMLMediaElement.prototype, 'ended', 'get').mockImplementation(
    function (this: HTMLMediaElement) {
      return ended.get(this) ?? false;
    },
  );
  vi.spyOn(HTMLMediaElement.prototype, 'paused', 'get').mockImplementation(
    function (this: HTMLMediaElement) {
      return paused.get(this) ?? true;
    },
  );
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function (
    this: HTMLMediaElement,
  ) {
    paused.set(this, false);
    ended.set(this, false);
    this.dispatchEvent(new Event('play'));
    return new Promise<void>((resolve, reject) => {
      attempts.push({ element: this, resolve, reject });
    });
  });
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function (
    this: HTMLMediaElement,
  ) {
    paused.set(this, true);
    this.dispatchEvent(new Event('pause'));
  });
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(function (
    this: HTMLMediaElement,
  ) {
    paused.set(this, true);
    ended.set(this, false);
    Object.defineProperty(this, 'error', { configurable: true, value: null });
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const begin = async (attempt: Playback) => {
  await act(async () => {
    fireEvent.playing(attempt.element);
    attempt.resolve();
  });
};

it('reports a rejected play request and retries the same clip in place', async () => {
  render(<ClipButton src="/clip.wav" label="听片段" />);
  await userEvent.click(screen.getByRole('button', { name: '听片段' }));
  await act(async () =>
    attempts[0].reject(new DOMException('blocked', 'NotAllowedError')),
  );
  expect(screen.getByRole('alert')).toHaveTextContent('无法试听');
  const retry = screen.getByRole('button', { name: '重试听片段' });
  expect(retry).toHaveAttribute('aria-pressed', 'false');
  await userEvent.click(retry);
  await begin(attempts[1]);
  expect(screen.queryByRole('alert')).toBeNull();
  expect(screen.getByRole('button', { name: '暂停听片段' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
});

it.each([404, 503])(
  'recovers a media network failure (%i) without reloading the task',
  async (status) => {
    const { container } = render(<ClipButton src="/clip.wav" label="听片段" />);
    await userEvent.click(screen.getByRole('button', { name: '听片段' }));
    await begin(attempts[0]);
    const audio = container.querySelector('audio')!;
    // Native audio exposes a MediaError, not the HTTP response body/status.
    Object.defineProperty(audio, 'error', {
      configurable: true,
      value: { code: status === 404 ? 4 : 2 },
    });
    fireEvent.error(audio);
    expect(screen.getByRole('alert')).toHaveTextContent('无法试听');
    expect(screen.getByRole('button', { name: '重试听片段' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    await userEvent.click(screen.getByRole('button', { name: '重试听片段' }));
    expect(audio.load).toHaveBeenCalled();
    await begin(attempts[1]);
    expect(screen.queryByRole('alert')).toBeNull();
  },
);

it('changes source without letting the old play promise clear the new playing state', async () => {
  const shown = render(<ClipButton src="/old.wav" label="听片段" />);
  await userEvent.click(screen.getByRole('button', { name: '听片段' }));
  const old = attempts[0];
  shown.rerender(<ClipButton src="/current.wav" label="听片段" />);
  expect(old.element.paused).toBe(true);
  expect(shown.container.querySelector('audio')).not.toBe(old.element);
  expect(shown.container.querySelector('audio')?.getAttribute('src')).toBe(
    '/current.wav',
  );
  expect(screen.getByRole('button', { name: '听片段' })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
  await userEvent.click(screen.getByRole('button', { name: '听片段' }));
  await begin(attempts[1]);
  await act(async () =>
    old.reject(new DOMException('old request stopped', 'AbortError')),
  );
  expect(screen.getByRole('button', { name: '暂停听片段' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  fireEvent.error(old.element);
  expect(screen.queryByRole('alert')).toBeNull();
});

it('stops a pending request and ignores its late playing event', async () => {
  render(<ClipButton src="/clip.wav" label="听片段" />);
  await userEvent.click(screen.getByRole('button', { name: '听片段' }));
  expect(screen.getByRole('button', { name: '停止听片段' })).toHaveAttribute(
    'aria-busy',
    'true',
  );
  await userEvent.click(screen.getByRole('button', { name: '停止听片段' }));
  await begin(attempts[0]);
  expect(attempts[0].element.paused).toBe(true);
  expect(screen.getByRole('button', { name: '听片段' })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
  expect(screen.queryByRole('alert')).toBeNull();
});

it('stops audio when its task closes and never reports its late failure in another task', async () => {
  const shown = render(<ClipButton src="/old.wav" label="听片段" />);
  await userEvent.click(screen.getByRole('button', { name: '听片段' }));
  shown.unmount();
  expect(attempts[0].element.paused).toBe(true);
  render(<ClipButton src="/next.wav" label="听新片段" />);
  await act(async () => attempts[0].reject(new Error('old network failure')));
  expect(screen.queryByRole('alert')).toBeNull();
  expect(screen.getByRole('button', { name: '听新片段' })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
});

it('plays only one clip and prevents a stopped clip from taking playback back', async () => {
  render(
    <>
      <ClipButton src="/one.wav" label="听第一段" />
      <ClipButton src="/two.wav" label="听第二段" />
    </>,
  );
  await userEvent.click(screen.getByRole('button', { name: '听第一段' }));
  await userEvent.click(screen.getByRole('button', { name: '听第二段' }));
  expect(attempts[0].element.paused).toBe(true);
  await begin(attempts[1]);
  await begin(attempts[0]);
  expect(attempts[0].element.paused).toBe(true);
  expect(screen.getByRole('button', { name: '听第一段' })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
  expect(screen.getByRole('button', { name: '暂停听第二段' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
});

it('coordinates native main audio with a comparison clip and lets native audio retry', async () => {
  const { container } = render(
    <>
      <AudioPlayer src="/main.wav" aria-label="主试听" />
      <ClipButton src="/comparison.wav" label="听对照" />
    </>,
  );
  const main = container.querySelector('audio')!;
  paused.set(main, false);
  fireEvent.play(main);
  fireEvent.playing(main);
  await userEvent.click(screen.getByRole('button', { name: '听对照' }));
  expect(main.paused).toBe(true);
  await begin(attempts[0]);
  paused.set(main, false);
  fireEvent.play(main);
  fireEvent.playing(main);
  expect(attempts[0].element.paused).toBe(true);
  Object.defineProperty(main, 'error', {
    configurable: true,
    value: { code: 2 },
  });
  fireEvent.error(main);
  expect(screen.getByRole('alert')).toHaveTextContent('无法试听');
  await userEvent.click(screen.getByRole('button', { name: '重试主试听' }));
  await begin(attempts[1]);
  expect(screen.queryByRole('alert')).toBeNull();
});

it('ignores the stopped clip media failure while the next clip plays', async () => {
  render(
    <>
      <ClipButton src="/one.wav" label="听第一段" />
      <ClipButton src="/two.wav" label="听第二段" />
    </>,
  );
  await userEvent.click(screen.getByRole('button', { name: '听第一段' }));
  await userEvent.click(screen.getByRole('button', { name: '听第二段' }));
  await begin(attempts[1]);
  fireEvent.error(attempts[0].element);
  await act(async () => attempts[0].reject(new Error('stopped request')));
  expect(screen.queryByRole('alert')).toBeNull();
  expect(screen.getByRole('button', { name: '暂停听第二段' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
});

it('does not let a queued native play event reclaim a paused main player', async () => {
  const { container } = render(
    <>
      <AudioPlayer src="/main.wav" aria-label="主试听" />
      <ClipButton src="/comparison.wav" label="听对照" />
    </>,
  );
  const main = container.querySelector('audio')!;
  paused.set(main, false);
  fireEvent.play(main);
  await userEvent.click(screen.getByRole('button', { name: '听对照' }));
  await begin(attempts[0]);
  expect(main.paused).toBe(true);
  fireEvent.play(main);
  fireEvent.playing(main);
  expect(main.paused).toBe(true);
  expect(screen.getByRole('button', { name: '暂停听对照' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
});

it('ignores a queued pause event from a cancelled request after the same clip was started again', async () => {
  render(<ClipButton src="/clip.wav" label="听片段" />);
  await userEvent.click(screen.getByRole('button', { name: '听片段' }));
  await userEvent.click(screen.getByRole('button', { name: '停止听片段' }));
  await userEvent.click(screen.getByRole('button', { name: '听片段' }));
  const current = attempts[1];
  expect(current.element.paused).toBe(false);
  fireEvent.pause(current.element);
  await begin(current);
  expect(screen.getByRole('button', { name: '暂停听片段' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await act(async () =>
    attempts[0].reject(new DOMException('old abort', 'AbortError')),
  );
  expect(screen.queryByRole('alert')).toBeNull();
});

it.each(['clip', 'native'] as const)(
  'restores the %s audio resource after StrictMode replays effect cleanup',
  async (kind) => {
    const shown = render(
      <StrictMode>
        {kind === 'clip' ? (
          <ClipButton src="/strict.wav" label="听片段" />
        ) : (
          <AudioPlayer src="/strict.wav" aria-label="主试听" />
        )}
      </StrictMode>,
    );
    const audio = shown.container.querySelector('audio')!;
    expect(audio.getAttribute('src')).toBe('/strict.wav');
    if (kind === 'clip') {
      await userEvent.click(screen.getByRole('button', { name: '听片段' }));
      await begin(attempts[0]);
      expect(
        screen.getByRole('button', { name: '暂停听片段' }),
      ).toHaveAttribute('aria-pressed', 'true');
    } else {
      paused.set(audio, false);
      fireEvent.play(audio);
      fireEvent.playing(audio);
      expect(audio.paused).toBe(false);
    }
    expect(audio.getAttribute('src')).toBe('/strict.wav');
  },
);

it('ignores an old ended event after a finished clip was replayed on the same element', async () => {
  render(
    <>
      <ClipButton src="/one.wav" label="听第一段" />
      <ClipButton src="/two.wav" label="听第二段" />
    </>,
  );
  await userEvent.click(screen.getByRole('button', { name: '听第一段' }));
  await begin(attempts[0]);
  const audio = attempts[0].element;
  paused.set(audio, true);
  ended.set(audio, true);
  fireEvent.ended(audio);
  expect(screen.getByRole('button', { name: '听第一段' })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
  await userEvent.click(screen.getByRole('button', { name: '听第一段' }));
  await begin(attempts[1]);
  expect(attempts[1].element).toBe(audio);
  expect(audio.ended).toBe(false);
  expect(audio.paused).toBe(false);
  fireEvent.ended(audio);
  expect(screen.getByRole('button', { name: '暂停听第一段' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await userEvent.click(screen.getByRole('button', { name: '听第二段' }));
  expect(audio.paused).toBe(true);
});

it('ignores an old error event after load cleared the error and the same clip plays again', async () => {
  render(<ClipButton src="/clip.wav" label="听片段" />);
  await userEvent.click(screen.getByRole('button', { name: '听片段' }));
  await begin(attempts[0]);
  const audio = attempts[0].element;
  Object.defineProperty(audio, 'error', {
    configurable: true,
    value: { code: 2 },
  });
  fireEvent.error(audio);
  expect(screen.getByRole('alert')).toHaveTextContent('无法试听');
  await userEvent.click(screen.getByRole('button', { name: '重试听片段' }));
  expect(audio.error).toBeNull();
  await begin(attempts[1]);
  expect(attempts[1].element).toBe(audio);
  fireEvent.error(audio);
  expect(screen.queryByRole('alert')).toBeNull();
  expect(audio.paused).toBe(false);
  expect(screen.getByRole('button', { name: '暂停听片段' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
});

it.each([undefined, '听林舟'])(
  'keeps the failed clip compact with an accessible retry description (%s)',
  async (caption) => {
    render(
      <ClipButton src="/clip.wav" label="听片段" caption={caption} size="md" />,
    );
    const initial = screen.getByRole('button', { name: '听片段' });
    expect(initial).not.toHaveAttribute('title');
    expect(initial).not.toHaveClass('text-danger');
    await userEvent.click(initial);
    await act(async () =>
      attempts[0].reject(new Error('synthetic playback failure')),
    );
    const retry = screen.getByRole('button', { name: '重试听片段' });
    const alert = screen.getByRole('alert');
    expect(retry).toHaveAttribute('title', '无法试听，请重试');
    expect(retry).toHaveAccessibleDescription('无法试听，请重试');
    expect(retry).toHaveClass('text-danger');
    expect(retry.querySelector('svg')).toHaveClass('lucide-rotate-ccw');
    expect(retry).toHaveAttribute('aria-describedby', alert.id);
    expect(alert).toHaveClass('sr-only');
    if (caption) expect(retry).toHaveTextContent(caption);
    await userEvent.click(retry);
    await begin(attempts[1]);
    expect(screen.queryByRole('alert')).toBeNull();
    const playing = screen.getByRole('button', { name: '暂停听片段' });
    expect(playing).not.toHaveAttribute('title');
    expect(playing).not.toHaveAttribute('aria-describedby');
    expect(playing).not.toHaveClass('text-danger');
    if (caption) expect(playing).toHaveTextContent(caption);
  },
);
