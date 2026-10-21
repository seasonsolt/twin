import { useEffect, useRef, useState } from 'react';
import {
  isMedia,
  uploadMedia,
  type UploadProgress,
} from '../../lib/mediaUpload';

export interface Pick {
  file: File;
  progress?: UploadProgress;
  error?: string;
  done?: boolean;
}

// Library recordings only feed memories: their sound may be made smaller before it is sent.
const LIBRARY_UPLOADS = {
  base: '/api/library/uploads',
  scope: 'library',
  compact: 'audio-and-video',
} as const;

const same = (a: File, b: File) =>
  a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;

/** Uploading recordings to the team's library, one file at a time; ``changed`` runs after each file. Files added
 * while others are still uploading join the end of the queue instead of waiting for the picker to free up. */
export function useUploads(changed: () => void) {
  const [picks, setPicks] = useState<Pick[]>([]);
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState('');
  const controller = useRef<AbortController | null>(null);
  // Files waiting their turn and the one being sent (null between runs): refs, so files added mid-run join it.
  const queue = useRef<Pick[]>([]);
  const active = useRef<File | null>(null);
  const running = useRef(false);
  useEffect(() => () => controller.current?.abort(), []);

  const update = (pick: Pick, change: Partial<Pick>) =>
    setPicks((current) =>
      current.map((p) => (p.file === pick.file ? { ...p, ...change } : p)),
    );

  const run = async () => {
    running.current = true;
    setUploading(true);
    const abort = new AbortController();
    controller.current = abort;
    // One file at a time: the server admits each against free space and the queue limit.
    const theirs: string[] = [];
    while (!abort.signal.aborted) {
      const pick = queue.current.shift();
      if (!pick) break;
      active.current = pick.file;
      try {
        const filed = await uploadMedia(
          pick.file,
          abort.signal,
          (progress) => update(pick, { progress }),
          LIBRARY_UPLOADS,
        );
        // The same meeting a colleague uploaded first stays theirs to sort out.
        if (filed.mine === false) theirs.push(pick.file.name);
        update(pick, { done: true });
      } catch (failure) {
        if (failure instanceof DOMException && failure.name === 'AbortError')
          break;
        update(pick, {
          error: failure instanceof Error ? failure.message : '上传失败',
        });
      }
      changed();
    }
    active.current = null;
    if (theirs.length)
      setNotice(
        `${theirs.map((name) => `「${name}」`).join('')}已经有同事上传过，由 TA 整理`,
      );
    running.current = false;
    setUploading(false);
    // Files added after a stop, while the stopped file was still winding down, start a run of their own.
    if (queue.current.length) await run();
  };

  const add = async (files: File[]) => {
    const media = files.filter(isMedia);
    const skipped = files.length - media.length;
    setNotice(skipped ? `已跳过 ${skipped} 个不是音视频的文件` : '');
    // A file already waiting or uploading is not sent twice.
    const fresh = media.filter(
      (file) =>
        !queue.current.some((p) => same(p.file, file)) &&
        !(active.current && same(active.current, file)),
    );
    if (!fresh.length) return;
    const added: Pick[] = fresh.map((file) => ({ file }));
    queue.current.push(...added);
    setPicks((current) => [
      ...current.filter(
        (p) => !p.done && !added.some((a) => same(a.file, p.file)),
      ),
      ...added,
    ]);
    if (!running.current) await run();
  };

  return {
    add,
    uploading,
    notice,
    unfinished: picks.filter((p) => !p.done),
    // What had not started stays listed, to be added again; a started file resumes where it was.
    stop: () => {
      queue.current = [];
      controller.current?.abort();
    },
  };
}
