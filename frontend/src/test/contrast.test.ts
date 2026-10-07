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

const themes = [...css.matchAll(/:root\s*\{([^}]+)\}/g)]
  .map((root) =>
    Object.fromEntries(
      [...root[1].matchAll(/--([\w-]+):\s*(#[\da-f]{6})/gi)].map((pair) => [
        pair[1],
        pair[2],
      ]),
    ),
  )
  .filter((theme) => theme.canvas);

describe('WCAG AA tokens', () => {
  it('uses the warm palette even when the system is dark', () => {
    expect(themes).toHaveLength(1);
    expect(themes[0]).toMatchObject({
      canvas: '#fff4ea',
      accent: '#c9432c',
      'text-primary': '#2b1d16',
      'text-secondary': '#6b4a3a',
      border: '#f2dfcf',
      soft: '#fbe9dd',
      sun: '#f5b83d',
    });
    expect(css).not.toContain('prefers-color-scheme: dark');
    expect(
      contrast(themes[0]['text-primary'], themes[0].sun),
    ).toBeGreaterThanOrEqual(4.5);
    expect(
      contrast(themes[0].canvas, themes[0]['text-primary']),
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
  it('covers stage, yellow cards, status chips, outline inputs and video controls', () => {
    const theme = themes[0];
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
  });
  for (const [index, theme] of themes.entries()) {
    it(`${index === 0 ? 'light' : 'dark'} text and status colors have 4.5:1 on every surface`, () => {
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
