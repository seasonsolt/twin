import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router';
import { Settings2 } from 'lucide-react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { RailButton } from '../components/ui';
import { SystemDialog } from '../features/admin/SystemDialog';
import { useSystem, type SystemState } from '../stores/system';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
const json = (value: unknown) =>
  new Response(JSON.stringify(value), { status: 200 });

const NOW = 1_800_000_000;
const hours = Array.from({ length: 24 }, (_, i) => ({
  start: NOW - (24 - i) * 3600,
  checks: 60,
  failures: 0,
}));
const service = (key: string, name: string, ok: boolean | null) => ({
  key,
  name,
  enabled: true,
  address: '127.0.0.1:18790',
  latest:
    ok === null
      ? null
      : {
          at: NOW - 30,
          ok,
          latency_ms: 12,
          reason: ok ? null : '隧道未连接或服务未启动（连接被拒绝）',
          version: '1.2',
          device: 'cuda:0',
          busy: false,
          model: null,
          embeddings_ms: null,
        },
  since: NOW - 600,
  checks: 1440,
  failures: ok ? 0 : 10,
  availability: ok ? 1 : 0.99,
  first_at: NOW - 86400,
  last_failure: null,
  buckets: hours,
});

let state: SystemState;
let puts: { url: string; body: unknown }[];
beforeEach(() => {
  puts = [];
  useSystem.setState({ data: null, error: '' });
  state = {
    now: NOW,
    interval: 60,
    window: 86400,
    services: [
      service('asr', '转写服务', true),
      service('embed', '文本向量服务', false),
    ],
    switches: {
      tts: {
        configured: true,
        enabled: true,
        missing: null,
        changed_at: null,
        changed_by: null,
      },
      video: {
        configured: false,
        enabled: false,
        missing: 'twin.toml 里没有配置 [video]',
        changed_at: null,
        changed_by: null,
      },
    },
    config: {
      embed: [['模型', 'bge-m3']],
      asr: [['接口', '命令']],
      tts: [['模型', 'tts-test']],
      video: [['接口', '未配置']],
    },
    models: [
      {
        use: '整理记忆、校对转写',
        section: '[llm]',
        provider: 'OpenAI 兼容',
        model: 'm-test',
        address: 'llm.example.com',
        external: true,
      },
    ],
    keys: [
      { env: 'TWIN_LLM_KEY', use: '文字模型', set: true },
      { env: 'TWIN_TTS_KEY', use: '朗读服务', set: false },
    ],
    quota: {
      limit: 1000,
      hours: 24,
      used: 250,
      exhausted: false,
      resets_at: null,
      custom: false,
      default_limit: 1000,
      default_hours: 24,
    },
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const body: unknown = JSON.parse(String(init.body));
        puts.push({ url, body });
        if (url === '/api/admin/system/switches/tts')
          state = {
            ...state,
            switches: {
              ...state.switches,
              tts: {
                ...state.switches.tts,
                enabled: (body as { enabled: boolean }).enabled,
              },
            },
          };
        return json(state);
      }
      if (url.startsWith('/api/admin/system')) return json(state);
      throw new Error(url);
    }),
  );
});
afterEach(() => vi.restoreAllMocks());

function Where() {
  const location = useLocation();
  return (
    <output aria-label="地址">{location.pathname + location.search}</output>
  );
}

const show = (section = 'monitor') =>
  render(
    <MemoryRouter initialEntries={[`/team?tab=x&system=${section}`]}>
      <SystemDialog />
      <Where />
    </MemoryRouter>,
  );

it('opens over the page at the section in the address, and closing leaves the page as it was', async () => {
  show();
  const dialog = await screen.findByRole('dialog', { name: '系统' });
  expect(await within(dialog).findByText('1 项服务异常')).toBeInTheDocument();
  // The failing service is flagged in the menu; everything else stays quiet.
  expect(
    within(dialog).getByRole('button', { name: /监控.*1 项异常/ }),
  ).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: /文本向量服务/ }));
  expect(screen.getByLabelText('地址')).toHaveTextContent(
    '/team?tab=x&system=embed',
  );
  expect(
    within(dialog).getByRole('button', { name: /向量服务/, current: 'page' }),
  ).toBeInTheDocument();
  fireEvent.click(within(dialog).getAllByRole('button', { name: '关闭' })[0]);
  expect(screen.getByLabelText('地址')).toHaveTextContent('/team?tab=x');
  expect(screen.getByLabelText('地址')).not.toHaveTextContent('system');
});

it('switches speech off at once, and explains what video still needs', async () => {
  show('tts');
  const toggle = await screen.findByRole('switch', { name: '启用朗读' });
  expect(toggle).toBeChecked();
  fireEvent.click(toggle);
  await vi.waitFor(() =>
    expect(screen.getByRole('switch', { name: '启用朗读' })).not.toBeChecked(),
  );
  expect(puts).toEqual([
    { url: '/api/admin/system/switches/tts', body: { enabled: false } },
  ]);
  fireEvent.click(screen.getByRole('button', { name: /视频服务/ }));
  expect(
    await screen.findByText('twin.toml 里没有配置 [video]'),
  ).toBeInTheDocument();
  expect(screen.queryByRole('switch', { name: '启用口型视频' })).toBeNull();
});

it('names the keys without their values and saves the token quota', async () => {
  show('tokens');
  const keys = await screen.findByRole('table', { name: '密钥' });
  expect(within(keys).getByText('TWIN_LLM_KEY')).toBeInTheDocument();
  expect(within(keys).getByText('已设置')).toBeInTheDocument();
  expect(within(keys).getByText('未设置')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('每人 token 上限'), {
    target: { value: '5000' },
  });
  fireEvent.change(screen.getByLabelText('统计时长'), {
    target: { value: '6' },
  });
  fireEvent.click(screen.getByRole('button', { name: '保存' }));
  await vi.waitFor(() =>
    expect(puts).toEqual([
      {
        url: '/api/admin/system/quota',
        body: { batch_tokens: 5000, batch_hours: 6 },
      },
    ]),
  );
});

it('marks the rail entry when a service fails', () => {
  render(
    <RailButton
      icon={Settings2}
      label="系统"
      alert="1 项服务异常"
      onClick={() => {}}
    />,
  );
  expect(
    screen.getByRole('button', { name: '系统（1 项服务异常）' }),
  ).toBeInTheDocument();
});
