import {
  useLayoutEffect,
  useRef,
  type ComponentProps,
  type ReactNode,
} from 'react';
import { ChevronDown, LoaderCircle } from 'lucide-react';
import type { HTMLMotionProps } from 'motion/react';
import { Pressable } from '../motion';
import { cn } from '../../lib/utils';

export type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';
export const toneClasses: Record<Tone, string> = {
  neutral: 'text-secondary',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  info: 'text-info',
};

export type ButtonProps = Omit<HTMLMotionProps<'button'>, 'children'> & {
  children?: ReactNode;
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
};
export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled,
  className,
  children,
  ...props
}: ButtonProps) {
  const variants = {
    primary:
      'bg-accent text-on-accent hover:bg-accent-hover active:bg-accent-pressed',
    secondary:
      'border border-tertiary/60 bg-surface text-primary hover:bg-soft',
    ghost: 'bg-transparent text-secondary hover:bg-surface-raised',
    danger:
      'border border-danger/30 bg-danger/10 text-danger hover:bg-danger/20',
  };
  return (
    <Pressable
      {...props}
      disabled={disabled || loading}
      aria-busy={loading}
      className={cn(
        'inline-flex shrink-0 items-center justify-center gap-2 rounded-sm font-medium disabled:cursor-not-allowed disabled:opacity-50',
        variants[variant],
        {
          sm: 'min-h-8 px-3 text-sm',
          md: 'min-h-9 px-4',
          lg: 'min-h-10 px-5 text-md',
        }[size],
        className,
      )}
    >
      {loading && (
        <LoaderCircle
          aria-hidden
          className="size-4 animate-spin motion-reduce:animate-none"
        />
      )}
      {children}
    </Pressable>
  );
}

export function IconButton({
  label,
  children,
  ...props
}: Omit<ButtonProps, 'children'> & { label: string; children: ReactNode }) {
  return (
    <Button
      variant="ghost"
      {...props}
      aria-label={label}
      className={cn('size-9 p-0', props.className)}
    >
      {children}
    </Button>
  );
}

export function Input({ className, ...props }: ComponentProps<'input'>) {
  return (
    <input
      {...props}
      className={cn(
        'min-h-9 w-full rounded-sm border border-tertiary/60 bg-surface px-3 text-primary placeholder:text-tertiary hover:border-tertiary disabled:opacity-50',
        className,
      )}
    />
  );
}

export function Textarea({
  onSend,
  onKeyDown,
  className,
  value,
  rows = 2,
  maxRows,
  ...props
}: ComponentProps<'textarea'> & { onSend?: () => void; maxRows?: number }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const composing = useRef(false);
  const resize = () => {
    if (!ref.current) return;
    ref.current.style.height = 'auto';
    const style = window.getComputedStyle(ref.current);
    const lineHeight = parseFloat(style.lineHeight) || 24;
    const padding =
      (parseFloat(style.paddingTop) || 0) +
      (parseFloat(style.paddingBottom) || 0);
    const maximum = maxRows ? lineHeight * maxRows + padding + 2 : 240;
    ref.current.style.height = `${Math.min(Math.max(ref.current.scrollHeight, lineHeight * rows + padding + 2), maximum)}px`;
  };
  useLayoutEffect(resize, [value, maxRows, rows]);
  return (
    <textarea
      {...props}
      ref={ref}
      value={value}
      rows={rows}
      className={cn(
        'w-full resize-none rounded-sm border border-tertiary/60 bg-surface px-3 py-2 leading-6 placeholder:text-tertiary hover:border-tertiary disabled:opacity-50',
        className,
      )}
      onChange={(event) => {
        resize();
        props.onChange?.(event);
      }}
      onCompositionStart={(event) => {
        composing.current = true;
        props.onCompositionStart?.(event);
      }}
      onCompositionEnd={(event) => {
        composing.current = false;
        props.onCompositionEnd?.(event);
      }}
      onKeyDown={(event) => {
        onKeyDown?.(event);
        if (
          !event.defaultPrevented &&
          event.key === 'Enter' &&
          !event.shiftKey &&
          !event.nativeEvent.isComposing &&
          !composing.current &&
          event.keyCode !== 229 &&
          onSend
        ) {
          event.preventDefault();
          onSend();
        }
      }}
    />
  );
}

export function Field({
  id,
  label,
  help,
  error,
  children,
}: {
  id: string;
  label: string;
  help?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block font-medium">
        {label}
      </label>
      {children}
      {(help || error) && (
        <p
          id={`${id}-description`}
          className={cn('text-sm', error ? 'text-danger' : 'text-secondary')}
          role={error ? 'alert' : undefined}
        >
          {error ?? help}
        </p>
      )}
    </div>
  );
}

/** A native drop-down, styled like Input; options are <option> children. Label it with Field or aria-label. */
export function Select({
  className,
  children,
  ...props
}: Omit<ComponentProps<'select'>, 'style'>) {
  return (
    <span className={cn('relative inline-flex min-w-0', className)}>
      <select
        {...props}
        className="min-h-9 w-full min-w-0 appearance-none rounded-sm border border-tertiary/60 bg-surface py-1 pr-9 pl-3 text-primary hover:border-tertiary disabled:opacity-50"
      >
        {children}
      </select>
      <ChevronDown
        aria-hidden
        className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-secondary"
      />
    </span>
  );
}

type ChoiceProps = Omit<
  ComponentProps<'input'>,
  'type' | 'className' | 'style' | 'size'
> & {
  label: ReactNode;
  /** Extra content on the same line after the label, such as a badge. */
  children?: ReactNode;
};
function Choice({
  type,
  label,
  children,
  disabled,
  ...props
}: ChoiceProps & { type: 'checkbox' | 'radio' }) {
  return (
    <label
      className={cn(
        'inline-flex min-h-11 items-center gap-3 md:min-h-9',
        disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
      )}
    >
      <input
        {...props}
        type={type}
        disabled={disabled}
        className="size-4 shrink-0 accent-accent max-md:size-5"
      />
      <span>{label}</span>
      {children}
    </label>
  );
}
/** A checkbox with its label; the whole line is clickable. */
export function Checkbox(props: ChoiceProps) {
  return <Choice {...props} type="checkbox" />;
}
/** One radio button with its label; give the ones that belong together the same `name`. */
export function Radio(props: ChoiceProps) {
  return <Choice {...props} type="radio" />;
}

/** A pill that can be switched on and off (a filter), or just shown when it has no onClick. */
export function Chip({
  pressed,
  onClick,
  disabled,
  children,
  ...props
}: {
  pressed?: boolean;
  onClick?: () => void;
  disabled?: boolean;
  children: ReactNode;
} & Pick<ComponentProps<'button'>, 'aria-label' | 'title'>) {
  const styles = cn(
    'inline-flex min-h-8 items-center gap-1.5 rounded-full border px-3 text-sm',
    pressed
      ? 'border-primary bg-primary text-canvas'
      : 'border-border bg-surface text-secondary',
  );
  return onClick ? (
    <button
      {...props}
      type="button"
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        styles,
        !pressed && 'hover:bg-soft',
        'disabled:cursor-not-allowed disabled:opacity-50',
      )}
    >
      {children}
    </button>
  ) : (
    <span {...props} className={styles}>
      {children}
    </span>
  );
}
