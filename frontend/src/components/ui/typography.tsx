import type { ComponentProps, ElementType, ReactNode, Ref } from 'react';
import { Link } from 'react-router';
import { cn } from '../../lib/utils';

// Type sizes have names, not numbers: a page picks what a piece of text is (a page title, a section title, small
// print) and the size comes from here, so the scale in tokens.css stays the only one in use.

export type TextTone =
  | 'primary'
  | 'secondary'
  | 'tertiary'
  | 'accent'
  | 'success'
  | 'warning'
  | 'danger'
  | 'info'
  | 'inherit';
export const textTones: Record<TextTone, string> = {
  primary: 'text-primary',
  secondary: 'text-secondary',
  tertiary: 'text-tertiary',
  accent: 'text-accent',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  info: 'text-info',
  inherit: '',
};

export type TextSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl' | '2xl' | 'inherit';
/** 12 / 13 / 14 (body) / 16 / 18 / 22px. xl and 2xl are for a name inside a control, where a Heading cannot go. */
export const textSizes: Record<TextSize, string> = {
  xs: 'text-xs',
  sm: 'text-sm',
  md: 'text-base',
  lg: 'text-lg',
  xl: 'text-xl',
  '2xl': 'text-2xl',
  inherit: '',
};
const weights = {
  regular: 'font-normal',
  medium: 'font-medium',
  semibold: 'font-semibold',
  bold: 'font-bold',
  inherit: '',
};

export type HeadingSize = 'display' | 'page' | 'title' | 'section' | 'item';
/** display 26px (a first-run welcome), page 22px, title 18px (a dialog or panel), section 16px, item 15px; all
 * semibold. */
const headingSizes: Record<HeadingSize, string> = {
  display: 'text-3xl',
  page: 'text-2xl',
  title: 'text-xl',
  section: 'text-lg',
  item: 'text-md',
};
const defaultHeading: Record<1 | 2 | 3 | 4, HeadingSize> = {
  1: 'page',
  2: 'page',
  3: 'section',
  4: 'item',
};

export function Heading({
  level = 2,
  weight = 'semibold',
  size,
  tone = 'primary',
  align = 'start',
  truncate = false,
  id,
  ref,
  tabIndex,
  title,
  className,
  children,
}: {
  /** The outline level (h1–h4); the look follows `size`. */
  level?: 1 | 2 | 3 | 4;
  weight?: 'medium' | 'semibold' | 'bold';
  size?: HeadingSize;
  tone?: TextTone;
  align?: 'start' | 'center';
  truncate?: boolean;
  id?: string;
  ref?: Ref<HTMLHeadingElement>;
  tabIndex?: number;
  /** What the heading leaves unsaid, on hover: a rule or a reason that need not take room on the page. */
  title?: string;
  /** Layout only (margins, flex). Size, colour and weight come from the props. */
  className?: string;
  children: ReactNode;
}) {
  const Tag = `h${level}` as const;
  return (
    <Tag
      id={id}
      ref={ref}
      tabIndex={tabIndex}
      title={title}
      className={cn(
        weights[weight],
        headingSizes[size ?? defaultHeading[level]],
        textTones[tone],
        align === 'center' && 'text-center',
        truncate && 'truncate',
        className,
      )}
    >
      {children}
    </Tag>
  );
}

type TextProps<T extends ElementType> = {
  as?: T;
  size?: TextSize;
  tone?: TextTone;
  weight?: keyof typeof weights;
  align?: 'start' | 'center' | 'end';
  truncate?: boolean;
  /** Long unbroken strings (file names, ids) wrap anywhere. */
  breakAll?: boolean;
  /** Long text shows its first two lines; the whole of it is the hover title and stays for screen readers. */
  twoLines?: boolean;
  /** Layout only (margins, flex). Size, colour and weight come from the props. */
  className?: string;
  children?: ReactNode;
} & Omit<
  ComponentProps<T>,
  'as' | 'className' | 'children' | 'style' | 'color'
>;

/** Body text. Defaults to a 14px paragraph in the primary colour. */
export function Text<T extends ElementType = 'p'>({
  as,
  size = 'md',
  tone = 'primary',
  weight = 'inherit',
  align = 'start',
  truncate = false,
  breakAll = false,
  twoLines = false,
  className,
  children,
  ...props
}: TextProps<T>) {
  const Tag: ElementType = as ?? 'p';
  return (
    <Tag
      {...props}
      className={cn(
        textSizes[size],
        textTones[tone],
        weights[weight],
        align === 'center' && 'text-center',
        align === 'end' && 'text-right',
        truncate && 'truncate',
        breakAll && 'break-all',
        twoLines && 'line-clamp-2',
        className,
      )}
      title={
        twoLines && typeof children === 'string'
          ? children
          : (props as { title?: string }).title
      }
    >
      {children}
    </Tag>
  );
}

type LinkLook = {
  size?: TextSize;
  weight?: 'regular' | 'medium';
  truncate?: boolean;
  children: ReactNode;
};
const linkClasses = ({
  size = 'inherit',
  weight = 'regular',
  truncate,
}: LinkLook) =>
  cn(
    'text-accent underline underline-offset-2 hover:text-accent-hover disabled:cursor-not-allowed disabled:opacity-50',
    truncate ? 'block max-w-full truncate' : 'inline-flex items-center gap-1',
    textSizes[size],
    weights[weight],
  );

/**
 * Underlined accent text: an in-app route (`to`), an address (`href`), or an action that looks like a link
 * (`onClick`, rendered as a button).
 */
export function TextLink(
  props: LinkLook &
    (
      | ({ to: string } & Omit<
          ComponentProps<typeof Link>,
          'className' | 'style' | 'children'
        >)
      | ({ href: string } & Omit<
          ComponentProps<'a'>,
          'className' | 'style' | 'children'
        >)
      | ({ onClick: () => void } & Omit<
          ComponentProps<'button'>,
          'className' | 'style' | 'children' | 'onClick'
        >)
    ),
) {
  const { size, weight, truncate, children, ...rest } = props;
  const className = linkClasses({ size, weight, truncate, children });
  if ('to' in rest)
    return (
      <Link {...rest} className={className}>
        {children}
      </Link>
    );
  if ('href' in rest)
    return (
      <a {...rest} className={className}>
        {children}
      </a>
    );
  return (
    <button type="button" {...rest} className={className}>
      {children}
    </button>
  );
}
