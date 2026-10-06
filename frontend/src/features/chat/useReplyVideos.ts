import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../../lib/api';
import type { Job } from '../jobs/useJob';
import type { Turn } from './types';

export interface VideoResult {
  file: string;
  duration_s: number;
  warnings: string[];
}
export interface ReplyVideoState {
  status: 'generating' | 'done' | 'failed';
  jobId?: string;
  result?: VideoResult;
}
export const videoUrl = (result?: VideoResult) =>
  result && /^[0-9a-f]{64}\.mp4$/.test(result.file)
    ? `/api/media/video/${result.file}`
    : null;
const key = (id: string) => `twin.reply-video:${id}`;
const submissions = new Map<string, Promise<{ job_id: string }>>();
function restore(id: string): ReplyVideoState | undefined {
  try {
    const saved = JSON.parse(sessionStorage.getItem(key(id)) ?? 'null');
    if (saved?.status === 'done' && videoUrl(saved.result)) return saved;
    if (saved?.status === 'failed')
      return { status: 'failed', jobId: saved.jobId };
    if (saved?.status === 'generating' && typeof saved.jobId === 'string')
      return saved;
  } catch {
    // Session storage is optional.
  }
}
function save(id: string, state: ReplyVideoState) {
  try {
    sessionStorage.setItem(key(id), JSON.stringify(state));
  } catch {
    // Keep the mounted page's cache when storage is unavailable.
  }
}
function wait(signal: AbortSignal) {
  return new Promise<void>((resolve) => {
    const finish = () => {
      clearTimeout(timer);
      signal.removeEventListener('abort', finish);
      resolve();
    };
    const timer = setTimeout(finish, 1000);
    signal.addEventListener('abort', finish, { once: true });
    if (signal.aborted) finish();
  });
}

function runningJobs() {
  const records = new Map<string, ReplyVideoState>(
    [...submissions.keys()].map((id) => [id, { status: 'generating' }]),
  );
  try {
    for (let index = 0; index < sessionStorage.length; index++) {
      const storedKey = sessionStorage.key(index);
      if (!storedKey?.startsWith('twin.reply-video:')) continue;
      const id = storedKey.slice('twin.reply-video:'.length);
      const state = restore(id);
      if (state?.jobId && state.status !== 'done') records.set(id, state);
    }
  } catch {
    // Session storage is optional.
  }
  return records;
}

export function useReplyVideos(active: boolean, turns: Turn[], name: string) {
  const [cache] = useState(runningJobs);
  const records = useRef(cache);
  const [view, setView] = useState<Record<string, ReplyVideoState>>({});
  const actions = useRef({
    update(_turns: Turn[], _name: string) {
      void _turns;
      void _name;
    },
    retry(_id: string) {
      void _id;
    },
  });
  useEffect(() => {
    if (!active) return;
    let alive = true;
    let pending: Turn[] = [];
    let persona = '';
    let running = false;
    const controller = new AbortController();
    const publish = (id: string, state: ReplyVideoState) => {
      records.current.set(id, state);
      save(id, state);
      if (alive) setView(Object.fromEntries(records.current));
    };
    const run = async (id: string, turn?: Turn) => {
      let state = records.current.get(id)!;
      try {
        if (!state.jobId) {
          let submission = submissions.get(id);
          if (!submission) {
            submission = api<{ job_id: string }>('/api/media/video', {
              method: 'POST',
              json: {
                kind: 'chat_reply',
                answer: turn!.reply,
                persona_name: persona,
              },
            });
            submissions.set(id, submission);
          }
          const result = await submission;
          submissions.delete(id);
          state = { status: 'generating', jobId: result.job_id };
          publish(id, state);
        }
        while (alive) {
          const job = await api<Job<VideoResult>>(
            `/api/media/video/jobs/${encodeURIComponent(state.jobId!)}`,
            { signal: controller.signal },
          );
          if (!alive) return;
          if (job.status === 'done') {
            state = { status: 'done', result: job.result };
            if (!videoUrl(job.result)) throw new Error('视频文件不可用');
            publish(id, state);
            return;
          }
          if (job.status === 'failed') {
            state = { status: 'failed' };
            throw new Error('视频生成失败');
          }
          await wait(controller.signal);
        }
      } catch (error) {
        submissions.delete(id);
        if (alive)
          publish(id, {
            status: 'failed',
            jobId:
              error instanceof ApiError && error.status === 404
                ? undefined
                : state.jobId,
          });
      }
    };
    const pump = async () => {
      if (!alive || running) return;
      const unresolved = [...records.current].find(
        ([id, state]) =>
          (state.jobId || submissions.has(id)) && state.status !== 'done',
      );
      if (unresolved?.[1].status === 'failed') return;
      const next = [...pending]
        .reverse()
        .find((turn) => records.current.get(turn.id)?.status === 'generating');
      const id = unresolved?.[0] ?? next?.id;
      if (!id) return;
      running = true;
      await run(id, next);
      running = false;
      if (alive) void pump();
    };
    actions.current = {
      update(next, nextName) {
        persona = nextName;
        pending = next.filter(
          (turn) =>
            turn.role === 'twin' &&
            turn.reply &&
            !turn.reply.abstain &&
            turn.reply.mode !== 'abstain',
        );
        for (const turn of pending) {
          if (!records.current.has(turn.id))
            records.current.set(
              turn.id,
              restore(turn.id) ?? { status: 'generating' },
            );
        }
        setView(Object.fromEntries(records.current));
        void Promise.resolve().then(pump);
      },
      retry(id) {
        if (records.current.get(id)?.status !== 'failed') return;
        publish(id, {
          status: 'generating',
          jobId: records.current.get(id)?.jobId,
        });
        void pump();
      },
    };
    return () => {
      alive = false;
      controller.abort();
      actions.current = { update() {}, retry() {} };
    };
  }, [active]);
  useEffect(() => {
    actions.current.update(turns, name);
  }, [active, turns, name]);
  return {
    videos: view,
    retry: (id: string) => actions.current.retry(id),
    invalidate: (id: string) => {
      const state: ReplyVideoState = { status: 'failed' };
      records.current.set(id, state);
      save(id, state);
      setView(Object.fromEntries(records.current));
    },
  };
}
