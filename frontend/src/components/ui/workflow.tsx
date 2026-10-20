import { useRef, useState, type ComponentProps, type ReactNode } from 'react';
import { Link } from 'react-router';
import { ChevronRight, Pause, Play } from 'lucide-react';
import { Button, IconButton } from './controls';
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
  return <audio {...props} controls preload="none" className="h-11 w-full" />;
}

/** A round play/pause button for a short clip, heard where it is listed without a player taking up a row. With a
 * ``caption`` it is a small text button instead, for a clip heard beside the main one (a reference to compare with). */
export function ClipButton({
  src,
  label,
  caption,
  size = 'lg',
}: {
  src: string;
  label: string;
  caption?: string;
  /** lg 44px (default), md 36px for a clip inside a list row or card. */
  size?: 'md' | 'lg';
}) {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const toggle = () => {
    const element = audio.current;
    if (!element) return;
    if (playing) element.pause();
    else void element.play().catch(() => setPlaying(false));
  };
  const icon = playing ? (
    <Pause aria-hidden className="size-4" />
  ) : (
    <Play aria-hidden className="size-4" />
  );
  return (
    <>
      {caption ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label={playing ? `暂停${label}` : label}
          aria-pressed={playing}
          onClick={toggle}
        >
          {icon}
          {caption}
        </Button>
      ) : (
        <IconButton
          label={playing ? `暂停${label}` : label}
          shape="circle"
          size={size}
          variant="secondary"
          aria-pressed={playing}
          onClick={toggle}
        >
          {icon}
        </IconButton>
      )}
      <audio
        ref={audio}
        src={src}
        preload="none"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
      />
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
