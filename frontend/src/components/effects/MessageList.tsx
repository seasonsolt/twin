import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import AnimatedList from '../reactbits/AnimatedList';
import { cn } from '../../lib/utils';
import { crossfade } from '../../design/motion';

export interface MessageListItem {
  id: string;
  text: string;
}

export function MessageList({
  items,
  label,
  className,
}: {
  items: MessageListItem[];
  label: string;
  className?: string;
}) {
  const reduced = useReducedMotion();
  return (
    <ul aria-label={label} className={cn('effects-list space-y-2', className)}>
      <AnimatePresence initial={false}>
        {items.map((item) => (
          <motion.li key={item.id} exit={{ opacity: 0 }} transition={crossfade}>
            {reduced ? (
              <p className="rounded-md border border-border bg-canvas p-3 text-primary">
                {item.text}
              </p>
            ) : (
              <AnimatedList
                items={[item.text]}
                enableArrowNavigation={false}
                showGradients={false}
                displayScrollbar={false}
                className="!w-full"
                itemClassName="!rounded-md border border-border !bg-canvas !p-3 [&>p]:!text-primary"
              />
            )}
          </motion.li>
        ))}
      </AnimatePresence>
    </ul>
  );
}
