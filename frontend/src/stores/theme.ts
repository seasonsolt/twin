import { create } from 'zustand';
import { usePersonaEdition } from './auth';

/** The team's palettes in design/tokens.css: 朱砂红 is the default, the others set <html data-theme>. */
export const THEMES = [
  { id: 'red', label: '朱砂红' },
  { id: 'blue', label: '海蓝' },
  { id: 'ink', label: '墨夜' },
] as const;
/** The persona edition's 素体 palettes, all dark: 体温 is its default. */
export const SUTAI_THEMES = [
  { id: 'sutai', label: '体温' },
  { id: 'amber', label: '琥珀' },
  { id: 'moon', label: '月光' },
] as const;
export type ThemeId =
  (typeof THEMES)[number]['id'] | (typeof SUTAI_THEMES)[number]['id'];

const DEFAULT: ThemeId = 'red';
const KEY = 'twin:theme';
// The edition's default when nothing was chosen, so the next visit starts in it before the server has answered.
const EDITION_KEY = 'twin:theme-default';
const DARK = new Set<ThemeId>(['ink', 'sutai', 'amber', 'moon']);
const isTheme = (value: unknown): value is ThemeId =>
  [...THEMES, ...SUTAI_THEMES].some((theme) => theme.id === value);

export const themesFor = (persona: boolean) =>
  persona ? SUTAI_THEMES : THEMES;
/** The palettes beside this one, for a page shown before the server says which edition it is (signing in). */
export const familyOf = (theme: ThemeId) =>
  themesFor(SUTAI_THEMES.some((option) => option.id === theme));
const editionDefault = (persona: boolean): ThemeId =>
  persona ? 'sutai' : DEFAULT;

// Choices of this browser only: storage can be blocked or empty, and then the default is used.
function read(key: string): ThemeId | null {
  try {
    const value = localStorage.getItem(key);
    return isTheme(value) ? value : null;
  } catch {
    return null;
  }
}
function write(key: string, theme: ThemeId) {
  try {
    localStorage.setItem(key, theme);
  } catch {
    // Not remembered, but still shown until the page is closed.
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
    ?.setAttribute('content', DARK.has(theme) ? 'dark' : 'light');
}

export const useTheme = create<{
  theme: ThemeId;
  setTheme: (theme: ThemeId) => void;
  /** Once the server says which edition it runs: keep a choice made in it, else show the edition's default. */
  adoptEdition: (persona: boolean) => void;
}>((set) => ({
  theme: read(KEY) ?? read(EDITION_KEY) ?? DEFAULT,
  setTheme: (theme) => {
    write(KEY, theme);
    applyTheme(theme);
    set({ theme });
  },
  adoptEdition: (persona) => {
    const chosen = read(KEY);
    const own = themesFor(persona).some((theme) => theme.id === chosen);
    const theme = own && chosen ? chosen : editionDefault(persona);
    write(EDITION_KEY, editionDefault(persona));
    applyTheme(theme);
    set({ theme });
  },
}));

/** The current palette, the palettes this edition offers, and how to pick one. */
export function useThemes() {
  const persona = usePersonaEdition();
  const { theme, setTheme } = useTheme();
  return { theme, setTheme, options: themesFor(persona) };
}
