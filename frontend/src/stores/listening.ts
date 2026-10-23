import { create } from 'zustand';

const KEY = 'twin:listen-original';

// A choice of this browser only: storage can be blocked or empty, and then the denoised audio plays.
function stored(): boolean {
  try {
    return localStorage.getItem(KEY) === '1';
  } catch {
    return false;
  }
}

/**
 * Whether recordings play as recorded instead of denoised (``media.denoise``). The denoised copy is clearer to
 * listen to; the original is there to check exactly what was said. Every player of the library follows the choice.
 */
export const useListening = create<{
  original: boolean;
  setOriginal: (original: boolean) => void;
}>((set) => ({
  original: stored(),
  setOriginal: (original) => {
    try {
      if (original) localStorage.setItem(KEY, '1');
      else localStorage.removeItem(KEY);
    } catch {
      // Not remembered, but kept until the page is closed.
    }
    set({ original });
  },
}));

/** A library clip's address as the listener chose to hear it. */
export function heard(src: string, original: boolean): string {
  return original ? `${src}${src.includes('?') ? '&' : '?'}original=true` : src;
}

/** ``heard`` with the listener's choice, for players that have no switch of their own. */
export function useHeard(): (src: string) => string {
  const original = useListening((state) => state.original);
  return (src) => heard(src, original);
}
