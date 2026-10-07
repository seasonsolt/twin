import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import { PersonaSwitcher } from '../components/layout/PersonaSwitcher';
import { Twins } from '../pages/Twins';
import { ConfirmProvider } from '../components/ui';
import type { Turn } from '../features/chat/types';
import { useConversation, CHAT_KEY } from '../features/chat/useConversation';
import { useReplyAudio } from '../features/chat/useReplyAudio';
import { useReplyVideos, videoUrl } from '../features/chat/useReplyVideos';
import { useQuestionnaire } from '../features/questionnaire/useQuestionnaire';
import { api } from '../lib/api';
import { uploadMedia } from '../lib/mediaUpload';
import {
  getPersonaId,
  personaKey,
  personaUrl,
  setPersonaId,
} from '../lib/persona';
import { usePersonas, type Persona } from '../stores/personas';
import { useStatus } from '../stores/status';

const B = 'p-bbbbbbbbbb';
const NEW = 'p-cccccccccc';
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const selected = (init?: RequestInit) =>
  new Headers(init?.headers).get('X-Twin-Persona');
let items: Persona[];
let fetcher: ReturnType<typeof vi.fn>;
const reply = {
  reply: '独立回复',
  citations: [],
  confidence: 0.5,
  abstain: true,
  abstain_reason: '',
  retrieved_ids: [],
  cited: [],
};

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  setPersonaId('default');
  items = [
    {
      id: 'default',
      name: '主人',
      sources: 2,
      avatar_url: null,
      created_at: 'now',
      is_default: true,
    },
    {
      id: B,
      name: '朋友',
      sources: 3,
      avatar_url: `/api/media/avatar-image?persona=${B}`,
      created_at: 'now',
      is_default: false,
    },
  ];
  usePersonas.setState({ id: 'default', items: [] });
  useStatus.setState({ data: null, error: null });
  fetcher = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === '/api/whoami')
      return json({ email: null, admin: true, auth_enabled: false });
    const persona =
      items.find((item) => item.id === selected(init)) ?? items[0];
    if (path === '/api/personas') {
      if (init?.method === 'POST') {
        const name = JSON.parse(init.body as string).name;
        const created = {
          ...items[1],
          id: NEW,
          name,
          sources: 0,
          avatar_url: null,
        };
        items.push(created);
        return json(created, 201);
      }
      return json(items);
    }
    if (path.startsWith('/api/personas/') && init?.method === 'DELETE') {
      items = items.filter((item) => item.id !== path.split('/').at(-1));
      return json({ deleted: true });
    }
    if (path === '/api/identity') {
      if (init?.method === 'PUT')
        persona.name = JSON.parse(init.body as string).name;
      return json({
        name: persona.name,
        about: '保留介绍',
        aliases: [],
        name_source: 'user',
        egress: [],
        onboarding_pending: persona.id === NEW,
      });
    }
    if (path === '/api/status')
      return json({
        target_name: persona.name,
        counts: { sources: persona.sources, items: 0 },
        egress: [],
      });
    if (path === '/api/persona/chat/stream')
      return new Response(`event: final\ndata: ${JSON.stringify(reply)}\n\n`, {
        headers: { 'Content-Type': 'text/event-stream' },
      });
    if (path.startsWith('/api/persona/questionnaire'))
      return json({
        questions: [],
        sections: [],
        answers: {},
        updated_at: null,
      });
    if (path === '/api/persona/state') return json({ stale: false });
    if (path === '/api/media/capabilities')
      return json({ available: false, video: { available: false } });
    if (path === '/api/jobs') return json([]);
    if (path === '/api/persona/sources') return json([]);
    if (path === '/api/persona/processing') return json({ state: 'idle' });
    return json({});
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => {
  cleanup();
  setPersonaId('default');
  usePersonas.setState({ id: 'default', items: [] });
  vi.restoreAllMocks();
});
function switcher() {
  return render(
    <ConfirmProvider>
      <MemoryRouter>
        <PersonaSwitcher />
      </MemoryRouter>
    </ConfirmProvider>,
  );
}

