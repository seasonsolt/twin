import { AnimatePresence, motion } from 'motion/react';
import AnimatedList from '../reactbits/AnimatedList';
import { cn } from '../../lib/utils';
import { crossfade, useMotionPreset } from '../../design/motion';
import type { ReactNode } from 'react';

export interface MessageListItem {
  id: string;
  text: string;
  content?: ReactNode;
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
  const { reduced, transition } = useMotionPreset('gentle');
  return (
    <ul aria-label={label} className={cn('effects-list space-y-2', className)}>
      <AnimatePresence initial={false}>
        {items.map((item) => (
          <motion.li
            key={item.id}
            initial={item.content && !reduced ? { opacity: 0, y: 8 } : false}
            animate={
              item.content && !reduced ? { opacity: 1, y: 0 } : undefined
            }
            exit={{ opacity: 0, transition: crossfade }}
            transition={transition}
          >
            {item.content ??
              (reduced ? (
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
              ))}
          </motion.li>
        ))}
      </AnimatePresence>
    </ul>
  );
}
