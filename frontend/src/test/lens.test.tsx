import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider, TooltipProvider } from '../components/ui';
import type { ChatReply } from '../features/chat/types';
import { LensCard } from '../features/lens/LensCard';
import { LensTab } from '../features/lens/LensTab';
import {
  dayLabel,
  type FacetVerdict,
  type Lens,
  type LensCardData,
  type LensList,
  type LensUse,
} from '../features/lens/types';
import { setPersonaId } from '../lib/persona';
import { Chat } from '../pages/Chat';
import { useAuth } from '../stores/auth';
import { useChatLayout } from '../stores/chatLayout';
import { usePersonas, type Persona } from '../stores/personas';
import { useStatus } from '../stores/status';
import { useTeam } from '../stores/team';
import { conversationServer } from './conversationServer';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const facet = (
  id: string,
  name: string,
  dimension: string,
  extra: Partial<FacetVerdict> = {},
): FacetVerdict => ({
  facet_id: id,
  name,
  dimension_id: 'D3',
  dimension,
  level: 3,
  label: '了解较多',
  checked: false,
  checked_label: '',
  occasions: 4,
  ok: true,
  reasons: [],
  ...extra,
});
const facets = [
  facet('5.1', '拿手的事', '擅长什么', { checked: true }),
  facet('3.4', '常见取舍', '怎么做决定'),
  facet('3.3', '依据偏好', '怎么做决定', { checked: true }),
  facet('4.2', '追问习惯', '怎么思考', {
    ok: false,
    level: 2,
    label: '了解一些',
    reasons: ['场合不足 3 个'],
  }),
  facet('2.3', '做事的原则', '看重什么', {
    ok: false,
    level: 1,
    label: '提到过',
    reasons: ['多是别人的话', '来源只有一种'],
  }),
];
const lens = (extra: Partial<Lens> = {}): Lens => ({
  id: 'l1',
  name: '大客户谈判',
  status: 'active',
  published_at: '2026-10-20T09:00:00+00:00',
  audience: { scope: 'team', twins: [] },
  facets: [
    { facet_id: '3.4', name: '常见取舍' },
    { facet_id: '3.3', name: '依据偏好' },
  ],
  speaking: ['3.4', '3.3'],
  failing: [],
  stopped: [],
  uses_week: 12,
  ...extra,
});
/** Today as the server writes a day, in the local time the page reads it in. */
const today = () => {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
};
const use = (id: string, extra: Partial<LensUse> = {}): LensUse => ({
  id,
  question: '客户嫌报价高，要求再降 10%，我该怎么回？',
  said: '先问清预算是谁定的\n让价换条件，不单方面降',
  facets: [{ facet_id: '3.4', name: '常见取舍' }],
  corrected: false,
  at: today(),
  ...extra,
});

let list: LensList;
let uses: LensUse[];
let fetcher: ReturnType<typeof vi.fn>;
const sent = (suffix: string, method = 'POST') =>
  fetcher.mock.calls.filter(
    ([url, init]) => String(url).endsWith(suffix) && init?.method === method,
  );

