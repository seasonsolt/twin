import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
  clock,
  GpuStatus,
  type GpuCheck,
  type GpuService,
  type GpuState,
} from '../features/admin/GpuStatus';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const NOW = 1_760_680_000;
const check = (change: Partial<GpuCheck> = {}): GpuCheck => ({
  at: NOW,
  ok: true,
  latency_ms: 12,
  reason: null,
  version: '1.2',
  device: 'cuda',
  busy: false,
  model: null,
  embeddings_ms: null,
  ...change,
});
const service = (change: Partial<GpuService> = {}): GpuService => ({
  key: 'asr',
  name: '转写服务',
  address: '127.0.0.1:18790',
  latest: check(),
  since: NOW - 7200,
  checks: 120,
  failures: 0,
  availability: 1,
  first_at: NOW - 7200,
  last_failure: null,
  buckets: Array.from({ length: 24 }, (_, k) => ({
    start: NOW - 86400 + k * 3600,
    checks: k >= 22 ? 60 : 0,
    failures: 0,
  })),
  ...change,
});
let state: GpuState;
let requests: string[];
beforeEach(() => {
  requests = [];
  state = { now: NOW, interval: 60, window: 86400, services: [service()] };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      requests.push(url);
      if (url.startsWith('/api/admin/gpu')) return json(state);
      throw new Error(url);
    }),
  );
});
afterEach(() => vi.restoreAllMocks());

it('shows a healthy service with its version, device, load and record', async () => {
  render(<GpuStatus />);
  const item = (await screen.findByText('转写服务')).closest('li')!;
  expect(within(item).getByText('正常')).toBeInTheDocument();
  expect(within(item).getByText('127.0.0.1:18790')).toBeInTheDocument();
  expect(
    within(item).getByText('版本 1.2 · cuda · 空闲 · 响应 12 ms'),
  ).toBeInTheDocument();
  expect(item).toHaveTextContent(
    '最近 2 小时可用率 100%（120 次检查，0 次失败） · 期间没有失败',
  );
  expect(
    within(item).getByRole('img', { name: '转写服务每小时检查结果' }).children,
  ).toHaveLength(24);
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(requests).toEqual(['/api/admin/gpu']);
});

it('says in Chinese why a service is down, since when, and how stable it was', async () => {
  state.services = [
    service({
      latest: check({
        ok: false,
        reason: '隧道未连接或服务未启动（连接被拒绝）',
        version: null,
        device: null,
        busy: null,
        latency_ms: null,
      }),
      since: NOW - 1800,
      checks: 1440,
      failures: 30,
      availability: 1410 / 1440,
      first_at: NOW - 86400,
      last_failure: { at: NOW, reason: '隧道未连接或服务未启动（连接被拒绝）' },
    }),
    service({
      key: 'embed',
      name: '文本向量服务',
      address: '127.0.0.1:18791',
      latest: check({
        model: 'BAAI/bge-m3',
        version: '0.3',
        busy: null,
        embeddings_ms: 30,
      }),
    }),
  ];
  render(<GpuStatus />);
  const down = (await screen.findByText('转写服务')).closest('li')!;
  expect(within(down).getByText('异常')).toBeInTheDocument();
  expect(within(down).getByRole('alert')).toHaveTextContent(
    `隧道未连接或服务未启动（连接被拒绝）（自 ${clock(NOW - 1800)} 起）`,
  );
  expect(down).toHaveTextContent(
    '最近 1 天可用率 97.9%（1440 次检查，30 次失败）',
  );
  expect(down).toHaveTextContent(
    `最近一次失败 ${clock(NOW)}：隧道未连接或服务未启动（连接被拒绝）`,
  );
  const up = screen.getByText('文本向量服务').closest('li')!;
  expect(within(up).getByText('正常')).toBeInTheDocument();
  expect(up).toHaveTextContent('BAAI/bge-m3');
  expect(up).toHaveTextContent('向量 30 ms');
});

it('checks again on request', async () => {
  render(<GpuStatus />);
  await screen.findByText('正常');
  state.services = [
    service({
      latest: check({ ok: false, reason: '服务返回错误（HTTP 500）' }),
    }),
  ];
  fireEvent.click(screen.getByRole('button', { name: '立即检查' }));
  expect(await screen.findByText('异常')).toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent(
    '服务返回错误（HTTP 500）',
  );
  expect(requests).toEqual(['/api/admin/gpu', '/api/admin/gpu?refresh=true']);
});

it('stays out of the way when no GPU service is configured', async () => {
  state.services = [];
  const { container } = render(<GpuStatus />);
  await vi.waitFor(() => expect(requests).toHaveLength(1));
  expect(container).toBeEmptyDOMElement();
});

it('reports when the status cannot be read', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => json({ detail: '仅管理员可查看 GPU 服务状态' }, 403)),
  );
  render(<GpuStatus />);
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '仅管理员可查看 GPU 服务状态',
  );
});
