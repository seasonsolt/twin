import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider } from '../components/ui';
import { uploadMedia, type UploadProgress } from '../lib/mediaUpload';
import { Memories } from '../pages/Memories';

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const key = 'twin:media-uploads';
beforeEach(() => {
  localStorage.clear();
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it('sends sequential 8 MiB blobs with CSRF and progress, then forgets the completed upload', async () => {
  const file = new File([new Uint8Array(8 * 1024 ** 2 + 123)], '手机.mov', {
    type: 'video/quicktime',
    lastModified: 10,
  });
  const progress: UploadProgress[] = [];
  const fetcher = vi.fn(async (url: string, init: RequestInit) => {
    expect(init.headers).toHaveProperty('X-Twin', '1');
    if (url === '/api/uploads') return json({ id: 'id', offset: 0 });
    if (url.includes('?offset=0')) {
      expect((init.body as Blob).size).toBe(8 * 1024 ** 2);
      expect(init.headers).toHaveProperty(
        'Content-Type',
        'application/octet-stream',
      );
      return json({ offset: 8 * 1024 ** 2 });
    }
    if (url.includes('?offset=8388608')) {
      expect((init.body as Blob).size).toBe(123);
      return json({ offset: file.size });
    }
    if (url.endsWith('/finish')) return json({ source_id: 's1' });
    throw new Error(url);
  });
  vi.stubGlobal('fetch', fetcher);
  await uploadMedia(file, new AbortController().signal, (p) =>
    progress.push(p),
  );
  expect(fetcher).toHaveBeenCalledTimes(4);
  expect(progress.some((p) => p.offset === 8 * 1024 ** 2)).toBe(true);
  expect(progress.at(-1)?.offset).toBe(file.size);
  expect(JSON.parse(localStorage.getItem(key)!)).toEqual([]);
});

it('resumes a reselected file from the server offset and resyncs a 409', async () => {
  const file = new File(['1234567890'], '录音.m4a', { lastModified: 42 });
  localStorage.setItem(
    key,
    JSON.stringify([
      { id: 'old', name: file.name, size: 10, lastModified: 42 },
    ]),
  );
  const fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (url === '/api/uploads/old') return json({ offset: 2, size: 10 });
    if (url.endsWith('?offset=2')) return json({ offset: 5 }, 409);
    if (url.endsWith('?offset=5')) {
      expect((init.body as Blob).size).toBe(5);
      return json({ offset: 10 });
    }
    if (url.endsWith('/finish')) return json({ source_id: 's' });
    throw new Error(url);
  });
  vi.stubGlobal('fetch', fetcher);
  await uploadMedia(file, new AbortController().signal, vi.fn());
  expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
    '/api/uploads/old',
    '/api/uploads/old?offset=2',
    '/api/uploads/old?offset=5',
    '/api/uploads/old/finish',
  ]);
});

it('retries network and 5xx errors with backoff and keeps the ID when cancelled', async () => {
  vi.useFakeTimers();
  const file = new File(['abc'], 'a.mp3');
  let puts = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/uploads') return json({ id: 'retry' });
      if (url.includes('?')) {
        puts++;
        if (puts === 1) throw new TypeError('network');
        if (puts === 2) return json({ detail: '稍后重试' }, 503);
        return json({ offset: 3 });
      }
      return json({ source_id: 's' });
    }),
  );
  const done = uploadMedia(file, new AbortController().signal, vi.fn());
  await vi.advanceTimersByTimeAsync(499);
  expect(puts).toBe(1);
  await vi.advanceTimersByTimeAsync(1);
  expect(puts).toBe(2);
  await vi.advanceTimersByTimeAsync(1000);
  await done;
  expect(puts).toBe(3);

  const controller = new AbortController();
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/uploads') return json({ id: 'cancel' });
      throw new TypeError('network');
    }),
  );
  const cancelled = uploadMedia(file, controller.signal, vi.fn());
  const assertion = expect(cancelled).rejects.toMatchObject({
    name: 'AbortError',
  });
  await vi.advanceTimersByTimeAsync(1);
  controller.abort();
  await assertion;
  expect(localStorage.getItem(key)).toContain('cancel');
});

it('pauses offline and resumes on online or visible events', async () => {
  const online = vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
  const fetcher = vi.fn(async (url: string) => {
    if (url === '/api/uploads') return json({ id: 'online' });
    if (url.includes('?')) return json({ offset: 3 });
    return json({});
  });
  vi.stubGlobal('fetch', fetcher);
  const progress = vi.fn();
  const done = uploadMedia(
    new File(['abc'], 'a.wav'),
    new AbortController().signal,
    progress,
  );
  expect(fetcher).not.toHaveBeenCalled();
  expect(progress.mock.calls.at(-1)?.[0].paused).toBe(true);
  online.mockReturnValue(true);
  document.dispatchEvent(new Event('visibilitychange'));
  await done;
  expect(fetcher).toHaveBeenCalledTimes(3);
});

it('shows upload percent/MB and all media row states with retranscription', async () => {
  let complete: (value: Response) => void = () => {};
  const media = (status: string, kind = 'video') => ({
    source_id: status,
    title: status,
    kind,
    media_sha: 'sha',
    detected_kind_label: '视频',
    first_date: null,
    duration_s: 120,
    transcribed_s: 60,
    status,
    remembered: 2,
  });
  const fetcher = vi.fn(async (url: string) => {
    if (url === '/api/persona/sources')
      return json([
        media('extracting'),
        media('transcribing'),
        media('processing'),
        media('remembered'),
        media('failed'),
        media('needs_asr', 'audio'),
      ]);
    if (url === '/api/persona/processing') return json({ state: 'idle' });
    if (url === '/api/status')
      return json({ counts: { sources: 6, items: 2 }, egress: [] });
    if (url === '/api/uploads') return json({ id: 'ui' });
    if (url.includes('?offset='))
      return new Promise<Response>((resolve) => {
        complete = resolve;
      });
    if (url.endsWith('/transcribe')) return json({ job_id: 'j' });
    if (url.endsWith('/finish')) return json({ source_id: 's' });
    throw new Error(url);
  });
  vi.stubGlobal('fetch', fetcher);
  render(
    <ConfirmProvider>
      <MemoryRouter initialEntries={['/memories']}>
        <Memories />
      </MemoryRouter>
    </ConfirmProvider>,
  );
  await screen.findByText('转写中 1.0/2.0 分钟');
  expect(screen.getByText('提取音频')).toBeInTheDocument();
  expect(screen.getByText('整理中')).toBeInTheDocument();
  expect(screen.getByText('已加入 · 已记住 2 条')).toBeInTheDocument();
  expect(screen.getByText('需要配置语音识别')).toBeInTheDocument();
  await userEvent.click(
    screen.getAllByRole('button', { name: '重新转写' })[0]!,
  );
  await waitFor(() =>
    expect(fetcher).toHaveBeenCalledWith(
      '/api/persona/sources/failed/transcribe',
      expect.anything(),
    ),
  );
  await userEvent.click(screen.getByRole('tab', { name: '上传文件' }));
  fireEvent.change(screen.getByLabelText('选择文件'), {
    target: { files: [new File(['abc'], 'a.mp4', { type: 'video/mp4' })] },
  });
  await screen.findByText('上传中，请保持页面打开');
  expect(screen.getByText('上传中 0% · 0.0 / 0.0 MB')).toBeInTheDocument();
  expect(screen.getByRole('progressbar', { name: '上传进度' })).toHaveAttribute(
    'value',
    '0',
  );
  await act(async () => complete(json({ offset: 3 })));
  await waitFor(() =>
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument(),
  );
});
