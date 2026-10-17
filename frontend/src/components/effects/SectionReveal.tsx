import { motion, useReducedMotion } from 'motion/react';
import type { ReactNode } from 'react';
import { cn } from '../../lib/utils';

/** A section that eases in (8px up, fading) the first time it scrolls into view; still with reduced motion. */
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
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.05 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      className={classes}
    >
      {children}
    </motion.div>
  );
}
