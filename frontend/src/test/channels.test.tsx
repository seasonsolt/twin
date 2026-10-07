import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Channels } from '../features/profile/Channels';
import { setPersonaId } from '../lib/persona';
import { usePersonas } from '../stores/personas';

const json = (wecom: unknown[]) => new Response(JSON.stringify({ wecom }));

beforeEach(() => {
  setPersonaId('default');
  usePersonas.setState({ id: 'default' });
});
afterEach(() => {
  vi.useRealTimers();
  setPersonaId('default');
  usePersonas.setState({ id: 'default' });
});

it('hides unconfigured channels and follows the persona API helper', async () => {
  const fetcher = vi.fn().mockResolvedValue(json([]));
  vi.stubGlobal('fetch', fetcher);
  render(<Channels />);
  await waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
  expect(screen.queryByText('接入')).not.toBeInTheDocument();
  expect(fetcher.mock.calls[0][0]).toBe('/api/channels');
  expect(fetcher.mock.calls[0][1].headers.get('X-Twin-Persona')).toBe(
    'default',
  );
});

it.each([
  ['connected', '', '已连接，同事可以在企业微信里和他聊', 'text-success'],
  ['connecting', '', '连接中…', 'text-warning'],
  ['error', '凭证无效', '凭证无效', 'text-danger'],
])('renders %s with a status dot', async (status, detail, text, tone) => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(json([{ bot_id: 'aibTest', status, detail }])),
  );
  render(<Channels />);
  expect(await screen.findByText(text)).toBeVisible();
  expect(screen.getByText('企业微信')).toBeVisible();
  expect(
    screen.getByText('接入').parentElement?.querySelector('[aria-hidden]'),
  ).toHaveClass(tone);
});

it('refreshes connection state and cancels polling on unmount', async () => {
  vi.useFakeTimers();
  const fetcher = vi
    .fn()
    .mockImplementationOnce(() =>
      Promise.resolve(
        json([{ bot_id: 'aibTest', status: 'connecting', detail: '' }]),
      ),
    )
    .mockImplementation(() =>
      Promise.resolve(
        json([{ bot_id: 'aibTest', status: 'connected', detail: '' }]),
      ),
    );
  vi.stubGlobal('fetch', fetcher);
  const view = render(<Channels />);
  await act(async () => {});
  expect(screen.getByText('连接中…')).toBeVisible();
  await act(async () => vi.advanceTimersByTimeAsync(5000));
  expect(screen.getByText('已连接，同事可以在企业微信里和他聊')).toBeVisible();
  view.unmount();
  await act(async () => vi.advanceTimersByTimeAsync(10000));
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it('never publishes an old persona response into the new profile', async () => {
  let resolveOld!: (value: Response) => void;
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveOld = resolve;
          }),
      )
      .mockResolvedValue(json([])),
  );
  render(<Channels />);
  await act(async () => {
    setPersonaId('other');
    usePersonas.setState({ id: 'other' });
  });
  await act(async () =>
    resolveOld(json([{ bot_id: 'old', status: 'connected', detail: '' }])),
  );
  expect(screen.queryByText('企业微信')).not.toBeInTheDocument();
});
