import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ThemePicker } from '../components/ui';
import { applyTheme, THEMES, useTheme } from '../stores/theme';

afterEach(() => {
  localStorage.clear();
  useTheme.getState().setTheme('red');
  localStorage.clear();
  vi.restoreAllMocks();
});

function Picker() {
  const { theme, setTheme } = useTheme();
  return (
    <ThemePicker value={theme} options={THEMES} onChange={setTheme} named />
  );
}

it('starts in 朱砂红 with no data-theme, and remembers another palette in this browser', () => {
  applyTheme(useTheme.getState().theme);
  render(<Picker />);
  expect(document.documentElement.dataset.theme).toBeUndefined();
  expect(screen.getByRole('radio', { name: '朱砂红' })).toBeChecked();
  expect(screen.getByText('朱砂红')).toBeVisible();
  fireEvent.click(screen.getByRole('radio', { name: '墨夜' }));
  expect(document.documentElement.dataset.theme).toBe('ink');
  expect(screen.getByRole('radio', { name: '墨夜' })).toBeChecked();
  expect(localStorage.getItem('twin:theme')).toBe('ink');
  fireEvent.click(screen.getByRole('radio', { name: '朱砂红' }));
  expect(document.documentElement.dataset.theme).toBeUndefined();
});

it('still switches when the browser blocks storage', () => {
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('blocked');
  });
  render(<Picker />);
  fireEvent.click(screen.getByRole('radio', { name: '海蓝' }));
  expect(document.documentElement.dataset.theme).toBe('blue');
});
