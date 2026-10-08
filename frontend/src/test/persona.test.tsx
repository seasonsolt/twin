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
import { reviewLabels, type ProfileItem } from '../features/profile/types';
import { useStatus } from '../stores/status';

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
    if (url === '/api/persona/sources') return Promise.resolve(json([]));
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
    if (url.startsWith('/api/persona/items?'))
      return Promise.resolve(
        json(rows.filter((row) => row.review !== 'rejected')),
      );
    if (url.endsWith('/review') || url.endsWith('/review-batch'))
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

it('uses plain review status labels', () => {
  expect(reviewLabels).toEqual({
    unreviewed: '待确认',
    confirmed: '已确认',
    edited: '已修改',
    rejected: '已否定',
  });
});

it('groups by plain topics, hides internal ids/metrics, caps suggestions and links optional questions', async () => {
  mount();
  await screen.findByRole('article');
  expect(
    screen.getByRole('tab', { name: /看重什么 1\s*· 1 待确认/ }),
  ).toBeVisible();
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
it('confirms with X-Twin, rolls back errors, and can undo', async () => {
  const user = userEvent.setup();
  mount();
  await screen.findByRole('article');
  await user.click(article().getByRole('button', { name: '对' }));
  expect(article().getByText('已确认')).toBeVisible();
  await act(async () => resolveReview(json({ detail: '保存失败' }, 500)));
  expect(article().getByText('待确认')).toBeVisible();
  await user.click(article().getByRole('button', { name: '对' }));
  await complete('confirmed');
  const options = fetcher.mock.calls.find(([url]) =>
    url.endsWith('/review'),
  )![1] as RequestInit;
  expect(new Headers(options.headers).get('X-Twin')).toBe('1');
  expect(JSON.parse(options.body as string).status).toBe('confirmed');
  await user.click(article().getByRole('button', { name: '撤销审核' }));
  await complete('unreviewed');
  expect(article().getByText('待确认')).toBeVisible();
});
it('edits inline, retains failed drafts, and saves new wording', async () => {
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
  expect(article().getByText('已修改')).toBeVisible();
  expect(article().queryByLabelText('修改表述')).not.toBeInTheDocument();
});
it('rejects an item and removes it from About', async () => {
  mount();
  await screen.findByRole('article');
  fireEvent.click(article().getByRole('button', { name: '不对' }));
  await complete('rejected');
  expect(screen.queryByRole('article')).not.toBeInTheDocument();
});
it('aborts outstanding reads and reviews on unmount', async () => {
  const view = mount();
  await screen.findByRole('article');
  fireEvent.click(article().getByRole('button', { name: '对' }));
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

it('counts non-rejected items and defaults to the first dimension awaiting review', async () => {
  rows = [
    ...dimensionItems('D1', 2, 'confirmed'),
    ...dimensionItems('D2', 7),
    ...dimensionItems('D3', 1),
    ...dimensionItems('D9', 3, 'rejected'),
  ];
  mountOverview();
  const tab = await screen.findByRole('tab', {
    name: /看重什么 7\s*· 7 待确认/,
  });
  expect(tab).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByRole('tab', { name: '经历与身份 2' })).toBeVisible();
  expect(
    screen.getByRole('tab', { name: /怎么做决定 1\s*· 1 待确认/ }),
  ).toBeVisible();
  expect(screen.getAllByRole('tab')).toHaveLength(3);
  expect(screen.getByText('共 10 条，其中 8 条待你确认')).toBeVisible();
  expect(screen.getByRole('tablist')).toHaveClass('overflow-x-auto', 'w-full');
  expect(tab).toHaveClass('shrink-0', 'whitespace-nowrap');
});

it('defaults to the first populated dimension when everything is reviewed', async () => {
  rows = [
    ...dimensionItems('D2', 1, 'edited'),
    ...dimensionItems('D3', 1, 'confirmed'),
  ];
  mountOverview();
  expect(
    await screen.findByRole('tab', { name: '看重什么 1' }),
  ).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByText('共 2 条，其中 0 条待你确认')).toBeVisible();
});

it('keeps server order, shows five items, and resets expansion after switching tabs', async () => {
  rows = [...dimensionItems('D1', 1, 'confirmed'), ...dimensionItems('D2', 7)];
  rows[1].review = 'confirmed';
  mountOverview();
  await screen.findByRole('tab', { name: /看重什么 7\s*· 6 待确认/ });
  expect(
    screen
      .getAllByRole('article')
      .map((card) => card.getAttribute('aria-label')),
  ).toEqual(rows.slice(1, 6).map((row) => row.statement));
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: '展开其余 2 条' }));
  expect(screen.getAllByRole('article')).toHaveLength(7);
  await user.click(screen.getByRole('button', { name: '收起' }));
  expect(screen.getAllByRole('article')).toHaveLength(5);
  await user.click(screen.getByRole('button', { name: '展开其余 2 条' }));
  await user.click(screen.getByRole('tab', { name: '经历与身份 1' }));
  expect(screen.getAllByRole('article')).toHaveLength(1);
  expect(screen.queryByRole('button', { name: /展开其余/ })).toBeNull();
  await user.click(
    screen.getByRole('tab', { name: /看重什么 7\s*· 6 待确认/ }),
  );
  expect(screen.getAllByRole('article')).toHaveLength(5);
  expect(screen.getByRole('button', { name: '展开其余 2 条' })).toBeVisible();
});

