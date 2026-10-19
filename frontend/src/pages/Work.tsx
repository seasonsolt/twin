import { useCallback, useEffect, useRef } from 'react';
import { useLocation } from 'react-router';
import {
  ArrowUp,
  ChevronDown,
  Download,
  FileSpreadsheet,
  FileText,
  PanelLeft,
  Square,
  SquarePen,
} from 'lucide-react';
import { PersonaFade } from '../components/motion/PersonaFade';
import {
  Card,
  ChatAction,
  ChatIdentity,
  ChatInput,
  ChatSurface,
  Chip,
  Heading,
  IconButton,
  Notice,
  ResizeHandle,
  Row,
  Text,
  toast,
  useConfirm,
  Spacer,
  TypingIndicator,
} from '../components/ui';
import {
  PersonaPortrait,
  PersonaSwitcher,
} from '../components/layout/PersonaSwitcher';
import { Citations } from '../features/chat/Citations';
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
import { useMediaQuery, useMobile } from '../lib/useMobile';
import {
  usePersonaId,
  usePersonaState as useState,
} from '../lib/usePersonaState';
import { SHEET_WIDTH, useChatLayout } from '../stores/chatLayout';
import { usePersonas } from '../stores/personas';
import { useStatus } from '../stores/status';

const POLL_MS = 1500;
const MAX_TEXT = 8000;
const STARTERS = [
  '把最近会上答应别人的事整理成 Excel',
  '按我的口吻写一份本周周报',
  '列一下我还没回答的问题',
];

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
    <Card as="div" variant="outline" padding="none" className="overflow-hidden">
      <a
        href={fileUrl(taskId, file.path)}
        download={name}
        className="flex min-h-11 items-center gap-3 px-3 py-2 text-primary hover:bg-soft"
      >
        <Icon aria-hidden className="size-5 shrink-0 text-secondary" />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">{file.path}</span>
          <Text as="span" size="xs" tone="secondary">
            {size(file.size)}
          </Text>
        </span>
        <Download aria-hidden className="size-4 shrink-0 text-secondary" />
        <span className="sr-only">下载</span>
      </a>
    </Card>
  );
}