it('lists avatars and memory counts, switches without reload, persists and sends the selected header', async () => {
  const user = userEvent.setup();
  switcher();
  await user.click(screen.getByRole('button', { name: '切换分身' }));
  await screen.findByText('3 条记忆');
  expect(screen.getByLabelText('当前分身')).toBeInTheDocument();
  const friend = screen.getByRole('button', { name: /朋友.*3 条记忆/ });
  expect(friend.querySelector('img')).toHaveAttribute(
    'src',
    `/api/media/avatar-image?persona=${B}`,
  );
  await user.click(friend);
  expect(usePersonas.getState().id).toBe(B);
  expect(localStorage.getItem('twin:persona')).toBe(B);
  await api('/api/status');
  expect(selected(fetcher.mock.calls.at(-1)![1])).toBe(B);
});

function twinsPage() {
  return render(
    <ConfirmProvider>
      <MemoryRouter initialEntries={['/twins']}>
        <Twins />
      </MemoryRouter>
    </ConfirmProvider>,
  );
}

it('renames through the persona identity endpoint and preserves its introduction', async () => {
  const user = userEvent.setup();
  twinsPage();
  await user.click(await screen.findByLabelText('管理朋友'));
  expect(screen.getAllByRole('button', { name: '删除' })).toHaveLength(1);
  await user.click(
    within(screen.getByLabelText('管理朋友').closest('article')!).getByRole(
      'button',
      { name: '重命名' },
    ),
  );
  const input = screen.getByRole('textbox', { name: '分身名字' });
  await user.clear(input);
  await user.type(input, '新朋友');
  await user.click(screen.getByRole('button', { name: '保存名字' }));
  await screen.findByRole('button', { name: '和新朋友聊天' });
  const saved = fetcher.mock.calls.find(
    ([path, init]) => path === '/api/identity' && init?.method === 'PUT',
  )![1];
  expect(selected(saved)).toBe(B);
  expect(JSON.parse(saved!.body as string)).toEqual({
    name: '新朋友',
    about: '保留介绍',
  });
});

it('requires delete confirmation and purges only the deleted persona browser records', async () => {
  const user = userEvent.setup();
  sessionStorage.setItem(personaKey(CHAT_KEY, B), 'private');
  sessionStorage.setItem(CHAT_KEY, 'default history');
  twinsPage();
  await user.click(await screen.findByLabelText('管理朋友'));
  await user.click(screen.getByRole('button', { name: '删除' }));
  let dialog = screen.getByRole('dialog', { name: '删除「朋友」？' });
  await user.click(within(dialog).getByRole('button', { name: '取消' }));
  expect(fetcher.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(
    false,
  );
  await waitFor(() =>
    expect(
      screen.queryByRole('dialog', { name: '删除「朋友」？' }),
    ).not.toBeInTheDocument(),
  );
  await user.click(screen.getByLabelText('管理朋友'));
  await user.click(screen.getByRole('button', { name: '删除' }));
  dialog = screen.getByRole('dialog', { name: '删除「朋友」？' });
  await user.click(within(dialog).getByRole('button', { name: '删除分身' }));
  await waitFor(() => expect(items).toHaveLength(1));
  expect(sessionStorage.getItem(personaKey(CHAT_KEY, B))).toBeNull();
  expect(sessionStorage.getItem(CHAT_KEY)).toBe('default history');
});

it('creates, switches and opens onboarding even though the new identity already has a name', async () => {
  window.location.hash = '#/chat';
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole('button', { name: '新建分身' }));
  await user.type(
    await screen.findByRole('textbox', { name: '分身名字' }),
    '新的分身',
  );
  await user.click(screen.getByRole('button', { name: '创建并开始' }));
  await screen.findByRole('heading', { name: '你是谁' });
  expect(screen.getByRole('heading', { name: '新的分身' })).toBeVisible();
  expect(getPersonaId()).toBe(NEW);
  expect(screen.getByRole('textbox', { name: '名字' })).toHaveValue('新的分身');
  expect(screen.getByRole('button', { name: '切换分身' })).toBeVisible();
});

