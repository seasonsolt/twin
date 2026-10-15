import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowUp,
  Download,
  FileSpreadsheet,
  FileText,
  LoaderCircle,
  Plus,
  Trash2,
} from 'lucide-react';
import { usePersonaId, usePersonaState } from '../lib/usePersonaState';
import { api } from '../lib/api';
import { withBase } from '../lib/base';
import { getPersonaId } from '../lib/persona';
import { cn } from '../lib/utils';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  IconButton,
  Skeleton,
  Textarea,
  toast,
  useConfirm,
} from '../components/ui';
import { StageHeader } from '../components/layout/StageHeader';
import { MessageText } from '../features/chat/MessageText';
import type {
  WorkFile,
  WorkStarted,
  WorkSummary,
  WorkTask,
  WorkTurn,
} from '../features/work/types';

const POLL_MS = 1500;
const MAX_TEXT = 8000;

export function fileUrl(taskId: string, path: string) {
  const encoded = path.split('/').map(encodeURIComponent).join('/');
  const persona = getPersonaId();
  // A download link cannot send the persona header, so it goes in the query.
  return withBase(
    `/api/persona/work/${encodeURIComponent(taskId)}/files/${encoded}${persona === 'default' ? '' : `?persona=${encodeURIComponent(persona)}`}`,
  );
}

function size(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function when(iso: string) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getMonth() + 1}月${date.getDate()}日 ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function FileCard({ taskId, file }: { taskId: string; file: WorkFile }) {
  const name = file.path.split('/').pop() ?? file.path;
  const Icon = /\.xlsx$/iu.test(name) ? FileSpreadsheet : FileText;
  return (
    <a
      href={fileUrl(taskId, file.path)}
      download={name}
      className="flex min-h-11 items-center gap-3 rounded-lg border border-border bg-surface px-3 py-2 text-primary hover:bg-soft"
    >
      <Icon aria-hidden className="size-5 shrink-0 text-secondary" />
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium">{file.path}</span>
        <span className="text-xs text-secondary">{size(file.size)}</span>
      </span>
      <Download aria-hidden className="size-4 shrink-0 text-secondary" />
      <span className="sr-only">下载</span>
    </a>
  );
}

function Steps({ steps }: { steps: string[] }) {
  if (!steps.length) return null;
  return (
    <details className="text-sm text-secondary">
      <summary className="cursor-pointer select-none">
        做了 {steps.length} 步
      </summary>
      <ol className="mt-1 list-decimal space-y-0.5 pl-5">
        {steps.map((step, index) => (
          <li key={index}>{step}</li>
        ))}
      </ol>
    </details>
  );
}

function Turn({
  task,
  turn,
  files,
}: {
  task: WorkTask;
  turn: WorkTurn;
  files: Map<string, WorkFile>;
}) {
  if (turn.role === 'user')
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl bg-soft px-4 py-2 whitespace-pre-wrap">
          {turn.content}
        </p>
      </div>
    );
  const delivered = turn.files
    .map((path) => files.get(path))
    .filter((file): file is WorkFile => file !== undefined);
  return (
    <article aria-label="回复" className="space-y-2">
      <Steps steps={turn.steps} />
      <MessageText text={turn.content} />
      {delivered.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {delivered.map((file) => (
            <FileCard key={file.path} taskId={task.task_id} file={file} />
          ))}
        </div>
      )}
    </article>
  );
}

