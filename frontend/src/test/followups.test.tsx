import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { toast } from '../components/ui';
import { Followups, type Followup } from '../features/followups/Followups';

vi.mock('../components/ui', async (original) => ({
  ...(await original<typeof import('../components/ui')>()),
  toast: vi.fn(),
}));

const json = (data: unknown) => new Response(JSON.stringify(data));

function item(overrides: Partial<Followup>): Followup {
  return {
    followup_id: 'f1',
    question: '你怎么看远岚的报价？',
    previous: '',
    reason: '资料里没有',
    asked: 1,
    first_at: '2026-10-14T09:00:00',
    last_at: '2026-10-14T16:24:38',
    status: 'pending',
    handled_at: null,
    asked_since: 0,
    source_id: null,
    unresolved: false,
    ...overrides,
  };
}

let items: Followup[];
let fetcher: ReturnType<typeof vi.fn>;
const posts = () =>
  fetcher.mock.calls
    .filter(([, options]) => options?.method === 'POST')
    .map(([url, options]) => [url, JSON.parse(String(options.body))]);

beforeEach(() => {
  vi.mocked(toast).mockClear();
  items = [
    item({ asked: 3, previous: '上周经营会你在吗' }),
    item({ followup_id: 'f2', question: '你几点睡？', unresolved: true }),
    item({
      followup_id: 'f3',
      question: '你最喜欢的书？',
      status: 'answered',
      handled_at: '2026-10-13T10:00:00',
      source_id: 'src_1',
    }),
    item({
      followup_id: 'f4',
      question: '你家住哪？',
      status: 'dismissed',
      handled_at: '2026-10-13T10:00:00',
      asked_since: 2,
    }),
  ];
  fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (options?.method === 'POST') {
      const id = url.split('/')[4];
      const target = items.find((entry) => entry.followup_id === id)!;
      target.status = url.endsWith('/answer')
        ? 'answered'
        : (JSON.parse(String(options.body)) as { status: Followup['status'] })
            .status;
      return json({ followup: target });
    }
    return json({
      items: [...items],
      pending: items.filter((entry) => entry.status === 'pending').length,
    });
  });
  vi.stubGlobal('fetch', fetcher);
});

it('lists pending questions with what they followed and why the twin stopped', async () => {
  render(<Followups />);
  const price = await screen.findByRole('article', {
    name: '你怎么看远岚的报价？',
  });
  expect(price).toHaveTextContent('接着「上周经营会你在吗」问：');
  expect(price).toHaveTextContent('被问了 3 次，最近 10月14日 16:24');
  expect(price).toHaveTextContent('分身没回答的原因：资料里没有');
  expect(
    within(screen.getByRole('article', { name: '你几点睡？' })).getByText(
      '回答过，分身还是答不上，可以再补充',
    ),
  ).toBeInTheDocument();
  expect(screen.getByText('已回答 1 个')).toBeInTheDocument();
  expect(screen.getByText('之后又被问了 2 次')).toBeInTheDocument();
  expect(
    within(price).getByRole('button', { name: '记为我的回答' }),
  ).toBeDisabled();
});

it('keeps the answer in the person’s words and reloads the queue', async () => {
  const user = userEvent.setup();
  render(<Followups />);
  const price = await screen.findByRole('article', {
    name: '你怎么看远岚的报价？',
  });
  await user.type(
    within(price).getByRole('textbox', { name: '你的回答' }),
    '  报价只认实施费打包。 ',
  );
  await user.click(within(price).getByRole('button', { name: '记为我的回答' }));
  await waitFor(() =>
    expect(
      screen.queryByRole('article', { name: '你怎么看远岚的报价？' }),
    ).not.toBeInTheDocument(),
  );
  expect(posts()).toEqual([
    ['/api/persona/followups/f1/answer', { text: '报价只认实施费打包。' }],
  ]);
  expect(toast).toHaveBeenCalledWith('已记下，正在整理成记忆', 'success');
  expect(screen.getByText('已回答 2 个')).toBeInTheDocument();
});

it('sets a question aside and puts one back', async () => {
  const user = userEvent.setup();
  render(<Followups />);
  const sleep = await screen.findByRole('article', { name: '你几点睡？' });
  await user.click(within(sleep).getByRole('button', { name: '不用回答' }));
  await waitFor(() =>
    expect(
      screen.queryByRole('article', { name: '你几点睡？' }),
    ).not.toBeInTheDocument(),
  );
  await user.click(screen.getByText('不用回答 2 个'));
  const [first] = screen.getAllByRole('button', { name: '放回待回答' });
  await user.click(first);
  await waitFor(() => expect(posts()).toHaveLength(2));
  expect(posts()).toEqual([
    ['/api/persona/followups/f2/status', { status: 'dismissed' }],
    ['/api/persona/followups/f2/status', { status: 'pending' }],
  ]);
});

it('says so when nothing is waiting', async () => {
  items = [];
  render(<Followups />);
  expect(await screen.findByText('没有待回答的问题')).toBeInTheDocument();
});

it('quietly shows only waiting questions, and leaves once none is waiting', async () => {
  const user = userEvent.setup();
  const view = render(<Followups quiet />);
  expect(
    await screen.findByRole('heading', { name: '待你回答 2 个' }),
  ).toBeVisible();
  expect(screen.queryByText('已回答 1 个')).toBeNull();
  expect(screen.queryByText(/不用回答 \d 个/)).toBeNull();
  for (const name of ['你怎么看远岚的报价？', '你几点睡？']) {
    const question = await screen.findByRole('article', { name });
    await user.click(
      within(question).getByRole('button', { name: '不用回答' }),
    );
    await waitFor(() =>
      expect(screen.queryByRole('article', { name })).toBeNull(),
    );
  }
  await waitFor(() => expect(view.container).toBeEmptyDOMElement());
});
