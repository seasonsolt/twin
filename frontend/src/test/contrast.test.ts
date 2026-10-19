import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';

const css = readFileSync('src/design/tokens.css', 'utf-8');
const historyCss = readFileSync('src/features/chat/history.css', 'utf-8');

function luminance(hex: string) {
  const rgb = hex
    .slice(1)
    .match(/.{2}/g)!
    .map((part) => {
      const value = parseInt(part, 16) / 255;
      return value <= 0.04045
        ? value / 12.92
        : ((value + 0.055) / 1.055) ** 2.4;
    });
  return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
}
function contrast(a: string, b: string) {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

const tokens = (block: string): Record<string, string> =>
  Object.fromEntries(
    [...block.matchAll(/--([\w-]+):\s*(#[\da-f]{6})/gi)].map((pair) => [
      pair[1],
      pair[2],
    ]),
  );
const base = tokens(css.match(/:root\s*\{([^}]+)\}/)![1]);
// Each named theme only sets what differs from the default, so it is read over it.
const named = [...css.matchAll(/:root\[data-theme='(\w+)'\]\s*\{([^}]+)\}/g)];
// The stage is the accent unless a theme gives it a ground of its own (--stage-bg: var(--accent) by default).
const withStage = (theme: Record<string, string>) =>
  theme['stage-bg'] ? theme : { ...theme, 'stage-bg': theme.accent };
const themes = [
  withStage(base),
  ...named.map((match) => withStage({ ...base, ...tokens(match[2]) })),
];

describe('WCAG AA tokens', () => {
  it('starts in 朱砂红 and offers 海蓝 and 墨夜, even when the system is dark', () => {
    expect(named.map((match) => match[1])).toEqual(['blue', 'ink']);
    expect(themes[0]).toMatchObject({
      canvas: '#fff4ea',
      accent: '#c9432c',
      'text-primary': '#2b1d16',
      'text-secondary': '#6b4a3a',
      border: '#f2dfcf',
      soft: '#fbe9dd',
      sun: '#f5b83d',
    });
    expect(themes[1]).toMatchObject({ canvas: '#f3f5f8', accent: '#1f5fbf' });
    expect(css).not.toContain('prefers-color-scheme: dark');
    for (const theme of themes) {
      expect(
        contrast(theme.canvas, theme['text-primary']),
      ).toBeGreaterThanOrEqual(4.5);
      expect(
        contrast(theme['stage-ink'], theme['stage-bg']),
        'stage ink on the stage',
      ).toBeGreaterThanOrEqual(4.5);
    }
    expect(
      contrast(themes[0]['text-primary'], themes[0].sun),
    ).toBeGreaterThanOrEqual(4.5);
  });
  it('keeps history group labels readable on the accent and current items solid ground with ink', () => {
    expect(historyCss).toMatch(
      /\.stage-history \.history-group-label\s*\{[^}]*color: var\(--on-accent\)/s,
    );
    expect(
      contrast(themes[0]['on-accent'], themes[0].accent),
    ).toBeGreaterThanOrEqual(4.5);
    expect(historyCss).toMatch(
      /\.stage-history \.history-entry\[data-current='true'\]\s*\{[^}]*background: var\(--canvas\)[^}]*color: var\(--text-primary\)/s,
    );
    expect(historyCss).not.toContain('box-shadow: inset');
  });
  it.each(themes.map((theme, index) => [index, theme] as const))(
    'theme %i covers stage, yellow cards, status chips, outline inputs and video controls',
    (_index, theme) => {
      for (const [foreground, background] of [
        ['text-primary', 'note'],
        ['text-secondary', 'note'],
        ['text-primary', 'sun'],
        ['text-primary', 'soft'],
        ['on-accent', 'accent'],
        ['canvas', 'text-primary'],
        ['success', 'surface'],
        ['accent-ink', 'surface'],
      ]) {
        expect(
          contrast(theme[foreground], theme[background]),
          `${foreground} on ${background}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
      for (const surface of ['canvas', 'surface', 'accent']) {
        const outline = surface === 'accent' ? 'canvas' : 'text-primary';
        expect(contrast(theme[outline], theme[surface])).toBeGreaterThanOrEqual(
          3,
        );
      }
    },
  );
  for (const [index, theme] of themes.entries()) {
    it(`theme ${index} text and status colors have 4.5:1 on every surface`, () => {
      for (const text of [
        'text-primary',
        'text-secondary',
        'text-tertiary',
        'accent-ink',
        'success',
        'warning',
        'danger',
        'info',
      ]) {
        for (const surface of ['canvas', 'surface', 'surface-raised']) {
          expect(
            contrast(theme[text], theme[surface]),
            `${text} on ${surface}`,
          ).toBeGreaterThanOrEqual(4.5);
        }
      }
      for (const accent of ['accent', 'accent-hover', 'accent-pressed']) {
        expect(
          contrast(theme['on-accent'], theme[accent]),
        ).toBeGreaterThanOrEqual(4.5);
      }
    });
  }
});
