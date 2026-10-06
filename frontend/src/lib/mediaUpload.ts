import { ApiError, handleApiFailure } from './api';
import { getPersonaId, personaKey } from './persona';

const CHUNK_SIZE = 8 * 1024 * 1024;
const STORAGE_KEY = 'twin:media-uploads';
const extensions = new Set(
  'mp4 mov m4v webm mkv avi 3gp m4a mp3 wav aac ogg opus flac caf amr'.split(
    ' ',
  ),
);
export const isMedia = (file: File) =>
  extensions.has(file.name.split('.').at(-1)?.toLowerCase() ?? '');

interface SavedUpload {
  id: string;
  name: string;
  size: number;
  lastModified: number;
}
export interface UploadProgress {
  name: string;
  offset: number;
  size: number;
  paused: boolean;
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
function matches(upload: SavedUpload, file: File) {
  return (
    upload.name === file.name &&
    upload.size === file.size &&
    upload.lastModified === file.lastModified
  );
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
      const response = await fetch(path, {
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

export async function uploadMedia(
  file: File,
  signal: AbortSignal,
  progress: (value: UploadProgress) => void,
): Promise<void> {
  if (file.size > 4 * 1024 ** 3) throw new Error('音视频文件最多 4 GB');
  const persona = getPersonaId();
  let offset = 0;
  const report = (paused = false) =>
    progress({ name: file.name, offset, size: file.size, paused });
  const send = (path: string, options: RequestInit = {}) =>
    request(path, options, signal, report, persona);
  let saved = savedUploads(persona).find((upload) => matches(upload, file));
  report();
  if (saved) {
    try {
      const { data } = await send(`/api/uploads/${saved.id}`);
      offset = offsetOf(data, file.size);
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) throw error;
      save(
        savedUploads(persona).filter((upload) => !matches(upload, file)),
        persona,
      );
      saved = undefined;
    }
  }
  if (!saved) {
    const { data } = await send('/api/uploads', {
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
    };
    save(
      [
        ...savedUploads(persona).filter((upload) => !matches(upload, file)),
        saved,
      ],
      persona,
    );
  }
  report();
  let conflicts = 0;
  while (offset < file.size) {
    const { response, data } = await send(
      `/api/uploads/${saved.id}?offset=${offset}`,
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
  await send(`/api/uploads/${saved.id}/finish`, { method: 'POST' });
  save(
    savedUploads(persona).filter((upload) => upload.id !== saved.id),
    persona,
  );
}
