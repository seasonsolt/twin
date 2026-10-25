import {
  cloneElement,
  type ComponentProps,
  type ReactElement,
  type ReactNode,
} from 'react';
import { motion } from 'motion/react';
import { Link } from 'react-router';
import {
  Check,
  ChevronDown,
  Inbox,
  MoreHorizontal,
  type LucideIcon,
} from 'lucide-react';
import { useMotionPreset } from '../../design/motion';
import { Pressable } from '../motion';
import { cn } from '../../lib/utils';
import { buttonClasses, toneClasses, type Tone } from './controls';

const cardVariants = {
  /** Content inside an existing card, with padding but no second surface. */
  plain: '',
  /** White card lifted off the canvas (the default). */
  raised: 'bg-surface shadow-card',
  /** White card with a hairline border, for blocks inside a page section. */
  outline: 'border border-border bg-surface',
  /** Warm note colour, for a prompt the person should read. */
  note: 'bg-note',
  /** Tinted, for something set back from the content around it. */
  soft: 'bg-soft',
  /** Hairline dashes, for something that stands but may no longer be so. */
  dashed: 'border border-dashed border-tertiary bg-surface',
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

/** A Badge that opens something under it (what an answer rests on): a button with a caret, `open` says whether it is. */
export function BadgeToggle({
  tone = 'neutral',
  open,
  className,
  children,
  ...props
}: Omit<ComponentProps<'button'>, 'type'> & { tone?: Tone; open: boolean }) {
  return (
    <button
      {...props}
      type="button"
      aria-expanded={open}
      className={cn(
        'inline-flex min-h-8 items-center gap-1 rounded-full border border-current/15 bg-current/5 px-2.5 py-0.5 text-xs font-medium hover:bg-current/10',
        toneClasses[tone],
        className,
      )}
    >
      {children}
      <ChevronDown
        aria-hidden
        className={cn('size-3.5 shrink-0', open && 'rotate-180')}
      />
    </button>
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
  scroll = true,
}: {
  caption: string;
  headers: string[];
  rows: ReactNode[][];
  /**
   * Scroll sideways when too wide (the default). Off for a table whose rows open menus, which a scrolling box would
   * cut off: on a desktop it then lays out at full width; a phone keeps each cell on one line and scrolls it rather
   * than widen the page or break its words a character at a time.
   */
  scroll?: boolean;
}) {
  return (
    <div
      className={cn(
        'rounded-md border border-border',
        scroll ? 'overflow-x-auto' : 'max-md:overflow-x-auto',
      )}
    >
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
                <td
                  key={j}
                  className={cn(
                    'px-4 py-3',
                    !scroll && 'max-md:whitespace-nowrap',
                  )}
                >
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

/**
 * A small card that is one link: a heading with where it leads on the right, a line under it, and how far the
 * current piece of work has got (the side bar's 后台 card).
 */
export function StatusCard({
  to,
  title,
  action,
  detail,
  progress,
}: {
  /** Where the card leads; none when the person is already there, and then it only reports. */
  to?: string;
  title: string;
  /** What following the card does (shown only with `to`). */
  action: string;
  detail?: string;
  progress?: { value: number | null; max: number; label: string };
}) {
  const body = (
    <>
      <span className="flex justify-between gap-2 text-xs">
        <span className="font-medium">{title}</span>
        {to && <span className="text-secondary">{action} ›</span>}
      </span>
      {detail && <span className="text-xs text-secondary">{detail}</span>}
      {progress && (
        <Meter
          size="sm"
          hideLabel
          value={progress.value}
          max={progress.max}
          label={progress.label}
        />
      )}
    </>
  );
  const frame =
    'flex flex-col gap-1.5 rounded-md border border-border bg-surface px-3 py-2.5 text-primary';
  return to ? (
    <Link
      to={to}
      className={`${frame} hover:border-tertiary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent`}
    >
      {body}
    </Link>
  ) : (
    <div className={frame}>{body}</div>
  );
}

const noticeTones = {
  success: 'border border-success/20 bg-success/5 text-primary',
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
  stackOnMobile = false,
  leading,
  title,
  meta,
  trailing,
  children,
  ...props
}: {
  as?: 'li' | 'div' | 'article';
  /** Put details above actions instead of squeezing the filename on phones. */
  stackOnMobile?: boolean;
  /** card: white row on the canvas; outline: hairline border; plain: no box, for rows inside a card. */
  variant?: 'card' | 'outline' | 'plain' | 'divided' | 'dashed';
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
        variant === 'divided' && 'border-b border-border py-3 last:border-b-0',
        variant === 'dashed' &&
          'rounded-md border border-dashed border-border p-3',
      )}
    >
      {leading && <div className="shrink-0">{leading}</div>}
      <div
        className={cn(
          'min-w-0 flex-1 space-y-1',
          stackOnMobile && 'max-md:basis-full',
        )}
      >
        <div className="min-w-0 font-medium">{title}</div>
        {meta && <div className="text-sm text-secondary">{meta}</div>}
        {children}
      </div>
      {trailing && (
        <div
          className={cn(
            'flex flex-wrap items-center gap-2',
            stackOnMobile && 'max-md:w-full max-md:justify-end',
          )}
        >
          {trailing}
        </div>
      )}
    </Tag>
  );
}

