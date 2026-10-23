import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Away } from '../features/away/Away';
import {
  AWAY_CHANGED,
  type Away as AwayData,
  type Handoff,
} from '../features/away/useAway';
import { setPersonaId } from '../lib/persona';
import { usePersonas } from '../stores/personas';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const handoff = (overrides: Partial<Handoff>): Handoff => ({
  id: 'h1',
  kind: 'decide',
  kind_label: '要你决定',
  status: 'delivered',
  status_label: '已送达',
  asker_name: '许清禾',
  question: '需求评审里那组接口，你倾向这次就改，还是下个版本再说？',
  context: '',
  ask: '',
  answer: '这个我先看看安排。',
  source_known: true,
  created_at: '2026-10-22T09:02:00+00:00',
  expires_at: '2026-10-25T09:02:00+00:00',
  days_left: 2,
  commit: null,
  reply: null,
  replied_at: null,
  ...overrides,
});
const data = (overrides: Partial<AwayData> = {}): AwayData => ({
  waiting: [],
  guessed: [],
  sourced: [],
  sourced_count: 0,
  answered: 0,
  shelved: [],
  settled: [],
  pending: 0,
  days: 7,
  ...overrides,
});

let away: AwayData;
let fetcher: ReturnType<typeof vi.fn>;
const posts = () =>
  fetcher.mock.calls
    .filter(([, init]) => init?.method === 'POST')
    .map(([url, init]) => [url, JSON.parse(String(init.body))]);

