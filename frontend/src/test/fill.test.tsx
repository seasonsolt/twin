import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { TooltipProvider } from '../components/ui';
import { FillDialog } from '../features/fill/FillDialog';
import { useAuth } from '../stores/auth';

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

const failing = (url: string, status: number, detail: string) => {
  const fetcher = vi.mocked(fetch);
  const original = fetcher.getMockImplementation()!;
  fetcher.mockImplementation(async (input, init) =>
    String(input) === url
      ? new Response(JSON.stringify({ detail }), { status })
      : original(input, init),
  );
};

async function answered(
  user: ReturnType<typeof userEvent.setup>,
  asked = /最近有什么事占了你比较多的时间/,
) {
  const dialog = await screen.findByRole('dialog', { name: '补一补' });
  await waitFor(() => expect(within(dialog).getByText(asked)).toBeVisible());
  await user.type(
    within(dialog).getByRole('textbox', { name: '你的回答' }),
    '在推知识库检索改版。',
  );
  return dialog;
}

it('shows why an answer could not be read, and why it could not be kept', async () => {
  const user = userEvent.setup();
  failing('/api/persona/fill/draft', 502, '暂时没能整理这段回答，请重试');
  open();
  const dialog = await answered(user);
  await user.click(within(dialog).getByRole('button', { name: '整理' }));
  expect(await within(dialog).findByRole('alert')).toHaveTextContent(
    '暂时没能整理这段回答，请重试',
  );
});

it('says why keeping failed and keeps the conclusions to try again', async () => {
  const user = userEvent.setup();
  failing('/api/persona/fill/keep', 409, '记忆正在更新，请稍后再试');
  const { onKept, onOpenChange } = open();
  const dialog = await answered(user);
  await user.click(within(dialog).getByRole('button', { name: '整理' }));
  await within(dialog).findByText('整理成 2 条');
  await user.click(within(dialog).getByRole('button', { name: '存进记忆' }));
  expect(await within(dialog).findByRole('alert')).toHaveTextContent(
    '记忆正在更新，请稍后再试',
  );
  expect(within(dialog).getByText(FIRST)).toBeVisible();
  expect(onKept).not.toHaveBeenCalled();
  expect(onOpenChange).not.toHaveBeenCalled();
});

it('tells the page what was stored when the dialog is closed before the last question', async () => {
  const user = userEvent.setup();
  const fetcher = vi.mocked(fetch);
  const original = fetcher.getMockImplementation()!;
  const asked = (id: string) => ({
    id,
    text: `问题 ${id}`,
    facet: '8.1',
    facet_name: '近期重点',
    level: 0,
    level_label: '还不了解',
  });
  fetcher.mockImplementation(async (input, init) =>
    String(input).startsWith('/api/persona/fill?')
      ? json({ questions: [asked('q17'), asked('q18'), asked('q19')] })
      : original(input, init),
  );
  const { onKept, onOpenChange } = open();
  const dialog = await answered(user, /问题 q17/);
  await user.click(within(dialog).getByRole('button', { name: '整理' }));
  await within(dialog).findByText('整理成 2 条');
  await user.click(within(dialog).getByRole('button', { name: '存进记忆' }));
  await within(dialog).findByText('第 2 题，共 3 题');
  expect(onKept).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: /关闭|Close/ }));
  expect(onOpenChange).toHaveBeenCalledWith(false);
  expect(onKept).toHaveBeenCalledTimes(1);
});

it('does not tell the page anything when the dialog is closed with nothing stored', async () => {
  const user = userEvent.setup();
  const { onKept, onOpenChange } = open();
  await screen.findByRole('dialog', { name: '补一补' });
  await user.keyboard('{Escape}');
  expect(onOpenChange).toHaveBeenCalledWith(false);
  expect(onKept).not.toHaveBeenCalled();
});

