import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { SelfAssets } from '../features/assets/SelfAssets';
import { useRecorder } from '../features/assets/useRecorder';

vi.mock('react-easy-crop', () => ({
  default: ({
    aspect,
    onCropComplete,
  }: {
    aspect: number;
    onCropComplete: (area: object) => void;
  }) => (
    <button
      onClick={() => onCropComplete({ x: 10, y: 20, width: 60, height: 80 })}
    >
      裁剪 {aspect}
    </button>
  ),
}));
const empty = { portrait: null, voice: null, speech_clone: true, video: false };
const owner = {
  ...empty,
  voice: { id: 'self-0123456789abcdef', file: 'voice.wav', duration_s: 12 },
};
let assets: object;
let fetcher: ReturnType<typeof vi.fn>;
let speech = false;
let tracks: { stop: ReturnType<typeof vi.fn> }[];
let gum: ReturnType<typeof vi.fn>;
const json = (value: unknown) => new Response(JSON.stringify(value));
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
  headers: Record<string, string> = {};
  body: FormData | null = null;
  method = '';
  path = '';
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
  complete(profile: object, status = 200) {
    assets = profile;
    this.status = status;
    this.responseText = JSON.stringify(profile);
    this.onload?.();
  }
}
class Recorder {
  static last: Recorder;
  static isTypeSupported = vi.fn((type: string) => type === 'audio/mp4');
  state = 'inactive';
  mimeType = 'audio/mp4';
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() {
    Recorder.last = this;
  }
  start = vi.fn(() => {
    this.state = 'recording';
  });
  stop = vi.fn(() => {
    this.state = 'inactive';
    this.ondataavailable?.({
      data: new Blob(['recorded audio'], { type: this.mimeType }),
    });
    this.onstop?.();
  });
}
beforeEach(() => {
  assets = empty;
  speech = false;
  tracks = [{ stop: vi.fn() }];
  gum = vi.fn().mockResolvedValue({ getTracks: () => tracks });
  vi.stubGlobal('MediaRecorder', Recorder);
  vi.stubGlobal('XMLHttpRequest', Xhr);
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: gum },
  });
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:preview');
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  fetcher = vi.fn((path: string, init: RequestInit) => {
    if (path === '/api/me/assets') return Promise.resolve(json(assets));
    if (path === '/api/media/capabilities')
      return Promise.resolve(json({ available: speech, avatar_image: null }));
    if (path === '/api/me/portrait' || path === '/api/me/voice') {
      if (init.method === 'DELETE') assets = empty;
      return Promise.resolve(json(assets));
    }
    if (path === '/api/media/audio')
      return Promise.resolve(
        json({ segments: [{ url: '/api/media/audio/sample.wav' }] }),
      );
    throw new Error(path);
  });
  vi.stubGlobal('fetch', fetcher);
});

it('keeps photo and voice setup usable while speech capabilities are still loading', async () => {
  fetcher.mockImplementation((path: string) =>
    path === '/api/me/assets'
      ? Promise.resolve(json(empty))
      : new Promise(() => {}),
  );
  render(<SelfAssets />);
  await waitFor(() =>
    expect(screen.getByRole('button', { name: '换一张' })).toBeEnabled(),
  );
  expect(screen.getByRole('button', { name: '录一段' })).toBeEnabled();
  expect(screen.getByRole('button', { name: '上传录音或视频' })).toBeEnabled();
});

