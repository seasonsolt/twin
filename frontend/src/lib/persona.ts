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
// Preserve existing default-persona history without migrating it.
export const personaKey = (key: string, id = current) =>
  id === 'default' ? key : `twin.persona:${id}:${key}`;
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
  return url.pathname + url.search;
}