/**
 * One thing to settle in a list: a mark or clip, a title, one line of details, an optional hint line, extra content
 * under them (answers offered in one click), and the actions. With `actionsWidth="field"` the actions get a fixed
 * column, so a list of rows with the same controls (a name field, confirm, menu) lines up; "auto" sizes it to the
 * buttons, right-aligned. Render a list of them inside <Stack as="ul" gap={0}>.
 */
export function TaskRow({
  as: Tag = 'li',
  leading,
  title,
  meta,
  hint,
  children,
  actions,
  actionsWidth = 'auto',
  ...props
}: {
  as?: 'li' | 'div';
  /** A clip button or a StatusDot; the column stays when it is absent. */
  leading?: ReactNode;
  title: ReactNode;
  /** One line, cut with an ellipsis. */
  meta?: ReactNode;
  /** One more line, quieter than `meta`. */
  hint?: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  actionsWidth?: 'auto' | 'field';
} & Pick<ComponentProps<'li'>, 'id' | 'aria-label'>) {
  return (
    <Tag
      {...props}
      className={cn(
        'grid items-start gap-x-4 gap-y-2 border-b border-border py-3 last:border-b-0',
        actionsWidth === 'field'
          ? 'grid-cols-[2.25rem_minmax(0,1fr)] md:grid-cols-[2.25rem_minmax(0,1fr)_20rem]'
          : 'grid-cols-[2.25rem_minmax(0,1fr)] md:grid-cols-[2.25rem_minmax(0,1fr)_auto]',
      )}
    >
      <div className="grid min-h-9 place-items-center">{leading}</div>
      <div className="min-w-0 space-y-1 pt-1">
        <div className="truncate font-medium">{title}</div>
        {meta && <div className="truncate text-sm text-secondary">{meta}</div>}
        {hint && <div className="truncate text-sm text-tertiary">{hint}</div>}
        {children}
      </div>
      {actions && (
        <div
          className={cn(
            'col-span-2 flex items-center gap-2 md:col-span-1',
            actionsWidth === 'auto' && 'justify-end',
          )}
        >
          {actions}
        </div>
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
 * The people in something, as overlapping round initials: up to `max`, then +n, and a "?" when some speakers are
 * still unnamed. One image for screen readers, who get the names.
 */
export function AvatarStack({
  names,
  unknown = 0,
  max = 4,
}: {
  names: string[];
  /** How many speakers nobody has named yet. */
  unknown?: number;
  max?: number;
}) {
  const shown = names.slice(0, max);
  const rest = names.length - shown.length;
  if (!names.length && !unknown) return null;
  return (
    <span
      role="img"
      aria-label={`参会人：${names.join('、')}${unknown ? `${names.length ? '，' : ''}${unknown} 位没认出` : ''}`}
      className="flex items-center -space-x-2"
    >
      {shown.map((name) => (
        <AvatarFrame key={name} size="sm" outlined>
          {Array.from(name)[0]}
        </AvatarFrame>
      ))}
      {rest > 0 && (
        <AvatarFrame size="sm" outlined>
          +{rest}
        </AvatarFrame>
      )}
      {unknown > 0 && (
        <AvatarFrame size="sm" outlined muted>
          ?
        </AvatarFrame>
      )}
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

/**
 * The number of a step in a short how-it-works list. In a list worked through in order, `state` marks the steps:
 * done shows a tick, current is filled with the accent, pending is only outlined.
 */
export function StepNumber({
  state,
  size = 'md',
  children,
}: {
  state?: 'done' | 'current' | 'pending';
  /** sm: beside a line of text in a card. */
  size?: 'sm' | 'md';
  children: ReactNode;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        'grid shrink-0 place-items-center rounded-full font-semibold',
        size === 'sm' ? 'size-6 text-xs' : 'size-8',
        state === undefined && 'bg-primary text-canvas',
        state === 'done' && 'bg-success text-on-accent',
        state === 'current' && 'bg-accent text-on-accent',
        state === 'pending' && 'border-2 border-tertiary/50 text-tertiary',
      )}
    >
      {state === 'done' ? (
        <Check className={size === 'sm' ? 'size-3.5' : 'size-4'} />
      ) : (
        children
      )}
    </span>
  );
}

/**
 * The steps of a short flow worked through in order, in a line: the ones before `current` are done (a tick), the
 * current one is filled and named to assistive technology as the current step, the rest are only outlined.
 */
export function Steps({
  label,
  steps,
  current,
}: {
  /** Names the list, such as "步骤". */
  label: string;
  steps: string[];
  /** Index of the step under way. */
  current: number;
}) {
  return (
    <ol aria-label={label} className="flex items-center gap-3 text-sm">
      {steps.map((step, index) => (
        <li
          key={step}
          aria-current={index === current ? 'step' : undefined}
          className={cn(
            'flex items-center gap-3',
            index === current ? 'font-medium' : 'text-secondary',
          )}
        >
          {index > 0 && <span aria-hidden className="h-px w-6 bg-border" />}
          <span className="flex items-center gap-1.5">
            <StepNumber
              size="sm"
              state={
                index < current
                  ? 'done'
                  : index === current
                    ? undefined
                    : 'pending'
              }
            >
              {index + 1}
            </StepNumber>
            {step}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** One action in an `ActionMenu`. */
export interface ActionItem {
  label: string;
  onSelect: () => void;
  disabled?: boolean;
  /** A leading icon, where it helps the eye find the item among the others. */
  icon?: LucideIcon;
  /** How many wait there (抽查声线 1): a small badge on the right. Nothing when 0. */
  count?: number;
  /** A quiet word on the right about where it stands (未绑定). */
  status?: string;
  /** Deletes or takes something back: set apart at the end, after a divider, in the danger colour. */
  danger?: boolean;
}

function ActionMenuItem({ item }: { item: ActionItem }) {
  const Icon = item.icon;
  return (
    <button
      type="button"
      disabled={item.disabled}
      // Read as one phrase: 抽查声线 2, 绑定企业账号 未绑定.
      aria-label={
        item.status || item.count
          ? [item.label, item.status, item.count || '']
              .filter(Boolean)
              .join(' ')
          : undefined
      }
      className={cn(
        'flex min-h-9 w-full items-center gap-2 rounded-sm px-3 text-left text-sm whitespace-nowrap disabled:cursor-not-allowed disabled:opacity-50',
        item.danger
          ? 'text-danger hover:bg-danger/10'
          : 'text-primary hover:bg-surface-raised',
      )}
      onClick={(event) => {
        const menu = event.currentTarget.closest('details');
        menu?.removeAttribute('open');
        // The button that had the focus is hidden now: the focus goes back to the "⋯" it came from.
        menu?.querySelector('summary')?.focus();
        item.onSelect();
      }}
    >
      {Icon && (
        <Icon
          aria-hidden
          className={cn('size-4 shrink-0', !item.danger && 'text-secondary')}
        />
      )}
      <span className="flex-1">{item.label}</span>
      {item.status && (
        <span className="text-xs text-tertiary">{item.status}</span>
      )}
      {!!item.count && (
        <span className="grid min-w-5 place-items-center rounded-full bg-accent px-1.5 text-xs font-semibold text-on-accent">
          {item.count}
        </span>
      )}
    </button>
  );
}

/**
 * A round "⋯" button that opens a short list of actions below it; choosing one closes the list. Destructive items
 * (`danger`) come last, after a divider, whatever their place in `items`. `className` places the menu (for example
 * absolute in a card's corner).
 */
export function ActionMenu({
  label,
  items,
  className,
  text,
}: {
  label: string;
  items: ActionItem[];
  className?: string;
  /** Words on the button (a secondary button with a caret, such as “添加”) instead of the round “⋯”. */
  text?: string;
}) {
  const ordinary = items.filter((item) => !item.danger);
  const destructive = items.filter((item) => item.danger);
  return (
    <details className={cn('relative', className)}>
      <summary
        aria-label={text ? undefined : label}
        className={cn(
          'cursor-pointer list-none [&::-webkit-details-marker]:hidden',
          text
            ? buttonClasses({ variant: 'secondary' })
            : 'grid size-11 place-items-center rounded-full text-secondary hover:bg-soft',
        )}
      >
        {text ? (
          <>
            {text}
            <ChevronDown size={16} aria-hidden />
          </>
        ) : (
          <MoreHorizontal size={20} aria-hidden />
        )}
      </summary>
      <div className="absolute right-0 z-10 grid min-w-28 rounded-lg border border-border bg-surface p-1 shadow-elevation-2">
        {ordinary.map((item) => (
          <ActionMenuItem key={item.label} item={item} />
        ))}
        {ordinary.length > 0 && destructive.length > 0 && (
          <hr aria-hidden className="my-1 border-border" />
        )}
        {destructive.map((item) => (
          <ActionMenuItem key={item.label} item={item} />
        ))}
      </div>
    </details>
  );
}

// Quiet when all is well, so a failed hour is what the eye finds.
const historyTones = {
  none: 'bg-soft',
  success: 'bg-success/35',
  warning: 'bg-warning/60',
  danger: 'bg-danger',
};
/**
 * A strip of equal slots, one per period (an hour of health checks), coloured by how that period went. Read as one
 * image named `label`; each slot's `title` says what it holds.
 */
export function HistoryBar({
  label,
  slots,
}: {
  label: string;
  slots: {
    key: string | number;
    tone: keyof typeof historyTones;
    title: string;
  }[];
}) {
  return (
    <div role="img" aria-label={label} className="flex h-4 gap-px">
      {slots.map((slot) => (
        <span
          key={slot.key}
          title={slot.title}
          className={cn('flex-1 rounded-[1px]', historyTones[slot.tone])}
        />
      ))}
    </div>
  );
}
