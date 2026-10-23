import { useEffect, useRef, type ReactNode } from 'react';
import {
  ArrowUp,
  Download,
  FileSpreadsheet,
  FileText,
  Square,
} from 'lucide-react';
import { PersonaFade } from '../../components/motion/PersonaFade';
import { PersonaPortrait } from '../../components/layout/PersonaSwitcher';
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
  Row,
  Spacer,
  Text,
  TypingIndicator,
} from '../../components/ui';
import { withBase } from '../../lib/base';
import { getPersonaId } from '../../lib/persona';
import { usePersonaState as useState } from '../../lib/usePersonaState';
import type { Persona } from '../../stores/personas';
import { Citations } from '../chat/Citations';
import { MessageText } from '../chat/MessageText';
import {
  usePinnedMessage,
  type ComposerLayout,
} from '../chat/useComposerLayout';
import type { Work } from './useWork';
import type { WorkFile, WorkTurn } from './types';

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

/**
 * One task with the twin: what was asked and answered, the progress of the turn in flight, the files made, and the
 * box to give the next instruction, a word while it runs, or the stop. The page around it (the list, the header)
 * lives in the conversation page; ``modeSwitch`` is its 问答 / 交代任务 choice, shown in the composer.
 */
export function WorkThread({
  active,
  work,
  name,
  persona,
  layout,
  modeSwitch,
  target,
}: {
  active: boolean;
  work: Work;
  name: string;
  persona?: Persona;
  layout: ComposerLayout;
  modeSwitch?: ReactNode;
  /** Whom the instruction goes to, with the way to change it, beside the box. */
  target?: ReactNode;
}) {
  const { end, composer, composerHeight } = layout;
  const { task, current, draft, setDraft, sending, running } = work;
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
  const send = () => {
    pinNext.current = true;
    void work.send().then((sent) => {
      if (!sent) pinNext.current = false;
    });
  };
  const files = new Map(task?.files.map((file) => [file.path, file]) ?? []);
  return (
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
                            document.getElementById('work-input')?.focus();
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
          send();
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
            onSend={send}
            placeholder={
              running
                ? '插一句，下一步就会看到'
                : current === null
                  ? `交给${name}一件事…`
                  : '接着说，或者让我改一改'
            }
          />
          <Row gap={1}>
            {target}
            {modeSwitch}
            <div className="flex-1" />
            {running && (
              <IconButton
                shape="circle"
                label="停下"
                disabled={task?.stopping}
                onClick={() => void work.stop()}
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
  );
}