beforeEach(() => {
  setPersonaId('default');
  usePersonas.setState({ id: 'default', items: [] });
  useTeam.setState({
    people: [
      { id: 'pe1', name: '沈从', persona_id: 'p-shen' },
      { id: 'pe2', name: '陈一', persona_id: 'p-chen' },
      { id: 'pe3', name: '王屿', persona_id: 'default' },
    ] as never,
  });
  list = { lenses: [], facets, stop_after: 3 };
  uses = [];
  fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    if (url === '/api/persona/lenses' && method === 'GET') return json(list);
    if (url.includes('/uses') && method === 'GET') return json({ uses });
    if (url === '/api/persona/lenses/preview')
      return json({
        views: [
          {
            facet_id: '3.4',
            facet: '常见取舍',
            text: '让价换条件，不单方面降',
            basis: [
              { quote: '我一般拉长合同期', date: '2026-10-01', kind: '音频' },
            ],
          },
        ],
        settled_by_person: true,
      });
    return json(lens());
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => {
  vi.unstubAllGlobals();
  setPersonaId('default');
  useTeam.setState({ people: null });
});

const mount = () =>
  render(
    <TooltipProvider>
      <ConfirmProvider>
        <LensTab person="王屿" twinId="default" />
      </ConfirmProvider>
    </TooltipProvider>,
  );

it('offers to publish when there is no lens, and only the facets that are well founded can be ticked', async () => {
  const user = userEvent.setup();
  mount();
  await user.click(await screen.findByRole('button', { name: '发布赋能' }));
  const panel = await screen.findByRole('dialog', { name: '发布赋能' });
  // What is well founded can be ticked, with where it sits and how well the twin knows it, and the check mark.
  const group = within(panel).getByRole('group', { name: '开放哪些方面' });
  expect(
    within(group).getByRole('checkbox', { name: /擅长什么 › 拿手的事/u }),
  ).toBeEnabled();
  expect(
    within(group).getByRole('checkbox', { name: /常见取舍/u }),
  ).toBeEnabled();
  expect(
    within(group).queryByRole('checkbox', { name: /追问习惯/u }),
  ).toBeNull();
  expect(
    within(group).queryByRole('checkbox', { name: /做事的原则/u }),
  ).toBeNull();
  expect(within(group).getAllByText('✓')).toHaveLength(2);
  // The others are folded with why not.
  await user.click(within(group).getByText('还不能开放 2'));
  // The layer fades in: wait for it to be seen.
  await waitFor(() =>
    expect(within(group).getByText('场合不足 3 个')).toBeVisible(),
  );
  expect(within(group).getByText('多是别人的话、来源只有一种')).toBeVisible();
  // Nothing can be published without a name and a facet.
  const publish = within(panel).getByRole('button', { name: '发布给全团队' });
  expect(publish).toBeDisabled();
  await user.type(
    within(panel).getByRole('textbox', { name: '名字' }),
    '大客户谈判',
  );
  expect(publish).toBeDisabled();
  await user.click(within(group).getByRole('checkbox', { name: /常见取舍/u }));
  expect(
    await within(panel).findByText('让价换条件，不单方面降'),
  ).toBeVisible();
  expect(sent('/lenses/preview')).toHaveLength(1);
  expect(JSON.parse(String(sent('/lenses/preview')[0][1].body))).toEqual({
    facets: ['3.4'],
  });
  await user.click(publish);
  await waitFor(() => expect(sent('/api/persona/lenses')).toHaveLength(1));
  expect(JSON.parse(String(sent('/api/persona/lenses')[0][1].body))).toEqual({
    name: '大客户谈判',
    facets: ['3.4'],
    audience: { scope: 'team', twins: [] },
  });
});

it('publishes to named people, never to the person themself, and needs at least one', async () => {
  const user = userEvent.setup();
  mount();
  await user.click(await screen.findByRole('button', { name: '发布赋能' }));
  const panel = await screen.findByRole('dialog', { name: '发布赋能' });
  await user.type(within(panel).getByRole('textbox', { name: '名字' }), '谈判');
  await user.click(within(panel).getByRole('checkbox', { name: /常见取舍/u }));
  await user.click(within(panel).getByRole('radio', { name: '指定的人' }));
  expect(within(panel).queryByRole('checkbox', { name: '王屿' })).toBeNull();
  expect(
    within(panel).getByRole('button', { name: '发布给 0 人' }),
  ).toBeDisabled();
  await user.click(within(panel).getByRole('checkbox', { name: '沈从' }));
  await user.click(within(panel).getByRole('button', { name: '发布给 1 人' }));
  await waitFor(() => expect(sent('/api/persona/lenses')).toHaveLength(1));
  expect(
    JSON.parse(String(sent('/api/persona/lenses')[0][1].body)).audience,
  ).toEqual({
    scope: 'people',
    twins: ['p-shen'],
  });
});

it('says what the server refused with and keeps the panel open', async () => {
  const user = userEvent.setup();
  fetcher.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === '/api/persona/lenses' && (init?.method ?? 'GET') === 'GET')
      return json(list);
    if (url === '/api/persona/lenses/preview') return json({ views: [] });
    return json({ detail: '还不能开放：常见取舍（来源只有一种）' }, 400);
  });
  mount();
  await user.click(await screen.findByRole('button', { name: '发布赋能' }));
  const panel = await screen.findByRole('dialog', { name: '发布赋能' });
  await user.type(within(panel).getByRole('textbox', { name: '名字' }), '谈判');
  await user.click(within(panel).getByRole('checkbox', { name: /常见取舍/u }));
  await user.click(within(panel).getByRole('button', { name: '发布给全团队' }));
  expect(await within(panel).findByRole('alert')).toHaveTextContent(
    '来源只有一种',
  );
});