it('crops at 3:4, uploads fractions with progress, disables controls and cache-busts the portrait', async () => {
  const changed = vi.fn();
  window.addEventListener('twin-assets-changed', changed, { once: true });
  render(<SelfAssets />);
  await waitFor(() =>
    expect(screen.getByRole('button', { name: '换一张' })).toBeEnabled(),
  );
  const input = screen.getByLabelText('选择照片');
  expect(input).toHaveAttribute('accept', 'image/*');
  const file = new File(['image'], 'self.jpg', { type: 'image/jpeg' });
  fireEvent.change(input, { target: { files: [file] } });
  await screen.findByRole('button', { name: '裁剪 0.75' });
  expect(screen.getByRole('button', { name: '使用这张' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: '裁剪 0.75' }));
  fireEvent.change(screen.getByLabelText('照片缩放'), {
    target: { value: '2' },
  });
  fireEvent.click(screen.getByRole('button', { name: '使用这张' }));
  await waitFor(() => expect(Xhr.last?.path).toBe('/api/me/portrait'));
  const xhr = Xhr.last;
  expect(xhr.method).toBe('PUT');
  expect(xhr.path).toBe('/api/me/portrait');
  expect(xhr.headers['X-Twin']).toBe('1');
  expect(xhr.body?.get('file')).toBe(file);
  expect(['x', 'y', 'w', 'h'].map((key) => xhr.body?.get(key))).toEqual([
    '0.1',
    '0.2',
    '0.6',
    '0.8',
  ]);
  expect(screen.getByRole('button', { name: '上传录音或视频' })).toBeDisabled();
  act(() =>
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 60, total: 100 }),
  );
  expect(screen.getByRole('progressbar', { name: '上传进度' })).toHaveAttribute(
    'value',
    '60',
  );
  act(() =>
    xhr.complete({ ...empty, portrait: { sha: 'abc123', file: 'abc123.png' } }),
  );
  const preview = await screen.findByRole('img', { name: '当前肖像' });
  expect(preview).toHaveAttribute(
    'src',
    '/api/media/avatar-image?v=abc123&persona=default',
  );
  expect(changed).toHaveBeenCalledOnce();
  await waitFor(() =>
    expect(screen.getByRole('button', { name: '恢复默认' })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole('button', { name: '恢复默认' }));
  await screen.findByLabelText('肖像占位');
});

it('re-encodes an iPhone HEIC photo as JPEG before uploading', async () => {
  Object.defineProperty(HTMLImageElement.prototype, 'decode', {
    configurable: true,
    value: vi.fn().mockResolvedValue(undefined),
  });
  const context = vi
    .spyOn(HTMLCanvasElement.prototype, 'getContext')
    .mockReturnValue({ drawImage: vi.fn() } as never);
  const toBlob = vi
    .spyOn(HTMLCanvasElement.prototype, 'toBlob')
    .mockImplementation((callback) =>
      callback(new Blob(['jpeg'], { type: 'image/jpeg' })),
    );
  render(<SelfAssets />);
  await waitFor(() =>
    expect(screen.getByRole('button', { name: '换一张' })).toBeEnabled(),
  );
  const heic = new File(['heic'], 'IMG_0001.HEIC', { type: 'image/heic' });
  fireEvent.change(screen.getByLabelText('选择照片'), {
    target: { files: [heic] },
  });
  fireEvent.click(await screen.findByRole('button', { name: '裁剪 0.75' }));
  fireEvent.click(screen.getByRole('button', { name: '使用这张' }));
  await waitFor(() => expect(Xhr.last?.path).toBe('/api/me/portrait'));
  const sent = Xhr.last.body?.get('file') as File;
  expect(sent.type).toBe('image/jpeg');
  expect(sent.name).toBe('portrait.jpg');
  expect(Xhr.last.body?.get('w')).toBe('0.6');
  delete (HTMLImageElement.prototype as { decode?: unknown }).decode;
  context.mockRestore();
  toBlob.mockRestore();
});

