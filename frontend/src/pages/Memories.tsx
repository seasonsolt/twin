import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router';
import { MessageList } from '../components/effects/MessageList';
import { ThinkingLabel } from '../components/effects/ThinkingLabel';
import { LayoutScope } from '../components/motion';
import {
  Badge,
  Button,
  Card,
  Dialog,
  EmptyState,
  Tabs,
  Textarea,
  toast,
  useConfirm,
} from '../components/ui';
import { api } from '../lib/api';
import { useStatus } from '../stores/status';

const accept = '.txt,.md,.pdf,.docx,.html,.htm,.csv,.json,.srt,.vtt';
export interface Memory {
  source_id: string;
  title: string;
  first_date: string | null;
  detected_kind_label: string;
  status: 'processing' | 'remembered' | 'nothing_found' | 'failed';
  remembered: number;
}
interface Processing {
  state: 'idle' | 'queued' | 'running';
  last_error?: string | null;
}

export function Memories({ embedded = false }: { embedded?: boolean }) {
  const active = useLocation().pathname === '/memories' || embedded;
  const confirm = useConfirm();
  const [memories, setMemories] = useState<Memory[]>([]);
  const [processing, setProcessing] = useState<Processing>({ state: 'idle' });
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [skipped, setSkipped] = useState<{ file: string; reason: string }[]>(
    [],
  );
  const [preview, setPreview] = useState<{
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
      if (state.state !== 'idle')
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
      const form = new FormData();
      files.forEach((file) =>
        form.append('files', file, file.webkitRelativePath || file.name),
      );
      const result = await api<{
        imported: Memory[];
        skipped: { file: string; reason: string }[];
      }>('/api/persona/import', { method: 'POST', form, signal });
      if (alive.current) {
        setSkipped(result.skipped);
        if (result.imported.length) toast('已添加，正在记住…', 'success');
      }
    });
  const retry = () =>
    void mutate((signal) =>
      api('/api/persona/build', { method: 'POST', signal }),
    );
  const view = async (memory: Memory) => {
    previewRequest.current?.abort();
    const controller = new AbortController();
    previewRequest.current = controller;
    setPreview({ title: memory.title, text: '正在读取…' });
    try {
      const value = await api<string>(
        `/api/persona/sources/${encodeURIComponent(memory.source_id)}/text`,
        { responseType: 'text', signal: controller.signal },
      );
      if (alive.current && !controller.signal.aborted)
        setPreview({ title: memory.title, text: value });
    } catch (err) {
      if (alive.current && !controller.signal.aborted)
        setPreview({
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
        {...(folder ? { webkitdirectory: '' } : {})}
        onChange={(event) => {
          upload(Array.from(event.target.files ?? []));
          event.target.value = '';
        }}
      />
      <p className="text-xs text-tertiary">
        TXT、Markdown、PDF、Word、HTML、CSV、JSON、SRT、VTT；每个文件最多 50
        MB。扫描 PDF 暂不支持。
      </p>
    </div>
  );
  return (
    <div className="space-y-6">
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
            <Button size="sm" variant="ghost" disabled={busy} onClick={retry}>
              重新处理
            </Button>
          </p>
        )}
      </header>
      <Card>
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
                      if (alive.current) setText('');
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
                  <Button type="submit" loading={busy} disabled={!text.trim()}>
                    保存
                  </Button>
                </form>
              ),
            },
            { value: 'files', label: '上传文件', content: fileInput(false) },
            { value: 'folder', label: '上传文件夹', content: fileInput(true) },
          ]}
        />
        {skipped.length > 0 && (
          <ul aria-label="跳过的文件" className="mt-3 text-sm text-secondary">
            {skipped.map((row, i) => (
              <li key={i}>
                {row.file}：{row.reason}
              </li>
            ))}
          </ul>
        )}
      </Card>
      {error && (
        <p role="alert" className="text-danger">
          {error}{' '}
          <Button size="sm" variant="ghost" onClick={() => void refresh()}>
            重试加载
          </Button>
        </p>
      )}
      {!embedded && (
        <Card>
          <h2 className="mb-4 text-lg font-semibold">已添加的记忆</h2>
          {!memories.length && (
            <EmptyState
              title="还没有记忆"
              body="从上面写一段话或上传文件开始。"
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
                  <article className="flex flex-wrap items-center justify-between gap-3 border-b border-border py-3">
                    <div>
                      <h3 className="font-medium">{memory.title}</h3>
                      <p className="text-sm text-secondary">
                        {[memory.first_date, memory.detected_kind_label]
                          .filter(Boolean)
                          .join(' · ')}
                      </p>
                      <Badge
                        tone={memory.status === 'failed' ? 'danger' : 'neutral'}
                      >
                        {memory.status === 'processing' ? (
                          <ThinkingLabel text="正在记住…" />
                        ) : memory.status === 'remembered' ? (
                          `已记住 ${memory.remembered} 条`
                        ) : memory.status === 'nothing_found' ? (
                          '没找到关于你的内容'
                        ) : (
                          '处理失败'
                        )}
                      </Badge>
                      {memory.status === 'failed' && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={retry}
                          disabled={busy}
                        >
                          重试
                        </Button>
                      )}
                    </div>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => void view(memory)}
                      >
                        查看
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy}
                        onClick={() =>
                          void (async () => {
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
                                api(
                                  `/api/persona/sources/${encodeURIComponent(memory.source_id)}`,
                                  { method: 'DELETE', signal },
                                ),
                              );
                          })()
                        }
                      >
                        删除
                      </Button>
                    </div>
                  </article>
                ),
              }))}
            />
          </LayoutScope>
        </Card>
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
        <pre className="whitespace-pre-wrap break-words font-sans text-sm">
          {preview?.text}
        </pre>
      </Dialog>
    </div>
  );
}