it('shows a published lens, what it was used for and not by whom, and corrects a use', async () => {
  const user = userEvent.setup();
  list = { ...list, lenses: [lens()] };
  uses = [
    use('u1'),
    use('u2', { question: '渠道商要独家代理，答应吗？', said: '' }),
  ];
  mount();
  expect(await screen.findByText('王屿 · 大客户谈判')).toBeVisible();
  expect(screen.getByText('已发布')).toBeVisible();
  expect(screen.getByText('全团队 · 2 个方面 · 本周 12 次')).toBeVisible();
  expect(screen.getByText('不显示提问人')).toBeVisible();
  const first = (await screen.findByText(/客户嫌报价高/u)).closest('li')!;
  expect(first).toHaveTextContent(
    '→ 先问清预算是谁定的；让价换条件，不单方面降',
  );
  expect(first).toHaveTextContent('今天');
  expect(
    screen.getByText('渠道商要独家代理，答应吗？').closest('li'),
  ).toHaveTextContent('未回答');
  await user.click(within(first).getByRole('button', { name: /^纠正/u }));
  await waitFor(() => expect(sent('/uses/u1/correct')).toHaveLength(1));
});

it('holds, resumes and takes a lens back only after asking', async () => {
  const user = userEvent.setup();
  list = { ...list, lenses: [lens()] };
  mount();
  await screen.findByText('王屿 · 大客户谈判');
  await user.click(screen.getByRole('button', { name: '暂停' }));
  await waitFor(() => expect(sent('/lenses/l1/pause')).toHaveLength(1));
  list = { ...list, lenses: [lens({ status: 'paused' })] };
  await user.click(screen.getByRole('button', { name: '撤回' }));
  const ask = await screen.findByRole('dialog');
  expect(ask).toHaveTextContent('撤回后不能恢复');
  await user.click(within(ask).getByRole('button', { name: '撤回' }));
  await waitFor(() => expect(sent('/lenses/l1/withdraw')).toHaveLength(1));
});

it('says a facet was corrected out and shows only the uses that touched it', async () => {
  const user = userEvent.setup();
  list = {
    ...list,
    lenses: [
      lens({
        speaking: ['3.3'],
        stopped: [{ facet_id: '3.4', name: '常见取舍', corrected: 3 }],
      }),
    ],
  };
  uses = [use('u1')];
  mount();
  expect(
    await screen.findByText(/“常见取舍”被纠正 3 次，已停用/u),
  ).toBeVisible();
  await user.click(screen.getByText('去看看 →'));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([url]) =>
        String(url).endsWith('/uses?facet=3.4'),
      ),
    ).toBe(true),
  );
});

it('adjusts the scope: a facet that was corrected out is unticked and says so, ticking it opens it afresh', async () => {
  const user = userEvent.setup();
  list = {
    ...list,
    lenses: [
      lens({
        speaking: ['3.3'],
        stopped: [{ facet_id: '3.4', name: '常见取舍', corrected: 3 }],
      }),
    ],
  };
  mount();
  await user.click(await screen.findByRole('button', { name: '调整范围' }));
  const panel = await screen.findByRole('dialog', { name: '调整范围' });
  const stopped = within(panel).getByRole('checkbox', { name: /常见取舍/u });
  expect(stopped).not.toBeChecked();
  expect(within(panel).getByText('已停用')).toBeInTheDocument();
  expect(
    within(panel).getByRole('checkbox', { name: /依据偏好/u }),
  ).toBeChecked();
  await user.click(stopped);
  await user.click(within(panel).getByRole('button', { name: '保存' }));
  await waitFor(() => expect(sent('/lenses/l1', 'PATCH')).toHaveLength(1));
  expect(JSON.parse(String(sent('/lenses/l1', 'PATCH')[0][1].body))).toEqual({
    name: '大客户谈判',
    facets: ['3.3', '3.4'],
    audience: { scope: 'team', twins: [] },
  });
});

it('reads days the way a person says them', () => {
  const now = new Date(2026, 9, 23, 12);
  expect(dayLabel('2026-10-23', now)).toBe('今天');
  expect(dayLabel('2026-10-22', now)).toBe('昨天');
  expect(dayLabel('2026-10-01', now)).toBe('10 月 1 日');
  expect(dayLabel('nope', now)).toBe('');
});

// ------------------------------------------------------------------ what a colleague is shown

