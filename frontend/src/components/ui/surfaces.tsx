import { type ComponentProps, type ReactNode } from 'react';
import { motion } from 'motion/react';
import { Inbox } from 'lucide-react';
import { useMotionPreset } from '../../design/motion';
import { Pressable } from '../motion';
import { cn } from '../../lib/utils';
import { toneClasses, type Tone } from './controls';

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

export function Meter({
  value,
  label,
  hideLabel = false,
}: {
  value: number | null;
  label: string;
  hideLabel?: boolean;
}) {
  const { reduced, transition } = useMotionPreset('gentle');
  const percent = value === null ? null : Math.max(0, Math.min(100, value));
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
        aria-valuemin={percent === null ? undefined : 0}
        aria-valuemax={percent === null ? undefined : 100}
        aria-valuenow={percent ?? undefined}
        className="h-2 overflow-hidden rounded-full bg-border"
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

export function Skeleton({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      {...props}
      aria-hidden
      className={cn('skeleton h-4 rounded-sm', className)}
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
};
/** A round frame for a portrait, an illustration or a name's first character. */
export function AvatarFrame({
  size = 'lg',
  children,
}: {
  size?: keyof typeof frameSizes;
  children: ReactNode;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        'grid shrink-0 place-items-center overflow-hidden rounded-full bg-soft font-semibold text-accent',
        frameSizes[size],
      )}
    >
      {children}
    </span>
  );
}
