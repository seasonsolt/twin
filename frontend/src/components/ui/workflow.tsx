import {
  useImperativeHandle,
  useId,
  type ComponentProps,
  type ReactNode,
  type Ref,
} from 'react';
import { Link } from 'react-router';
import {
  ChevronRight,
  LoaderCircle,
  Pause,
  Play,
  RotateCcw,
} from 'lucide-react';
import { Button, IconButton } from './controls';
import { useClipAudio } from './useClipAudio';
import { cn } from '../../lib/utils';

/** Route navigation with the same appearance as an action button. */
export function RouteButton({
  variant = 'primary',
  size = 'md',
  ...props
}: ComponentProps<typeof Link> & {
  variant?: 'primary' | 'secondary' | 'ghost';
  size?: 'sm' | 'md';
}) {
  return (
    <Link
      {...props}
      className={cn(
        'inline-flex min-h-9 items-center justify-center gap-2 rounded-sm px-4 font-medium',
        size === 'sm' && 'min-h-8 px-3 text-sm',
        variant === 'primary'
          ? 'bg-accent text-on-accent hover:bg-accent-hover'
          : variant === 'secondary'
            ? 'border border-tertiary/60 bg-surface text-primary hover:bg-soft'
            : 'text-secondary hover:bg-soft',
        props.className,
      )}
    />
  );
}

/** The whole identity header is one target, whether it opens a profile or an editor. */
export function IdentityLink({
  to,
  onClick,
  label,
  children,
}: {
  to?: string;
  onClick: () => void;
  label: string;
  children: ReactNode;
}) {
  const content = (
    <>
      {children}
      <ChevronRight aria-hidden className="size-4 shrink-0 text-tertiary" />
    </>
  );
  const classes = 'flex w-full items-center gap-3 text-left hover:opacity-80';
  return to ? (
    <Link
      to={to}
      aria-label={label}
      className={classes}
      onClick={(event) => {
        event.preventDefault();
        onClick();
      }}
    >
      {content}
    </Link>
  ) : (
    <button
      type="button"
      aria-label={label}
      className={classes}
      onClick={onClick}
    >
      {content}
    </button>
  );
}

/** Keep the current decision within reach on phones, in normal flow on desktop. */
export function DecisionBar({
  children,
  secondary,
}: {
  children: ReactNode;
  secondary?: ReactNode;
}) {
  return (
    <div className="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-3 border-t border-border bg-surface p-3 rounded-b-lg md:static md:border-0 md:px-6 md:pb-6 md:pt-0">
      <div className="flex flex-wrap items-center gap-3">{children}</div>
      {secondary && (
        <div className="flex flex-wrap items-center gap-2">{secondary}</div>
      )}
    </div>
  );
}

export function AudioPlayer(
  props: Pick<ComponentProps<'audio'>, 'src' | 'aria-label'>,
) {
  const player = useClipAudio(props.src, true);
  const errorId = useId();
  return (
    <>
      <audio
        {...props}
        key={props.src}
        ref={player.audio}
        aria-describedby={player.error ? errorId : undefined}
        controls
        preload="none"
        className="h-11 w-full"
      />
      {player.error && (
        <span className="flex items-center gap-2 text-sm text-danger">
          <span id={errorId} role="alert">
            {player.error}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={player.toggle}
            aria-label={`重试${props['aria-label'] ?? '试听'}`}
          >
            重试
          </Button>
        </span>
      )}
    </>
  );
}

/** What a shortcut key can do to a clip button. */
export interface ClipControls {
  toggle: () => void;
}

/** A round play/pause button for a short clip, heard where it is listed without a player taking up a row. With a
 * ``caption`` it is a small text button instead, for a clip heard beside the main one (a reference to compare with). */
export function ClipButton({
  src,
  label,
  caption,
  size = 'lg',
  controls,
}: {
  src: string;
  label: string;
  caption?: string;
  /** lg 44px (default), md 36px for a clip inside a list row or card. */
  size?: 'md' | 'lg';
  /** Play or pause from outside, for a shortcut key. */
  controls?: Ref<ClipControls>;
}) {
  const { audio, playing, loading, error, toggle } = useClipAudio(src);
  const errorId = useId();
  useImperativeHandle(controls, () => ({ toggle }));
  const action = playing
    ? `暂停${label}`
    : loading
      ? `停止${label}`
      : error
        ? `重试${label}`
        : label;
  const icon = loading ? (
    <LoaderCircle
      aria-hidden
      className="size-4 animate-spin motion-reduce:animate-none"
    />
  ) : error ? (
    <RotateCcw aria-hidden className="size-4" />
  ) : playing ? (
    <Pause aria-hidden className="size-4" />
  ) : (
    <Play aria-hidden className="size-4" />
  );
  return (
    <>
      {caption ? (
        <Button
          type="button"
          variant={error ? 'danger' : 'ghost'}
          size="sm"
          aria-label={action}
          title={error || undefined}
          aria-pressed={playing}
          aria-busy={loading}
          aria-describedby={error ? errorId : undefined}
          onClick={toggle}
        >
          {icon}
          {caption}
        </Button>
      ) : (
        <IconButton
          label={action}
          shape="circle"
          size={size}
          variant={error ? 'danger' : 'secondary'}
          title={error || undefined}
          aria-pressed={playing}
          aria-busy={loading}
          aria-describedby={error ? errorId : undefined}
          onClick={toggle}
        >
          {icon}
        </IconButton>
      )}
      <audio key={src} ref={audio} src={src} preload="none" />
      {error && (
        <span id={errorId} role="alert" className="sr-only">
          {error}
        </span>
      )}
    </>
  );
}

/** A large selectable voice match; choosing it does not submit the decision. */
export function VoiceChoice({
  selected,
  children,
  onClick,
  disabled,
}: {
  selected: boolean;
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <Button
      variant={selected ? 'primary' : 'secondary'}
      size="lg"
      aria-pressed={selected}
      disabled={disabled}
      onClick={onClick}
      className="flex-1 py-3"
    >
      {children}
    </Button>
  );
}
