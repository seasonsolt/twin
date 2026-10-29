import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ItemCard } from '../features/profile/ItemCard';
import { Overview } from '../features/profile/Overview';
import { mirrorDraft } from '../features/profile/ItemRow';
import { setPersonaId } from '../lib/persona';
import { useAuth } from '../stores/auth';
import { usePersonas } from '../stores/personas';
import { MemberAt, memberTwin, showTwins } from './member';
import { ConfirmProvider, toast } from '../components/ui';

vi.mock('../components/ui', async (original) => ({
  ...(await original<typeof import('../components/ui')>()),
  toast: vi.fn(),
}));
import type { ProfileItem, Tier } from '../features/profile/types';
import { useStatus } from '../stores/status';
import {
  isItemSearchUrl,
  isItemSummaryUrl,
  isSourcesUrl,
  itemSearch,
  itemSummary,
  itemsPage,
  sourcesPage,
} from './personaApi';

const item: ProfileItem = {
  item_id: 'i/1',
  dimension_id: 'D2',
  dimension_name: 'internal',
  facet_id: '2.1',
  facet_name: 'internal',
  statement: '先听大家的意见',
  extracted_statement: '',
  applies_when: '',
  conflict: '',
  occasions: 1,
  review: 'unreviewed',
  evidence: [
    {
      expression_id: 'e1',
      source_id: 's1',
      source_kind: 'interview',
      quote: '我会先听听',
      date: null,
      own_words: true,
    },
  ],
};
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
let rows: ProfileItem[];
let fetcher: ReturnType<typeof vi.fn>;
let resolveReview: (response: Response) => void;
beforeEach(() => {
  setPersonaId('default');
  usePersonas.setState({ id: 'default', items: [], pendingId: null });
  vi.mocked(toast).mockClear();
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  rows = structuredClone([item]);
  useStatus.setState({ data: null, error: null });
  fetcher = vi.fn((url: string) => {
    if (url === '/api/identity')
      return Promise.resolve(
        json({
          name: '小林',
          about: '喜欢徒步',
          name_source: 'user',
          aliases: [],
          voice: 'preset',
          avatar: null,
        }),
      );
    if (isSourcesUrl(url)) return Promise.resolve(json(sourcesPage(url, [])));
    if (url === '/api/persona/processing')
      return Promise.resolve(json({ state: 'idle' }));
    if (url === '/api/media/capabilities')
      return Promise.resolve(json({ available: false }));
    if (url === '/api/persona/coverage')
      return Promise.resolve(
        json({
          kind_labels: { interview: '访谈' },
          facets: Array.from({ length: 9 }, (_, i) => ({
            facet_id: `${i + 1}.1`,
            dimension_id: `D${i + 1}`,
          })),
          suggestions: Array.from({ length: 9 }, (_, i) => ({
            facet_id: `${i + 1}.1`,
            name: 'internal',
            reason: 'internal',
          })),
        }),
      );
    if (isItemSummaryUrl(url)) return Promise.resolve(json(itemSummary(rows)));
    if (url.startsWith('/api/persona/items?'))
      return Promise.resolve(json(itemsPage(url, rows)));
    if (isItemSearchUrl(url))
      return Promise.resolve(json(itemSearch(url, rows)));
    if (url.endsWith('/review'))
      return new Promise<Response>((resolve) => {
        resolveReview = resolve;
      });
    if (url === '/api/status')
      return Promise.resolve(
        json({ counts: { sources: 1, items: rows.length }, egress: [] }),
      );
    throw new Error(url);
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => {
  setPersonaId('default');
  usePersonas.setState({ id: 'default', items: [], pendingId: null });
  useAuth.setState({ identity: null });
});
const mount = () => {
  showTwins();
  return render(
    <ConfirmProvider>
      <MemberAt />
    </ConfirmProvider>,
  );
};
// What a memory's row keeps under “⋯”: its evidence, removing it, putting its first wording back.
const choose = async (card: ReturnType<typeof within>, name: string) => {
  await userEvent.click(card.getByLabelText(/^更多：/u));
  await userEvent.click(card.getByRole('button', { name }));
};
const mountOverview = () =>
  render(
    <MemoryRouter>
      <ConfirmProvider>
        <Overview />
      </ConfirmProvider>
    </MemoryRouter>,
  );
const article = () => within(screen.getByRole('article'));
// A tab loads its items after it mounts, and switching tabs mounts the new one, so wait for its cards.
const cards = (count: number) =>
  waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(count));
async function complete(
  status: ProfileItem['review'],
  statement = item.statement,
  target = item,
) {
  const updated = {
    ...target,
    review: status,
    statement,
    extracted_statement: status === 'edited' ? target.statement : '',
  };
  rows = rows.map((row) => (row.item_id === target.item_id ? updated : row));
  await act(async () => resolveReview(json(updated)));
}

it('marks only what is worth knowing: an edit, or a memory resting on what others said', async () => {
  rows = [
    { ...item, item_id: 'a', statement: '本人说过的' },
    { ...item, item_id: 'b', statement: '改过的', review: 'edited' },
    {
      ...item,
      item_id: 'c',
      statement: '别人说的',
      evidence: [{ ...item.evidence[0], own_words: false }],
    },
  ];
  mountOverview();
  await cards(3);
  const card = (name: string) => within(screen.getByRole('article', { name }));
  expect(card('本人说过的').queryByText('你改过')).toBeNull();
  expect(card('本人说过的').queryByText('只有别人说')).toBeNull();
  expect(card('改过的').getByText('你改过')).toBeVisible();
  expect(card('别人说的').getByText('只有别人说')).toBeVisible();
  // Nothing waits for a confirmation.
  expect(screen.queryByText(/待确认|已确认/)).toBeNull();
  expect(screen.queryByRole('button', { name: /^对$|全部确认/ })).toBeNull();
});

it('groups by plain topics, hides internal ids/metrics, caps suggestions and links optional questions', async () => {
  mount();
  await screen.findByRole('article');
  expect(screen.getByRole('tab', { name: /^看重什么 1/u })).toBeVisible();
  expect(screen.queryByText('internal')).not.toBeInTheDocument();
  expect(screen.queryByText('2.1')).not.toBeInTheDocument();
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  // What is known too little is said once, in a line, with one way to add to it.
  expect(
    screen.getByText(/^了解得还少：/).textContent?.split('、'),
  ).toHaveLength(5);
  expect(screen.getByRole('link', { name: '添加记忆' })).toBeVisible();
  expect(screen.queryByRole('link', { name: /^多写写你/ })).toBeNull();
  // The fixed questions are gone: 补一补 asks about what is least known, and only the person is asked.
  expect(screen.queryByRole('link', { name: '回答几个问题' })).toBeNull();
  expect(screen.queryByRole('button', { name: '补一补' })).toBeNull();
  await choose(article(), '依据');
  expect(article().getByText('我会先听听')).toBeInTheDocument();
});
it('removes a memory with X-Twin once saved, and keeps it when saving fails', async () => {
  mount();
  await screen.findByRole('article');
  await choose(article(), '删掉');
  await act(async () => resolveReview(json({ detail: '保存失败' }, 500)));
  expect(toast).toHaveBeenCalledWith('保存失败', 'danger');
  expect(screen.getByRole('article')).toBeVisible();
  await choose(article(), '删掉');
  const options = fetcher.mock.calls
    .filter(([url]) => String(url).endsWith('/review'))
    .at(-1)![1] as RequestInit;
  expect(new Headers(options.headers).get('X-Twin')).toBe('1');
  expect(JSON.parse(options.body as string).status).toBe('rejected');
  await complete('rejected');
  expect(toast).toHaveBeenCalledWith('删掉了，之后不会再用它', 'success');
  await waitFor(() =>
    expect(screen.queryByRole('article')).not.toBeInTheDocument(),
  );
});
it('edits inline, retains failed drafts, saves new wording, and can go back to the original', async () => {
  const user = userEvent.setup();
  mount();
  await screen.findByRole('article');
  await user.click(article().getByRole('button', { name: /^改这条/u }));
  const input = article().getByLabelText('修改表述');
  fireEvent.change(input, { target: { value: '先核对事实' } });
  await user.click(article().getByRole('button', { name: '保存修改' }));
  await act(async () => resolveReview(json({ detail: '失败' }, 500)));
  expect(input).toHaveValue('先核对事实');
  await user.click(article().getByRole('button', { name: '保存修改' }));
  await complete('edited', '先核对事实');
  expect(article().getByText('你改过')).toBeVisible();
  expect(article().queryByLabelText('修改表述')).not.toBeInTheDocument();
  await choose(article(), '依据');
  expect(article().getByText('原提炼：先听大家的意见')).toBeVisible();
  await choose(article(), '恢复原样');
  await complete('unreviewed');
  expect(article().queryByText('你改过')).toBeNull();
  expect(
    article().queryByRole('button', { name: '恢复原样' }),
  ).not.toBeInTheDocument();
});
it('aborts outstanding reads and reviews on unmount', async () => {
  const view = mount();
  await screen.findByRole('article');
  await choose(article(), '删掉');
  const options = fetcher.mock.calls.find(([url]) =>
    url.endsWith('/review'),
  )![1] as RequestInit;
  view.unmount();
  expect(options.signal?.aborted).toBe(true);
});

function dimensionItems(
  dimension: string,
  count: number,
  review: ProfileItem['review'] = 'unreviewed',
) {
  return Array.from({ length: count }, (_, index) => ({
    ...item,
    item_id: `${dimension}-${index}`,
    dimension_id: dimension,
    statement: `${dimension} 条目 ${index + 1}`,
    review,
  }));
}

it('lays out all ten aspects in three layers, counts non-rejected items, and opens the first known one', async () => {
  rows = [
    ...dimensionItems('D1', 2, 'confirmed'),
    ...dimensionItems('D2', 7),
    ...dimensionItems('D3', 1),
    ...dimensionItems('D9', 3, 'rejected'),
  ];
  mountOverview();
  const tab = await screen.findByRole('tab', { name: /^看重什么 7/u });
  expect(tab).toHaveAttribute('aria-selected', 'true');
  expect(
    screen
      .getAllByRole('tab')
      .map((row) => row.textContent?.replace(/[\s\d]+$/, '')),
  ).toEqual([
    '看重什么',
    '存在与意义',
    '怎么思考',
    '怎么做决定',
    '说话方式',
    '和人相处',
    '擅长什么',
    '经历与身份',
    '最近在关注',
    '生活与喜好',
  ]);
  expect(screen.getByRole('tab', { name: /^经历与身份 2/u })).toBeVisible();
  expect(screen.getByRole('tab', { name: /^怎么做决定 1/u })).toBeVisible();
  expect(screen.getByRole('tab', { name: /^生活与喜好/u })).toBeVisible();
  expect(
    screen.getByRole('img', { name: '十个方面里已了解 3 个' }),
  ).toBeVisible();
  // The count is on the 记忆 tab already: the overview does not say it again, nor how memories are used.
  expect(screen.queryByText(/条记忆/u)).toBeNull();
  expect(screen.getByRole('tablist', { name: '十个方面' })).toHaveClass(
    'overflow-x-auto',
  );
  const user = userEvent.setup();
  await user.click(screen.getByRole('tab', { name: /^生活与喜好/u }));
  const panel = screen.getByRole('tabpanel', { name: /^生活与喜好/u });
  expect(within(panel).getByText('还不了解这一面。')).toBeVisible();
  // One way to add to it, not two: the person has 补一补 beside the name, anyone else the line above.
  expect(within(panel).queryByRole('link')).toBeNull();
  expect(within(panel).queryByRole('article')).toBeNull();
});

it('keeps server order, shows five items, and resets expansion after switching tabs', async () => {
  rows = [...dimensionItems('D2', 7), ...dimensionItems('D1', 1, 'confirmed')];
  mountOverview();
  const user = userEvent.setup();
  await user.click(await screen.findByRole('tab', { name: /^看重什么 7/u }));
  await cards(5);
  expect(
    screen
      .getAllByRole('article')
      .map((card) => card.getAttribute('aria-label')),
  ).toEqual(rows.slice(0, 5).map((row) => row.statement));
  await user.click(await screen.findByRole('button', { name: '再看 2 条' }));
  expect(screen.getAllByRole('article')).toHaveLength(7);
  await user.click(screen.getByRole('button', { name: '收起' }));
  expect(screen.getAllByRole('article')).toHaveLength(5);
  await user.click(await screen.findByRole('button', { name: '再看 2 条' }));
  await user.click(screen.getByRole('tab', { name: /^经历与身份 1/u }));
  await cards(1);
  expect(screen.queryByRole('button', { name: /^再看 \d+ 条/ })).toBeNull();
  await user.click(screen.getByRole('tab', { name: /^看重什么 7/u }));
  await cards(5);
  expect(screen.getByRole('button', { name: '再看 2 条' })).toBeVisible();
});

it('finds memories by search, and corrects or removes them right in the results', async () => {
  rows = [
    ...dimensionItems('D2', 7),
    {
      ...item,
      item_id: 'overtime',
      dimension_id: 'D3',
      statement: '不鼓励加班',
      evidence: [{ ...item.evidence[0], quote: '到点就走' }],
    },
  ];
  mountOverview();
  const user = userEvent.setup();
  await screen.findByRole('tab', { name: /^看重什么 7/u });
  await user.type(screen.getByLabelText('搜索记忆'), '到点');
  const results = await screen.findByRole('region', { name: '搜索结果' });
  await waitFor(() =>
    expect(within(results).getAllByRole('article')).toHaveLength(1),
  );
  expect(screen.queryByRole('tablist')).toBeNull();
  const search = fetcher.mock.calls.find(([url]) => isItemSearchUrl(url))!;
  expect(search[0]).toBe('/api/persona/items/search?q=%E5%88%B0%E7%82%B9');
  expect(
    new Headers((search[1] as RequestInit).headers).get('X-Twin-Persona'),
  ).toBe('default');
  const card = within(within(results).getByRole('article'));
  await user.click(card.getByRole('button', { name: /^改这条/u }));
  fireEvent.change(card.getByLabelText('修改表述'), {
    target: { value: '加班要看情况' },
  });
  await user.click(card.getByRole('button', { name: '保存修改' }));
  await complete('edited', '加班要看情况', rows.at(-1));
  expect(
    within(results).getByRole('article', { name: '加班要看情况' }),
  ).toBeVisible();
  await choose(within(within(results).getByRole('article')), '删掉');
  await complete('rejected', '加班要看情况', rows.at(-1));
  await waitFor(() =>
    expect(within(results).queryByRole('article')).toBeNull(),
  );
  expect(within(results).getByText('没找到相关的记忆')).toBeVisible();
  await user.clear(screen.getByLabelText('搜索记忆'));
  expect(await screen.findByRole('tablist')).toBeVisible();
});

it('offers a look at memories whose evidence disagrees, without making it a chore', async () => {
  rows = [
    ...dimensionItems('D2', 3),
    { ...dimensionItems('D3', 1)[0], conflict: '说的和做的不一样' },
  ];
  mountOverview();
  const user = userEvent.setup();
  const toggle = await screen.findByRole('button', { name: '看矛盾 1 条' });
  expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await user.click(toggle);
  const list = await screen.findByRole('region', { name: '有矛盾的记忆' });
  await waitFor(() =>
    expect(within(list).getAllByRole('article')).toHaveLength(1),
  );
  expect(within(list).getByText('有矛盾')).toBeVisible();
  expect(
    fetcher.mock.calls.some(([url]) => String(url).includes('conflict=true')),
  ).toBe(true);
  await user.click(toggle);
  expect(await screen.findByRole('tablist')).toBeVisible();
});

it('preserves the selected tab and expansion through editing and removal', async () => {
  rows = [...dimensionItems('D1', 1), ...dimensionItems('D2', 7)];
  const target = rows[7];
  mountOverview();
  const user = userEvent.setup();
  const selected = await screen.findByRole('tab', { name: /^看重什么 7/u });
  await user.click(selected);
  await user.click(await screen.findByRole('button', { name: '再看 2 条' }));
  const card = within(screen.getByRole('article', { name: target.statement }));
  await user.click(card.getByRole('button', { name: /^改这条/u }));
  fireEvent.change(card.getByLabelText('修改表述'), {
    target: { value: '新的表述' },
  });
  await user.click(card.getByRole('button', { name: '保存修改' }));
  await complete('edited', '新的表述', target);
  expect(selected).toHaveAttribute('aria-selected', 'true');
  expect(screen.getAllByRole('article')).toHaveLength(7);
  expect(screen.getByRole('button', { name: '收起' })).toHaveAttribute(
    'aria-expanded',
    'true',
  );
  await choose(
    within(screen.getByRole('article', { name: '新的表述' })),
    '删掉',
  );
  await complete('rejected', target.statement, target);
  expect(selected).toHaveAttribute('aria-selected', 'true');
  await waitFor(() => expect(selected).toHaveTextContent('看重什么 6'));
  expect(screen.getAllByRole('article')).toHaveLength(6);
  expect(screen.getByRole('button', { name: '收起' })).toHaveAttribute(
    'aria-expanded',
    'true',
  );
});

it('resets the tab and expansion when switching twins', async () => {
  rows = [...dimensionItems('D1', 1), ...dimensionItems('D2', 7)];
  mountOverview();
  await screen.findByRole('tab', { name: /^看重什么 7/u });
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: '再看 2 条' }));
  expect(screen.getAllByRole('article')).toHaveLength(7);
  await user.click(screen.getByRole('tab', { name: /^经历与身份 1/u }));
  await cards(1);
  act(() => {
    setPersonaId('friend');
    usePersonas.setState({ id: 'friend' });
  });
  await waitFor(() =>
    expect(screen.getByRole('tab', { name: /^看重什么 7/u })).toHaveAttribute(
      'aria-selected',
      'true',
    ),
  );
  await cards(5);
  expect(screen.getByRole('button', { name: '再看 2 条' })).toBeVisible();
});