function TaskList({
  tasks,
  current,
  onOpen,
  onNew,
}: {
  tasks: WorkSummary[] | null;
  current: string | null;
  onOpen: (taskId: string) => void;
  onNew: () => void;
}) {
  return (
    <nav aria-label="任务" className="space-y-2">
      <Button
        variant="secondary"
        className="w-full"
        onClick={onNew}
        aria-pressed={current === null}
      >
        <Plus aria-hidden className="size-4" />
        新任务
      </Button>
      {tasks === null && <Skeleton className="h-24" />}
      <ul className="space-y-1">
        {tasks?.map((task) => (
          <li key={task.task_id}>
            <button
              type="button"
              onClick={() => onOpen(task.task_id)}
              aria-current={task.task_id === current ? 'page' : undefined}
              className={cn(
                'flex min-h-11 w-full flex-col rounded-lg px-3 py-2 text-left hover:bg-soft',
                task.task_id === current && 'bg-soft font-medium',
              )}
            >
              <span className="truncate">{task.title}</span>
              <span className="flex items-center gap-2 text-xs text-secondary">
                {when(task.updated_at)}
                {task.status === 'running' && <Badge tone="info">在做</Badge>}
                {task.status === 'failed' && (
                  <Badge tone="danger">没做成</Badge>
                )}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function Work() {
  const personaId = usePersonaId();
  const confirm = useConfirm();
  const [tasks, setTasks] = usePersonaState<WorkSummary[] | null>(null);
  const [current, setCurrent] = usePersonaState<string | null>(null);
  const [task, setTask] = usePersonaState<WorkTask | null>(null);
  const [error, setError] = usePersonaState('');
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  const loadTasks = useCallback(async () => {
    try {
      const data = await api<{ tasks: WorkSummary[] }>('/api/persona/work');
      setTasks(data.tasks);
      setError('');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '加载失败');
    }
  }, [setTasks, setError]);

  const loadTask = useCallback(
    async (taskId: string) => {
      const data = await api<WorkTask>(
        `/api/persona/work/${encodeURIComponent(taskId)}`,
      );
      setTask(data);
      return data;
    },
    [setTask],
  );

  useEffect(() => {
    void loadTasks();
  }, [loadTasks, personaId]);

  useEffect(() => {
    if (current === null) {
      setTask(null);
      return;
    }
    void loadTask(current).catch((failure: unknown) =>
      setError(failure instanceof Error ? failure.message : '加载失败'),
    );
  }, [current, loadTask, setTask, setError]);

  const running = task?.status === 'running';
  const taskId = task?.task_id;
  useEffect(() => {
    if (!running || !taskId) return;
    const timer = window.setInterval(() => {
      void loadTask(taskId)
        .then((next) => {
          if (next.status !== 'running') void loadTasks();
        })
        .catch(() => undefined);
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [running, taskId, loadTask, loadTasks]);

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ block: 'end' });
  }, [task?.turns.length, task?.progress.length]);

  const send = async () => {
    const value = text.trim();
    if (!value || sending || running) return;
    setSending(true);
    try {
      const started = await api<WorkStarted>('/api/persona/work', {
        method: 'POST',
        json: { text: value, ...(current ? { task_id: current } : {}) },
      });
      setText('');
      setCurrent(started.task.task_id);
      await loadTask(started.task.task_id);
      await loadTasks();
    } catch (failure) {
      toast(failure instanceof Error ? failure.message : '发送失败', 'danger');
    } finally {
      setSending(false);
    }
  };

  const remove = async () => {
    if (!task) return;
    const ok = await confirm({
      title: '删除这个任务',
      body: '对话和做出来的文件都会删掉，不能恢复。',
      confirmLabel: '删除',
      tone: 'danger',
    });
    if (!ok) return;
    try {
      await api(`/api/persona/work/${encodeURIComponent(task.task_id)}`, {
        method: 'DELETE',
      });
      setCurrent(null);
      await loadTasks();
    } catch (failure) {
      toast(failure instanceof Error ? failure.message : '删除失败', 'danger');
    }
  };

  const files = new Map(task?.files.map((file) => [file.path, file]) ?? []);
  return (
    <div>
      <StageHeader />
      <div className="page-content grid gap-6 md:grid-cols-[14rem_minmax(0,1fr)]">
        <aside className={cn(current !== null && 'max-md:hidden')}>
          <TaskList
            tasks={tasks}
            current={current}
            onOpen={setCurrent}
            onNew={() => setCurrent(null)}
          />
        </aside>
        <section aria-label="工作区" className="min-w-0 space-y-4">
          {error && (
            <div role="alert" className="space-y-2 text-danger">
              <p>{error}</p>
              <Button variant="secondary" onClick={() => void loadTasks()}>
                重试加载
              </Button>
            </div>
          )}
          {current === null ? (
            <header className="space-y-2">
              <h2 className="text-2xl font-semibold">交代一件事</h2>
              <p className="text-sm text-secondary">
                聊天是问答；这里交给我去做：整理表格、写周报和方案，做完把 Word
                或 Excel 文件交给你。
              </p>
            </header>
          ) : task ? (
            <header className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <Button
                  variant="ghost"
                  size="sm"
                  className="md:hidden"
                  onClick={() => setCurrent(null)}
                >
                  全部任务
                </Button>
                <h2 className="truncate text-xl font-semibold">{task.title}</h2>
              </div>
              <IconButton
                label="删除任务"
                onClick={() => void remove()}
                disabled={running}
              >
                <Trash2 aria-hidden className="size-4" />
              </IconButton>
            </header>
          ) : (
            <Skeleton className="h-40" />
          )}
          {task && (
            <div className="space-y-5">
              {task.turns.map((turn, index) => (
                <Turn key={index} task={task} turn={turn} files={files} />
              ))}
              {running && (
                <div aria-live="polite">
                  <Card className="space-y-2">
                    <p className="flex items-center gap-2 font-medium">
                      <LoaderCircle
                        aria-hidden
                        className="size-4 animate-spin motion-reduce:animate-none"
                      />
                      正在做
                    </p>
                    {task.progress.length > 0 && (
                      <ol className="list-decimal space-y-0.5 pl-5 text-sm text-secondary">
                        {task.progress.map((line, index) => (
                          <li key={index}>{line}</li>
                        ))}
                      </ol>
                    )}
                  </Card>
                </div>
              )}
              {task.status === 'failed' && task.error && (
                <p role="alert" className="text-danger">
                  {task.error}
                </p>
              )}
              <div ref={bottom} />
            </div>
          )}
          {current === null && tasks?.length === 0 && (
            <EmptyState
              title="还没有任务"
              body="比如：把最近会上答应别人的事整理成 Excel；按我的口吻写一份本周周报。"
            />
          )}
          <form
            className="flex items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              void send();
            }}
          >
            <Textarea
              aria-label="要做的事"
              placeholder={
                current === null ? '说说要做什么' : '接着说，或者让我改一改'
              }
              value={text}
              maxLength={MAX_TEXT}
              maxRows={8}
              onChange={(event) => setText(event.target.value)}
              onSend={() => void send()}
              className="flex-1"
            />
            <IconButton
              label="交代"
              type="submit"
              disabled={!text.trim() || sending || running}
            >
              <ArrowUp aria-hidden className="size-5" />
            </IconButton>
          </form>
        </section>
      </div>
    </div>
  );
}
