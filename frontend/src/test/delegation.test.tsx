import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { TooltipProvider } from '../components/ui';
import { Delegation } from '../features/delegation/Delegation';
import type {
  DelegationTarget,
  DelegationView,
} from '../features/delegation/types';
import { setPersonaId } from '../lib/persona';
import { usePersonas } from '../stores/personas';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const target = (overrides: Partial<DelegationTarget>): DelegationTarget => ({
  persona_id: 'p-wang',
  name: '王屿',
  conversation_id: 'c-wang',
  state: 'answered',
  answer: '能接受。两家大客户都说 3 月前不急，希望年底别动。',
  mode: 'grounded',
  ask: '',
  team_answer: null,
  handoff: null,
  owner_reply: null,
  also: [],
  ...overrides,
});
const asked = (targets: DelegationTarget[]): DelegationView => ({
  id: 'd1',
  question: '旧模板延到明年 3 月，客户能接受吗？',
  targets,
  limit: 3,
});
const note = { id: 'd1', summary: '客户能接受；脚本排期等陈一。', asked: 2 };

let view: DelegationView;
let fetcher: ReturnType<typeof vi.fn>;
const posts = () =>
  fetcher.mock.calls
    .filter(([, init]) => init?.method === 'POST')
    .map(([url, init]) => [url, JSON.parse(String(init.body))]);

