import { create } from 'zustand';

const KEY = 'twin:chat-layout';
/** The conversation sheet's width in CSS pixels: the default matches --spacing-chat-sheet. */
export const SHEET_WIDTH = { min: 220, default: 280, max: 440 } as const;
type Choices = { sheet?: boolean; stage?: boolean };
type Preferences = Choices & { sheetWidth?: number };
export function clampSheetWidth(width: number): number {
  return Math.round(
    Math.min(SHEET_WIDTH.max, Math.max(SHEET_WIDTH.min, width)),
  );
}
function read(): Preferences {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(KEY) ?? '{}');
    if (!value || typeof value !== 'object') return {};
    const input = value as Preferences;
    return {
      sheet: typeof input.sheet === 'boolean' ? input.sheet : undefined,
      stage: typeof input.stage === 'boolean' ? input.stage : undefined,
      sheetWidth:
        typeof input.sheetWidth === 'number' &&
        Number.isFinite(input.sheetWidth)
          ? clampSheetWidth(input.sheetWidth)
          : undefined,
    };
  } catch {
    return {};
  }
}
export const useChatLayout = create<
  Preferences & {
    setChoice(key: keyof Choices, value: boolean): void;
    setSheetWidth(width: number): void;
  }
>((set, get) => {
  const save = () => {
    try {
      const { sheet, stage, sheetWidth } = get();
      localStorage.setItem(KEY, JSON.stringify({ sheet, stage, sheetWidth }));
    } catch {
      /* Private browsing may deny storage; the choice still lasts this session. */
    }
  };
  return {
    ...read(),
    setChoice(key, value) {
      set({ [key]: value });
      save();
    },
    setSheetWidth(width) {
      set({ sheetWidth: clampSheetWidth(width) });
      save();
    },
  };
});
