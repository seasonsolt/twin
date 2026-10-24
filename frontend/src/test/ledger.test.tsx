import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider, TooltipProvider, toast } from '../components/ui';
import { Ledger } from '../pages/Ledger';
import { usePersonas } from '../stores/personas';
import { setPersonaId } from '../lib/persona';
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
    pending_accept: '待你接受',
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
    if (
      url.startsWith('/api/persona/ledger') ||
      url.startsWith('/api/personas/commitments')
    )
      return json(ledger);
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

const setup = (page = <Ledger />) =>
  render(
    <TooltipProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={['/ledger']}>
          <Routes>
            <Route path="ledger" element={page} />
          </Routes>
        </MemoryRouter>
      </ConfirmProvider>
    </TooltipProvider>,
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
  expect(within(objection).getByText('待核对')).toBeInTheDocument();
  expect(
    within(objection).queryByRole('button', { name: '复制确认消息' }),
  ).not.toBeInTheDocument();
  // The meeting is said once, in its heading, not again before every quote under it.
  expect(promise).toHaveTextContent('其他人1：「我周五前给您一版新报价方案」');
  expect(promise).not.toHaveTextContent('经营会');
  // One main action in sight; the rest are behind "更多".
  expect(within(promise).getByRole('button', { name: '确认' })).toBeVisible();
  expect(
    within(promise).getByRole('button', { name: '驳回' }),
  ).not.toBeVisible();
  expect(screen.getByRole('status')).toHaveTextContent(
    '共 1 场会议，都已整理；2 条待确认',
  );

  await user.click(within(promise).getByRole('button', { name: '确认' }));
  await waitFor(() =>
    expect(posts()).toEqual([
      ['/api/persona/ledger/e1/review', { action: 'confirm' }],
    ]),
  );
  await user.click(await within(promise).findByLabelText('更多'));
  expect(
    await within(promise).findByRole('button', { name: '撤销已确认' }),
  ).toBeInTheDocument();
});

it('copies the confirmation message for the owner', async () => {
  const user = userEvent.setup();
  const writeText = vi.spyOn(navigator.clipboard, 'writeText');
  setup();
  const promise = await screen.findByRole('article', {
    name: '承诺：周五前给我一版新报价方案',
  });
  await user.click(within(promise).getByLabelText('更多'));
  await user.click(
    within(promise).getByRole('button', { name: '复制确认消息' }),
  );
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
  await user.click(within(promise).getByLabelText('更多'));
  await user.click(within(promise).getByRole('button', { name: '修改' }));
  const dialog = await screen.findByRole('dialog', { name: '修改这一条' });
  // 待你接受 is what a promise asked for in a conversation waits as, not a state to choose by hand.
  expect(
    within(dialog).queryByRole('option', { name: '待你接受' }),
  ).not.toBeInTheDocument();
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

it('lets the person take or turn down a promise someone asked for in a conversation', async () => {
  const user = userEvent.setup();
  ledger.entries = [
    entry({
      entry_id: 'h1',
      source_id: 'handoff:h1',
      meeting_title: '沈从的对话',
      speaker: '沈从',
      quote: '周五前给我一版发布方案',
      owner: '本人',
      counterpart: '沈从',
      what: '周五前给沈从一版发布方案',
      status: 'pending_accept',
      current_status: 'pending_accept',
      current_status_label: '待你接受',
      confirmation_message: null,
      origin: 'conversation',
      handoff_id: 'h1',
    }),
  ];
  ledger.people = [];
  setup();
  const asked = await screen.findByRole('article', {
    name: '承诺：周五前给沈从一版发布方案',
  });
  expect(within(asked).getByText('待你接受')).toBeInTheDocument();
  expect(
    within(asked).queryByRole('button', { name: '确认' }),
  ).not.toBeInTheDocument();
  await user.click(within(asked).getByRole('button', { name: '接下' }));
  await waitFor(() =>
    expect(posts()).toContainEqual(['/api/persona/ledger/h1/accept', {}]),
  );
  await user.click(within(asked).getByRole('button', { name: '不接' }));
  await waitFor(() =>
    expect(posts()).toContainEqual(['/api/persona/ledger/h1/decline', {}]),
  );
});

it('gives a promise that was turned down no way to be asked again', async () => {
  ledger.entries = [
    entry({
      entry_id: 'h1',
      source_id: 'handoff:h1',
      speaker: '沈从',
      owner: '本人',
      what: '周五前给沈从一版发布方案',
      status: 'pending_accept',
      current_status: 'pending_accept',
      current_status_label: '待你接受',
      confirmation_message: null,
      origin: 'conversation',
      handoff_id: 'h1',
      review: 'rejected',
    }),
  ];
  ledger.people = [];
  const user = userEvent.setup();
  setup();
  await user.click(await screen.findByRole('checkbox', { name: '显示已驳回' }));
  const declined = await screen.findByRole('article', {
    name: '承诺：周五前给沈从一版发布方案',
  });
  expect(within(declined).getByText('已驳回')).toBeInTheDocument();
  expect(within(declined).queryByRole('button')).not.toBeInTheDocument();
});

it('marks a quote that is not the exact words, and explains it on hover', async () => {
  const user = userEvent.setup();
  ledger.entries = [entry({ quote_exact: false })];
  setup();
  const badge = await screen.findByText('非原话');
  expect(screen.queryByText(/没有找到逐字原话/u)).not.toBeInTheDocument();
  await user.hover(badge);
  expect(
    (await screen.findAllByText('没有找到逐字原话，显示整句')).length,
  ).toBeGreaterThan(0);
});

it('speaks of the ledger’s owner by name when someone else is looking at it', async () => {
  setPersonaId('p-1');
  usePersonas.setState({
    id: 'p-1',
    items: [
      {
        id: 'p-1',
        name: '林舟',
        avatar_url: null,
        sources: 1,
        created_at: '',
        is_default: false,
      },
    ],
  });
  ledger.entries[0] = entry({ owner: '本人', counterpart: '老王' });
  try {
    const user = userEvent.setup();
    setup();
    const promise = await screen.findByRole('article', {
      name: '承诺：周五前给我一版新报价方案',
    });
    expect(within(promise).getByText('林舟 → 老王')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '林舟' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: '我自己' })).toBeNull();
    await user.click(within(promise).getByLabelText('更多'));
    await user.click(within(promise).getByRole('button', { name: '修改' }));
    expect(
      await screen.findByText('写「本人」表示林舟自己'),
    ).toBeInTheDocument();
  } finally {
    usePersonas.setState({ id: '', items: [] });
  }
});

it('names the twins whose meetings are still to be read when everyone’s list has nothing yet', async () => {
  const user = userEvent.setup();
  const opened: string[] = [];
  ledger = {
    ...ledger,
    entries: [],
    people: [],
    meetings: { total: 2, pending: 1 },
    twins: [
      { id: 'p-1', name: '林舟', pending: 1 },
      { id: 'p-2', name: '许清禾', pending: 0 },
    ],
  };
  setup(<Ledger everyone onOpen={(id) => opened.push(id)} />);
  expect(await screen.findByText('选一位，去整理会议。')).toBeVisible();
  expect(screen.queryByRole('button', { name: '许清禾' })).toBeNull();
  await user.click(screen.getByRole('button', { name: '林舟' }));
  expect(opened).toEqual(['p-1']);
});
