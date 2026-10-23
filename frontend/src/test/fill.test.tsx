import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { TooltipProvider } from '../components/ui';
import { FillDialog } from '../features/fill/FillDialog';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));

const json = (value: unknown) =>
  new Response(JSON.stringify(value), { status: 200 });
const FIRST = '在推知识库检索改版，月底前要提高命中率';
const SECOND = '在带两个新人熟悉评审流程';
const worth = (names: string[]) =>
  names.map((facet) => ({
    facet_id: facet,
    facet: facet === '8.1' ? '近期重点' : '正在做的事',
    before: 0,
    after: 1,
    before_label: '还不了解',
    after_label: '提到过',
  }));

let calls: { url: string; body: unknown }[];
let kept: number;
beforeEach(() => {
  calls = [];
  kept = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({
        url,
        body: typeof init?.body === 'string' ? JSON.parse(init.body) : null,
      });
      if (url.startsWith('/api/persona/fill?'))
        return json({
          questions: [
            {
              id: 'q17',
              text: '最近有什么事占了你比较多的时间或心思？现在怎么样了？',
              facet: '8.1',
              facet_name: '近期重点',
              level: 0,
              level_label: '还不了解',
              tier: 'colleague',
            },
          ],
        });
      if (url === '/api/persona/fill/draft')
        return json({
          drafts: [
            {
              facet: '8.1',
              facet_name: '近期重点',
              statement: FIRST,
              tier: 'colleague',
            },
            {
              facet: '8.2',
              facet_name: '正在做的事',
              statement: SECOND,
              tier: 'colleague',
            },
          ],
          changes: worth(['8.1', '8.2']),
        });
      if (url === '/api/persona/fill/preview') {
        const sent = (
          JSON.parse(String(init?.body)) as {
            items: { facet: string; choice: string }[];
          }
        ).items;
        return json({
          changes: worth(
            sent.filter((i) => i.choice !== 'none').map((i) => i.facet),
          ),
        });
      }
      if (url === '/api/persona/fill/keep') {
        const sent = (
          JSON.parse(String(init?.body)) as { items: { choice: string }[] }
        ).items;
        kept = sent.filter((i) => i.choice !== 'none').length;
        return json({ saved: kept, changes: [] });
      }
      return json({});
    }),
  );
});

function open(onKept = vi.fn(), onOpenChange = vi.fn()) {
  render(
    <TooltipProvider>
      <FillDialog
        open
        onOpenChange={onOpenChange}
        scope={{ facet: '8.1' }}
        onKept={onKept}
      />
    </TooltipProvider>,
  );
  return { onKept, onOpenChange };
}

it('reads an answer into drafts, shows what keeping them is worth, and keeps only what the person chose', async () => {
  const user = userEvent.setup();
  const { onKept, onOpenChange } = open();
  const dialog = await screen.findByRole('dialog', { name: '补一补' });
  // The dialog fades in: it is read once it has.
  await waitFor(() =>
    expect(
      within(dialog).getByText(/最近有什么事占了你比较多的时间/),
    ).toBeVisible(),
  );
  expect(calls[0].url).toBe('/api/persona/fill?facet=8.1');
  // Nothing is offered to keep before the answer is read.
  expect(
    within(dialog).getByRole('button', { name: '存进记忆' }),
  ).toBeDisabled();
  await user.type(
    within(dialog).getByRole('textbox', { name: '你的回答' }),
    '在推知识库检索改版。另外在带两个新人熟悉评审。',
  );
  await user.click(within(dialog).getByRole('button', { name: '整理' }));
  expect(await within(dialog).findByText('整理成 2 条')).toBeVisible();
  expect(within(dialog).getByText(FIRST)).toBeVisible();
  const lines = within(dialog).getAllByRole('radiogroup', {
    name: '谁能用这条',
  });
  expect(
    within(lines[0]).getByRole('radio', { name: '同事能用' }),
  ).toHaveAttribute('aria-checked', 'true');
  expect(
    within(dialog).getByRole('img', {
      name: '存了以后：近期重点从还不了解升到提到过',
    }),
  ).toBeVisible();
  // The second is not kept: its facet is no longer told to go up.
  await user.click(within(lines[1]).getByRole('radio', { name: '不存' }));
  await waitFor(() =>
    expect(
      within(dialog).queryByRole('img', { name: /正在做的事从/ }),
    ).toBeNull(),
  );
  await user.click(within(lines[0]).getByRole('radio', { name: '只有我' }));
  await user.click(within(dialog).getByRole('button', { name: '存进记忆' }));
  await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  expect(
    calls.find((call) => call.url === '/api/persona/fill/keep')?.body,
  ).toEqual({
    question: 'q17',
    facet: '8.1',
    items: [
      { facet: '8.1', statement: FIRST, choice: 'self' },
      { facet: '8.2', statement: SECOND, choice: 'none' },
    ],
  });
  expect(kept).toBe(1);
  expect(onKept).toHaveBeenCalled();
});

it('keeps nothing when the person skips', async () => {
  const user = userEvent.setup();
  const { onKept, onOpenChange } = open();
  await screen.findByRole('dialog', { name: '补一补' });
  await user.click(screen.getByRole('button', { name: '跳过' }));
  expect(onOpenChange).toHaveBeenCalledWith(false);
  expect(onKept).not.toHaveBeenCalled();
  expect(calls.some((call) => call.url === '/api/persona/fill/keep')).toBe(
    false,
  );
});

it('says so when there is nothing left to ask', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => json({ questions: [] })),
  );
  open();
  // The dialog fades in: the words are there before they can be seen.
  const none = await screen.findByText(/暂时没有要补的/);
  await waitFor(() => expect(none).toBeVisible());
});
