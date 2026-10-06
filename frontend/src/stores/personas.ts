import { create } from 'zustand';
import { api } from '../lib/api';
import { getPersonaId, setPersonaId } from '../lib/persona';
import { useStatus } from './status';

export interface Persona {
  id: string;
  name: string;
  avatar_url: string | null;
  sources: number;
  created_at: string;
  is_default: boolean;
}
let refreshVersion = 0;
export const usePersonas = create<{
  id: string;
  items: Persona[];
  refresh: () => Promise<void>;
  switchTo: (id: string) => void;
}>((set, get) => ({
  id: getPersonaId(),
  items: [],
  switchTo(id) {
    setPersonaId(id);
    useStatus.setState({ data: null, error: null });
    set({ id });
  },
  async refresh() {
    const version = ++refreshVersion;
    // The registry is global, including when a persisted persona was deleted.
    const items = await api<Persona[]>('/api/personas', {
      headers: { 'X-Twin-Persona': 'default' },
    });
    if (version !== refreshVersion) return;
    if (!Array.isArray(items)) throw new Error('无法加载分身列表');
    set({ items });
    if (!items.some((item) => item.id === get().id))
      get().switchTo(items.find((item) => item.is_default)?.id ?? 'default');
  },
}));
