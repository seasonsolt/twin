import { useEffect, useLayoutEffect, useRef, useState } from 'react';

/** The conversation layout chat and work share: the pinned composer's height (the thread leaves room for it),
 * the phone keyboard's inset, and the end of the thread to scroll to. */
export function useComposerLayout(active: boolean) {
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
  return { end, composer, composerHeight };
}
