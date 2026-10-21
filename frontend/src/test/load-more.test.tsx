import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { LoadMore } from '../components/ui';

let watches: {
  notify: IntersectionObserverCallback;
  observer: IntersectionObserver;
}[];
beforeEach(() => {
  watches = [];
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      constructor(notify: IntersectionObserverCallback) {
        watches.push({
          notify,
          observer: this as unknown as IntersectionObserver,
        });
      }
      observe() {}
      disconnect() {}
    },
  );
});

const intersect = (index: number, visible = true) => {
  const { notify, observer } = watches[index];
  notify([{ isIntersecting: visible } as IntersectionObserverEntry], observer);
};

it('continues once per observed page and ignores callbacks after cleanup', () => {
  const more = vi.fn();
  const view = render(<LoadMore shown={18} total={41} onLoadMore={more} />);
  act(() => {
    intersect(0, false);
    intersect(0);
    intersect(0);
  });
  expect(more).toHaveBeenCalledTimes(1);
  view.rerender(<LoadMore shown={36} total={41} onLoadMore={more} />);
  act(() => intersect(1));
  expect(more).toHaveBeenCalledTimes(2);
  view.unmount();
  act(() => intersect(1));
  expect(more).toHaveBeenCalledTimes(2);
});

it('does not load inactive, disabled or completed lists', () => {
  const more = vi.fn();
  const view = render(
    <LoadMore shown={18} total={41} active={false} onLoadMore={more} />,
  );
  expect(watches).toHaveLength(0);
  view.rerender(<LoadMore shown={18} total={41} disabled onLoadMore={more} />);
  expect(screen.getByRole('button')).toBeDisabled();
  expect(watches).toHaveLength(0);
  view.rerender(<LoadMore shown={41} total={41} onLoadMore={more} />);
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
  expect(watches).toHaveLength(0);
  expect(more).not.toHaveBeenCalled();
});

it('keeps a keyboard action when automatic observation is unavailable', async () => {
  vi.stubGlobal('IntersectionObserver', undefined);
  const more = vi.fn();
  render(
    <LoadMore shown={18} total={41} onLoadMore={more} label="继续加载人物" />,
  );
  expect(screen.getByText('已显示 18 / 41')).toBeVisible();
  await userEvent.tab();
  await userEvent.keyboard('{Enter}');
  expect(more).toHaveBeenCalledTimes(1);
});