function Conversation() {
  const chat = useConversation(true);
  return (
    <>
      <p>{chat.turns.map((turn) => turn.content).join('|')}</p>
      <button onClick={() => void chat.send('新的问题')}>发送</button>
    </>
  );
}
function ChatContext() {
  const id = usePersonas((state) => state.id);
  return <Conversation key={id} />;
}
it('restores and saves chat history independently for each persona', async () => {
  const turn = { id: 'same', role: 'twin', timestamp: 'now' };
  sessionStorage.setItem(
    CHAT_KEY,
    JSON.stringify([{ ...turn, content: '主人的历史' }]),
  );
  sessionStorage.setItem(
    personaKey(CHAT_KEY, B),
    JSON.stringify([{ ...turn, content: '朋友的历史' }]),
  );
  render(<ChatContext />);
  expect(screen.getByText('主人的历史')).toBeVisible();
  act(() => usePersonas.getState().switchTo(B));
  expect(screen.queryByText('主人的历史')).not.toBeInTheDocument();
  expect(screen.getByText('朋友的历史')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: '发送' }));
  await waitFor(() =>
    expect(sessionStorage.getItem(personaKey(CHAT_KEY, B))).toContain(
      '新的问题',
    ),
  );
  expect(sessionStorage.getItem(CHAT_KEY)).not.toContain('新的问题');
  const request = fetcher.mock.calls.find(
    ([path]) => path === '/api/persona/chat/stream',
  )![1];
  expect(selected(request)).toBe(B);
  act(() => usePersonas.getState().switchTo('default'));
  expect(screen.getByText('主人的历史')).toBeVisible();
});

