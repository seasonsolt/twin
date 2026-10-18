import { ChevronDown, MoreHorizontal } from 'lucide-react';
import { Badge, Row, Text, type Tone } from '../../components/ui';
import { Citations } from './Citations';
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

export function replyMode(reply: ChatReply) {
  return modes[reply.mode ?? (reply.abstain ? 'abstain' : 'grounded')];
}

/**
 * The line under an answer: what kind of answer it is and what it rests on. A grounded answer without evidence to
 * show says only that it drew on the profile; an answer nothing could be checked against shows no line at all,
 * and why an answer abstained is told in its details, not here.
 */
export function ReplyBasis({ reply }: { reply: ChatReply }) {
  const cited = reply.cited ?? [];
  if (reply.verified === false) return null;
  const mode = replyMode(reply);
  const grounded = (reply.mode ?? 'grounded') === 'grounded' && !reply.abstain;
  return (
    <Row gap={2} wrap role="group" aria-label="回答依据摘要">
      {grounded && !cited.length ? (
        <Badge>结合档案资料</Badge>
      ) : (
        <Badge tone={mode.tone}>{mode.label}</Badge>
      )}
      <Citations cited={cited} note={mode.note} />
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

/** The nearest ancestor that scrolls vertically, whose visible box the opened details must fit in. */
function scrollParent(element: HTMLElement): HTMLElement | null {
  for (let node = element.parentElement; node; node = node.parentElement) {
    if (/auto|scroll/u.test(getComputedStyle(node).overflowY)) return node;
  }
  return null;
}

/** Open the compact details upward when the space below the button, inside its scrolling list, is too short and
 * the space above is not, then bring the whole of it into view: the last answer sits right above the composer. */
export function placeDetails(details: HTMLDetailsElement) {
  delete details.dataset.placement;
  if (!details.open) return;
  const content = details.querySelector<HTMLElement>('.reply-details-content');
  if (!content) return;
  const frame = scrollParent(details)?.getBoundingClientRect() ?? {
    top: 0,
    bottom: window.innerHeight,
  };
  const anchor = details.getBoundingClientRect();
  const height = content.getBoundingClientRect().height;
  if (anchor.bottom + height > frame.bottom && anchor.top - height >= frame.top)
    details.dataset.placement = 'top';
  content.scrollIntoView?.({ block: 'nearest' });
}

/** How the answer was made, for whoever wants to know: closed, and quieter than the answer and its evidence. */
export function ReplyDetails({
  reply,
  compact = false,
}: {
  reply: ChatReply;
  compact?: boolean;
}) {
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
  const profileCitations =
    reply.cited?.filter(
      (citation) => citation.kind === 'item' || citation.kind === 'expression',
    ).length ?? 0;
  const fileCitations =
    reply.cited?.filter((citation) => citation.kind === 'file').length ?? 0;

  return (
    <details
      className={
        compact ? 'reply-details reply-details-compact' : 'reply-details'
      }
      onToggle={(event) => {
        if (compact) placeDetails(event.currentTarget);
      }}
    >
      <Text
        as="summary"
        size="xs"
        tone="tertiary"
        className="inline-flex min-h-11 items-center gap-1"
      >
        {compact ? (
          <>
            <span className="sr-only">处理详情</span>
            <MoreHorizontal size={18} aria-hidden />
          </>
        ) : (
          <>
            处理详情 <ChevronDown size={14} aria-hidden />
          </>
        )}
      </Text>
      <Text
        as="div"
        size="xs"
        tone="secondary"
        className="reply-details-content space-y-1 border-l-2 border-accent/40 py-2 pl-3"
      >
        <p>
          生成用时 {formatElapsed(elapsed)} ·{' '}
          <time dateTime={reply.completed_at}>{clock} 完成</time>
        </p>
        {profileCitations > 0 && <p>记忆依据 {profileCitations} 条</p>}
        {fileCitations > 0 && <p>附件依据 {fileCitations} 条</p>}
        {profileCitations === 0 && fileCitations === 0 && (
          <p>未引用可展示的档案或附件依据</p>
        )}
        {reply.verified === false && <p>这条回答没有附带依据说明，无法核对</p>}
        {reply.abstain && reply.abstain_reason && (
          <p>没有作答的原因：{reply.abstain_reason}</p>
        )}
      </Text>
    </details>
  );
}
