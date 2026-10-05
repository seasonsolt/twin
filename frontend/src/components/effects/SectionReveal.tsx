import { useReducedMotion } from 'motion/react';
import type { ReactNode } from 'react';
import AnimatedContent from '../reactbits/AnimatedContent';
import { cn } from '../../lib/utils';

export function SectionReveal({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const classes = cn('text-primary', className);
  return reduced ? (
    <div className={classes}>{children}</div>
  ) : (
    <AnimatedContent
      distance={8}
      duration={0.25}
      scale={1}
      threshold={0.05}
      animateOpacity
      className={classes}
    >
      {children}
    </AnimatedContent>
  );
}
