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

/** Uploading recordings to the team's library, one file at a time; ``changed`` runs after each file. */
export function useUploads(changed: () => void) {
  const [picks, setPicks] = useState<Pick[]>([]);
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState('');
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  const add = async (files: File[]) => {
    const media = files.filter(isMedia);
    const skipped = files.length - media.length;
    setNotice(skipped ? `已跳过 ${skipped} 个不是音视频的文件` : '');
    if (!media.length) return;
    const queue: Pick[] = media.map((file) => ({ file }));
    setPicks((current) => [...current.filter((p) => !p.done), ...queue]);
    setUploading(true);
    const abort = new AbortController();
    controller.current = abort;
    const update = (pick: Pick, change: Partial<Pick>) =>
      setPicks((current) =>
        current.map((p) => (p.file === pick.file ? { ...p, ...change } : p)),
      );
    // One file at a time: the server admits each against free space and the queue limit.
    const theirs: string[] = [];
    for (const pick of queue) {
      if (abort.signal.aborted) break;
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
    if (theirs.length)
      setNotice(
        `${theirs.map((name) => `「${name}」`).join('')}已经有同事上传过，由 TA 整理`,
      );
    setUploading(false);
  };

  return {
    add,
    uploading,
    notice,
    unfinished: picks.filter((p) => !p.done),
    stop: () => controller.current?.abort(),
  };
}
