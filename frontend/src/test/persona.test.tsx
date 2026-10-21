import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Overview } from '../features/profile/Overview';
import { setPersonaId } from '../lib/persona';
import { usePersonas } from '../stores/personas';
import { Profile } from '../pages/Profile';
import { ConfirmProvider, toast } from '../components/ui';

vi.mock('../components/ui', async (original) => ({
  ...(await original<typeof import('../components/ui')>()),
  toast: vi.fn(),
}));
import type { ProfileItem } from '../features/profile/types';
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
});
const mount = () =>
  render(
    <ConfirmProvider>
      <MemoryRouter initialEntries={['/profile']}>
        <Profile />
      </MemoryRouter>
    </ConfirmProvider>,
  );
const mountOverview = () =>
  render(
    <ConfirmProvider>
      <Overview />
    </ConfirmProvider>,
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
  expect(card('本人说过的').queryByText('只有别人的说法')).toBeNull();
  expect(card('改过的').getByText('你改过')).toBeVisible();
  expect(card('别人说的').getByText('只有别人的说法')).toBeVisible();
  // Nothing waits for a confirmation.
  expect(screen.queryByText(/待确认|已确认/)).toBeNull();
  expect(screen.queryByRole('button', { name: /^对$|全部确认/ })).toBeNull();
});

