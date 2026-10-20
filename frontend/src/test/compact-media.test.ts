import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
  compactable,
  mp4CreationTime,
  setMp4CreationTime,
} from '../lib/compactMedia';
import { uploadMedia, type UploadProgress } from '../lib/mediaUpload';

const made = vi.hoisted(() => ({ file: undefined as File | undefined }));
vi.mock('../lib/compactMedia', async (actual) => {
  const real = await actual<typeof import('../lib/compactMedia')>();
  return {
    ...real,
    compactMedia: async (
      file: File,
      _mode: unknown,
      _signal: AbortSignal,
      progress: (done: number) => void,
    ) => {
      if (!made.file)
        return real.compactMedia(file, 'audio', _signal, progress);
      progress(0.5);
      return made.file;
    },
  };
});

// jsdom's Blob has no arrayBuffer(); every browser this runs in does.
if (!Blob.prototype.arrayBuffer)
  Blob.prototype.arrayBuffer = function (this: Blob) {
    return new Promise<ArrayBuffer>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as ArrayBuffer);
      reader.onerror = () => reject(reader.error);
      reader.readAsArrayBuffer(this);
    });
  };

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
beforeEach(() => {
  localStorage.clear();
  made.file = undefined;
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
});
afterEach(() => vi.restoreAllMocks());

function box(type: string, ...parts: Uint8Array[]): Uint8Array<ArrayBuffer> {
  const size = 8 + parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(size);
  new DataView(out.buffer).setUint32(0, size);
  out.set(new TextEncoder().encode(type), 4);
  let at = 8;
  for (const part of parts) {
    out.set(part, at);
    at += part.length;
  }
  return out;
}
/** A full box body: version, flags, then creation and modification time (32 or 64 bit), then padding. */
function timed(version: 0 | 1, seconds: number): Uint8Array<ArrayBuffer> {
  const out = new Uint8Array(version ? 4 + 16 + 8 : 4 + 8 + 8);
  const view = new DataView(out.buffer);
  view.setUint8(0, version);
  if (version) {
    view.setBigUint64(4, BigInt(seconds));
    view.setBigUint64(12, BigInt(seconds));
  } else {
    view.setUint32(4, seconds);
    view.setUint32(8, seconds);
  }
  return out;
}
function mp4(seconds: number, mdatFirst = false): Uint8Array<ArrayBuffer> {
  const moov = box(
    'moov',
    box('mvhd', timed(0, seconds)),
    box(
      'trak',
      box('tkhd', timed(0, seconds)),
      box('mdia', box('mdhd', timed(1, seconds))),
    ),
  );
  const mdat = box('mdat', new Uint8Array(1000));
  const ftyp = box('ftyp', new Uint8Array(8));
  const parts = mdatFirst ? [ftyp, mdat, moov] : [ftyp, moov, mdat];
  const out = new Uint8Array(parts.reduce((sum, p) => sum + p.length, 0));
  let at = 0;
  for (const part of parts) {
    out.set(part, at);
    at += part.length;
  }
  return out;
}
function times(bytes: Uint8Array): number[] {
  const view = new DataView(bytes.buffer);
  const found: number[] = [];
  for (let at = 0; at + 8 <= bytes.length; at++) {
    const type = new TextDecoder().decode(bytes.slice(at + 4, at + 8));
    if (!['mvhd', 'tkhd', 'mdhd'].includes(type)) continue;
    const body = at + 8;
    found.push(
      view.getUint8(body) === 1
        ? Number(view.getBigUint64(body + 4))
        : view.getUint32(body + 4),
    );
  }
  return found;
}

it('reads the recording time of an MP4 wherever its moov is', async () => {
  for (const mdatFirst of [false, true]) {
    const file = new File([mp4(3_800_000_000, mdatFirst)], 'a.mp4');
    expect(await mp4CreationTime(file)).toBe(3_800_000_000);
  }
  expect(await mp4CreationTime(new File([new Uint8Array(3)], 'b.mp4'))).toBe(0);
});

it('writes one time into every mvhd, tkhd and mdhd', () => {
  const bytes = mp4(123);
  setMp4CreationTime(bytes, 3_700_000_000);
  expect(times(bytes)).toEqual([3_700_000_000, 3_700_000_000, 3_700_000_000]);
  setMp4CreationTime(bytes, 0);
  expect(times(bytes)).toEqual([0, 0, 0]);
});

it('only offers to change memory material, and videos only for the library', () => {
  const file = (name: string) => new File([], name);
  expect(compactable(file('会.wav'), 'audio')).toBe(true);
  expect(compactable(file('会.flac'), 'audio')).toBe(true);
  expect(compactable(file('会.mp3'), 'audio-and-video')).toBe(false);
  expect(compactable(file('会.mp4'), 'audio')).toBe(false);
  expect(compactable(file('会.mov'), 'audio-and-video')).toBe(true);
  expect(compactable(file('会.mkv'), 'audio-and-video')).toBe(false);
});

it('sends the original when the browser cannot encode', async () => {
  const original = new File([new Uint8Array(100)], '会.wav', {
    lastModified: 5,
  });
  const sent: Blob[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      if (url === '/api/uploads') {
        expect(JSON.parse(init.body as string).filename).toBe('会.wav');
        return json({ id: 'id', offset: 0 });
      }
      if (url.includes('?offset=')) {
        sent.push(init.body as Blob);
        return json({ offset: 100 });
      }
      return json({ source_id: 's' });
    }),
  );
  await uploadMedia(original, new AbortController().signal, () => {}, {
    compact: 'audio',
  });
  expect(sent.map((blob) => blob.size)).toEqual([100]);
});

it('uploads the smaller file and resumes it only when it is the same bytes', async () => {
  const original = new File([new Uint8Array(1000)], '会.wav', {
    lastModified: 5,
  });
  made.file = new File([new Uint8Array([1, 2, 3])], '会.m4a', {
    lastModified: 5,
  });
  const progress: UploadProgress[] = [];
  const created: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      if (url === '/api/uploads') {
        created.push(JSON.parse(init.body as string).filename);
        return json({ id: 'a'.repeat(32), offset: 0 });
      }
      if (url.includes('?offset=')) throw new TypeError('offline');
      return json({ offset: 0 });
    }),
  );
  const controller = new AbortController();
  const attempt = uploadMedia(
    original,
    controller.signal,
    (p) => progress.push(p),
    { compact: 'audio' },
  );
  await vi.waitFor(() => expect(created).toEqual(['会.m4a']));
  controller.abort();
  await expect(attempt).rejects.toThrow();
  expect(progress[0].preparing).toBe(0);
  expect(progress.some((p) => p.preparing === 0.5)).toBe(true);
  const [saved] = JSON.parse(localStorage.getItem('twin:media-uploads')!);
  expect(saved).toMatchObject({ name: '会.m4a', size: 3 });
  expect(saved.sha).toMatch(/^[0-9a-f]{64}$/u);

  // Made again with other bytes of the same size: a new upload, never a resume on top of the old one.
  made.file = new File([new Uint8Array([9, 9, 9])], '会.m4a', {
    lastModified: 5,
  });
  const urls: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      urls.push(url);
      if (url === '/api/uploads')
        return json({ id: 'b'.repeat(32), offset: 0 });
      if (url.includes('?offset=')) return json({ offset: 3 });
      return json({ source_id: 's' });
    }),
  );
  await uploadMedia(original, new AbortController().signal, () => {}, {
    compact: 'audio',
  });
  expect(urls[0]).toBe('/api/uploads');
  expect(urls.some((url) => url.includes('a'.repeat(32)))).toBe(false);
});