it('uploads a video as voice, plays the processed reference and offers synthesis with the new voice', async () => {
  speech = true;
  render(<SelfAssets />);
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: '上传录音或视频' }),
    ).toBeEnabled(),
  );
  const input = screen.getByLabelText('选择录音或视频');
  expect(input).toHaveAttribute('accept', 'audio/*,video/*');
  const file = new File(['video audio'], 'record.mov', {
    type: 'video/quicktime',
  });
  fireEvent.change(input, { target: { files: [file] } });
  expect(Xhr.last.path).toBe('/api/me/voice');
  expect(Xhr.last.body?.get('file')).toBe(file);
  act(() => Xhr.last.complete(owner));
  await screen.findByText('我的声音（12.0 秒）');
  expect(screen.getByLabelText('播放声音参考')).toHaveAttribute(
    'src',
    '/api/me/voice/reference?v=self-0123456789abcdef&persona=default',
  );
  await screen.findByLabelText('试听我的声音');
  expect(
    fetcher.mock.calls.filter(([path]) => path === '/api/media/audio'),
  ).toHaveLength(1);
  const sample = JSON.parse(
    fetcher.mock.calls.find(([path]) => path === '/api/media/audio')![1].body,
  );
  expect(sample.answer.reply).toContain('这是我的声音');
  expect(screen.getByRole('button', { name: '试听' })).toBeEnabled();
});

it('shows Chinese upload errors and aborts an unfinished upload on unmount', async () => {
  const view = render(<SelfAssets />);
  await waitFor(() =>
    expect(screen.getByLabelText('选择录音或视频')).toBeEnabled(),
  );
  const upload = () =>
    fireEvent.change(screen.getByLabelText('选择录音或视频'), {
      target: { files: [new File(['short'], 'short.wav')] },
    });
  upload();
  act(() =>
    Xhr.last.complete({ detail: '声音太短，至少需要 5 秒清晰的说话' }, 400),
  );
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '声音太短，至少需要 5 秒清晰的说话',
  );
  expect(screen.getByRole('button', { name: '上传录音或视频' })).toBeEnabled();
  upload();
  view.unmount();
  expect(Xhr.last.abort).toHaveBeenCalledOnce();
});

it('records, stops, replays, re-records and uploads the iPhone mp4 reference', async () => {
  render(<SelfAssets />);
  await waitFor(() =>
    expect(screen.getByRole('button', { name: '录一段' })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole('button', { name: '录一段' }));
  await screen.findByRole('timer');
  expect(screen.getByText(/今天的阳光很温暖/)).toBeVisible();
  expect(screen.getByRole('meter', { name: '录音音量' })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: '停止录音' }));
  expect(await screen.findByLabelText('回放录音')).toHaveAttribute(
    'src',
    'blob:preview',
  );
  expect(tracks[0].stop).toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '重录' }));
  await screen.findByRole('timer');
  expect(gum).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole('button', { name: '停止录音' }));
  fireEvent.click(screen.getByRole('button', { name: '使用' }));
  expect((Xhr.last.body?.get('file') as File).name).toBe('recording.m4a');
  act(() => Xhr.last.complete(owner));
  await screen.findByText('我的声音（12.0 秒）');
  expect(screen.queryByLabelText('回放录音')).not.toBeInTheDocument();
});

it('stops automatically at 30 seconds and releases microphone/timers on unmount', async () => {
  vi.useFakeTimers();
  try {
    const view = renderHook(() => useRecorder());
    await act(async () => view.result.current.start());
    expect(view.result.current.state).toBe('recording');
    act(() => vi.advanceTimersByTime(30_000));
    expect(view.result.current.state).toBe('review');
    expect(view.result.current.seconds).toBe(30);
    expect(Recorder.last.stop).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
    await act(async () => view.result.current.start());
    view.unmount();
    expect(Recorder.last.stop).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  } finally {
    vi.useRealTimers();
  }
});

it('handles denied permissions and stops a stream granted after unmount', async () => {
  gum.mockRejectedValueOnce(new Error('denied'));
  const view = renderHook(() => useRecorder());
  await act(async () => view.result.current.start());
  expect(view.result.current.state).toBe('idle');
  expect(view.result.current.error).toContain('无法使用麦克风');
  let grant!: (value: unknown) => void;
  gum.mockReturnValueOnce(
    new Promise((resolve) => {
      grant = resolve;
    }),
  );
  act(() => {
    void view.result.current.start();
  });
  expect(view.result.current.state).toBe('requesting');
  view.unmount();
  await act(async () => grant({ getTracks: () => tracks }));
  expect(tracks[0].stop).toHaveBeenCalledOnce();
});
