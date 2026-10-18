import { useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import './resize.css';

const STEP = 16;
const LARGE_STEP = 64;

/** A vertical edge the viewer drags to set the width of the positioned panel it sits in. Arrow keys move it by
 * 16px (64px with Shift), Home and End go to the limits, and a double click puts back ``defaultValue``. */
export function ResizeHandle({
  label,
  value,
  min,
  max,
  defaultValue,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  defaultValue: number;
  onChange(value: number): void;
}) {
  const start = useRef<{ x: number; value: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const change = (next: number) =>
    onChange(Math.round(Math.min(max, Math.max(min, next))));
  const end = (event: PointerEvent<HTMLDivElement>) => {
    if (!start.current) return;
    start.current = null;
    setDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const keys = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? LARGE_STEP : STEP;
    const next = {
      ArrowLeft: value - step,
      ArrowRight: value + step,
      Home: min,
      End: max,
    }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    change(next);
  };
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={value}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      className="resize-handle"
      data-dragging={dragging || undefined}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        // No text selection or focus jump while dragging; the pointer stays with the handle off its edge.
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        start.current = { x: event.clientX, value };
        setDragging(true);
      }}
      onPointerMove={(event) => {
        if (start.current)
          change(start.current.value + event.clientX - start.current.x);
      }}
      onPointerUp={end}
      onPointerCancel={end}
      onDoubleClick={() => change(defaultValue)}
      onKeyDown={keys}
    />
  );
}
