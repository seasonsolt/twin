import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider } from '../components/ui';
import { FIRST_QUESTIONS, SetupCard } from '../features/setup/SetupCard';
import type { IdentityData } from '../features/identity/useIdentity';
import { isSourcesUrl, sourcesPage } from './personaApi';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
const json = (value: unknown) => new Response(JSON.stringify(value));
const identity = {
  name: '林小新',
  about: '',
  aliases: [],
  egress: [],
  onboarding_pending: true,
} as unknown as IdentityData;
const recording = {
  source_id: 'rec',
  title: '周会 10-18',
  status: 'needs_speaker',
  detected_kind_label: '会议录音',
  remembered: 0,
  first_date: null,
  kind: 'audio',
  duration_s: 2520,
};
let rows: Record<string, unknown>[];
let fetcher: ReturnType<typeof vi.fn>;
beforeEach(() => {
  rows = [];
  fetcher = vi.fn(async (path: string, init?: RequestInit) => {
    if (isSourcesUrl(path)) return json(sourcesPage(path, rows));
    if (path === '/api/persona/processing') return json({ state: 'idle' });
    if (path === '/api/persona/sources/rec/speakers')
      return json({
        diarized: true,
        speakers: [
          {
            id: 'S1',
            seconds: 1080,
            suggested: false,
            quote: '这个版本先别上',
            samples: ['/api/persona/sources/rec/samples/0/0'],
          },
          { id: 'S2', seconds: 40, suggested: true, quote: '', samples: [] },
        ],
      });
    if (path === '/api/persona/sources/rec/speaker' && init?.method === 'PUT') {
      rows = [{ ...recording, status: 'remembered', remembered: 23 }];
      return json({});
    }
    if (path === '/api/persona/notes' && init?.method === 'POST') {
      rows = [
        {
          ...recording,
          source_id: 'note',
          title: '笔记',
          status: 'processing',
        },
      ];
      return json({});
    }
    if (path === '/api/persona/items/summary') return json({ total: 23 });
    if (path === '/api/identity/onboarding-complete') return json({});
    if (path === '/api/status') return json({ counts: { sources: 1 } });
    throw new Error(path);
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => {
  vi.restoreAllMocks();
});
function mount(onAsk = vi.fn()) {
  render(
    <ConfirmProvider>
      <MemoryRouter>
        <SetupCard
          name="林小新"
          identity={identity}
          onIdentityChanged={vi.fn()}
          onAsk={onAsk}
        />
      </MemoryRouter>
    </ConfirmProvider>,
  );
  return onAsk;
}
const calls = (path: string) =>
  fetcher.mock.calls.filter(([url]) => url === path);

it('starts with the recording, then asks which speaker is the person and opens the chat once it remembers', async () => {
  rows = [recording];
  const onAsk = mount();
  expect(
    await screen.findByRole('region', { name: '让林小新认识你' }),
  ).toBeVisible();
  expect(await screen.findByText('哪位是你？')).toBeVisible();
  expect(screen.getByText('“这个版本先别上”')).toBeVisible();
  expect(screen.getByText('18 分钟', { exact: false })).toBeVisible();
  expect(screen.getByText('像你')).toBeVisible();
  expect(
    screen.getByRole('button', { name: '播放说话人 1 的片段' }),
  ).toBeVisible();
  // Name is asked once, when the twin is made.
  expect(screen.queryByRole('textbox', { name: /名字/ })).toBeNull();
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: '说话人 1 是我' }));
  const put = calls('/api/persona/sources/rec/speaker')[0][1] as RequestInit;
  expect(JSON.parse(put.body as string)).toEqual({ speakers: ['S1'] });
  expect(
    await screen.findByText(
      '林小新已经记住 23 条关于你的事 · 来自「周会 10-18」',
    ),
  ).toBeVisible();
  expect(calls('/api/identity/onboarding-complete')).toHaveLength(1);
  expect(screen.getByRole('link', { name: '看看记了什么' })).toHaveAttribute(
    'href',
    '/profile?section=memories',
  );
  await user.click(screen.getByRole('button', { name: FIRST_QUESTIONS[1] }));
  expect(onAsk).toHaveBeenCalledWith(FIRST_QUESTIONS[1]);
});

it('says none of the speakers is the person', async () => {
  rows = [recording];
  mount();
  await screen.findByText('哪位是你？');
  await userEvent
    .setup()
    .click(screen.getByRole('button', { name: '都不是我' }));
  await waitFor(() =>
    expect(calls('/api/persona/sources/rec/speaker')).toHaveLength(1),
  );
  const put = calls('/api/persona/sources/rec/speaker')[0][1] as RequestInit;
  expect(JSON.parse(put.body as string)).toEqual({ speakers: [] });
});

it('takes a few written lines in place of a recording', async () => {
  mount();
  const user = userEvent.setup();
  expect(
    await screen.findByRole('region', { name: '添加会议录音' }),
  ).toBeVisible();
  expect(screen.getByText('转写完成后在这里选。')).toBeVisible();
  await user.click(
    screen.getByRole('button', { name: '没有录音？写一段或上传文档' }),
  );
  await user.type(
    screen.getByRole('textbox', { name: '写一段关于你的事' }),
    '我负责排期。',
  );
  await user.click(screen.getByRole('button', { name: '保存' }));
  const post = calls('/api/persona/notes')[0][1] as RequestInit;
  expect(JSON.parse(post.body as string)).toEqual({ text: '我负责排期。' });
  expect(
    await screen.findByText('正在从你说的话里整理，好了会在这里告诉你。'),
  ).toBeVisible();
});
