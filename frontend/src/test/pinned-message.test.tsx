import { act, render } from '@testing-library/react';
import { useRef } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { usePinnedMessage } from '../features/chat/useComposerLayout';

let tops: Record<string, number> = {};
const rect = (top: number) => ({ top }) as DOMRect;

function Thread({ pinned }: { pinned: string | null }) {
  const end = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLFormElement>(null);
  const space = usePinnedMessage(pinned, end, composer);
  return (
    <div className="chat-scroll">
      <div className="chat-conversation">
        <article data-pin="m1" data-testid="m1" />
        <div ref={end} data-testid="end" />
        {space > 0 && <div data-testid="space" style={{ height: space }} />}
      </div>
      <form ref={composer} data-testid="composer" />
    </div>
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  tops = {};
});

it('keeps the room below a sent message that brings it to the top, shrinking as the reply grows', async () => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
    function (this: HTMLElement) {
      return rect(tops[this.dataset.testid ?? ''] ?? 0);
    },
  );
  const scroll = vi.fn();
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: scroll,
  });
  // The composer starts 800px down; the message is at 100 and the thread ends 200px below it.
  tops = { composer: 800, m1: 100, end: 300 };
  const view = render(<Thread pinned={null} />);
  expect(view.queryByTestId('space')).toBeNull();
  view.rerender(<Thread pinned="m1" />);
  await act(async () => {
    await new Promise((resolve) => requestAnimationFrame(resolve));
  });
  // 800 visible - 200 of content - 16 of gap.
  expect(view.getByTestId('space')).toHaveStyle({ height: '584px' });
  expect(scroll).toHaveBeenCalledWith({ block: 'start' });
  expect(scroll.mock.contexts.at(-1)).toBe(view.getByTestId('m1'));

  // The reply grows past the screen: no room is left.
  tops = { ...tops, end: 1000 };
  act(() => window.dispatchEvent(new Event('resize')));
  expect(view.queryByTestId('space')).toBeNull();
  expect(scroll).toHaveBeenCalledTimes(1);

  view.rerender(<Thread pinned={null} />);
  expect(view.queryByTestId('space')).toBeNull();
  delete (HTMLElement.prototype as Partial<HTMLElement>).scrollIntoView;
});
