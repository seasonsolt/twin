import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ToastViewport, TooltipProvider } from '../components/ui';
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
  groups: [],
  often: [],
  answers: { total: 0, stale: 0 },
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
  expect(await screen.findByText('等你决定')).toBeVisible();
  expect(screen.getByText('近 7 天 · 答了 12 问')).toBeVisible();
  const card = screen.getByRole('article', {
    name: /需求评审里那组接口/u,
  });
  expect(within(card).getByText('还剩 2 天', { exact: false })).toBeVisible();
  // The first is opened with what the twin said; the others are folded until they are opened.
  expect(within(card).getByText('分身的回答')).toBeVisible();
  expect(within(card).getByText('这个我先看看安排。')).toBeVisible();
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
      { text: '这次先改，下版本补测试。', tier: 'colleague' },
    ]),
  );
  await waitFor(() => expect(changed).toHaveBeenCalled());
  window.removeEventListener(AWAY_CHANGED, changed);
  // Another can be opened, and set aside from its “⋯”.
  await user.click(within(row).getByRole('button', { name: '回复' }));
  const second = await screen.findByRole('article', { name: /新来的实习生/u });
  expect(second).toBeVisible();
  expect(within(second).getByText('这个我先看看安排。')).not.toBeVisible();
});

it('lets the person choose who may use a reply as a memory when they send it', async () => {
  const user = userEvent.setup();
  away = data({ waiting: [handoff({})], pending: 1 });
  render(<Away />);
  const card = await screen.findByRole('article', {
    name: /需求评审里那组接口/u,
  });
  const choice = within(card).getByRole('radiogroup', {
    name: '谁能用这条记忆',
  });
  // Colleagues may use it unless the person says otherwise.
  expect(within(choice).getByRole('radio', { name: '按默认' })).toBeChecked();
  expect(
    within(choice)
      .getAllByRole('radio')
      .map((radio) => radio.textContent),
  ).toEqual(['按默认', '只有我', '不存']);
  await user.click(within(choice).getByRole('radio', { name: '只有我' }));
  await user.type(within(card).getByRole('textbox'), '这是我自己的看法。');
  await user.click(within(card).getByRole('button', { name: '发送' }));
  await waitFor(() =>
    expect(posts()).toContainEqual([
      '/api/persona/handoffs/h1/reply',
      { text: '这是我自己的看法。', tier: 'self' },
    ]),
  );
});

