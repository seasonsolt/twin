import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router';
import { Check, MoreHorizontal, Plus, Video, AudioLines } from 'lucide-react';
import { StageHeader } from '../components/layout/StageHeader';
import { PersonaSwitcher } from '../components/layout/PersonaSwitcher';
import { useMobile } from '../lib/useMobile';
import { MessageList } from '../components/effects/MessageList';
import { ThinkingLabel } from '../components/effects/ThinkingLabel';
import { LayoutScope } from '../components/motion';
import {
  Badge,
  Button,
  Card,
  Dialog,
  EmptyState,
  IconButton,
  Tabs,
  Textarea,
  toast,
  useConfirm,
} from '../components/ui';
import { api } from '../lib/api';
import {
  isMedia,
  uploadMedia,
  uploadForm,
  type UploadProgress,
} from '../lib/mediaUpload';
import { usePendingWork } from '../lib/pendingWork';
import { useStatus } from '../stores/status';
import { MediaClaim } from '../features/sources/MediaClaim';

const accept =
  '.txt,.md,.pdf,.docx,.html,.htm,.csv,.json,.srt,.vtt,audio/*,video/*,.mkv,.caf,.amr,.opus';
export interface Memory {
  source_id: string;
  title: string;
  first_date: string | null;
  detected_kind_label: string;
  status:
    | 'processing'
    | 'remembered'
    | 'nothing_found'
    | 'failed'
    | 'queued'
    | 'extracting'
    | 'transcribing'
    | 'needs_asr'
    | 'needs_speaker';
  remembered: number;
  kind?: string;
  duration_s?: number | null;
  transcribed_s?: number;
  media_sha?: string | null;
  candidates_pending?: boolean;
}
interface Processing {
  state: 'idle' | 'queued' | 'running';
  last_error?: string | null;
}

const mediaPending = (memory: Memory) =>
  ['queued', 'extracting', 'transcribing'].includes(memory.status);
const memoryPending = (memory: Memory) =>
  memory.status === 'processing' ||
  (memory.candidates_pending &&
    !['failed', 'needs_asr', 'needs_speaker'].includes(memory.status));
function MemoryWork({
  memory,
  visible,
  busy,
  onRetry,
}: {
  memory: Memory;
  visible: boolean;
  busy: boolean;
  onRetry: () => void;
}) {
  const pending = mediaPending(memory);
  const label =
    memory.status === 'transcribing'
      ? `正在转写 ${((memory.transcribed_s ?? 0) / 60).toFixed(1)}/${((memory.duration_s ?? 0) / 60).toFixed(1)} 分钟…`
      : memory.status === 'extracting'
        ? '正在提取音频…'
        : '等待转写…';
  usePendingWork(pending, label, true);
  if (visible && ['failed', 'needs_asr'].includes(memory.status))
    return (
      <p role="alert" className="text-sm text-danger">
        {memory.title} ·{' '}
        {memory.status === 'needs_asr' ? '需要配置语音识别' : '处理失败'}
        <Button variant="ghost" disabled={busy} onClick={onRetry}>
          重试
        </Button>
      </p>
    );
  return visible && pending ? (
    <p role="status" aria-busy="true" className="text-sm text-secondary">
      {memory.title} · {label}
    </p>
  ) : null;
}