const card = (extra: Partial<LensCardData> = {}): LensCardData => ({
  id: 'l1',
  name: '大客户谈判',
  owner_name: '王屿',
  views: [
    {
      facet_id: '3.4',
      facet: '常见取舍',
      text: '让价换条件，比如拉长合同期，不单方面降',
      basis: [{ quote: '我一般拉长合同期', date: '2026-10-01', kind: '音频' }],
    },
  ],
  empty: false,
  settled_by_person: false,
  note: '根据王屿说过的话推测，不代表王屿的意见',
  ...extra,
});

it('shows statements with their basis folded, and says it is inferred and not the person’s opinion', async () => {
  const user = userEvent.setup();
  render(<LensCard card={card()} />);
  expect(
    screen.getByText('让价换条件，比如拉长合同期，不单方面降'),
  ).toBeVisible();
  expect(
    screen.getByText('根据王屿说过的话推测，不代表王屿的意见'),
  ).toBeVisible();
  await user.click(screen.getByText('依据'));
  expect(screen.getByText('“我一般拉长合同期”')).toBeVisible();
  expect(screen.getByText('10 月 1 日 · 音频')).toBeVisible();
  expect(screen.queryByRole('button')).toBeNull();
});

it('points at the person where the matter is theirs to settle or the lens has nothing, and asks them only when told to', async () => {
  const user = userEvent.setup();
  const ask = vi.fn(async () => {});
  const { rerender } = render(
    <LensCard card={card({ settled_by_person: true })} onAskOwner={ask} />,
  );
  expect(screen.getByText('具体怎么定：未开放，可直接问王屿。')).toBeVisible();
  await user.click(screen.getByRole('button', { name: '问王屿本人' }));
  expect(ask).toHaveBeenCalledTimes(1);
  rerender(
    <LensCard card={card({ views: [], empty: true })} onAskOwner={ask} />,
  );
  expect(screen.getByText('没有能回答的内容。')).toBeVisible();
  expect(screen.getByText('可直接问王屿。')).toBeVisible();
  // Where it settles itself there is nothing to ask.
  rerender(<LensCard card={card()} onAskOwner={ask} />);
  expect(screen.queryByRole('button', { name: '问王屿本人' })).toBeNull();
});