beforeEach(() => {
  setPersonaId('default');
  usePersonas.setState({ id: 'default', items: [] });
  away = data();
  fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/persona/handoffs') return json(away);
    if (init?.method === 'POST') return json({ handoff: {}, pending: 0 });
    return json({});
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => vi.unstubAllGlobals());

it('says nothing waits when nothing does, and stays quiet about the rest', async () => {
  render(<Away />);
  expect(await screen.findByText('没有等你决定的事。')).toBeVisible();
  expect(screen.getByText('仅你可见')).toBeVisible();
  expect(screen.queryByText(/分身推测/u)).toBeNull();
  expect(screen.queryByText(/有出处/u)).toBeNull();
});

it('opens the first question with the twin’s answer and a box for the person’s own words, and lists the others', async () => {
  const user = userEvent.setup();
  away = data({
    waiting: [
      handoff({}),
      handoff({
        id: 'h2',
        kind: 'evaluate',
        kind_label: '涉及评价',
        asker_name: '陈一',
        question: '你觉得新来的实习生能不能独立负责导入模块？',
      }),
    ],
    answered: 12,
    pending: 2,
  });
  render(<Away />);
  expect(await screen.findByText('等你决定 2')).toBeVisible();
  expect(screen.getByText('近 7 天 · 答了 12 问')).toBeVisible();
  const card = screen.getByRole('article', {
    name: /需求评审里那组接口/u,
  });
  expect(within(card).getByText('还剩 2 天', { exact: false })).toBeVisible();
  expect(within(card).getByText('分身的回答')).toBeVisible();
  const row = screen.getByRole('listitem', {
    name: '你觉得新来的实习生能不能独立负责导入模块？',
  });
  expect(row).toHaveTextContent('陈一');
  expect(row).toHaveTextContent('涉及评价');
  // Sending needs words; the reply goes to this handoff, and the page asks again afterwards.
  const changed = vi.fn();
  window.addEventListener(AWAY_CHANGED, changed);
  const send = within(card).getByRole('button', { name: '发送' });
  expect(send).toBeDisabled();
  await user.type(
    within(card).getByRole('textbox'),
    '这次先改，下版本补测试。',
  );
  await user.click(send);
  await waitFor(() =>
    expect(posts()).toContainEqual([
      '/api/persona/handoffs/h1/reply',
      { text: '这次先改，下版本补测试。' },
    ]),
  );
  await waitFor(() => expect(changed).toHaveBeenCalled());
  window.removeEventListener(AWAY_CHANGED, changed);
  // Another can be opened, and set aside from its “⋯”.
  await user.click(within(row).getByRole('button', { name: '回复' }));
  expect(
    await screen.findByRole('article', { name: /新来的实习生/u }),
  ).toBeVisible();
});

it('puts the twin’s draft in the box for the person to change, and sends nothing', async () => {
  const user = userEvent.setup();
  away = data({ waiting: [handoff({})], pending: 1 });
  fetcher.mockImplementation(async (url: string) => {
    if (url === '/api/persona/handoffs') return json(away);
    if (url === '/api/persona/handoffs/h1/draft')
      return json({ text: '这次先改。【请你定：测试补不补】' });
    return json({ handoff: {}, pending: 0 });
  });
  render(<Away />);
  const card = await screen.findByRole('article', {
    name: /需求评审里那组接口/u,
  });
  await user.click(within(card).getByRole('button', { name: '请分身起草' }));
  const box = within(card).getByRole('textbox');
  await waitFor(() =>
    expect(box).toHaveValue('这次先改。【请你定：测试补不补】'),
  );
  expect(
    fetcher.mock.calls.filter(([url]) => String(url).endsWith('/reply')),
  ).toHaveLength(0);
  expect(within(card).getByRole('button', { name: '发送' })).toBeEnabled();
});

it('puts a promise asked for beside the box: take it, move its date, or turn it down', async () => {
  const user = userEvent.setup();
  away = data({
    waiting: [
      handoff({
        id: 'h3',
        kind: 'commit',
        kind_label: '要你答应',
        asker_name: '沈从',
        question: '下周的发布你打算怎么安排？周五前给我一版方案。',
        commit: {
          entry_id: 'e3',
          what: '周五前给沈从一版发布方案',
          due: '2026-10-25',
          pending: true,
        },
      }),
    ],
    pending: 1,
  });
  render(<Away />);
  const card = await screen.findByRole('article', { name: /下周的发布/u });
  expect(within(card).getByText('待接承诺')).toBeVisible();
  expect(
    within(card).getByText('周五前给沈从一版发布方案（10月25日前）'),
  ).toBeVisible();
  await user.click(within(card).getByRole('button', { name: '接下' }));
  await waitFor(() =>
    expect(posts()).toContainEqual(['/api/persona/handoffs/h3/accept', {}]),
  );
  await user.click(within(card).getByRole('button', { name: '改时间' }));
  const date = within(card).getByLabelText('新的截止日期');
  await user.clear(date);
  await user.type(date, '2026-10-28');
  await user.click(within(card).getByRole('button', { name: '接下' }));
  await waitFor(() =>
    expect(posts()).toContainEqual([
      '/api/persona/handoffs/h3/accept',
      { due: '2026-10-28' },
    ]),
  );
  await user.click(within(card).getByRole('button', { name: '不接' }));
  await waitFor(() =>
    expect(posts()).toContainEqual(['/api/persona/handoffs/h3/decline', {}]),
  );
});

it('keeps a question from before handoffs as a memory only, and says its source is unknown', async () => {
  away = data({
    waiting: [
      handoff({
        id: 'legacy-1',
        kind: 'missing',
        kind_label: '无出处',
        asker_name: '',
        source_known: false,
        answer: null,
        question: '你几点睡？',
      }),
    ],
    pending: 1,
  });
  render(<Away />);
  const card = await screen.findByRole('article', { name: '你几点睡？' });
  expect(
    within(card).getByText('来源不明', { selector: 'span' }),
  ).toBeVisible();
  expect(within(card).getByRole('button', { name: '记下' })).toBeDisabled();
  expect(within(card).queryByRole('button', { name: '发送' })).toBeNull();
});

it('sets a question aside and puts it back from what was settled', async () => {
  const user = userEvent.setup();
  away = data({
    waiting: [
      handoff({}),
      handoff({
        id: 'h2',
        asker_name: '陈一',
        question: '这次发布要不要加测试环境？',
      }),
    ],
    shelved: [
      handoff({
        id: 'h9',
        status: 'dismissed',
        status_label: '不答',
        question: '午饭吃什么？',
        days_left: null,
      }),
    ],
    settled: [
      handoff({
        id: 'h8',
        status: 'replied',
        status_label: '已回复',
        question: '要不要开会？',
        replied_at: '2026-10-22T10:00:00+00:00',
        days_left: null,
      }),
    ],
    pending: 2,
  });
  render(<Away />);
  const row = await screen.findByRole('listitem', {
    name: '这次发布要不要加测试环境？',
  });
  await user.click(within(row).getByLabelText(/更多/u));
  await user.click(within(row).getByRole('button', { name: '不答' }));
  await waitFor(() =>
    expect(posts()).toContainEqual(['/api/persona/handoffs/h2/dismiss', {}]),
  );
  await user.click(screen.getByText('已处理 2'));
  const back = await screen.findByText(/午饭吃什么/u);
  const put = within(back.closest('li')!).getByRole('button', { name: '放回' });
  await user.click(put);
  await waitFor(() =>
    expect(posts()).toContainEqual(['/api/persona/handoffs/h9/restore', {}]),
  );
  // What was answered has nothing to put back.
  const done = screen.getByText(/要不要开会/u).closest('li')!;
  expect(within(done).queryByRole('button', { name: '放回' })).toBeNull();
  expect(done).toHaveTextContent('已回复');
});

it('shows the answers the twin guessed, to confirm or put right, and how many it answered from the profile', async () => {
  const user = userEvent.setup();
  const guess = {
    conversation_id: 'c1',
    turn: 2,
    asker_name: '沈从',
    question: '要是发布延期一周，你能接受吗？',
    answer: '能接受，但我会先把大文件导入拿出这次发布。',
    at: '2026-10-22T11:00:00+00:00',
  };
  away = data({
    guessed: [guess, { ...guess, conversation_id: 'c2', asker_name: '王屿' }],
    sourced: [{ ...guess, conversation_id: 'c3', asker_name: '陈一' }],
    sourced_count: 7,
  });
  render(<Away />);
  expect(await screen.findByText('分身推测 2')).toBeVisible();
  const [first, second] = screen.getAllByText('没错');
  await user.click(first);
  await waitFor(() =>
    expect(posts()).toContainEqual(['/api/persona/answers/c1/2/confirm', {}]),
  );
  // 更正 opens a box for what is right, and sends it.
  const item = second.closest('li')!;
  await user.click(within(item).getByLabelText(/更多/u));
  await user.click(within(item).getByRole('button', { name: '更正' }));
  await user.type(within(item).getByRole('textbox'), '最多三天。');
  await user.click(within(item).getByRole('button', { name: '发送更正' }));
  await waitFor(() =>
    expect(posts()).toContainEqual([
      '/api/persona/answers/c2/2/correct',
      { text: '最多三天。' },
    ]),
  );
  // What had a source is folded under its count.
  expect(screen.getByText('有出处 7')).toBeVisible();
});

it('says why it could not load and loads again on request', async () => {
  const user = userEvent.setup();
  fetcher.mockImplementationOnce(async () =>
    json({ detail: '团队库暂时读不了' }, 503),
  );
  render(<Away />);
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '团队库暂时读不了',
  );
  await user.click(screen.getByRole('button', { name: '重试加载' }));
  expect(await screen.findByText('没有等你决定的事。')).toBeVisible();
});
