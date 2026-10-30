import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { TooltipProvider } from '../components/ui';
import { Observations } from '../features/profile/Observations';

const json = (value: unknown) =>
  new Response(JSON.stringify(value), {
    headers: { 'Content-Type': 'application/json' },
  });
const DEFENSE = {
  id: 'ob_1',
  kind: 'defense',
  kind_label: '防御',
  text: '你在痛的时候让自己忙起来',
  quotes: [
    { quote: '那件事就别说了', date: '2019-06-01', dream: false },
    { quote: '我在找一个人', date: '2024-03-02', dream: true },
  ],
  mark: null,
};

it('makes observations when asked, shows the words they rest on, and keeps the person’s mark', async () => {
  const user = userEvent.setup();
  const sent: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      sent.push({
        url,
        method,
        body: typeof init?.body === 'string' ? JSON.parse(init.body) : null,
      });
      if (url === '/api/persona/observations' && method === 'GET')
        return json({ made_at: null, observations: [] });
      if (url === '/api/persona/observations')
        return json({
          made_at: '2026-10-30T12:00:00',
          observations: [DEFENSE],
        });
      return json({
        made_at: '2026-10-30T12:00:00',
        observations: [{ ...DEFENSE, mark: 'useless' }],
      });
    }),
  );
  render(
    <TooltipProvider>
      <Observations open onOpenChange={vi.fn()} />
    </TooltipProvider>,
  );
  const dialog = await screen.findByRole('dialog', { name: '剖析观察' });
  // Nothing is made until the person asks.
  await user.click(
    await within(dialog).findByRole('button', { name: '开始看' }),
  );
  expect(
    await within(dialog).findByText('你在痛的时候让自己忙起来'),
  ).toBeVisible();
  expect(within(dialog).getByText('防御')).toBeVisible();
  // The words it rests on are folded under it, a dream marked as one.
  const words = within(dialog).getByText(/那件事就别说了/);
  expect(words).not.toBeVisible();
  await user.click(within(dialog).getByText('原话 2'));
  expect(words).toHaveTextContent('2019-06-01：那件事就别说了');
  expect(within(dialog).getByText(/我在找一个人/)).toHaveTextContent(
    '梦 2024-03-02：我在找一个人',
  );
  const marks = within(dialog).getByRole('radiogroup', {
    name: '这条说得对吗',
  });
  expect(
    within(marks)
      .getAllByRole('radio')
      .map((r) => r.textContent),
  ).toEqual(['对', '不对', '对但没用']);
  await user.click(within(marks).getByRole('radio', { name: '对但没用' }));
  await waitFor(() =>
    expect(
      within(dialog).getByRole('radio', { name: '对但没用' }),
    ).toBeChecked(),
  );
  expect(sent.at(-1)).toEqual({
    url: '/api/persona/observations/ob_1/mark',
    method: 'PUT',
    body: { mark: 'useless' },
  });
  expect(within(dialog).getByRole('button', { name: '重新看' })).toBeVisible();
});

it('says why nothing could be made', async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method === 'POST'
        ? new Response(
            JSON.stringify({
              detail: '相关的记忆还太少，多回顾一些人生再来看',
            }),
            { status: 400, headers: { 'Content-Type': 'application/json' } },
          )
        : json({ made_at: null, observations: [] }),
    ),
  );
  render(
    <TooltipProvider>
      <Observations open onOpenChange={vi.fn()} />
    </TooltipProvider>,
  );
  await user.click(await screen.findByRole('button', { name: '开始看' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '相关的记忆还太少',
  );
});
