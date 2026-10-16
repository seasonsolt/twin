import { useCallback, useEffect, useRef } from 'react';
import {
  usePersonaId,
  usePersonaState as useState,
} from '../lib/usePersonaState';
import { useLocation } from 'react-router';
import { Check, MoreHorizontal, Plus, Video, AudioLines } from 'lucide-react';
import { StageHeader } from '../components/layout/StageHeader';
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
  Skeleton,
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
import {
  useStatus,
  type KernelStatus,
  type KernelVersion,
} from '../stores/status';
import { usePersonas } from '../stores/personas';
import { useAuth } from '../stores/auth';
import { MediaClaim } from '../features/sources/MediaClaim';

const accept =
  '.txt,.md,.pdf,.docx,.epub,.html,.htm,.csv,.json,.srt,.vtt,audio/*,video/*,.mkv,.caf,.amr,.opus';
const MAX_FOLDER_UPLOAD_BYTES = 500 * 1024 * 1024;
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
  chunks_done?: number;
  chunks_total?: number;
  extraction?: { returned: number; kept: number } | null;
}
export interface SourceSummary {
  total: number;
  duration_s: number;
  needs_speaker: number;
  busy: number;
  remembered: number;
  nothing_found: number;
  failed: number;
}
export interface SourcePage {
  items: Memory[];
  total: number;
  summary: SourceSummary;
  attention?: Memory[];
}
const PAGE_SIZE = 50;
const UPLOAD_BATCH_FILES = 200;
const UPLOAD_BATCH_BYTES = 256 * 1024 ** 2;

/** Documents in upload order, cut into requests the server accepts; a file larger than a batch goes alone. */
export function uploadBatches(files: File[]) {
  const batches: File[][] = [];
  let current: File[] = [];
  let bytes = 0;
  for (const file of files) {
    if (
      current.length &&
      (current.length >= UPLOAD_BATCH_FILES ||
        bytes + file.size > UPLOAD_BATCH_BYTES)
    ) {
      batches.push(current);
      current = [];
      bytes = 0;
    }
    current.push(file);
    bytes += file.size;
  }
  if (current.length) batches.push(current);
  return batches;
}
// The server's largest page: polling re-reads at most this many of the rows already shown.
const MAX_PAGE = 500;
const emptySummary: SourceSummary = {
  total: 0,
  duration_s: 0,
  needs_speaker: 0,
  busy: 0,
  remembered: 0,
  nothing_found: 0,
  failed: 0,
};
interface Processing {
  state: 'idle' | 'queued' | 'running';
  progress?: { phase: 'extract' | 'merge'; done: number; total: number };
  stage?: { current: number; total: number; label: string } | null;
  tally?: { done: number; failed: number; total: number | null } | null;
  notice?: string | null;
  last_error?: string | null;
}

// A source's chunks are read one by one; once all are read it waits for the shared merge at the end of the build.
const processingLabel = (memory: Memory) => {
  const total = memory.chunks_total ?? 0;
  if (total > 0) {
    const done = memory.chunks_done ?? 0;
    return done < total ? `正在记住… ${done}/${total} 段` : '已读完，等待合并';
  }
  return memory.media_sha ? '整理中' : '正在记住…';
};

const processingText = (processing: Processing) => {
  if (processing.state === 'queued') return '记忆整理排队中';
  const progress = processing.progress;
  if (progress?.phase === 'merge') return '正在合并记忆…';
  if (progress && progress.total > 0)
    return `正在记住… 已读 ${progress.done}/${progress.total} 段`;
  return '正在记住…';
};

const mediaPending = (memory: Memory) =>
  ['queued', 'extracting', 'transcribing'].includes(memory.status);
const memoryPending = (memory: Memory) =>
  memory.status === 'processing' ||
  (memory.candidates_pending &&
    !['failed', 'needs_asr', 'needs_speaker'].includes(memory.status));
// The model drew conclusions from it, but none passed the checks (quotes, facet).
const misquoted = (memory: Memory) =>
  !!memory.extraction &&
  memory.extraction.returned > 0 &&
  memory.extraction.kept === 0;
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

const kernelLabel = (version: KernelVersion) =>
  `${version.prompt} · 分类 ${version.taxonomy}`;

