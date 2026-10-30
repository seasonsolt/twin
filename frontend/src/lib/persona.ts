import { withBase } from './base';
let current = 'default';
try {
  current = localStorage.getItem('twin:persona') || 'default';
} catch {
  // Storage is optional.
}
export const getPersonaId = () => current;
export function setPersonaId(id: string) {
  current = id;
  try {
    localStorage.setItem('twin:persona', id);
  } catch {
    // Switching still works without storage.
  }
}
/** An heir's twin for this visit (P2.7): kept only in memory, so the person's own choice of twin stays as it was. */
export function adoptPersonaId(id: string) {
  current = id;
}
// While an heir is in, what this browser keeps of a twin is theirs alone: not the person's, nor another heir's.
let heir = '';
export function setHeirKeys(id: string) {
  heir = id;
}
// Preserve existing default-persona history without migrating it.
export const personaKey = (key: string, id = current) =>
  heir
    ? `twin.heir:${heir}:${id}:${key}`
    : id === 'default'
      ? key
      : `twin.persona:${id}:${key}`;
export function forgetPersona(id: string) {
  const prefix = `twin.persona:${id}:`;
  for (const storage of [() => localStorage, () => sessionStorage]) {
    try {
      const store = storage();
      for (let index = store.length - 1; index >= 0; index--) {
        const key = store.key(index);
        if (
          key?.startsWith(prefix) ||
          key?.startsWith(`twin.reply-video:${prefix}`)
        )
          store.removeItem(key);
      }
    } catch {
      // Storage is optional.
    }
  }
}
export function personaUrl(path: string, id = current) {
  if (!path.startsWith('/api/')) return path;
  const url = new URL(path, window.location.origin);
  url.searchParams.set('persona', id);
  return withBase(url.pathname + url.search);
}
