import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { MoreHorizontal } from 'lucide-react';
import {
  Badge,
  BadgeToggle,
  IconButton,
  Row,
  Text,
  type Tone,
} from '../../components/ui';
import { CitationList } from './Citations';
import type { ChatReply } from './types';

type Mode = NonNullable<ChatReply['mode']>;

/** What kind of answer this is, said where it is read: the boundary of the answer, never a confidence score. */
const modes: Record<Mode, { label: string; tone: Tone; note: string }> = {
  grounded: {
    label: '有本人资料支持',
    tone: 'success',
    note: '这条回答来自下面这些资料。',
  },
  inferred: {
    label: '根据资料推测，不是本人原话',
    tone: 'warning',
    note: '本人没有直接说过这件事，回答是根据下面的资料推测的。',
  },
  general: {
    label: '通用建议，不代表本人观点',
    tone: 'neutral',
    note: '资料里没有本人对这件事的看法，回答是通用建议，下面是参考过的资料。',
  },
  abstain: {
    label: '资料不足，需要问本人',
    tone: 'warning',
    note: '资料不足以回答，下面是找到的相关内容。',
  },
};

/** The same, said to the person themself, in their own conversation with their assistant. */
const ownModes: Record<Mode, { label: string; tone: Tone; note: string }> = {
  grounded: {
    label: '来自你的记忆',
    tone: 'success',
    note: '这条回答来自下面这些资料。',
  },
  inferred: {
    label: '按资料推测',
    tone: 'warning',
    note: '你没有直接说过这件事，回答是根据下面的资料推测的。',
  },
  general: {
    label: '通用回答',
    tone: 'neutral',
    note: '资料里没有你对这件事的说法，回答是通用的，下面是参考过的资料。',
  },
  abstain: {
    label: '资料里没有',
    tone: 'warning',
    note: '资料里没有这条，下面是找到的相关内容。',
  },
};

export function replyMode(reply: ChatReply, own = false) {
  return (own ? ownModes : modes)[
    reply.mode ?? (reply.abstain ? 'abstain' : 'grounded')
  ];
}

/** Whether an answer has anything to open under it: the memories and words it rests on, or why it did not answer. */
const hasDetails = (reply: ChatReply) =>
  !!reply.cited?.length ||
  !!(reply.abstain && reply.abstain_reason) ||
  reply.verified === false;

/**
 * The badge under an answer: what kind of answer it is. A grounded answer without evidence to show says only that it
 * drew on the profile; an answer nothing could be checked against shows no label at all. With ``onToggle`` and
 * something behind it (what it rests on, why it abstained), the badge is the button that opens it right under the
 * answer.
 */
export function ReplyBasis({
  reply,
  open = false,
  onToggle,
  controls,
  own = false,
}: {
  reply: ChatReply;
  open?: boolean;
  onToggle?: () => void;
  /** The id of what the badge opens, for assistive technology. */
  controls?: string;
  /** In the person's own conversation, where it speaks of "你". */
  own?: boolean;
}) {
  const cited = reply.cited ?? [];
  if (reply.verified === false) return null;
  const mode = replyMode(reply, own);
  const grounded = (reply.mode ?? 'grounded') === 'grounded' && !reply.abstain;
  const bare = grounded && !cited.length;
  const label = bare ? (own ? '结合你的记忆' : '结合档案资料') : mode.label;
  return (
    <Row gap={2} wrap role="group" aria-label="回答依据摘要">
      {onToggle && hasDetails(reply) ? (
        <BadgeToggle
          tone={bare ? 'neutral' : mode.tone}
          open={open}
          aria-controls={open ? controls : undefined}
          onClick={onToggle}
        >
          {label}
          {cited.length > 0 && <span> · {cited.length}</span>}
        </BadgeToggle>
      ) : (
        <Badge tone={bare ? 'neutral' : mode.tone}>{label}</Badge>
      )}
    </Row>
  );
}

