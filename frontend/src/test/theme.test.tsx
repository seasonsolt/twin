import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ThemePicker } from '../components/ui';
import { useAuth, type Identity } from '../stores/auth';
import { applyTheme, THEMES, useTheme, useThemes } from '../stores/theme';

const identity: Identity = { email: null, admin: false, auth_enabled: false };

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

function EditionPicker() {
  const { theme, setTheme, options } = useThemes();
  return (
    <ThemePicker value={theme} options={options} onChange={setTheme} named />
  );
}

it('shows the persona edition in 体温 until another 素体 palette is chosen, and keeps the team choice for the team', () => {
  useAuth.setState({ identity: { ...identity, edition: 'persona' } });
  useTheme.getState().adoptEdition(true);
  render(<EditionPicker />);
  expect(document.documentElement.dataset.theme).toBe('sutai');
  expect(screen.getByRole('radio', { name: '体温' })).toBeChecked();
  expect(screen.queryByRole('radio', { name: '朱砂红' })).toBeNull();
  // Nothing was chosen: the default is remembered so the next visit starts in it, but no choice is written.
  expect(localStorage.getItem('twin:theme')).toBeNull();
  expect(localStorage.getItem('twin:theme-default')).toBe('sutai');
  fireEvent.click(screen.getByRole('radio', { name: '月光' }));
  expect(document.documentElement.dataset.theme).toBe('moon');
  useTheme.getState().adoptEdition(true);
  expect(document.documentElement.dataset.theme).toBe('moon');
  // A team palette chosen earlier is not one of the persona edition's: it starts in 体温 and the choice stays.
  localStorage.setItem('twin:theme', 'blue');
  useTheme.getState().adoptEdition(true);
  expect(document.documentElement.dataset.theme).toBe('sutai');
  expect(localStorage.getItem('twin:theme')).toBe('blue');
  useTheme.getState().adoptEdition(false);
  expect(document.documentElement.dataset.theme).toBe('blue');
  useAuth.setState({ identity: null });
});
