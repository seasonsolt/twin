import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider } from '../components/ui';
import { Library, type LibraryState, type Recording } from '../pages/Library';
import { resetTeam } from '../stores/team';
import type { PendingMinutes } from '../features/library/MatchMinutes';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const meeting = (id: string, filename: string): Recording => ({
  id,
  filename,
  size: 10,
  kind: 'audio',
  status: 'ready',
  error: '',
  duration_s: 3600,
  transcribed_s: 3600,
  speakers: 2,
  segments: 90,
  created_at: '2026-10-11T00:00:00+00:00',
  people: ['林舟'],
  unsettled: 0,
  can_edit: true,
  minutes: 'auto',
});
const weekly = meeting('r_0708', '190708_1834 周会.m4a');
const review = meeting('r_0709', '190709_0910 评审.m4a');
const brief = (r: Recording, day: string) => ({
  id: r.id,
  filename: r.filename,
  day,
});
const pending: PendingMinutes[] = [
  {
    id: 'pm_1',
    filename: '2019年7月纪要汇总.docx',
    title: '7月8日周会',
    part: 1,
    parts: 2,
    day: '2019-07-08',
    how: '当天唯一',
    matched: true,
    proposal: brief(weekly, '2019-07-08'),
    choices: [brief(weekly, '2019-07-08'), brief(review, '2019-07-09')],
  },
  {
    id: 'pm_2',
    filename: '评审纪要.md',
    title: '评审纪要',
    part: 1,
    parts: 1,
    day: null,
    how: '没有日期',
    matched: false,
    proposal: null,
    choices: [brief(review, '2019-07-09'), brief(weekly, '2019-07-08')],
  },
];

let state: LibraryState;
let attached: unknown;
beforeEach(() => {
  resetTeam();
  attached = undefined;
  state = {
    recordings: [weekly, review],
    pending: 0,
    max_pending: 20,
    minutes_pending: 0,
    asr: true,
    capacity: {
      free_bytes: 50 * 1024 ** 3,
      arriving_bytes: 0,
      arriving: 0,
      headroom_bytes: 20 * 1024 ** 3,
    },
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library') return json(state);
      if (url === '/api/library/recollect') return json({ recordings: [] });
      if (url === '/api/library/minutes/read') {
        state.minutes_pending = pending.length;
        return json({ transcripts: [], unreadable: [], skipped: 1, added: 2 });
      }
      if (url === '/api/library/minutes/pending')
        return json({ items: pending });
      if (url === '/api/library/minutes/attach') {
        attached = JSON.parse(String(init?.body));
        state.minutes_pending = 0;
        return json({ attached: 2, pending: [] });
      }
      throw new Error(url);
    }),
  );
});
afterEach(() => vi.restoreAllMocks());

const show = () =>
  render(
    <MemoryRouter>
      <ConfirmProvider>
        <Library />
      </ConfirmProvider>
    </MemoryRouter>,
  );

it('reads dropped minutes for their meetings and puts them on once someone says so', async () => {
  const user = userEvent.setup({ applyAccept: false });
  show();
  await screen.findByText(weekly.filename);
  await user.upload(screen.getByLabelText('选择录音文件'), [
    new File(['x'], '2019年7月纪要汇总.docx'),
    new File(['x'], '评审纪要.md'),
  ]);
  const dialog = await screen.findByRole('dialog', { name: '挂上纪要 · 2 份' });
  // Those matched by their day fold into one line, opened to check.
  await user.click(
    within(dialog).getByRole('button', { name: '已配上 1 份 · 检查' }),
  );
  expect(within(dialog).getByText('7月8日周会')).toBeInTheDocument();
  expect(within(dialog).getByText('重复 1 份已跳过')).toBeInTheDocument();
  expect(
    within(dialog).getByRole('button', { name: '挂上 1 份' }),
  ).toBeEnabled();
  await user.selectOptions(
    within(dialog).getByLabelText('评审纪要是哪场会'),
    review.id,
  );
  await user.click(within(dialog).getByRole('button', { name: '挂上 2 份' }));
  await waitFor(() =>
    expect(attached).toEqual({
      items: [
        { id: 'pm_1', recording_id: weekly.id },
        { id: 'pm_2', recording_id: review.id },
      ],
    }),
  );
});

it('keeps minutes left for later waiting at the top of the library', async () => {
  state.minutes_pending = 2;
  const user = userEvent.setup();
  show();
  await screen.findByText('2 份纪要待配对');
  await user.click(screen.getByRole('button', { name: '去选' }));
  const dialog = await screen.findByRole('dialog', { name: '挂上纪要 · 2 份' });
  // One left out of those matched: only the other one is put on.
  await user.click(
    within(dialog).getByRole('button', { name: '已配上 1 份 · 检查' }),
  );
  await user.click(
    within(dialog).getByRole('button', {
      name: '不挂：7月8日周会',
    }),
  );
  expect(
    within(dialog).getByRole('button', { name: '挂上 0 份' }),
  ).toBeDisabled();
  await user.click(within(dialog).getByRole('button', { name: '稍后再选' }));
  await waitFor(() =>
    expect(screen.queryByRole('dialog', { name: /挂上纪要/ })).toBeNull(),
  );
  expect(screen.getByText('2 份纪要待配对')).toBeInTheDocument();
});