function formatElapsed(milliseconds: number) {
  if (milliseconds < 1000) return `${Math.round(milliseconds)} 毫秒`;
  if (milliseconds < 60_000) {
    const seconds = milliseconds / 1000;
    return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} 秒`;
  }
  const totalSeconds = Math.floor(milliseconds / 1000);
  return `${Math.floor(totalSeconds / 60)} 分 ${totalSeconds % 60} 秒`;
}

/** When the answer was finished and how long it took, beside the line under it; nothing for an older reply that
 * kept no times. */
export function ReplyTime({ reply }: { reply: ChatReply }) {
  const elapsed = reply.elapsed_ms;
  const completed = reply.completed_at ? new Date(reply.completed_at) : null;
  if (
    typeof elapsed !== 'number' ||
    !Number.isFinite(elapsed) ||
    elapsed < 0 ||
    !completed ||
    !Number.isFinite(completed.getTime())
  )
    return null;
  const clock = new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(completed);
  return (
    <Text as="span" size="xs" tone="tertiary">
      生成用时 {formatElapsed(elapsed)} ·{' '}
      <time dateTime={reply.completed_at}>{clock} 完成</time>
    </Text>
  );
}

/**
 * What the answer rests on, opened under it by its badge: the original words one layer down, where a memory that went
 * wrong can be corrected, and why it did not answer when it did not.
 */
export function ReplyDetails({
  reply,
  id,
  editable = false,
  own = false,
}: {
  reply: ChatReply;
  id?: string;
  /** Whether the viewer may correct a memory the answer drew on. */
  editable?: boolean;
  own?: boolean;
}) {
  const cited = reply.cited ?? [];
  const node = useRef<HTMLDivElement>(null);
  // Opened under an answer near the foot of the page, it is brought into view rather than left below the edge.
  useEffect(() => {
    node.current?.scrollIntoView?.({ block: 'nearest' });
  }, []);
  return (
    <Text
      as="div"
      ref={node}
      id={id}
      size="sm"
      tone="secondary"
      className="reply-details-content space-y-2 border-l-2 border-accent/40 py-1 pl-3"
    >
      {cited.length > 0 && (
        <>
          <p>{replyMode(reply, own).note}</p>
          <CitationList cited={cited} editable={editable} />
        </>
      )}
      {reply.verified === false && <p>这条回答没有附带依据说明，无法核对</p>}
      {reply.abstain && reply.abstain_reason && (
        <p>没有作答的原因：{reply.abstain_reason}</p>
      )}
    </Text>
  );
}

/**
 * The line under a twin's answer and what opens from it: the badge (opening what the answer rests on), when it was
 * made, and the actions given as children (speaking it, copying it).
 */
export function ReplyLine({
  reply,
  editable,
  own = false,
  plain = false,
  children,
}: {
  reply: ChatReply;
  editable?: boolean;
  /** In the person's own conversation. */
  own?: boolean;
  /** No badge: a reply that rests on nothing to show (the assistant taking a note down). */
  plain?: boolean;
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <>
      <div className="reply-actions mt-1 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 empty:hidden">
        {plain ? null : reply.verified === false ? (
          // Nothing to say about what kind of answer it is, so no badge: only a way to see why.
          <IconButton
            label="处理详情"
            aria-expanded={open}
            aria-controls={open ? id : undefined}
            onClick={() => setOpen(!open)}
          >
            <MoreHorizontal size={18} aria-hidden />
          </IconButton>
        ) : (
          <ReplyBasis
            reply={reply}
            open={open}
            onToggle={() => setOpen(!open)}
            controls={id}
            own={own}
          />
        )}
        <ReplyTime reply={reply} />
        {children}
      </div>
      {open && !plain && hasDetails(reply) && (
        <ReplyDetails reply={reply} id={id} editable={editable} own={own} />
      )}
    </>
  );
}
