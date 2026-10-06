import { useEffect, useMemo, useRef, useState } from 'react';
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
const key = (id: string, assets = '') =>
  `twin.reply-video:${assets ? `${assets}|` : ''}${id}`;
const submissions = new Map<string, Promise<{ job_id: string }>>();
function restore(id: string, assets = ''): ReplyVideoState | undefined {
  try {
    const saved = JSON.parse(sessionStorage.getItem(key(id, assets)) ?? 'null');
    if (saved?.status === 'done' && videoUrl(saved.result)) return saved;
    if (saved?.status === 'failed')
      return { status: 'failed', jobId: saved.jobId };
    if (saved?.status === 'generating' && typeof saved.jobId === 'string')
      return saved;
  } catch {
    // Session storage is optional.
  }
}
function save(id: string, state: ReplyVideoState, assets = '') {
  try {
    sessionStorage.setItem(key(id, assets), JSON.stringify(state));
  } catch {
    // Keep the mounted page's cache when storage is unavailable.
  }
}
function wait(signal: AbortSignal, delay: number) {
  return new Promise<void>((resolve) => {
    const visible = () => {
      if (document.visibilityState === 'visible') finish();
    };
    const finish = () => {
      clearTimeout(timer);
      signal.removeEventListener('abort', finish);
      document.removeEventListener('visibilitychange', visible);
      resolve();
    };
    const timer = setTimeout(finish, delay);
    signal.addEventListener('abort', finish, { once: true });
    document.addEventListener('visibilitychange', visible);
    if (signal.aborted) finish();
  });
}

function runningJobs(assets = '') {
  const prefix = key('', assets);
  const records = new Map<string, ReplyVideoState>(
    [...submissions.keys()]
      .filter(
        (id) => id.startsWith(prefix) && !id.slice(prefix.length).includes('|'),
      )
      .map((id) => [id.slice(prefix.length), { status: 'generating' }]),
  );
  try {
    for (let index = 0; index < sessionStorage.length; index++) {
      const storedKey = sessionStorage.key(index);
      if (!storedKey?.startsWith(prefix)) continue;
      const id = storedKey.slice(prefix.length);
      if (id.includes('|')) continue;
      const state = restore(id, assets);
      if (state?.jobId && state.status !== 'done') records.set(id, state);
    }
  } catch {
    // Session storage is optional.
  }
  return records;
}

export function useReplyVideos(
  active: boolean,
  turns: Turn[],
  name: string,
  assets = '',
) {
  const records = useMemo(() => ({ current: runningJobs(assets) }), [assets]);
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
    const retries = new Set<string>();
    let pollController: AbortController | undefined;
    let resumeVersion = 0;
    const visible = () => {
      if (document.visibilityState !== 'visible') return;
      resumeVersion += 1;
      pollController?.abort();
    };
    document.addEventListener('visibilitychange', visible);
    const publish = (id: string, state: ReplyVideoState) => {
      records.current.set(id, state);
      save(id, state, assets);
      if (alive) setView(Object.fromEntries(records.current));
    };
    const run = async (id: string, turn?: Turn) => {
      let state = records.current.get(id)!;
      let replaceFailedJob = retries.delete(id);
      let backoff = 1000;
      try {
        while (alive) {
          if (!state.jobId) {
            let submission = submissions.get(key(id, assets));
            if (!submission) {
              submission = api<{ job_id: string }>('/api/media/video', {
                method: 'POST',
                json: {
                  kind: 'chat_reply',
                  answer: turn!.reply,
                  persona_name: persona,
                },
              });
              submissions.set(key(id, assets), submission);
            }
            const result = await submission;
            submissions.delete(key(id, assets));
            state = { status: 'generating', jobId: result.job_id };
            publish(id, state);
            if (!alive) return;
          }
          const version = resumeVersion;
          pollController = new AbortController();
          let unknown = false;
          try {
            const job = await api<Job<VideoResult>>(
              `/api/media/video/jobs/${encodeURIComponent(state.jobId!)}`,
              { signal: pollController.signal },
            );
            if (!alive) return;
            if (version !== resumeVersion) continue;
            if (job.status === 'done') {
              if (!videoUrl(job.result)) throw new Error('视频文件不可用');
              publish(id, { status: 'done', result: job.result });
              return;
            }
            backoff = 1000;
            if (job.status !== 'failed') {
              await wait(controller.signal, 1000);
              continue;
            }
          } catch (error) {
            if (!alive) return;
            if (version !== resumeVersion) continue;
            if (!(error instanceof ApiError && error.status === 404)) {
              const delay = backoff;
              backoff = Math.min(backoff * 2, 8000);
              await wait(controller.signal, delay);
              continue;
            }
            unknown = true;
          }
          if (replaceFailedJob && turn) {
            replaceFailedJob = false;
            state = { status: 'generating' };
            publish(id, state);
            continue;
          }
          publish(id, {
            status: 'failed',
            jobId: unknown ? undefined : state.jobId,
          });
          return;
        }
      } catch {
        submissions.delete(key(id, assets));
        if (alive) publish(id, { status: 'failed', jobId: state.jobId });
      }
    };
    const pump = async () => {
      if (!alive || running) return;
      const unresolved = [...records.current].find(
        ([id, state]) =>
          (state.jobId || submissions.has(key(id, assets))) &&
          state.status === 'generating',
      );
      const next = [...pending]
        .reverse()
        .find((turn) => records.current.get(turn.id)?.status === 'generating');
      const id = unresolved?.[0] ?? next?.id;
      if (!id) return;
      running = true;
      await run(
        id,
        pending.find((turn) => turn.id === id),
      );
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
              restore(turn.id, assets) ?? { status: 'generating' },
            );
        }
        setView(Object.fromEntries(records.current));
        void Promise.resolve().then(pump);
      },
      retry(id) {
        if (records.current.get(id)?.status !== 'failed') return;
        retries.add(id);
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
      pollController?.abort();
      document.removeEventListener('visibilitychange', visible);
      actions.current = { update() {}, retry() {} };
    };
  }, [active, assets, records]);
  useEffect(() => {
    actions.current.update(turns, name);
  }, [active, turns, name, assets]);
  return {
    videos: view,
    retry: (id: string) => actions.current.retry(id),
    invalidate: (id: string) => {
      const state: ReplyVideoState = { status: 'failed' };
      records.current.set(id, state);
      save(id, state, assets);
      setView(Object.fromEntries(records.current));
    },
  };
}
