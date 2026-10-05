import { AnimatePresence, motion } from 'motion/react';
import AnimatedList from '../reactbits/AnimatedList';
import { cn } from '../../lib/utils';
import { crossfade, springs, useMotionPreset } from '../../design/motion';
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
  layout = false,
}: {
  items: MessageListItem[];
  label: string;
  className?: string;
  layout?: boolean;
}) {
  const { reduced, transition } = useMotionPreset('gentle');
  return (
    <ul
      aria-label={label}
      className={cn('effects-list space-y-2', layout && 'relative', className)}
    >
      <AnimatePresence initial={false} mode={layout ? 'popLayout' : 'sync'}>
        {items.map((item) => (
          <motion.li
            key={item.id}
            layout={layout && !reduced ? 'position' : false}
            initial={
              item.content && (!reduced || layout)
                ? { opacity: 0, ...(reduced ? {} : { y: 8 }) }
                : false
            }
            animate={
              item.content && (!reduced || layout)
                ? { opacity: 1, ...(reduced ? {} : { y: 0 }) }
                : undefined
            }
            exit={{ opacity: 0, transition: crossfade }}
            transition={{
              ...transition,
              layout: reduced ? crossfade : springs.layout,
            }}
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
