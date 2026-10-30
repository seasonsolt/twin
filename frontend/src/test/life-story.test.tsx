import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { TooltipProvider } from '../components/ui';
import { LifeStory } from '../features/profile/LifeStory';

const json = (value: unknown) =>
  new Response(JSON.stringify(value), {
    headers: { 'Content-Type': 'application/json' },
  });
const told = (item_id: string, statement: string, basis: string | null) => ({
  item_id,
  facet_id: '1.2',
  facet_name: '重要经历与转折',
  statement,
  basis,
});

it('lays out what was told by year, each run of empty years as one blank, and what has no year folded', async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      url === '/api/persona/life-story'
        ? json({
            years: [
              {
                year: 2015,
                until: 2015,
                items: [told('pi_quit', '辞职去了大理', 'written')],
              },
              { year: 2016, until: 2020, items: [] },
              {
                year: 2021,
                until: 2021,
                items: [told('pi_proud', '第一次独立带完项目', 'dated')],
              },
            ],
            undated: [told('pi_granny', '最早的记忆是外婆家的院子', null)],
          })
        : json({}),
    ),
  );
  render(
    <TooltipProvider>
      <LifeStory open onOpenChange={vi.fn()} />
    </TooltipProvider>,
  );
  const dialog = await screen.findByRole('dialog', { name: '生命线' });
  const years = await within(dialog).findByRole('list', { name: '按年份' });
  await waitFor(() =>
    expect(within(years).getByText('辞职去了大理')).toBeVisible(),
  );
  expect(within(years).getAllByRole('listitem')[0]).toHaveTextContent('2015');
  // Nothing is filled in for the years with nothing: one blank row.
  expect(within(years).getByLabelText('没有资料')).toHaveTextContent(
    '2016–2020',
  );
  // A year from when the words were written, not from the words, says so.
  expect(within(years).getAllByText('记于当年')).toHaveLength(1);
  expect(
    within(years).getByText('第一次独立带完项目').closest('li'),
  ).toHaveTextContent('记于当年');
  // What has no year is not placed anywhere; it waits, folded, at the end.
  expect(
    within(dialog).getByText('最早的记忆是外婆家的院子'),
  ).not.toBeVisible();
  await user.click(within(dialog).getByText('年份不明 1'));
  expect(within(dialog).getByText('最早的记忆是外婆家的院子')).toBeVisible();
});

it('says what to do when nothing of the life has been told', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => json({ years: [], undated: [] })),
  );
  render(
    <TooltipProvider>
      <LifeStory open onOpenChange={vi.fn()} />
    </TooltipProvider>,
  );
  expect(
    await screen.findByText('回顾人生之后，这里按年份排出来。'),
  ).toBeInTheDocument();
});
