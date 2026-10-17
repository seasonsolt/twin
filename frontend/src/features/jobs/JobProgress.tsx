import { useEffect, useRef } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Badge, Button, Card, Meter, Row, Text } from '../../components/ui';
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
    <Card
      variant="outline"
      padding="md"
      aria-label="人格档案构建进度"
      className="mt-5 space-y-3"
    >
      <Row gap={3} wrap role="status">
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
          <Text as="span" size="sm" tone="secondary">
            {job.finished
              ? '共用时'
              : job.status === 'queued'
                ? '已等待'
                : '已用时'}{' '}
            {elapsed(job.started ?? job.created, job.finished)}
          </Text>
        )}
      </Row>
      {(job || submitting) && (
        <Meter
          label="构建进度"
          value={
            job ? (jobRatio(job) === null ? null : jobRatio(job)! * 100) : null
          }
        />
      )}
      <AnimatePresence mode="wait" initial={false}>
        <Text
          as={motion.p}
          key={stageText}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={crossfade}
          size="sm"
          tone="secondary"
          aria-live="polite"
        >
          {stageText}
        </Text>
      </AnimatePresence>
      {retries > 0 && !disconnected && (
        <p role="status">无法连接本地服务，正在重试（第 {retries} 次）…</p>
      )}
      {job?.status === 'queued' && <p>排队等待中…</p>}
      {!stage && job?.status === 'running' && (
        <p>{summaries.at(-1) || '已开始，正在处理…'}</p>
      )}
      {stage && summaries.length > 0 && (
        <ul className="space-y-1">
          {summaries.map((line, index) => (
            <Text as="li" key={index} size="sm" tone="secondary">
              {line}
            </Text>
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
          <Text
            as="summary"
            size="sm"
            tone="secondary"
            className="cursor-pointer"
          >
            详细日志（{lines.length ? `英文，最近 ${lines.length} 行` : '暂无'}
            ）
          </Text>
          <Card
            as="div"
            variant="soft"
            padding="none"
            className="mt-2 overflow-hidden"
          >
            <Text
              as="pre"
              ref={log}
              tabIndex={0}
              aria-label="详细日志"
              onScroll={(event) => {
                const node = event.currentTarget;
                nearBottom.current =
                  node.scrollHeight - node.scrollTop - node.clientHeight < 40;
              }}
              size="xs"
              breakAll
              className="max-h-60 overflow-auto whitespace-pre-wrap p-3"
            >
              {lines.join('\n')}
            </Text>
          </Card>
        </details>
      )}
      {(error || job?.status === 'failed') && (
        <div role="alert" className="space-y-2">
          <Text size="sm" tone="danger">
            {error ||
              job?.error ||
              `${jobLabels[job?.kind ?? ''] || '任务'}失败：任务失败`}
          </Text>
          {job?.status === 'failed' && (
            <Text size="sm" tone="secondary">
              {failureHint}
            </Text>
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
    </Card>
  );
}