it('confirms all unreviewed items in only the selected dimension, refreshes, and preserves expansion', async () => {
  rows = [
    ...dimensionItems('D1', 1, 'confirmed'),
    ...dimensionItems('D2', 7),
    ...dimensionItems('D2', 1, 'rejected').map((row) => ({
      ...row,
      item_id: 'rejected',
    })),
    ...dimensionItems('D3', 2),
  ];
  rows[1].review = 'confirmed';
  rows[2].review = 'edited';
  const selectedItems = rows.filter(
    (row) => row.dimension_id === 'D2' && row.review === 'unreviewed',
  );
  mountOverview();
  const selected = await screen.findByRole('tab', { name: /看重什么 7/ });
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: '展开其余 2 条' }));
  await user.click(screen.getByRole('button', { name: '全部确认（5）' }));
  let dialog = screen.getByRole('dialog', { name: '确认这 5 条？' });
  expect(dialog).toHaveTextContent(
    '确认后，分身回答时会优先依据它们。可以随时逐条撤销。',
  );
  await user.click(within(dialog).getByRole('button', { name: '取消' }));
  expect(
    fetcher.mock.calls.some(([url]) => url.endsWith('/review-batch')),
  ).toBe(false);
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  await user.click(screen.getByRole('button', { name: '全部确认（5）' }));
  dialog = screen.getByRole('dialog', { name: '确认这 5 条？' });
  await user.click(within(dialog).getByRole('button', { name: '全部确认' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(screen.getByRole('button', { name: '全部确认（5）' })).toBeDisabled();
  const options = fetcher.mock.calls.find(([url]) =>
    url.endsWith('/review-batch'),
  )![1] as RequestInit;
  expect(JSON.parse(options.body as string)).toEqual({
    item_ids: selectedItems.map((row) => row.item_id),
    status: 'confirmed',
  });
  expect(new Headers(options.headers).get('X-Twin-Persona')).toBe('default');
  expect(new Headers(options.headers).get('X-Twin')).toBe('1');
  const ids = new Set(selectedItems.map((row) => row.item_id));
  rows = rows.map((row) =>
    ids.has(row.item_id) ? { ...row, review: 'confirmed' } : row,
  );
  await act(async () => resolveReview(json({ updated: 5 })));
  await waitFor(() =>
    expect(screen.queryByRole('button', { name: /^全部确认/ })).toBeNull(),
  );
  expect(toast).toHaveBeenCalledWith('已确认 5 条', 'success');
  expect(
    fetcher.mock.calls.filter(([url]) => url.startsWith('/api/persona/items?')),
  ).toHaveLength(2);
  expect(
    fetcher.mock.calls.filter(([url]) => url === '/api/persona/coverage'),
  ).toHaveLength(2);
  expect(fetcher.mock.calls.some(([url]) => url === '/api/status')).toBe(true);
  expect(selected).toHaveAttribute('aria-selected', 'true');
  expect(screen.getAllByRole('article')).toHaveLength(7);
  expect(screen.getByRole('button', { name: '收起' })).toHaveAttribute(
    'aria-expanded',
    'true',
  );
  await user.click(screen.getByRole('tab', { name: '经历与身份 1' }));
  expect(screen.queryByRole('button', { name: /^全部确认/ })).toBeNull();
  await user.click(screen.getByRole('tab', { name: /怎么做决定 2/ }));
  expect(screen.getByRole('button', { name: '全部确认（2）' })).toBeVisible();
});

it('reports batch failures without changing the current tab or expanded items', async () => {
  rows = dimensionItems('D2', 7);
  mountOverview();
  const selected = await screen.findByRole('tab', { name: /看重什么 7/ });
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: '展开其余 2 条' }));
  await user.click(screen.getByRole('button', { name: '全部确认（7）' }));
  await user.click(
    within(screen.getByRole('dialog')).getByRole('button', {
      name: '全部确认',
    }),
  );
  await act(async () => resolveReview(json({ detail: '批量确认失败' }, 500)));
  expect(toast).toHaveBeenCalledWith('批量确认失败', 'danger');
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(screen.getByRole('button', { name: '全部确认（7）' })).toBeEnabled();
  expect(selected).toHaveAttribute('aria-selected', 'true');
  expect(screen.getAllByRole('article')).toHaveLength(7);
  expect(screen.getByRole('button', { name: '收起' })).toHaveAttribute(
    'aria-expanded',
    'true',
  );
  expect(
    fetcher.mock.calls.filter(([url]) => url.startsWith('/api/persona/items?')),
  ).toHaveLength(1);
});

