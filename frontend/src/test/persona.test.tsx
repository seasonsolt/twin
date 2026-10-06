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
import { useReducedMotion } from 'motion/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider, toast } from '../components/ui';
import { Memories } from '../pages/Memories';
import { Profile } from '../pages/Profile';
import type { Source } from '../features/sources/types';
import type { Coverage, ProfileItem } from '../features/profile/types';

vi.mock('../components/ui', async (original) => ({
  ...(await original<typeof import('../components/ui')>()),
  toast: vi.fn(),
}));
vi.mock('motion/react', async (original) => {
  const actual = await original<typeof import('motion/react')>();
  const { createElement } = await import('react');
  const cache = new Map();
  return {
    ...actual,
    useReducedMotion: vi.fn(),
    AnimatePresence: ({ children }: { children: import('react').ReactNode }) =>
      children,
    motion: new Proxy(
      {},
      {
        get: (_, tag: string) => {
          if (!cache.has(tag))
            cache.set(tag, (props: Record<string, unknown>) =>
              createElement(
                tag,
                Object.fromEntries(
                  Object.entries(props).filter(
                    ([key]) =>
                      key === 'style' || !actual.isValidMotionProp(key),
                  ),
                ),
              ),
            );
          return cache.get(tag);
        },
      },
    ),
  };
});
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status });
const source: Source = {
  source_id: 's/1',
  title: '访谈稿',
  kind: 'interview',
  kind_label: '访谈',
  evidence_class: 'self_report',
  n_target: 2,
  n_expressions: 3,
  expressions_total: 3,
  expressions_target: 2,
  expressions_others: 1,
  first_date: '2024-01-01',
  last_date: '2024-02-01',
  items_supported: 1,
  facets: [{ facet_id: 'D1.1', name: '价值观' }],
  declined_facets: ['D9.1'],
  build_status: 'remembered',
};
const item: ProfileItem = {
  item_id: 'i/1',
  dimension_id: 'D1',
  dimension_name: '核心',
  facet_id: 'D1.1',
  facet_name: '价值观',
  statement: '先听大家的意见',
  extracted_statement: '',
  applies_when: '团队讨论',
  conflict: '',
  occasions: 1,
  review: 'unreviewed',
  evidence: [
    {
      expression_id: 'e1',
      source_id: 's1',
      source_kind: 'interview',
      date: '2024-01-01',
      quote: '我会先听听',
      own_words: true,
    },
  ],
};
const coverage: Coverage = {
  taxonomy: 'test-taxonomy',
  as_of: '2025-01-01',
  level_labels: { 0: 'API未覆盖', 1: 'API有证据', 2: 'API充分', 3: 'API验证' },
  kind_labels: { interview: 'API访谈', chat: 'API聊天' },
  dimensions: [
    {
      dimension_id: 'D1',
      name: '核心',
      facets: 2,
      consented: 1,
      covered: 0.5,
      sufficient: 0.25,
      verified: 0,
      conflicts: 1,
    },
    {
      dimension_id: 'D9',
      name: '门控维度',
      facets: 1,
      consented: 0,
      covered: null,
      sufficient: null,
      verified: null,
      conflicts: 0,
    },
  ],
  facets: [
    {
      facet_id: 'D1.1',
      name: '价值观',
      dimension_id: 'D1',
      consented: true,
      level: 1,
      sufficiency: 0.5,
      confirmed: 0,
      asked: 2,
      abstained: 1,
      conflicts: 1,
      by_kind: { interview: 1 },
    },
    {
      facet_id: 'D9.1',
      name: '私密细项',
      dimension_id: 'D9',
      consented: false,
      level: 0,
      sufficiency: 0,
      confirmed: 0,
      asked: 0,
      abstained: 0,
      conflicts: 0,
      by_kind: {},
    },
  ],
  suggestions: [
    {
      facet_id: 'D1.1',
      name: '价值观',
      reason: '场合不足',
      sources: ['interview'],
    },
  ],
};
let fetcher: ReturnType<typeof vi.fn>;
let sourceRows: Source[];
let itemRows: ProfileItem[];
let stale: boolean;
let reviewResponse: ((response: Response) => void) | undefined;
beforeEach(() => {
  vi.mocked(useReducedMotion).mockReturnValue(true);
  vi.mocked(toast).mockClear();
  sessionStorage.clear();
  sourceRows = structuredClone([source]);
  itemRows = structuredClone([item]);
  stale = true;
  reviewResponse = undefined;
  fetcher = vi.fn(async (url: string) => {
    if (url === '/api/persona/sources')
      return json(
        sourceRows.map((row) => ({
          ...row,
          status: 'remembered',
          remembered: row.items_supported,
          detected_kind_label: row.kind_label,
        })),
      );
    if (url === '/api/persona/processing') return json({ state: 'idle' });
    if (url === '/api/persona/state') return json({ stale });
    if (url === '/api/jobs') return json([]);
    if (url === '/api/status')
      return json({
        counts: { sources: sourceRows.length, items: itemRows.length },
      });
    if (url.startsWith('/api/persona/coverage'))
      return json({
        ...coverage,
        as_of:
          new URL(url, 'http://localhost').searchParams.get('as_of') ||
          coverage.as_of,
      });
    if (url.startsWith('/api/persona/items?'))
      return json(
        itemRows.filter(
          (row) => url.endsWith('true') || row.review !== 'rejected',
        ),
      );
    if (url === '/api/persona/items/i%2F1/review')
      return new Promise<Response>((resolve) => {
        reviewResponse = resolve;
      });
    throw new Error(`Unexpected API: ${url}`);
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => vi.useRealTimers());
function mountSources() {
  return render(
    <ConfirmProvider>
      <MemoryRouter initialEntries={['/memories']}>
        <Memories />
      </MemoryRouter>
    </ConfirmProvider>,
  );
}
function mountProfile() {
  return render(
    <MemoryRouter initialEntries={['/persona']}>
      <Profile />
    </MemoryRouter>,
  );
}
async function loadedSources() {
  await screen.findByRole('heading', { name: source.title });
}
async function loadedProfile() {
  await screen.findByRole('article', { name: '档案条目 i/1' });
}
const article = () =>
  within(screen.getByRole('article', { name: '档案条目 i/1' }));
async function completeReview(
  status: ProfileItem['review'],
  statement = item.statement,
) {
  const updated = {
    ...item,
    review: status,
    statement,
    extracted_statement: status === 'edited' ? item.statement : '',
  };
  itemRows = [updated];
  await act(async () => reviewResponse!(json(updated)));
}
it('renders coverage metrics, API level labels, unconsented badges, matrix and suggestions', async () => {
  mountProfile();
  await loadedProfile();
  expect(screen.getByText('API有证据')).toBeVisible();
  expect(screen.queryByText('API未覆盖')).not.toBeInTheDocument();
  expect(screen.getByText('未授权')).toBeVisible();
  expect(
    screen.getByRole('progressbar', { name: '核心覆盖率' }),
  ).toHaveAttribute('aria-valuenow', '50');
  expect(
    screen.getByRole('progressbar', { name: '核心充分率' }),
  ).toHaveAttribute('aria-valuenow', '25');
  expect(
    screen.getByRole('progressbar', { name: '核心验证率' }),
  ).toHaveAttribute('aria-valuenow', '0');
  expect(screen.getByText(/建议来源：API访谈/)).toBeVisible();
  expect(screen.getByRole('list', { name: '细项完成度' })).toHaveTextContent(
    '被问 / 答不上 2 / 1',
  );
  expect(
    screen.getByRole('heading', { name: 'D1 核心', level: 3 }),
  ).toBeVisible();
});
it('confirms optimistically, rolls back failures, saves then undoes review and expands evidence with keyboard', async () => {
  mountProfile();
  await loadedProfile();
  const user = userEvent.setup();
  await user.click(article().getByRole('button', { name: '确认' }));
  expect(article().getByText('已确认')).toBeVisible();
  expect(article().getByRole('button', { name: '撤销审核' })).toBeDisabled();
  await act(async () => reviewResponse!(json({ detail: '保存审核失败' }, 500)));
  expect(article().getByText('未审核')).toBeVisible();
  expect(toast).toHaveBeenCalledWith('保存审核失败', 'danger');
  await user.click(article().getByRole('button', { name: '确认' }));
  await completeReview('confirmed');
  const init = fetcher.mock.calls.find(([url]) =>
    url.endsWith('/review'),
  )![1] as RequestInit;
  expect(JSON.parse(init.body as string)).toEqual({
    status: 'confirmed',
    statement: null,
    note: '',
  });
  expect(new Headers(init.headers).get('X-Twin')).toBe('1');
  await user.click(article().getByRole('button', { name: '撤销审核' }));
  await completeReview('unreviewed');
  const disclosure = article().getByRole('button', {
    name: '证据 1 处 · 展开',
  });
  disclosure.focus();
  await user.keyboard('{Enter}');
  expect(disclosure).toHaveAttribute('aria-expanded', 'true');
  expect(article().getByRole('list', { name: '条目证据' })).toHaveTextContent(
    '我会先听听',
  );
  expect(article().getByText('2024-01-01 · API访谈 · 原话')).toBeVisible();
  await user.keyboard(' ');
  expect(disclosure).toHaveAttribute('aria-expanded', 'false');
});
it('edits inline, keeps the draft and rolls back statement on error, then saves the new wording', async () => {
  mountProfile();
  await loadedProfile();
  const user = userEvent.setup();
  await user.click(article().getByRole('button', { name: '修改' }));
  const textarea = article().getByLabelText('修改表述');
  expect(textarea).toHaveFocus();
  expect(textarea).toHaveAttribute('maxlength', '1000');
  fireEvent.change(textarea, { target: { value: '先核对事实' } });
  await user.click(article().getByRole('button', { name: '保存修改' }));
  expect(article().getByText('先核对事实', { selector: 'p' })).toBeVisible();
  await act(async () => reviewResponse!(json({ detail: '修改失败' }, 500)));
  expect(article().getByText(item.statement)).toBeVisible();
  expect(textarea).toHaveValue('先核对事实');
  await user.click(article().getByRole('button', { name: '保存修改' }));
  await completeReview('edited', '先核对事实');
  expect(article().queryByLabelText('修改表述')).not.toBeInTheDocument();
  expect(article().getByText('已修改')).toBeVisible();
  expect(article().getByText(`原提炼：${item.statement}`)).toBeVisible();
});
it('rejects with rollback, removes rejected items by default and refetches them with the toggle', async () => {
  mountProfile();
  await loadedProfile();
  const user = userEvent.setup();
  await user.click(article().getByRole('button', { name: '驳回' }));
  expect(article().getByText('已否决')).toBeVisible();
  await act(async () => reviewResponse!(json({ detail: '驳回失败' }, 500)));
  expect(article().getByText('未审核')).toBeVisible();
  await user.click(article().getByRole('button', { name: '驳回' }));
  await completeReview('rejected');
  expect(
    screen.queryByRole('article', { name: '档案条目 i/1' }),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole('switch', { name: '包含已否决条目' }));
  await loadedProfile();
  expect(article().getByText('已否决')).toBeVisible();
  expect(
    fetcher.mock.calls.some(
      ([url]) => url === '/api/persona/items?include_rejected=true',
    ),
  ).toBe(true);
  await user.click(screen.getByRole('switch', { name: '包含已否决条目' }));
  await waitFor(() =>
    expect(
      screen.queryByRole('article', { name: '档案条目 i/1' }),
    ).not.toBeInTheDocument(),
  );
});
it('refetches coverage on as_of change and aborts superseded dates', async () => {
  mountProfile();
  await loadedProfile();
  const date = screen.getByLabelText('完成度参考日期（可选）');
  fireEvent.change(date, { target: { value: '2024-04-01' } });
  expect(
    await screen.findByText('维度体系 test-taxonomy，截至 2024-04-01。'),
  ).toBeVisible();
  expect(
    fetcher.mock.calls.some(
      ([url]) => url === '/api/persona/coverage?as_of=2024-04-01',
    ),
  ).toBe(true);
  const old = fetcher.mock.calls.find(
    ([url]) => url === '/api/persona/coverage',
  )![1] as RequestInit;
  expect(old.signal?.aborted).toBe(true);
  expect(screen.getByText(/不是历史快照/)).toBeVisible();
});
it('keeps the latest date and rejected toggle when a review finishes during refetches', async () => {
  const rejected = {
    ...item,
    item_id: 'rejected',
    review: 'rejected' as const,
  };
  itemRows.push(rejected);
  mountProfile();
  await loadedProfile();
  fireEvent.click(article().getByRole('button', { name: '确认' }));
  fireEvent.change(screen.getByLabelText('完成度参考日期（可选）'), {
    target: { value: '2023-01-01' },
  });
  fireEvent.click(screen.getByRole('switch', { name: '包含已否决条目' }));
  await screen.findByRole('article', { name: '档案条目 rejected' });
  const updated = { ...item, review: 'confirmed' as const };
  itemRows = [updated, rejected];
  await act(async () => reviewResponse!(json(updated)));
  await waitFor(() => expect(article().getByText('已确认')).toBeVisible());
  expect(
    screen.getByRole('article', { name: '档案条目 rejected' }),
  ).toBeInTheDocument();
  const coverageCalls = fetcher.mock.calls.filter(([url]) =>
    url.startsWith('/api/persona/coverage'),
  );
  expect(coverageCalls.at(-1)?.[0]).toBe(
    '/api/persona/coverage?as_of=2023-01-01',
  );
  const itemCalls = fetcher.mock.calls.filter(([url]) =>
    url.startsWith('/api/persona/items?'),
  );
  expect(itemCalls.at(-1)?.[0]).toBe(
    '/api/persona/items?include_rejected=true',
  );
});
it.each([300, 301])(
  'only virtualizes when more than 300 items (%i)',
  async (count) => {
    itemRows = Array.from({ length: count }, (_, i) => ({
      ...item,
      item_id: `bulk-${i}`,
    }));
    const { container } = mountProfile();
    await screen.findByRole('article', { name: '档案条目 bulk-0' });
    if (count === 300) {
      expect(
        screen.queryByLabelText('档案条目滚动区域'),
      ).not.toBeInTheDocument();
      expect(container.querySelectorAll('article')).toHaveLength(300);
    } else {
      const region = screen.getByLabelText('档案条目滚动区域');
      expect(container.querySelectorAll('article').length).toBeLessThan(20);
      expect(
        container.querySelector('li[aria-setsize="301"]'),
      ).toBeInTheDocument();
      fireEvent.scroll(region, { target: { scrollTop: 70_000 } });
      expect(
        screen.getByRole('article', { name: '档案条目 bulk-250' }),
      ).toBeInTheDocument();
    }
  },
);
it('aborts source loads and profile reviews on unmount', async () => {
  const sources = mountSources();
  await loadedSources();
  sources.unmount();
  const profile = mountProfile();
  await loadedProfile();
  fireEvent.click(article().getByRole('button', { name: '确认' }));
  const review = fetcher.mock.calls.find(([url]) =>
    url.endsWith('/review'),
  )![1] as RequestInit;
  profile.unmount();
  expect(review.signal?.aborted).toBe(true);
  const sourceLoad = fetcher.mock.calls.find(
    ([url]) => url === '/api/persona/sources',
  )![1] as RequestInit;
  expect(sourceLoad.signal?.aborted).toBe(true);
});
