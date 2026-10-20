import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import type { ReactNode } from 'react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { useReducedMotion } from 'motion/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider } from '../components/ui';
import { SelfAssets } from '../features/assets/SelfAssets';
import { IdentityForm } from '../features/identity/IdentityForm';
import { PendingWorkProvider, useFlowPending } from '../lib/pendingWork';
import { Memories, type Memory } from '../pages/Memories';
import { useStatus } from '../stores/status';
import { isSourcesUrl, sourcesPage } from './personaApi';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: vi.fn(),
}));
vi.mock('react-easy-crop', () => ({
  default: ({
    onCropComplete,
    mediaProps,
  }: {
    onCropComplete: (area: object) => void;
    mediaProps: { onError: () => void };
  }) => (
    <>
      <img alt="待裁剪照片" {...mediaProps} />
      <button
        onClick={() => onCropComplete({ x: 0, y: 0, width: 100, height: 100 })}
      >
        裁剪
      </button>
    </>
  ),
}));

const identity = {
  name: '小林',
  about: '',
  name_source: 'config' as const,
  aliases: [],
  voice: null,
  avatar: null,
  egress: [],
};
const empty = { portrait: null, voice: null, speech_clone: true, video: false };
const json = (value: unknown) => new Response(JSON.stringify(value));
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
class Xhr {
  static last: Xhr;
  upload = {
    onprogress: null as
      | ((event: {
          lengthComputable: boolean;
          loaded: number;
          total: number;
        }) => void)
      | null,
  };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  responseText = '';
  status = 200;
  path = '';
  method = '';
  headers: Record<string, string> = {};
  body: FormData | null = null;
  constructor() {
    Xhr.last = this;
  }
  open(method: string, path: string) {
    this.method = method;
    this.path = path;
  }
  setRequestHeader(key: string, value: string) {
    this.headers[key] = value;
  }
  send(body: FormData) {
    this.body = body;
  }
  abort = vi.fn(() => this.onabort?.());
  progress(percent: number) {
    this.upload.onprogress?.({
      lengthComputable: true,
      loaded: percent,
      total: 100,
    });
  }
  complete(value: unknown, status = 200) {
    this.status = status;
    this.responseText = JSON.stringify(value);
    this.onload?.();
  }
}
let rows: Memory[];
let processing: 'idle' | 'running' | 'queued';
let fetcher: ReturnType<typeof vi.fn<(path: string) => Promise<Response>>>;
let speech: boolean;
const media = (
  id: string,
  status: Memory['status'] = 'transcribing',
): Memory => ({
  source_id: id,
  title: `录音 ${id}`,
  status,
  remembered: 0,
  detected_kind_label: '音频',
  first_date: null,
  media_sha: id,
  duration_s: 540,
  transcribed_s: 120,
});
beforeEach(() => {
  rows = [];
  processing = 'idle';
  speech = false;
  localStorage.clear();
  useStatus.setState({ data: null, error: null });
  vi.mocked(useReducedMotion).mockReturnValue(true);
  vi.stubGlobal('XMLHttpRequest', Xhr);
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:photo');
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
  fetcher = vi.fn((path: string) => {
    if (path === '/api/identity')
      return Promise.resolve(json({ ...identity, name_source: 'user' }));
    if (path === '/api/personas')
      return Promise.resolve(
        json([{ id: 'default', name: '小林', is_default: true }]),
      );
    if (path === '/api/status')
      return Promise.resolve(
        json({ counts: { sources: rows.length, items: 0 }, egress: [] }),
      );
    if (path === '/api/me/assets') return Promise.resolve(json(empty));
    if (path === '/api/media/capabilities')
      return Promise.resolve(json({ available: speech }));
    if (isSourcesUrl(path))
      return Promise.resolve(json(sourcesPage(path, rows)));
    if (path === '/api/persona/processing')
      return Promise.resolve(json({ state: processing }));
    if (path === '/api/media/audio')
      return Promise.resolve(
        json({ segments: [{ url: '/api/media/audio/trial.wav' }] }),
      );
    throw new Error(path);
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
// Stands in for the host that shows what the components registered as pending work.
function PendingProbe() {
  const pending = useFlowPending('');
  return <p data-testid="pending">{pending.label}</p>;
}
function mount(ui: ReactNode) {
  return render(
    <ConfirmProvider>
      <MemoryRouter>
        <PendingWorkProvider>
          {ui}
          <PendingProbe />
        </PendingWorkProvider>
      </MemoryRouter>
    </ConfirmProvider>,
  );
}
const mountAssets = () => mount(<SelfAssets />);
const mountMemories = () => mount(<Memories embedded />);
function locked(label: string) {
  expect(screen.getByTestId('pending')).toHaveTextContent(label);
}
function released() {
  expect(screen.getByTestId('pending')).toBeEmptyDOMElement();
}

it.each([
  [true, false],
  [false, false],
  [true, true],
  [false, true],
])(
  'locks portrait upload and processing (reduced=%s, HEIC fallback=%s)',
  async (reduced, heic) => {
    vi.mocked(useReducedMotion).mockReturnValue(reduced);
    mountAssets();
    await waitFor(() =>
      expect(screen.getByLabelText('选择照片')).toBeEnabled(),
    );
    fireEvent.change(screen.getByLabelText('选择照片'), {
      target: {
        files: [
          new File(['photo'], heic ? 'self.heic' : 'self.jpg', {
            type: heic ? 'image/heic' : 'image/jpeg',
          }),
        ],
      },
    });
    if (heic)
      fireEvent.error(await screen.findByRole('img', { name: '待裁剪照片' }));
    else fireEvent.click(await screen.findByRole('button', { name: '裁剪' }));
    fireEvent.click(screen.getByRole('button', { name: '使用这张' }));
    await waitFor(() => expect(Xhr.last.path).toBe('/api/me/portrait'));
    locked('正在上传照片…');
    expect(screen.getByRole('region', { name: '形象' })).toHaveAttribute(
      'aria-busy',
      'true',
    );
    act(() => Xhr.last.progress(50));
    const progressStatus = screen
      .getByRole('progressbar', { name: '上传进度' })
      .closest('[role="status"]');
    expect(progressStatus).toHaveTextContent(/上传中\s*50%.*MB/);
    act(() => Xhr.last.progress(100));
    locked('正在处理照片…');
    act(() =>
      Xhr.last.complete({
        ...empty,
        portrait: { sha: 'new', file: 'new.png' },
      }),
    );
    await waitFor(released);
    expect(screen.getByRole('region', { name: '形象' })).not.toHaveAttribute(
      'aria-busy',
      'true',
    );
  },
);

it('keeps voice processing locked through trial synthesis, without a background escape', async () => {
  speech = true;
  const synthesis = deferred<Response>();
  const original = fetcher.getMockImplementation()!;
  fetcher.mockImplementation((path: string) =>
    path === '/api/media/audio' ? synthesis.promise : original(path),
  );
  mountAssets();
  await waitFor(() =>
    expect(screen.getByLabelText('选择录音或视频')).toBeEnabled(),
  );
  fireEvent.change(screen.getByLabelText('选择录音或视频'), {
    target: { files: [new File(['voice'], 'voice.wav')] },
  });
  locked('正在上传声音…');
  act(() => Xhr.last.progress(100));
  locked('正在处理声音…');
  await act(async () =>
    Xhr.last.complete({
      ...empty,
      voice: { id: 'voice', file: 'voice.wav', duration_s: 12 },
    }),
  );
  locked('正在处理声音…');
  await act(async () =>
    synthesis.resolve(
      json({ segments: [{ url: '/api/media/audio/trial.wav' }] }),
    ),
  );
  released();
  expect(screen.getByLabelText('试听我的声音')).toBeInTheDocument();
});

it('unlocks after an upload error and retries the same voice file', async () => {
  mountAssets();
  await waitFor(() =>
    expect(screen.getByLabelText('选择录音或视频')).toBeEnabled(),
  );
  const file = new File(['voice'], 'voice.wav');
  fireEvent.change(screen.getByLabelText('选择录音或视频'), {
    target: { files: [file] },
  });
  act(() => Xhr.last.complete({ detail: '声音太短，请重试' }, 400));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '声音太短，请重试',
  );
  released();
  fireEvent.click(screen.getByRole('button', { name: '重试' }));
  locked('正在上传声音…');
  expect(Xhr.last.body?.get('file')).toBe(file);
  await act(async () => Xhr.last.complete(empty));
  released();
});

it.each(['上传文件', '上传文件夹'])(
  'shows percent/MB for %s and tracks each long job in turn',
  async (tab) => {
    mountMemories();
    await userEvent.click(screen.getByRole('tab', { name: tab }));
    fireEvent.change(
      screen.getByLabelText(tab === '上传文件' ? '选择文件' : '选择文件夹'),
      {
        target: {
          files: [
            new File(['a'], 'a.txt'),
            new File(['b'], 'b.txt'),
            new File(['c'], 'c.txt'),
          ],
        },
      },
    );
    locked('正在上传 1/3…');
    expect(Xhr.last.path).toBe('/api/persona/import');
    expect(Xhr.last.headers['X-Twin']).toBe('1');
    const folder = tab === '上传文件夹';
    expect(Xhr.last.body?.getAll('files')).toHaveLength(folder ? 1 : 3);
    act(() => Xhr.last.progress(50));
    locked(folder ? '正在上传 1/3…' : '正在上传 2/3…');
    const progressStatus = screen
      .getByRole('progressbar', { name: '上传进度' })
      .closest('[role="status"]');
    expect(progressStatus).toHaveTextContent(
      folder ? /上传中\s*16%.*MB/ : /上传中\s*50%.*MB/,
    );
    if (folder) {
      for (const [index, name] of ['b.txt', 'c.txt'].entries()) {
        await act(async () => Xhr.last.complete({ imported: [], skipped: [] }));
        locked(`正在上传 ${index + 2}/3…`);
        expect(Xhr.last.body?.getAll('files')).toHaveLength(1);
        expect(Xhr.last.body?.get('files')).toHaveProperty('name', name);
      }
    }
    vi.useFakeTimers();
    rows = [media('1')];
    processing = 'running';
    await act(async () => Xhr.last.complete({ imported: [], skipped: [] }));
    locked('正在转写 2.0/9.0 分钟…');
    expect(screen.getByText(/录音 1 · 正在转写/)).toBeInTheDocument();
    expect(screen.getByText(/^共 1 份/)).toHaveTextContent(
      '共 1 份 · 已记住 0 份 · 整理中 1 份',
    );
    expect(
      screen.getByText(/^共 1 份/).closest('[aria-live]'),
    ).toHaveTextContent('正在记住…');
    rows = [{ ...media('1'), transcribed_s: 240 }];
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getByText(/录音 1 · 正在转写 4.0/)).toBeInTheDocument();
    rows.push(media('2'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    locked('正在转写 4.0/9.0 分钟…');
    // A new byte upload takes over the pending label while jobs still run.
    fireEvent.change(
      screen.getByLabelText(tab === '上传文件' ? '选择文件' : '选择文件夹'),
      { target: { files: [new File(['d'], 'd.txt')] } },
    );
    locked('正在上传 1/1…');
  },
);

it('holds chunked media through finish, polls transcription progress, and unlocks when processing completes', async () => {
  const finish = deferred<Response>();
  const original = fetcher.getMockImplementation()!;
  fetcher.mockImplementation((path: string) => {
    if (path === '/api/uploads') return Promise.resolve(json({ id: 'upload' }));
    if (path.includes('?offset=')) return Promise.resolve(json({ offset: 3 }));
    if (path.endsWith('/finish')) return finish.promise;
    return original(path);
  });
  mountMemories();
  await userEvent.click(screen.getByRole('tab', { name: '上传文件' }));
  fireEvent.change(screen.getByLabelText('选择文件'), {
    target: { files: [new File(['abc'], 'a.mp3')] },
  });
  await waitFor(() =>
    expect(fetcher.mock.calls.some(([path]) => path.endsWith('/finish'))).toBe(
      true,
    ),
  );
  locked('正在上传 1/1…');
  expect(screen.getByRole('progressbar')).toHaveAttribute('value', '3');
  vi.useFakeTimers();
  rows = [media('1')];
  await act(async () => finish.resolve(json({ source_id: '1' })));
  locked('正在转写 2.0/9.0 分钟…');
  rows = [{ ...media('1'), transcribed_s: 240 }];
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000);
  });
  locked('正在转写 4.0/9.0 分钟…');
  rows = [media('1', 'remembered')];
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000);
  });
  released();
});

