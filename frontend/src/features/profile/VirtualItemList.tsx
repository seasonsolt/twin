import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';

const ESTIMATE = 280;
const OVERSCAN = 700;
function MeasuredRow({
  id,
  onHeight,
  children,
}: {
  id: string;
  onHeight: (id: string, height: number) => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    const measure = () => {
      const height = node.getBoundingClientRect().height;
      if (height > 0) onHeight(id, height);
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [id, onHeight]);
  return (
    <div ref={ref} className="pb-3">
      {children}
    </div>
  );
}
export function VirtualItemList({
  rows,
}: {
  rows: { id: string; content: ReactNode }[];
}) {
  const [heights, setHeights] = useState<Record<string, number>>({});
  const [viewport, setViewport] = useState({ top: 0, height: 600 });
  const [focused, setFocused] = useState<string | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const [measure] = useState(() => (id: string, height: number) => {
    setHeights((previous) =>
      previous[id] === height ? previous : { ...previous, [id]: height },
    );
  });
  useLayoutEffect(() => {
    const node = container.current;
    if (!node) return;
    const resize = () =>
      setViewport({ top: node.scrollTop, height: node.clientHeight || 600 });
    resize();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(resize);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  let total = 0;
  const positions = rows.map((row) => {
    const top = total;
    const height = heights[row.id] ?? ESTIMATE;
    total += height;
    return { row, top, height };
  });
  return (
    <div
      ref={container}
      tabIndex={0}
      aria-label="档案条目滚动区域"
      className="h-[65dvh] overflow-y-auto"
      style={{ overflowAnchor: 'none' }}
      onScroll={(event) =>
        setViewport({
          top: event.currentTarget.scrollTop,
          height: event.currentTarget.clientHeight || 600,
        })
      }
    >
      <ul aria-label="档案条目" className="relative" style={{ height: total }}>
        {positions.map(({ row, top, height }, index) => {
          if (
            row.id !== focused &&
            (top + height < viewport.top - OVERSCAN ||
              top > viewport.top + viewport.height + OVERSCAN)
          )
            return null;
          return (
            <li
              key={row.id}
              aria-posinset={index + 1}
              aria-setsize={rows.length}
              className="absolute right-0 left-0"
              style={{ top }}
              onFocusCapture={() => setFocused(row.id)}
              onBlurCapture={(event) => {
                if (
                  !event.currentTarget.contains(
                    event.relatedTarget as Node | null,
                  )
                )
                  setFocused(null);
              }}
            >
              <MeasuredRow id={row.id} onHeight={measure}>
                {row.content}
              </MeasuredRow>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