function Steps({ steps }: { steps: string[] }) {
  if (!steps.length) return null;
  return (
    <Text as="details" size="sm" tone="secondary" className="mb-1">
      <summary className="cursor-pointer select-none">
        做了 {steps.length} 步
      </summary>
      <ol className="mt-1 list-decimal space-y-0.5 pl-5">
        {steps.map((step, index) => (
          <li key={index}>{step}</li>
        ))}
      </ol>
    </Text>
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
        className="user-bubble ml-auto w-fit max-w-17/20 px-4 py-3"
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
      className="mr-auto w-full max-w-9/10 min-w-0 space-y-2 text-primary"
    >
      <Steps steps={turn.steps} />
      <div className="twin-bubble min-w-0">
        <MessageText text={turn.content} />
      </div>
      {!!turn.cited?.length && (
        <div className="reply-actions mt-1 flex min-w-0 flex-wrap items-center justify-end gap-x-2">
          <Citations cited={turn.cited} />
        </div>
      )}
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
  const mobile = useMobile();
  const wide = useMediaQuery('(min-width: 1280px)');
  // The task list is chat's conversation sheet: the same width and the same open or closed choice.
  const layout = useChatLayout();
  const sheetOpen = !mobile && (layout.sheet ?? wide);
  const confirm = useConfirm();
  const status = useStatus((state) => state.data);
  const persona = usePersonas((state) =>
    state.items.find((item) => item.id === state.id),
  );
  const name = status?.target_name || persona?.name || '本人';
  const [tasks, setTasks] = useState<WorkSummary[] | null>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [task, setTask] = useState<WorkTask | null>(null);
  const [error, setError] = useState('');
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const historyTrigger = useRef<HTMLElement | null>(null);
  const { page, end, composer, composerHeight } = useComposerLayout(active);

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
    if (!mobile) setHistoryOpen(false);
  }, [mobile, setHistoryOpen]);

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
  const switcher = (
    <PersonaSwitcher
      label={`切换分身（当前：${name}）`}
      className="flex min-w-0 items-center gap-2 py-1"
      trigger={
        <>
          <ChatIdentity>
            <PersonaPortrait persona={persona} />
          </ChatIdentity>
          <Text as="span" size="2xl" weight="bold" truncate>
            {name}
          </Text>
          <ChevronDown size={16} aria-hidden />
        </>
      }
    />
  );
  const history = (
    <WorkHistory
      tasks={tasks}
      error={error}
      current={current}
      open={active && historyOpen}
      onOpenChange={(open) =>
        mobile ? setHistoryOpen(open) : layout.setChoice('sheet', open)
      }
      onOpen={setCurrent}
      onNew={() => setCurrent(null)}
      onDelete={(row) => void remove(row)}
      onRetry={() => void loadTasks()}
      name={name}
      inline={!mobile}
      heading={switcher}
      returnFocus={historyTrigger}
    />
  );
  const files = new Map(task?.files.map((file) => [file.path, file]) ?? []);
  const title = current === null ? '新任务' : (task?.title ?? '');
  return (
    <div
      ref={page}
      className="chat-page chat-redesign"
      data-sheet={sheetOpen}
      data-empty={current === null}
    >
      {sheetOpen && (
        <ChatSurface variant="sheet" width={layout.sheetWidth}>
          {history}
          <ResizeHandle
            label="调整任务列表宽度"
            value={layout.sheetWidth ?? SHEET_WIDTH.default}
            min={SHEET_WIDTH.min}
            max={SHEET_WIDTH.max}
            defaultValue={SHEET_WIDTH.default}
            onChange={layout.setSheetWidth}
          />
        </ChatSurface>
      )}
      {mobile && history}
      <ChatSurface
        variant="panel"
        className="flex min-h-0 min-w-0 flex-1 flex-col"
      >
        <header className="chat-topbar" aria-label={`${name}的工作`}>
          {mobile ? (
            <>
              <IconButton label="任务列表" onClick={openHistory}>
                <PanelLeft size={20} aria-hidden />
              </IconButton>
              <PersonaSwitcher
                label={`切换分身（当前：${name}）`}
                className="flex shrink-0 items-center"
                trigger={
                  <ChatIdentity size="mobile">
                    <PersonaPortrait persona={persona} />
                  </ChatIdentity>
                }
              />
              <div className="min-w-0 flex-1">
                <Heading size="section" truncate>
                  {name}
                </Heading>
              </div>
              <IconButton label="新任务" onClick={() => setCurrent(null)}>
                <SquarePen size={20} aria-hidden />
              </IconButton>
            </>
          ) : (
            <>
              {!sheetOpen && (
                <IconButton
                  label="展开任务列表"
                  onClick={() => layout.setChoice('sheet', true)}
                >
                  <PanelLeft size={18} aria-hidden />
                </IconButton>
              )}
              <Heading
                level={1}
                weight="medium"
                size="item"
                truncate
                className="min-w-0 flex-1"
              >
                {!sheetOpen ? `${name} / ` : ''}
                {title}
              </Heading>
            </>
          )}
        </header>
        <div className="chat-body flex min-h-0 flex-1">
          <div className="chat-thread">
            <div className="chat-scroll">
              <div className="chat-column-grid">
                <PersonaFade>
                  <div className="chat-conversation flex flex-col space-y-4">
                    <div aria-live="polite" aria-relevant="additions text">
                      {current === null && (
                        <ChatSurface variant="empty">
                          <ChatIdentity size="empty">
                            <PersonaPortrait persona={persona} />
                          </ChatIdentity>
                          <Heading
                            level={2}
                            size="display"
                            weight="bold"
                            align="center"
                          >
                            交给{name}一件事
                          </Heading>
                          <Text tone="secondary" align="center">
                            聊天是问答；这里交代要做的事，做完把 Word 或 Excel
                            文件交给你。做的过程中可以随时插话或叫停。
                          </Text>
                          <Row gap={2} wrap justify="center">
                            {STARTERS.map((starter) => (
                              <Chip
                                key={starter}
                                onClick={() => {
                                  setDraft(starter);
                                  document
                                    .getElementById('work-input')
                                    ?.focus();
                                }}
                              >
                                {starter}
                              </Chip>
                            ))}
                          </Row>
                        </ChatSurface>
                      )}
                      {current !== null && !task && (
                        <Text role="status" size="sm" tone="secondary">
                          正在加载任务…
                        </Text>
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
                              <TypingIndicator
                                text={task.stopping ? '正在停下…' : '正在做…'}
                              />
                              {task.progress.length > 0 && (
                                <Text
                                  as="ol"
                                  aria-label="进度"
                                  size="sm"
                                  tone="secondary"
                                  className="list-decimal space-y-0.5 pl-5"
                                >
                                  {task.progress.map((line, index) => (
                                    <li key={index}>{line}</li>
                                  ))}
                                </Text>
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                    {task?.status === 'failed' && task.error && (
                      <Notice tone="danger" role="alert">
                        {task.error}
                      </Notice>
                    )}
                    <div ref={end} />
                    {space > 0 && <Spacer height={space} />}
                  </div>
                </PersonaFade>
              </div>
            </div>
            <form
              ref={composer}
              aria-label="交代的事"
              className="chat-composer chat-column-grid"
              onSubmit={(event) => {
                event.preventDefault();
                void send();
              }}
            >
              <ChatSurface variant="composer">
                <ChatInput
                  id="work-input"
                  aria-label="要做的事"
                  maxRows={5}
                  maxLength={MAX_TEXT}
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onSend={() => void send()}
                  placeholder={
                    running
                      ? '插一句，下一步就会看到'
                      : current === null
                        ? `交给${name}一件事…`
                        : '接着说，或者让我改一改'
                  }
                />
                <Row gap={1}>
                  <div className="flex-1" />
                  {running && (
                    <IconButton
                      shape="circle"
                      label="停下"
                      disabled={task.stopping}
                      onClick={() => void stop()}
                    >
                      <Square className="size-4 fill-current" aria-hidden />
                    </IconButton>
                  )}
                  <ChatAction
                    type="submit"
                    variant="send"
                    aria-label={running ? '插话' : '交代'}
                    loading={sending}
                    disabled={!draft.trim()}
                  >
                    {!sending && <ArrowUp className="size-5" aria-hidden />}
                  </ChatAction>
                </Row>
              </ChatSurface>
            </form>
          </div>
        </div>
      </ChatSurface>
    </div>
  );
}
