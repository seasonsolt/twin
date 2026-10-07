import { startTransition } from 'react';
import { create } from 'zustand';
import { api } from '../lib/api';
import { getPersonaId, setPersonaId } from '../lib/persona';
import { useStatus, type Status } from './status';
import {
  clearPrefetch,
  loadEssential,
  peekEssential,
  prefetchPersona,
} from '../lib/personaPrefetch';

export interface Persona {
  id: string;
  name: string;
  avatar_url: string | null;
  sources: number;
  created_at: string;
  is_default: boolean;
  public?: boolean;
  can_manage?: boolean;
  owner?: string | null;
}
let refreshVersion = 0;
let switchVersion = 0;
let prefetchController: AbortController | undefined;
export const usePersonas = create<{
  id: string;
  items: Persona[];
  pendingId: string | null;
  refresh: () => Promise<void>;
  switchTo: (id: string) => Promise<void>;
  reset: () => void;
}>((set, get) => ({
  id: getPersonaId(),
  items: [],
  pendingId: null,
  reset() {
    ++refreshVersion;
    ++switchVersion;
    prefetchController?.abort();
    clearPrefetch();
    setPersonaId('');
    useStatus.setState({ data: null, error: null });
    set({ id: '', pendingId: null, items: [] });
  },
  async switchTo(id) {
    if (id === get().id && get().pendingId === null) return;
    const version = ++switchVersion;
    prefetchController?.abort();
    clearPrefetch();
    set({ pendingId: id });
    if (id === get().id) {
      set({ pendingId: null });
      return;
    }
    const controller = new AbortController();
    prefetchController = controller;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const loading = prefetchPersona(
      id,
      controller.signal,
      get().items.find((item) => item.id === id)?.avatar_url,
    );
    await Promise.race([
      loading,
      new Promise<void>((resolve) => {
        timer = setTimeout(resolve, 800);
      }),
    ]);
    clearTimeout(timer);
    if (version !== switchVersion || controller.signal.aborted) return;
    startTransition(() => {
      window.dispatchEvent(new Event('twin-persona-switch'));
      document
        .querySelectorAll<HTMLMediaElement>('audio, video')
        .forEach((media) => {
          if (media.hasAttribute('src') || !media.paused) media.pause();
        });
      setPersonaId(id);
      useStatus.setState({
        data: peekEssential<Status>('/api/status', id) ?? null,
        error: null,
      });
      set({ id, pendingId: null });
    });
    void loadEssential<Status>('/api/status', id, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted && get().id === id)
          useStatus.setState({ data, error: null });
      })
      .catch(() => {});
  },
  async refresh() {
    const version = ++refreshVersion;
    // The registry is global, including when a persisted persona was deleted.
    const items = await api<Persona[]>('/api/personas');
    if (version !== refreshVersion) return;
    if (!Array.isArray(items)) throw new Error('无法加载分身列表');
    set({ items });
    if (!items.some((item) => item.id === get().id))
      await get().switchTo(
        items.find((item) => item.is_default)?.id ?? items[0]?.id ?? '',
      );
  },
}));

// Someone else's public twin can only be talked to.
export const useCanManage = () =>
  usePersonas(
    (state) =>
      state.items.find((item) => item.id === state.id)?.can_manage ?? true,
  );