it('sends a reply that is not kept to the asker only', async () => {
  const user = userEvent.setup();
  away = data({ waiting: [handoff({})], pending: 1 });
  render(<Away />);
  const card = await screen.findByRole('article', {
    name: /需求评审里那组接口/u,
  });
  await user.click(within(card).getByRole('radio', { name: '不存' }));
  await user.type(within(card).getByRole('textbox'), '先不改。');
  await user.click(within(card).getByRole('button', { name: '发送' }));
  await waitFor(() =>
    expect(posts()).toContainEqual([
      '/api/persona/handoffs/h1/reply',
      { text: '先不改。', tier: 'none' },
    ]),
  );
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

const mountAway = () =>
  render(
    <TooltipProvider>
      <MemoryRouter>
        <Away />
      </MemoryRouter>
    </TooltipProvider>,
  );

const asked = (
  id: string,
  asker: string,
  question: string,
  mode: Handoff['twin_mode'] = 'abstain',
) =>
  handoff({
    id,
    asker_name: asker,
    question,
    twin_mode: mode,
    created_at: `2026-10-22T${id === 'a' ? '01:12' : id === 'b' ? '02:05' : '03:30'}:00+00:00`,
  });
const same = [
  asked('a', '许清禾', '旧版 Word 模板导出，这次之后还支持吗？'),
  asked('b', '陈一', '客户问旧模板还能不能导出，我该怎么回？'),
  asked('c', '王屿', '销售那边听说旧模板要停用了，是真的吗？', 'grounded'),
];

it('puts the questions that ask the same thing on one card, with what each asked and what the twin did', async () => {
  away = data({
    waiting: [
      ...same,
      handoff({
        id: 'z',
        asker_name: '周宁',
        question: '周报按项目写还是按人写？',
      }),
    ],
    groups: [['a', 'b', 'c']],
    pending: 4,
  });
  mountAway();
  const card = await screen.findByRole('article', { name: '同一件事' });
  expect(within(card).getByText('3 人问同一件事')).toBeVisible();
  // The server keeps UTC, the page shows the reader's own clock (Shanghai in the tests).
  expect(within(card).getByText('最早 09:12')).toBeVisible();
  expect(within(card).getByText(/客户问旧模板还能不能导出/u)).toBeVisible();
  expect(within(card).getByText('09:12 · 未答')).toBeVisible();
  expect(within(card).getByText('11:30 · 答了一半')).toBeVisible();
  // The fourth is its own row, and the heading still counts all four.
  expect(screen.getByText('等你决定')).toBeVisible();
  expect(
    screen.getByRole('listitem', { name: '周报按项目写还是按人写？' }),
  ).toBeVisible();
});

it('answers them all at once, into each one’s own conversation, and can make the answer the team’s in the same step', async () => {
  const user = userEvent.setup();
  away = data({ waiting: same, groups: [['a', 'b', 'c']], pending: 3 });
  fetcher.mockImplementation(async (url: string) => {
    if (url === '/api/persona/handoffs') return json(away);
    return json({
      done: ['a', 'b', 'c'],
      failed: [],
      team_answer: null,
      pending: 0,
    });
  });
  mountAway();
  const card = await screen.findByRole('article', { name: '同一件事' });
  const send = within(card).getByRole('button', { name: '回复 3 人' });
  expect(send).toBeDisabled();
  await user.type(
    within(card).getByRole('textbox', { name: '以本人回复 3 人' }),
    '支持到 12 月底。',
  );
  // The title is the first question, summed up, and can be changed.
  await user.click(within(card).getByRole('button', { name: '改问法' }));
  const title = within(card).getByRole('textbox', { name: '归纳的问法' });
  await user.clear(title);
  await user.type(title, '旧模板还支持吗？{Enter}');
  await user.click(
    within(card).getByRole('checkbox', { name: '同时设为团队答案' }),
  );
  await user.click(within(card).getByText('预览'));
  const preview = within(card).getByRole('article', { name: '团队答案' });
  expect(within(preview).getByText('旧模板还支持吗？')).toBeVisible();
  expect(within(preview).getByText('支持到 12 月底。')).toBeVisible();
  await user.click(send);
  await waitFor(() =>
    expect(posts()).toContainEqual([
      '/api/persona/handoffs/reply-many',
      {
        ids: ['a', 'b', 'c'],
        text: '支持到 12 月底。',
        tier: 'colleague',
        team_answer: { title: '旧模板还支持吗？', body: '支持到 12 月底。' },
      },
    ]),
  );
});

it('titles the card with the earliest question, then with the matter summed up by the draft for them all', async () => {
  const user = userEvent.setup();
  // The group as it may come: not in the order they were asked.
  away = data({ waiting: same, groups: [['c', 'a', 'b']], pending: 3 });
  let summed = '旧版 Word 模板这次之后还能导出吗？';
  fetcher.mockImplementation(async (url: string) => {
    if (url === '/api/persona/handoffs') return json(away);
    if (url === '/api/persona/handoffs/a/draft')
      return json({ text: '支持到 12 月底。', question: summed });
    throw new Error(url);
  });
  mountAway();
  const card = await screen.findByRole('article', { name: '同一件事' });
  expect(
    within(card).getByText('旧版 Word 模板导出，这次之后还支持吗？', {
      selector: 'p',
    }),
  ).toBeVisible();
  await user.click(within(card).getByRole('button', { name: '请分身起草' }));
  // One draft for all three, from the first asked, with the others along.
  await waitFor(() =>
    expect(posts()).toEqual([
      ['/api/persona/handoffs/a/draft', { also: ['b', 'c'] }],
    ]),
  );
  expect(await within(card).findByText(summed)).toBeVisible();
  expect(
    within(card).getByRole('textbox', { name: '以本人回复 3 人' }),
  ).toHaveValue('支持到 12 月底。');
  // A title the person wrote stays theirs when they draft again.
  await user.click(within(card).getByRole('button', { name: '改问法' }));
  const title = within(card).getByRole('textbox', { name: '归纳的问法' });
  await user.clear(title);
  await user.type(title, '旧模板还支持吗？{Enter}');
  summed = '别的问法';
  await user.click(within(card).getByRole('button', { name: '请分身起草' }));
  await waitFor(() => expect(posts()).toHaveLength(2));
  expect(within(card).getByText('旧模板还支持吗？')).toBeVisible();
  expect(within(card).queryByText('别的问法')).toBeNull();
});

it('answers them all in the tier chosen, and a team answer is always for colleagues', async () => {
  const user = userEvent.setup();
  away = data({ waiting: same, groups: [['a', 'b', 'c']], pending: 3 });
  mountAway();
  const card = await screen.findByRole('article', { name: '同一件事' });
  await user.type(
    within(card).getByRole('textbox', { name: '以本人回复 3 人' }),
    '先不动。',
  );
  await user.click(within(card).getByRole('radio', { name: '只有我' }));
  await user.click(within(card).getByRole('button', { name: '回复 3 人' }));
  await waitFor(() =>
    expect(posts()).toContainEqual([
      '/api/persona/handoffs/reply-many',
      { ids: ['a', 'b', 'c'], text: '先不动。', tier: 'self' },
    ]),
  );
  // Making it the team's takes the choice away: everyone may use what everyone is shown.
  await user.click(
    within(card).getByRole('checkbox', { name: '同时设为团队答案' }),
  );
  expect(within(card).getByRole('radio', { name: '按默认' })).toBeChecked();
  expect(within(card).getByRole('radio', { name: '只有我' })).toBeDisabled();
});

it('takes them apart when they were not one matter, each as its own row to answer', async () => {
  const user = userEvent.setup();
  away = data({ waiting: same, groups: [['a', 'b', 'c']], pending: 3 });
  mountAway();
  const card = await screen.findByRole('article', { name: '同一件事' });
  await user.click(within(card).getByRole('button', { name: '拆开分别回' }));
  expect(screen.queryByRole('article', { name: '同一件事' })).toBeNull();
  expect(
    screen.getByRole('article', { name: /旧版 Word 模板导出/u }),
  ).toBeVisible();
  expect(
    screen.getByRole('listitem', { name: /客户问旧模板还能不能导出/u }),
  ).toBeVisible();
  expect(screen.getByText('等你决定')).toBeVisible();
});

it('still reloads when some of a group could not be answered, for the page to show what is left', async () => {
  const user = userEvent.setup();
  away = data({ waiting: same, groups: [['a', 'b', 'c']], pending: 3 });
  fetcher.mockImplementation(async (url: string) =>
    url === '/api/persona/handoffs'
      ? json(away)
      : json({
          done: ['a', 'c'],
          failed: [{ id: 'b', detail: '提问的人已经删掉了这段对话，不用回了' }],
          pending: 0,
        }),
  );
  mountAway();
  const card = await screen.findByRole('article', { name: '同一件事' });
  await user.type(
    within(card).getByRole('textbox', { name: '以本人回复 3 人' }),
    '好。',
  );
  await user.click(within(card).getByRole('button', { name: '回复 3 人' }));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.filter(([url]) => url === '/api/persona/handoffs'),
    ).toHaveLength(2),
  );
});