it('keeps the surest points in step with a correction', async () => {
  mountOverview();
  const user = userEvent.setup();
  const surest = await screen.findByRole('list', { name: '最有把握的几点' });
  expect(within(surest).getByText('先听大家的意见')).toBeVisible();
  // Cut to two lines when long, the whole of it is the hover.
  expect(within(surest).getByText('先听大家的意见')).toHaveAttribute(
    'title',
    '先听大家的意见',
  );
  const card = within(await screen.findByRole('article'));
  await user.click(card.getByRole('button', { name: /^改这条/u }));
  fireEvent.change(card.getByLabelText('修改表述'), {
    target: { value: '先听一圈再拍板' },
  });
  await user.click(card.getByRole('button', { name: '保存修改' }));
  await complete('edited', '先听一圈再拍板');
  expect(await within(surest).findByText('先听一圈再拍板')).toBeVisible();
  expect(within(surest).queryByText('先听大家的意见')).toBeNull();
});

it.each([
  [false, 'ArrowDown', 'vertical'],
  [true, 'ArrowRight', 'horizontal'],
])(
  'moves between aspects with the arrows that match the layout (phone: %s)',
  async (phone, key, orientation) => {
    vi.mocked(window.matchMedia).mockImplementation(
      (query: string) =>
        ({
          matches: phone && query === '(max-width: 767px)',
          media: query,
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
        }) as unknown as MediaQueryList,
    );
    rows = [...dimensionItems('D2', 2), ...dimensionItems('D10', 1)];
    mountOverview();
    const user = userEvent.setup();
    const first = await screen.findByRole('tab', { name: /^看重什么 2/u });
    expect(screen.getByRole('tablist', { name: '十个方面' })).toHaveAttribute(
      'aria-orientation',
      orientation,
    );
    first.focus();
    await user.keyboard(`{${key}}`);
    expect(screen.getByRole('tab', { name: /^存在与意义 1/u })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  },
);

it('shows how far a library update has gone in place of the refused profile, then loads it', async () => {
  let updating = true;
  const base = fetcher.getMockImplementation() as (
    url: string,
  ) => Promise<Response>;
  fetcher.mockImplementation((url: string) => {
    if (updating && (isItemSummaryUrl(url) || url === '/api/persona/coverage'))
      return Promise.resolve(
        json(
          {
            detail: '记忆更新中：录音的说话人归属刚有变化，整理完成后就能回答',
            code: 'memory_updating',
          },
          409,
        ),
      );
    if (url === '/api/persona/processing')
      return Promise.resolve(
        json({
          state: 'running',
          progress: { phase: 'extract', done: 77, total: 406 },
        }),
      );
    return base(url);
  });
  useStatus.setState({
    data: {
      target_name: '小林',
      counts: { sources: 1, items: 0 },
      memory_updating: true,
      llm: { provider: 'x', model: 'x' },
      embed: { provider: 'x' },
      egress: [],
    },
    error: null,
  });
  mountOverview();
  expect(
    await screen.findByRole('progressbar', { name: '第 1/3 步 · 读资料' }),
  ).toHaveAttribute('aria-valuenow', '77');
  expect(screen.getByText('19%')).toBeInTheDocument();
  // The refusal is what the bar explains: no error and nothing to retry.
  expect(
    screen.queryByRole('button', { name: '重试' }),
  ).not.toBeInTheDocument();
  updating = false;
  act(() =>
    useStatus.setState({
      data: { ...useStatus.getState().data!, memory_updating: false },
    }),
  );
  expect(
    await screen.findByRole('heading', { name: '我了解到的他' }),
  ).toBeInTheDocument();
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
});

it('names how well an aspect and its facets are known in four levels, with a tick on a checked third', async () => {
  rows = dimensionItems('D2', 3);
  const original = fetcher.getMockImplementation()! as (
    url: string,
  ) => Promise<Response>;
  fetcher.mockImplementation((url: string) =>
    url === '/api/persona/coverage'
      ? Promise.resolve(
          json({
            kind_labels: {},
            level_labels: { 1: '提到过', 2: '了解一些', 3: '了解较多' },
            checked_label: '回答经过检查',
            facets: [
              {
                facet_id: '2.1',
                dimension_id: 'D2',
                name: '核心价值',
                level: 3,
                checked: true,
              },
              { facet_id: '2.2', dimension_id: 'D2', name: '底线', level: 1 },
              {
                facet_id: '2.3',
                dimension_id: 'D2',
                name: '原则',
                level: 2,
              },
              {
                facet_id: '2.4',
                dimension_id: 'D2',
                name: '看人',
                level: 3,
              },
            ],
            suggestions: [],
          }),
        )
      : original(url),
  );
  mountOverview();
  const user = userEvent.setup();
  // How well the aspect is known shows once, as dots beside its name in the list (named for reading and for
  // hovering): the panel does not say it again.
  const tab = await screen.findByRole('tab', { name: /^看重什么 3/u });
  expect(within(tab).getByRole('img', { name: '了解一些' })).toHaveAttribute(
    'title',
    '了解一些',
  );
  await user.click(tab);
  const panel = await screen.findByRole('tabpanel', { name: /^看重什么 3/u });
  expect(
    await within(panel).findByRole('img', { name: '了解较多 ✓' }),
  ).toBeInTheDocument();
  expect(within(panel).queryByText(/了解一些|3 条/u)).toBeNull();
  expect(
    within(panel).getByRole('img', { name: '了解较多 ✓' }),
  ).toBeInTheDocument();
  expect(
    within(panel).getByRole('img', { name: '了解较多' }),
  ).toBeInTheDocument();
  expect(
    within(panel).getByRole('img', { name: '了解一些' }),
  ).toBeInTheDocument();
  expect(
    within(panel).getByRole('img', { name: '提到过' }),
  ).toBeInTheDocument();
  expect(screen.queryByText(/回答经过检查|已了解一些/u)).toBeNull();
});

const withTier = (
  response: (request: RequestInit) => Response | Promise<Response>,
) => {
  const original = fetcher.getMockImplementation()! as (
    url: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation((url: string, init?: RequestInit) =>
    url.endsWith('/tier')
      ? Promise.resolve(response(init ?? {}))
      : original(url, init),
  );
};

it('lets the person themselves say who may use a memory, and marks the ones only they may', async () => {
  useAuth.setState({
    identity: { email: null, admin: true, auth_enabled: false },
  });
  rows = [
    { ...item, item_id: 'a', statement: '孩子的事', tier: 'self' },
    { ...item, item_id: 'b', statement: '工作上的做法', tier: 'colleague' },
  ];
  withTier((init) => {
    const { tier } = JSON.parse(String(init.body)) as { tier: Tier };
    rows = rows.map((row) =>
      row.item_id === 'a' ? { ...row, tier, tier_changed: true } : row,
    );
    return json(rows[0]);
  });
  mountOverview();
  await cards(2);
  const card = (name: string) => within(screen.getByRole('article', { name }));
  expect(card('孩子的事').getByText('只有本人能用')).toBeVisible();
  expect(card('工作上的做法').queryByText('只有本人能用')).toBeNull();
  await choose(card('孩子的事'), '设为同事能用');
  await waitFor(() =>
    expect(card('孩子的事').queryByText('只有本人能用')).toBeNull(),
  );
  const put = fetcher.mock.calls.find(([url]) =>
    String(url).endsWith('/tier'),
  )!;
  expect(put[0]).toBe('/api/persona/items/a/tier');
  expect(put[1]).toMatchObject({
    method: 'PUT',
    body: JSON.stringify({ tier: 'colleague' }),
  });
  expect(toast).toHaveBeenCalledWith('之后同事问到时也会用它', 'success');
  // The other way round, the memory goes back to the person alone.
  await choose(card('工作上的做法'), '设为只有本人');
  await waitFor(() =>
    expect(toast).toHaveBeenCalledWith('之后只有你自己的对话会用它', 'success'),
  );
});

it('puts a memory back as it was when saving who may use it fails', async () => {
  useAuth.setState({
    identity: { email: null, admin: true, auth_enabled: false },
  });
  rows = [{ ...item, item_id: 'a', statement: '孩子的事', tier: 'self' }];
  withTier(() => json({ detail: '保存失败' }, 500));
  mountOverview();
  await cards(1);
  await choose(article(), '设为同事能用');
  await waitFor(() => expect(toast).toHaveBeenCalledWith('保存失败', 'danger'));
  expect(article().getByText('只有本人能用')).toBeVisible();
});

it('shows whoever only looks after a twin the colleague tier alone, with no say over it', async () => {
  // A manager is a colleague to the twin's person: the server sends only what colleagues may use.
  useAuth.setState({
    identity: { email: 'boss@example.test', admin: true, auth_enabled: true },
  });
  rows = [
    { ...item, item_id: 'b', statement: '工作上的做法', tier: 'colleague' },
  ];
  mountOverview();
  await cards(1);
  await userEvent.click(article().getByLabelText(/^更多：/u));
  expect(screen.getByRole('button', { name: '删掉' })).toBeVisible();
  expect(screen.queryByRole('button', { name: '设为只有本人' })).toBeNull();
  expect(screen.queryByRole('button', { name: '设为同事能用' })).toBeNull();
});

it('lets someone looking after a twin ask its person for more of an aspect, with a link that opens 补一补 there', async () => {
  useAuth.setState({
    identity: { email: 'boss@example.test', admin: true, auth_enabled: true },
  });
  showTwins([memberTwin({ claim: 'lin@example.test' })]);
  const copy = vi.spyOn(navigator.clipboard, 'writeText');
  render(
    <ConfirmProvider>
      <MemberAt />
    </ConfirmProvider>,
  );
  await screen.findByRole('article');
  await userEvent.click(screen.getByRole('button', { name: '请小林补充 ›' }));
  expect(copy).toHaveBeenCalledWith(
    expect.stringMatching(
      /小林，.*「看重什么」.*#\/team\/twin\/default\?fill=D2$/u,
    ),
  );
  expect(toast).toHaveBeenCalledWith('已复制，发给小林', 'success');
});

it('asks nobody to fill in a twin that is not made for a person, and not the person themself', async () => {
  useAuth.setState({
    identity: { email: 'boss@example.test', admin: true, auth_enabled: true },
  });
  showTwins([memberTwin()]);
  const view = render(
    <ConfirmProvider>
      <MemberAt />
    </ConfirmProvider>,
  );
  await screen.findByRole('article');
  expect(screen.queryByRole('button', { name: /补充 ›$/u })).toBeNull();
  view.unmount();
  useAuth.setState({
    identity: { email: 'lin@example.test', admin: false, auth_enabled: true },
  });
  showTwins([
    memberTwin({ claim: 'lin@example.test', mine: true, approved: true }),
  ]);
  render(
    <ConfirmProvider>
      <MemberAt />
    </ConfirmProvider>,
  );
  await screen.findByRole('article');
  expect(screen.queryByRole('button', { name: /补充 ›$/u })).toBeNull();
});

it('opens 补一补 on the aspect a colleague asked for, for the person', async () => {
  useAuth.setState({
    identity: { email: 'lin@example.test', admin: false, auth_enabled: true },
  });
  showTwins([
    memberTwin({ claim: 'lin@example.test', mine: true, approved: true }),
  ]);
  const base = fetcher.getMockImplementation() as (
    url: string,
  ) => Promise<Response>;
  fetcher.mockImplementation((url: string) => {
    if (url.startsWith('/api/persona/fill?'))
      return Promise.resolve(json({ questions: [] }));
    if (url.startsWith('/api/persona/handoffs'))
      return Promise.resolve(
        json({
          waiting: [],
          groups: [],
          often: [],
          answers: { total: 0, stale: 0 },
          guessed: [],
          sourced: [],
          sourced_count: 0,
          answered: 0,
          shelved: [],
          settled: [],
          pending: 0,
          days: 7,
        }),
      );
    return base(url);
  });
  render(
    <ConfirmProvider>
      <MemberAt path="/team/twin/default?fill=D3" />
    </ConfirmProvider>,
  );
  await screen.findByRole('dialog', { name: '补一补' });
  expect(
    fetcher.mock.calls.some(
      ([url]) => url === '/api/persona/fill?dimension=D3',
    ),
  ).toBe(true);
});

it('has one way to add to an empty profile: the person is offered 补一补, anyone else adding memories', async () => {
  rows = [];
  const view = mountOverview();
  expect(
    await screen.findByRole('heading', { name: '我了解到的他' }),
  ).toBeVisible();
  expect(screen.getByText('还不够了解他')).toBeVisible();
  expect(screen.getAllByRole('link', { name: '添加记忆' })).toHaveLength(1);
  expect(screen.queryByText(/^了解得还少/u)).toBeNull();
  view.unmount();
  useAuth.setState({
    identity: { email: null, admin: true, auth_enabled: false },
  });
  mountOverview();
  expect(
    await screen.findByRole('heading', { name: '我了解到的你' }),
  ).toBeVisible();
  expect(screen.getByText('还不够了解你')).toBeVisible();
  expect(screen.queryByRole('link', { name: '添加记忆' })).toBeNull();
  expect(screen.getByText(/^了解得还少/u)).toBeVisible();
  expect(screen.getAllByRole('button', { name: '补一补' })).toHaveLength(1);
});

it('asks nothing of the viewer where an aspect says who to ask, and the person has only 补一补 for an empty aspect', async () => {
  useAuth.setState({
    identity: { email: 'boss@example.test', admin: true, auth_enabled: true },
  });
  showTwins([memberTwin({ claim: 'lin@example.test' })]);
  const view = render(
    <ConfirmProvider>
      <MemberAt />
    </ConfirmProvider>,
  );
  await screen.findByRole('article');
  expect(screen.getByText(/^了解得还少/u)).toBeVisible();
  expect(screen.queryByRole('link', { name: '添加记忆' })).toBeNull();
  expect(screen.getByRole('button', { name: '请小林补充 ›' })).toBeVisible();
  view.unmount();
  useAuth.setState({
    identity: { email: null, admin: true, auth_enabled: false },
  });
  mountOverview();
  await userEvent.click(
    await screen.findByRole('tab', { name: /^生活与喜好/u }),
  );
  const panel = screen.getByRole('tabpanel', { name: /^生活与喜好/u });
  expect(within(panel).getByRole('button', { name: '补一补' })).toBeVisible();
  expect(within(panel).queryByRole('link')).toBeNull();
});

it('reads the profile again once the build after 补一补 is done', async () => {
  useAuth.setState({
    identity: { email: null, admin: true, auth_enabled: false },
  });
  const summaries = () =>
    fetcher.mock.calls.filter(([url]) => isItemSummaryUrl(String(url))).length;
  const base = fetcher.getMockImplementation() as (
    url: string,
  ) => Promise<Response>;
  fetcher.mockImplementation((url: string) => {
    if (url === '/api/persona/fill')
      return Promise.resolve(
        json({
          questions: [
            {
              id: 'q17',
              text: '最近有什么事占了你比较多的时间？',
              facet: '8.1',
              facet_name: '近期重点',
              level: 0,
              level_label: '还不了解',
            },
          ],
        }),
      );
    if (url === '/api/persona/fill/draft')
      return Promise.resolve(
        json({
          drafts: [
            {
              facet: '8.1',
              facet_name: '近期重点',
              statement: '在推检索改版',
              tier: 'colleague',
            },
          ],
          changes: [],
        }),
      );
    if (url === '/api/persona/fill/keep')
      return Promise.resolve(json({ saved: 1, changes: [] }));
    if (url === '/api/persona/processing')
      return Promise.resolve(json({ state: 'idle' }));
    return base(url);
  });
  mountOverview();
  const user = userEvent.setup();
  await user.click(
    (await screen.findAllByRole('button', { name: '补一补' }))[0],
  );
  const dialog = await screen.findByRole('dialog', { name: '补一补' });
  await user.type(
    await within(dialog).findByRole('textbox', { name: '你的回答' }),
    '在推检索改版',
  );
  await user.click(within(dialog).getByRole('button', { name: '整理' }));
  await user.click(
    await within(dialog).findByRole('button', { name: '存进记忆' }),
  );
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  // What was kept is only made into memories by the build that follows: nothing to read yet ...
  const before = summaries();
  expect(before).toBeGreaterThan(0);
  expect(
    fetcher.mock.calls.some(([url]) => url === '/api/persona/processing'),
  ).toBe(false);
  // ... until the page has seen it done.
  await waitFor(() => expect(summaries()).toBeGreaterThan(before), {
    timeout: 6000,
  });
  const polled = () =>
    fetcher.mock.calls.filter(([url]) => url === '/api/persona/processing')
      .length;
  expect(polled()).toBe(1);
}, 15000);

it('lets the person put a memory back to the default of its kind, and offers it only for one they changed', async () => {
  useAuth.setState({
    identity: { email: null, admin: true, auth_enabled: false },
  });
  rows = [
    {
      ...item,
      item_id: 'a',
      statement: '孩子的事',
      tier: 'colleague',
      tier_changed: true,
    },
    { ...item, item_id: 'b', statement: '工作上的做法', tier: 'colleague' },
  ];
  withTier(() => {
    rows = rows.map((row) =>
      row.item_id === 'a' ? { ...row, tier: 'self', tier_changed: false } : row,
    );
    return json(rows[0]);
  });
  mountOverview();
  await cards(2);
  const card = (name: string) => within(screen.getByRole('article', { name }));
  await userEvent.click(card('工作上的做法').getByLabelText(/^更多：/u));
  expect(
    card('工作上的做法').queryByRole('button', { name: '恢复默认' }),
  ).toBeNull();
  await userEvent.keyboard('{Escape}');
  await choose(card('孩子的事'), '恢复默认');
  const put = fetcher.mock.calls.find(([url]) =>
    String(url).endsWith('/tier'),
  )!;
  expect(put[1]).toMatchObject({
    method: 'PUT',
    body: JSON.stringify({ tier: null }),
  });
  await waitFor(() =>
    expect(toast).toHaveBeenCalledWith(
      '回到默认：只有你自己的对话会用它',
      'success',
    ),
  );
  expect(card('孩子的事').getByText('只有本人能用')).toBeVisible();
});

it('marks a memory only the person may use on the card the graph opens, and lets them say who may use it', async () => {
  const onTier = vi.fn(() => Promise.resolve(true));
  const view = render(
    <ItemCard
      item={{ ...item, tier: 'self', tier_changed: true }}
      pending={false}
      onReview={() => Promise.resolve(true)}
      onTier={onTier}
      kindLabels={{}}
    />,
  );
  expect(screen.getByText('只有本人能用')).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: '设为同事能用' }));
  expect(onTier).toHaveBeenLastCalledWith(expect.anything(), 'colleague');
  await userEvent.click(screen.getByRole('button', { name: '恢复默认' }));
  expect(onTier).toHaveBeenLastCalledWith(expect.anything(), null);
  view.unmount();
  // Anyone else cannot say, and sees nothing to say it with.
  render(
    <ItemCard
      item={{ ...item, tier: 'colleague' }}
      pending={false}
      onReview={() => Promise.resolve(true)}
      kindLabels={{}}
    />,
  );
  expect(screen.queryByRole('button', { name: /设为/u })).toBeNull();
});

