import { create } from 'zustand';
import { api } from '../lib/api';
import { getPersonaId } from '../lib/persona';

export interface Status {
  target_name: string;
  counts: { sources: number; items: number };
  llm: { provider: string; model: string };
  embed: { provider: string };
  egress: {
    kind: string;
    provider: string;
    host: string | null;
    external: boolean;
    declared: boolean;
  }[];
}

export const useStatus = create<{
  data: Status | null;
  error: string | null;
  refresh: (signal?: AbortSignal) => Promise<void>;
}>((set) => ({
  data: null,
  error: null,
  refresh: async (signal) => {
    const persona = getPersonaId();
    try {
      const data = await api<Status>('/api/status', { signal });
      if (!signal?.aborted && persona === getPersonaId())
        set({ data, error: null });
    } catch (error) {
      if (!signal?.aborted && persona === getPersonaId())
        set({ error: error instanceof Error ? error.message : '状态加载失败' });
    }
  },
}));

export function startStatusPolling() {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | undefined;
  let stopped = false;
  let initialLoading = true;
  const poll = async () => {
    if (stopped || (document.hidden && !initialLoading)) return;
    const active = new AbortController();
    controller = active;
    await useStatus.getState().refresh(active.signal);
    initialLoading = false;
    if (
      !stopped &&
      !document.hidden &&
      controller === active &&
      !active.signal.aborted
    )
      timer = setTimeout(() => void poll(), 10_000);
  };
  const visibility = () => {
    clearTimeout(timer);
    if (initialLoading) return;
    controller?.abort();
    if (!document.hidden) void poll();
  };
  document.addEventListener('visibilitychange', visibility);
  void poll();
  return () => {
    stopped = true;
    clearTimeout(timer);
    controller?.abort();
    document.removeEventListener('visibilitychange', visibility);
  };
}