it('offers a reply the twin keeps giving as a team answer, with a title and words to change, or lets it go', async () => {
  const user = userEvent.setup();
  away = data({
    often: [
      {
        handoff_id: 'h5',
        title: '周报按项目写还是按人写？',
        reply: '按项目写。',
        askers: ['王屿', '周宁'],
        uses: 2,
        days: 7,
      },
    ],
    answers: { total: 4, stale: 1 },
  });
  mountAway();
  expect(await screen.findByText('常被问到')).toBeVisible();
  const row = screen.getByText('周报按项目写还是按人写？').closest('li')!;
  expect(row).toHaveTextContent('王屿、周宁 · 近 7 天 2 次');
  await user.click(within(row).getByRole('button', { name: '设为团队答案' }));
  const dialog = await screen.findByRole('dialog', { name: '设为团队答案' });
  const body = within(dialog).getByRole('textbox', { name: '内容' });
  expect(body).toHaveValue('按项目写。');
  await user.clear(body);
  await user.type(body, '按项目写，周五前发。');
  await user.click(within(dialog).getByRole('button', { name: '设好' }));
  await waitFor(() =>
    expect(posts()).toContainEqual([
      '/api/persona/team-answers',
      {
        handoff_id: 'h5',
        title: '周报按项目写还是按人写？',
        body: '按项目写，周五前发。',
      },
    ]),
  );
  await user.click(within(row).getByLabelText(/更多/u));
  await user.click(await screen.findByRole('button', { name: '不用' }));
  await waitFor(() =>
    expect(posts()).toContainEqual([
      '/api/persona/handoffs/h5/often/decline',
      {},
    ]),
  );
  // How many the person has set, and the way to them.
  expect(screen.getByText('我的团队答案 4')).toBeVisible();
  expect(screen.getByText('1 可能过期')).toBeVisible();
  expect(screen.getByRole('link', { name: '查看 ›' })).toHaveAttribute(
    'href',
    expect.stringContaining('view=answers'),
  );
});