function KernelLine({
  kernel,
  processing,
  admin,
  busy,
  onUpgrade,
}: {
  kernel: KernelStatus;
  processing: Processing;
  admin: boolean;
  busy: boolean;
  onUpgrade: () => void;
}) {
  const current = (
    <span className="font-medium">记忆内核 {kernelLabel(kernel.version)}</span>
  );
  if (kernel.scope === 'none')
    return (
      <p className="text-sm text-secondary">
        {current}
        {' · 已是最新'}
      </p>
    );
  const from = kernel.built ? kernelLabel(kernel.built) : '旧版';
  if (processing.state !== 'idle')
    return (
      <p role="status" className="text-sm text-secondary">
        {current}
        {` · 正在从 ${from} 升级，整理完成前沿用旧档案`}
      </p>
    );
  return (
    <div
      role="status"
      className="space-y-1 rounded-lg border border-border p-3 text-sm"
    >
      <p>
        {current}
        {' · 可以升级'}
      </p>
      <p className="text-secondary">
        现有记忆按 {from} 整理，升级后按新版本重新整理
        {kernel.pending_chunks > 0 &&
          `，需重新整理 ${kernel.pending_chunks} 段，会调用模型`}
        。升级完成前沿用旧档案。
      </p>
      {admin ? (
        <Button
          className="min-h-11"
          size="sm"
          disabled={busy}
          onClick={onUpgrade}
        >
          升级记忆内核
        </Button>
      ) : (
        <p className="text-secondary">请管理员升级。</p>
      )}
    </div>
  );
}