it('aborts batch confirmation when switching twins', async () => {
  rows = dimensionItems('D2', 7);
  mountOverview();
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole('button', { name: '全部确认（7）' }),
  );
  await user.click(
    within(screen.getByRole('dialog')).getByRole('button', {
      name: '全部确认',
    }),
  );
  const options = fetcher.mock.calls.find(([url]) =>
    url.endsWith('/review-batch'),
  )![1] as RequestInit;
  act(() => {
    setPersonaId('friend');
    usePersonas.setState({ id: 'friend' });
  });
  expect(options.signal?.aborted).toBe(true);
  await act(async () => resolveReview(json({ updated: 7 })));
  expect(toast).not.toHaveBeenCalledWith('已确认 7 条', 'success');
  expect(
    await screen.findByRole('button', { name: '全部确认（7）' }),
  ).toBeEnabled();
});

it('preserves the selected tab and expansion through confirmation, editing, and rejection', async () => {
  rows = [...dimensionItems('D2', 7, 'confirmed'), ...dimensionItems('D3', 1)];
  rows[6].review = 'unreviewed';
  const target = rows[6];
  mountOverview();
  const selected = await screen.findByRole('tab', {
    name: /看重什么 7\s*· 1 待确认/,
  });
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: '展开其余 2 条' }));
  await user.click(
    within(screen.getByRole('article', { name: target.statement })).getByRole(
      'button',
      { name: '对' },
    ),
  );
  await complete('confirmed', target.statement, target);
  expect(selected).toHaveAttribute('aria-selected', 'true');
  expect(screen.getAllByRole('article')).toHaveLength(7);
  expect(screen.getByRole('button', { name: '收起' })).toHaveAttribute(
    'aria-expanded',
    'true',
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
  await user.click(
    within(screen.getByRole('article', { name: '新的表述' })).getByRole(
      'button',
      { name: '不对' },
    ),
  );
  await complete('rejected', target.statement, target);
  expect(selected).toHaveAttribute('aria-selected', 'true');
  expect(selected).toHaveTextContent('看重什么 6');
  expect(screen.getAllByRole('article')).toHaveLength(6);
  expect(screen.getByRole('button', { name: '收起' })).toHaveAttribute(
    'aria-expanded',
    'true',
  );
});

it('resets the tab and expansion when switching twins', async () => {
  rows = [...dimensionItems('D1', 1), ...dimensionItems('D2', 7)];
  mountOverview();
  await screen.findByRole('tab', { name: /经历与身份 1\s*· 1 待确认/ });
  const user = userEvent.setup();
  await user.click(
    screen.getByRole('tab', { name: /看重什么 7\s*· 7 待确认/ }),
  );
  await user.click(screen.getByRole('button', { name: '展开其余 2 条' }));
  expect(screen.getAllByRole('article')).toHaveLength(7);
  act(() => {
    setPersonaId('friend');
    usePersonas.setState({ id: 'friend' });
  });
  await waitFor(() =>
    expect(
      screen.getByRole('tab', { name: /经历与身份 1\s*· 1 待确认/ }),
    ).toHaveAttribute('aria-selected', 'true'),
  );
  await user.click(
    screen.getByRole('tab', { name: /看重什么 7\s*· 7 待确认/ }),
  );
  expect(screen.getAllByRole('article')).toHaveLength(5);
  expect(screen.getByRole('button', { name: '展开其余 2 条' })).toBeVisible();
});
