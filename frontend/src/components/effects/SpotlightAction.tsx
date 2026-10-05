import { useReducedMotion } from 'motion/react';
import type { ComponentProps, ReactNode } from 'react';
import SpotlightCard from '../reactbits/SpotlightCard';
import { cn } from '../../lib/utils';

export function SpotlightAction({
  children,
  onClick,
  label,
  disabled = false,
}: {
  children: ReactNode;
  onClick: () => void;
  label: string;
  disabled?: boolean;
}) {
  const reduced = useReducedMotion();
  const content = (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="relative block w-full rounded-lg p-4 text-left disabled:opacity-50"
    >
      {children}
    </button>
  );
  const classes =
    'rounded-lg border border-border bg-surface text-primary shadow-card';
  if (reduced || disabled) return <div className={classes}>{content}</div>;
  // Upstream's rgba-only type is narrower than the CSS color syntax it accepts.
  const color =
    'color-mix(in srgb, var(--accent) 6%, transparent)' as NonNullable<
      ComponentProps<typeof SpotlightCard>['spotlightColor']
    >;
  return (
    <SpotlightCard
      spotlightColor={color}
      className={cn(classes, '!rounded-lg !border-border !bg-surface !p-0')}
    >
      {content}
    </SpotlightCard>
  );
}
