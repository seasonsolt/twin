import {
  cloneElement,
  type ComponentProps,
  type ReactElement,
  type ReactNode,
} from 'react';
import { motion } from 'motion/react';
import { Inbox, MoreHorizontal } from 'lucide-react';
import { useMotionPreset } from '../../design/motion';
import { Pressable } from '../motion';
import { cn } from '../../lib/utils';
import { Button, toneClasses, type Tone } from './controls';

const cardVariants = {
  /** White card lifted off the canvas (the default). */
  raised: 'bg-surface shadow-card',
  /** White card with a hairline border, for blocks inside a page section. */
  outline: 'border border-border bg-surface',
  /** Warm note colour, for a prompt the person should read. */
  note: 'bg-note',
  /** Tinted, for something set back from the content around it. */
  soft: 'bg-soft',
  /** Danger zone. */
  danger: 'border border-danger/20 bg-surface shadow-card',
};
const cardPadding = {
  none: '',
  sm: 'p-3',
  md: 'p-4',
  lg: 'p-5',
  /** 16px on phones, 24px from tablets up. */
  roomy: 'p-4 md:p-6',
};
export type CardVariant = keyof typeof cardVariants;

export function Card({
  interactive = false,
  onClick,
  variant = 'raised',
  padding = 'lg',
  as: Tag = 'section',
  className,
  children,
  ...props
}: {
  interactive?: boolean;
  onClick?: () => void;
  variant?: CardVariant;
  padding?: keyof typeof cardPadding;
  as?: 'section' | 'div' | 'li' | 'article' | 'aside';
  /** Layout only (spacing between children, flex, opacity). The look comes from `variant` and `padding`. */
  className?: string;
  children: ReactNode;
} & Pick<
  ComponentProps<'section'>,
  'id' | 'role' | 'aria-label' | 'aria-labelledby' | 'aria-busy' | 'aria-live'
>) {
  const styles = cn(
    'rounded-lg',
    cardVariants[variant],
    cardPadding[padding],
    className,
  );
  return interactive ? (
    <Pressable onClick={onClick} className={cn(styles, 'text-left')}>
      {children}
    </Pressable>
  ) : (
    <Tag {...props} className={styles}>
      {children}
    </Tag>
  );
}

export function Badge({
  tone = 'neutral',
  className,
  ...props
}: ComponentProps<'span'> & { tone?: Tone }) {
  return (
    <span
      {...props}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border border-current/15 bg-current/5 px-2.5 py-0.5 text-xs font-medium',
        toneClasses[tone],
        className,
      )}
    />
  );
}

/**
 * A progress bar. `value` counts up to `max` (100 by default, so a plain percent works); null means it is working
 * without a known end. `size="sm"` is the thin bar for a step inside a list.
 */
