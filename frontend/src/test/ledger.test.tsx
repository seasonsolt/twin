import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider, toast } from '../components/ui';
import { Ledger } from '../pages/Ledger';
import type {
  LedgerBrief,
  LedgerData,
  LedgerEntry,
} from '../features/ledger/types';

vi.mock('../components/ui', async (original) => ({
  ...(await original<typeof import('../components/ui')>()),
  toast: vi.fn(),
}));
vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status });

function entry(overrides: Partial<LedgerEntry>): LedgerEntry {
  return {
    entry_id: 'e1',
    source_id: 'm1',
    meeting_date: '2026-10-12',
    meeting_title: '经营会',
    kind: 'commitment',
    kind_label: '承诺',
    speaker: '其他人1',
    quote: '我周五前给您一版新报价方案',
    quote_exact: true,
    owner: '老王',
    counterpart: '本人',
    what: '周五前给我一版新报价方案',
    due: '2026-10-16',
    due_text: '周五前',
    condition: '',
    relates_to: null,
    status: null,
    status_label: null,
    current_status: 'open',
    current_status_label: '进行中',
    confidence: 0.9,
    review: 'unreviewed',
    version: 1,
    thread: 'e1',
    confirmation_message:
      '老王，确认一下10月12日经营会上说的：周五前给我一版新报价方案，10月16日前。有出入直接回我。',
    ...overrides,
  };
}

const labels = {
  kind_labels: {
    decision: '决定',
    commitment: '承诺',
    objection: '异议',
    progress: '进展',
  },
  status_labels: {
    open: '进行中',
    claimed_done: '本人称已完成',
    evidenced: '已有交付证据',
    confirmed_done: '对方确认完成',
    not_done: '未完成',
    reopened: '重新打开',
    unknown: '未知',
  },
} satisfies Pick<LedgerData, 'kind_labels' | 'status_labels'>;

let ledger: LedgerData;
let fetcher: ReturnType<typeof vi.fn>;
const posts = () =>
  fetcher.mock.calls
    .filter(([, options]) => options?.method === 'POST')
    .map(([url, options]) => [url, JSON.parse(String(options.body))]);

beforeEach(() => {
  vi.mocked(toast).mockClear();
  ledger = {
    ...labels,
    entries: [
      entry({}),
      entry({
        entry_id: 'e2',
        kind: 'objection',
        kind_label: '异议',
        quote: '实施费单列像变相涨价',
        what: '实施费单列像变相涨价',
        due: null,
        due_text: '',
        counterpart: '',
        confirmation_message: null,
        confidence: 0.4,
      }),
    ],
    people: ['老王'],
    meetings: { total: 1, pending: 0 },
    job_id: null,
  };
  fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.startsWith('/api/persona/ledger/brief'))
      return json({
        person: '老王',
        as_of: '2026-10-19',
        theirs: [ledger.entries[0]],
        mine: [],
        progress: [],
        objections: [ledger.entries[1]],
        questions: [
          {
            entry_id: 'e1',
            text: '「周五前给我一版新报价方案」原定10月16日前，现在进展如何？',
          },
        ],
      } satisfies LedgerBrief);
    if (url.startsWith('/api/persona/ledger/build'))
      return json({ job_id: 'job1', notice: null }, 202);
    if (url.endsWith('/review')) {
      const body = JSON.parse(String(options?.body)) as { action: string };
      ledger.entries[0] = {
        ...ledger.entries[0],
        review: body.action === 'confirm' ? 'confirmed' : 'edited',
      };
      return json(ledger.entries[0]);
    }
    if (url.startsWith('/api/persona/ledger')) return json(ledger);
    if (url === '/api/jobs/job1')
      return json({
        job_id: 'job1',
        kind: 'ledger_build',
        status: 'done',
        result: { sources: 1, entries: 2, dropped: 0 },
      });
    if (url === '/api/jobs') return json([]);
    return json({});
  });
  vi.stubGlobal('fetch', fetcher);
});

const setup = () =>
  render(
    <ConfirmProvider>
      <MemoryRouter initialEntries={['/ledger']}>
        <Routes>
          <Route path="ledger" element={<Ledger />} />
        </Routes>
      </MemoryRouter>
    </ConfirmProvider>,
  );

