import { useEffect, useRef, useState } from 'react';
import { Film } from 'lucide-react';
import { Button } from '../../components/ui';
import { api } from '../../lib/api';
import { jobRatio, type Job } from '../jobs/useJob';
import type { ChatReply } from './types';

interface VideoResult {
  file: string;
  duration_s: number;
  warnings: string[];
}
const videoUrl = (result?: VideoResult) =>
  result && /^[0-9a-f]{64}\.mp4$/.test(result.file)
    ? `/api/media/video/${result.file}`
    : null;
function restore(key: string): Job<VideoResult> | null {
  try {
    const job = JSON.parse(
      sessionStorage.getItem(key) ?? 'null',
    ) as Job<VideoResult> | null;
    return job?.status === 'done' && videoUrl(job.result) ? job : null;
  } catch {
    return null;
  }
}

export function ReplyVideo({
  id,
  answer,
  name,
  portrait,
}: {
  id: string;
  answer: ChatReply;
  name: string;
  portrait?: string;
}) {
  const key = `twin.reply-video:${id}`;
  const [job, setJob] = useState<Job<VideoResult> | null>(() => restore(key));
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const request = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(
    () => () => {
      request.current?.abort();
      clearTimeout(timer.current);
    },
    [],
  );
  const start = async () => {
    setVisible(true);
    if (busy || videoUrl(job?.result)) return;
    request.current?.abort();
    clearTimeout(timer.current);
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setJob(null);
    setError('');
    const failed = (failure: unknown) => {
      if (controller.signal.aborted) return;
      setBusy(false);
      setError(
        failure instanceof Error ? failure.message : '视频生成失败，请重试',
      );
    };
    const poll = async (jobId: string) => {
      try {
        const next = await api<Job<VideoResult>>(
          `/api/media/video/jobs/${encodeURIComponent(jobId)}`,
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        setJob(next);
        if (next.status === 'done') {
          if (!videoUrl(next.result)) throw new Error('视频文件不可用，请重试');
          setBusy(false);
          try {
            sessionStorage.setItem(key, JSON.stringify(next));
          } catch {
            // The mounted reply still caches the result if storage is unavailable.
          }
        } else if (next.status === 'failed') {
          throw new Error(next.error || '视频生成失败，请重试');
        } else timer.current = setTimeout(() => void poll(jobId), 1000);
      } catch (failure) {
        failed(failure);
      }
    };
    try {
      const result = await api<{ job_id: string }>('/api/media/video', {
        method: 'POST',
        json: { kind: 'chat_reply', answer, persona_name: name },
        signal: controller.signal,
      });
      if (!controller.signal.aborted) void poll(result.job_id);
    } catch (failure) {
      failed(failure);
    }
  };
  const url = job?.status === 'done' ? videoUrl(job.result) : null;
  const ratio = job ? jobRatio(job) : null;
  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className="min-h-11 min-w-11"
        aria-label="生成视频"
        disabled={busy}
        onClick={() => void start()}
      >
        <Film size={16} aria-hidden />
        视频
      </Button>
      {visible && (
        <section
          className="w-full min-w-0 basis-full space-y-2"
          aria-label="回复视频"
        >
          {busy && (
            <div
              role="status"
              className="max-w-[360px] rounded-lg border border-border p-3 text-sm"
            >
              <p>正在生成视频…</p>
              <progress
                aria-label="视频生成进度"
                max={1}
                value={ratio ?? undefined}
                className="mt-2 h-1 w-full accent-accent"
              />
              <p className="mt-1 text-xs text-secondary">通常约 30 秒</p>
            </div>
          )}
          {error && (
            <div role="alert" className="text-sm text-danger">
              {error}{' '}
              <Button
                variant="ghost"
                size="sm"
                className="min-h-11 min-w-11"
                aria-label="重试生成视频"
                onClick={() => void start()}
              >
                重试
              </Button>
            </div>
          )}
          {url && (
            <div className="max-w-[360px] space-y-2">
              <video
                controls
                playsInline
                preload="metadata"
                poster={portrait}
                src={url}
                onError={() => {
                  setJob(null);
                  setError('视频播放失败，请重试');
                  try {
                    sessionStorage.removeItem(key);
                  } catch {
                    // Storage is optional.
                  }
                }}
                aria-label="回复的真人视频"
                aria-describedby={`video-text-${id}`}
                className="w-full max-w-[360px] rounded-lg"
              />
              <p id={`video-text-${id}`} className="sr-only">
                {answer.reply}
              </p>
              <a
                href={url}
                download="twin-video.mp4"
                className="inline-flex min-h-11 items-center text-sm text-accent underline"
              >
                保存
              </a>
              {job?.result?.warnings.map((warning, index) => {
                const sentence = /^s(\d+): cer=/.exec(warning);
                return (
                  <p key={index} role="note" className="text-xs text-secondary">
                    {sentence
                      ? Number(sentence[1]) === 1
                        ? '开头提示回听与原文有出入'
                        : `第 ${Number(sentence[1]) - 1} 句回听与原文有出入`
                      : '视频生成有提示，请检查回听结果'}
                  </p>
                );
              })}
            </div>
          )}
        </section>
      )}
    </>
  );
}
