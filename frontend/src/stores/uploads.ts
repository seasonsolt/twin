import { create } from 'zustand';
import { isMedia, uploadMedia, type UploadProgress } from '../lib/mediaUpload';

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

interface Uploads {
  picks: Pick[];
  uploading: boolean;
  notice: string;
  /** Bumped after each file is filed or fails: pages showing the library reload then. */
  changes: number;
  add: (files: File[]) => Promise<void>;
  /** What had not started stays listed, to be added again; a started file resumes where it was. */
  stop: () => void;
}

// Files waiting their turn and the one being sent (null between runs): outside the state, so files added mid-run
// join it.
let queue: Pick[] = [];
let active: File | null = null;
let running = false;
let controller: AbortController | null = null;

/** Uploading recordings to the team's library, one file at a time, for the whole app: an upload started from the
 * side bar or a page goes on while the person moves between pages. Files added while others are still uploading
 * join the end of the queue instead of waiting for the picker to free up. */
export const useUploadStore = create<Uploads>((set, get) => {
  const update = (pick: Pick, change: Partial<Pick>) =>
    set((state) => ({
      picks: state.picks.map((p) =>
        p.file === pick.file ? { ...p, ...change } : p,
      ),
    }));

  const run = async (): Promise<void> => {
    running = true;
    set({ uploading: true });
    const abort = new AbortController();
    controller = abort;
    // One file at a time: the server admits each against free space and the queue limit.
    const theirs: string[] = [];
    while (!abort.signal.aborted) {
      const pick = queue.shift();
      if (!pick) break;
      active = pick.file;
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
      set((state) => ({ changes: state.changes + 1 }));
    }
    active = null;
    if (theirs.length)
      set({
        notice: `${theirs.map((name) => `「${name}」`).join('')}已经有同事上传过，由 TA 整理`,
      });
    running = false;
    set({ uploading: false });
    // Files added after a stop, while the stopped file was still winding down, start a run of their own.
    if (queue.length) await run();
  };

  return {
    picks: [],
    uploading: false,
    notice: '',
    changes: 0,
    add: async (files) => {
      const media = files.filter(isMedia);
      const skipped = files.length - media.length;
      set({ notice: skipped ? `已跳过 ${skipped} 个不是音视频的文件` : '' });
      // A file already waiting or uploading is not sent twice.
      const fresh = media.filter(
        (file) =>
          !queue.some((p) => same(p.file, file)) &&
          !(active && same(active, file)),
      );
      if (!fresh.length) return;
      const added: Pick[] = fresh.map((file) => ({ file }));
      queue.push(...added);
      set({
        picks: [
          ...get().picks.filter(
            (p) => !p.done && !added.some((a) => same(a.file, p.file)),
          ),
          ...added,
        ],
      });
      if (!running) await run();
    },
    stop: () => {
      queue = [];
      controller?.abort();
    },
  };
});

/** Back to no uploads at all, as on a fresh load (tests start each case from here). */
export function resetUploads() {
  controller?.abort();
  queue = [];
  active = null;
  running = false;
  controller = null;
  useUploadStore.setState({
    picks: [],
    uploading: false,
    notice: '',
    changes: 0,
  });
}