it('unlocks failed document uploads and offers retry', async () => {
  mountMemories();
  await userEvent.click(screen.getByRole('tab', { name: '上传文件' }));
  fireEvent.change(screen.getByLabelText('选择文件'), {
    target: { files: [new File(['a'], 'a.txt')] },
  });
  act(() => Xhr.last.complete({ detail: '上传失败，请重试' }, 400));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '上传失败，请重试',
  );
  released();
  fireEvent.click(screen.getByRole('button', { name: '重试上传' }));
  locked('正在上传 1/1…');
});

it('locks identity and memory text saves until their requests finish', async () => {
  const saved = deferred<Response>();
  const note = deferred<Response>();
  const original = fetcher.getMockImplementation()!;
  fetcher.mockImplementation((path: string) =>
    path === '/api/identity'
      ? saved.promise
      : path === '/api/persona/notes'
        ? note.promise
        : original(path),
  );
  const first = mount(<IdentityForm identity={identity} />);
  fireEvent.change(screen.getByLabelText('名字'), {
    target: { value: '小林' },
  });
  fireEvent.click(screen.getByRole('button', { name: '保存' }));
  locked('正在保存身份…');
  expect(screen.getByLabelText('名字').closest('form')).toHaveAttribute(
    'aria-busy',
    'true',
  );
  await act(async () =>
    saved.resolve(json({ ...identity, name_source: 'user' })),
  );
  released();
  first.unmount();
  mountMemories();
  const text = await screen.findByLabelText('要记住的文字');
  fireEvent.change(text, { target: { value: '我喜欢散步' } });
  fireEvent.click(
    within(text.closest('form')!).getByRole('button', { name: '保存' }),
  );
  locked('正在保存记忆…');
  await act(async () => note.resolve(json({ new: true })));
  released();
});
