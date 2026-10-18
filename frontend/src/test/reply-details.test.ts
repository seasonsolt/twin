import { afterEach, expect, it, vi } from 'vitest';
import { placeDetails } from '../features/chat/ReplyDetails';

function box(top: number, bottom: number) {
  return { top, bottom, height: bottom - top } as DOMRect;
}

/** A compact details at ``anchorTop``, inside a list scrolling from 0 to 600, whose content is 100px tall. */
function opened(anchorTop: number) {
  const list = document.createElement('div');
  list.style.overflowY = 'auto';
  const details = document.createElement('details');
  const content = document.createElement('div');
  content.className = 'reply-details-content';
  details.append(document.createElement('summary'), content);
  list.append(details);
  document.body.append(list);
  details.open = true;
  list.getBoundingClientRect = () => box(0, 600);
  details.getBoundingClientRect = () => box(anchorTop, anchorTop + 40);
  content.getBoundingClientRect = () => box(0, 100);
  content.scrollIntoView = vi.fn();
  return { details, content };
}

afterEach(() => {
  document.body.replaceChildren();
});

it('opens upward only when the room below is too short and the room above is enough', () => {
  const low = opened(520);
  placeDetails(low.details);
  expect(low.details.dataset.placement).toBe('top');
  expect(low.content.scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' });

  const high = opened(100);
  placeDetails(high.details);
  expect(high.details.dataset.placement).toBeUndefined();

  // A short list with no room either way keeps opening downward and is scrolled into view instead.
  const cramped = opened(50);
  cramped.details.getBoundingClientRect = () => box(50, 560);
  placeDetails(cramped.details);
  expect(cramped.details.dataset.placement).toBeUndefined();
  expect(cramped.content.scrollIntoView).toHaveBeenCalled();
});

it('forgets the placement when closed', () => {
  const { details } = opened(520);
  placeDetails(details);
  details.open = false;
  placeDetails(details);
  expect(details.dataset.placement).toBeUndefined();
});