it('groups entries by meeting with their status, quote and review actions', async () => {
  const user = userEvent.setup();
  setup();
  const meeting = await screen.findByRole('region', { name: '10月12日经营会' });
  const promise = within(meeting).getByRole('article', {
    name: '承诺：周五前给我一版新报价方案',
  });
  expect(within(promise).getByText('进行中')).toBeInTheDocument();
  expect(within(promise).getByText('老王 → 本人')).toBeInTheDocument();
  expect(within(promise).getByText('10月16日（周五前）')).toBeInTheDocument();
  expect(promise).toHaveTextContent('「我周五前给您一版新报价方案」');
  const objection = within(meeting).getByRole('article', {
    name: '异议：实施费单列像变相涨价',
  });
  expect(within(objection).getByText('把握不大，请核对')).toBeInTheDocument();
  expect(
    within(objection).queryByRole('button', { name: '复制确认消息' }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent(
    '共 1 场会议，都已整理；2 条待确认',
  );

  await user.click(within(promise).getByRole('button', { name: '确认' }));
  await waitFor(() =>
    expect(posts()).toEqual([
      ['/api/persona/ledger/e1/review', { action: 'confirm' }],
    ]),
  );
  expect(
    await within(meeting).findByRole('button', { name: '撤销已确认' }),
  ).toBeInTheDocument();
});

it('copies the confirmation message for the owner', async () => {
  const user = userEvent.setup();
  const writeText = vi.spyOn(navigator.clipboard, 'writeText');
  setup();
  await user.click(await screen.findByRole('button', { name: '复制确认消息' }));
  expect(writeText).toHaveBeenCalledWith(
    ledger.entries[0].confirmation_message,
  );
  await waitFor(() =>
    expect(toast).toHaveBeenCalledWith(
      '确认消息已复制，可以发给对方',
      'success',
    ),
  );
});

it('sends only the corrected fields when an entry is edited', async () => {
  const user = userEvent.setup();
  setup();
  const promise = await screen.findByRole('article', {
    name: '承诺：周五前给我一版新报价方案',
  });
  await user.click(within(promise).getByRole('button', { name: '修改' }));
  const dialog = await screen.findByRole('dialog', { name: '修改这一条' });
  const due = within(dialog).getByLabelText('截止日期');
  await user.clear(due);
  await user.type(due, '2026-10-17');
  await user.selectOptions(
    within(dialog).getByRole('combobox', { name: '状态' }),
    'claimed_done',
  );
  await user.click(within(dialog).getByRole('button', { name: '保存' }));
  await waitFor(() =>
    expect(posts()).toEqual([
      [
        '/api/persona/ledger/e1/review',
        {
          action: 'edit',
          changes: { due: '2026-10-17', status: 'claimed_done' },
        },
      ],
    ]),
  );
  await waitFor(() =>
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
  );
});

it('reads the new meetings and reports what it found', async () => {
  const user = userEvent.setup();
  ledger.meetings = { total: 2, pending: 1 };
  setup();
  await user.click(
    await screen.findByRole('button', { name: '整理 1 场新会议' }),
  );
  await waitFor(() =>
    expect(toast).toHaveBeenCalledWith('读了 1 场会议，记下 2 条', 'success'),
  );
  expect(posts()).toEqual([['/api/persona/ledger/build', {}]]);
  expect(
    screen.queryByRole('button', { name: '重新整理全部' }),
  ).not.toBeInTheDocument();
});

it('shows the questions to ask before meeting someone', async () => {
  const user = userEvent.setup();
  setup();
  await user.click(await screen.findByRole('tab', { name: '见面前' }));
  expect(
    await screen.findByText(
      '「周五前给我一版新报价方案」原定10月16日前，现在进展如何？',
    ),
  ).toBeInTheDocument();
  const brief = fetcher.mock.calls
    .map(([url]) => String(url))
    .find((url) => url.startsWith('/api/persona/ledger/brief'));
  expect(new URL(brief ?? '', 'http://x').searchParams.get('person')).toBe(
    '老王',
  );
  expect(
    screen.getByRole('region', { name: '老王提过的顾虑' }),
  ).toHaveTextContent('实施费单列像变相涨价');
  expect(
    within(screen.getByRole('region', { name: '老王答应的事' })).queryByRole(
      'button',
    ),
  ).not.toBeInTheDocument();
});

it('explains how to get meetings when there are none', async () => {
  ledger = {
    ...ledger,
    entries: [],
    people: [],
    meetings: { total: 0, pending: 0 },
  };
  setup();
  expect(
    await screen.findByText(
      '还没有会议。添加有你和别人发言的录音或会议记录，并选出哪位是你。',
    ),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: /整理/ }),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
});