it('aborts an unfinished reply on persona switch and never saves its partial text', async () => {
  let controller: ReadableStreamDefaultController<Uint8Array>;
  let signal: AbortSignal | null | undefined;
  const cancel = vi.fn();
  const original = fetcher.getMockImplementation()! as (
    path: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation((path: string, init?: RequestInit) => {
    if (path !== '/api/persona/chat/stream') return original(path, init);
    signal = init?.signal;
    return Promise.resolve(
      new Response(
        new ReadableStream<Uint8Array>({
          start(value) {
            controller = value;
          },
          cancel,
        }),
      ),
    );
  });
  render(<ChatContext />);
  await act(async () =>
    fireEvent.click(screen.getByRole('button', { name: '发送' })),
  );
  await act(async () =>
    controller.enqueue(
      new TextEncoder().encode('event: delta\ndata: {"text":"主人回复中"}\n\n'),
    ),
  );
  expect(screen.getByText(/主人回复中/)).toBeInTheDocument();
  await act(async () => usePersonas.getState().switchTo(B));
  expect(signal?.aborted).toBe(true);
  expect(cancel).toHaveBeenCalledOnce();
  expect(screen.queryByText(/主人回复中/)).not.toBeInTheDocument();
  expect(sessionStorage.getItem(CHAT_KEY)).toBeNull();
  expect(sessionStorage.getItem(personaKey(CHAT_KEY, B))).toBeNull();
});

const videoTurns: Turn[] = [
  {
    id: 'same',
    role: 'twin',
    timestamp: 'now',
    content: '回答',
    reply: { ...reply, abstain: false },
  },
];
function Videos() {
  const state = useReplyVideos(true, videoTurns, '测试');
  return <p>{state.videos.same?.result?.file}</p>;
}
it('keys video session results by persona and adds persona to every media URL', async () => {
  const file = `${'a'.repeat(64)}.mp4`;
  sessionStorage.setItem(
    'twin.reply-video:same',
    JSON.stringify({ status: 'done', result: { file } }),
  );
  setPersonaId(B);
  const otherFile = `${'b'.repeat(64)}.mp4`;
  sessionStorage.setItem(
    `twin.reply-video:${personaKey('')}|same`,
    JSON.stringify({ status: 'done', result: { file: otherFile } }),
  );
  render(<Videos />);
  await screen.findByText(otherFile);
  expect(screen.queryByText(file)).not.toBeInTheDocument();
  expect(videoUrl({ file, duration_s: 1, warnings: [] })).toBe(
    `/api/media/video/${file}?persona=${B}`,
  );
  for (const path of [
    '/api/media/avatar-image?v=sha',
    '/api/me/voice/reference',
    '/api/media/avatar.vrm',
    '/api/media/audio/a.wav',
  ])
    expect(personaUrl(path)).toContain(`persona=${B}`);
});

it('isolates upload resume records and captures the persona through a switch during transfer', async () => {
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
  const file = new File(['abc'], 'same.mp3', { lastModified: 1 });
  localStorage.setItem(
    'twin:media-uploads',
    JSON.stringify([
      { id: 'owner-upload', name: file.name, size: 3, lastModified: 1 },
    ]),
  );
  setPersonaId(B);
  fetcher.mockImplementation(async (path: string, init: RequestInit) => {
    expect(selected(init)).toBe(B);
    if (path === '/api/uploads') return json({ id: 'friend-upload' });
    if (path.includes('?offset=')) {
      setPersonaId('default');
      return json({ offset: 3 });
    }
    if (path === '/api/uploads/friend-upload/finish') return json({});
    throw new Error(`Unexpected request ${path}`);
  });
  await uploadMedia(file, new AbortController().signal, vi.fn());
  expect(localStorage.getItem('twin:media-uploads')).toContain('owner-upload');
  expect(localStorage.getItem(personaKey('twin:media-uploads', B))).toBe('[]');
});

function Questions() {
  const questions = useQuestionnaire('initial');
  return (
    <>
      <p>{questions.loading ? 'loading' : 'ready'}</p>
      <button onClick={() => questions.change('q01', '原分身的答案')}>
        写答案
      </button>
    </>
  );
}
function QuestionContext() {
  const id = usePersonas((state) => state.id);
  return <Questions key={id} />;
}
function AudioReply() {
  const audio = useReplyAudio(true);
  return (
    <>
      <audio ref={audio.audioRef} />
      <button
        onClick={() =>
          audio.toggle('same', { ...reply, abstain: false }, '测试')
        }
      >
        播放
      </button>
    </>
  );
}
function AudioContextPage() {
  const id = usePersonas((state) => state.id);
  return <AudioReply key={id} />;
}
it('stops playback and does not reuse another persona audio cache on switching', async () => {
  vi.stubGlobal('AudioContext', undefined);
  const pause = vi
    .spyOn(HTMLMediaElement.prototype, 'pause')
    .mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
  const url = `/api/media/audio/${'a'.repeat(64)}.wav`;
  fetcher.mockImplementation(async () =>
    json({
      segment_count: 1,
      segments: [{ index: 0, url, duration_s: 1, lipsync: null }],
    }),
  );
  const view = render(<AudioContextPage />);
  fireEvent.click(screen.getByRole('button', { name: '播放' }));
  const previous = view.container.querySelector('audio')!;
  await waitFor(() =>
    expect(previous).toHaveAttribute('src', `${url}?persona=default`),
  );
  act(() => usePersonas.getState().switchTo(B));
  expect(pause).toHaveBeenCalled();
  expect(previous).not.toHaveAttribute('src');
  expect(view.container.querySelector('audio')).not.toHaveAttribute('src');
  fireEvent.click(screen.getByRole('button', { name: '播放' }));
  await waitFor(() =>
    expect(view.container.querySelector('audio')).toHaveAttribute(
      'src',
      `${url}?persona=${B}`,
    ),
  );
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(selected(fetcher.mock.calls[0][1])).toBe('default');
  expect(selected(fetcher.mock.calls[1][1])).toBe(B);
});

it('does not let an older registry response undo a switch to a newly created persona', async () => {
  let resolve!: (response: Response) => void;
  fetcher.mockImplementationOnce(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  const stale = usePersonas.getState().refresh();
  const created = { ...items[1], id: NEW, name: '新分身' };
  fetcher.mockResolvedValueOnce(json([...items, created]));
  await usePersonas.getState().refresh();
  usePersonas.getState().switchTo(NEW);
  resolve(json(items));
  await stale;
  expect(usePersonas.getState().id).toBe(NEW);
  expect(usePersonas.getState().items).toContainEqual(created);
});

it('can switch when browser storage is unavailable', () => {
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('disabled');
  });
  expect(() => usePersonas.getState().switchTo(B)).not.toThrow();
  expect(getPersonaId()).toBe(B);
});

it('keeps deferred questionnaire leave-page writes attributed to their original persona', async () => {
  render(<QuestionContext />);
  await screen.findByText('ready');
  fireEvent.click(screen.getByRole('button', { name: '写答案' }));
  act(() => usePersonas.getState().switchTo(B));
  await waitFor(() =>
    expect(fetcher.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(
      true,
    ),
  );
  const write = fetcher.mock.calls.find(
    ([, init]) => init?.method === 'PUT',
  )![1];
  expect(selected(write)).toBe('default');
  expect(JSON.parse(write!.body as string).answers.q01).toBe('原分身的答案');
  expect(
    fetcher.mock.calls
      .filter(
        ([path, init]) =>
          path.includes('questionnaire') && init?.method !== 'PUT',
      )
      .some(([, init]) => selected(init) === B),
  ).toBe(true);
});
