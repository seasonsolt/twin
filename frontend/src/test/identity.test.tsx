import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, expect, it, vi } from 'vitest';
import { About } from '../pages/About';
import { useStatus, type Status } from '../stores/status';

const identity = {
  name: '配置姓名',
  about: '喜欢徒步',
  name_source: 'config',
  aliases: [],
  voice: 'configured-voice',
  avatar: 'default',
};
const spec = {
  schema_version: 1,
  avatar_id: 'default',
  label: 'API形象标签',
  mouth_states: 4,
  stylized: true,
  palette: {
    skin: '#abcdef',
    hair: '#123456',
    background: '#fedcba',
    outfit: '#987654',
    accent: '#112233',
  },
};
let fetcher: ReturnType<typeof vi.fn>;
let failAvatar: boolean;
let failIdentity: boolean;
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const status: Status = {
  target_name: identity.name,
  counts: { sources: 1, items: 0 },
  llm: { provider: 'mock', model: 'mock' },
  embed: { provider: 'local' },
  labels: {
    explicit: 'API标签',
    disclaimer: 'API说明',
    chat_notice: 'API聊天',
  },
  egress: [
    {
      kind: 'tts',
      provider: 'remote',
      host: 'speech.test',
      external: true,
      declared: true,
    },
    {
      kind: 'embed',
      provider: 'local',
      host: 'localhost',
      external: false,
      declared: false,
    },
  ],
};
beforeEach(() => {
  failAvatar = failIdentity = false;
  useStatus.setState({ data: status, error: null });
  fetcher = vi.fn((path: string, options: RequestInit) =>
    Promise.resolve(
      path === '/api/identity'
        ? failIdentity
          ? json({ detail: '身份暂不可用' }, 503)
          : json(
              options.method === 'PUT'
                ? {
                    ...identity,
                    ...JSON.parse(options.body as string),
                    name_source: 'user',
                  }
                : identity,
            )
        : path === '/api/media/capabilities'
          ? failAvatar
            ? json({ detail: '预览暂不可用' }, 503)
            : json({ available: false, avatar: spec })
          : path === '/api/persona/items?include_rejected=false'
            ? json([])
            : path === '/api/persona/coverage'
              ? json({ facets: [], suggestions: [], kind_labels: {} })
              : json(status),
    ),
  );
  vi.stubGlobal('fetch', fetcher);
});
const setup = () =>
  render(
    <MemoryRouter initialEntries={['/about']}>
      <About />
    </MemoryRouter>,
  );

it('edits name/about inline and saves with X-Twin, previews a closed-mouth avatar and names external services plainly', async () => {
  setup();
  await screen.findByDisplayValue(identity.name);
  expect(screen.getByLabelText('介绍一下自己')).toHaveValue(identity.about);
  expect(screen.getByLabelText('名字')).toHaveAttribute('maxlength', '20');
  expect(screen.getByLabelText('介绍一下自己')).toHaveAttribute(
    'maxlength',
    '200',
  );
  expect(screen.getByText('音色：configured-voice（预置音色）')).toBeVisible();
  expect(screen.getByText('朗读：speech.test')).toBeVisible();
  expect(screen.queryByText(/localhost/)).not.toBeInTheDocument();
  const avatar = await screen.findByRole('img', { name: '风格化插画' });
  expect(avatar).toHaveAttribute('data-mouth-level', '0');
  expect(screen.getByText('API形象标签')).toBeVisible();
  fireEvent.change(screen.getByLabelText('名字'), {
    target: { value: '新名字' },
  });
  fireEvent.change(screen.getByLabelText('介绍一下自己'), {
    target: { value: '新介绍' },
  });
  fireEvent.click(screen.getByRole('button', { name: '保存' }));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([, options]) => options.method === 'PUT'),
    ).toBe(true),
  );
  const options = fetcher.mock.calls.find(
    ([, options]) => options.method === 'PUT',
  )![1] as RequestInit;
  expect(JSON.parse(options.body as string)).toEqual({
    name: '新名字',
    about: '新介绍',
  });
  expect(new Headers(options.headers).get('X-Twin')).toBe('1');
});
it('describes external services using plain names, never provider ids or local services', async () => {
  useStatus.setState({
    data: {
      ...status,
      egress: [
        ...status.egress,
        {
          kind: 'llm',
          provider: 'openai_compat',
          host: 'api.example.com',
          external: true,
          declared: false,
        },
        {
          kind: 'embed',
          provider: 'openai_compat',
          host: 'api.cloudflare.com',
          external: true,
          declared: false,
        },
        {
          kind: 'asr',
          provider: 'openai_compat',
          host: 'recognition.test',
          external: true,
          declared: false,
        },
        {
          kind: 'video',
          provider: 'remote',
          host: 'gpu-box',
          external: true,
          declared: false,
        },
        {
          kind: 'judge',
          provider: 'claude_cli',
          host: null,
          external: true,
          declared: false,
        },
      ],
    },
  });
  setup();
  await screen.findByDisplayValue(identity.name);
  for (const text of [
    '大模型：api.example.com',
    '向量：api.cloudflare.com',
    '朗读：speech.test',
    '语音识别：recognition.test',
    '视频生成：gpu-box',
    '回答检查：地址未提供',
  ])
    expect(screen.getByText(text)).toBeVisible();
  expect(
    screen.queryByText(/openai_compat|claude_cli|localhost/),
  ).not.toBeInTheDocument();
});

it('keeps identity editable when the preview fails and supports retry', async () => {
  failAvatar = true;
  setup();
  await screen.findByDisplayValue(identity.name);
  expect(screen.getByRole('alert')).toHaveTextContent('预览暂不可用');
  failAvatar = false;
  fireEvent.click(screen.getByRole('button', { name: '重试预览' }));
  expect(await screen.findByRole('img')).toBeVisible();
});
it('retries identity failures and aborts reads on unmount', async () => {
  failIdentity = true;
  const view = setup();
  await screen.findByText('身份暂不可用');
  failIdentity = false;
  fireEvent.click(screen.getByRole('button', { name: '重试加载' }));
  await screen.findByDisplayValue(identity.name);
  view.unmount();
  expect(
    fetcher.mock.calls
      .filter(([, options]) => options.signal)
      .every(([, options]) => options.signal.aborted),
  ).toBe(true);
});
it('does not hard-code AI labels while status is unavailable', async () => {
  useStatus.setState({ data: null });
  setup();
  await screen.findByDisplayValue(identity.name);
  expect(screen.queryByText(/AI 合成|不代表本人意见/)).not.toBeInTheDocument();
});