const view = (d: AwayData, reload = async () => {}) => (
  <TooltipProvider>
    <MemoryRouter>
      <ToastViewport />
      <Away away={{ data: d, error: '', reload }} />
    </MemoryRouter>
  </TooltipProvider>
);

it('keeps what is being written to a group when another colleague asks the same thing, and keeps it taken apart', async () => {
  const user = userEvent.setup();
  const two = data({ waiting: same.slice(0, 2), groups: [['a', 'b']] });
  const three = data({ waiting: same, groups: [['a', 'b', 'c']] });
  const { rerender } = render(view(two));
  const card = await screen.findByRole('article', { name: '同一件事' });
  await user.type(
    within(card).getByRole('textbox', { name: '以本人回复 2 人' }),
    '先写一半',
  );
  // The page asks again and a third colleague is in the group: the same card, the words still in it.
  rerender(view(three));
  const wider = screen.getByRole('article', { name: '同一件事' });
  expect(wider).toBe(card);
  expect(within(wider).getByText('3 人问同一件事')).toBeVisible();
  expect(
    within(wider).getByRole('textbox', { name: /以本人回复/u }),
  ).toHaveValue('先写一半');
  // Taken apart, it stays so when the group grows.
  await user.click(within(wider).getByRole('button', { name: '拆开分别回' }));
  expect(screen.queryByRole('article', { name: '同一件事' })).toBeNull();
  rerender(
    view(
      data({
        waiting: [...same, asked('d', '周宁', '旧模板还能用吗？')],
        groups: [['a', 'b', 'c', 'd']],
      }),
    ),
  );
  expect(screen.queryByRole('article', { name: '同一件事' })).toBeNull();
});

it('tells the person why putting a folded question aside failed', async () => {
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
    pending: 2,
  });
  fetcher.mockImplementation(async (_url: string, init?: RequestInit) =>
    init?.method === 'POST'
      ? json({ detail: '团队库暂时读不了，请稍后重试' }, 503)
      : json(away),
  );
  render(
    <>
      <ToastViewport />
      <Away />
    </>,
  );
  const row = await screen.findByRole('listitem', {
    name: '这次发布要不要加测试环境？',
  });
  await user.click(within(row).getByLabelText(/更多/u));
  await user.click(within(row).getByRole('button', { name: '不答' }));
  expect(await screen.findByText('团队库暂时读不了，请稍后重试')).toBeVisible();
});

it('does not lose the words the person wrote when the twin’s draft takes their place, and gives them back', async () => {
  const user = userEvent.setup();
  away = data({ waiting: [handoff({})], pending: 1 });
  fetcher.mockImplementation(async (url: string) =>
    url === '/api/persona/handoffs'
      ? json(away)
      : json({ text: '这次先改。【请你定：测试补不补】' }),
  );
  render(<Away />);
  const card = await screen.findByRole('article', {
    name: /需求评审里那组接口/u,
  });
  const box = within(card).getByRole('textbox');
  // Nothing of theirs is replaced when the box is empty: there is nothing to give back.
  await user.click(within(card).getByRole('button', { name: '请分身起草' }));
  await waitFor(() =>
    expect(box).toHaveValue('这次先改。【请你定：测试补不补】'),
  );
  expect(within(card).queryByRole('button', { name: '换回我写的' })).toBeNull();
  // Words of their own, and then the draft: they can be had back, until the draft is changed.
  await user.clear(box);
  await user.type(box, '我的想法是下版本再改。');
  await user.click(within(card).getByRole('button', { name: '请分身起草' }));
  await waitFor(() =>
    expect(box).toHaveValue('这次先改。【请你定：测试补不补】'),
  );
  await user.click(within(card).getByRole('button', { name: '换回我写的' }));
  expect(box).toHaveValue('我的想法是下版本再改。');
  expect(within(card).queryByRole('button', { name: '换回我写的' })).toBeNull();
  await user.click(within(card).getByRole('button', { name: '请分身起草' }));
  await waitFor(() =>
    expect(box).toHaveValue('这次先改。【请你定：测试补不补】'),
  );
  await user.type(box, '再加一句');
  expect(within(card).queryByRole('button', { name: '换回我写的' })).toBeNull();
});

