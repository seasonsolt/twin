import { api } from './api';
import { personaKey, personaUrl } from './persona';
import type { Status } from '../stores/status';
import type { Capabilities } from '../features/avatar/types';
import type { Turn } from '../features/chat/types';

export interface PrefetchedConversation {
  id: string;
  title: string;
  turns: Turn[];
}
interface Entry {
  promise: Promise<unknown>;
  data?: unknown;
}
const entries = new Map<string, Entry>();
const key = (id: string, path: string) => `${id}:${path}`;

export function peekEssential<T>(path: string, id: string): T | undefined {
  return entries.get(key(id, path))?.data as T | undefined;
}

export function loadEssential<T>(
  path: string,
  id: string,
  signal?: AbortSignal,
): Promise<T> {
  const entry = entries.get(key(id, path));
  if (entry) {
    entries.delete(key(id, path));
    return entry.promise as Promise<T>;
  }
  return api<T>(path, { signal, headers: { 'X-Twin-Persona': id } });
}

export function currentConversationPath(id: string) {
  try {
    const saved = localStorage.getItem(
      personaKey('twin.current.conversation', id),
    );
    return saved ? `/api/conversations/${encodeURIComponent(saved)}` : null;
  } catch {
    return null;
  }
}

export function clearPrefetch() {
  entries.clear();
}

export function prefetchPersona(
  id: string,
  signal: AbortSignal,
  portrait?: string | null,
) {
  const load = <T>(path: string) => {
    const entry: Entry = { promise: Promise.resolve() };
    entry.promise = api<T>(path, { signal, headers: { 'X-Twin-Persona': id } })
      .then((data) => {
        if (!signal.aborted) entry.data = data;
        return data;
      })
      .catch((error: unknown) => {
        if (entries.get(key(id, path)) === entry) entries.delete(key(id, path));
        throw error;
      });
    entries.set(key(id, path), entry);
    return entry.promise as Promise<T>;
  };
  const decode = async (url?: string | null) => {
    if (!url || signal.aborted) return;
    const image = new Image();
    image.src = personaUrl(url, id);
    if (image.decode) await image.decode();
  };
  const conversation = currentConversationPath(id);
  return Promise.allSettled([
    load<Status>('/api/status'),
    load<Capabilities>('/api/media/capabilities').then((caps) =>
      decode(caps.avatar_image?.url || portrait),
    ),
    ...(conversation ? [load<PrefetchedConversation>(conversation)] : []),
    // Identity is also needed by the shell's onboarding check and About.
    load('/api/identity'),
  ]);
}
