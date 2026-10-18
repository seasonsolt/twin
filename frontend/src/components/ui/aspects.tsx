import * as TabsPrimitive from '@radix-ui/react-tabs';
import type { ReactNode } from 'react';
import { cn } from '../../lib/utils';
import { useMobile } from '../../lib/useMobile';

/**
 * Which layer of a person an aspect belongs to: the core (values, thinking, decisions), what shows outwardly
 * (speech, relationships, skills), or their circumstances (background, current focus, life). Each layer keeps one
 * colour everywhere it appears.
 */
export type AspectLayer = 'core' | 'outer' | 'context';

const layerFills: Record<AspectLayer, string> = {
  core: 'bg-accent',
  outer: 'bg-coral',
  context: 'bg-sun',
};
const layerStrokes: Record<AspectLayer, string> = {
  core: 'stroke-accent',
  outer: 'stroke-coral',
  context: 'stroke-sun',
};
// How much of the layer colour a level shows: nothing known reads as an empty track.
const levelOpacity = [0, 0.4, 0.7, 1];

/**
 * How well something is known, as up to `max` filled dots. With `label` it reads as that text; without it, it is
 * decoration next to words that already say the level.
 */
export function LevelDots({
  level,
  max = 3,
  layer = 'core',
  label,
}: {
  level: number;
  max?: number;
  layer?: AspectLayer;
  label?: string;
}) {
  const filled = Math.max(0, Math.min(max, Math.round(level)));
  return (
    <span
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className="inline-flex shrink-0 items-center gap-1"
    >
      {Array.from({ length: max }, (_, i) => (
        <span
          key={i}
          className={cn(
            'size-1.5 rounded-full',
            i < filled ? layerFills[layer] : 'bg-border',
          )}
        />
      ))}
    </span>
  );
}

/**
 * A ring cut into one segment per aspect, each coloured by its layer and filled by how well it is known, with
 * `children` (a count, a word) in the middle. Reads as `label`.
 */
export function AspectRing({
  segments,
  label,
  children,
}: {
  segments: { layer: AspectLayer; level: number }[];
  label: string;
  children?: ReactNode;
}) {
  const size = 160;
  const radius = 64;
  const center = size / 2;
  const gap = 4;
  const step = 360 / Math.max(1, segments.length);
  const point = (degrees: number) => {
    const radians = ((degrees - 90) * Math.PI) / 180;
    return `${center + radius * Math.cos(radians)} ${center + radius * Math.sin(radians)}`;
  };
  return (
    <div role="img" aria-label={label} className="relative size-40 shrink-0">
      <svg viewBox={`0 0 ${size} ${size}`} className="size-full" aria-hidden>
        {segments.map((segment, i) => {
          const start = i * step + gap / 2;
          const end = (i + 1) * step - gap / 2;
          const arc = `M ${point(start)} A ${radius} ${radius} 0 0 1 ${point(end)}`;
          const opacity = levelOpacity[Math.max(0, Math.min(3, segment.level))];
          return (
            <g key={i}>
              <path
                d={arc}
                fill="none"
                strokeWidth={14}
                strokeLinecap="butt"
                className="stroke-border"
              />
              {opacity > 0 && (
                <path
                  d={arc}
                  fill="none"
                  strokeWidth={14}
                  strokeLinecap="butt"
                  strokeOpacity={opacity}
                  className={layerStrokes[segment.layer]}
                />
              )}
            </g>
          );
        })}
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">
        <div>{children}</div>
      </div>
    </div>
  );
}

/**
 * Tabs listed down the side in labelled groups, with the chosen one's content beside them; on phones the list
 * becomes one scrolling row above the content. `children` is the content of the chosen tab.
 */
export function SideTabs({
  label,
  groups,
  value,
  onValueChange,
  children,
}: {
  label: string;
  groups: {
    label: string;
    layer?: AspectLayer;
    items: { value: string; label: ReactNode; trailing?: ReactNode }[];
  }[];
  value: string;
  onValueChange: (value: string) => void;
  children: ReactNode;
}) {
  // Arrow keys follow what the eye sees: left/right along the phone row, up/down down the side list.
  const mobile = useMobile();
  return (
    <TabsPrimitive.Root
      value={value}
      onValueChange={onValueChange}
      orientation={mobile ? 'horizontal' : 'vertical'}
      className="grid min-w-0 gap-4 md:grid-cols-[208px_minmax(0,1fr)] md:gap-6"
    >
      <TabsPrimitive.List
        aria-label={label}
        className="flex min-w-0 gap-1 overflow-x-auto md:flex-col md:overflow-visible"
      >
        {groups.map((group) => (
          <div
            key={group.label}
            role="presentation"
            className="flex shrink-0 gap-1 md:flex-col md:pb-3"
          >
            <div
              role="presentation"
              className="hidden items-center gap-2 px-3 pb-1 text-xs text-tertiary md:flex"
            >
              {group.layer && (
                <span
                  className={cn('size-2 rounded-full', layerFills[group.layer])}
                />
              )}
              {group.label}
            </div>
            {group.items.map((item) => (
              <TabsPrimitive.Trigger
                key={item.value}
                value={item.value}
                className="flex min-h-11 shrink-0 items-center justify-between gap-3 whitespace-nowrap rounded-full px-4 text-left text-secondary hover:bg-soft data-[state=active]:bg-soft data-[state=active]:font-medium data-[state=active]:text-primary md:min-h-10 md:rounded-md md:px-3"
              >
                <span className="min-w-0 truncate">{item.label}</span>
                {item.trailing && <> {item.trailing}</>}
              </TabsPrimitive.Trigger>
            ))}
          </div>
        ))}
      </TabsPrimitive.List>
      <TabsPrimitive.Content value={value} className="min-w-0">
        {children}
      </TabsPrimitive.Content>
    </TabsPrimitive.Root>
  );
}
