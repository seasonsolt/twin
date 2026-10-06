import { create } from 'zustand';
import { api } from '../lib/api';
import { usePersonas } from './personas';

export interface Identity {
  email: string | null;
  admin: boolean;
  auth_enabled: boolean;
}
let version = 0;
export const useAuth = create<{
  identity: Identity | null;
  login: (signal?: AbortSignal) => Promise<void>;
  logout: () => Promise<void>;
  clear: () => void;
}>((set, get) => ({
  identity: null,
  clear() {
    ++version;
    set({ identity: null });
    usePersonas.getState().reset();
  },
  async login(signal) {
    const current = ++version;
    const identity = await api<Identity>('/api/whoami', { signal });
    if (signal?.aborted || current !== version) return;
    await usePersonas.getState().refresh();
    if (!signal?.aborted && current === version) set({ identity });
  },
  async logout() {
    await api('/api/auth/logout', { method: 'POST' });
    get().clear();
  },
}));