beforeEach(() => {
  setPersonaId('default');
  usePersonas.setState({ id: 'default', items: [] });
  view = asked([
    target({ also: [{ persona_id: 'p-shen', name: '沈从' }] }),
    target({
      persona_id: 'p-chen',
      name: '陈一',
      conversation_id: 'c-chen',
      state: 'needs_owner',
      answer: '脚本做完七成。排期我回头答复你。',
      mode: 'general',
      ask: '脚本排期怎么定',
    }),
  ]);
  fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return json(view);
    if (url === '/api/persona/delegations/d1') return json(view);
    return json({});
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => vi.unstubAllGlobals());

const mount = () =>
  render(
    <TooltipProvider>
      <MemoryRouter>
        <Delegation note={note} />
      </MemoryRouter>
    </TooltipProvider>,
  );

it('shows a card for each twin that was asked, then the assistant’s own note marked as not theirs', async () => {
  mount();
  const wang = await screen.findByRole('article', { name: '王屿的分身的回答' });
  expect(within(wang).getByText('答了')).toBeVisible();
  expect(within(wang).getByText(/两家大客户都说 3 月前不急/u)).toBeVisible();
  expect(within(wang).getByRole('link', { name: '依据 ›' })).toHaveAttribute(
    'href',
    '/chat?with=p-wang&open=c-wang',
  );
  const chen = screen.getByRole('article', { name: '陈一的分身的回答' });
  expect(within(chen).getByText('要本人定')).toBeVisible();
  // Said once: the badge, then the two buttons, with no question that says it again.
  expect(within(chen).queryByText(/本人吗/u)).toBeNull();
  const mine = screen.getByLabelText('我的归纳');
  expect(within(mine).getByText('我的归纳 · 非原话')).toBeVisible();
  expect(within(mine).getByText('客户能接受；脚本排期等陈一。')).toBeVisible();
  expect(screen.getByText('只走一跳')).toBeVisible();
});

it('hands a question to its twin’s person only when the asker presses the card, and says where it stands', async () => {
  const user = userEvent.setup();
  mount();
  const chen = await screen.findByRole('article', { name: '陈一的分身的回答' });
  expect(posts()).toEqual([]);
  view = asked([
    view.targets[0],
    {
      ...view.targets[1],
      state: 'handed',
      handoff: { status: 'delivered', status_label: '已送达' },
    },
  ]);
  await user.click(within(chen).getByRole('button', { name: '转给本人' }));
  await waitFor(() =>
    expect(posts()).toEqual([
      ['/api/persona/delegations/d1/forward', { conversation_id: 'c-chen' }],
    ]),
  );
  expect(await within(chen).findByRole('status')).toHaveTextContent(
    '已转给陈一本人 · 已送达',
  );
  expect(within(chen).queryByRole('button', { name: '转给本人' })).toBeNull();
});

it('shows what the colleague wrote back as theirs, on the card', async () => {
  view = asked([
    view.targets[0],
    {
      ...view.targets[1],
      state: 'replied',
      owner_reply: '排期下周三前给你。',
      handoff: { status: 'replied', status_label: '已回复' },
    },
  ]);
  mount();
  const chen = await screen.findByRole('article', { name: '陈一的分身的回答' });
  expect(within(chen).getByText('本人已回')).toBeVisible();
  const reply = within(chen).getByLabelText('陈一本人');
  expect(within(reply).getByText('排期下周三前给你。')).toBeVisible();
  // The note still says 等陈一: out of date once he has answered.
  expect(screen.queryByLabelText('我的归纳')).toBeNull();
});

it('lets the asker leave a question where it is', async () => {
  const user = userEvent.setup();
  mount();
  const chen = await screen.findByRole('article', { name: '陈一的分身的回答' });
  view = asked([view.targets[0], { ...view.targets[1], state: 'skipped' }]);
  await user.click(within(chen).getByRole('button', { name: '先不用' }));
  await waitFor(() =>
    expect(posts()).toEqual([
      ['/api/persona/delegations/d1/skip', { conversation_id: 'c-chen' }],
    ]),
  );
  await waitFor(() =>
    expect(within(chen).queryByRole('button', { name: '转给本人' })).toBeNull(),
  );
});

it('offers to ask someone an answer sends the asker to, and asks them when the person says so', async () => {
  const user = userEvent.setup();
  mount();
  const wang = await screen.findByRole('article', { name: '王屿的分身的回答' });
  expect(within(wang).getByText('答案提到了沈从')).toBeVisible();
  view = asked([
    { ...view.targets[0], also: [] },
    view.targets[1],
    target({
      persona_id: 'p-shen',
      name: '沈从',
      conversation_id: 'c-shen',
      answer: '合同那家我来跟客户谈。',
    }),
  ]);
  await user.click(
    within(wang).getByRole('button', { name: '也问问沈从的分身' }),
  );
  await waitFor(() =>
    expect(posts()).toEqual([
      ['/api/persona/delegations/d1/ask', { persona_id: 'p-shen' }],
    ]),
  );
  expect(
    await screen.findByRole('article', { name: '沈从的分身的回答' }),
  ).toBeVisible();
  expect(screen.queryByRole('button', { name: /也问问/u })).toBeNull();
  // The note was written about the two first asked: with a third card it is out of date, and the cards say it.
  expect(screen.queryByLabelText('我的归纳')).toBeNull();
});

it('shows a team answer the twin’s person had confirmed as it stands, and says when the answers cannot be read', async () => {
  view = asked([
    target({
      answer: '团队里已经有确认过的答案，见上面的团队答案。',
      team_answer: {
        id: 'ta_1',
        persona_id: 'p-wang',
        owner_name: '王屿',
        title: '旧模板延期客户能接受吗',
        body: '能接受，不过年底前别动。',
        confirmed_at: '2026-10-22T09:00:00+00:00',
        status: 'valid',
        stale_note: '',
        partial: false,
      },
    }),
  ]);
  mount();
  const wang = await screen.findByRole('article', { name: '王屿的分身的回答' });
  expect(within(wang).getByRole('article', { name: '团队答案' })).toBeVisible();
  expect(within(wang).getByText('能接受，不过年底前别动。')).toBeVisible();
});

it('says when the answers could not be read', async () => {
  fetcher.mockImplementation(async () =>
    json({ detail: '团队库暂时读不了' }, 503),
  );
  mount();
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '团队库暂时读不了',
  );
});
