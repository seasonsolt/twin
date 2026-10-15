import { useCallback, useEffect, useRef, type CSSProperties } from 'react';
import { useLocation } from 'react-router';
import {
  ArrowUp,
  Download,
  FileSpreadsheet,
  FileText,
  Square,
} from 'lucide-react';
import { ThinkingLabel } from '../components/effects/ThinkingLabel';
import { PersonaFade } from '../components/motion/PersonaFade';
import {
  Button,
  EmptyState,
  Textarea,
  toast,
  useConfirm,
} from '../components/ui';
import type { Capabilities } from '../features/avatar/types';
import { ChatStage } from '../features/chat/ChatStage';
import { MessageText } from '../features/chat/MessageText';
import {
  useComposerLayout,
  usePinnedMessage,
} from '../features/chat/useComposerLayout';
import { WorkHistory } from '../features/work/WorkHistory';
import type {
  WorkFile,
  WorkStarted,
  WorkSummary,
  WorkTask,
  WorkTurn,
} from '../features/work/types';
import { api } from '../lib/api';
import { withBase } from '../lib/base';
import { getPersonaId } from '../lib/persona';
import { loadEssential, peekEssential } from '../lib/personaPrefetch';
import { useDesktop } from '../lib/useMobile';
import {
  usePersonaId,
  usePersonaState as useState,
} from '../lib/usePersonaState';
import { usePersonas } from '../stores/personas';
import { useStatus } from '../stores/status';

const POLL_MS = 1500;
const MAX_TEXT = 8000;
const STARTERS = [
  '把最近会上答应别人的事整理成 Excel',
  '按我的口吻写一份本周周报',
  '列一下我还没回答的问题',
];
const noop = () => undefined;

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

function FileCard({ taskId, file }: { taskId: string; file: WorkFile }) {
  const name = file.path.split('/').pop() ?? file.path;
  const Icon = /\.xlsx$/iu.test(name) ? FileSpreadsheet : FileText;
  return (
    <a
      href={fileUrl(taskId, file.path)}
      download={name}
      className="flex min-h-11 items-center gap-3 rounded-2xl border border-border bg-surface px-3 py-2 text-primary hover:bg-soft"
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
    <details className="mb-1 text-sm text-secondary">
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
  taskId,
  turn,
  pin,
  files,
}: {
  taskId: string;
  turn: WorkTurn;
  pin: string;
  files: Map<string, WorkFile>;
}) {
  if (turn.role === 'user')
    return (
      <article
        aria-label="你说"
        data-pin={pin}
        className="user-bubble ml-auto w-fit max-w-[85%] px-4 py-3"
      >
        <MessageText text={turn.content} plain />
      </article>
    );
  const delivered = turn.files
    .map((path) => files.get(path))
    .filter((file): file is WorkFile => file !== undefined);
  return (
    <article
      aria-label="回复"
      className="mr-auto w-full max-w-[90%] min-w-0 space-y-2 text-primary"
    >
      <Steps steps={turn.steps} />
      <div className="twin-bubble min-w-0">
        <MessageText text={turn.content} />
      </div>
      {delivered.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {delivered.map((file) => (
            <FileCard key={file.path} taskId={taskId} file={file} />
          ))}
        </div>
      )}
    </article>
  );
}

