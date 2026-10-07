import { useCallback, useEffect, useRef } from 'react';
import {
  usePersonaId,
  usePersonaState as useState,
} from '../../lib/usePersonaState';
import { api, ApiError } from '../../lib/api';
import { personaKey } from '../../lib/persona';

export interface Job<Result = unknown> {
  job_id: string;
  kind: string;
  status: 'queued' | 'running' | 'done' | 'failed';
  created?: string;
  started?: string | null;
  finished?: string | null;
  progress?: string[];
  milestones?: string[];
  stage?: { current: number; total: number; label: string } | null;
  tally?: { done: number; failed: number; total: number | null } | null;
  result?: Result;
  error?: string | null;
}
export const jobLabels: Record<string, string> = {
  persona_build: '构建人格档案',
  chat: '和分身聊天',
  video: '生成视频',
};
export const statusLabels = {
  queued: '排队中',
  running: '运行中',
  done: '已完成',
  failed: '失败',
};
export function jobStage(job: Job) {
  if (job.stage !== undefined) return job.stage;
  for (const line of [...(job.progress ?? [])].reverse()) {
    const match = /^\[(\d+)\/(\d+)\]\s*(.*)/.exec(line);
    if (match)
      return {
        current: Number(match[1]),
        total: Number(match[2]),
        label: match[3].trim(),
      };
  }
  return null;
}
export function jobRatio(job: Job): number | null {
  if (job.status === 'done') return 1;
  const stage = jobStage(job);
  if (stage && stage.total > 0) return (stage.current - 1) / stage.total;
  if (job.tally?.total && job.tally.total > 0)
    return (job.tally.done + job.tally.failed) / job.tally.total;
  return job.status === 'failed' ? 0 : null;
}
function savedId(key?: string) {
  try {
    return key ? sessionStorage.getItem(key) : null;
  } catch {
    return null;
  }
}
function saveId(key: string | undefined, id: string | null) {
  try {
    if (key) {
      if (id) sessionStorage.setItem(key, id);
      else sessionStorage.removeItem(key);
    }
  } catch {
    /* Storage is optional; running jobs are discoverable from the API. */
  }
}
export async function findRunningJob(kinds: string[], signal?: AbortSignal) {
  try {
    const jobs = await api<Job[]>('/api/jobs', { signal });
    return (
      jobs.find(
        (job) =>
          kinds.includes(job.kind) &&
          (job.status === 'queued' || job.status === 'running'),
      ) ?? null
    );
  } catch {
    return null;
  }
}

export function useJob<Result>({
  kind,
  storageKey,
  active = true,
  onDone,
}: {
  kind: string;
  storageKey?: string;
  active?: boolean;
  onDone?: (job: Job<Result>, context: { restored: boolean }) => void;
}) {
  const personaId = usePersonaId();
  storageKey = storageKey ? personaKey(storageKey, personaId) : undefined;
  const [job, setJob] = useState<Job<Result> | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [retries, setRetries] = useState(0);
  const [disconnected, setDisconnected] = useState(false);
  const alive = useRef(false);
  const tracking = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const currentId = useRef<string | null>(null);
  const callback = useRef(onDone);
  useEffect(() => {
    callback.current = onDone;
  }, [onDone]);
  const cancel = useCallback(() => {
    controller.current?.abort();
    clearTimeout(timer.current);
  }, []);
  const attach = useCallback(
    (id: string, restored = false) => {
      if (!alive.current) return;
      cancel();
      const request = new AbortController();
      controller.current = request;
      currentId.current = id;
      saveId(storageKey, id);
      tracking.current = true;
      setJob({ job_id: id, kind, status: 'queued' });
      setSubmitting(false);
      setError('');
      setDisconnected(false);
      setRetries(0);
      let failures = 0;
      let sawActive = false;
      const poll = async () => {
        if (request.signal.aborted || !alive.current) return;
        try {
          const next = await api<Job<Result>>(
            `/api/jobs/${encodeURIComponent(id)}`,
            {
              signal: request.signal,
              headers: { 'X-Twin-Persona': personaId },
            },
          );
          if (request.signal.aborted || !alive.current) return;
          failures = 0;
          setRetries(0);
          setJob(next);
          if (next.status === 'queued' || next.status === 'running')
            sawActive = true;
          if (next.status === 'done' || next.status === 'failed') {
            tracking.current = false;
            if (next.status === 'done') {
              if (next.kind && next.kind !== kind) {
                setNotice(
                  `正在运行的${jobLabels[next.kind] || '任务'}已完成，现在可以重新提交。`,
                );
                saveId(storageKey, null);
              } else
                callback.current?.(next, { restored: restored && !sawActive });
            }
            return;
          }
          timer.current = setTimeout(() => void poll(), 1000);
        } catch (failure) {
          if (request.signal.aborted || !alive.current) return;
          if (failure instanceof ApiError && failure.status === 404) {
            saveId(storageKey, null);
            currentId.current = null;
            tracking.current = false;
            setJob(null);
            if (!restored)
              setError('任务记录已不存在。本地服务可能已经重启，请重新发起。');
            return;
          }
          failures += 1;
          setRetries(failures);
          if (failures < 15)
            timer.current = setTimeout(() => void poll(), 2000);
          else {
            tracking.current = false;
            setDisconnected(true);
            setError(
              '连接中断，已停止自动重试。请重新运行 twin ui 后重新连接；服务重启后任务会丢失，需要重新提交。',
            );
          }
        }
      };
      void poll();
    },
    [cancel, kind, storageKey, personaId],
  );
  useEffect(() => {
    alive.current = active;
    if (active) {
      const request = new AbortController();
      controller.current = request;
      void (async () => {
        const running = await findRunningJob([kind], request.signal);
        if (request.signal.aborted || !alive.current) return;
        const id = running?.job_id ?? savedId(storageKey);
        if (id) attach(id, true);
      })();
    }
    return () => {
      alive.current = false;
      tracking.current = false;
      cancel();
    };
  }, [active, attach, cancel, kind, storageKey]);
  const start = async (path: string, json?: unknown) => {
    if (!alive.current || tracking.current) return;
    tracking.current = true;
    cancel();
    const request = new AbortController();
    controller.current = request;
    setSubmitting(true);
    setJob(null);
    setError('');
    setNotice('');
    setRetries(0);
    setDisconnected(false);
    saveId(storageKey, null);
    try {
      const response = await api<{ job_id: string }>(path, {
        method: 'POST',
        json,
        signal: request.signal,
      });
      if (request.signal.aborted || !alive.current) return;
      if (typeof response.job_id !== 'string' || !response.job_id)
        throw new Error('服务没有返回任务编号');
      attach(response.job_id);
    } catch (failure) {
      if (request.signal.aborted || !alive.current) return;
      if (
        failure instanceof ApiError &&
        failure.status === 409 &&
        failure.jobId
      ) {
        attach(failure.jobId);
        setNotice(
          '已有构建、评测、导入或重建索引任务在运行，同一时间只能运行一个。下面显示正在运行的任务，它结束后可以重新提交。',
        );
      } else {
        tracking.current = false;
        setSubmitting(false);
        setError(failure instanceof Error ? failure.message : '未能提交任务');
      }
    }
  };
  return {
    job,
    submitting,
    error,
    notice,
    retries,
    disconnected,
    busy:
      submitting ||
      Boolean(
        job &&
        !disconnected &&
        !error &&
        ['queued', 'running'].includes(job.status),
      ),
    start,
    attach,
    reconnect: () => {
      if (currentId.current) attach(currentId.current, true);
    },
  };
}
export type JobState<Result = unknown> = ReturnType<typeof useJob<Result>>;
