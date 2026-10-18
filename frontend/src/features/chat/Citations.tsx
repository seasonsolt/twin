import { useId, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Dialog,
  Stack,
  Text,
  TextLink,
  Textarea,
  toast,
} from '../../components/ui';
import { cn } from '../../lib/utils';
import { api } from '../../lib/api';
import { useCanManage } from '../../stores/personas';
import type { Citation } from './types';

/** A card's heading: where the words come from, with the place in a file. */
function citationLabel(citation: Citation): string {
  if (citation.kind === 'file')
    return (
      [citation.file_name, citation.locator].filter(Boolean).join(' · ') ||
      '附件'
    );
  return citationSource(citation);
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
    <Card as="li" variant="outline" padding="sm">
      <Badge>{citationLabel(citation)}</Badge>
      <Text
        as="blockquote"
        size="sm"
        tone={removed ? 'tertiary' : 'inherit'}
        className={cn('mt-2 whitespace-pre-wrap', removed && 'line-through')}
      >
        {text}
      </Text>
      {removed ? (
        <Text size="xs" tone="tertiary" className="mt-1">
          已删掉
        </Text>
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
    </Card>
  );
}

/** "10 月 15 日" for an ISO date this year, "2024 年 1 月 1 日" for another year; anything else as it came. */
function day(date: string | null | undefined) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(date ?? '');
  if (!match) return date || '';
  const [, year, month, dayOfMonth] = match.map(Number);
  const year_ = year === new Date().getFullYear() ? '' : `${year} 年 `;
  return `${year_}${month} 月 ${dayOfMonth} 日`;
}

/** Where the first piece of evidence comes from, in a few words: the meeting and the day, the file, the memory. */
function citationSource(citation: Citation): string {
  if (citation.kind === 'item') return citation.facet || '档案';
  if (citation.kind === 'file') return citation.file_name || '附件';
  const when = [citation.channel, day(citation.date)]
    .filter(Boolean)
    .join(' · ');
  if (citation.kind === 'ledger')
    return [`承诺账本 · ${citation.ledger_kind ?? '条目'}`, when]
      .filter(Boolean)
      .join(' · ');
  return when || '原话';
}

/** The line under an answer saying what it rests on: "依据 · 产品周会 · 10 月 15 日 等 2 处". */
export function citationSummary(cited: Citation[]) {
  return `依据 · ${citationSource(cited[0])}${cited.length > 1 ? ` 等 ${cited.length} 处` : ''}`;
}

/**
 * What an answer rests on, as one line under it; clicking it opens the original words in a layer at the right edge,
 * where a memory that went wrong can be corrected. Closing it returns to the conversation where it was.
 * ``note`` says beside the evidence what kind of answer it supports.
 */
export function Citations({
  cited = [],
  note,
}: {
  cited?: Citation[];
  note?: string;
}) {
  // Only the person behind the twin can change what it remembers; a visitor just sees the evidence.
  const editable = useCanManage();
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  if (!cited.length) return null;
  return (
    <>
      <TextLink
        ref={trigger}
        size="sm"
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
      >
        {citationSummary(cited)}
      </TextLink>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title="回答依据"
        variant="side"
        // Back to the line that opened it, so the conversation is where the reader left it.
        onCloseAutoFocus={(event) => {
          if (trigger.current?.isConnected) {
            event.preventDefault();
            trigger.current.focus();
          }
        }}
      >
        <Stack gap={3}>
          {note && (
            <Text size="sm" tone="secondary">
              {note}
            </Text>
          )}
          <Stack as="ul" gap={2} aria-label="回答依据">
            {cited.map((citation) => (
              <CitationCard
                key={citation.id}
                citation={citation}
                editable={editable}
              />
            ))}
          </Stack>
        </Stack>
      </Dialog>
    </>
  );
}
