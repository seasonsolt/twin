import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { Pace, type PaceState } from '../features/settings/Pace';

let state: PaceState;
let fetcher: ReturnType<typeof vi.fn>;
const json = (value: unknown) => new Response(JSON.stringify(value));

beforeEach(() => {
  state = { pace: { kind: 'off', limit: 30 }, used: null, reminder: null };
  fetcher = vi.fn((path: string, init?: RequestInit) => {
    if (path === '/api/persona/pace' && init?.method === 'PUT')
      state = {
        ...state,
        pace: JSON.parse(String(init.body)) as PaceState['pace'],
      };
    return Promise.resolve(json(state));
  });
  vi.stubGlobal('fetch', fetcher);
});

const puts = () =>
  fetcher.mock.calls
    .filter(([, init]) => (init as RequestInit | undefined)?.method === 'PUT')
    .map(([, init]) => JSON.parse(String((init as RequestInit).body)));

it('is off until the person sets a pace, a number of minutes a day or of times a week', async () => {
  render(<Pace />);
  const kind = await screen.findByRole('combobox', { name: '节奏' });
  expect(kind).toHaveValue('off');
  expect(screen.queryByRole('spinbutton')).toBeNull();
  fireEvent.change(kind, { target: { value: 'daily_minutes' } });
  const minutes = await screen.findByRole('spinbutton', { name: '每天分钟' });
  expect(minutes).toHaveValue(30);
  fireEvent.change(minutes, { target: { value: '45' } });
  fireEvent.blur(minutes);
  // Not a whole number of minutes: put back as it was, nothing saved.
  fireEvent.change(minutes, { target: { value: '0' } });
  fireEvent.blur(minutes);
  await waitFor(() => expect(minutes).toHaveValue(45));
  fireEvent.change(screen.getByRole('combobox', { name: '节奏' }), {
    target: { value: 'weekly_times' },
  });
  expect(
    await screen.findByRole('spinbutton', { name: '每周次数' }),
  ).toBeVisible();
  expect(puts()).toEqual([
    { kind: 'daily_minutes', limit: 30 },
    { kind: 'daily_minutes', limit: 45 },
    { kind: 'weekly_times', limit: 45 },
  ]);
});
