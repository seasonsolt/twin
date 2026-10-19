import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider, toast } from '../components/ui';
import type { TranscriptRoster } from '../features/sources/TranscriptClaim';
import { setPersonaId } from '../lib/persona';
import { Memories } from '../pages/Memories';
import { isSourcesUrl, sourcesPage } from './personaApi';

vi.mock('../components/ui', async (original) => ({
  ...(await original<typeof import('../components/ui')>()),
  toast: vi.fn(),
}));
vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
const json = (value: unknown) => new Response(JSON.stringify(value));
const anonymous = {
  source_id: 'anon',
  title: '周会',
  first_date: '2026-09-01',
  speakers: [
    {
      label: '发言人1',
      segments: 2,
      chars: 13,
      files: 1,
      samples: ['方案先这么定。'],
    },
    {
      label: '发言人2',
      segments: 2,
      chars: 13,
      files: 1,
      samples: ['同意，我来写文档。'],
    },
  ],
};
const aliases = { aliases: [], fixed: ['林沐'], not_me: 0 };
let roster: TranscriptRoster;
let waiting: string[];
let fetcher: ReturnType<typeof vi.fn>;
beforeEach(() => {
  setPersonaId('p-test');
  vi.mocked(toast).mockClear();
  waiting = ['n1', 'anon'];
  roster = {
    pending: 2,
    names: [
      {
        name: '小明',
        segments: 2,
        chars: 80,
        files: 1,
        samples: ['我觉得排期太紧了，要不要往后挪一周？', '行。'],
        likely: '说得最多',
      },
      {
        name: '林沐老师',
        segments: 2,
        chars: 30,
        files: 2,
        samples: ['不挪，先核对。'],
        likely: '和你的名字相近',
      },
      {
        name: '小张',
        segments: 1,
        chars: 10,
        files: 1,
        samples: ['上线前要回归吗？'],
        likely: null,
      },
    ],
    names_total: 3,
    files: [],
    files_total: 0,
    ...aliases,
  };
  fetcher = vi.fn(async (url: string, init: RequestInit = {}) => {
    if (isSourcesUrl(url))
      return json(
        sourcesPage(
          url,
          ['n1', 'anon'].map((id) => ({
            source_id: id,
            title: id,
            first_date: null,
            detected_kind_label: '访谈',
            status: waiting.includes(id) ? 'needs_name' : 'remembered',
            remembered: 1,
          })),
        ),
      );
    if (url === '/api/persona/processing') return json({ state: 'idle' });
    if (url === '/api/status')
      return json({ counts: { sources: 2, items: 0 }, egress: [] });
    if (url === '/api/persona/transcripts/speakers') return json(roster);
    if (url === '/api/persona/transcripts/names') {
      waiting = ['anon'];
      roster = {
        ...roster,
        pending: 1,
        names: [],
        names_total: 0,
        files: [anonymous],
        files_total: 1,
        aliases: ['林沐老师'],
      };
      return json({ ...roster, changed: 2 });
    }
    if (
      url === '/api/persona/transcripts/not-mine' ||
      url === '/api/persona/transcripts/anon/speakers'
    ) {
      waiting = [];
      roster = { ...roster, pending: 0, files: [], files_total: 0 };
      return json({ ...roster, changed: 1 });
    }
    throw new Error(`${init.method ?? 'GET'} ${url}`);
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => setPersonaId('default'));

const bodies = (url: string) =>
  fetcher.mock.calls
    .filter(([called]) => called === url)
    .map(([, init]) => JSON.parse((init as RequestInit).body as string));

async function openClaim() {
  render(
    <ConfirmProvider>
      <MemoryRouter initialEntries={['/memories']}>
        <Memories />
      </MemoryRouter>
    </ConfirmProvider>,
  );
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole('button', {
      name: '有 2 份文字记录需要确认哪位是你',
    }),
  );
  const dialog = await screen.findByRole('dialog', { name: '哪位是你' });
  return { user, dialog };
}

it('claims names across files in one step and lists the label-only files after', async () => {
  const { user, dialog } = await openClaim();
  await within(dialog).findByRole('checkbox', { name: /林沐老师/ });
  // Nothing is picked for the person, however likely.
  for (const box of within(dialog).getAllByRole('checkbox'))
    expect(box).not.toBeChecked();
  const row = within(dialog)
    .getByRole('checkbox', { name: /林沐老师/ })
    .closest('li')!;
  expect(within(row).getByText('可能是你')).toHaveAttribute(
    'title',
    '和你的名字相近',
  );
  expect(
    within(row).getByText('2 段 · 约 30 字 · 出现在 2 份文件里'),
  ).toBeVisible();
  expect(within(row).getByText('“不挪，先核对。”')).toBeVisible();
  expect(
    within(dialog).getByRole('button', { name: '这 3 个名字都不是我' }),
  ).toBeVisible();

  await user.click(within(dialog).getByRole('checkbox', { name: /林沐老师/ }));
  await user.click(
    within(dialog).getByRole('button', {
      name: '确认：1 个是我，其余 2 个不是',
    }),
  );
  await waitFor(() =>
    expect(bodies('/api/persona/transcripts/names')).toEqual([
      { mine: ['林沐老师'], others: ['小明', '小张'] },
    ]),
  );
  expect(toast).toHaveBeenCalledWith('已确认，正在重新整理记忆', 'success');
  expect(await within(dialog).findByText('周会')).toBeVisible();
  expect(within(dialog).getByText('“同意，我来写文档。”')).toBeVisible();
  expect(
    await screen.findByRole('button', {
      name: '有 1 份文字记录需要确认哪位是你',
      // Behind the open dialog.
      hidden: true,
    }),
  ).toBeInTheDocument();

  await user.click(
    within(dialog).getByRole('button', { name: '这 1 份都不是我' }),
  );
  await waitFor(() =>
    expect(bodies('/api/persona/transcripts/not-mine')).toEqual([
      { source_ids: ['anon'] },
    ]),
  );
  expect(await within(dialog).findByText('都确认好了')).toBeVisible();
  await waitFor(() =>
    expect(
      screen.queryByRole('button', {
        name: /份文字记录需要确认/,
        hidden: true,
      }),
    ).not.toBeInTheDocument(),
  );
});

it('picks one label in a label-only file', async () => {
  roster = {
    ...roster,
    names: [],
    names_total: 0,
    files: [anonymous],
    files_total: 1,
  };
  const { user, dialog } = await openClaim();
  const confirm = await within(dialog).findByRole('button', {
    name: '确认这份',
  });
  expect(confirm).toBeDisabled();
  await user.click(within(dialog).getByRole('radio', { name: /发言人1 是我/ }));
  await user.click(confirm);
  await waitFor(() =>
    expect(bodies('/api/persona/transcripts/anon/speakers')).toEqual([
      { speakers: ['发言人1'] },
    ]),
  );
  expect(
    fetcher.mock.calls.find(
      ([url]) => url === '/api/persona/transcripts/anon/speakers',
    )?.[1].method,
  ).toBe('PUT');
});