export function Memories({ embedded = false }: { embedded?: boolean }) {
  const active = useLocation().pathname === '/memories' || embedded;
  const confirm = useConfirm();
  const mobile = useMobile();
  const [adding, setAdding] = useState(false);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [processing, setProcessing] = useState<Processing>({ state: 'idle' });
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [busyLabel, setBusyLabel] = useState('正在保存记忆…');
  const [error, setError] = useState('');
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(
    null,
  );
  usePendingWork(busy, busyLabel);
  const building = processing.state !== 'idle' || memories.some(memoryPending);
  usePendingWork(building, '正在整理记忆…', true);
  const failedFiles = useRef<File[]>([]);
  const [skipped, setSkipped] = useState<{ file: string; reason: string }[]>(
    [],
  );
  const [preview, setPreview] = useState<{
    memory: Memory;
    title: string;
    text: string;
  } | null>(null);
  const alive = useRef(false);
  const request = useRef<AbortController | null>(null);
  const previewRequest = useRef<AbortController | null>(null);
  const mutation = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refresh = useCallback(async function reload() {
    request.current?.abort();
    if (timer.current) clearTimeout(timer.current);
    const controller = new AbortController();
    request.current = controller;
    try {
      const [rows, state] = await Promise.all([
        api<Memory[]>('/api/persona/sources', { signal: controller.signal }),
        api<Processing>('/api/persona/processing', {
          signal: controller.signal,
        }),
      ]);
      if (!alive.current || controller.signal.aborted) return;
      setMemories(rows);
      setProcessing(state);
      setError('');
      if (
        state.state !== 'idle' ||
        rows.some((row) => mediaPending(row) || memoryPending(row))
      )
        timer.current = setTimeout(() => void reload(), 2000);
      else void useStatus.getState().refresh();
    } catch (err) {
      if (alive.current && !controller.signal.aborted) {
        setError(err instanceof Error ? err.message : '无法读取记忆');
        timer.current = setTimeout(() => void reload(), 2000);
      }
    }
  }, []);
  useEffect(() => {
    alive.current = active;
    if (active) void refresh();
    return () => {
      alive.current = false;
      request.current?.abort();
      previewRequest.current?.abort();
      mutation.current?.abort();
      if (timer.current) clearTimeout(timer.current);
    };
  }, [active, refresh]);

  const mutate = async (
    fn: (signal: AbortSignal) => Promise<unknown>,
    added = false,
    label = '正在保存记忆…',
  ) => {
    if (mutation.current) return;
    const controller = new AbortController();
    mutation.current = controller;
    setBusy(true);
    setBusyLabel(label);
    setError('');
    try {
      await fn(controller.signal);
      if (!alive.current) return;
      if (added) toast('已添加，正在记住…', 'success');
      await refresh();
    } catch (err) {
      if (alive.current)
        setError(err instanceof Error ? err.message : '操作失败，请重试');
    } finally {
      mutation.current = null;
      if (alive.current) setBusy(false);
    }
  };
  const upload = (files: File[]) =>
    void mutate(
      async (signal) => {
        if (!files.length) return;
        failedFiles.current = files;
        const documents: File[] = [];
        const ignored: { file: string; reason: string }[] = [];
        try {
          let completed = 0;
          for (const file of files) {
            setBusyLabel(`正在上传 ${completed + 1}/${files.length}…`);
            if (
              (file.webkitRelativePath || file.name)
                .split('/')
                .some((part) => part.startsWith('.'))
            ) {
              ignored.push({ file: file.name, reason: '已跳过隐藏文件' });
              completed++;
            } else if (isMedia(file)) {
              await uploadMedia(file, signal, (value) => {
                if (alive.current) setUploadProgress(value);
              });
              completed++;
              await refresh();
            } else documents.push(file);
          }
          if (documents.length) {
            const form = new FormData();
            documents.forEach((file) =>
              form.append('files', file, file.webkitRelativePath || file.name),
            );
            const size = documents.reduce((sum, file) => sum + file.size, 0);
            setBusyLabel(`正在上传 ${completed + 1}/${files.length}…`);
            setUploadProgress({
              name: documents.map((file) => file.name).join('、'),
              offset: 0,
              size,
              paused: false,
            });
            const result = await uploadForm<{
              imported: Memory[];
              skipped: { file: string; reason: string }[];
            }>('/api/persona/import', form, signal, (percent) => {
              if (!alive.current) return;
              setUploadProgress({
                name: documents.map((file) => file.name).join('、'),
                offset: (size * percent) / 100,
                size,
                paused: false,
              });
              setBusyLabel(
                percent === 100
                  ? '正在处理文件…'
                  : `正在上传 ${completed + Math.min(documents.length, Math.floor((documents.length * percent) / 100) + 1)}/${files.length}…`,
              );
            });
            ignored.push(...result.skipped);
            if (alive.current && result.imported.length)
              toast('已添加，正在记住…', 'success');
          }
          failedFiles.current = [];
          if (alive.current) setSkipped(ignored);
        } finally {
          if (alive.current) setUploadProgress(null);
        }
      },
      false,
      `正在上传 1/${files.length}…`,
    );
  const retry = () =>
    void mutate((signal) =>
      api('/api/persona/build', { method: 'POST', signal }),
    );
  const retranscribe = (memory: Memory) =>
    void mutate((signal) =>
      api(
        `/api/persona/sources/${encodeURIComponent(memory.source_id)}/transcribe`,
        { method: 'POST', signal },
      ),
    );
  const progressUI = uploadProgress && (
    <div
      role="status"
      className="space-y-2 rounded-lg border border-border p-3"
    >
      <p className="truncate font-medium">{uploadProgress.name}</p>
      <p className="text-sm text-secondary">
        {uploadProgress.paused
          ? '网络已断开，联网后继续上传'
          : '上传中，请保持页面打开'}
      </p>
      <progress
        className="h-2 w-full"
        aria-label="上传进度"
        max={uploadProgress.size || 1}
        value={uploadProgress.offset}
      />
      <p className="text-sm text-secondary">
        上传中{' '}
        {Math.floor((uploadProgress.offset / (uploadProgress.size || 1)) * 100)}
        % · {(uploadProgress.offset / 1024 ** 2).toFixed(1)} /{' '}
        {(uploadProgress.size / 1024 ** 2).toFixed(1)} MB
      </p>
    </div>
  );
  const view = async (memory: Memory) => {
    previewRequest.current?.abort();
    const controller = new AbortController();
    previewRequest.current = controller;
    setPreview({ memory, title: memory.title, text: '正在读取…' });
    try {
      const value = await api<string>(
        `/api/persona/sources/${encodeURIComponent(memory.source_id)}/text`,
        { responseType: 'text', signal: controller.signal },
      );
      if (alive.current && !controller.signal.aborted)
        setPreview({ memory, title: memory.title, text: value });
    } catch (err) {
      if (alive.current && !controller.signal.aborted)
        setPreview({
          memory,
          title: memory.title,
          text: err instanceof Error ? err.message : '读取失败',
        });
    }
  };
  const addPanel = useRef<HTMLElement>(null);
  const openAdd = () => {
    if (mobile) setAdding(true);
    else {
      addPanel.current?.scrollIntoView?.({
        block: 'center',
        behavior: 'instant',
      });
      addPanel.current?.querySelector<HTMLElement>('textarea, input')?.focus();
    }
  };
  const recordingHours =
    memories.reduce((total, memory) => total + (memory.duration_s ?? 0), 0) /
    3600;
  const fileInput = (folder: boolean) => (
    <div
      aria-busy={busy}
      className={`space-y-3 rounded-lg border border-dashed border-border p-6 ${busy ? 'opacity-60' : ''}`}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        if (!busy) upload(Array.from(event.dataTransfer.files));
      }}
    >
      <p className="text-sm text-secondary">
        {folder
          ? '选择文件夹，自动跳过隐藏文件和不支持的格式。'
          : '拖放文件到这里，或选择多个文件。'}
      </p>
      <input
        type="file"
        aria-label={folder ? '选择文件夹' : '选择文件'}
        multiple
        accept={accept}
        disabled={busy}
        className="min-h-11 max-w-full text-base"
        {...(folder ? { webkitdirectory: '' } : {})}
        onChange={(event) => {
          upload(Array.from(event.target.files ?? []));
          event.target.value = '';
        }}
      />
      <p className="text-xs text-tertiary">
        TXT、Markdown、PDF、Word、HTML、CSV、JSON、SRT、VTT；每个文件最多 50
        MB。音频、视频最多 4 GB，支持断点续传。刷新后重新选择同一文件即可继续。
      </p>
    </div>
  );
  const addContent = (
    <>
      <Tabs
        items={[
          {
            value: 'note',
            label: '写一段',
            content: (
              <form
                aria-busy={busy}
                className={`space-y-3 ${busy ? 'opacity-60' : ''}`}
                onSubmit={(event) => {
                  event.preventDefault();
                  const saved = text;
                  void mutate(async (signal) => {
                    await api('/api/persona/notes', {
                      signal,
                      method: 'POST',
                      json: { text: saved },
                    });
                    if (alive.current) {
                      setText('');
                      setAdding(false);
                    }
                  }, true);
                }}
              >
                <Textarea
                  aria-label="要记住的文字"
                  maxLength={20000}
                  value={text}
                  disabled={busy}
                  onChange={(event) => setText(event.target.value)}
                  placeholder="写下你的经历、想法或偏好…"
                />
                <Button
                  type="submit"
                  className="min-h-11"
                  loading={busy}
                  disabled={!text.trim()}
                >
                  {busy ? busyLabel : '保存'}
                </Button>
              </form>
            ),
          },
          { value: 'files', label: '上传文件', content: fileInput(false) },
          { value: 'folder', label: '上传文件夹', content: fileInput(true) },
        ]}
      />
      {mobile && progressUI}
      {skipped.length > 0 && (
        <ul aria-label="跳过的文件" className="mt-3 text-sm text-secondary">
          {skipped.map((row, i) => (
            <li key={i}>
              {row.file}：{row.reason}
            </li>
          ))}
        </ul>
      )}
    </>
  );
  const remove = async (memory: Memory) => {
    if (
      (await confirm({
        title: '删除记忆？',
        body: `删除“${memory.title}”？删除后会自动重新处理。`,
        confirmLabel: '确认删除',
        tone: 'danger',
      })) &&
      alive.current
    )
      await mutate((signal) =>
        api(`/api/persona/sources/${encodeURIComponent(memory.source_id)}`, {
          method: 'DELETE',
          signal,
        }),
      );
  };
  return (
    <div className="memories-page">
      {!embedded && (
        <StageHeader
          left={<PersonaSwitcher stage />}
          right={
            mobile ? undefined : (
              <button
                type="button"
                className="stage-add"
                aria-label="从舞台添加记忆"
                onClick={openAdd}
              >
                <Plus size={24} aria-hidden />
              </button>
            )
          }
        />
      )}
      <div
        className={
          embedded
            ? 'space-y-4'
            : 'page-content memories-grid space-y-4 md:space-y-6'
        }
      >
        <header>
          {embedded ? (
            <h2 className="text-xl font-semibold">添加记忆</h2>
          ) : (
            <h2 className="text-2xl font-semibold">他记得的事</h2>
          )}
          {!embedded && (
            <p className="mt-2 text-secondary">
              {memories.length} 条 · {Number(recordingHours.toFixed(1))}{' '}
              小时录音
            </p>
          )}
          <p className="my-2 text-sm text-secondary">
            写一段话，或上传文件、文件夹。添加后会自动处理。
          </p>
          {processing.state !== 'idle' && (
            <ThinkingLabel
              text={processing.state === 'queued' ? '等待记住…' : '正在记住…'}
            />
          )}
          {embedded && building && processing.state === 'idle' && (
            <p role="status">正在整理记忆…</p>
          )}
          {memories.map((memory) => (
            <MemoryWork
              key={memory.source_id}
              memory={memory}
              visible={embedded}
              busy={busy}
              onRetry={() =>
                memory.media_sha ? retranscribe(memory) : retry()
              }
            />
          ))}
          {processing.last_error && (
            <p className="text-sm text-danger">
              {processing.last_error}{' '}
              <Button
                className="min-h-11"
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={retry}
              >
                重新处理
              </Button>
            </p>
          )}
        </header>
        {memories.some((memory) => memory.status === 'needs_speaker') && (
          <Button
            variant="secondary"
            className="speaker-banner min-h-11 w-full text-left"
            onClick={() =>
              void view(
                memories.find((memory) => memory.status === 'needs_speaker')!,
              )
            }
          >
            有{' '}
            {
              memories.filter((memory) => memory.status === 'needs_speaker')
                .length
            }{' '}
            段录音需要确认哪位是你
          </Button>
        )}
        {(!mobile || embedded) && (
          <section
            ref={addPanel}
            className="memory-add-panel"
            aria-label="添加记忆"
            aria-busy={busy}
          >
            <Card>{addContent}</Card>
          </section>
        )}
        {(!mobile || !adding) && progressUI}
        {error && !adding && (
          <p role="alert" className="text-danger">
            {error}{' '}
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() =>
                failedFiles.current.length
                  ? upload(failedFiles.current)
                  : void refresh()
              }
            >
              {failedFiles.current.length ? '重试上传' : '重试加载'}
            </Button>
          </p>
        )}
        {!embedded && (
          <section className="memory-list">
            <h2 className="mb-2 text-md font-semibold md:mb-4 md:text-lg">
              已添加的记忆
            </h2>
            {!memories.length && (
              <EmptyState
                title="还没有记忆"
                body={
                  mobile
                    ? '点 + 写一段话或上传文件。'
                    : '从上面写一段话或上传文件开始。'
                }
              />
            )}
            <LayoutScope>
              <MessageList
                layout
                label="记忆列表"
                items={memories.map((memory) => ({
                  id: memory.source_id,
                  text: memory.title,
                  content: (
                    <article
                      aria-busy={mediaPending(memory) || memoryPending(memory)}
                      className={`memory-card flex items-start justify-between gap-2 rounded-xl bg-surface p-4 shadow-card ${mediaPending(memory) || memoryPending(memory) ? 'opacity-60' : ''}`}
                    >
                      <div className="min-w-0 flex-1">
                        <h3 className="flex items-center gap-2 font-medium">
                          {memory.kind === 'video' && (
                            <Video size={18} aria-label="视频" />
                          )}
                          {memory.kind === 'audio' && (
                            <AudioLines size={18} aria-label="音频" />
                          )}
                          <span className="truncate">{memory.title}</span>
                        </h3>
                        <p className="text-xs text-secondary">
                          {[
                            memory.detected_kind_label,
                            memory.first_date,
                            memory.duration_s != null
                              ? `${(memory.duration_s / 60).toFixed(1)} 分钟`
                              : null,
                          ]
                            .filter(Boolean)
                            .join(' · ')}
                        </p>
                        <Badge
                          tone={
                            memory.status === 'failed' ? 'danger' : 'neutral'
                          }
                          className={`memory-status status-${memory.status}`}
                        >
                          {(memory.status === 'remembered' ||
                            (memory.status === 'nothing_found' &&
                              memory.media_sha)) && (
                            <Check size={14} aria-hidden />
                          )}
                          {memory.status === 'needs_speaker' ? (
                            '待确认'
                          ) : memory.status === 'needs_asr' ? (
                            '需要配置语音识别'
                          ) : memory.status === 'queued' ? (
                            '等待转写'
                          ) : memory.status === 'extracting' ? (
                            '提取音频'
                          ) : memory.status === 'transcribing' ? (
                            `转写中 ${Math.min(100, Math.floor(((memory.transcribed_s ?? 0) / (memory.duration_s || 1)) * 100))}% · ${((memory.transcribed_s ?? 0) / 60).toFixed(1)}/${((memory.duration_s ?? 0) / 60).toFixed(1)} 分钟`
                          ) : memory.status === 'processing' ? (
                            <ThinkingLabel
                              text={memory.media_sha ? '整理中' : '正在记住…'}
                            />
                          ) : memory.status === 'remembered' ? (
                            `已加入 · 已记住 ${memory.remembered} 条`
                          ) : memory.status === 'nothing_found' ? (
                            memory.media_sha ? (
                              '已加入'
                            ) : (
                              '没找到关于你的内容'
                            )
                          ) : (
                            '处理失败'
                          )}
                        </Badge>
                        {(memory.status === 'failed' ||
                          memory.status === 'needs_asr') && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() =>
                              memory.media_sha ? retranscribe(memory) : retry()
                            }
                            disabled={busy}
                            className="min-h-11"
                          >
                            {memory.media_sha ? '重新转写' : '重试'}
                          </Button>
                        )}
                      </div>
                      {mobile ? (
                        <details className="relative shrink-0">
                          <summary
                            aria-label={`${memory.title}的操作`}
                            className="grid size-11 cursor-pointer list-none place-items-center rounded-md text-secondary [&::-webkit-details-marker]:hidden"
                          >
                            <MoreHorizontal size={20} aria-hidden />
                          </summary>
                          <div className="absolute right-0 z-10 grid min-w-28 rounded-md border border-border bg-surface p-1 shadow-elevation-2">
                            <Button
                              size="sm"
                              variant="ghost"
                              className="min-h-11"
                              onClick={(event) => {
                                event.currentTarget
                                  .closest('details')
                                  ?.removeAttribute('open');
                                void view(memory);
                              }}
                            >
                              查看
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="min-h-11"
                              disabled={busy}
                              onClick={(event) => {
                                event.currentTarget
                                  .closest('details')
                                  ?.removeAttribute('open');
                                void remove(memory);
                              }}
                            >
                              删除
                            </Button>
                          </div>
                        </details>
                      ) : (
                        <div className="flex gap-2">
                          <Button
                            size="sm"
                            variant="ghost"
                            className="min-h-11"
                            onClick={() => void view(memory)}
                          >
                            查看
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="min-h-11"
                            disabled={busy}
                            onClick={() => void remove(memory)}
                          >
                            删除
                          </Button>
                        </div>
                      )}
                    </article>
                  ),
                }))}
              />
            </LayoutScope>
          </section>
        )}
        {mobile && !embedded && (
          <>
            <IconButton
              label="添加记忆"
              onClick={() => setAdding(true)}
              className="memory-add fixed right-4 bottom-[calc(var(--mobile-tabs-height)+16px)] z-20 size-12 rounded-full bg-sun text-primary shadow-elevation-2"
            >
              <Plus size={24} aria-hidden />
            </IconButton>
            <Dialog
              open={adding && active}
              onOpenChange={(open) => {
                if (!busy) setAdding(open);
              }}
              title="添加记忆"
              body="写一段话，或上传文件、文件夹。"
              className="top-auto right-0 bottom-0 left-0 max-h-[85dvh] w-full translate-x-0 translate-y-0 rounded-b-none rounded-t-xl p-4 pb-[max(16px,env(safe-area-inset-bottom))]"
            >
              {addContent}
              {error && (
                <p role="alert" className="mt-3 text-danger">
                  {error}
                  {failedFiles.current.length > 0 && (
                    <Button
                      variant="ghost"
                      disabled={busy}
                      onClick={() => upload(failedFiles.current)}
                    >
                      重试上传
                    </Button>
                  )}
                </p>
              )}
            </Dialog>
          </>
        )}
        <Dialog
          open={preview !== null && active}
          onOpenChange={(open) => {
            if (!open) {
              previewRequest.current?.abort();
              setPreview(null);
            }
          }}
          title={preview?.title ?? ''}
          body="这是分身看到的文字，最多显示 20000 字。"
        >
          {preview?.memory.media_sha && (
            <MediaClaim
              key={preview.memory.source_id}
              sourceId={preview.memory.source_id}
              onChanged={() => {
                void refresh();
                void view(preview.memory);
              }}
            />
          )}
          <pre className="whitespace-pre-wrap break-words font-sans text-sm">
            {preview?.text}
          </pre>
        </Dialog>
      </div>
    </div>
  );
}