it('keeps the button when asking the person failed, and says why', async () => {
  const user = userEvent.setup();
  render(
    <LensCard
      card={card({ settled_by_person: true })}
      onAskOwner={async () => {
        throw new Error('没能转给王屿本人');
      }}
    />,
  );
  await user.click(screen.getByRole('button', { name: '问王屿本人' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '没能转给王屿本人',
  );
  expect(screen.getByRole('button', { name: '问王屿本人' })).toBeEnabled();
});

// ------------------------------------------------------------------ in a colleague's conversation

const twin = (id: string, name: string, extra: Partial<Persona> = {}) =>
  ({
    id,
    name,
    avatar_url: null,
    sources: 3,
    created_at: '',
    is_default: false,
    can_manage: false,
    ...extra,
  }) satisfies Persona;

const answerReply = (extra: Partial<ChatReply> = {}): ChatReply => ({
  reply:
    '让价换条件，比如拉长合同期，不单方面降\n具体怎么定：未开放，可直接问王屿。',
  citations: [],
  confidence: 1,
  abstain: false,
  abstain_reason: '',
  retrieved_ids: [],
  mode: 'general',
  verified: true,
  lens: card({ settled_by_person: true }),
  ...extra,
});

function chatWith(lenses: unknown, onAsk?: (body: unknown) => Response) {
  const server = conversationServer();
  const calls = vi.fn(async (url: string, init?: RequestInit) => {
    const saved = server.respond(url, init);
    if (saved) return saved;
    if (url === '/api/persona/lenses/available') return json({ lenses });
    if (url === '/api/persona/lenses/l1/ask') {
      const body = JSON.parse(String(init?.body)) as {
        question: string;
        conversation_id: string;
      };
      if (onAsk) return onAsk(body);
      const row = server.rows.get(body.conversation_id)!;
      const reply = answerReply();
      row.turns.push(
        {
          id: 'u-lens',
          role: 'user',
          content: body.question,
          timestamp: '2026-10-23T09:00:00',
        },
        {
          id: 't-lens',
          role: 'twin',
          content: reply.reply,
          reply,
          timestamp: '2026-10-23T09:00:01',
        },
      );
      return json(reply);
    }
    if (url === '/api/persona/lenses/ask-owner')
      return json({
        handoff: {
          id: 'h1',
          kind: 'missing',
          status: 'delivered',
          status_label: '已送达',
          owner_name: '王屿',
        },
      });
    if (url === '/api/media/capabilities')
      return json({ available: false, video: { available: false } });
    return json({ stale: false });
  });
  vi.stubGlobal('fetch', calls);
  useAuth.setState({
    identity: {
      email: 'shen@example.com',
      admin: false,
      auth_enabled: true,
      features: {},
    },
  });
  usePersonas.setState({
    id: 'p-wang',
    items: [twin('p-wang', '王屿')],
    switchTo: vi.fn(async () => {}),
  });
  setPersonaId('p-wang');
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: query === '(min-width: 1280px)',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  return {
    calls,
    ...render(
      <TooltipProvider>
        <ConfirmProvider>
          <MemoryRouter initialEntries={['/chat']}>
            <Chat />
          </MemoryRouter>
        </ConfirmProvider>
      </TooltipProvider>,
    ),
  };
}

const offered = [
  {
    id: 'l1',
    name: '大客户谈判',
    owner_name: '王屿',
    facets: [{ facet_id: '3.4', name: '常见取舍' }],
  },
];

it('lets a colleague ask a lens of the twin in view, and shows its answer in the conversation', async () => {
  sessionStorage.clear();
  localStorage.clear();
  useChatLayout.setState({ sheet: undefined, stage: undefined });
  useStatus.setState({ data: null, error: null });
  const user = userEvent.setup();
  const { calls } = chatWith(offered);
  const chip = await screen.findByRole('button', { name: '赋能 · 大客户谈判' });
  expect(chip).toHaveAttribute('aria-pressed', 'false');
  await user.click(chip);
  expect(chip).toHaveAttribute('aria-pressed', 'true');
  const box = screen.getByRole('textbox', { name: '你说' });
  expect(box).toHaveAttribute('placeholder', '向王屿的赋能提问…');
  await user.type(box, '客户嫌报价高，预算是谁定的？');
  await user.click(screen.getByRole('button', { name: '发送' }));
  const asked = await screen.findByText('具体怎么定：未开放，可直接问王屿。');
  expect(asked).toBeVisible();
  expect(
    screen.getByText('根据王屿说过的话推测，不代表王屿的意见'),
  ).toBeVisible();
  const ask = calls.mock.calls.find(
    ([url]) => url === '/api/persona/lenses/l1/ask',
  )!;
  expect(JSON.parse(String(ask[1]?.body))).toMatchObject({
    question: '客户嫌报价高，预算是谁定的？',
  });
  // Nothing was streamed from the twin.
  expect(
    calls.mock.calls.some(([url]) => url === '/api/persona/chat/stream'),
  ).toBe(false);
  // Asking the person themself is a request of its own, and the line under the answer says where it stands.
  await user.click(screen.getByRole('button', { name: '问王屿本人' }));
  expect(await screen.findByText('已转给王屿本人 · 等回复')).toBeVisible();
  expect(screen.queryByRole('button', { name: '问王屿本人' })).toBeNull();
});

it('offers nothing when the twin has no lens for the viewer', async () => {
  sessionStorage.clear();
  localStorage.clear();
  useChatLayout.setState({ sheet: undefined, stage: undefined });
  useStatus.setState({ data: null, error: null });
  chatWith([]);
  await screen.findByRole('textbox', { name: '你说' });
  expect(screen.queryByRole('button', { name: /^赋能/u })).toBeNull();
});

it('shows why when the lens could not be asked any more, and no longer offers it', async () => {
  sessionStorage.clear();
  localStorage.clear();
  useChatLayout.setState({ sheet: undefined, stage: undefined });
  useStatus.setState({ data: null, error: null });
  const user = userEvent.setup();
  let held = false;
  const { calls } = chatWith(offered, () => {
    held = true;
    return json({ detail: '这个赋能现在不能用' }, 404);
  });
  const chip = await screen.findByRole('button', { name: '赋能 · 大客户谈判' });
  await user.click(chip);
  await user.type(screen.getByRole('textbox', { name: '你说' }), '问个问题');
  await user.click(screen.getByRole('button', { name: '发送' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '这个赋能现在不能用',
  );
  expect(held).toBe(true);
  expect(
    calls.mock.calls.filter(([url]) => url === '/api/persona/lenses/available')
      .length,
  ).toBeGreaterThan(0);
});
