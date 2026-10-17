import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Check, Circle, LoaderCircle } from 'lucide-react';
import { ThinkingLabel } from '../../components/effects/ThinkingLabel';
import { Card, Meter, Text } from '../../components/ui';

export interface Processing {
  state: 'idle' | 'queued' | 'running';
  progress?: {
    phase: 'extract' | 'merge';
    done: number;
    total: number;
    // Merge batches finished and to finish, once the build merges.
    merged?: number;
    to_merge?: number;
  };
  stage?: { current: number; total: number; label: string } | null;
  tally?: { done: number; failed: number; total: number | null } | null;
  // When the running build started, and what it is doing right now: the model calls it waits on, the retries
  // since it last moved on, and when that was. ``now`` is the server's clock, which the page counts from.
  started?: string | null;
  activity?: {
    waiting: number;
    longest_s: number;
    retries: number;
    last_progress_at: string;
  } | null;
  now?: string;
  notice?: string | null;
  last_error?: string | null;
}

export const INDEX_STAGE = '更新检索向量';
// Without any progress or answer for this long, the page says so instead of only ticking on.
const QUIET_S = 300;

export interface BuildStep {
  label: string;
  state: 'done' | 'running' | 'pending';
  done?: number;
  total?: number | null;
  unit: string;
}

/** The build's three steps (read the material, merge what it found, embed it for retrieval) and where it is. */
export function buildSteps(processing: Processing): BuildStep[] {
  const { progress, stage, tally } = processing;
  const indexing = !progress && stage?.label === INDEX_STAGE;
  const merging = !indexing && progress?.phase === 'merge';
  return [
    {
      label: '读资料',
      unit: '段',
      state: merging || indexing ? 'done' : 'running',
      done: progress?.done,
      total: progress?.total,
    },
    {
      label: '合并成记忆',
      unit: '批',
      state: indexing ? 'done' : merging ? 'running' : 'pending',
      done: merging ? (progress?.merged ?? 0) : undefined,
      total: merging ? progress?.to_merge : undefined,
    },
    {
      label: '更新检索',
      unit: '条',
      state: indexing ? 'running' : 'pending',
      done: indexing ? tally?.done : undefined,
      total: indexing ? tally?.total : undefined,
    },
  ];
}

export const duration = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s} 秒`;
  if (s < 3600) return `${Math.floor(s / 60)} 分 ${s % 60} 秒`;
  return `${Math.floor(s / 3600)} 小时 ${Math.floor((s % 3600) / 60)} 分`;
};

const since = (iso: string | null | undefined, now: number) =>
  iso ? (now - Date.parse(iso)) / 1000 : 0;

/** What the build is doing this second, from the server's view at the last poll plus the time since. */
export function liveness(processing: Processing, now: number) {
  const activity = processing.activity;
  if (processing.state !== 'running' || !activity) return [];
  const quiet = since(activity.last_progress_at, now);
  const lines: string[] = [];
  if (activity.waiting > 0) {
    const longest = activity.longest_s + since(processing.now, now);
    lines.push(
      `正在等模型回复 · ${activity.waiting} 个请求 · 最久已等 ${duration(longest)}`,
    );
  }
  if (activity.retries > 0)
    lines.push(`有请求超时或出错，正在自动重试（${activity.retries} 次）`);
  lines.push(quiet < 3 ? '刚刚有进展' : `上次进展在 ${duration(quiet)} 前`);
  if (quiet > QUIET_S && activity.waiting === 0)
    lines.push('已经有一阵没有进展；可在「任务」里查看详细记录');
  return lines;
}

function StepRow({ step }: { step: BuildStep }) {
  const counted = step.total
    ? `${step.done ?? 0}/${step.total} ${step.unit}`
    : '';
  return (
    <li className="space-y-1">
      <div className="flex items-center gap-2">
        {step.state === 'done' ? (
          <Check aria-hidden className="size-4 text-success" />
        ) : step.state === 'running' ? (
          <LoaderCircle
            aria-hidden
            className="size-4 animate-spin text-accent motion-reduce:animate-none"
          />
        ) : (
          <Circle aria-hidden className="size-4 text-tertiary" />
        )}
        <span
          className={
            step.state === 'pending' ? 'text-tertiary' : 'text-primary'
          }
        >
          {step.label}
          <span className="sr-only">
            {step.state === 'done'
              ? '（已完成）'
              : step.state === 'running'
                ? '（进行中）'
                : '（未开始）'}
          </span>
        </span>
        {counted && step.state !== 'pending' && (
          <span className="ml-auto tabular-nums text-secondary">{counted}</span>
        )}
      </div>
      {step.state === 'running' && !!step.total && (
        <div className="ml-6">
          <Meter
            size="sm"
            hideLabel
            label={`${step.label}进度`}
            value={step.done ?? 0}
            max={step.total}
          />
        </div>
      )}
    </li>
  );
}

/** The whole build at a glance, ticking every second so a long wait never looks like a hang. */
export function BuildProgress({
  processing,
  title,
  children,
}: {
  processing: Processing;
  title: string;
  children?: ReactNode;
}) {
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => {
    if (processing.state !== 'running') return;
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [processing.state]);
  // The server's clock at this tick: its time at the last poll, moved on by the time since that poll arrived.
  const received = useMemo(
    () => ({ at: Date.now(), server: processing.now }),
    [processing.now],
  );
  const now = received.server
    ? Date.parse(received.server) + (clock - received.at)
    : clock;
  const running = processing.state === 'running';
  const steps = buildSteps(processing);
  const lines = liveness(processing, now);
  return (
    <Card as="div" variant="outline" padding="md" aria-live="polite">
      <Text as="div" size="sm" className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <ThinkingLabel text={title} />
          {running && processing.started && (
            <Text as="span" size="xs" tone="tertiary" className="tabular-nums">
              已用时 {duration(since(processing.started, now))}
            </Text>
          )}
        </div>
        {processing.state !== 'idle' && (
          <ol aria-label="整理步骤" className="space-y-2">
            {steps.map((step) => (
              <StepRow key={step.label} step={step} />
            ))}
          </ol>
        )}
        {lines.length > 0 && (
          <Text
            as="ul"
            size="xs"
            tone="secondary"
            aria-label="实时状态"
            className="space-y-0.5"
          >
            {lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </Text>
        )}
        {children}
      </Text>
    </Card>
  );
}
