import { useEffect, useRef, useState } from 'react';
import { Button, Dialog } from '../../components/ui';
import { api, ApiError } from '../../lib/api';
import { JobProgress } from '../jobs/JobProgress';
import type { Job, JobState } from '../jobs/useJob';
import type { ChatReply } from '../chat/types';

interface VideoResult {
  file: string;
  duration_s: number;
  warnings: string[];
}

export function RemoteVideoPanel({
  answer,
  personaName,
  label,
}: {
  answer: ChatReply;
  personaName: string;
  label?: string;
}) {
  const [confirming, setConfirming] = useState(false);
  const [job, setJob] = useState<Job<VideoResult> | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [retries, setRetries] = useState(0);
  const [disconnected, setDisconnected] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const alive = useRef(true);
  const busy =
    submitting || Boolean(job && ['queued', 'running'].includes(job.status));
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      controller.current?.abort();
      clearTimeout(timer.current);
    };
  }, []);
  const attach = (id: string) => {
    controller.current?.abort();
    clearTimeout(timer.current);
    const request = new AbortController();
    controller.current = request;
    setError('');
    setRetries(0);
    setDisconnected(false);
    let failures = 0;
    const poll = async () => {
      try {
        const next = await api<Job<VideoResult>>(
          `/api/media/video/jobs/${encodeURIComponent(id)}`,
          { signal: request.signal },
        );
        if (!alive.current || request.signal.aborted) return;
        setJob(next);
        failures = 0;
        setRetries(0);
        if (['queued', 'running'].includes(next.status))
          timer.current = setTimeout(() => void poll(), 1000);
      } catch (failure) {
        if (!alive.current || request.signal.aborted) return;
        if (failure instanceof ApiError && failure.status === 404) {
          setJob(null);
          setError('视频任务记录已不存在，请重新生成');
          return;
        }
        setRetries(++failures);
        if (failures < 15) timer.current = setTimeout(() => void poll(), 2000);
        else {
          setDisconnected(true);
          setError(
            failure instanceof Error
              ? failure.message
              : '无法连接视频任务，请重新连接',
          );
        }
      }
    };
    void poll();
  };
  const start = async () => {
    if (busy && !disconnected) return;
    setSubmitting(true);
    setJob(null);
    setError('');
    const request = new AbortController();
    controller.current?.abort();
    controller.current = request;
    try {
      const response = await api<{ job_id: string }>('/api/media/video', {
        method: 'POST',
        json: { kind: 'chat_reply', answer, persona_name: personaName },
        signal: request.signal,
      });
      if (!alive.current || request.signal.aborted) return;
      setJob({ job_id: response.job_id, kind: 'video', status: 'queued' });
      attach(response.job_id);
    } catch (failure) {
      if (alive.current && !request.signal.aborted)
        setError(
          failure instanceof Error ? failure.message : '视频任务提交失败',
        );
    } finally {
      if (alive.current && !request.signal.aborted) setSubmitting(false);
    }
  };
  const state: JobState<VideoResult> = {
    job,
    submitting,
    error,
    notice: '',
    retries,
    disconnected,
    busy,
    start,
    attach,
    reconnect: () => {
      if (job) attach(job.job_id);
    },
  };
  const result = job?.status === 'done' ? job.result : null;
  const url =
    result && /^[0-9a-f]{64}\.mp4$/.test(result.file)
      ? `/api/media/video/${result.file}`
      : null;
  return (
    <section className="space-y-2" aria-label="真人视频">
      <Button
        variant="secondary"
        disabled={busy}
        onClick={() => setConfirming(true)}
      >
        生成真人视频
      </Button>
      <Dialog
        open={confirming}
        onOpenChange={setConfirming}
        title="生成真人视频"
        body="在本人 GPU 主机上生成，通常需要几分钟"
      >
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirming(false)}>
            取消
          </Button>
          <Button
            onClick={() => {
              setConfirming(false);
              void start();
            }}
          >
            确认生成
          </Button>
        </div>
      </Dialog>
      <JobProgress state={state} onRetry={() => setConfirming(true)} />
      {url && result && (
        <div className="space-y-2">
          {label && (
            <p role="note" className="text-sm text-secondary">
              {label}
            </p>
          )}
          <video
            controls
            src={url}
            className="w-full"
            aria-label="带标识的真人视频"
          />
          <a href={url} download="twin-video.mp4">
            下载视频（{result.duration_s} 秒）
          </a>
          {result.warnings.map((warning, index) => {
            const id = /^s(\d+): cer=/.exec(warning);
            return (
              <p key={index} role="note" className="text-xs text-secondary">
                {id
                  ? Number(id[1]) === 1
                    ? '开头提示回听与原文有出入'
                    : `第 ${Number(id[1]) - 1} 句回听与原文有出入`
                  : '视频生成有提示，请检查回听结果'}
              </p>
            );
          })}
        </div>
      )}
    </section>
  );
}
