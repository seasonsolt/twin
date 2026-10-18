import { create } from 'zustand';

const KEY = 'twin:chat-layout';
type Preferences = { sheet?: boolean; stage?: boolean };
function read(): Preferences {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(KEY) ?? '{}');
    if (!value || typeof value !== 'object') return {};
    const input = value as Preferences;
    return {
      sheet: typeof input.sheet === 'boolean' ? input.sheet : undefined,
      stage: typeof input.stage === 'boolean' ? input.stage : undefined,
    };
  } catch {
    return {};
  }
}
export const useChatLayout = create<
  Preferences & { setChoice(key: keyof Preferences, value: boolean): void }
>((set, get) => ({
  ...read(),
  setChoice(key, value) {
    set({ [key]: value });
    try {
      const { sheet, stage } = get();
      localStorage.setItem(KEY, JSON.stringify({ sheet, stage }));
    } catch {
      /* Private browsing may deny storage; the choice still lasts this session. */
    }
  },
}));
