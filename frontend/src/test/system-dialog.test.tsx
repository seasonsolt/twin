import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router';
import { Settings2 } from 'lucide-react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AccountMenu } from '../components/ui';
import { SystemDialog } from '../features/admin/SystemDialog';
import { useSystem, type SystemState } from '../stores/system';
import { useAuth } from '../stores/auth';

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
    features: {
      work: {
        label: '工作',
        enabled: true,
        changed_at: null,
        changed_by: null,
      },
      ledger: {
        label: '承诺账本',
        enabled: true,
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
    editable_models: [
      {
        name: 'llm',
        section: '[llm]',
        use: '整理记忆、校对转写',
        base_url: 'https://llm.example.com/v1',
        model: 'm-test',
        locked: null,
        custom: false,
        changed_at: null,
        changed_by: null,
      },
      {
        name: 'embed',
        section: '[embed]',
        use: '检索向量',
        base_url: 'http://127.0.0.1:18791/v1',
        model: 'bge-m3',
        locked: null,
        custom: false,
        changed_at: null,
        changed_by: null,
      },
    ],
    keys: [
      { env: 'TWIN_LLM_KEY', use: '文字模型', set: true },
      { env: 'TWIN_TTS_KEY', use: '朗读服务', set: false },
    ],
    env_file: '.env',
    audit: [],
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
        const feature = /\/features\/(\w+)$/.exec(url)?.[1] as
          'work' | 'ledger' | undefined;
        if (feature && state.features)
          state = {
            ...state,
            features: {
              ...state.features,
              [feature]: {
                ...state.features[feature],
                enabled: (body as { enabled: boolean }).enabled,
              },
            },
          };
        const env = /\/keys\/(\w+)$/.exec(url)?.[1];
        if (env)
          state = {
            ...state,
            keys: state.keys.map((key) =>
              key.env === env
                ? { ...key, set: 'value' in (body as object) }
                : key,
            ),
            audit: [
              {
                at: '2026-10-18T02:00:00+00:00',
                by: 'zhangxun',
                action: 'key',
                env,
                set: 'value' in (body as object),
              },
            ],
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

it('replaces a key in an empty password field and never shows its value', async () => {
  const user = userEvent.setup();
  show('tokens');
  const keys = await screen.findByRole('table', { name: '密钥' });
  await user.click(
    within(keys).getByRole('button', { name: '设置 TWIN_TTS_KEY' }),
  );
  const form = screen.getByRole('form', { name: '设置 TWIN_TTS_KEY' });
  const field = within(form).getByLabelText('TWIN_TTS_KEY');
  expect(field).toHaveAttribute('type', 'password');
  expect(field).toHaveValue('');
  expect(within(form).getByRole('button', { name: '保存' })).toBeDisabled();
  await user.type(field, 'sk-secret-test');
  await user.click(within(form).getByRole('button', { name: '保存' }));
  await vi.waitFor(() =>
    expect(puts).toEqual([
      {
        url: '/api/admin/system/keys/TWIN_TTS_KEY',
        body: { value: 'sk-secret-test' },
      },
    ]),
  );
  // The form closes, the table says it is set, and the value appears nowhere.
  await vi.waitFor(() =>
    expect(screen.queryByLabelText('TWIN_TTS_KEY')).toBeNull(),
  );
  expect(within(keys).getAllByText('已设置')).toHaveLength(2);
  expect(document.body).not.toHaveTextContent('sk-secret-test');
  expect(screen.getByText(/zhangxun 设置了 TWIN_TTS_KEY/)).toBeInTheDocument();

  await user.click(
    within(keys).getByRole('button', { name: '更换 TWIN_LLM_KEY' }),
  );
  await user.click(screen.getByRole('button', { name: '移除这个密钥' }));
  await vi.waitFor(() =>
    expect(puts.at(-1)).toEqual({
      url: '/api/admin/system/keys/TWIN_LLM_KEY',
      body: {},
    }),
  );
});

it('points a model elsewhere behind one button, and warns before changing the embedding model', async () => {
  const user = userEvent.setup();
  show('tokens');
  await user.click(
    await screen.findByRole('button', { name: '修改地址和模型' }),
  );
  const form = screen.getByRole('form', { name: '修改 [llm]' });
  const name = within(form).getByLabelText('模型名');
  expect(name).toHaveValue('m-test');
  await user.clear(name);
  await user.type(name, 'm-new');
  await user.click(
    within(form).getByRole('button', { name: '保存并立即生效' }),
  );
  await vi.waitFor(() =>
    expect(puts).toEqual([
      {
        url: '/api/admin/system/models/llm',
        body: { base_url: 'https://llm.example.com/v1', model: 'm-new' },
      },
    ]),
  );
  await user.click(screen.getByRole('button', { name: /向量服务/ }));
  await user.click(
    await screen.findByRole('button', { name: '修改地址和模型' }),
  );
  expect(screen.getByText(/重新生成/)).toBeInTheDocument();
});

it('switches work off for everyone at once, and never chat', async () => {
  const user = userEvent.setup();
  useAuth.setState({
    identity: {
      email: null,
      admin: true,
      auth_enabled: false,
      features: { work: true, ledger: true },
    },
  });
  show('features');
  const chat = await screen.findByRole('switch', { name: '聊天' });
  expect(chat).toBeChecked();
  expect(chat).toBeDisabled();
  await user.click(screen.getByRole('switch', { name: '工作' }));
  await vi.waitFor(() =>
    expect(screen.getByRole('switch', { name: '工作' })).not.toBeChecked(),
  );
  expect(puts).toEqual([
    { url: '/api/admin/system/features/work', body: { enabled: false } },
  ]);
  // The menu hides it without signing in again.
  expect(useAuth.getState().identity?.features).toEqual({
    work: false,
    ledger: true,
  });
  expect(
    screen.getByRole('button', { name: /功能.*关闭 1 项/ }),
  ).toBeInTheDocument();
});

it('keeps the system settings in the account menu and marks the account button when a service fails', async () => {
  const user = userEvent.setup();
  const open = vi.fn();
  render(
    <AccountMenu
      name="张三"
      detail="管理员"
      groups={[
        [
          {
            key: 'system',
            label: '系统设置',
            icon: Settings2,
            alert: '1 项服务异常',
            onSelect: open,
          },
        ],
        [],
      ]}
    />,
  );
  const account = screen.getByRole('button', { name: '账户（1 项服务异常）' });
  await user.click(account);
  const menu = screen.getByRole('dialog', { name: '账户' });
  expect(within(menu).getByText('张三')).toBeVisible();
  expect(within(menu).getByText('管理员')).toBeVisible();
  await user.click(
    within(menu).getByRole('button', { name: '系统设置（1 项服务异常）' }),
  );
  expect(open).toHaveBeenCalledOnce();
  expect(screen.queryByRole('dialog', { name: '账户' })).toBeNull();
});
