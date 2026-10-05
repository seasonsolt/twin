import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { useReducedMotion } from 'motion/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Identity } from '../pages/Identity';
import { useStatus } from '../stores/status';
import type { AvatarSpec } from '../features/playback/types';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: vi.fn(),
}));
const spec: AvatarSpec = {
  schema_version: 1,
  avatar_id: 'configured-avatar',
  label: 'API形象专属标签',
  palette: {
    skin: '#abcdef',
    hair: '#123456',
    background: '#fedcba',
    outfit: '#987654',
    accent: '#112233',
  },
  mouth_states: 4,
  stylized: true,
};
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status });
let fetcher: ReturnType<typeof vi.fn>;
let failAvatar: boolean;
let failIdentity: boolean;
let previous: ReturnType<typeof useStatus.getState>;
const setup = () =>
  render(
    <MemoryRouter initialEntries={['/identity']}>
      <Identity />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.mocked(useReducedMotion).mockReturnValue(false);
  previous = useStatus.getState();
  useStatus.setState({ data: null, error: null });
  failAvatar = failIdentity = false;
  fetcher = vi.fn((path: string) =>
    Promise.resolve(
      path === '/api/identity'
        ? failIdentity
          ? json({ detail: '身份加载暂不可用' }, 503)
          : json({
              name: '配置姓名',
              aliases: ['别名甲', '别名乙'],
              voice: 'configured-voice',
              avatar: 'configured-avatar',
              egress: [
                {
                  kind: 'api-llm-kind',
                  provider: 'api-provider',
                  host: 'model.example.test',
                  external: true,
                  declared: true,
                },
                {
                  kind: 'api-embed-kind',
                  provider: 'local-provider',
                  host: null,
                  external: false,
                  declared: false,
                },
                {
                  kind: 'api-judge-kind',
                  provider: 'judge-provider',
                  host: 'judge.example.test',
                  external: true,
                  declared: false,
                },
              ],
            })
        : failAvatar
          ? json({ detail: '媒体预览暂不可用' }, 503)
          : json({ available: false, label: 'API媒体标签', avatar: spec }),
    ),
  );
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => {
  useStatus.setState(previous);
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it('renders configured identity, exact API egress kinds/providers/hosts and a closed-mouth preset avatar', async () => {
  setup();
  expect(await screen.findByText('配置姓名')).toBeVisible();
  expect(screen.getByText('别名甲、别名乙')).toBeVisible();
  expect(screen.getByText('configured-voice（预置音色）')).toBeVisible();
  expect(screen.getByText('configured-avatar（风格化插画）')).toBeVisible();
  const rows = within(
    screen.getByRole('table', { name: '出境状态' }),
  ).getAllByRole('row');
  expect(rows).toHaveLength(4);
  expect(within(rows[1]).getByText('api-llm-kind')).toBeVisible();
  expect(within(rows[1]).getByText('api-provider')).toBeVisible();
  expect(within(rows[1]).getByText('model.example.test')).toBeVisible();
  expect(within(rows[1]).getByText('外部')).toBeVisible();
  expect(within(rows[1]).getByText('声明')).toBeVisible();
  expect(within(rows[2]).getByText('本机')).toBeVisible();
  expect(within(rows[2]).getByText('推断')).toBeVisible();
  expect(within(rows[2]).getByText('未知')).toBeVisible();
  expect(within(rows[3]).getByText('api-judge-kind')).toBeVisible();
  const avatar = await screen.findByRole('img', { name: '风格化插画' });
  expect(avatar).toHaveAttribute('data-mouth-level', '0');
  expect(avatar.querySelector('rect')).toHaveAttribute('fill', '#fedcba');
  expect(screen.getByText('API形象专属标签')).toBeVisible();
  expect(
    screen.getByText('本版本不支持真人声音复刻或照片驱动形象。'),
  ).toBeVisible();
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(
    fetcher.mock.calls.every(([, options]) => options.method === 'GET'),
  ).toBe(true);
});

it('keeps AI labels empty before status arrives and uses only API label text thereafter', async () => {
  const view = setup();
  await screen.findByText('配置姓名');
  expect(
    screen.queryByText(/AI 合成|模拟推演|不代表本人意见/),
  ).not.toBeInTheDocument();
  await act(async () => {
    useStatus.setState({
      data: {
        ...({} as NonNullable<typeof previous.data>),
        labels: {
          explicit: 'API显式身份标识',
          disclaimer: 'API免责声明',
          chat_notice: 'API聊天提示',
        },
      },
    });
  });
  expect(screen.getByText('API显式身份标识')).toBeVisible();
  expect(screen.getByText('API形象专属标签')).toBeVisible();
  view.unmount();
});

it('does not blink with reduced motion, never moves the mouth, and cleans up timers', async () => {
  vi.mocked(useReducedMotion).mockReturnValue(true);
  const view = setup();
  const avatar = await screen.findByRole('img');
  vi.useFakeTimers();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10_000);
  });
  expect(avatar).toHaveAttribute('data-mouth-level', '0');
  expect(avatar.querySelector('[data-eye]')).toHaveAttribute('ry', '7');
  view.unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it('allows blinking otherwise and cancels it on unmount', async () => {
  vi.spyOn(Math, 'random').mockReturnValue(0);
  vi.useFakeTimers();
  const view = setup();
  await act(async () => {});
  const avatar = screen.getByRole('img');
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  expect(avatar.querySelector('[data-eye]')).toHaveAttribute('ry', '1');
  expect(avatar).toHaveAttribute('data-mouth-level', '0');
  await act(async () => {
    await vi.advanceTimersByTimeAsync(140);
  });
  expect(avatar.querySelector('[data-eye]')).toHaveAttribute('ry', '7');
  view.unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it('keeps identity readable when media fails and retries the avatar preview', async () => {
  failAvatar = true;
  const user = userEvent.setup();
  setup();
  expect(await screen.findByText('配置姓名')).toBeVisible();
  expect(screen.getByRole('alert')).toHaveTextContent('媒体预览暂不可用');
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  failAvatar = false;
  await user.click(screen.getByRole('button', { name: '重试预览' }));
  expect(await screen.findByRole('img')).toBeVisible();
});

it('shows identity load errors with retry and aborts both reads on unmount', async () => {
  failIdentity = true;
  const user = userEvent.setup();
  const view = setup();
  expect(await screen.findByText('身份加载暂不可用')).toBeVisible();
  failIdentity = false;
  await user.click(screen.getByRole('button', { name: '重试加载' }));
  expect(await screen.findByText('配置姓名')).toBeVisible();
  view.unmount();
  expect(
    fetcher.mock.calls.every(([, options]) => options.signal.aborted),
  ).toBe(true);
});
