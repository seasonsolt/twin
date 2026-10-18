import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from 'react';

/** The conversation layout chat and work share: the pinned composer's height (the thread leaves room for it),
 * the phone keyboard's inset, and the end of the thread to scroll to. The height is also written to `page` (the
 * conversation's root element) as `--composer-height`, which the thread's bottom padding in tokens.css reads. */
export function useComposerLayout(active: boolean) {
  const page = useRef<HTMLDivElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLFormElement>(null);
  const [composerHeight, setComposerHeight] = useState(76);
  useLayoutEffect(() => {
    const form = composer.current;
    if (!form) return;
    const resize = () =>
      setComposerHeight(form.getBoundingClientRect().height || 76);
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(form);
    return () => observer.disconnect();
  }, []);
  useLayoutEffect(() => {
    page.current?.style.setProperty('--composer-height', `${composerHeight}px`);
  }, [composerHeight]);
  useEffect(() => {
    if (!active) return;
    const viewport = window.visualViewport;
    const root = document.documentElement;
    let frame = 0;
    const update = () => {
      const inset = viewport
        ? Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop)
        : 0;
      const mobile = window.matchMedia('(max-width: 767px)').matches;
      const focused = document.activeElement?.matches(
        'input, textarea, select',
      );
      const keyboard = mobile && !!focused && inset > 120;
      root.dataset.keyboard = String(keyboard);
      root.style.setProperty(
        '--keyboard-inset',
        keyboard ? `${inset}px` : '0px',
      );
      cancelAnimationFrame(frame);
      if (focused)
        frame = requestAnimationFrame(() =>
          end.current?.scrollIntoView?.({ block: 'end' }),
        );
    };
    update();
    viewport?.addEventListener('resize', update);
    viewport?.addEventListener('scroll', update);
    window.addEventListener('resize', update);
    document.addEventListener('focusin', update);
    document.addEventListener('focusout', update);
    return () => {
      cancelAnimationFrame(frame);
      viewport?.removeEventListener('resize', update);
      viewport?.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
      document.removeEventListener('focusin', update);
      document.removeEventListener('focusout', update);
      delete root.dataset.keyboard;
      root.style.removeProperty('--keyboard-inset');
    };
  }, [active]);
  return { page, end, composer, composerHeight };
}

const REPLY_GAP = 16;

/** ChatGPT's way with a message just sent: it goes to the top of the visible thread and the space below it is
 * kept open for the reply, shrinking as the reply grows. ``pinned`` is the ``data-pin`` of that message (null:
 * nothing pinned, e.g. a conversation opened from history, which shows its end instead). Returns the height of
 * the space to render after ``end``. */
export function usePinnedMessage(
  pinned: string | null,
  end: RefObject<HTMLElement | null>,
  composer: RefObject<HTMLElement | null>,
) {
  const [space, setSpace] = useState(0);
  const scrolled = useRef<string | null>(null);
  useLayoutEffect(() => {
    if (!pinned) {
      setSpace(0);
      scrolled.current = null;
      return;
    }
    const target = document.querySelector<HTMLElement>(
      `[data-pin="${CSS.escape(pinned)}"]`,
    );
    const marker = end.current;
    const form = composer.current;
    if (!target || !marker || !form) {
      setSpace(0);
      return;
    }
    // The thread scrolls in its own column on a wide screen, and with the window otherwise.
    const scroller = target.closest<HTMLElement>('.chat-scroll');
    const own =
      scroller !== null &&
      ['auto', 'scroll'].includes(getComputedStyle(scroller).overflowY);
    const measure = () => {
      const top = own ? scroller.getBoundingClientRect().top : 0;
      const margin = parseFloat(getComputedStyle(target).scrollMarginTop) || 0;
      const visible = form.getBoundingClientRect().top - top - margin;
      const content =
        marker.getBoundingClientRect().top - target.getBoundingClientRect().top;
      setSpace(Math.max(0, Math.round(visible - content - REPLY_GAP)));
    };
    measure();
    const observer = new ResizeObserver(measure);
    if (marker.parentElement) observer.observe(marker.parentElement);
    observer.observe(form);
    window.addEventListener('resize', measure);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, [pinned, end, composer]);
  useEffect(() => {
    if (!pinned || scrolled.current === pinned) return;
    const target = document.querySelector<HTMLElement>(
      `[data-pin="${CSS.escape(pinned)}"]`,
    );
    if (!target) return;
    // After the space below is in place, so the message can reach the top; a later change of the space before
    // the frame cancels this one and schedules it again.
    const frame = requestAnimationFrame(() => {
      scrolled.current = pinned;
      // Glide rather than jump, so the earlier answer is seen leaving upward instead of vanishing at once.
      const reduced = window.matchMedia?.(
        '(prefers-reduced-motion: reduce)',
      ).matches;
      target.scrollIntoView?.({
        block: 'start',
        behavior: reduced ? 'auto' : 'smooth',
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [pinned, space]);
  return space;
}