it('drafting again over an untouched draft still gives back the words the person first wrote', async () => {
  const user = userEvent.setup();
  away = data({ waiting: [handoff({})], pending: 1 });
  fetcher.mockImplementation(async (url: string) =>
    url === '/api/persona/handoffs'
      ? json(away)
      : json({ text: '这次先改。【请你定：测试补不补】' }),
  );
  render(<Away />);
  const card = await screen.findByRole('article', {
    name: /需求评审里那组接口/u,
  });
  const box = within(card).getByRole('textbox');
  await user.type(box, '我的想法是下版本再改。');
  await user.click(within(card).getByRole('button', { name: '请分身起草' }));
  await waitFor(() =>
    expect(box).toHaveValue('这次先改。【请你定：测试补不补】'),
  );
  await user.click(within(card).getByRole('button', { name: '请分身起草' }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
  await user.click(within(card).getByRole('button', { name: '换回我写的' }));
  expect(box).toHaveValue('我的想法是下版本再改。');
});

it('reads the list again when the question was answered meanwhile, and says so', async () => {
  const user = userEvent.setup();
  away = data({ waiting: [handoff({})], pending: 1 });
  fetcher.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === '/api/persona/handoffs') return json(away);
    away = data({
      settled: [
        handoff({ status: 'replied', status_label: '已回复', days_left: null }),
      ],
    });
    return init?.method === 'POST'
      ? json({ detail: '这条已经回复过了' }, 409)
      : json({});
  });
  render(<Away />);
  const card = await screen.findByRole('article', {
    name: /需求评审里那组接口/u,
  });
  await user.type(within(card).getByRole('textbox'), '先改。');
  await user.click(within(card).getByRole('button', { name: '发送' }));
  // The card goes at once, not at the next poll.
  expect(await screen.findByText('没有等你决定的事。')).toBeVisible();
  expect(screen.getByText('已处理 1')).toBeVisible();
});

it('tells which of the replies went out and whether the team answer came out, apart', async () => {
  const user = userEvent.setup();
  away = data({ waiting: same, groups: [['a', 'b', 'c']], pending: 3 });
  fetcher.mockImplementation(async (url: string) =>
    url === '/api/persona/handoffs'
      ? json(away)
      : json({
          done: ['a', 'b', 'c'],
          failed: [],
          team_answer: null,
          team_answer_error: '这条已经设为团队答案了',
          pending: 0,
        }),
  );
  render(view(away));
  const card = await screen.findByRole('article', { name: '同一件事' });
  await user.type(
    within(card).getByRole('textbox', { name: /以本人回复/u }),
    '好。',
  );
  await user.click(
    within(card).getByRole('checkbox', { name: '同时设为团队答案' }),
  );
  await user.click(within(card).getByRole('button', { name: '回复 3 人' }));
  expect(
    await screen.findByText(
      '已回复 3 人，团队答案没设成：这条已经设为团队答案了',
    ),
  ).toBeVisible();
});

it('lets a promise answered in words be taken or turned down from what was settled', async () => {
  const user = userEvent.setup();
  const promised = handoff({
    id: 'h7',
    kind: 'commit',
    kind_label: '要你答应',
    status: 'replied',
    status_label: '已回复',
    question: '周五前给我一版发布方案。',
    replied_at: '2026-10-22T10:00:00+00:00',
    days_left: null,
    commit: {
      entry_id: 'e7',
      what: '周五前给一版发布方案',
      due: null,
      pending: true,
    },
  });
  away = data({
    settled: [
      promised,
      {
        ...promised,
        id: 'h8',
        question: '周六前给我一版测试计划。',
        commit: { ...promised.commit!, pending: false },
      },
    ],
  });
  render(<Away />);
  // Opened for them, as there is something to do in it.
  const row = (await screen.findByText(/周五前给我一版发布方案/u)).closest(
    'li',
  )!;
  expect(row).toHaveTextContent('待接下');
  const other = screen.getByText(/周六前给我一版测试计划/u).closest('li')!;
  expect(within(other).queryByRole('button', { name: '接下' })).toBeNull();
  await user.click(within(row).getByRole('button', { name: '接下' }));
  await waitFor(() =>
    expect(posts()).toContainEqual(['/api/persona/handoffs/h7/accept', {}]),
  );
  await user.click(within(row).getByRole('button', { name: '不接' }));
  await waitFor(() =>
    expect(posts()).toContainEqual(['/api/persona/handoffs/h7/decline', {}]),
  );
});

it('ends with the line of the team answers the person has set, below what was settled', async () => {
  away = data({
    settled: [
      handoff({ status: 'replied', status_label: '已回复', days_left: null }),
    ],
    answers: { total: 2, stale: 0 },
  });
  render(
    <MemoryRouter>
      <Away />
    </MemoryRouter>,
  );
  const line = await screen.findByText('我的团队答案 2');
  expect(screen.getByText('已处理 1').compareDocumentPosition(line)).toBe(
    Node.DOCUMENT_POSITION_FOLLOWING,
  );
});
