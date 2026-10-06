import { useEffect, useRef } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Badge, Button, Meter } from '../../components/ui';
import { crossfade } from '../../design/motion';
import {
  jobLabels,
  jobRatio,
  jobStage,
  statusLabels,
  type JobState,
} from './useJob';

function elapsed(start?: string | null, end?: string | null) {
  if (!start) return '';
  const parse = (time: string) =>
    Date.parse(/(?:Z|[+-]\d\d:\d\d)$/.test(time) ? time : `${time}Z`);
  const seconds = Math.max(
    0,
    Math.floor(((end ? parse(end) : Date.now()) - parse(start)) / 1000),
  );
  if (!Number.isFinite(seconds)) return '';
  return seconds < 60
    ? `${seconds} 秒`
    : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}
export function JobProgress({
  state,
  onRetry,
}: {
  state: JobState;
  onRetry: () => void;
}) {
  const { job, submitting, error, notice, retries, disconnected } = state;
  const log = useRef<HTMLPreElement>(null);
  const nearBottom = useRef(true);
  const lines = job?.progress ?? [];
  useEffect(() => {
    if (log.current && nearBottom.current)
      log.current.scrollTop = log.current.scrollHeight;
  }, [job?.progress]);
  if (!job && !submitting && !error && !notice) return null;
  const stage = job ? jobStage(job) : null;
  const tally = job?.tally;
  const counted =
    tally && (tally.done || tally.failed || tally.total)
      ? `已完成 ${tally.done}${tally.total ? ` / ${tally.total}` : ''} 项${tally.failed ? `（失败 ${tally.failed}）` : ''}`
      : '';
  const stageText = stage
    ? `第 ${stage.current}/${stage.total} 步：${stage.label}${counted ? `，${counted}` : ''}`
    : counted;
  const summaries = (job?.milestones ?? []).filter(
    (line) => !/^\[\d+\/\d+\]/.test(line),
  );
  const failureHint =
    job?.kind === 'persona_build'
      ? '已经完成的模型调用都保存在资料库里，修正问题后再次构建会跳过它们。常见原因：模型或向量服务的配置、密钥、网络问题。'
      : job?.kind === 'chat'
        ? '检查 twin.toml 的 [llm] 配置和密钥所在的环境变量，修正后重启 twin ui 再试。'
        : '查看进度日志了解原因，修正后重试。';
  return (
    <section
      aria-label="人格档案构建进度"
      className="mt-5 space-y-3 rounded-md border border-border p-4"
    >
      <div className="flex flex-wrap items-center gap-3" role="status">
        <Badge
          tone={
            error || job?.status === 'failed'
              ? 'danger'
              : job?.status === 'done'
                ? 'success'
                : 'info'
          }
        >
          {submitting
            ? '提交中'
            : disconnected
              ? '连接中断'
              : job
                ? statusLabels[job.status]
                : '未能提交'}
        </Badge>
        <span>{job ? jobLabels[job.kind] || '任务' : '正在提交任务…'}</span>
        {job && (
          <span className="text-sm text-secondary">
            {job.finished
              ? '共用时'
              : job.status === 'queued'
                ? '已等待'
                : '已用时'}{' '}
            {elapsed(job.started ?? job.created, job.finished)}
          </span>
        )}
      </div>
      {(job || submitting) && (
        <Meter
          label="构建进度"
          value={
            job ? (jobRatio(job) === null ? null : jobRatio(job)! * 100) : null
          }
        />
      )}
      <AnimatePresence mode="wait" initial={false}>
        <motion.p
          key={stageText}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={crossfade}
          className="text-sm text-secondary"
          aria-live="polite"
        >
          {stageText}
        </motion.p>
      </AnimatePresence>
      {retries > 0 && !disconnected && (
        <p role="status">无法连接本地服务，正在重试（第 {retries} 次）…</p>
      )}
      {job?.status === 'queued' && <p>排队等待中…</p>}
      {!stage && job?.status === 'running' && (
        <p>{summaries.at(-1) || '已开始，正在处理…'}</p>
      )}
      {stage && summaries.length > 0 && (
        <ul className="space-y-1 text-sm text-secondary">
          {summaries.map((line, index) => (
            <li key={index}>{line}</li>
          ))}
        </ul>
      )}
      {notice && (
        <p role="status" className="text-warning">
          {notice}
        </p>
      )}
      {job && (
        <details>
          <summary className="cursor-pointer text-sm text-secondary">
            详细日志（{lines.length ? `英文，最近 ${lines.length} 行` : '暂无'}
            ）
          </summary>
          <pre
            ref={log}
            tabIndex={0}
            aria-label="详细日志"
            onScroll={(event) => {
              const node = event.currentTarget;
              nearBottom.current =
                node.scrollHeight - node.scrollTop - node.clientHeight < 40;
            }}
            className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-all rounded-md bg-canvas p-3 text-xs"
          >
            {lines.join('\n')}
          </pre>
        </details>
      )}
      {(error || job?.status === 'failed') && (
        <div role="alert" className="space-y-2 text-sm text-danger">
          <p>
            {error ||
              job?.error ||
              `${jobLabels[job?.kind ?? ''] || '任务'}失败：任务失败`}
          </p>
          {job?.status === 'failed' && (
            <p className="text-secondary">{failureHint}</p>
          )}
          <Button
            variant="secondary"
            size="sm"
            onClick={disconnected ? state.reconnect : onRetry}
          >
            {disconnected ? '重新连接' : '重试'}
          </Button>
        </div>
      )}
    </section>
  );
}
