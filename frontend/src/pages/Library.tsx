import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { Upload } from 'lucide-react';
import {
  Badge,
  Button,
  EmptyState,
  Meter,
  Skeleton,
  useConfirm,
  type Tone,
} from '../components/ui';
import { StageHeader } from '../components/layout/StageHeader';
import { api } from '../lib/api';
import { Team } from '../features/library/Team';
import { isMedia, uploadMedia, type UploadProgress } from '../lib/mediaUpload';

export interface Recording {
  id: string;
  filename: string;
  size: number;
  kind: 'audio' | 'video';
  status: 'queued' | 'transcribing' | 'ready' | 'failed';
  error: string;
  duration_s: number | null;
  transcribed_s: number;
  speakers: number;
  segments: number;
  created_at: string;
}
export interface LibraryState {
  recordings: Recording[];
  pending: number;
  max_pending: number;
  asr: boolean;
  capacity: {
    free_bytes: number;
    arriving_bytes: number;
    arriving: number;
    headroom_bytes: number;
  };
}
interface Pick {
  file: File;
  progress?: UploadProgress;
  error?: string;
  done?: boolean;
}

const LIBRARY_UPLOADS = { base: '/api/library/uploads', scope: 'library' };
const statusLabel: Record<Recording['status'], [string, Tone]> = {
  queued: ['排队中', 'neutral'],
  transcribing: ['转写中', 'info'],
  ready: ['已转写', 'success'],
  failed: ['失败', 'danger'],
};
const gb = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(1)} GB`;
const minutes = (seconds: number | null) =>
  seconds === null ? '' : `${Math.max(1, Math.round(seconds / 60))} 分钟`;

export function Library() {
  const [library, setLibrary] = useState<LibraryState | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [picks, setPicks] = useState<Pick[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const controller = useRef<AbortController | null>(null);
  const confirm = useConfirm();

  // Bumped on every reload, so the people and review lists follow new transcripts.
  const [version, setVersion] = useState(0);
  const load = useCallback(async () => {
    try {
      setLibrary(await api<LibraryState>('/api/library'));
      setVersion((v) => v + 1);
      setError('');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '无法加载录音库');
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const busy = uploading || !!library?.pending;
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => void load(), 3000);
    return () => clearInterval(timer);
  }, [busy, load]);
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
    for (const pick of queue) {
      if (abort.signal.aborted) break;
      try {
        await uploadMedia(
          pick.file,
          abort.signal,
          (progress) => update(pick, { progress }),
          LIBRARY_UPLOADS,
        );
        update(pick, { done: true });
      } catch (failure) {
        if (failure instanceof DOMException && failure.name === 'AbortError')
          break;
        update(pick, {
          error: failure instanceof Error ? failure.message : '上传失败',
        });
      }
      void load();
    }
    setUploading(false);
  };

  const retry = async (recording: Recording) => {
    try {
      await api(`/api/library/recordings/${recording.id}/retry`, {
        method: 'POST',
      });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '重试失败');
    }
    await load();
  };
  const remove = async (recording: Recording) => {
    if (
      !(await confirm({
        title: `删除「${recording.filename}」？`,
        body: '转写结果和试听文件会一起删除，不能恢复',
        confirmLabel: '删除录音',
        tone: 'danger',
      }))
    )
      return;
    try {
      await api(`/api/library/recordings/${recording.id}`, {
        method: 'DELETE',
      });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '删除失败');
    }
    await load();
  };

  const capacity = library?.capacity;
  const room = capacity
    ? capacity.free_bytes - capacity.arriving_bytes - capacity.headroom_bytes
    : 0;
  const unfinished = picks.filter((p) => !p.done);
  return (
    <div className="library-page">
      <StageHeader
        variant="brand"
        intro={
          <p className="stage-caption">
            上传会议录音，自动区分并认出每个人，新出现的人自动建档。
          </p>
        }
      />
      <div className="page-content space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <h2 className="text-2xl font-semibold">录音库</h2>
          <Link to="/twins" className="text-sm text-accent underline">
            返回我的分身
          </Link>
        </header>
        <p className="text-sm text-secondary">
          只有你的账号能看到这里的录音。转写完成并校验后，原始文件会删除以节省空间，保留转写稿和试听用的音频。
        </p>
        {error && (
          <p role="alert" className="text-danger">
            {error}
          </p>
        )}
        {notice && (
          <p role="status" className="text-sm text-secondary">
            {notice}
          </p>
        )}
        {library && !library.asr && (
          <p role="status" className="rounded-xl bg-note p-4 text-sm">
            还没有配置能区分说话人的转写服务（asr-funasr），录音会先排队，配置后自动开始转写。
          </p>
        )}
        <section
          aria-label="添加录音"
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            void add(Array.from(event.dataTransfer.files));
          }}
          className={`flex flex-col items-center gap-3 rounded-xl border-2 border-dashed p-8 text-center ${dragging ? 'border-accent bg-soft' : 'border-primary'}`}
        >
          <Upload aria-hidden className="size-8" />
          <p>把会议录音拖到这里，或</p>
          <Button disabled={uploading} onClick={() => input.current?.click()}>
            选择文件
          </Button>
          <input
            ref={input}
            type="file"
            multiple
            accept="audio/*,video/*,.mkv,.caf,.amr,.opus,.m4a"
            className="sr-only"
            aria-label="选择录音文件"
            onChange={(event) => {
              const files = Array.from(event.currentTarget.files ?? []);
              event.currentTarget.value = '';
              void add(files);
            }}
          />
          {library && capacity && (
            <p className="text-sm text-secondary">
              排队 {library.pending} / {library.max_pending} 个 · 还可添加约{' '}
              {gb(Math.max(0, room))}（保留 {gb(capacity.headroom_bytes)}{' '}
              安全余量）
            </p>
          )}
        </section>
        {unfinished.length > 0 && (
          <section aria-label="上传进度" className="space-y-3">
            {unfinished.map((pick) => (
              <div
                key={`${pick.file.name}-${pick.file.lastModified}-${pick.file.size}`}
                className="rounded-xl bg-surface p-4"
              >
                {pick.error ? (
                  <p className="text-sm">
                    {pick.file.name}：
                    <span className="text-danger">{pick.error}</span>
                  </p>
                ) : (
                  <Meter
                    label={
                      pick.progress?.paused
                        ? `${pick.file.name}（网络中断，恢复后继续）`
                        : pick.file.name
                    }
                    value={
                      pick.progress
                        ? (pick.progress.offset / pick.progress.size) * 100
                        : 0
                    }
                  />
                )}
              </div>
            ))}
            {uploading && (
              <Button
                variant="ghost"
                onClick={() => controller.current?.abort()}
              >
                停止上传（已传的部分下次接着传）
              </Button>
            )}
          </section>
        )}
        <Team version={version} />
        {!library ? (
          <Skeleton className="h-32" />
        ) : library.recordings.length === 0 ? (
          <EmptyState
            title="还没有录音"
            body="添加会议录音后，会自动转写并区分每位说话人。"
          />
        ) : (
          <ul aria-label="录音列表" className="space-y-3">
            {library.recordings.map((recording) => {
              const [label, tone] = statusLabel[recording.status];
              return (
                <li
                  key={recording.id}
                  className="flex flex-wrap items-center gap-3 rounded-xl bg-surface p-4"
                >
                  <div className="min-w-0 flex-1 space-y-1">
                    {recording.status === 'ready' ? (
                      <Link
                        to={`/library/${encodeURIComponent(recording.id)}`}
                        className="block truncate font-medium text-accent underline"
                        title={recording.filename}
                      >
                        {recording.filename}
                      </Link>
                    ) : (
                      <p
                        className="truncate font-medium"
                        title={recording.filename}
                      >
                        {recording.filename}
                      </p>
                    )}
                    <p className="text-sm text-secondary">
                      {[
                        minutes(recording.duration_s),
                        recording.status === 'ready'
                          ? `${recording.speakers} 位说话人`
                          : '',
                        recording.status === 'transcribing' &&
                        recording.duration_s
                          ? `已转写 ${Math.round((recording.transcribed_s / recording.duration_s) * 100)}%`
                          : '',
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </p>
                    {recording.error && (
                      <p className="text-sm text-danger">{recording.error}</p>
                    )}
                  </div>
                  <Badge tone={tone}>{label}</Badge>
                  {recording.status === 'failed' && (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => void retry(recording)}
                    >
                      重试
                    </Button>
                  )}
                  {recording.status !== 'transcribing' && (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`删除${recording.filename}`}
                      onClick={() => void remove(recording)}
                    >
                      删除
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
