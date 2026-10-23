import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider, TooltipProvider } from '../components/ui';
import type { LedgerData, LedgerEntry } from '../features/ledger/types';
import { Commitments } from '../pages/Commitments';
import { usePersonas, type Persona } from '../stores/personas';
import { setPersonaId } from '../lib/persona';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));

const json = (value: unknown) =>
  new Response(JSON.stringify(value), { status: 200 });
const twin = (change: Partial<Persona>): Persona => ({
  id: 'p-1',
  name: '林舟',
  avatar_url: null,
  sources: 2,
  created_at: '',
  is_default: false,
  can_manage: true,
  ...change,
});
const entry = {
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
  review: 'confirmed',
  version: 1,
  thread: 'e1',
  confirmation_message: null,
} as LedgerEntry;
const ledger: LedgerData = {
  entries: [entry],
  people: ['老王'],
  meetings: { total: 1, pending: 0 },
  job_id: null,
  kind_labels: { commitment: '承诺' },
  status_labels: { open: '进行中' },
} as unknown as LedgerData;

let asked: { url: string; persona: string | null }[];
beforeEach(() => {
  asked = [];
  setPersonaId('p-1');
  usePersonas.setState({
    id: 'p-1',
    items: [twin({}), twin({ id: 'p-2', name: '许清禾' })],
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      asked.push({
        url,
        persona: new Headers(init?.headers).get('X-Twin-Persona'),
      });
      if (url.startsWith('/api/persona/ledger')) return json(ledger);
      if (url === '/api/jobs') return json([]);
      return json({});
    }),
  );
});

it('shows the commitments of the person chosen in the page itself, with the way to choose another', async () => {
  render(
    <TooltipProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={['/commitments']}>
          <Commitments />
        </MemoryRouter>
      </ConfirmProvider>
    </TooltipProvider>,
  );
  expect(screen.getByRole('heading', { name: '承诺' })).toBeVisible();
  expect(
    screen.getByRole('button', { name: '切换分身（当前：林舟）' }),
  ).toBeVisible();
  const meeting = await screen.findByRole('region', { name: '10月12日经营会' });
  expect(
    within(meeting).getByRole('article', {
      name: '承诺：周五前给我一版新报价方案',
    }),
  ).toBeVisible();
  // The ledger asked is the chosen twin's, and the page keeps no second heading or blurb of its own.
  expect(
    asked.filter((call) => call.url.startsWith('/api/persona/ledger?')),
  ).toEqual([
    { url: '/api/persona/ledger?include_rejected=true', persona: 'p-1' },
  ]);
  expect(screen.queryByText('承诺账本')).toBeNull();
});

it('lists everyone together on request, and changes an entry in the ledger that keeps it', async () => {
  const together = {
    ...ledger,
    entries: [
      {
        ...entry,
        owner: '林舟',
        counterpart: '',
        review: 'unreviewed',
        persona_id: 'p-2',
        persona_name: '林舟',
        meeting: 'rec_1',
      } as LedgerEntry,
    ],
    people: ['林舟'],
    twins: [
      { id: 'p-1', name: '林舟' },
      { id: 'p-2', name: '许清禾' },
    ],
  };
  const calls: { url: string; persona: string | null; body?: string }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({
        url,
        persona: new Headers(init?.headers).get('X-Twin-Persona'),
        body: typeof init?.body === 'string' ? init.body : undefined,
      });
      if (url.startsWith('/api/personas/commitments')) return json(together);
      if (url.includes('/review')) return json(together.entries[0]);
      return json({});
    }),
  );
  render(
    <TooltipProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={['/commitments?who=all']}>
          <Commitments />
        </MemoryRouter>
      </ConfirmProvider>
    </TooltipProvider>,
  );
  expect(screen.getByRole('button', { name: '全部' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  // Whose twin is chosen no longer matters, and a list of several people has no ledger to build or brief to read.
  expect(screen.queryByRole('button', { name: /切换分身/ })).toBeNull();
  const meeting = await screen.findByRole('region', { name: '10月12日经营会' });
  expect(
    calls.filter((call) => call.url.startsWith('/api/persona/ledger')),
  ).toEqual([]);
  expect(screen.queryByRole('tab', { name: '见面前' })).toBeNull();
  expect(screen.queryByRole('button', { name: /整理/ })).toBeNull();
  within(meeting).getByRole('button', { name: '确认' }).click();
  await vi.waitFor(() =>
    expect(calls.find((call) => call.url.includes('/review'))).toMatchObject({
      url: '/api/persona/ledger/e1/review',
      persona: 'p-2',
    }),
  );
});
