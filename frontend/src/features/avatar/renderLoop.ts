export function visibleRenderLoop(
  element: HTMLElement,
  render: (delta: number) => void,
) {
  let intersecting = false;
  let frame: number | null = null;
  let previous: number | null = null;
  let disposed = false;
  const tick = (time: number) => {
    frame = null;
    if (disposed || !intersecting || document.hidden) return;
    if (previous === null || time - previous >= 1000 / 60 - 0.1) {
      const delta =
        previous === null ? 1 / 60 : Math.min((time - previous) / 1000, 0.05);
      previous = time;
      render(delta);
    }
    if (!disposed) frame = requestAnimationFrame(tick);
  };
  const sync = () => {
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    previous = null;
    if (!disposed && intersecting && !document.hidden)
      frame = requestAnimationFrame(tick);
  };
  const observer = new IntersectionObserver((entries) => {
    intersecting = entries.some((entry) => entry.isIntersecting);
    sync();
  });
  observer.observe(element);
  document.addEventListener('visibilitychange', sync);
  return () => {
    disposed = true;
    observer.disconnect();
    document.removeEventListener('visibilitychange', sync);
    sync();
  };
}
