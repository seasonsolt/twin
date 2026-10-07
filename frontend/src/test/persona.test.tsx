import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
import { beforeEach, expect, it, vi } from 'vitest';
import { Profile } from '../pages/Profile';
import { ConfirmProvider } from '../components/ui';
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
const mount = () =>
  render(
    <ConfirmProvider>
      <MemoryRouter initialEntries={['/profile']}>
        <Profile />
      </MemoryRouter>
    </ConfirmProvider>,
  );
const article = () => within(screen.getByRole('article'));
async function complete(
  status: ProfileItem['review'],
  statement = item.statement,
) {
  const updated = {
    ...item,
    review: status,
    statement,
    extracted_statement: status === 'edited' ? item.statement : '',
  };
  rows = [updated];
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
  expect(screen.getByRole('heading', { name: '看重什么' })).toBeVisible();
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
