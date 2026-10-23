import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider, TooltipProvider } from '../components/ui';
import { MyAnswers } from '../features/answers/MyAnswers';
import type { MyTeamAnswer } from '../features/answers/types';
import { setPersonaId } from '../lib/persona';
import { usePersonas } from '../stores/personas';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const answer = (overrides: Partial<MyTeamAnswer> = {}): MyTeamAnswer => ({
  id: 'ta_1',
  persona_id: 'default',
  owner_name: '林舟',
  title: '旧版 Word 模板还支持吗？',
  body: '支持到 12 月 31 日，之后只保留新模板。',
  confirmed_at: '2026-10-22T09:00:00+00:00',
  status: 'valid',
  stale_note: '',
  partial: false,
  handoff_id: 'h1',
  ...overrides,
});

let listed: MyTeamAnswer[];
let fetcher: ReturnType<typeof vi.fn>;
const sent = (suffix: string) =>
  fetcher.mock.calls.filter(
    ([url, init]) => String(url).endsWith(suffix) && init?.method !== 'GET',
  );

beforeEach(() => {
  setPersonaId('default');
  usePersonas.setState({ id: 'default', items: [] });
  listed = [];
  fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/persona/team-answers' && init?.method === 'GET')
      return json({ team_answers: listed });
    return json({ team_answer: answer() });
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => vi.unstubAllGlobals());

const mount = () =>
  render(
    <TooltipProvider>
      <ConfirmProvider>
        <MyAnswers />
      </ConfirmProvider>
    </TooltipProvider>,
  );

it('tells the person how to set one when they have none', async () => {
  mount();
  expect(await screen.findByText('还没有团队答案')).toBeVisible();
  expect(screen.getByText(/同时设为团队答案/u)).toBeVisible();
});

it('lists what the person made the team’s, those possibly out of date with what they said since', async () => {
  listed = [
    answer({
      id: 'ta_2',
      title: '续约折扣谁能批？',
      status: 'stale',
      stale_note: '10 月 27 日「周会」里说：超过 20% 才报沈总',
    }),
    answer(),
  ];
  mount();
  const stale = (await screen.findByText('续约折扣谁能批？')).closest('li')!;
  expect(within(stale).getByText('可能过期')).toBeVisible();
  expect(within(stale).getByText(/超过 20% 才报沈总/u)).toBeVisible();
  const valid = screen.getByText('旧版 Word 模板还支持吗？').closest('li')!;
  expect(valid).toHaveTextContent('10 月 22 日确认');
  expect(within(valid).queryByText('可能过期')).toBeNull();
});

it('puts an answer right with new words, and it stands again', async () => {
  const user = userEvent.setup();
  listed = [answer()];
  mount();
  const row = (await screen.findByText('旧版 Word 模板还支持吗？')).closest(
    'li',
  )!;
  await user.click(within(row).getByRole('button', { name: '更新' }));
  const dialog = await screen.findByRole('dialog', { name: '更新团队答案' });
  const body = within(dialog).getByRole('textbox', { name: '内容' });
  await user.clear(body);
  await user.type(body, '支持到 2027 年 3 月。');
  await user.click(within(dialog).getByRole('button', { name: '保存' }));
  await waitFor(() => expect(sent('/team-answers/ta_1')).toHaveLength(1));
  const [, init] = sent('/team-answers/ta_1')[0];
  expect(init.method).toBe('PATCH');
  expect(JSON.parse(String(init.body))).toEqual({
    title: '旧版 Word 模板还支持吗？',
    body: '支持到 2027 年 3 月。',
  });
});

it('says what it could not save and keeps the box open', async () => {
  const user = userEvent.setup();
  listed = [answer()];
  fetcher.mockImplementation(async (_url: string, init?: RequestInit) =>
    init?.method === 'PATCH'
      ? json({ detail: '这条团队答案已经撤回了' }, 409)
      : json({ team_answers: listed }),
  );
  mount();
  const row = (await screen.findByText('旧版 Word 模板还支持吗？')).closest(
    'li',
  )!;
  await user.click(within(row).getByRole('button', { name: '更新' }));
  const dialog = await screen.findByRole('dialog', { name: '更新团队答案' });
  await user.click(within(dialog).getByRole('button', { name: '保存' }));
  expect(await within(dialog).findByRole('alert')).toHaveTextContent(
    '已经撤回了',
  );
});

it('says a doubted answer still stands, or takes it back after asking', async () => {
  const user = userEvent.setup();
  listed = [
    answer({ status: 'stale', stale_note: '10 月 27 日「周会」里说：改了' }),
  ];
  mount();
  const row = (await screen.findByText('旧版 Word 模板还支持吗？')).closest(
    'li',
  )!;
  await user.click(within(row).getByLabelText(/更多/u));
  await user.click(await screen.findByRole('button', { name: '仍然有效' }));
  await waitFor(() => expect(sent('/team-answers/ta_1/keep')).toHaveLength(1));

  await user.click(within(row).getByLabelText(/更多/u));
  await user.click(await screen.findByRole('button', { name: '撤回' }));
  const ask = await screen.findByRole('dialog', { name: '撤回这条团队答案？' });
  expect(sent('/withdraw')).toHaveLength(0);
  await user.click(within(ask).getByRole('button', { name: '撤回' }));
  await waitFor(() =>
    expect(sent('/team-answers/ta_1/withdraw')).toHaveLength(1),
  );
});
