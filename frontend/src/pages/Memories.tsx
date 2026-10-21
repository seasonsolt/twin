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
import {
  BuildProgress,
  INDEX_STAGE,
  type Processing,
} from '../features/memories/BuildProgress';
import { LayoutScope } from '../components/motion';
import {
  Badge,
  Button,
  Card,
  Dialog,
  EmptyState,
  FileDrop,
  Heading,
  IconButton,
  Skeleton,
  Tabs,
  Text,
  Textarea,
  toast,
  useConfirm,
  TypingIndicator,
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
import { TranscriptClaim } from '../features/sources/TranscriptClaim';

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
    | 'needs_speaker'
    | 'needs_name';
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
  needs_name?: number;
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

// A source's chunks are read one by one; once all are read it waits for the merge shared by the whole build, which
// starts when every source of the build is read, then for the retrieval vectors.
const processingLabel = (memory: Memory, processing: Processing) => {
  const total = memory.chunks_total ?? 0;
  if (total > 0) {
    const done = memory.chunks_done ?? 0;
    if (done < total) return `正在记住… ${done}/${total} 段`;
    const progress = processing.progress;
    if (progress?.phase === 'merge')
      return progress.to_merge
        ? `合并中 · 已合并 ${progress.merged ?? 0}/${progress.to_merge} 批`
        : '合并中';
    if (!progress && processing.stage?.label === INDEX_STAGE)
      return '正在更新检索向量';
    const left = progress ? progress.total - progress.done : 0;
    return left > 0
      ? `已读完，等其余 ${left} 段读完后合并`
      : '已读完，等待合并';
  }
  return memory.media_sha ? '整理中' : '正在记住…';
};

const processingText = (processing: Processing) => {
  if (processing.state === 'queued') return '记忆整理排队中';
  // No build: only uploads or recordings are still being read in.
  if (processing.state === 'idle') return '正在处理资料…';
  const progress = processing.progress;
  // After extraction and merge the build embeds the memories for retrieval, counted in tally.
  if (!progress && processing.stage?.label === INDEX_STAGE)
    return '正在更新检索向量…';
  if (progress?.phase === 'merge')
    return progress.to_merge
      ? `正在合并记忆… 已合并 ${progress.merged ?? 0}/${progress.to_merge} 批`
      : '正在合并记忆…';
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
      <Text role="alert" size="sm" tone="danger">
        {memory.title} ·{' '}
        {memory.status === 'needs_asr' ? '需要配置语音识别' : '处理失败'}
        <Button variant="ghost" disabled={busy} onClick={onRetry}>
          重试
        </Button>
      </Text>
    );
  return visible && pending ? (
    <Text role="status" aria-busy="true" size="sm" tone="secondary">
      {memory.title} · {label}
    </Text>
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
      <Text size="sm" tone="secondary">
        {current}
        {' · 已是最新'}
      </Text>
    );
  const from = kernel.built ? kernelLabel(kernel.built) : '旧版';
  if (processing.state !== 'idle')
    return (
      <Text role="status" size="sm" tone="secondary">
        {current}
        {` · 正在从 ${from} 升级，整理完成前沿用旧档案`}
      </Text>
    );
  return (
    <Card
      as="div"
      variant="outline"
      padding="sm"
      role="status"
      className="space-y-1"
    >
      <Text size="sm">
        {current}
        {' · 可以升级'}
      </Text>
      <Text size="sm" tone="secondary">
        现有记忆按 {from} 整理，升级后按新版本重新整理
        {kernel.pending_chunks > 0 &&
          `，需重新整理 ${kernel.pending_chunks} 段，会调用模型`}
        。升级完成前沿用旧档案。
      </Text>
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
        <Text size="sm" tone="secondary">
          请管理员升级。
        </Text>
      )}
    </Card>
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
  const [claiming, setClaiming] = useState(false);
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
              await uploadMedia(
                file,
                signal,
                (value) => {
                  if (alive.current) setUploadProgress(value);
                },
                { compact: 'audio' },
              );
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
    <Card
      as="div"
      variant="outline"
      padding="sm"
      role="status"
      className="space-y-2"
    >
      <Text weight="medium" truncate>
        {uploadProgress.name}
      </Text>
      <Text size="sm" tone="secondary">
        {uploadProgress.paused
          ? '网络已断开，联网后继续上传'
          : uploadProgress.preparing !== undefined
            ? '正在本机压缩音频，压缩后上传更快，请保持页面打开'
            : '上传中，请保持页面打开'}
      </Text>
      {uploadProgress.preparing !== undefined ? (
        <>
          <progress
            className="h-2 w-full"
            aria-label="压缩进度"
            max={1}
            value={uploadProgress.preparing}
          />
          <Text size="sm" tone="secondary">
            压缩中 {Math.floor(uploadProgress.preparing * 100)}%
          </Text>
        </>
      ) : (
        <>
          <progress
            className="h-2 w-full"
            aria-label="上传进度"
            max={uploadProgress.size || 1}
            value={uploadProgress.offset}
          />
          <Text size="sm" tone="secondary">
            上传中{' '}
            {Math.floor(
              (uploadProgress.offset / (uploadProgress.size || 1)) * 100,
            )}
            % · {(uploadProgress.offset / 1024 ** 2).toFixed(1)} /{' '}
            {(uploadProgress.size / 1024 ** 2).toFixed(1)} MB
          </Text>
        </>
      )}
    </Card>
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
  const waiting =
    summary.total -
    summary.remembered -
    summary.nothing_found -
    summary.failed -
    summary.busy;
  const recordingHours = summary.duration_s / 3600;
  const firstSpeaker = attention.find(
    (memory) => memory.status === 'needs_speaker',
  );
  const fileInput = (folder: boolean) => (
    // A phone cannot drag files in, so there the button says it all.
    <FileDrop
      label={folder ? '文件夹上传区' : '文件上传区'}
      title={
        mobile
          ? null
          : folder
            ? '点击选择文件夹，或把文件拖到这里'
            : '点击选择文件，或拖到这里'
      }
      actionLabel={folder ? '选择文件夹' : '选择文件'}
      directory={folder}
      disabled={busy}
      onFiles={(files) => upload(files, folder)}
      hint={
        <>
          <p>
            文档：TXT、Markdown、PDF、Word、EPUB、HTML、CSV、JSON、SRT、VTT，每个最多
            1 GB
            {folder &&
              '；文件夹总量最多 500 MB，自动跳过隐藏文件和不支持的格式'}
          </p>
          <p>
            录音和视频：每个最多 4 GB，断点续传，刷新后重新选择同一文件即可继续
          </p>
        </>
      }
    />
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
        <Text
          as="ul"
          size="sm"
          tone="secondary"
          aria-label="跳过的文件"
          className="mt-3"
        >
          {skipped.map((row, i) => (
            <li key={i}>
              {row.file}：{row.reason}
            </li>
          ))}
        </Text>
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
              <IconButton
                label="从舞台添加记忆"
                shape="circle"
                size="lg"
                className="stage-add"
                onClick={openAdd}
              >
                <Plus size={24} aria-hidden />
              </IconButton>
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
            <Heading level={2} size="title">
              添加记忆
            </Heading>
          ) : (
            <Heading level={2}>他记得的事</Heading>
          )}
          {!embedded && (
            <Text tone="secondary" className="mt-2">
              {summary.total} 条 · {Number(recordingHours.toFixed(1))} 小时录音
            </Text>
          )}
          <Text size="sm" tone="secondary" className="my-2">
            写一段话，或上传文件、文件夹。添加后会自动处理。
          </Text>
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
              <Text role="status" size="sm" tone="secondary">
                {processing.notice}
              </Text>
            )
          )}
          {(processing.state !== 'idle' || summary.busy > 0) && (
            <BuildProgress
              processing={processing}
              title={processingText(processing)}
            >
              <Text size="xs" tone="secondary">
                共 {summary.total} 份 · 已记住 {summary.remembered} 份
                {summary.nothing_found > 0 &&
                  ` · 已处理无结果 ${summary.nothing_found} 份`}
                {summary.busy > 0 && ` · 整理中 ${summary.busy} 份`}
                {summary.failed > 0 && ` · 失败 ${summary.failed} 份`}
                {waiting > 0 && ` · 待处理或确认 ${waiting} 份`}
              </Text>
            </BuildProgress>
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
            <Text size="sm" tone="danger">
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
            </Text>
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
        {(summary.needs_name ?? 0) > 0 && (
          <Button
            variant="secondary"
            className="speaker-banner min-h-11 w-full text-left"
            onClick={() => setClaiming(true)}
          >
            有 {summary.needs_name} 份文字记录需要确认哪位是你
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
            <Heading level={2} size="section" className="mb-2 md:mb-4">
              已添加的记忆
            </Heading>
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
                    <Card
                      as="article"
                      padding="md"
                      aria-busy={mediaPending(memory) || memoryPending(memory)}
                      className={`memory-card flex items-start justify-between gap-2 ${mediaPending(memory) || memoryPending(memory) ? 'opacity-60' : ''}`}
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
                        <Text size="xs" tone="secondary">
                          {[
                            memory.detected_kind_label,
                            memory.first_date,
                            memory.duration_s != null
                              ? `${(memory.duration_s / 60).toFixed(1)} 分钟`
                              : null,
                          ]
                            .filter(Boolean)
                            .join(' · ')}
                        </Text>
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
                          {memory.status === 'needs_speaker' ||
                          memory.status === 'needs_name' ? (
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
                            <TypingIndicator
                              text={processingLabel(memory, processing)}
                            />
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
                            className="grid size-11 cursor-pointer list-none place-items-center text-secondary"
                          >
                            <MoreHorizontal size={20} aria-hidden />
                          </summary>
                          <Card
                            as="div"
                            variant="outline"
                            padding="none"
                            className="absolute right-0 z-10 grid min-w-28 p-1 shadow-elevation-2"
                          >
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
                          </Card>
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
                    </Card>
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
                shape="circle"
                className="memory-add fixed right-4 z-20 size-12 bg-sun text-primary shadow-elevation-2"
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
              variant="sheet"
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
          open={claiming && active}
          onOpenChange={setClaiming}
          title="哪位是你"
          body="确认后，这些文字记录会按你的选择重新整理；没确认之前，里面的话都不算你说的。"
        >
          <TranscriptClaim onChanged={() => void refresh()} />
        </Dialog>
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
          <Text
            as="pre"
            size="sm"
            className="whitespace-pre-wrap break-words font-sans"
          >
            {preview?.text}
          </Text>
        </Dialog>
      </div>
    </div>
  );
}
