import {
  useLayoutEffect,
  useRef,
  type ComponentProps,
  type ReactNode,
} from 'react';
import { LoaderCircle } from 'lucide-react';
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
    secondary: 'border border-border bg-surface text-primary hover:bg-canvas',
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
        'inline-flex shrink-0 items-center justify-center gap-2 rounded-full font-medium disabled:cursor-not-allowed disabled:opacity-50',
        variants[variant],
        {
          sm: 'min-h-11 px-3 text-sm',
          md: 'min-h-11 px-4',
          lg: 'min-h-12 px-5 text-md',
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
      className={cn('size-11 p-0', props.className)}
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
        'min-h-11 w-full rounded-md border border-border bg-surface px-3 text-md text-primary placeholder:text-tertiary disabled:opacity-50',
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
        'w-full resize-none rounded-md border border-border bg-surface px-3 py-2 text-md leading-6 placeholder:text-tertiary disabled:opacity-50',
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
