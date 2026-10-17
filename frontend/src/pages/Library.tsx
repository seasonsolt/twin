import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { Upload } from 'lucide-react';
import {
  Badge,
  Button,
  EmptyState,
  Skeleton,
  useConfirm,
  type Tone,
} from '../components/ui';
import { StageHeader } from '../components/layout/StageHeader';
import { api } from '../lib/api';
import { UploadList } from '../features/library/UploadList';
import { MEDIA_ACCEPT, useUploads } from '../features/library/useUploads';

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
  // Who the speakers were recognised as, and how many still wait for the owner.
  people: string[];
  unsettled: number;
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
const statusLabel: Record<Recording['status'], [string, Tone]> = {
  queued: ['排队中', 'neutral'],
  transcribing: ['转写中', 'info'],
  ready: ['已转写', 'success'],
  failed: ['失败', 'danger'],
};
/** A transcribed recording is described by how far its speakers are identified. */
function identityLabel(recording: Recording): [string, Tone] {
  if (recording.status !== 'ready') return statusLabel[recording.status];
  if (!recording.unsettled) return ['已认人', 'success'];
  return recording.unsettled === recording.speakers
    ? ['还没认人', 'warning']
    : [`${recording.unsettled} 位待确认`, 'warning'];
}
const gb = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(1)} GB`;
const minutes = (seconds: number | null) =>
  seconds === null ? '' : `${Math.max(1, Math.round(seconds / 60))} 分钟`;

export function Library() {
  const [library, setLibrary] = useState<LibraryState | null>(null);
  const [error, setError] = useState('');
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const confirm = useConfirm();

  const load = useCallback(async () => {
    try {
      setLibrary(await api<LibraryState>('/api/library'));
      setError('');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '无法加载录音库');
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const { add, uploading, notice, unfinished, stop } = useUploads(
    () => void load(),
  );
  const busy = uploading || !!library?.pending;
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => void load(), 3000);
    return () => clearInterval(timer);
  }, [busy, load]);

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
  return (
    <div className="library-page">
      <StageHeader
        variant="brand"
        intro={
          <p className="stage-caption">
            全部会议录音：上传、转写进度和每段录音的说话人。
          </p>
        }
      />
      <div className="page-content space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <h2 className="text-2xl font-semibold">录音库</h2>
          <Link to="/team" className="text-sm text-accent underline">
            返回团队
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
            accept={MEDIA_ACCEPT}
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
        <UploadList picks={unfinished} uploading={uploading} onStop={stop} />
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
              const [label, tone] = identityLabel(recording);
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
                        recording.people.join('、'),
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