export function Memories({
  embedded = false,
  profile = false,
  onSpeakerCount,
}: {
  embedded?: boolean;
  profile?: boolean;
  onSpeakerCount?: (count: number) => void;
}) {
  const active = useLocation().pathname === '/memories' || embedded || profile;
  const personaId = usePersonaId();
  const confirm = useConfirm();
  const mobile = useMobile();
  const [adding, setAdding] = useState(false);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<SourceSummary>(emptySummary);
  // Memories being transcribed or waiting for the person, wherever they are in the list.
  const [attention, setAttention] = useState<Memory[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [processing, setProcessing] = useState<Processing>({ state: 'idle' });
  const admin = useAuth((state) => state.identity?.admin ?? false);
  const kernel = useStatus((state) => state.data?.kernel);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [busyLabel, setBusyLabel] = useState('正在保存记忆…');
  const [error, setError] = useState('');
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(
    null,
  );
  usePendingWork(busy, busyLabel);
  const building = processing.state !== 'idle' || summary.busy > 0;
  usePendingWork(building, '正在整理记忆…', true);
  const failedFiles = useRef<File[]>([]);
  const failedUploadIsFolder = useRef(false);
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
  const more = useRef<AbortController | null>(null);
  const previewRequest = useRef<AbortController | null>(null);
  const mutation = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const shown = useRef(0);
  useEffect(() => {
    shown.current = memories.length;
  }, [memories]);
  const refresh = useCallback(
    async function reload() {
      request.current?.abort();
      if (timer.current) clearTimeout(timer.current);
      const controller = new AbortController();
      request.current = controller;
      const limit = Math.min(MAX_PAGE, Math.max(PAGE_SIZE, shown.current));
      try {
        const [page, state] = await Promise.all([
          api<SourcePage>(
            `/api/persona/sources?limit=${limit}&attention=true`,
            {
              signal: controller.signal,
              headers: { 'X-Twin-Persona': personaId },
            },
          ),
          api<Processing>('/api/persona/processing', {
            headers: { 'X-Twin-Persona': personaId },
            signal: controller.signal,
          }),
        ]);
        if (!alive.current || controller.signal.aborted) return;
        // Rows past the re-read ones stay as they were; they refresh when the person pages to them again.
        setMemories((rows) => {
          const fresh = new Set(page.items.map((row) => row.source_id));
          return [
            ...page.items,
            ...rows.slice(limit).filter((row) => !fresh.has(row.source_id)),
          ].slice(0, page.total);
        });
        setTotal(page.total);
        setSummary(page.summary);
        setAttention(page.attention ?? []);
        onSpeakerCount?.(page.summary.needs_speaker);
        setLoading(false);
        setProcessing(state);
        setError('');
        if (state.state !== 'idle' || page.summary.busy > 0)
          timer.current = setTimeout(() => void reload(), 2000);
        else void useStatus.getState().refresh();
      } catch (err) {
        if (alive.current && !controller.signal.aborted) {
          setLoading(false);
          setError(err instanceof Error ? err.message : '无法读取记忆');
          timer.current = setTimeout(() => void reload(), 2000);
        }
      }
    },
    [personaId, onSpeakerCount],
  );
  const loadMore = async () => {
    if (more.current) return;
    const controller = new AbortController();
    more.current = controller;
    setLoadingMore(true);
    try {
      const page = await api<SourcePage>(
        `/api/persona/sources?limit=${PAGE_SIZE}&offset=${memories.length}`,
        { signal: controller.signal, headers: { 'X-Twin-Persona': personaId } },
      );
      if (!alive.current || controller.signal.aborted) return;
      setMemories((rows) => {
        const seen = new Set(rows.map((row) => row.source_id));
        return [
          ...rows,
          ...page.items.filter((row) => !seen.has(row.source_id)),
        ];
      });
      setTotal(page.total);
      setSummary(page.summary);
    } catch (err) {
      if (alive.current && !controller.signal.aborted)
        setError(err instanceof Error ? err.message : '无法读取记忆');
    } finally {
      if (more.current === controller) more.current = null;
      if (alive.current && !controller.signal.aborted) setLoadingMore(false);
    }
  };
  useEffect(() => {
    alive.current = active;
    failedFiles.current = [];
    mutation.current = null;
    if (active) void refresh();
    return () => {
      alive.current = false;
      request.current?.abort();
      more.current?.abort();
      more.current = null;
      previewRequest.current?.abort();
      mutation.current?.abort();
      if (timer.current) clearTimeout(timer.current);
    };
  }, [active, refresh, personaId]);

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
    setSkipped([]);
    try {
      await fn(controller.signal);
      if (!alive.current || controller.signal.aborted) return;
      if (added) toast('已添加，等待整理结果', 'success');
      await refresh();
    } catch (err) {
      if (alive.current && !controller.signal.aborted)
        setError(err instanceof Error ? err.message : '操作失败，请重试');
    } finally {
      if (mutation.current === controller) mutation.current = null;
      if (alive.current && !controller.signal.aborted) setBusy(false);
    }
  };
  const upload = (files: File[], folder = false) =>
    void mutate(
      async (signal) => {
        failedFiles.current = [];
        failedUploadIsFolder.current = folder;
        if (!files.length) return;
        const totalSize = files.reduce((sum, file) => sum + file.size, 0);
        if (folder && totalSize > MAX_FOLDER_UPLOAD_BYTES)
          throw new Error('文件夹内容超过 500 MB，请分批上传');
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
            const size = documents.reduce((sum, file) => sum + file.size, 0);
            const name =
              documents
                .slice(0, 3)
                .map((file) => file.name)
                .join('、') +
              (documents.length > 3 ? ` 等 ${documents.length} 个文件` : '');
            let sent = 0;
            let sentFiles = 0;
            let added = 0;
            setUploadProgress({ name, offset: 0, size, paused: false });
            // Keep the folder cap while retaining the server's bounded batches for ordinary multi-file uploads.
            const batches = folder
              ? documents.map((file) => [file])
              : uploadBatches(documents);
            for (const batch of batches) {
              const form = new FormData();
              batch.forEach((file) =>
                form.append(
                  'files',
                  file,
                  file.webkitRelativePath || file.name,
                ),
              );
              const bytes = batch.reduce((sum, file) => sum + file.size, 0);
              const before = completed;
              failedFiles.current = documents.slice(sentFiles);
              setBusyLabel(`正在上传 ${completed + 1}/${files.length}…`);
              const result = await uploadForm<{
                imported: Memory[];
                skipped: { file: string; reason: string }[];
              }>('/api/persona/import', form, signal, (percent) => {
                if (!alive.current) return;
                setUploadProgress({
                  name,
                  offset: sent + (bytes * percent) / 100,
                  size,
                  paused: false,
                });
                setBusyLabel(
                  percent === 100
                    ? '正在处理文件…'
                    : `正在上传 ${before + Math.min(batch.length, Math.floor((batch.length * percent) / 100) + 1)}/${files.length}…`,
                );
              });
              sent += bytes;
              sentFiles += batch.length;
              completed += batch.length;
              added += result.imported.length;
              ignored.push(...result.skipped);
              // Files already sent are not sent again if a later batch fails and the person retries.
              failedFiles.current = documents.slice(sentFiles);
            }
            if (alive.current && added) toast('已添加，正在记住…', 'success');
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
  const rebuildKernel = () =>
    void mutate(async (signal) => {
      await api('/api/kernel/rebuild', { method: 'POST', signal });
      void useStatus.getState().refresh();
    });
  const reextract = (memory: Memory) =>
    void mutate((signal) =>
      api(
        `/api/persona/sources/${encodeURIComponent(memory.source_id)}/reextract`,
        { method: 'POST', signal },
      ),
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
  const recordingHours = summary.duration_s / 3600;
  const firstSpeaker = attention.find(
    (memory) => memory.status === 'needs_speaker',
  );
  const fileInput = (folder: boolean) => (
    <div
      aria-busy={busy}
      className={`space-y-3 rounded-lg border border-dashed border-border p-6 ${busy ? 'opacity-60' : ''}`}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        if (!busy) upload(Array.from(event.dataTransfer.files), folder);
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
          upload(Array.from(event.target.files ?? []), folder);
          event.target.value = '';
        }}
      />
      <p className="text-xs text-tertiary">
        {folder && '文件夹内容总量最多 500 MB。'}
        TXT、Markdown、PDF、Word、EPUB、HTML、CSV、JSON、SRT、VTT；每个文件最多
        1 GB。音频、视频最多 4
        GB，支持断点续传。刷新后重新选择同一文件即可继续。
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
      alive.current &&
      personaId === usePersonas.getState().id
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
      {!embedded && !profile && (
        <StageHeader
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
            : `${profile ? '' : 'page-content '}memories-grid space-y-4 md:space-y-6`
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
              {summary.total} 条 · {Number(recordingHours.toFixed(1))} 小时录音
            </p>
          )}
          <p className="my-2 text-sm text-secondary">
            写一段话，或上传文件、文件夹。添加后会自动处理。
          </p>
          {profile && mobile && (
            <Button onClick={openAdd} className="min-h-11">
              添加记忆
            </Button>
          )}
          {kernel && (!embedded || kernel.scope !== 'none') ? (
            <KernelLine
              kernel={kernel}
              processing={processing}
              admin={admin}
              busy={busy}
              onUpgrade={rebuildKernel}
            />
          ) : (
            processing.notice && (
              <p role="status" className="text-sm text-secondary">
                {processing.notice}
              </p>
            )
          )}
          {(processing.state !== 'idle' || summary.busy > 0) && (
            <div
              aria-live="polite"
              className="space-y-1 text-sm text-secondary"
            >
              <ThinkingLabel text={processingText(processing)} />
              <p>
                {processingText(processing)} · 共 {summary.total} 份 · 已记住{' '}
                {summary.remembered} 份
                {summary.nothing_found > 0 &&
                  ` · 已处理无结果 ${summary.nothing_found} 份`}
                {summary.busy > 0 && ` · 整理中 ${summary.busy} 份`}
                {summary.failed > 0 && ` · 失败 ${summary.failed} 份`}
                {summary.total -
                  summary.remembered -
                  summary.nothing_found -
                  summary.failed -
                  summary.busy >
                  0 &&
                  ` · 待处理或确认 ${
                    summary.total -
                    summary.remembered -
                    summary.nothing_found -
                    summary.failed -
                    summary.busy
                  } 份`}
              </p>
              {processing.stage && (
                <p className="text-xs">
                  当前阶段 {processing.stage.current}/{processing.stage.total} ·{' '}
                  {processing.stage.label}
                  {processing.tally &&
                    processing.tally.done + processing.tally.failed > 0 &&
                    ` · 已完成 ${processing.tally.done} 项，失败 ${processing.tally.failed} 项`}
                </p>
              )}
            </div>
          )}
          {embedded && building && processing.state === 'idle' && (
            <p role="status">正在整理记忆…</p>
          )}
          {attention.map((memory) => (
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
        {summary.needs_speaker > 0 && firstSpeaker && (
          <Button
            variant="secondary"
            className="speaker-banner min-h-11 w-full text-left"
            onClick={() => void view(firstSpeaker)}
          >
            有 {summary.needs_speaker} 段录音需要确认哪位是你
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
                  ? upload(failedFiles.current, failedUploadIsFolder.current)
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
            {loading && <Skeleton className="h-24" />}
            {!loading && !memories.length && (
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
                            <ThinkingLabel text={processingLabel(memory)} />
                          ) : memory.status === 'remembered' ? (
                            `已加入 · 已记住 ${memory.remembered} 条`
                          ) : memory.status === 'nothing_found' ? (
                            memory.media_sha ? (
                              '已加入'
                            ) : misquoted(memory) ? (
                              '找到一些内容，但没通过核对'
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
                        {memory.status === 'nothing_found' && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => reextract(memory)}
                            disabled={busy}
                            className="min-h-11"
                          >
                            重新整理
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
            {memories.length < total && (
              <Button
                variant="ghost"
                className="mt-3 min-h-11 w-full"
                loading={loadingMore}
                onClick={() => void loadMore()}
              >
                再看 {Math.min(PAGE_SIZE, total - memories.length)} 条（还有{' '}
                {total - memories.length} 条）
              </Button>
            )}
          </section>
        )}
        {mobile && !embedded && (
          <>
            {!profile && (
              <IconButton
                label="添加记忆"
                onClick={() => setAdding(true)}
                className="memory-add fixed right-4 bottom-[calc(var(--mobile-tabs-height)+16px)] z-20 size-12 rounded-full bg-sun text-primary shadow-elevation-2"
              >
                <Plus size={24} aria-hidden />
              </IconButton>
            )}
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
                      onClick={() =>
                        upload(
                          failedFiles.current,
                          failedUploadIsFolder.current,
                        )
                      }
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
