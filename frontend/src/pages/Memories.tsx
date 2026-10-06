import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router';
import { MoreHorizontal, Plus, Video, AudioLines } from 'lucide-react';
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
import { isMedia, uploadMedia, type UploadProgress } from '../lib/mediaUpload';
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

export function Memories({ embedded = false }: { embedded?: boolean }) {
  const active = useLocation().pathname === '/memories' || embedded;
  const confirm = useConfirm();
  const mobile = useMobile();
  const [adding, setAdding] = useState(false);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [processing, setProcessing] = useState<Processing>({ state: 'idle' });
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(
    null,
  );
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
        rows.some(
          (row) =>
            ['queued', 'extracting', 'transcribing'].includes(row.status) ||
            row.candidates_pending,
        )
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
  ) => {
    if (mutation.current) return;
    const controller = new AbortController();
    mutation.current = controller;
    setBusy(true);
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
    void mutate(async (signal) => {
      if (!files.length) return;
      failedFiles.current = files;
      const documents: File[] = [];
      const ignored: { file: string; reason: string }[] = [];
      try {
        for (const file of files) {
          if (
            (file.webkitRelativePath || file.name)
              .split('/')
              .some((part) => part.startsWith('.'))
          ) {
            ignored.push({ file: file.name, reason: '已跳过隐藏文件' });
          } else if (isMedia(file)) {
            await uploadMedia(file, signal, (value) => {
              if (alive.current) setUploadProgress(value);
            });
            await refresh();
          } else documents.push(file);
        }
        if (documents.length) {
          const form = new FormData();
          documents.forEach((file) =>
            form.append('files', file, file.webkitRelativePath || file.name),
          );
          const result = await api<{
            imported: Memory[];
            skipped: { file: string; reason: string }[];
          }>('/api/persona/import', { method: 'POST', form, signal });
          ignored.push(...result.skipped);
          if (alive.current && result.imported.length)
            toast('已添加，正在记住…', 'success');
        }
        failedFiles.current = [];
        if (alive.current) setSkipped(ignored);
      } finally {
        if (alive.current) setUploadProgress(null);
      }
    });
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
        max={uploadProgress.size}
        value={uploadProgress.offset}
      />
      <p className="text-sm text-secondary">
        上传中 {Math.floor((uploadProgress.offset / uploadProgress.size) * 100)}
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
  const fileInput = (folder: boolean) => (
    <div
      className="space-y-3 rounded-lg border border-dashed border-border p-6"
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
                className="space-y-3"
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
                  保存
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
    <div className="space-y-4 md:space-y-6">
      <header>
        {embedded ? (
          <h2 className="text-xl font-semibold">添加记忆</h2>
        ) : (
          <h1 className="text-2xl font-semibold">记忆</h1>
        )}
        <p className="my-2 text-sm text-secondary">
          写一段话，或上传文件、文件夹。添加后会自动处理。
        </p>
        {processing.state !== 'idle' && (
          <ThinkingLabel
            text={processing.state === 'queued' ? '等待记住…' : '正在记住…'}
          />
        )}
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
          className="min-h-11 w-full text-left"
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
      {(!mobile || embedded) && <Card>{addContent}</Card>}
      {(!mobile || !adding) && progressUI}
      {error && !adding && (
        <p role="alert" className="text-danger">
          {error}{' '}
          <Button
            size="sm"
            variant="ghost"
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
        <Card className="px-3 py-2 md:p-6">
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
                  <article className="flex items-start justify-between gap-2 border-b border-border py-2 md:py-3">
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
                        tone={memory.status === 'failed' ? 'danger' : 'neutral'}
                      >
                        {memory.status === 'needs_speaker' ? (
                          '待确认'
                        ) : memory.status === 'needs_asr' ? (
                          '需要配置语音识别'
                        ) : memory.status === 'queued' ? (
                          '等待转写'
                        ) : memory.status === 'extracting' ? (
                          '提取音频'
                        ) : memory.status === 'transcribing' ? (
                          `转写中 ${((memory.transcribed_s ?? 0) / 60).toFixed(1)}/${((memory.duration_s ?? 0) / 60).toFixed(1)} 分钟`
                        ) : memory.status === 'processing' ? (
                          <ThinkingLabel
                            text={memory.media_sha ? '整理中' : '正在记住…'}
                          />
                        ) : memory.status === 'remembered' ? (
                          memory.media_sha ? (
                            `已加入 · 已记住 ${memory.remembered} 条`
                          ) : (
                            `已记住 ${memory.remembered} 条`
                          )
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
        </Card>
      )}
      {mobile && !embedded && (
        <>
          <IconButton
            label="添加记忆"
            onClick={() => setAdding(true)}
            className="fixed right-4 bottom-[calc(var(--mobile-tabs-height)+16px)] z-20 size-12 rounded-full bg-accent text-on-accent shadow-elevation-2"
          >
            <Plus size={24} aria-hidden />
          </IconButton>
          <Dialog
            open={adding && active}
            onOpenChange={setAdding}
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
  );
}
