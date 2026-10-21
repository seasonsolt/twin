import { withBase } from './base';
import { ApiError, handleApiFailure } from './api';
import { compactable, compactMedia, type Compaction } from './compactMedia';
import { getPersonaId, personaKey } from './persona';

const CHUNK_SIZE = 8 * 1024 * 1024;
const STORAGE_KEY = 'twin:media-uploads';
const MEDIA_EXTENSIONS =
  'mp4 mov m4v webm mkv avi 3gp m4a mp3 wav aac ogg opus flac caf amr'.split(
    ' ',
  );
const extensions = new Set(MEDIA_EXTENSIONS);
// For a file picker, every suffix spelled out: a browser decides what audio/* covers from the system's file types,
// and some systems do not count .m4a as audio, which greys it out.
export const MEDIA_ACCEPT = [
  'audio/*',
  'video/*',
  ...MEDIA_EXTENSIONS.map((extension) => `.${extension}`),
].join(',');
export const isMedia = (file: File) =>
  extensions.has(file.name.split('.').at(-1)?.toLowerCase() ?? '');

export function uploadForm<T>(
  path: string,
  form: FormData,
  signal: AbortSignal,
  progress: (percent: number) => void,
  method = 'POST',
): Promise<T> {
  return new Promise((resolve, reject) => {
    signal.throwIfAborted();
    const xhr = new XMLHttpRequest();
    xhr.open(method, withBase(path));
    xhr.setRequestHeader('X-Twin', '1');
    xhr.setRequestHeader('X-Twin-Persona', getPersonaId());
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable)
        progress(Math.round((event.loaded / event.total) * 100));
    };
    const abort = () => xhr.abort();
    const finish = () => signal.removeEventListener('abort', abort);
    xhr.onload = () => {
      finish();
      let data: T & { detail?: string };
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        reject(new Error('上传失败，请重试'));
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else {
        handleApiFailure(xhr.status, data);
        reject(
          new ApiError(
            xhr.status,
            typeof data?.detail === 'string' &&
              /[\u3400-\u9fff]/u.test(data.detail)
              ? data.detail
              : '上传失败，请重试',
          ),
        );
      }
    };
    xhr.onerror = () => {
      finish();
      reject(new Error('连接中断，请重新上传'));
    };
    xhr.onabort = () => {
      finish();
      reject(new DOMException('上传已取消', 'AbortError'));
    };
    signal.addEventListener('abort', abort, { once: true });
    xhr.send(form);
  });
}

interface SavedUpload {
  id: string;
  name: string;
  size: number;
  lastModified: number;
  // SHA-256 of a file made smaller in the browser: made again on resume, it must be the same bytes.
  sha?: string;
}
export interface UploadProgress {
  name: string;
  offset: number;
  size: number;
  paused: boolean;
  /** Set (0..1) while the file is being made smaller in the browser, before any byte is sent. */
  preparing?: number;
}
function savedUploads(persona: string): SavedUpload[] {
  try {
    const value: unknown = JSON.parse(
      localStorage.getItem(personaKey(STORAGE_KEY, persona)) ?? '[]',
    );
    return Array.isArray(value) ? (value as SavedUpload[]) : [];
  } catch {
    return [];
  }
}
function save(uploads: SavedUpload[], persona: string) {
  try {
    localStorage.setItem(
      personaKey(STORAGE_KEY, persona),
      JSON.stringify(uploads),
    );
  } catch {
    // Uploading still works when Safari's storage is unavailable.
  }
}
function matches(upload: SavedUpload, file: File, sha?: string) {
  return (
    upload.name === file.name &&
    upload.size === file.size &&
    upload.lastModified === file.lastModified &&
    upload.sha === sha
  );
}
async function digest(file: File): Promise<string | undefined> {
  try {
    const hash = await crypto.subtle.digest(
      'SHA-256',
      await file.arrayBuffer(),
    );
    return Array.from(new Uint8Array(hash), (byte) =>
      byte.toString(16).padStart(2, '0'),
    ).join('');
  } catch {
    // No WebCrypto (an insecure origin): such an upload is not resumed.
    return undefined;
  }
}
function abort(signal: AbortSignal) {
  signal.throwIfAborted();
}
async function pause(signal: AbortSignal, delay?: number): Promise<void> {
  abort(signal);
  await new Promise<void>((resolve, reject) => {
    const timer = delay === undefined ? undefined : setTimeout(done, delay);
    function cleanup() {
      clearTimeout(timer);
      window.removeEventListener('online', done);
      document.removeEventListener('visibilitychange', visible);
      signal.removeEventListener('abort', cancelled);
    }
    function done() {
      cleanup();
      resolve();
    }
    function visible() {
      if (!document.hidden && navigator.onLine) done();
    }
    function cancelled() {
      cleanup();
      reject(signal.reason);
    }
    window.addEventListener('online', done);
    document.addEventListener('visibilitychange', visible);
    signal.addEventListener('abort', cancelled, { once: true });
  });
}
async function request(
  path: string,
  options: RequestInit,
  signal: AbortSignal,
  onPause: (paused: boolean) => void,
  persona: string,
): Promise<{ response: Response; data: Record<string, unknown> }> {
  for (let attempt = 0; ; attempt++) {
    while (!navigator.onLine) {
      onPause(true);
      await pause(signal);
    }
    onPause(false);
    abort(signal);
    try {
      const response = await fetch(withBase(path), {
        ...options,
        signal,
        credentials: 'same-origin',
        redirect: 'error',
        headers: {
          'X-Twin': '1',
          'X-Twin-Persona': persona,
          ...(options.body instanceof Blob
            ? { 'Content-Type': 'application/octet-stream' }
            : { 'Content-Type': 'application/json' }),
        },
      });
      const data = (await response.json()) as Record<string, unknown>;
      if (!response.ok) handleApiFailure(response.status, data);
      if (!response.ok && response.status !== 409)
        throw new ApiError(
          response.status,
          typeof data.detail === 'string' ? data.detail : '上传失败，请重试',
        );
      return { response, data };
    } catch (error) {
      abort(signal);
      if ((error instanceof ApiError && error.status < 500) || attempt >= 6)
        throw error;
      await pause(signal, Math.min(500 * 2 ** attempt, 15000));
    }
  }
}
function offsetOf(data: Record<string, unknown>, size: number): number {
  if (
    typeof data.offset !== 'number' ||
    !Number.isInteger(data.offset) ||
    data.offset < 0 ||
    data.offset > size
  )
    throw new Error('上传进度无效，请重新选择文件');
  return data.offset;
}

