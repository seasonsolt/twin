import { useId, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Badge, Button, Textarea, toast } from '../../components/ui';
import { useMotionPreset } from '../../design/motion';
import { api } from '../../lib/api';
import { useCanManage } from '../../stores/personas';
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

/** A memory the answer drew on, which the person can correct or remove right where they saw it go wrong. */
function ItemFix({
  citation,
  onSaved,
}: {
  citation: Citation;
  onSaved(text: string | null): void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(citation.text);
  const [pending, setPending] = useState(false);
  const id = useId();
  const save = async (status: 'edited' | 'rejected', statement?: string) => {
    setPending(true);
    try {
      await api(
        `/api/persona/items/${encodeURIComponent(citation.id)}/review`,
        {
          method: 'POST',
          json: { status, statement: statement ?? null, note: '' },
        },
      );
      onSaved(status === 'edited' ? statement! : null);
      setEditing(false);
      toast(
        status === 'edited'
          ? '改好了，之后按这条回答'
          : '删掉了，之后不会再用它',
        'success',
      );
    } catch (failure) {
      toast(failure instanceof Error ? failure.message : '没有保存', 'danger');
    } finally {
      setPending(false);
    }
  };
  if (editing)
    return (
      <form
        className="mt-2 space-y-2"
        onSubmit={(event) => {
          event.preventDefault();
          const text = draft.trim();
          if (!text) toast('表述不能为空', 'warning');
          else void save('edited', text);
        }}
      >
        <label htmlFor={id} className="sr-only">
          修改这条记忆
        </label>
        <Textarea
          id={id}
          value={draft}
          maxLength={1000}
          autoFocus
          disabled={pending}
          onChange={(event) => setDraft(event.target.value)}
        />
        <div className="flex gap-2">
          <Button type="submit" size="sm" loading={pending}>
            保存
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={pending}
            onClick={() => setEditing(false)}
          >
            取消
          </Button>
        </div>
      </form>
    );
  return (
    <div className="mt-1 flex gap-1" aria-label="修改这条记忆">
      <Button
        variant="ghost"
        size="sm"
        disabled={pending}
        onClick={() => {
          setDraft(citation.text);
          setEditing(true);
        }}
      >
        改一下
      </Button>
      <Button
        variant="ghost"
        size="sm"
        className="text-danger"
        loading={pending}
        onClick={() => void save('rejected')}
      >
        删掉
      </Button>
    </div>
  );
}

export function CitationCard({
  citation,
  editable = false,
}: {
  citation: Citation;
  editable?: boolean;
}) {
  const [text, setText] = useState(citation.text);
  const [removed, setRemoved] = useState(false);
  return (
    <li className="rounded-md border border-border bg-canvas p-3 text-sm">
      <Badge>{citationLabel(citation)}</Badge>
      <blockquote
        className={`mt-2 whitespace-pre-wrap${removed ? ' text-tertiary line-through' : ''}`}
      >
        {text}
      </blockquote>
      {removed ? (
        <p className="mt-1 text-xs text-tertiary">已删掉</p>
      ) : (
        editable &&
        citation.kind === 'item' && (
          <ItemFix
            citation={{ ...citation, text }}
            onSaved={(next) => {
              if (next === null) setRemoved(true);
              else setText(next);
            }}
          />
        )
      )}
    </li>
  );
}

export function Citations({ cited = [] }: { cited?: Citation[] }) {
  // Only the person behind the twin can change what it remembers; a visitor just sees the evidence.
  const editable = useCanManage();
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
                <CitationCard
                  key={citation.id}
                  citation={citation}
                  editable={editable}
                />
              ))}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
