import { useId, type ComponentProps, type ReactNode } from 'react';
import { motion } from 'motion/react';
import { NavLink } from 'react-router';
import {
  AudioLines,
  BookOpen,
  ClipboardList,
  FileText,
  MessagesSquare,
  Mic,
  PenLine,
  Video,
  type LucideIcon,
} from 'lucide-react';
import { useMotionPreset } from '../../design/motion';
import { cn } from '../../lib/utils';

/* The 素体 pieces: frosted glass over the twin's core, the pill that moves between 对话, 记忆 and 资料, where an
   answer comes from, and the twin's own words rising into view. They read the theme tokens, so they work in every
   palette, but are drawn for the dark 素体 ones. */

const glassPadding = { none: '', md: 'p-5', lg: 'p-7' };

/** A frosted layer floating over the core or the memory graph. */
export function GlassPanel({
  as: Tag = 'section',
  padding = 'md',
  strong = false,
  className,
  children,
  ...props
}: {
  as?: 'section' | 'div' | 'article' | 'aside';
  padding?: keyof typeof glassPadding;
  /** Denser glass, for a panel that holds reading (a card of quotes) rather than a control. */
  strong?: boolean;
  /** Layout only (width, placement, spacing between children). */
  className?: string;
  children: ReactNode;
} & Pick<
  ComponentProps<'section'>,
  'id' | 'role' | 'aria-label' | 'aria-labelledby' | 'aria-live'
>) {
  return (
    <Tag
      {...props}
      className={cn(
        'rounded-glass border border-glass-line shadow-glass backdrop-blur-xl backdrop-saturate-150',
        strong ? 'bg-glass-strong' : 'bg-glass',
        glassPadding[padding],
        className,
      )}
    >
      {children}
    </Tag>
  );
}

export interface PillNavItem {
  to: string;
  label: string;
}

/** The few places of the app as one glass pill; the current one is a porcelain pill that springs between them. */
export function PillNav({
  items,
  label = '主导航',
}: {
  items: readonly PillNavItem[];
  label?: string;
}) {
  const id = useId();
  const { transition } = useMotionPreset('layout');
  return (
    <nav
      aria-label={label}
      className="flex rounded-full border border-glass-line bg-glass p-1 shadow-glass backdrop-blur-xl backdrop-saturate-150"
    >
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) =>
            cn(
              'relative grid h-9 w-18 place-items-center rounded-full text-base transition-colors',
              isActive
                ? 'font-medium text-canvas'
                : 'text-tertiary hover:text-primary',
            )
          }
        >
          {({ isActive }) => (
            <>
              {isActive && (
                <motion.span
                  aria-hidden
                  layoutId={`pill-${id}`}
                  transition={transition}
                  className="absolute inset-0 rounded-full bg-primary"
                />
              )}
              <span className="relative">{item.label}</span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}

/** Where a line of the twin's comes from (日记 · 2023-04-12), or that two of the person's own sayings disagree. */
export function CitationChip({
  kind = 'source',
  onClick,
  children,
}: {
  /** 'conflict': the person said both; drawn dashed, with no source dot. */
  kind?: 'source' | 'conflict';
  /** Opens what the line rests on; without it the chip only says where it comes from. */
  onClick?: () => void;
  children: ReactNode;
}) {
  const className = cn(
    'inline-flex h-6 items-center gap-1.5 rounded-full border bg-glass px-3 font-mono text-xs text-secondary',
    kind === 'conflict'
      ? 'border-dashed border-accent/60'
      : 'border-glass-line',
    onClick && 'hover:text-primary',
  );
  const content = (
    <>
      {kind === 'source' && (
        <span aria-hidden className="size-1.5 rounded-full bg-accent" />
      )}
      {children}
    </>
  );
  return onClick ? (
    <button type="button" onClick={onClick} className={className}>
      {content}
    </button>
  ) : (
    <span className={className}>{content}</span>
  );
}

const riseSize = { md: 'text-xl', lg: 'text-2xl' };

/** The twin's own words in its voice (a Song face), rising out of a blur the first time they are shown. */
export function RiseText({
  as = 'p',
  size = 'md',
  delay = 0,
  children,
}: {
  as?: 'p' | 'span';
  /** 'lg' for the line just said, 'md' for what came before. */
  size?: keyof typeof riseSize;
  /** Seconds to wait, for lines that follow one another. */
  delay?: number;
  children: ReactNode;
}) {
  const { reduced } = useMotionPreset('gentle');
  const Tag = as === 'span' ? motion.span : motion.p;
  return (
    <Tag
      initial={
        reduced ? { opacity: 0 } : { opacity: 0, y: 12, filter: 'blur(10px)' }
      }
      animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
      transition={{
        duration: reduced ? 0.15 : 0.9,
        delay: reduced ? 0 : delay,
        ease: [0.2, 0.7, 0.2, 1],
      }}
      className={cn(
        'm-0 font-voice leading-relaxed font-light tracking-wide text-primary',
        riseSize[size],
      )}
    >
      {children}
    </Tag>
  );
}

const OBJECTS: Record<string, LucideIcon> = {
  diary: BookOpen,
  chat: MessagesSquare,
  questionnaire: ClipboardList,
  interview: Mic,
  video: Video,
  audio: AudioLines,
  document: FileText,
};

/**
 * What a piece of material is, as the thing itself: a diary, a chat, a recording, a page. A note the person wrote here
 * (labelled 笔记) is a pen whatever kind it was read as.
 */
export function SourceObject({
  kind,
  label,
}: {
  kind?: string;
  label?: string;
}) {
  const Icon = label === '笔记' ? PenLine : (OBJECTS[kind ?? ''] ?? FileText);
  return (
    <span
      role="img"
      aria-label={label || '资料'}
      className="grid size-11 shrink-0 place-items-center rounded-full border border-glass-line bg-glass text-primary shadow-glass"
    >
      <Icon size={20} aria-hidden />
    </span>
  );
}
