const KEY = 'twin:recent-personas';
const KEEP = 10;

/** Twins this browser switched to, most recent first; the rail shows the first few beside the current one. */
export function recentPersonas(): string[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(KEY) ?? '[]');
    return Array.isArray(value)
      ? value.filter((id): id is string => typeof id === 'string')
      : [];
  } catch {
    return [];
  }
}

export function rememberPersona(id: string) {
  if (!id) return;
  try {
    localStorage.setItem(
      KEY,
      JSON.stringify(
        [id, ...recentPersonas().filter((other) => other !== id)].slice(
          0,
          KEEP,
        ),
      ),
    );
  } catch {
    // The rail falls back to list order without storage.
  }
}
