import { create } from 'zustand';
import { api } from '../lib/api';
import { usePersonas } from './personas';

export interface Identity {
  email: string | null;
  /** Display name from single sign-on; email login has none. */
  name?: string | null;
  admin: boolean;
  auth_enabled: boolean;
  /** 'sso' means signing in and out belongs to another app on this site. */
  provider?: 'email' | 'sso' | null;
  /** Pages an administrator switched on or off for everyone; missing (an older server) means on. */
  features?: Partial<Record<Feature, boolean>>;
}

/** Pages that can be switched off. Chat is the twin itself and never is. */
export type Feature = 'work' | 'ledger';

export const featureOn = (identity: Identity | null, feature: Feature) =>
  identity?.features?.[feature] !== false;

/** After an administrator switched a page, show it or hide it at once, without signing in again. */
export function setFeatures(features: Partial<Record<Feature, boolean>>) {
  useAuth.setState((state) => ({
    identity: state.identity && {
      ...state.identity,
      features: { ...state.identity.features, ...features },
    },
  }));
}

export const accountLabel = (identity: Identity) =>
  identity.name || identity.email || '';
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
