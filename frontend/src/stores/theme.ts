import { create } from 'zustand';

/** The palettes in design/tokens.css: 朱砂红 is the default, the others set <html data-theme>. */
export const THEMES = [
  { id: 'red', label: '朱砂红' },
  { id: 'blue', label: '海蓝' },
  { id: 'ink', label: '墨夜' },
] as const;
export type ThemeId = (typeof THEMES)[number]['id'];

const DEFAULT: ThemeId = 'red';
const KEY = 'twin:theme';
const isTheme = (value: unknown): value is ThemeId =>
  THEMES.some((theme) => theme.id === value);

// A choice of this browser only: storage can be blocked or empty, and then the default is used.
function stored(): ThemeId {
  try {
    const value = localStorage.getItem(KEY);
    return isTheme(value) ? value : DEFAULT;
  } catch {
    return DEFAULT;
  }
}

/** Put the palette on the page, and tell the browser its chrome colour and whether it is dark. */
export function applyTheme(theme: ThemeId) {
  const root = document.documentElement;
  if (theme === DEFAULT) delete root.dataset.theme;
  else root.dataset.theme = theme;
  const stage = getComputedStyle(root).getPropertyValue('--stage-bg').trim();
  const accent = getComputedStyle(root).getPropertyValue('--accent').trim();
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute('content', stage.startsWith('#') ? stage : accent);
  document
    .querySelector('meta[name="color-scheme"]')
    ?.setAttribute('content', theme === 'ink' ? 'dark' : 'light');
}

export const useTheme = create<{
  theme: ThemeId;
  setTheme: (theme: ThemeId) => void;
}>((set) => ({
  theme: stored(),
  setTheme: (theme) => {
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      // Not remembered, but still shown until the page is closed.
    }
    applyTheme(theme);
    set({ theme });
  },
}));
