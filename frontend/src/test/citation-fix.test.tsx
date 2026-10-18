import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { toast } from '../components/ui';
import { Citations } from '../features/chat/Citations';
import type { Citation } from '../features/chat/types';
import { setPersonaId } from '../lib/persona';
import { usePersonas, type Persona } from '../stores/personas';

vi.mock('../components/ui', async (original) => ({
  ...(await original<typeof import('../components/ui')>()),
  toast: vi.fn(),
}));
vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));

const cited: Citation[] = [
  { id: 'pi/1', kind: 'item', facet: '价值观', text: '钱到账才算' },
  { id: 'e1', kind: 'expression', date: '2026-10-01', text: '我说过的话' },
];
let fetcher: ReturnType<typeof vi.fn>;
let status = 200;

beforeEach(() => {
  status = 200;
  vi.mocked(toast).mockClear();
  fetcher = vi.fn(
    async () =>
      new Response(JSON.stringify({ detail: '找不到档案条目' }), { status }),
  );
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => {
  setPersonaId('default');
  usePersonas.setState({ id: 'default', items: [] });
});

const open = async () => {
  const user = userEvent.setup();
  render(<Citations cited={cited} />);
  await user.click(screen.getByRole('button', { name: /^依据 · / }));
  return { user, list: screen.getByRole('list', { name: '回答依据' }) };
};
const sent = () =>
  fetcher.mock.calls.map(([url, init]) => [
    url,
    JSON.parse(String((init as RequestInit).body)),
  ]);

it('lets the person correct a memory right where the answer used it', async () => {
  const { user, list } = await open();
  const [memory, words] = within(list).getAllByRole('listitem');
  expect(
    within(words).queryByRole('button', { name: '改一下' }),
  ).not.toBeInTheDocument();
  await user.click(within(memory).getByRole('button', { name: '改一下' }));
  fireEvent.change(within(memory).getByLabelText('修改这条记忆'), {
    target: { value: '钱进了账户才算收入' },
  });
  await user.click(within(memory).getByRole('button', { name: '保存' }));
  expect(sent()).toEqual([
    [
      '/api/persona/items/pi%2F1/review',
      { status: 'edited', statement: '钱进了账户才算收入', note: '' },
    ],
  ]);
  expect(await within(memory).findByText('钱进了账户才算收入')).toBeVisible();
  expect(toast).toHaveBeenCalledWith('改好了，之后按这条回答', 'success');
});

it('removes a memory from the answer it misled, and says why when that fails', async () => {
  const { user, list } = await open();
  const memory = within(list).getAllByRole('listitem')[0];
  status = 404;
  await user.click(within(memory).getByRole('button', { name: '删掉' }));
  expect(toast).toHaveBeenCalledWith('找不到档案条目', 'danger');
  expect(within(memory).queryByText('已删掉')).not.toBeInTheDocument();
  status = 200;
  await user.click(within(memory).getByRole('button', { name: '删掉' }));
  expect(sent().at(-1)).toEqual([
    '/api/persona/items/pi%2F1/review',
    { status: 'rejected', statement: null, note: '' },
  ]);
  expect(await within(memory).findByText('已删掉')).toBeVisible();
  expect(within(memory).getByText('钱到账才算')).toHaveClass('line-through');
  expect(
    within(memory).queryByRole('button', { name: '改一下' }),
  ).not.toBeInTheDocument();
});

it('shows a visitor of a public twin the evidence only', async () => {
  usePersonas.setState({
    id: 'p2',
    items: [{ id: 'p2', name: '朋友', can_manage: false } as Persona],
  });
  setPersonaId('p2');
  const { list } = await open();
  expect(within(list).queryByRole('button')).not.toBeInTheDocument();
});