/** Upload a recording in resumable chunks. By default it becomes a memory of the current twin; with
 * `{ base: '/api/library/uploads', scope: 'library' }` it goes to the account's recording library instead
 * (`scope` keeps the resume records of the two apart). `compact` first makes material for memories smaller in the
 * browser (see `compactMedia`); leave it out for anything whose sound must stay as recorded. */
export async function uploadMedia(
  original: File,
  signal: AbortSignal,
  progress: (value: UploadProgress) => void,
  {
    base = '/api/uploads',
    scope,
    compact,
  }: { base?: string; scope?: string; compact?: Compaction } = {},
): Promise<Record<string, unknown>> {
  let file = original;
  let sha: string | undefined;
  if (compact && compactable(original, compact)) {
    const preparing = (done: number) =>
      progress({
        name: original.name,
        offset: 0,
        size: original.size,
        paused: false,
        preparing: done,
      });
    preparing(0);
    file = await compactMedia(original, compact, signal, preparing);
    if (file !== original) sha = await digest(file);
  }
  if (file.size > 4 * 1024 ** 3) throw new Error('音视频文件最多 4 GB');
  const persona = scope ?? getPersonaId();
  let offset = 0;
  const report = (paused = false) =>
    progress({ name: original.name, offset, size: file.size, paused });
  const send = (path: string, options: RequestInit = {}) =>
    request(path, options, signal, report, persona);
  let saved = savedUploads(persona).find((upload) =>
    matches(upload, file, sha),
  );
  report();
  if (saved) {
    try {
      const { data } = await send(`${base}/${saved.id}`);
      offset = offsetOf(data, file.size);
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) throw error;
      save(
        savedUploads(persona).filter((upload) => !matches(upload, file, sha)),
        persona,
      );
      saved = undefined;
    }
  }
  if (!saved) {
    const { data } = await send(base, {
      method: 'POST',
      body: JSON.stringify({
        filename: file.name,
        size: file.size,
        type: file.type,
      }),
    });
    if (typeof data.id !== 'string') throw new Error('无法创建上传，请重试');
    saved = {
      id: data.id,
      name: file.name,
      size: file.size,
      lastModified: file.lastModified,
      sha,
    };
    // A made-smaller file without its hash cannot be checked on resume, so it is not remembered.
    if (file === original || sha)
      save(
        [
          ...savedUploads(persona).filter(
            (upload) => !matches(upload, file, sha),
          ),
          saved,
        ],
        persona,
      );
  }
  report();
  let conflicts = 0;
  while (offset < file.size) {
    const { response, data } = await send(
      `${base}/${saved.id}?offset=${offset}`,
      {
        method: 'PUT',
        body: file.slice(offset, Math.min(offset + CHUNK_SIZE, file.size)),
      },
    );
    const next = offsetOf(data, file.size);
    if (response.status === 409) {
      if (++conflicts > 10) throw new Error('上传进度冲突，请重试');
    } else {
      if (next <= offset) throw new Error('上传没有完成，请重试');
      conflicts = 0;
    }
    offset = next;
    report();
  }
  const { data: filed } = await send(`${base}/${saved.id}/finish`, {
    method: 'POST',
  });
  save(
    savedUploads(persona).filter((upload) => upload.id !== saved.id),
    persona,
  );
  return filed;
}