it('asks about the aspect shown as wanting more when what the twin knows least has nothing to ask', async () => {
  vi.mocked(fetch).mockImplementation(async (input) =>
    String(input) === '/api/persona/fill'
      ? json({ questions: [] })
      : String(input) === '/api/persona/fill?dimension=D9'
        ? json({
            questions: [
              {
                id: 'q30',
                text: '平时有什么爱好？',
                facet: '9.1',
                facet_name: '兴趣爱好',
                level: 0,
                level_label: '还不了解',
              },
            ],
          })
        : json({}),
  );
  render(
    <TooltipProvider>
      <FillDialog
        open
        onOpenChange={vi.fn()}
        scope={{ otherwise: 'D9' }}
        onKept={vi.fn()}
      />
    </TooltipProvider>,
  );
  expect(await screen.findByText('平时有什么爱好？')).toBeInTheDocument();
});

it('in the persona edition asks about the person’s life stage by stage, keeps it only for them, and remembers what was passed over', async () => {
  const user = userEvent.setup();
  useAuth.setState({
    identity: {
      email: 'me@example.com',
      admin: false,
      auth_enabled: false,
      features: { work: false },
      edition: 'persona',
    },
  });
  const childhood = (id: string, text: string) => ({
    id,
    text,
    facet: '1.3',
    facet_name: '常讲的经历与故事',
    level: 0,
    level_label: '还不了解',
    stage: 'childhood',
    stage_label: '童年',
  });
  const sent: { url: string; body: unknown }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      sent.push({
        url,
        body: typeof init?.body === 'string' ? JSON.parse(init.body) : null,
      });
      if (url === '/api/persona/life-review')
        return json({
          questions: [
            childhood('L01', '你记得的最早的一件事是什么？'),
            childhood('L02', '小时候家里是什么样的？'),
          ],
          stages: [{ id: 'childhood', label: '童年', answered: 0, total: 3 }],
        });
      if (url === '/api/persona/fill/draft')
        return json({
          drafts: [
            {
              facet: '1.3',
              facet_name: '常讲的经历与故事',
              statement: '最早的记忆是外婆家的院子',
              tier: 'colleague',
            },
          ],
          changes: [],
        });
      if (url === '/api/persona/fill/keep') return json({ saved: 1 });
      return json({});
    }),
  );
  const onKept = vi.fn();
  render(
    <TooltipProvider>
      <FillDialog
        open
        onOpenChange={vi.fn()}
        scope={{ life: true }}
        onKept={onKept}
      />
    </TooltipProvider>,
  );
  const dialog = await screen.findByRole('dialog', { name: '回顾人生' });
  await waitFor(() =>
    expect(
      within(dialog).getByText('你记得的最早的一件事是什么？'),
    ).toBeVisible(),
  );
  expect(within(dialog).getByText('童年 · 0/3')).toBeInTheDocument();
  await user.type(within(dialog).getByLabelText('你的回答'), '外婆家的院子');
  await user.click(within(dialog).getByRole('button', { name: '整理' }));
  // No colleagues to share it with: kept for the person, or not at all.
  const tiers = await within(dialog).findByRole('radiogroup', {
    name: '谁能用这条',
  });
  expect(within(tiers).queryByText('同事能用')).not.toBeInTheDocument();
  expect(within(tiers).getByRole('radio', { name: '只有我' })).toBeChecked();
  await user.click(within(dialog).getByRole('button', { name: '存进记忆' }));
  expect(
    await within(dialog).findByText('小时候家里是什么样的？'),
  ).toBeInTheDocument();
  expect(within(dialog).getByText('童年 · 1/3')).toBeInTheDocument();
  expect(sent.find((c) => c.url === '/api/persona/fill/keep')?.body).toEqual({
    question: 'L01',
    facet: '1.3',
    items: [
      { facet: '1.3', statement: '最早的记忆是外婆家的院子', choice: 'self' },
    ],
  });
  // Passed over, the question is remembered so it comes back after the others.
  await user.click(within(dialog).getByRole('button', { name: '跳过' }));
  await waitFor(() => expect(onKept).toHaveBeenCalled());
  expect(
    sent.find((c) => c.url === '/api/persona/life-review/skip')?.body,
  ).toEqual({ question: 'L02' });
  useAuth.setState({ identity: null });
});