it('takes the person from a memory whose two sides disagree into 照镜子 with the words of both, in the persona edition', async () => {
  useAuth.setState({
    identity: {
      email: null,
      admin: true,
      auth_enabled: false,
      features: { work: false },
      edition: 'persona',
    },
  });
  const said = {
    ...item,
    item_id: 'a',
    statement: '说要早睡',
    conflict: '常常凌晨还在写',
    evidence: [
      { ...item.evidence[0], quote: '我以后十一点就睡', date: '2026-03-02' },
      { ...item.evidence[0], expression_id: 'e2', quote: '又写到两点' },
    ],
  };
  rows = [said, { ...item, item_id: 'b', statement: '工作上的做法' }];
  let arrived: unknown = null;
  function ChatAt() {
    arrived = useLocation().state;
    return <p>对话</p>;
  }
  render(
    <MemoryRouter>
      <ConfirmProvider>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/chat" element={<ChatAt />} />
        </Routes>
      </ConfirmProvider>
    </MemoryRouter>,
  );
  await cards(2);
  const card = (name: string) => within(screen.getByRole('article', { name }));
  // Only a memory that disagrees is offered it.
  expect(
    card('工作上的做法').queryByRole('button', {
      name: '照镜子',
      hidden: true,
    }),
  ).toBeNull();
  await choose(card('说要早睡'), '照镜子');
  expect(await screen.findByText('对话')).toBeVisible();
  expect(arrived).toEqual({ ask: mirrorDraft(said), reflection: 'mirror' });
  expect(mirrorDraft(said).split('\n')).toEqual([
    '我想看看这两种说法：说要早睡',
    '不一致的地方：常常凌晨还在写',
    '原话：',
    '- 2026-03-02：我以后十一点就睡',
    '- 没有日期：又写到两点',
  ]);
});
