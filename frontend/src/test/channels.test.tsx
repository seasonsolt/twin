import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider } from '../components/ui';
import { Channels } from '../features/profile/Channels';
import { setPersonaId } from '../lib/persona';
import { usePersonas } from '../stores/personas';

const response = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status });
const json = (wecom: unknown) => response({ wecom });
const binding = {
  bot_id: 'aibTest',
  status: 'connected',
  detail: '已连接',
  secret_set: true,
};
const renderChannels = () =>
  render(
    <ConfirmProvider>
      <Channels />
    </ConfirmProvider>,
  );

beforeEach(() => {
  setPersonaId('default');
  usePersonas.setState({ id: 'default' });
});
afterEach(() => {
  vi.useRealTimers();
  setPersonaId('default');
  usePersonas.setState({ id: 'default' });
});

it('always shows an unbound channel and follows the persona API helper', async () => {
  const fetcher = vi.fn().mockResolvedValue(json(null));
  vi.stubGlobal('fetch', fetcher);
  renderChannels();
  await waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
  expect(screen.getByText('接入')).toBeVisible();
  expect(screen.getByText('让同事在企业微信里单聊或 @ 这个分身')).toBeVisible();
  expect(screen.getByRole('button', { name: '绑定' })).toBeVisible();
  expect(fetcher.mock.calls[0][0]).toBe('/api/channels');
  expect(fetcher.mock.calls[0][1].headers.get('X-Twin-Persona')).toBe(
    'default',
  );
});

it.each([
  ['connected', '', '已连接，同事可以在企业微信里和他聊', 'text-success'],
  ['connecting', '', '连接中…', 'text-warning'],
  ['error', 'Bot ID 或 Secret 不对', 'Bot ID 或 Secret 不对', 'text-danger'],
])(
  'renders %s with a status dot and Bot ID',
  async (status, detail, text, tone) => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(json({ ...binding, status, detail })),
    );
    renderChannels();
    expect(await screen.findByText(text)).toBeVisible();
    expect(screen.getByText('企业微信')).toBeVisible();
    expect(screen.getByText('aibTest')).toHaveClass('font-mono');
    expect(
      screen.getByText('接入').parentElement?.querySelector('[aria-hidden]'),
    ).toHaveClass(tone);
  },
);

it('binds with trimmed credentials, disables save while pending, and shows connecting', async () => {
  let resolveSave!: (value: Response) => void;
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(json(null))
    .mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          resolveSave = resolve;
        }),
    );
  vi.stubGlobal('fetch', fetcher);
  const user = userEvent.setup();
  renderChannels();
  await waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
  await user.click(screen.getByRole('button', { name: '绑定' }));
  await user.type(screen.getByLabelText('Bot ID'), ' aibTest ');
  await user.type(screen.getByLabelText('Secret'), ' private-secret ');
  expect(screen.getByLabelText('Secret')).toHaveAttribute('type', 'password');
  expect(screen.getByLabelText('Secret')).toHaveAttribute(
    'autocomplete',
    'off',
  );
  await user.click(screen.getByRole('button', { name: '保存' }));
  expect(screen.getByRole('button', { name: '保存' })).toBeDisabled();
  expect(fetcher.mock.calls[1][0]).toBe('/api/channels/wecom');
  expect(fetcher.mock.calls[1][1].method).toBe('PUT');
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({
    bot_id: 'aibTest',
    secret: 'private-secret',
  });
  await act(async () =>
    resolveSave(response({ ...binding, status: 'connecting' })),
  );
  expect(screen.getByText('连接中…')).toBeVisible();
  expect(screen.queryByLabelText('Secret')).not.toBeInTheDocument();
});

it('edits a binding with an empty secret sent as null', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(json(binding))
    .mockResolvedValueOnce(response(binding));
  vi.stubGlobal('fetch', fetcher);
  const user = userEvent.setup();
  renderChannels();
  await user.click(await screen.findByRole('button', { name: '修改' }));
  expect(screen.getByLabelText('Bot ID')).toHaveValue('aibTest');
  expect(screen.getByLabelText('Secret')).toHaveValue('');
  expect(screen.getByLabelText('Secret')).toHaveAttribute(
    'placeholder',
    '不修改就留空',
  );
  await user.click(screen.getByRole('button', { name: '保存' }));
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({
    bot_id: 'aibTest',
    secret: null,
  });
});

it('unbinds only after confirmation', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(json(binding))
    .mockResolvedValueOnce(response({ deleted: true }));
  vi.stubGlobal('fetch', fetcher);
  const user = userEvent.setup();
  renderChannels();
  await user.click(await screen.findByRole('button', { name: '解绑' }));
  const dialog = await screen.findByRole('dialog');
  expect(fetcher).toHaveBeenCalledOnce();
  await user.click(within(dialog).getByRole('button', { name: '取消' }));
  expect(fetcher).toHaveBeenCalledOnce();
  await user.click(await screen.findByRole('button', { name: '解绑' }));
  await user.click(
    within(await screen.findByRole('dialog')).getByRole('button', {
      name: '确认解绑',
    }),
  );
  await waitFor(() =>
    expect(screen.getByRole('button', { name: '绑定' })).toBeVisible(),
  );
  expect(fetcher.mock.calls[1][1].method).toBe('DELETE');
  expect(fetcher.mock.calls[1][0]).toBe('/api/channels/wecom');
});

it('shows server errors inline without clearing the form', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(json(null))
      .mockResolvedValueOnce(
        response({ detail: '这个机器人已经绑定了另一个分身' }, 409),
      ),
  );
  const user = userEvent.setup();
  renderChannels();
  await user.click(screen.getByRole('button', { name: '绑定' }));
  await user.type(screen.getByLabelText('Bot ID'), 'aibTest');
  await user.type(screen.getByLabelText('Secret'), 'secret');
  await user.click(screen.getByRole('button', { name: '保存' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '这个机器人已经绑定了另一个分身',
  );
  expect(screen.getByLabelText('Bot ID')).toHaveValue('aibTest');
  expect(screen.getByRole('button', { name: '保存' })).not.toBeDisabled();
});

it('refreshes connection state and cancels polling on unmount', async () => {
  vi.useFakeTimers();
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(json({ ...binding, status: 'connecting' }))
    .mockImplementation(() => Promise.resolve(json(binding)));
  vi.stubGlobal('fetch', fetcher);
  const view = renderChannels();
  await act(async () => {});
  expect(screen.getByText('连接中…')).toBeVisible();
  await act(async () => vi.advanceTimersByTimeAsync(5000));
  expect(screen.getByText('已连接，同事可以在企业微信里和他聊')).toBeVisible();
  view.unmount();
  await act(async () => vi.advanceTimersByTimeAsync(10000));
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it('never publishes an old persona response or form into the new profile', async () => {
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
      .mockResolvedValue(json(null)),
  );
  renderChannels();
  fireEvent.click(screen.getByRole('button', { name: '绑定' }));
  fireEvent.change(screen.getByLabelText('Secret'), {
    target: { value: 'old-secret' },
  });
  await act(async () => {
    setPersonaId('other');
    usePersonas.setState({ id: 'other' });
  });
  await act(async () => resolveOld(json({ ...binding, bot_id: 'old' })));
  expect(screen.queryByText('old')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Secret')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '绑定' })).toBeVisible();
});