export function Meter({
  value,
  max = 100,
  label,
  hideLabel = false,
  size = 'md',
}: {
  value: number | null;
  max?: number;
  label: string;
  hideLabel?: boolean;
  size?: 'sm' | 'md';
}) {
  const { reduced, transition } = useMotionPreset('gentle');
  const percent =
    value === null
      ? null
      : Math.max(0, Math.min(100, max > 0 ? (value / max) * 100 : 0));
  return (
    <div className="space-y-2">
      <div className={hideLabel ? 'sr-only' : 'flex justify-between text-sm'}>
        <span>{label}</span>
        <span className="text-secondary">
          {percent === null ? '正在处理…' : `${Math.round(percent)}%`}
        </span>
      </div>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={value === null ? undefined : 0}
        aria-valuemax={value === null ? undefined : max}
        aria-valuenow={
          value === null ? undefined : Math.min(max, Math.max(0, value))
        }
        className={cn(
          'overflow-hidden rounded-full',
          size === 'sm' ? 'h-1.5 bg-soft' : 'h-2 bg-border',
        )}
      >
        {percent === null ? (
          <div className="h-full w-full rounded-full bg-accent/30" />
        ) : reduced ? (
          <motion.div
            key={percent}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={transition}
            style={{ width: `${percent}%` }}
            className="h-full rounded-full bg-accent"
          />
        ) : (
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${percent}%` }}
            transition={transition}
            className="h-full rounded-full bg-accent"
          />
        )}
      </div>
    </div>
  );
}

export function Skeleton({
  panel = false,
  className,
  ...props
}: ComponentProps<'div'> & {
  /** Stands in for a view that fills most of the screen (a graph): 70% of the viewport's height. */
  panel?: boolean;
}) {
  return (
    <div
      {...props}
      aria-hidden
      className={cn('skeleton h-4 rounded-sm', panel && 'h-[70vh]', className)}
    />
  );
}

export function EmptyState({
  title,
  body,
  children,
}: {
  title: string;
  body?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 px-5 py-16 text-center">
      <span className="rounded-lg border border-border bg-surface p-4 text-tertiary">
        <Inbox aria-hidden className="size-7" />
      </span>
      <h2 className="text-lg font-semibold">{title}</h2>
      {body && <p className="max-w-md text-secondary">{body}</p>}
      {children}
    </div>
  );
}

export function Table({
  caption,
  headers,
  rows,
}: {
  caption: string;
  headers: string[];
  rows: ReactNode[][];
}) {
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full border-collapse text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-canvas text-secondary">
          <tr>
            {headers.map((header) => (
              <th
                key={header}
                scope="col"
                className="whitespace-nowrap px-4 py-3 font-medium"
              >
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-border">
              {row.map((cell, j) => (
                <td key={j} className="px-4 py-3">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const noticeTones = {
  note: 'bg-note text-primary',
  info: 'border border-info/20 bg-info/5 text-primary',
  warning: 'border border-warning/25 bg-warning/5 text-primary',
  danger: 'border border-danger/25 bg-danger/5 text-danger',
};
/** A short message across the content: setup still missing, something to know before acting. */
export function Notice({
  tone = 'note',
  role = 'status',
  title,
  actions,
  children,
}: {
  tone?: keyof typeof noticeTones;
  role?: 'status' | 'alert' | 'note';
  title?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div
      role={role}
      className={cn(
        'flex flex-wrap items-center gap-3 rounded-md p-4 text-sm',
        noticeTones[tone],
      )}
    >
      <div className="min-w-0 flex-1 space-y-1">
        {title && <p className="font-medium">{title}</p>}
        {children}
      </div>
      {actions}
    </div>
  );
}

/**
 * One item in a list: an optional picture or icon, a title, a line of details, extra content under them, and its
 * actions at the end. Render a list of them inside <Stack as="ul">.
 */
export function ListRow({
  as: Tag = 'li',
  variant = 'card',
  leading,
  title,
  meta,
  trailing,
  children,
  ...props
}: {
  as?: 'li' | 'div' | 'article';
  /** card: white row on the canvas; outline: hairline border; plain: no box, for rows inside a card. */
  variant?: 'card' | 'outline' | 'plain';
  leading?: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  trailing?: ReactNode;
  children?: ReactNode;
} & Pick<ComponentProps<'li'>, 'id' | 'aria-label' | 'aria-current'>) {
  return (
    <Tag
      {...props}
      className={cn(
        'flex flex-wrap items-center gap-3',
        variant === 'card' && 'rounded-md bg-surface p-4',
        variant === 'outline' &&
          'rounded-md border border-border bg-surface p-4',
        variant === 'plain' && 'py-3',
      )}
    >
      {leading && <div className="shrink-0">{leading}</div>}
      <div className="min-w-0 flex-1 space-y-1">
        <div className="min-w-0 font-medium">{title}</div>
        {meta && <div className="text-sm text-secondary">{meta}</div>}
        {children}
      </div>
      {trailing && (
        <div className="flex flex-wrap items-center gap-2">{trailing}</div>
      )}
    </Tag>
  );
}

/** A number with what it counts, for summaries. */
export function Stat({
  label,
  value,
  hint,
  tone = 'neutral',
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  tone?: Tone;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-sm text-secondary">{label}</span>
      <span
        className={cn(
          'text-2xl font-semibold tabular-nums',
          tone === 'neutral' ? 'text-primary' : toneClasses[tone],
        )}
      >
        {value}
      </span>
      {hint && <span className="text-xs text-tertiary">{hint}</span>}
    </div>
  );
}

/** Label–value pairs (who, when, where from), as a description list. */
export function KeyValue({
  items,
  layout = 'rows',
}: {
  items: [ReactNode, ReactNode][];
  /** rows: label beside value; inline: pairs flowing on one line, for short facts under a title. */
  layout?: 'rows' | 'inline';
}) {
  return layout === 'rows' ? (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
      {items.map(([label, value], i) => (
        <div key={i} className="contents">
          <dt className="text-secondary">{label}</dt>
          <dd className="min-w-0 break-words">{value}</dd>
        </div>
      ))}
    </dl>
  ) : (
    <dl className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
      {items.map(([label, value], i) => (
        <div key={i} className="flex gap-1">
          <dt className="text-secondary">{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

const frameSizes = {
  sm: 'size-8 text-sm',
  md: 'size-10 text-base',
  lg: 'size-12 text-lg',
  xl: 'size-16 text-xl',
  '2xl': 'size-18 text-2xl',
  /** Fills its parent, whose size the page sets. */
  fill: 'size-full text-lg',
};
/**
 * A round frame for a portrait (an <img> fills it), an illustration or a name's first character. Hidden from screen
 * readers unless it has a `label`, or `decorative={false}` when the content names itself (an <img alt>). `muted` is
 * for a placeholder word such as "未设置".
 */
export function AvatarFrame({
  size = 'lg',
  label,
  decorative = true,
  muted = false,
  outlined = false,
  children,
}: {
  size?: keyof typeof frameSizes;
  label?: string;
  decorative?: boolean;
  muted?: boolean;
  /** A 2px ring in the canvas colour, so a photo stands off a background of the same tone. */
  outlined?: boolean;
  children: ReactNode;
}) {
  return (
    <span
      {...(label
        ? { role: 'img', 'aria-label': label }
        : decorative && { 'aria-hidden': true })}
      className={cn(
        'grid shrink-0 place-items-center overflow-hidden rounded-full [&>img]:size-full [&>img]:object-cover',
        muted
          ? 'bg-canvas text-sm text-secondary'
          : 'bg-soft font-semibold text-accent',
        // A placeholder word keeps its small size whatever the frame's.
        muted ? frameSizes[size].split(' ')[0] : frameSizes[size],
        outlined && 'border-2 border-canvas',
      )}
    >
      {children}
    </span>
  );
}

/**
 * A portrait photo filling its frame, cropped towards the face (the upper part of the picture) rather than the middle.
 */
export function Portrait(props: Omit<ComponentProps<'img'>, 'className'>) {
  return <img {...props} className="size-full object-cover object-[50%_30%]" />;
}

const clipShapes = {
  /** A card's 16px corners. */
  card: 'rounded-lg',
  /** A list row's 12px corners. */
  row: 'rounded-md',
  circle: 'rounded-full',
};
/**
 * Rounds and clips its one child (a video, a box holding a 3D view) to a shape from the scale, keeping the child's
 * own element and layout classes.
 */
export function Clip({
  shape,
  children,
}: {
  shape: keyof typeof clipShapes;
  children: ReactElement<{ className?: string }>;
}) {
  return cloneElement(children, {
    className: cn(
      children.props.className,
      'overflow-hidden',
      clipShapes[shape],
    ),
  });
}

/** A box for a picture or a cropper: clips to the card corners. */
export function MediaFrame({
  height = 'lg',
  tone = 'dark',
  label,
  children,
}: {
  /** md 256px, lg 320px. */
  height?: 'md' | 'lg';
  /** dark behind a photo; soft for a message in place of one. */
  tone?: 'dark' | 'soft';
  label?: string;
  children: ReactNode;
}) {
  return (
    <div
      aria-label={label}
      className={cn(
        'relative overflow-hidden rounded-lg',
        height === 'md' ? 'h-64' : 'h-80',
        tone === 'dark'
          ? 'bg-black'
          : 'flex items-center justify-center bg-canvas p-6 text-center text-secondary',
      )}
    >
      {children}
    </div>
  );
}

/** Bars that rise with the microphone level (0–1) while recording. Decorative: give the level in text too. */
export function AudioLevel({
  level,
  bars = 12,
}: {
  level: number;
  bars?: number;
}) {
  return (
    <div aria-hidden className="flex h-12 items-center gap-1">
      {Array.from({ length: bars }, (_, index) => (
        <i
          key={index}
          className="w-1.5 rounded-full bg-primary"
          style={{ height: `${8 + level * ((index % 3) + 1) * 12}px` }}
        />
      ))}
    </div>
  );
}

const dotTones: Record<Tone | 'accent', string> = {
  neutral: 'bg-tertiary',
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
  info: 'bg-info',
  accent: 'bg-accent',
};
/** A small coloured dot before a status word; pair it with text, colour alone says nothing to everyone. */
export function StatusDot({ tone = 'neutral' }: { tone?: Tone | 'accent' }) {
  return (
    <span
      aria-hidden
      className={cn(
        'inline-block size-2 shrink-0 rounded-full',
        dotTones[tone],
      )}
    />
  );
}

/** A card that opens to show more, such as a full transcript. The summary line is the toggle. */
export function Disclosure({
  summary,
  defaultOpen = false,
  variant = 'raised',
  children,
}: {
  summary: ReactNode;
  defaultOpen?: boolean;
  variant?: 'raised' | 'outline' | 'plain';
  children: ReactNode;
}) {
  return (
    <details
      open={defaultOpen || undefined}
      className={cn(
        variant === 'raised' && 'rounded-lg bg-surface p-4',
        variant === 'outline' &&
          'rounded-lg border border-border bg-surface p-4',
      )}
    >
      <summary className="min-h-11 cursor-pointer content-center md:min-h-9">
        {summary}
      </summary>
      <div className="mt-3">{children}</div>
    </details>
  );
}

/** The number of a step in a short how-it-works list. */
export function StepNumber({ children }: { children: ReactNode }) {
  return (
    <span
      aria-hidden
      className="grid size-8 shrink-0 place-items-center rounded-full bg-primary font-semibold text-canvas"
    >
      {children}
    </span>
  );
}

/**
 * A round "⋯" button that opens a short list of actions below it; choosing one closes the list. `className` places
 * the menu (for example absolute in a card's corner).
 */
export function ActionMenu({
  label,
  items,
  className,
}: {
  label: string;
  items: { label: string; onSelect: () => void; disabled?: boolean }[];
  className?: string;
}) {
  return (
    <details className={className}>
      <summary
        aria-label={label}
        className="grid size-11 cursor-pointer list-none place-items-center rounded-full text-secondary hover:bg-soft [&::-webkit-details-marker]:hidden"
      >
        <MoreHorizontal size={20} aria-hidden />
      </summary>
      <div className="absolute right-0 z-10 grid min-w-28 rounded-lg border border-border bg-surface p-1 shadow-elevation-2">
        {items.map((item) => (
          <Button
            key={item.label}
            variant="ghost"
            disabled={item.disabled}
            onClick={(event) => {
              event.currentTarget.closest('details')?.removeAttribute('open');
              item.onSelect();
            }}
          >
            {item.label}
          </Button>
        ))}
      </div>
    </details>
  );
}
