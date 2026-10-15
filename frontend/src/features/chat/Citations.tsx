import { useId, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Badge, Button } from '../../components/ui';
import { useMotionPreset } from '../../design/motion';
import type { Citation } from './types';

function citationLabel(citation: Citation): string {
  if (citation.kind === 'item') return citation.facet || '档案';
  const when = [citation.date, citation.channel].filter(Boolean).join(' · ');
  if (citation.kind === 'ledger')
    return [`账本 · ${citation.ledger_kind ?? '条目'}`, when]
      .filter(Boolean)
      .join(' · ');
  return when || '原话';
}

export function CitationCard({ citation }: { citation: Citation }) {
  return (
    <li className="rounded-md border border-border bg-canvas p-3 text-sm">
      <Badge>{citationLabel(citation)}</Badge>
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
    <div className="contents">
      <Button
        variant="ghost"
        size="sm"
        className="citation-toggle min-h-11 px-1"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
      >
        <span className="rounded-full border border-primary px-3 py-0.5 text-xs text-primary">
          依据 {cited.length}
        </span>
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
            className="order-last w-full overflow-hidden"
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
