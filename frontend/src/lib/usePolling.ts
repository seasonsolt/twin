import { useEffect, useRef } from 'react';

/** Call ``load`` every ``interval`` milliseconds (0 = not at all) while the page is in view. A tab in the
 * background asks nothing of the server; coming back, it loads at once and goes on polling. */
export function usePolling(load: () => unknown, interval: number) {
  const latest = useRef(load);
  useEffect(() => {
    latest.current = load;
  }, [load]);
  useEffect(() => {
    if (!interval) return;
    let timer: ReturnType<typeof setInterval> | undefined;
    const start = () => {
      clearInterval(timer);
      timer = setInterval(() => void latest.current(), interval);
    };
    const visibility = () => {
      if (document.hidden) {
        clearInterval(timer);
        timer = undefined;
      } else {
        void latest.current();
        start();
      }
    };
    if (!document.hidden) start();
    document.addEventListener('visibilitychange', visibility);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', visibility);
    };
  }, [interval]);
}
