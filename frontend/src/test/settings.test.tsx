import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router';
import { Settings2 } from 'lucide-react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AccountMenu, ConfirmProvider } from '../components/ui';
import { Settings } from '../features/settings/Settings';
import {
  useSystem,
  type Components,
  type ParamState,
  type SystemState,
} from '../stores/system';
import { useAuth } from '../stores/auth';
import { usePersonas } from '../stores/personas';
import type { LibraryState } from '../pages/Library';

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

const v6 = { schema: 4, prompt: 'persona-v6', taxonomy: 'v2' };
const v7 = { schema: 4, prompt: 'persona-v7', taxonomy: 'v2' };
const param = (
  key: string,
  label: string,
  value: boolean | number,
  unit = '',
): ParamState => ({
  key,
  label,
  help: `${label}的说明`,
  unit,
  value,
  default: value,
  custom: false,
  changed_at: null,
  changed_by: null,
});

let state: SystemState;
let library: LibraryState;
let components: Components;
let puts: { url: string; body: unknown }[];
let posts: { url: string; body: unknown }[];
let teamRefusal: string;
let libraryFails: boolean;
beforeEach(() => {
  puts = [];
  posts = [];
  teamRefusal = '';
  libraryFails = false;
  useSystem.setState({
    data: null,
    error: '',
    components: null,
    componentsError: '',
  });
  components = {
    kernel: {
      version: v7,
      twins: [
        {
          id: 'default',
          name: '林舟',
          version: v7,
          built: v6,
          scope: 'full',
          pending_chunks: 512,
          state: 'awaiting_confirmation',
        },
        {
          id: 'p2',
          name: '陈默',
          version: v7,
          built: v7,
          scope: 'none',
          pending_chunks: 0,
          state: 'ready',
        },
      ],
    },
    ledger: {
      version: 'ledger-v1',
      enabled: true,
      twins: [
        {
          id: 'default',
          name: '林舟',
          meetings: 4,
          pending: 2,
          running: false,
        },
        { id: 'p2', name: '陈默', meetings: 1, pending: 0, running: false },
      ],
    },
    library: { attribution: 'attribution-v2', cleanup: 'cleanup-v1' },
  };
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
    params: [
      param('kernel.auto_rebuild', '自动升级记忆内核', true),
      param('kernel.max_auto_rebuild_chunks', '自动升级上限', 400, '段'),
      param('library.max_pending', '每人排队转写上限', 20, '条'),
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
  library = {
    recordings: [],
    pending: 3,
    max_pending: 20,
    asr: true,
    capacity: {
      free_bytes: 80 * 1024 ** 3,
      arriving_bytes: 2 * 1024 ** 3,
      arriving: 2,
      headroom_bytes: 20 * 1024 ** 3,
    },
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        posts.push({ url, body: JSON.parse(String(init.body)) as unknown });
        components = {
          ...components,
          kernel: {
            ...components.kernel,
            twins: components.kernel.twins.map((twin) =>
              twin.scope === 'none' ? twin : { ...twin, state: 'queued' },
            ),
          },
        };
        return json({ queued: ['default'], ...components });
      }
      if (url === '/api/library')
        return libraryFails
          ? new Response(JSON.stringify({ detail: '录音库暂时读不出来' }), {
              status: 500,
            })
          : json(library);
      if (url === '/api/admin/system/components') return json(components);
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
        if (url === '/api/admin/system/team' && teamRefusal)
          return new Response(JSON.stringify({ detail: teamRefusal }), {
            status: 400,
          });
        if (url === '/api/admin/system/team')
          state = {
            ...state,
            team_name: (body as { name: string }).name.trim() || null,
          };
        const key = /\/params\/([\w.]+)$/.exec(url)?.[1];
        if (key)
          state = {
            ...state,
            params: state.params?.map((p) =>
              p.key === key
                ? {
                    ...p,
                    value: (body as { value?: number }).value ?? p.default,
                    custom: 'value' in (body as object),
                  }
                : p,
            ),
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
beforeEach(() => {
  useAuth.setState({
    identity: { email: null, admin: true, auth_enabled: false },
  });
  usePersonas.setState({ items: [], id: '' });
});
afterEach(() => vi.restoreAllMocks());

function Where() {
  const location = useLocation();
  return (
    <output aria-label="地址">{location.pathname + location.search}</output>
  );
}

const show = (section = 'status', key = 'settings') =>
  render(
    <ConfirmProvider>
      <MemoryRouter initialEntries={[`/team?tab=x&${key}=${section}`]}>
        <Settings />
        <Where />
      </MemoryRouter>
    </ConfirmProvider>,
  );

it('opens over the page at the section in the address, and closing leaves the page as it was', async () => {
  show();
  const dialog = await screen.findByRole('dialog', { name: '设置' });
  expect(await within(dialog).findByText('1 项服务异常')).toBeInTheDocument();
  // The failing service is flagged in the menu; everything else stays quiet.
  expect(
    within(dialog).getByRole('button', { name: /状态.*1 项异常/ }),
  ).toBeInTheDocument();
  // Each part of the system opens its own page, which is not in the menu: the status stays marked, with a way back.
  fireEvent.click(within(dialog).getByRole('button', { name: /^向量服务/ }));
  expect(screen.getByLabelText('地址')).toHaveTextContent(
    '/team?tab=x&settings=embed',
  );
  expect(
    within(dialog).getByRole('button', { name: /状态/, current: 'page' }),
  ).toBeInTheDocument();
  expect(
    within(dialog).queryByRole('button', { name: /^向量服务/ }),
  ).toBeNull();
  fireEvent.click(within(dialog).getByRole('button', { name: '返回状态' }));
  expect(screen.getByLabelText('地址')).toHaveTextContent(
    '/team?tab=x&settings=status',
  );
  fireEvent.click(within(dialog).getAllByRole('button', { name: '关闭' })[0]);
  expect(screen.getByLabelText('地址')).toHaveTextContent('/team?tab=x');
  expect(screen.getByLabelText('地址')).not.toHaveTextContent('settings');
});

it('shows where the last day of tokens went, by use, and says when some calls did not report theirs', async () => {
  state = {
    ...state,
    usage: [
      {
        stage: 'proofread',
        calls: 12,
        failures: 1,
        input_tokens: 1_500_000,
        output_tokens: 4_000,
        cached_tokens: 0,
        unknown_calls: 0,
      },
      {
        stage: 'chat.answer.hedge',
        calls: 3,
        failures: 0,
        input_tokens: 0,
        output_tokens: 0,
        cached_tokens: 0,
        unknown_calls: 3,
      },
    ],
  };
  show('models');
  const dialog = await screen.findByRole('dialog', { name: '设置' });
  const table = await within(dialog).findByRole('table', {
    name: '最近 24 小时的 token 用量',
  });
  const rows = within(table).getAllByRole('row');
  expect(rows).toHaveLength(3);
  expect(rows[1]).toHaveTextContent('录音校对');
  expect(rows[1]).toHaveTextContent('12（失败 1）');
  expect(rows[2]).toHaveTextContent('聊天回答 · 抢先重发');
  expect(
    within(dialog).getByText(/有 3 次调用没有报告用量/u),
  ).toBeInTheDocument();
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
  fireEvent.click(screen.getByRole('button', { name: '返回状态' }));
  fireEvent.click(await screen.findByRole('button', { name: /^视频服务/ }));
  expect(
    await screen.findByText('twin.toml 里没有配置 [video]'),
  ).toBeInTheDocument();
  expect(screen.queryByRole('switch', { name: '启用口型视频' })).toBeNull();
});

it('names the keys without their values and saves the token quota', async () => {
  show('models');
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
  show('models');
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
  show('models');
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
  await user.click(screen.getByRole('button', { name: /^状态/ }));
  await user.click(await screen.findByRole('button', { name: /^向量服务/ }));
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

it('keeps the settings in the account menu and marks the account button when a service fails', async () => {
  const user = userEvent.setup();
  const open = vi.fn();
  render(
    <AccountMenu
      name="张三"
      detail="管理员"
      groups={[
        [
          {
            key: 'settings',
            label: '设置',
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
    within(menu).getByRole('button', { name: '设置（1 项服务异常）' }),
  );
  expect(open).toHaveBeenCalledOnce();
  expect(screen.queryByRole('dialog', { name: '账户' })).toBeNull();
});

it('lists what each twin was built on and upgrades every outdated kernel after a confirmation', async () => {
  const user = userEvent.setup();
  show('memory');
  const dialog = await screen.findByRole('dialog', { name: '设置' });
  // The menu says what waits, wherever the dialog opened.
  expect(
    await within(dialog).findByRole('button', { name: /记忆.*2 项可升级/ }),
  ).toBeInTheDocument();
  const kernels = await screen.findByRole('table', {
    name: '各分身的记忆内核',
  });
  expect(within(kernels).getByText('persona-v6 · 分类 v2')).toBeInTheDocument();
  expect(
    within(kernels).getByText('待确认 · 需重新整理 512 段'),
  ).toBeInTheDocument();
  expect(within(kernels).getByText('已是最新')).toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: '升级 陈默 的记忆内核' }),
  ).toBeNull();

  await user.click(
    screen.getByRole('button', { name: '全部升级（1 个分身）' }),
  );
  const confirm = await screen.findByRole('dialog', {
    name: '升级全部分身的记忆内核',
  });
  expect(confirm).toHaveTextContent('共需重新整理 512 段，会调用模型');
  await user.click(within(confirm).getByRole('button', { name: '全部升级' }));
  await vi.waitFor(() =>
    expect(posts).toEqual([
      { url: '/api/admin/system/components/kernel', body: {} },
    ]),
  );
  expect(await within(kernels).findByText('排队中')).toBeInTheDocument();
  expect(screen.getByText('正在升级，完成后这里会更新。')).toBeInTheDocument();

  // One twin's ledger, without asking: it reads only meetings not yet read.
  await user.click(
    await screen.findByRole('button', { name: '整理 林舟 的承诺账本' }),
  );
  await vi.waitFor(() =>
    expect(posts.at(-1)).toEqual({
      url: '/api/admin/system/components/ledger',
      body: { persona_ids: ['default'] },
    }),
  );
});

it('changes a parameter at once, refuses what is not a number, and goes back to twin.toml', async () => {
  const user = userEvent.setup();
  show('library');
  const field = await screen.findByLabelText('每人排队转写上限（条）');
  // Kernel parameters live with the kernel, not here.
  expect(screen.queryByRole('switch', { name: '自动升级记忆内核' })).toBeNull();
  await user.clear(field);
  await user.type(field, 'abc');
  await user.click(screen.getByRole('button', { name: '保存' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('请填数字');
  expect(puts).toEqual([]);
  await user.clear(field);
  await user.type(field, '5');
  await user.click(screen.getByRole('button', { name: '保存' }));
  await vi.waitFor(() =>
    expect(puts).toEqual([
      {
        url: '/api/admin/system/params/library.max_pending',
        body: { value: 5 },
      },
    ]),
  );
  await user.click(
    await screen.findByRole('button', { name: '恢复 twin.toml 的设置' }),
  );
  await vi.waitFor(() => expect(puts.at(-1)?.body).toEqual({}));
  expect(await screen.findByLabelText('每人排队转写上限（条）')).toHaveValue(
    '20',
  );

  await user.click(screen.getByRole('button', { name: /^记忆/ }));
  await user.click(
    await screen.findByRole('switch', { name: '自动升级记忆内核' }),
  );
  await vi.waitFor(() =>
    expect(puts.at(-1)).toEqual({
      url: '/api/admin/system/params/kernel.auto_rebuild',
      body: { value: false },
    }),
  );
});

const waiting = (uploader: string, n: number, from = 0) =>
  Array.from({ length: n }, (_, i) => ({
    id: `${uploader}-${from + i}`,
    filename: `${uploader}-${from + i}.m4a`,
    size: 1,
    kind: 'audio' as const,
    status: 'queued' as const,
    error: '',
    duration_s: null,
    transcribed_s: 0,
    speakers: 0,
    segments: 0,
    created_at: '2026-10-18T02:00:00+00:00',
    people: [],
    unsettled: 0,
    uploader,
  }));

it('shows how much room the recordings have, from the library itself', async () => {
  show('library');
  const dialog = await screen.findByRole('dialog', { name: '设置' });
  // The menu carries it, apart from the services.
  expect(
    within(dialog).getByRole('button', { name: /录音库/, current: 'page' }),
  ).toBeInTheDocument();
  // The whole team's queue, beside the cap each member has.
  expect(await within(dialog).findByText('3 条')).toBeInTheDocument();
  expect(within(dialog).getByText('20 条')).toBeInTheDocument();
  // What is free, less what is arriving and what is kept back.
  expect(within(dialog).getByText('约 58.0 GB')).toBeInTheDocument();
  expect(within(dialog).getByText('安全余量')).toBeInTheDocument();
  expect(within(dialog).getByText('2 项 · 2.0 GB')).toBeInTheDocument();
  // The rules that settle speakers and segments on their own sit with the library they act on.
  expect(await within(dialog).findByText('attribution-v2')).toBeInTheDocument();
});

it('flags the queue only when one member has filled their own, not when the team adds up to the cap', async () => {
  // Twenty waiting in all, but none of the four members has more than five.
  library = {
    ...library,
    recordings: ['a', 'b', 'c', 'd'].flatMap((who) => waiting(who, 5)),
    pending: 20,
  };
  show('library');
  const dialog = await screen.findByRole('dialog', { name: '设置' });
  await within(dialog).findByText('每人上限');
  expect(
    within(dialog).getByRole('button', { name: '录音库' }),
  ).toBeInTheDocument();
  expect(within(dialog).queryByText(/有人排满/)).toBeNull();
});

it('flags the queue in the menu when a member has filled their own', async () => {
  library = {
    ...library,
    recordings: waiting('a', 20),
    pending: 20,
  };
  show('library');
  const dialog = await screen.findByRole('dialog', { name: '设置' });
  await within(dialog).findByText('1 位成员');
  expect(
    within(dialog).getByRole('button', { name: /录音库.*有人排满/ }),
  ).toBeInTheDocument();
});

it('flags the library in the menu when the disk has no room left', async () => {
  library = {
    ...library,
    capacity: { ...library.capacity, free_bytes: 21 * 1024 ** 3 },
  };
  show('library');
  const dialog = await screen.findByRole('dialog', { name: '设置' });
  await within(dialog).findByText('约 0.0 GB');
  expect(
    within(dialog).getByRole('button', { name: /录音库.*空间不足/ }),
  ).toBeInTheDocument();
});

it('says why the library capacity cannot be shown, and reads it again on retry', async () => {
  const user = userEvent.setup();
  libraryFails = true;
  show('library');
  const dialog = await screen.findByRole('dialog', { name: '设置' });
  expect(await within(dialog).findByRole('alert')).toHaveTextContent(
    '录音库暂时读不出来',
  );
  libraryFails = false;
  await user.click(within(dialog).getByRole('button', { name: '重试' }));
  expect(await within(dialog).findByText('3 条')).toBeInTheDocument();
  expect(within(dialog).queryByRole('alert')).toBeNull();
});

it('names the team in the settings, and the side bar and the way in follow at once', async () => {
  const user = userEvent.setup();
  useAuth.setState({
    identity: { email: null, admin: true, auth_enabled: false },
  });
  show('team');
  const field = await screen.findByRole('textbox', { name: '团队名' });
  expect(field).toHaveValue('');
  expect(field).toHaveAttribute('placeholder', '我的团队');
  expect(screen.getByRole('button', { name: '保存' })).toBeDisabled();
  await user.type(field, ' 产品研发部 ');
  await user.click(screen.getByRole('button', { name: '保存' }));
  await vi.waitFor(() =>
    expect(useAuth.getState().identity?.team_name).toBe('产品研发部'),
  );
  expect(puts).toEqual([
    { url: '/api/admin/system/team', body: { name: ' 产品研发部 ' } },
  ]);
  expect(await screen.findByRole('textbox', { name: '团队名' })).toHaveValue(
    '产品研发部',
  );
  await user.click(screen.getByRole('button', { name: '清除' }));
  await vi.waitFor(() =>
    expect(useAuth.getState().identity?.team_name).toBeNull(),
  );
  expect(puts.at(-1)).toEqual({
    url: '/api/admin/system/team',
    body: { name: '' },
  });
});

it('shows what the server said when the team name is refused', async () => {
  const user = userEvent.setup();
  teamRefusal = '团队名不能含控制字符';
  show('team');
  await user.type(await screen.findByRole('textbox', { name: '团队名' }), 'x');
  await user.click(screen.getByRole('button', { name: '保存' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '团队名不能含控制字符',
  );
});

it('says in the recent changes what the team was renamed to', async () => {
  state = {
    ...state,
    audit: [
      {
        at: '2026-10-18T03:00:00+00:00',
        by: 'zhangxun',
        action: 'team_name',
        name: ['产品部', null],
      },
      {
        at: '2026-10-18T02:00:00+00:00',
        by: 'zhangxun',
        action: 'team_name',
        name: [null, '产品部'],
      },
    ],
  };
  show('models');
  expect(await screen.findByText(/把团队名改为 产品部/)).toBeInTheDocument();
  expect(screen.getByText(/清除了团队名/)).toBeInTheDocument();
});

it('opens an old link to the administrators’ settings at the place it moved to', async () => {
  show('upgrades', 'system');
  const dialog = await screen.findByRole('dialog', { name: '设置' });
  expect(
    within(dialog).getByRole('button', { name: /^记忆/, current: 'page' }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText('地址')).toHaveTextContent(
    '/team?tab=x&settings=memory',
  );
});

it('gives a member their own settings and the twin they look after, and nothing of the team or system', async () => {
  useAuth.setState({
    identity: { email: 'lin@example.com', admin: false, auth_enabled: true },
  });
  usePersonas.setState({
    items: [
      {
        id: 'p-lin',
        name: '林舟',
        avatar_url: null,
        sources: 1,
        created_at: '2026-10-18T02:00:00+00:00',
        is_default: false,
        can_manage: true,
      },
    ],
    id: 'p-lin',
  });
  show('look');
  const dialog = await screen.findByRole('dialog', { name: '设置' });
  expect(within(dialog).getByText('分身 · 林舟')).toBeInTheDocument();
  for (const name of ['外观', '账号', '接入', '别名', '数据去向'])
    expect(
      within(dialog).getByRole('button', { name: new RegExp(`^${name}`) }),
    ).toBeInTheDocument();
  for (const name of ['团队', '模型与额度', '状态', '录音库', '记忆'])
    expect(
      within(dialog).queryByRole('button', { name: new RegExp(`^${name}`) }),
    ).toBeNull();
  expect(
    within(dialog).getByRole('radiogroup', { name: '界面主题' }),
  ).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: /^账号/ }));
  expect(within(dialog).getByText('成员')).toBeInTheDocument();
  expect(
    within(dialog).getByRole('button', { name: '退出登录' }),
  ).toBeInTheDocument();
});
