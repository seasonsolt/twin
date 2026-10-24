import {
  useId,
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

const buttonVariants = {
  primary:
    'bg-accent text-on-accent hover:bg-accent-hover active:bg-accent-pressed',
  secondary: 'border border-tertiary/60 bg-surface text-primary hover:bg-soft',
  ghost: 'bg-transparent text-secondary hover:bg-surface-raised',
  danger: 'border border-danger/30 bg-danger/10 text-danger hover:bg-danger/20',
};
const buttonSizes = {
  sm: 'min-h-8 px-3 text-sm',
  md: 'min-h-9 px-4',
  lg: 'min-h-10 px-5 text-md',
};
type ButtonLook = {
  variant?: keyof typeof buttonVariants;
  size?: keyof typeof buttonSizes;
  /** pill: fully rounded ends, for a lone action on a photo or video. */
  shape?: 'default' | 'pill';
};
/** A button's classes, for something that must look like one but cannot be a Button (a menu's `<summary>`). */
export const buttonClasses = ({
  variant = 'primary',
  size = 'md',
  shape = 'default',
}: ButtonLook) =>
  cn(
    'inline-flex shrink-0 items-center justify-center gap-2 font-medium disabled:cursor-not-allowed disabled:opacity-50',
    shape === 'pill' ? 'rounded-full' : 'rounded-sm',
    buttonVariants[variant],
    buttonSizes[size],
  );

export type ButtonProps = Omit<HTMLMotionProps<'button'>, 'children'> &
  ButtonLook & {
    children?: ReactNode;
    loading?: boolean;
  };
export function Button({
  variant,
  size,
  shape,
  loading = false,
  disabled,
  className,
  children,
  ...props
}: ButtonProps) {
  return (
    <Pressable
      {...props}
      disabled={disabled || loading}
      aria-busy={loading || props['aria-busy'] || false}
      className={cn(buttonClasses({ variant, size, shape }), className)}
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

/** A link (a download, another site) that looks like a Button. `className` is for layout only. */
export function LinkButton({
  variant,
  size,
  shape,
  className,
  ...props
}: ComponentProps<'a'> & ButtonLook) {
  return (
    <a
      {...props}
      className={cn(buttonClasses({ variant, size, shape }), className)}
    />
  );
}

/**
 * A bare round-ended button for the app's own chrome: a portrait that opens the twin switcher, a selectable row in
 * it. It has the shape and nothing else: no colour, padding or hover lift, so the caller's layout classes set those.
 * For an ordinary action use Button or IconButton.
 */
export function PlainButton({
  shape = 'pill',
  className,
  ...props
}: ComponentProps<'button'> & {
  /** pill: fully rounded ends. circle: also centres its content, for a portrait or a count. */
  shape?: 'pill' | 'circle';
}) {
  return (
    <button
      type="button"
      {...props}
      className={cn(
        'rounded-full',
        shape === 'circle' && 'grid shrink-0 place-items-center',
        className,
      )}
    />
  );
}

export function IconButton({
  label,
  children,
  shape = 'square',
  size,
  ...props
}: Omit<ButtonProps, 'children' | 'size' | 'shape'> & {
  label: string;
  children: ReactNode;
  /** circle: a round button, such as send or attach in a composer. */
  shape?: 'square' | 'circle';
  /** md 36px (default), lg 44px. */
  size?: 'md' | 'lg';
}) {
  return (
    <Button
      variant="ghost"
      {...props}
      aria-label={label}
      className={cn(
        'p-0',
        size === 'lg' ? 'size-11 min-h-11' : 'size-9',
        shape === 'circle' && 'rounded-full',
        props.className,
      )}
    >
      {children}
    </Button>
  );
}

export function Input({
  size = 'md',
  suggestions,
  className,
  ...props
}: Omit<ComponentProps<'input'>, 'size' | 'list'> & {
  /** lg: the one prominent field of a short form (sign-in), 48px with a heavy border. */
  size?: 'md' | 'lg';
  /** Values offered as the owner types (such as people's names); anything else can still be typed. */
  suggestions?: string[];
}) {
  const listId = useId();
  return (
    <>
      <input
        {...props}
        list={suggestions?.length ? listId : undefined}
        className={cn(
          'w-full rounded-sm bg-surface px-3 text-primary placeholder:text-tertiary disabled:opacity-50',
          size === 'lg'
            ? 'min-h-12 border-2 border-primary text-md'
            : 'min-h-9 border border-tertiary/60 hover:border-tertiary',
          className,
        )}
      />
      {!!suggestions?.length && (
        <datalist id={listId}>
          {suggestions.map((value) => (
            <option key={value} value={value} />
          ))}
        </datalist>
      )}
    </>
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

/**
 * The palettes the app can be shown in, as a row of colour dots (radio buttons, so arrow keys move between them).
 * Each dot keeps its own colour whatever the current palette is; the chosen one is ringed and named beside the row.
 */
export function ThemePicker<T extends string>({
  value,
  options,
  onChange,
  label = '界面主题',
  named = false,
}: {
  value: T;
  options: readonly { id: T; label: string }[];
  onChange: (value: T) => void;
  label?: string;
  /** Show the chosen palette's name after the dots. */
  named?: boolean;
}) {
  const name = useId();
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="inline-flex items-center text-sm text-secondary"
    >
      {options.map((option) => (
        <label
          key={option.id}
          title={option.label}
          className="grid size-11 cursor-pointer place-items-center"
        >
          <input
            type="radio"
            name={name}
            value={option.id}
            checked={option.id === value}
            onChange={() => onChange(option.id)}
            aria-label={option.label}
            className="peer sr-only"
          />
          <span
            aria-hidden
            data-swatch={option.id}
            className="theme-swatch size-5 rounded-full border border-black/15 peer-checked:outline-2 peer-checked:outline-offset-2 peer-checked:outline-primary peer-focus-visible:ring-2 peer-focus-visible:ring-accent peer-focus-visible:ring-offset-4 peer-focus-visible:ring-offset-canvas"
          />
        </label>
      ))}
      {named && (
        <span className="ml-1">
          {options.find((option) => option.id === value)?.label}
        </span>
      )}
    </div>
  );
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

/** A slider with its label in front, such as a zoom level. */
export function Slider({
  label,
  className,
  ...props
}: Omit<ComponentProps<'input'>, 'type' | 'style' | 'className'> & {
  label: ReactNode;
  /** Layout only, such as a width. */
  className?: string;
}) {
  return (
    <label className={cn('flex items-center gap-3', className)}>
      {label}
      <input
        {...props}
        type="range"
        className="min-h-11 flex-1 accent-accent disabled:opacity-50"
      />
    </label>
  );
}

/** Put the focus on the chosen option of the group named `group` once it shows `chosen`. The group may be made anew by
 * the change (a page that swaps one conversation for another carries its own), so it is looked for again by name
 * rather than kept by reference, for a few frames until it is there. */
function focusChosen(group: string, chosen: string, frames = 30) {
  requestAnimationFrame(() => {
    const target = Array.from(
      document.querySelectorAll<HTMLElement>(
        '[role="radiogroup"] [aria-checked="true"]',
      ),
    ).find(
      (option) =>
        option.textContent === chosen &&
        option.parentElement?.getAttribute('aria-label') === group,
    );
    if (target) target.focus();
    else if (frames > 0) focusChosen(group, chosen, frames - 1);
  });
}

/**
 * Two or three ways to take one thing, side by side, one chosen (such as what a message is: 问答 or 交代任务). Radio
 * buttons in a group named `label`, so the arrow keys move between them.
 */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string;
  value: T;
  options: readonly { id: T; label: string }[];
  onChange: (value: T) => void;
  disabled?: boolean;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="inline-flex shrink-0 gap-0.5 rounded-full bg-soft p-0.5"
    >
      {options.map((option) => {
        const chosen = option.id === value;
        return (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={chosen}
            tabIndex={chosen ? 0 : -1}
            disabled={disabled}
            onClick={() => onChange(option.id)}
            onKeyDown={(event) => {
              const step =
                event.key === 'ArrowRight' || event.key === 'ArrowDown'
                  ? 1
                  : event.key === 'ArrowLeft' || event.key === 'ArrowUp'
                    ? -1
                    : 0;
              if (!step) return;
              event.preventDefault();
              const index = options.findIndex((item) => item.id === value);
              const next =
                options[(index + step + options.length) % options.length];
              onChange(next.id);
              focusChosen(label, next.label);
            }}
            className={cn(
              'min-h-8 rounded-full px-3 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50',
              chosen
                ? 'bg-surface text-primary shadow-elevation-1'
                : 'text-secondary hover:text-primary',
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
