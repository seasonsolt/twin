import { useId, type ComponentProps, type ReactNode } from 'react';
import { cn } from '../../lib/utils';
import { Heading, Text } from './typography';
import { Card } from './surfaces';

// Layout primitives take spacing as a step of the design scale (4px units), never as a class name, so pages keep
// to the same rhythm: 1 = 4px, 2 = 8px, 3 = 12px, 4 = 16px, 5 = 20px, 6 = 24px, 8 = 32px.

export type Gap = 0 | 1 | 2 | 3 | 4 | 5 | 6 | 8;
// Written out in full so Tailwind sees every class.
const gaps: Record<Gap, string> = {
  0: 'gap-0',
  1: 'gap-1',
  2: 'gap-2',
  3: 'gap-3',
  4: 'gap-4',
  5: 'gap-5',
  6: 'gap-6',
  8: 'gap-8',
};
const aligns = {
  start: 'items-start',
  center: 'items-center',
  end: 'items-end',
  baseline: 'items-baseline',
  stretch: 'items-stretch',
};
const justifies = {
  start: 'justify-start',
  center: 'justify-center',
  end: 'justify-end',
  between: 'justify-between',
};

type BoxTag =
  | 'div'
  | 'section'
  | 'header'
  | 'footer'
  | 'ul'
  | 'ol'
  | 'li'
  | 'form'
  | 'nav'
  | 'fieldset';
type BoxProps = {
  as?: BoxTag;
  gap?: Gap;
  align?: keyof typeof aligns;
  /** Take the remaining width in a Row (and allow truncating text inside). */
  grow?: boolean;
  children?: ReactNode;
} & Omit<ComponentProps<'div'>, 'className' | 'style' | 'children'> &
  Pick<ComponentProps<'form'>, 'onSubmit' | 'noValidate'>;

function box(Tag: BoxTag, props: Record<string, unknown>, className: string) {
  const Element = Tag as 'div';
  return <Element {...props} className={className} />;
}

/** Children one under another. */
export function Stack({
  as = 'div',
  gap = 4,
  align = 'stretch',
  grow = false,
  ...props
}: BoxProps) {
  return box(
    as,
    props,
    cn('flex flex-col', gaps[gap], aligns[align], grow && 'min-w-0 flex-1'),
  );
}

/** Children side by side; `wrap` lets them flow onto the next line on narrow screens. */
export function Row({
  as = 'div',
  gap = 2,
  align = 'center',
  justify = 'start',
  wrap = false,
  grow = false,
  ...props
}: BoxProps & { justify?: keyof typeof justifies; wrap?: boolean }) {
  return box(
    as,
    props,
    cn(
      'flex',
      gaps[gap],
      aligns[align],
      justifies[justify],
      wrap && 'flex-wrap',
      grow && 'min-w-0 flex-1',
    ),
  );
}

/** A line of controls: what it is about on the left, actions on the right, wrapping on phones. */
export function Toolbar({
  gap = 3,
  align = 'center',
  stackOnMobile = false,
  ...props
}: Omit<BoxProps, 'grow'> & { stackOnMobile?: boolean }) {
  if (stackOnMobile) {
    const { as = 'div', ...rest } = props;
    return box(
      as,
      rest,
      cn(
        'flex flex-wrap justify-between max-md:flex-col max-md:items-stretch',
        gaps[gap],
        aligns[align],
      ),
    );
  }
  return <Row {...props} gap={gap} align={align} justify="between" wrap />;
}

const columns = {
  2: 'grid-cols-1 sm:grid-cols-2',
  3: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3',
  4: 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-4',
};
/** Equal columns that collapse to one (two for `4`) on phones. */
export function Grid({
  as = 'div',
  gap = 4,
  columns: count = 3,
  ...props
}: Omit<BoxProps, 'align' | 'grow'> & { columns?: keyof typeof columns }) {
  return box(as, props, cn('grid', gaps[gap], columns[count]));
}

/**
 * A page's content area: its title, a sentence on what it is for, the page's own actions, then the content.
 * Pages with a stage header (StageHeader) put it above this.
 */
export function Page({
  title,
  description,
  actions,
  aside,
  gap = 6,
  titleSize,
  breadcrumb,
  stackHeaderOnMobile = false,
  children,
}: {
  titleSize?: 'page' | 'display';
  breadcrumb?: ReactNode;
  stackHeaderOnMobile?: boolean;
  title?: ReactNode;
  description?: ReactNode;
  /** Buttons for the whole page, at the top right (under the title on phones). */
  actions?: ReactNode;
  /** Secondary navigation next to the title, such as a "back to …" link. */
  aside?: ReactNode;
  gap?: Gap;
  children: ReactNode;
}) {
  return (
    <div className="page-content">
      <Stack gap={gap}>
        {(title || actions || aside) && (
          <Toolbar
            as="header"
            gap={4}
            align="end"
            stackOnMobile={stackHeaderOnMobile}
          >
            <Stack gap={1} grow>
              {breadcrumb}
              {title && (
                <Heading level={2} size={titleSize}>
                  {title}
                </Heading>
              )}
              {description && <Text tone="secondary">{description}</Text>}
            </Stack>
            {aside}
            {actions && (
              <Row gap={2} wrap>
                {actions}
              </Row>
            )}
          </Toolbar>
        )}
        {children}
      </Stack>
    </div>
  );
}

/**
 * A titled part of a page. Its title names the region for screen readers. `framed` puts it on an outlined card,
 * for a block that should stand apart (a to-do list, a danger zone).
 */
export function Section({
  title,
  description,
  badge,
  actions,
  framed = false,
  gap = 4,
  level = 3,
  label,
  children,
}: {
  /** The title's outline level; it looks the same at every level. */
  level?: 2 | 3 | 4;
  title?: ReactNode;
  description?: ReactNode;
  /** Shown right after the title, such as a count. */
  badge?: ReactNode;
  actions?: ReactNode;
  framed?: boolean;
  gap?: Gap;
  /** The region's name when there is no visible title. */
  label?: string;
  children: ReactNode;
}) {
  const id = useId();
  const head = (title || actions) && (
    <Toolbar gap={3}>
      <Stack gap={1} grow>
        {title && (
          <Row gap={3}>
            <Heading level={level} size="section" id={id}>
              {title}
            </Heading>
            {badge}
          </Row>
        )}
        {description && (
          <Text size="sm" tone="secondary">
            {description}
          </Text>
        )}
      </Stack>
      {actions}
    </Toolbar>
  );
  const named = title ? { 'aria-labelledby': id } : { 'aria-label': label };
  return framed ? (
    <Card variant="outline" {...named}>
      <Stack gap={gap}>
        {head}
        {children}
      </Stack>
    </Card>
  ) : (
    <Stack as="section" gap={gap} {...named}>
      {head}
      {children}
    </Stack>
  );
}

/** Empty room of a measured height (pixels), such as the space kept below a just-sent message for the reply. */
export function Spacer({ height }: { height: number }) {
  return <div aria-hidden style={{ height }} />;
}
