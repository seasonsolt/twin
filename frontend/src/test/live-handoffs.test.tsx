import { render, screen, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { expect, it, vi, afterEach } from 'vitest';
import { TooltipProvider } from '../components/ui';
import { Delegation } from '../features/delegation/Delegation';
import type { DelegationTarget } from '../features/delegation/types';
import { useAway } from '../features/away/useAway';
import { setPersonaId } from '../lib/persona';
import { usePersonas } from '../stores/personas';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
const json = (value: unknown) =>
  new Response(JSON.stringify(value), { status: 200 });
const init = () => {
  setPersonaId('default');
  usePersonas.setState({ id: 'default', items: [] });
};

it('the open delegation updates when the colleague replies elsewhere', async () => {
  init();
  let target: DelegationTarget = {
    persona_id: 'p-chen',
    name: '陈一',
    conversation_id: 'c-chen',
    state: 'handed',
    answer: '等本人决定',
    mode: 'general',
    ask: '排期',
    team_answer: null,
    handoff: { status: 'delivered', status_label: '已送达' },
    owner_reply: null,
    also: [],
  };
  const fetcher = vi.fn(async () =>
    json({ id: 'd1', question: '排期怎么定', targets: [target], limit: 3 }),
  );
  vi.stubGlobal('fetch', fetcher);
  render(
    <TooltipProvider>
      <MemoryRouter>
        <Delegation note={{ id: 'd1', summary: '' }} />
      </MemoryRouter>
    </TooltipProvider>,
  );
  await screen.findByText('等本人回复');
  vi.useFakeTimers();
  await act(async () => {
    document.dispatchEvent(new Event('visibilitychange'));
  });
  target = {
    ...target,
    state: 'replied',
    owner_reply: '下周三前给你',
    handoff: { status: 'replied', status_label: '已回复' },
  };
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000);
  });
  expect(fetcher.mock.calls.length).toBeGreaterThan(1);
  expect(screen.queryByText('本人已回')).not.toBeNull();
  const settledCalls = fetcher.mock.calls.length;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30000);
  });
  expect(fetcher).toHaveBeenCalledTimes(settledCalls);
});

it('the open away page receives a newly arrived handoff', async () => {
  init();
  let pending = 0;
  const fetcher = vi.fn(async () =>
    json({
      pending,
      waiting: [],
      groups: [],
      often: [],
      answers: { total: 0, stale: 0 },
      guessed: [],
      sourced: [],
      sourced_count: 0,
      answered: 0,
      shelved: [],
      settled: [],
      days: 7,
    }),
  );
  vi.stubGlobal('fetch', fetcher);
  function Probe() {
    const { data } = useAway(true);
    return <div>{data ? `pending:${data.pending}` : 'loading'}</div>;
  }
  render(<Probe />);
  await screen.findByText('pending:0');
  vi.useFakeTimers();
  await act(async () => {
    document.dispatchEvent(new Event('visibilitychange'));
  });
  pending = 1;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(15000);
  });
  expect(fetcher.mock.calls.length).toBeGreaterThan(1);
  expect(screen.queryByText('pending:1')).not.toBeNull();
});