export function Work() {
  const personaId = usePersonaId();
  const { pathname } = useLocation();
  const active = pathname === '/work';
  const desktop = useDesktop();
  const confirm = useConfirm();
  const status = useStatus((state) => state.data);
  const persona = usePersonas((state) =>
    state.items.find((item) => item.id === state.id),
  );
  const name = status?.target_name || persona?.name || '本人';
  const [capabilities, setCapabilities] = useState<Capabilities | null>(
    () =>
      peekEssential<Capabilities>('/api/media/capabilities', personaId) ?? null,
  );
  const [tasks, setTasks] = useState<WorkSummary[] | null>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [task, setTask] = useState<WorkTask | null>(null);
  const [error, setError] = useState('');
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const historyTrigger = useRef<HTMLElement | null>(null);
  const { end, composer, composerHeight } = useComposerLayout(active);

  useEffect(() => {
    const controller = new AbortController();
    void loadEssential<Capabilities>(
      '/api/media/capabilities',
      personaId,
      controller.signal,
    )
      .then((data) => {
        if (!controller.signal.aborted) setCapabilities(data);
      })
      .catch(() => {});
    return () => controller.abort();
  }, [personaId, setCapabilities]);

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
    if (desktop) setHistoryOpen(false);
  }, [desktop, setHistoryOpen]);

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

  // A message the person sends (a new task, a follow-up or a word while it runs) goes to the top with room for
  // the reply below; a task opened from the list shows its end.
  const pinNext = useRef(false);
  const [pinned, setPinned] = useState<string | null>(null);
  const latestUser = task
    ? task.turns.map((turn) => turn.role).lastIndexOf('user')
    : -1;
  const latestPin =
    task && latestUser >= 0 ? `${task.task_id}:${latestUser}` : null;
  useEffect(() => {
    if (!pinNext.current || !latestPin) return;
    pinNext.current = false;
    setPinned(latestPin);
  }, [latestPin, setPinned]);
  const pinnedId =
    pinned && task && pinned.startsWith(`${task.task_id}:`) ? pinned : null;
  const space = usePinnedMessage(pinnedId, end, composer);
  useEffect(() => {
    if (active && !pinnedId) end.current?.scrollIntoView?.({ block: 'end' });
  }, [
    active,
    end,
    pinnedId,
    task?.turns.length,
    task?.progress.length,
    composerHeight,
  ]);

  const send = async () => {
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    pinNext.current = true;
    try {
      const started = await api<WorkStarted>('/api/persona/work', {
        method: 'POST',
        json: { text, ...(current ? { task_id: current } : {}) },
      });
      setDraft('');
      setCurrent(started.task.task_id);
      await loadTask(started.task.task_id);
      await loadTasks();
    } catch (failure) {
      pinNext.current = false;
      toast(failure instanceof Error ? failure.message : '发送失败', 'danger');
    } finally {
      setSending(false);
    }
  };

  const stop = async () => {
    if (!taskId) return;
    try {
      await api(`/api/persona/work/${encodeURIComponent(taskId)}/stop`, {
        method: 'POST',
      });
      await loadTask(taskId);
    } catch (failure) {
      toast(failure instanceof Error ? failure.message : '没能停下', 'danger');
    }
  };

  const remove = async (row: WorkSummary) => {
    const ok = await confirm({
      title: '删除任务？',
      body: `“${row.title}”和做出来的文件都会删掉，不能恢复。`,
      confirmLabel: '删除',
      tone: 'danger',
    });
    if (!ok) return;
    try {
      await api(`/api/persona/work/${encodeURIComponent(row.task_id)}`, {
        method: 'DELETE',
      });
      if (row.task_id === current) setCurrent(null);
      await loadTasks();
    } catch (failure) {
      toast(failure instanceof Error ? failure.message : '删除失败', 'danger');
    }
  };

  const openHistory = () => {
    historyTrigger.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    setHistoryOpen(true);
    void loadTasks();
  };
  const history = (
    <WorkHistory
      tasks={tasks}
      error={error}
      current={current}
      open={active && historyOpen}
      onOpenChange={setHistoryOpen}
      onOpen={setCurrent}
      onNew={() => setCurrent(null)}
      onDelete={(row) => void remove(row)}
      onRetry={() => void loadTasks()}
      name={name}
      inline={desktop}
      returnFocus={historyTrigger}
    />
  );
  // The stage shows who is working; it does not speak or play video here.
  const stageCapabilities = capabilities && {
    ...capabilities,
    available: false,
    video: undefined,
  };
  const files = new Map(task?.files.map((file) => [file.path, file]) ?? []);
  return (
    <div
      className="chat-page"
      data-empty={current === null}
      style={{ '--composer-height': `${composerHeight}px` } as CSSProperties}
    >
      <ChatStage
        name={name}
        capabilities={stageCapabilities}
        videoPlaying={false}
        voiceCaption=""
        level={0}
        speaking={false}
        onToggle={noop}
        onVideoPlaying={noop}
        onVideoError={noop}
        onClear={() => setCurrent(null)}
        onHistory={openHistory}
        history={desktop ? history : undefined}
        newLabel="新任务"
        historyLabel="任务记录"
      />
      {!desktop && history}
      <div className="chat-thread">
        <div className="chat-scroll">
          <div className="chat-column-grid">
            <PersonaFade>
              <div className="chat-conversation flex flex-col space-y-4">
                <div aria-live="polite" aria-relevant="additions text">
                  {current === null && (
                    <EmptyState
                      title={`交给${name}一件事`}
                      body="聊天是问答；这里交代要做的事，做完把 Word 或 Excel 文件交给你。做的过程中可以随时插话或叫停。"
                    >
                      <div
                        className="starter-chips flex flex-wrap justify-center gap-3"
                        aria-label="可以交代的事"
                      >
                        {STARTERS.map((starter) => (
                          <button
                            key={starter}
                            type="button"
                            className="starter-chip min-h-11 rounded-full border border-primary px-4 text-primary"
                            onClick={() => {
                              setDraft(starter);
                              document.getElementById('work-input')?.focus();
                            }}
                          >
                            {starter}
                          </button>
                        ))}
                      </div>
                    </EmptyState>
                  )}
                  {current !== null && !task && (
                    <p role="status" className="text-sm text-secondary">
                      正在加载任务…
                    </p>
                  )}
                  {task && (
                    <div className="space-y-4">
                      {task.turns.map((turn, index) => (
                        <Turn
                          key={index}
                          taskId={task.task_id}
                          turn={turn}
                          pin={`${task.task_id}:${index}`}
                          files={files}
                        />
                      ))}
                      {running && (
                        <div className="space-y-1 py-1">
                          <ThinkingLabel
                            text={task.stopping ? '正在停下…' : '正在做…'}
                          />
                          {task.progress.length > 0 && (
                            <ol
                              aria-label="进度"
                              className="list-decimal space-y-0.5 pl-5 text-sm text-secondary"
                            >
                              {task.progress.map((line, index) => (
                                <li key={index}>{line}</li>
                              ))}
                            </ol>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
                {task?.status === 'failed' && task.error && (
                  <div
                    role="alert"
                    className="rounded-md border border-danger/20 bg-danger/5 px-3 py-2 text-danger"
                  >
                    {task.error}
                  </div>
                )}
                <div ref={end} />
                {space > 0 && <div aria-hidden style={{ height: space }} />}
              </div>
            </PersonaFade>
          </div>
        </div>
        <form
          ref={composer}
          aria-label="交代的事"
          className="chat-composer chat-column-grid fixed inset-x-0 z-20 border-t border-border bg-canvas/95 px-3 pt-2 backdrop-blur-xl md:left-[var(--sidebar-width,0px)]"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <div className="composer-field mx-auto flex max-w-3xl items-end gap-1 bg-surface py-1 pr-1 pl-2">
            <Textarea
              id="work-input"
              aria-label="要做的事"
              rows={1}
              maxRows={5}
              maxLength={MAX_TEXT}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onSend={() => void send()}
              className="min-h-11 border-0 bg-transparent px-2 py-2.5 shadow-none focus-visible:outline-none"
              placeholder={
                running
                  ? '插一句，下一步就会看到'
                  : current === null
                    ? `交给${name}一件事…`
                    : '接着说，或者让我改一改'
              }
            />
            {running && (
              <Button
                type="button"
                variant="ghost"
                aria-label="停下"
                className="size-11 min-h-11 rounded-full p-0"
                disabled={task.stopping}
                onClick={() => void stop()}
              >
                <Square className="size-4 fill-current" aria-hidden />
              </Button>
            )}
            <Button
              type="submit"
              aria-label={running ? '插话' : '交代'}
              className="send-button size-11 min-h-11 rounded-full p-0"
              loading={sending}
              disabled={!draft.trim()}
            >
              {!sending && <ArrowUp className="size-5" aria-hidden />}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
