import { waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { uploadMedia, type UploadProgress } from '../lib/mediaUpload';
import { useAuth } from '../stores/auth';
import { resetUploads, useUploadStore } from '../stores/uploads';

vi.mock('../lib/mediaUpload', async (original) => ({
  ...(await original<typeof import('../lib/mediaUpload')>()),
  uploadMedia: vi.fn(),
}));

interface Upload {
  signal: AbortSignal;
  progress: (progress: UploadProgress) => void;
  resolve: (value: Record<string, unknown>) => void;
  reject: (error: Error) => void;
}
let uploads: Upload[];
const media = (name: string) => new File(['audio'], `${name}.m4a`);
const identity = (email: string) => ({
  email,
  admin: false,
  auth_enabled: true,
});
beforeEach(() => {
  resetUploads();
  uploads = [];
  useAuth.setState({ identity: identity('first@example.test') });
  vi.mocked(uploadMedia).mockImplementation(
    (_file, signal, progress) =>
      new Promise((resolve, reject) => {
        // A response already received, or media preparation that cannot stop at once, may finish after abort.
        uploads.push({ signal, progress, resolve, reject });
      }),
  );
});

const switchAccount = () => {
  useAuth.setState({ identity: null });
  useAuth.setState({ identity: identity('second@example.test') });
};

it.each(['success', 'failure', 'abort'] as const)(
  'does not let an old account upload finish over the new account (%s)',
  async (outcome) => {
    const old = useUploadStore.getState().add([media('旧账号会议')]);
    const previous = uploads[0];
    switchAccount();
    expect(previous.signal.aborted).toBe(true);
    const currentFile = media('当前账号会议');
    const current = useUploadStore.getState().add([currentFile]);
    if (outcome === 'success') previous.resolve({ mine: false });
    else
      previous.reject(
        outcome === 'abort'
          ? new DOMException('上传已取消', 'AbortError')
          : new Error('旧账号上传失败'),
      );
    await old;
    expect(useUploadStore.getState()).toMatchObject({
      uploading: true,
      notice: '',
      changes: 0,
      picks: [{ file: currentFile }],
    });
    // The old run must not release the new run's lock: further files still queue behind its active upload.
    const queued = useUploadStore.getState().add([media('下一段会议')]);
    expect(uploads).toHaveLength(2);
    uploads[1].resolve({ mine: true });
    await waitFor(() => expect(uploads).toHaveLength(3));
    uploads[2].resolve({ mine: true });
    await Promise.all([current, queued]);
    expect(useUploadStore.getState()).toMatchObject({
      uploading: false,
      notice: '',
      changes: 2,
    });
  },
);

it('discards late progress even when the next account picks the same File object', async () => {
  const sharedFile = media('同一文件');
  const old = useUploadStore.getState().add([sharedFile]);
  const previous = uploads[0];
  switchAccount();
  const current = useUploadStore.getState().add([sharedFile]);
  previous.progress({
    name: sharedFile.name,
    offset: 4,
    size: 5,
    paused: false,
  });
  expect(useUploadStore.getState().picks[0].progress).toBeUndefined();
  previous.resolve({ mine: false });
  await old;
  expect(useUploadStore.getState().picks[0].done).toBeUndefined();
  uploads[1].resolve({ mine: true });
  await current;
});

it('leaves a signed-out upload store empty when the old request finishes', async () => {
  const old = useUploadStore.getState().add([media('私有会议')]);
  useAuth.setState({ identity: null });
  uploads[0].resolve({ mine: false });
  await old;
  expect(useUploadStore.getState()).toMatchObject({
    picks: [],
    uploading: false,
    notice: '',
    changes: 0,
  });
});

it('still starts newly added files after a stopped upload finishes cancelling', async () => {
  const sending = useUploadStore
    .getState()
    .add([media('正在发送'), media('尚未发送')]);
  const stopped = uploads[0];
  useUploadStore.getState().stop();
  const added = useUploadStore.getState().add([media('新加的录音')]);
  expect(uploads).toHaveLength(1);
  expect(
    useUploadStore
      .getState()
      .picks.slice(0, 2)
      .map((pick) => pick.stopped),
  ).toEqual([true, true]);
  stopped.reject(new DOMException('上传已取消', 'AbortError'));
  await waitFor(() => expect(uploads).toHaveLength(2));
  uploads[1].resolve({ mine: true });
  await Promise.all([sending, added]);
  expect(useUploadStore.getState()).toMatchObject({
    uploading: false,
    changes: 1,
  });
  expect(useUploadStore.getState().picks[2].done).toBe(true);
});
