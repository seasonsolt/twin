import { useId, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Badge, Button } from '../../components/ui';
import { useMotionPreset } from '../../design/motion';
import type { Citation } from './types';

export function CitationCard({ citation }: { citation: Citation }) {
  return (
    <li className="rounded-md border border-border bg-canvas p-3 text-sm">
      <Badge>
        {citation.kind === 'item'
          ? citation.facet || '档案'
          : [citation.date, citation.channel].filter(Boolean).join(' · ') ||
            '原话'}
      </Badge>
      <blockquote className="mt-2 whitespace-pre-wrap">
        {citation.text}
      </blockquote>
    </li>
  );
}

export function Citations({ cited = [] }: { cited?: Citation[] }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const { reduced, transition, exit } = useMotionPreset('gentle');
  if (!cited.length) return null;
  return (
    <div>
      <Button
        variant="ghost"
        size="sm"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
      >
        依据 {cited.length} 条
      </Button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={id}
            initial={{ opacity: 0, ...(reduced ? {} : { height: 0 }) }}
            animate={{ opacity: 1, ...(reduced ? {} : { height: 'auto' }) }}
            exit={{
              opacity: 0,
              ...(reduced ? {} : { height: 0 }),
              transition: exit,
            }}
            transition={transition}
            className="overflow-hidden"
          >
            <ul aria-label="回答依据" className="space-y-2 py-2">
              {cited.map((citation) => (
                <CitationCard key={citation.id} citation={citation} />
              ))}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
