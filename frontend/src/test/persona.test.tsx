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
import { Sources } from '../pages/Sources';
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
let jobStatus: string;
let importFailure: boolean;
let reviewResponse: ((response: Response) => void) | undefined;
let deleteResponse: ((response: Response) => void) | undefined;
const buildResult = {
  sources: 1,
  chunks_extracted: 2,
  candidates: 3,
  items: 4,
  items_added: 2,
  items_changed: 1,
  items_removed: 3,
  facets_changed: 2,
  facet_diffs: {
    'D2.1': { added: 0, changed: 1, removed: 0 },
    'D1.1': { added: 2, changed: 0, removed: 3 },
    'D3.1': { added: 0, changed: 0, removed: 0 },
  },
};
beforeEach(() => {
  vi.mocked(useReducedMotion).mockReturnValue(true);
  vi.mocked(toast).mockClear();
  sessionStorage.clear();
  sourceRows = structuredClone([source]);
  itemRows = structuredClone([item]);
  stale = true;
  jobStatus = 'running';
  importFailure = false;
  reviewResponse = undefined;
  deleteResponse = undefined;
  fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (url === '/api/persona/sources') return json(sourceRows);
    if (url === '/api/persona/state') return json({ stale });
    if (url === '/api/jobs') return json([]);
    if (url === '/api/status')
      return json({
        counts: { sources: sourceRows.length, items: itemRows.length },
      });
    if (url.startsWith('/api/persona/import?'))
      return importFailure
        ? json({ detail: '没有可导入的文件：编码错误' }, 400)
        : json({
            imported: [{ ...source, new: true }],
            skipped: [{ file: 'bad.txt', reason: '编码错误' }],
          });
    if (url === '/api/persona/sources/s%2F1' && init.method === 'DELETE')
      return new Promise<Response>((resolve) => {
        deleteResponse = resolve;
      });
    if (url === '/api/persona/build') return json({ job_id: 'j/1' }, 202);
    if (url === '/api/jobs/j%2F1')
      return json({
        job_id: 'j/1',
        kind: 'persona_build',
        status: jobStatus,
        progress: ['[1/2] 抽取', '[2/2] 向量', 'call complete'],
        milestones: ['[2/2] 向量', '已合并 3 个细项'],
        result: buildResult,
        error: '模型调用失败',
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
      <MemoryRouter initialEntries={['/sources']}>
        <Sources />
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
  await screen.findByRole('article', { name: source.title });
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
it('imports multipart with kind/date, renders per-file imported/skipped reasons, and keeps labelled keyboard picker accessible', async () => {
  mountSources();
  await loadedSources();
  const user = userEvent.setup();
  await user.click(screen.getByRole('radio', { name: '转录文本' }));
  expect(screen.getByText(/有说话人的 TXT/)).toBeVisible();
  const input = screen.getByLabelText('文件（可多选）');
  expect(input).toHaveAttribute('multiple');
  expect(input).toHaveAttribute('accept', '.txt,.md,.srt,.vtt,.json');
  const click = vi.spyOn(input, 'click');
  const zone = screen.getByRole('button', { name: '选择或拖入文件（可多选）' });
  zone.focus();
  await user.keyboard('{Enter}');
  await user.keyboard(' ');
  expect(click).toHaveBeenCalledTimes(2);
  fireEvent.change(screen.getByLabelText('资料日期（可选）'), {
    target: { value: '2024-03-01' },
  });
  await user.upload(input, [
    new File(['test'], 'good.txt'),
    new File(['test'], 'bad.txt'),
  ]);
  await user.click(screen.getByRole('button', { name: '导入' }));
  expect(
    await screen.findByRole('list', { name: '导入结果' }),
  ).toHaveTextContent('已导入：访谈稿（本人 2 条）');
  expect(screen.getByRole('list', { name: '导入结果' })).toHaveTextContent(
    '未导入：bad.txt：编码错误',
  );
  const [url, init] = fetcher.mock.calls.find(([url]) =>
    url.startsWith('/api/persona/import?'),
  )! as [string, RequestInit];
  expect(url).toBe('/api/persona/import?kind=meeting&date=2024-03-01');
  expect(new Headers(init.headers).get('X-Twin')).toBe('1');
  expect(new Headers(init.headers).has('Content-Type')).toBe(false);
  expect((init.body as FormData).getAll('files')).toHaveLength(2);
  expect(toast).toHaveBeenCalledWith(
    '已导入或更新 1 份资料，跳过 1 份',
    'warning',
  );
  await waitFor(() =>
    expect(
      screen.queryByRole('list', { name: '待导入文件' }),
    ).not.toBeInTheDocument(),
  );
});
it('shows drag-over feedback, accepts multiple dropped files, and retains selection on import errors', async () => {
  mountSources();
  await loadedSources();
  const zone = screen.getByRole('button', { name: '选择或拖入文件（可多选）' });
  fireEvent.dragEnter(zone);
  expect(zone).toHaveTextContent('松开以选择文件');
  fireEvent.dragLeave(zone);
  expect(zone).toHaveTextContent('拖入文件');
  fireEvent.drop(zone, {
    dataTransfer: { files: [new File([''], 'a.txt'), new File([''], 'b.txt')] },
  });
  expect(
    screen.getByRole('list', { name: '待导入文件' }).children,
  ).toHaveLength(2);
  importFailure = true;
  fireEvent.click(screen.getByRole('button', { name: '导入' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('编码错误');
  expect(screen.getByRole('list', { name: '待导入文件' })).toBeInTheDocument();
});
it('renders remembered counts, facets, dates, declined notes and both unbuilt/no-items states', async () => {
  sourceRows.push(
    { ...source, source_id: 's2', title: '新资料', build_status: 'not_built' },
    {
      ...source,
      source_id: 's3',
      title: '空提炼',
      build_status: 'no_items',
      facets: [],
      items_supported: 0,
    },
  );
  mountSources();
  await loadedSources();
  const row = screen
    .getByRole('article', { name: '访谈稿' })
    .cloneNode(true) as HTMLElement;
  row.querySelectorAll('[aria-hidden="true"]').forEach((node) => node.remove());
  expect(row).toHaveTextContent('本人 / 全部：2 / 3');
  expect(row).toHaveTextContent(
    '原话 3 条（本人 2 / 他人 1） · 支撑档案 1 条 · 涉及：价值观',
  );
  expect(row).toHaveTextContent('2024-01-01 至 2024-02-01');
  expect(row).toHaveTextContent('未授权细项：D9.1');
  expect(screen.getByText(/尚未构建$/)).toBeVisible();
  expect(screen.getByText(/构建后未产生档案条目$/)).toBeVisible();
});
it('requires danger confirmation, optimistically deletes, rolls back errors and refreshes after success', async () => {
  mountSources();
  await loadedSources();
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: '删除 访谈稿' }));
  expect(screen.getByRole('button', { name: '取消' })).toHaveFocus();
  await user.click(screen.getByRole('button', { name: '取消' }));
  expect(deleteResponse).toBeUndefined();
  await user.click(screen.getByRole('button', { name: '删除 访谈稿' }));
  await user.click(screen.getByRole('button', { name: '确认删除' }));
  expect(
    screen.queryByRole('article', { name: source.title }),
  ).not.toBeInTheDocument();
  await act(async () => deleteResponse!(json({ detail: '删除失败' }, 500)));
  await loadedSources();
  expect(toast).toHaveBeenCalledWith('删除失败', 'danger');
  await user.click(screen.getByRole('button', { name: '删除 访谈稿' }));
  await user.click(screen.getByRole('button', { name: '确认删除' }));
  sourceRows = [];
  await act(async () => deleteResponse!(json({ deleted: true })));
  expect(await screen.findByText('还没有导入资料')).toBeVisible();
});
it('builds with progress/stage/logs, clears stale and shows sorted nonzero facet diffs', async () => {
  mountSources();
  await loadedSources();
  expect(screen.getByText(/资料有变化，尚未重新构建/)).toBeVisible();
  vi.useFakeTimers();
  await act(async () =>
    fireEvent.click(screen.getByRole('button', { name: '构建人格档案' })),
  );
  expect(screen.getByRole('progressbar', { name: '构建进度' })).toHaveAttribute(
    'aria-valuenow',
    '50',
  );
  expect(screen.getByText('第 2/2 步：向量')).toBeVisible();
  expect(screen.getByText('已合并 3 个细项')).toBeVisible();
  jobStatus = 'done';
  stale = false;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(
    screen.getByText('新增 2 条、修改 1 条、删除 3 条，涉及 2 个细项'),
  ).toBeVisible();
  expect(
    screen.getByText('D1.1：新增 2 条、修改 0 条、删除 3 条'),
  ).toBeVisible();
  expect(
    screen.getByText('D2.1：新增 0 条、修改 1 条、删除 0 条'),
  ).toBeVisible();
  expect(screen.queryByText(/D3.1：新增/)).not.toBeInTheDocument();
  expect(
    screen.queryByText(/资料有变化，尚未重新构建/),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole('link', { name: '查看档案与完成度' }),
  ).toHaveAttribute('href', '#/persona');
});
it('shows build failure hints and allows resubmission', async () => {
  jobStatus = 'failed';
  mountSources();
  await loadedSources();
  fireEvent.click(screen.getByRole('button', { name: '构建人格档案' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '已经完成的模型调用都保存在资料库里',
  );
  jobStatus = 'done';
  fireEvent.click(screen.getByRole('button', { name: '重试' }));
  expect(
    await screen.findByText('新增 2 条、修改 1 条、删除 3 条，涉及 2 个细项'),
  ).toBeVisible();
  expect(
    fetcher.mock.calls.filter(([url]) => url === '/api/persona/build'),
  ).toHaveLength(2);
});
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
it('aborts source loads/imports and profile reviews on unmount', async () => {
  const sources = mountSources();
  await loadedSources();
  const file = screen.getByLabelText('文件（可多选）');
  fireEvent.change(file, { target: { files: [new File(['test'], 'a.txt')] } });
  let signal: AbortSignal | null | undefined;
  const original = fetcher.getMockImplementation()! as (
    url: string,
    init: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation((url: string, init: RequestInit) => {
    if (url.startsWith('/api/persona/import?')) {
      signal = init.signal;
      return new Promise<Response>(() => {});
    }
    return original(url, init);
  });
  fireEvent.click(screen.getByRole('button', { name: '导入' }));
  sources.unmount();
  expect(signal?.aborted).toBe(true);
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