it('groups by plain topics, hides internal ids/metrics, caps suggestions and links optional questions', async () => {
  mount();
  await screen.findByRole('article');
  expect(screen.getByRole('tab', { name: '看重什么 1' })).toBeVisible();
  expect(screen.queryByText('internal')).not.toBeInTheDocument();
  expect(screen.queryByText('2.1')).not.toBeInTheDocument();
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  expect(screen.getAllByRole('link', { name: /^多写写你/ })).toHaveLength(5);
  expect(screen.getByRole('link', { name: '回答几个问题' })).toHaveAttribute(
    'href',
    '#/questionnaire',
  );
  fireEvent.click(article().getByRole('button', { name: '依据 · 展开' }));
  expect(article().getByText('我会先听听')).toBeInTheDocument();
});
it('removes a memory with X-Twin once saved, and keeps it when saving fails', async () => {
  const user = userEvent.setup();
  mount();
  await screen.findByRole('article');
  await user.click(article().getByRole('button', { name: '删掉' }));
  await act(async () => resolveReview(json({ detail: '保存失败' }, 500)));
  expect(toast).toHaveBeenCalledWith('保存失败', 'danger');
  expect(screen.getByRole('article')).toBeVisible();
  await user.click(article().getByRole('button', { name: '删掉' }));
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
  await user.click(article().getByRole('button', { name: '改一下' }));
  const input = article().getByLabelText('修改表述');
  fireEvent.change(input, { target: { value: '先核对事实' } });
  await user.click(article().getByRole('button', { name: '保存修改' }));
  await act(async () => resolveReview(json({ detail: '失败' }, 500)));
  expect(input).toHaveValue('先核对事实');
  await user.click(article().getByRole('button', { name: '保存修改' }));
  await complete('edited', '先核对事实');
  expect(article().getByText('你改过')).toBeVisible();
  expect(article().getByText('原提炼：先听大家的意见')).toBeVisible();
  expect(article().queryByLabelText('修改表述')).not.toBeInTheDocument();
  await user.click(article().getByRole('button', { name: '恢复原样' }));
  await complete('unreviewed');
  expect(article().queryByText('你改过')).toBeNull();
  expect(
    article().queryByRole('button', { name: '恢复原样' }),
  ).not.toBeInTheDocument();
});
it('aborts outstanding reads and reviews on unmount', async () => {
  const view = mount();
  await screen.findByRole('article');
  fireEvent.click(article().getByRole('button', { name: '删掉' }));
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

it('lays out all nine aspects in three layers, counts non-rejected items, and opens the first known one', async () => {
  rows = [
    ...dimensionItems('D1', 2, 'confirmed'),
    ...dimensionItems('D2', 7),
    ...dimensionItems('D3', 1),
    ...dimensionItems('D9', 3, 'rejected'),
  ];
  mountOverview();
  const tab = await screen.findByRole('tab', { name: '看重什么 7' });
  expect(tab).toHaveAttribute('aria-selected', 'true');
  expect(
    screen
      .getAllByRole('tab')
      .map((row) => row.textContent?.replace(/[\s\d]+$/, '')),
  ).toEqual([
    '看重什么',
    '怎么思考',
    '怎么做决定',
    '说话方式',
    '和人相处',
    '擅长什么',
    '经历与身份',
    '最近在关注',
    '生活与喜好',
  ]);
  expect(screen.getByRole('tab', { name: '经历与身份 2' })).toBeVisible();
  expect(screen.getByRole('tab', { name: '怎么做决定 1' })).toBeVisible();
  expect(screen.getByRole('tab', { name: '生活与喜好' })).toBeVisible();
  expect(
    screen.getByRole('img', { name: '九个方面里已了解 3 个' }),
  ).toBeVisible();
  expect(
    screen.getByText(
      '共 10 条记忆，回答时都会用到。哪条不对，在下面改掉或删掉。',
    ),
  ).toBeVisible();
  expect(screen.getByRole('tablist', { name: '九个方面' })).toHaveClass(
    'overflow-x-auto',
  );
  const user = userEvent.setup();
  await user.click(screen.getByRole('tab', { name: '生活与喜好' }));
  const panel = screen.getByRole('tabpanel', { name: '生活与喜好' });
  expect(within(panel).getByText('还不了解这一面。')).toBeVisible();
  expect(
    within(panel).getByRole('link', { name: '多写写你的生活与喜好' }),
  ).toBeVisible();
  expect(within(panel).queryByRole('article')).toBeNull();
});

it('keeps server order, shows five items, and resets expansion after switching tabs', async () => {
  rows = [...dimensionItems('D2', 7), ...dimensionItems('D1', 1, 'confirmed')];
  mountOverview();
  const user = userEvent.setup();
  await user.click(await screen.findByRole('tab', { name: '看重什么 7' }));
  await cards(5);
  expect(
    screen
      .getAllByRole('article')
      .map((card) => card.getAttribute('aria-label')),
  ).toEqual(rows.slice(0, 5).map((row) => row.statement));
  await user.click(
    await screen.findByRole('button', { name: '展开其余 2 条' }),
  );
  expect(screen.getAllByRole('article')).toHaveLength(7);
  await user.click(screen.getByRole('button', { name: '收起' }));
  expect(screen.getAllByRole('article')).toHaveLength(5);
  await user.click(
    await screen.findByRole('button', { name: '展开其余 2 条' }),
  );
  await user.click(screen.getByRole('tab', { name: '经历与身份 1' }));
  await cards(1);
  expect(screen.queryByRole('button', { name: /展开其余/ })).toBeNull();
  await user.click(screen.getByRole('tab', { name: '看重什么 7' }));
  await cards(5);
  expect(screen.getByRole('button', { name: '展开其余 2 条' })).toBeVisible();
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
  await screen.findByRole('tab', { name: '看重什么 7' });
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
  await user.click(card.getByRole('button', { name: '改一下' }));
  fireEvent.change(card.getByLabelText('修改表述'), {
    target: { value: '加班要看情况' },
  });
  await user.click(card.getByRole('button', { name: '保存修改' }));
  await complete('edited', '加班要看情况', rows.at(-1));
  expect(
    within(results).getByRole('article', { name: '加班要看情况' }),
  ).toBeVisible();
  await user.click(
    within(within(results).getByRole('article')).getByRole('button', {
      name: '删掉',
    }),
  );
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
  const toggle = await screen.findByRole('button', { name: '有矛盾的 1 条' });
  expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await user.click(toggle);
  const list = await screen.findByRole('region', { name: '有矛盾的记忆' });
  await waitFor(() =>
    expect(within(list).getAllByRole('article')).toHaveLength(1),
  );
  expect(within(list).getByText('矛盾：说的和做的不一样')).toBeVisible();
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
  const selected = await screen.findByRole('tab', { name: '看重什么 7' });
  await user.click(selected);
  await user.click(
    await screen.findByRole('button', { name: '展开其余 2 条' }),
  );
  const card = within(screen.getByRole('article', { name: target.statement }));
  await user.click(card.getByRole('button', { name: '改一下' }));
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
  await user.click(
    within(screen.getByRole('article', { name: '新的表述' })).getByRole(
      'button',
      { name: '删掉' },
    ),
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
  await screen.findByRole('tab', { name: '看重什么 7' });
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole('button', { name: '展开其余 2 条' }),
  );
  expect(screen.getAllByRole('article')).toHaveLength(7);
  await user.click(screen.getByRole('tab', { name: '经历与身份 1' }));
  await cards(1);
  act(() => {
    setPersonaId('friend');
    usePersonas.setState({ id: 'friend' });
  });
  await waitFor(() =>
    expect(screen.getByRole('tab', { name: '看重什么 7' })).toHaveAttribute(
      'aria-selected',
      'true',
    ),
  );
  await cards(5);
  expect(screen.getByRole('button', { name: '展开其余 2 条' })).toBeVisible();
});

it('keeps the surest points in step with a correction', async () => {
  mountOverview();
  const user = userEvent.setup();
  const surest = await screen.findByRole('list', { name: '最有把握的几点' });
  expect(within(surest).getByText('先听大家的意见')).toBeVisible();
  const card = within(await screen.findByRole('article'));
  await user.click(card.getByRole('button', { name: '改一下' }));
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
    rows = [...dimensionItems('D2', 2), ...dimensionItems('D4', 1)];
    mountOverview();
    const user = userEvent.setup();
    const first = await screen.findByRole('tab', { name: '看重什么 2' });
    expect(screen.getByRole('tablist', { name: '九个方面' })).toHaveAttribute(
      'aria-orientation',
      orientation,
    );
    first.focus();
    await user.keyboard(`{${key}}`);
    expect(screen.getByRole('tab', { name: '怎么思考 1' })).toHaveAttribute(
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
  expect(await screen.findByText(/共 1/u)).toBeInTheDocument();
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
});
