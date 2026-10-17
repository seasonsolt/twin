import { ChevronDown } from 'lucide-react';
import { Text } from '../../components/ui';
import type { ChatReply } from './types';

const modeLabels: Record<NonNullable<ChatReply['mode']>, string> = {
  grounded: '结合档案资料',
  general: '通用回答',
  inferred: '基于档案推测',
  abstain: '未形成确定结论',
};

function formatElapsed(milliseconds: number) {
  if (milliseconds < 1000) return `${Math.round(milliseconds)} 毫秒`;
  if (milliseconds < 60_000) {
    const seconds = milliseconds / 1000;
    return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} 秒`;
  }
  const totalSeconds = Math.floor(milliseconds / 1000);
  return `${Math.floor(totalSeconds / 60)} 分 ${totalSeconds % 60} 秒`;
}

export function ReplyDetails({ reply }: { reply: ChatReply }) {
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
    <details className="reply-details">
      <Text
        as="summary"
        size="xs"
        tone="secondary"
        className="flex min-h-11 flex-wrap items-center gap-x-3 gap-y-1"
      >
        <span>
          生成用时 {formatElapsed(elapsed)} ·{' '}
          <time dateTime={reply.completed_at}>{clock} 完成</time>
        </span>
        <span className="inline-flex items-center gap-1 text-primary">
          处理摘要 <ChevronDown size={14} aria-hidden />
        </span>
      </Text>
      <Text
        as="div"
        size="xs"
        tone="secondary"
        className="reply-details-content space-y-1 border-l-2 border-accent/40 py-2 pl-3"
      >
        <p>回答方式：{modeLabels[reply.mode ?? 'grounded']}</p>
        {reply.mode === 'abstain' && (
          <p>原因：{reply.abstain_reason || '模型未说明具体原因'}</p>
        )}
        {profileCitations > 0 && <p>记忆依据 {profileCitations} 条</p>}
        {fileCitations > 0 && <p>附件依据 {fileCitations} 条</p>}
        {profileCitations === 0 && fileCitations === 0 && (
          <p>未引用可展示的档案或附件依据</p>
        )}
      </Text>
    </details>
  );
}
