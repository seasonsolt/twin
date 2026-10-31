import { useCallback, useEffect, useRef, type ReactNode } from 'react';
import { ArrowUp, CircleHelp, Copy, Play, Plus, X } from 'lucide-react';
import { MessageList } from '../../components/effects/MessageList';
import { PersonaFade } from '../../components/motion/PersonaFade';
import { PersonaPortrait } from '../../components/layout/PersonaSwitcher';
import {
  Badge,
  Button,
  ChatAction,
  ChatIdentity,
  ChatInput,
  ChatMessage,
  ChatSurface,
  Chip,
  FileInput,
  Heading,
  IconButton,
  Notice,
  PlainButton,
  Row,
  Select,
  Spacer,
  Text,
  TextLink,
  toast,
  Tooltip,
  TypingIndicator,
} from '../../components/ui';
import { api } from '../../lib/api';
import {
  usePersonaId,
  usePersonaState as useState,
} from '../../lib/usePersonaState';
import { useSeesWhole } from '../../stores/access';
import { featureOn, useAuth, usePersonaEdition } from '../../stores/auth';
import { useStatus } from '../../stores/status';
import type { Persona } from '../../stores/personas';
import { askOwner } from '../answers/askOwner';
import { TeamAnswerCard } from '../answers/TeamAnswerCard';
import { Delegation } from '../delegation/Delegation';
import { LensCard } from '../lens/LensCard';
import { useLensChoices } from '../lens/useLensChoices';
import { useIdentity } from '../identity/useIdentity';
import { MemoryUpdating } from '../memories/BuildProgress';
import { SetupCard } from '../setup/SetupCard';
import { ChatCore } from './ChatCore';
import { MessageText } from './MessageText';
import { NoteCard } from './NoteCard';
import { ReplyLine } from './ReplyDetails';
import { usePinnedMessage, type ComposerLayout } from './useComposerLayout';
import type { ChatStep, useConversation } from './useConversation';
import {
  handoffText,
  promiseTaken,
  type ChatReply,
  type Reflection,
  type SelfRating,
  type Turn,
} from './types';
import { usePace } from './usePace';
import type { Playback } from './usePlayback';

const CHAT_ATTACHMENT_ACCEPT =
  '.txt,.md,.pdf,.docx,.epub,.html,.htm,.csv,.json,.srt,.vtt';
const CHAT_ATTACHMENT_SUFFIXES = new Set(
  'txt md pdf docx epub html htm csv json srt vtt'.split(' '),
);
const MAX_CHAT_ATTACHMENT_COUNT = 5;
const STEP_TEXT: Record<ChatStep, string> = {
  search: '查资料…',
  think: '推算中…',
  write: '写回答…',
};
// More lenses than this are chosen from a list, not laid out as a chip each.
const MAX_LENS_CHIPS = 2;
const MAX_CHAT_ATTACHMENT_BYTES = 50 * 1024 * 1024;

/** What the asker said before the twin's turn at `index`: the question a team answer card was given to. */
function askedBefore(turns: Turn[], index: number): string {
  for (let i = index - 1; i >= 0; i--) {
    if (turns[i].role === 'user') return turns[i].content;
  }
  return '';
}

/**
 * Whether a reply is no answer of the twin's memory, so that "how it rests on what the twin knows" is not said under
 * it: what the assistant took down, a lens's statements, what it asked colleagues, where help is when the message
 * spoke of harming oneself, and an answer that is the team's confirmed one (shown as its card).
 */
const unlabelled = (reply: ChatReply) =>
  !!reply.note ||
  !!reply.crisis ||
  !!reply.lens ||
  !!reply.delegation ||
  (!!reply.team_answers?.length &&
    reply.mode === 'general' &&
    !reply.cited?.length);

const SELF_RATINGS: readonly { id: SelfRating; label: string }[] = [
  { id: 'like', label: '像我' },
  { id: 'unlike', label: '不像我' },
];

/** 像我 / 不像我 under an answer: pressed again, the mark is taken back. */
function SelfRatingButtons({
  value,
  onRate,
}: {
  value?: SelfRating;
  onRate: (value: SelfRating | null) => void;
}) {
  return (
    <span role="group" aria-label="像不像我" className="flex items-center">
      {SELF_RATINGS.map((option) => (
        <ChatAction
          key={option.id}
          size="sm"
          selected={value === option.id}
          aria-pressed={value === option.id}
          onClick={() => onRate(value === option.id ? null : option.id)}
        >
          {option.label}
        </ChatAction>
      ))}
    </span>
  );
}

/**
 * One conversation with the twin: the notes above it (memory being organised, a new twin's setup), the messages with
 * what each rests on and the buttons to speak or copy it, and the box to ask the next question. The page around it
 * (the list, the header, the portrait) lives in the conversation page; ``modeSwitch`` is its 问答 / 交代任务 choice,
 * shown in the composer.
 */
export function ChatThread({
  active,
  chat,
  playback,
  name,
  persona,
  canManage,
  layout,
  modeSwitch,
  target,
  assistant = false,
  trial,
  look,
  reflection = 'ask',
}: {
  active: boolean;
  chat: ReturnType<typeof useConversation>;
  playback: Playback;
  name: string;
  persona?: Persona;
  /** Whether the viewer is the person behind this twin: only they correct what it remembers. */
  canManage: boolean;
  layout: ComposerLayout;
  modeSwitch?: ReactNode;
  /** Whom the message goes to, with the way to change it, beside the box. */
  target?: ReactNode;
  /** The person's own conversation with their assistant: it speaks to them, and takes down what they tell it. */
  assistant?: boolean;
  /** 看同事会得到什么 on or off; given only where the person can ask it. */
  trial?: { on: boolean; onChange(on: boolean): void };
  /** The persona edition's 素体: the twin's core stands over the chat in place of its portrait. */
  look?: 'sutai';
  /** The way the person is talking with their assistant about themself, chosen beside the box. */
  reflection?: Reflection;
}) {
  const personaId = usePersonaId();
  const personaEdition = usePersonaEdition();
  // In their own conversation the person says of an answer whether it is like them (自评记录), once it is saved.
  const rating = personaEdition && assistant && chat.conversationId !== null;
  // The person behind a twin reads what it says in their name; theirs to know, said once under the box.
  const seen = !useSeesWhole(persona) && persona?.claimed !== false;
  // Commitments are listed in a page an administrator can switch off; where it is off, they are not spoken of either.
  const ledgerOn = useAuth((auth) => featureOn(auth.identity, 'ledger'));
  const identity = useIdentity(active);
  const { audio, video, capabilities, toggleReply, speaking, speakable } =
    playback;
  // Only the person's own conversation in the persona edition keeps their pace.
  const pace = usePace(assistant && look === 'sutai', chat.busy);
  const status = useStatus((state) => state.data);
  const { end, composer, composerHeight } = layout;
  const attachmentInput = useRef<HTMLInputElement>(null);
  const [attachmentError, setAttachmentError] = useState('');
  // A twin still getting to know its person shows how in its chat until this visit ends, even once it is done.
  const [setup, setSetup] = useState(false);
  const newTwin =
    canManage &&
    !!identity.data &&
    !identity.data.visitor &&
    (!!identity.data.onboarding_pending || status?.counts.sources === 0);
  useEffect(() => {
    if (newTwin) setSetup(true);
  }, [newTwin, setSetup]);
  // While its steps show, the card is the empty chat's only content; once it remembers, the greeting returns.
  const [setupReady, setSetupReady] = useState(false);
  const [stale, setStale] = useState(false);
  const [stateError, setStateError] = useState('');
  const stateRequest = useRef<AbortController | null>(null);
  const alive = useRef(false);
  const refreshState = useCallback(async () => {
    stateRequest.current?.abort();
    const controller = new AbortController();
    stateRequest.current = controller;
    try {
      const memory = await api<{ stale: boolean }>('/api/persona/state', {
        headers: { 'X-Twin-Persona': personaId },
        signal: controller.signal,
      });
      if (!controller.signal.aborted && alive.current) {
        setStale(memory.stale);
        setStateError('');
      }
    } catch (error) {
      if (!controller.signal.aborted && alive.current)
        setStateError(
          error instanceof Error ? error.message : '无法检查档案状态',
        );
    }
  }, [personaId, setStale, setStateError]);
  useEffect(() => {
    alive.current = active;
    if (active) void refreshState();
    return () => {
      alive.current = false;
      stateRequest.current?.abort();
    };
  }, [active, refreshState]);
  // Another conversation, or a fresh one: a complaint about a file belongs to the one it was made in.
  const { conversationId } = chat;
  useEffect(() => {
    setAttachmentError('');
  }, [conversationId, setAttachmentError]);
  // A message the person sends goes to the top with room for the reply below; a conversation opened from
  // history shows its end.
  const pinNext = useRef(false);
  const [pinned, setPinned] = useState<string | null>(null);
  const latestUser =
    [...chat.turns].reverse().find((turn) => turn.role === 'user')?.id ?? null;
  useEffect(() => {
    if (!pinNext.current || !latestUser) return;
    pinNext.current = false;
    setPinned(latestUser);
  }, [latestUser, setPinned]);
  const pinnedId =
    pinned && chat.turns.some((turn) => turn.id === pinned) ? pinned : null;
  const space = usePinnedMessage(pinnedId, end, composer);
  useEffect(() => {
    if (active && !pinnedId) end.current?.scrollIntoView?.({ block: 'end' });
  }, [active, end, pinnedId, chat.turns, chat.busy, composerHeight]);
  // Once the person has had a say, or a question went to them, who said what is marked: the twin's answers and
  // the person's own words are not the same thing.
  const marked = chat.turns.some(
    (turn) => turn.role === 'self' || turn.handoff,
  );
  const lastAnswer = [...chat.turns]
    .reverse()
    .find((turn) => turn.role === 'twin')?.id;
  // The handoffs whose reply stands in the conversation: the line under the answer does not say it a second time.
  const repliedHere = new Set(
    chat.turns.flatMap((turn) =>
      turn.role === 'self' && turn.handoff_id ? [turn.handoff_id] : [],
    ),
  );
  const trying = !!trial?.on;
  // The lenses the person behind this twin published for colleagues, to ask in place of the twin; the one chosen
  // answers the next question.
  const lenses = useLensChoices(active && !assistant);
  const [lensId, setLensId] = useState<string | null>(null);
  const lens = lenses.choices.find((choice) => choice.id === lensId);
  const { reload: reloadLenses } = lenses;
  const failed = chat.error;
  useEffect(() => {
    // A lens that was held or taken back meanwhile is no longer offered.
    if (failed && lensId) void reloadLenses();
  }, [failed, lensId, reloadLenses]);
  useEffect(() => {
    // Also when none is offered any more: a lens that comes back later is not asked until it is chosen again.
    if (lensId && !lens) setLensId(null);
  }, [lensId, lens, setLensId]);
  // A trial question and a question to a lens take no files: those added wait for an ordinary message.
  const filesWait = trying || !!lens;
  const send = () => {
    if (chat.busy || chat.loading || chat.restoreFailed || !chat.draft.trim())
      return;
    audio.stop();
    audio.unlock();
    setAttachmentError('');
    void refreshState();
    pinNext.current = true;
    void chat.send(chat.draft, !!trial?.on, lens?.id ?? null, reflection);
  };
  // The words the assistant needs to take something down, put in the box, with the cursor after them.
  const addNote = () => {
    const start = '记一下，';
    chat.setDraft(start);
    window.requestAnimationFrame(() => {
      const box = document.getElementById('chat-input');
      if (!(box instanceof HTMLTextAreaElement)) return;
      box.focus();
      box.setSelectionRange(start.length, start.length);
    });
  };
  const addAttachments = (files: File[]) => {
    if (!files.length) return;
    const next = [...chat.attachments, ...files];
    if (next.length > MAX_CHAT_ATTACHMENT_COUNT) {
      setAttachmentError(`一次最多附加 ${MAX_CHAT_ATTACHMENT_COUNT} 个文件`);
      return;
    }
    const unsupported = files.find(
      (file) =>
        !CHAT_ATTACHMENT_SUFFIXES.has(
          file.name.split('.').at(-1)?.toLowerCase() ?? '',
        ),
    );
    if (unsupported) {
      setAttachmentError(
        `暂不支持 ${unsupported.name}，请上传可提取文字的文档`,
      );
      return;
    }
    const oversized = files.find(
      (file) => file.size > MAX_CHAT_ATTACHMENT_BYTES,
    );
    if (oversized) {
      setAttachmentError(`${oversized.name} 超过 50 MB，请拆分后上传`);
      return;
    }
    if (
      next.reduce((total, file) => total + file.size, 0) >
      MAX_CHAT_ATTACHMENT_BYTES
    ) {
      setAttachmentError('单次附件总量不能超过 50 MB');
      return;
    }
    setAttachmentError('');
    chat.setAttachments(next);
  };
  return (
    <div className="chat-thread">
      {look === 'sutai' && (
        <ChatCore
          pulse={chat.turns.length}
          thinking={chat.busy && !chat.newest}
        />
      )}
      <div className="chat-scroll">
        <div className="chat-column-grid">
          <PersonaFade>
            <div className="chat-conversation flex flex-col space-y-4">
              {status?.memory_updating && <MemoryUpdating />}
              {stale && canManage && (
                <Text role="status" size="xs" tone="secondary">
                  新添加的记忆正在处理中，聊天暂时使用已记住的内容。{' '}
                  <TextLink href="#/profile?section=memories">
                    查看记忆
                  </TextLink>
                </Text>
              )}
              {stateError && (
                <Text as="div" role="alert" size="sm" tone="danger">
                  无法检查档案状态：{stateError}{' '}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void refreshState()}
                  >
                    重新检查
                  </Button>
                </Text>
              )}
              <div
                aria-live="polite"
                aria-relevant="additions text"
                data-testid="chat-messages"
              >
                {chat.loading && (
                  <Text role="status" size="sm" tone="secondary">
                    正在加载对话…
                  </Text>
                )}
                {!chat.turns.length && !chat.loading && (
                  <ChatSurface variant="empty">
                    {(!setup || setupReady) && (
                      <>
                        {look !== 'sutai' && (
                          <ChatIdentity size="empty">
                            <PersonaPortrait persona={persona} />
                          </ChatIdentity>
                        )}
                        <Heading
                          level={2}
                          size="display"
                          weight="bold"
                          align="center"
                        >
                          {assistant ? '我的分身' : `和${name}聊聊`}
                        </Heading>
                        {identity.data?.about && (
                          <Text tone="secondary" align="center">
                            {identity.data.about}
                          </Text>
                        )}
                      </>
                    )}
                    {setup && identity.data && (
                      <div className="w-full max-w-xl text-left">
                        <SetupCard
                          name={name}
                          identity={identity.data}
                          onIdentityChanged={identity.reload}
                          onAsk={(question) => void chat.send(question)}
                          onReadyChange={setSetupReady}
                        />
                      </div>
                    )}
                  </ChatSurface>
                )}
                <MessageList
                  label="对话记录"
                  className="space-y-4"
                  items={chat.turns.map((turn, index) => ({
                    id: turn.id,
                    text: turn.content,
                    content:
                      turn.role === 'self' ? (
                        <ChatMessage speaker="self" aria-label="本人回复">
                          <Row gap={2}>
                            <Badge tone="info">本人</Badge>
                          </Row>
                          <div className="min-w-0">
                            <MessageText text={turn.content} plain />
                          </div>
                          {ledgerOn &&
                            promiseTaken(chat.turns, turn.handoff_id) &&
                            (persona?.can_manage ? (
                              <TextLink size="xs" to="/commitments">
                                已记为承诺 ›
                              </TextLink>
                            ) : (
                              <Text size="xs" tone="secondary">
                                已记为承诺
                              </Text>
                            ))}
                        </ChatMessage>
                      ) : (
                        <ChatMessage
                          speaker={turn.role}
                          last={turn.id === lastAnswer}
                          aria-label={
                            turn.role === 'user' ? '你说' : '分身回复'
                          }
                          data-pin={turn.role === 'user' ? turn.id : undefined}
                        >
                          {turn.preview ? (
                            <Text as="span" size="xs" tone="secondary">
                              {turn.role === 'user' ? '试问' : '同事会得到'}
                            </Text>
                          ) : (
                            marked &&
                            turn.role === 'twin' && (
                              <Text as="span" size="xs" tone="secondary">
                                {name}的分身
                              </Text>
                            )
                          )}
                          {assistant &&
                            turn.reply?.as_of &&
                            !turn.reply.crisis && (
                              <Text size="xs" tone="secondary">
                                这是 {turn.reply.as_of.slice(0, 4)}{' '}
                                年的你，只知道那年以前的事
                              </Text>
                            )}
                          {turn.reply?.team_answers?.map((card) => (
                            <TeamAnswerCard
                              key={card.id}
                              card={card}
                              onAsk={
                                turn.preview
                                  ? undefined
                                  : () =>
                                      askOwner(
                                        card.id,
                                        askedBefore(chat.turns, index),
                                      )
                              }
                            />
                          ))}
                          <div
                            className={
                              turn.role === 'twin'
                                ? 'twin-bubble min-w-0'
                                : 'min-w-0'
                            }
                            data-speaking={speaking(turn.id)}
                          >
                            {turn.reply?.lens ? (
                              <LensCard
                                card={turn.reply.lens}
                                onAskOwner={
                                  turn.id === lastAnswer && !turn.handoff
                                    ? () => chat.askLensOwner(turn.id)
                                    : undefined
                                }
                              />
                            ) : (
                              <MessageText
                                text={turn.content}
                                plain={turn.role === 'user'}
                                streaming={
                                  turn.role === 'twin' &&
                                  !turn.reply &&
                                  chat.busy
                                }
                              />
                            )}
                          </div>
                          {turn.reply && (
                            <>
                              <ReplyLine
                                reply={turn.reply}
                                editable={canManage}
                                own={assistant && !turn.preview}
                                plain={unlabelled(turn.reply)}
                              >
                                {(capabilities?.available ||
                                  !unlabelled(turn.reply)) && (
                                  <div
                                    role="group"
                                    aria-label="回复媒体"
                                    className="answer-controls ml-auto flex items-center"
                                  >
                                    {capabilities?.available &&
                                      !speakable(turn) && (
                                        <Tooltip label="在「关于你」同意用你的声音后，可以用它朗读">
                                          <IconButton
                                            label="怎么朗读内在声音"
                                            shape="circle"
                                          >
                                            <CircleHelp
                                              className="size-4"
                                              aria-hidden
                                            />
                                          </IconButton>
                                        </Tooltip>
                                      )}
                                    {speakable(turn) && (
                                      <PlainButton
                                        shape="circle"
                                        className="reply-play min-h-11 min-w-11"
                                        aria-label={
                                          speaking(turn.id)
                                            ? '正在说这句，点击暂停'
                                            : `让${name}说这句`
                                        }
                                        aria-busy={
                                          audio.id === turn.id && audio.loading
                                        }
                                        data-speaking={speaking(turn.id)}
                                        data-generating={
                                          video.videos[turn.id]?.status ===
                                          'generating'
                                        }
                                        onClick={() => toggleReply(turn)}
                                      >
                                        <span
                                          className="reply-play-visual"
                                          aria-hidden
                                        >
                                          {speaking(turn.id) ? (
                                            <span className="speaking-bars">
                                              <i />
                                              <i />
                                              <i />
                                            </span>
                                          ) : (
                                            <Play size={16} />
                                          )}
                                        </span>
                                      </PlainButton>
                                    )}
                                    {!unlabelled(turn.reply) && (
                                      <IconButton
                                        label="复制"
                                        onClick={() => {
                                          void navigator.clipboard
                                            .writeText(turn.content)
                                            .then(() => toast('已复制'))
                                            .catch(() =>
                                              toast('复制失败，请重试'),
                                            );
                                        }}
                                      >
                                        <Copy size={16} aria-hidden />
                                      </IconButton>
                                    )}
                                    {rating &&
                                      !turn.preview &&
                                      !turn.reply.abstain &&
                                      !unlabelled(turn.reply) && (
                                        <SelfRatingButtons
                                          value={turn.self_rating}
                                          onRate={(value) => {
                                            void chat
                                              .rateReply(turn.id, value)
                                              .catch(() =>
                                                toast(
                                                  '没能记下，请重试',
                                                  'danger',
                                                ),
                                              );
                                          }}
                                        />
                                      )}
                                  </div>
                                )}
                              </ReplyLine>
                              {turn.handoff &&
                                !(
                                  turn.handoff.status === 'replied' &&
                                  repliedHere.has(turn.handoff.id)
                                ) && (
                                  <Text
                                    role="status"
                                    size="xs"
                                    tone="secondary"
                                  >
                                    {handoffText(turn.handoff)}
                                  </Text>
                                )}
                              {turn.reply.note && (
                                <NoteCard
                                  note={turn.reply.note}
                                  onTier={(tier) =>
                                    chat.setNoteTier(turn.id, tier)
                                  }
                                />
                              )}
                              {turn.reply.delegation && (
                                <Delegation note={turn.reply.delegation} />
                              )}
                              {ledgerOn && turn.reply.commitment && (
                                <Text size="xs" tone="secondary">
                                  已记入承诺：{turn.reply.commitment.what}
                                  {turn.reply.commitment.due
                                    ? ` · ${turn.reply.commitment.due}前`
                                    : ''}{' '}
                                  <TextLink
                                    onClick={() => {
                                      void chat
                                        .undoPromise(turn.id)
                                        .catch(() =>
                                          toast('没能撤销，请重试', 'danger'),
                                        );
                                    }}
                                  >
                                    撤销
                                  </TextLink>
                                </Text>
                              )}
                              {!!turn.reply.preview?.withheld.length && (
                                <Row gap={2} wrap aria-label="没给同事的">
                                  {turn.reply.preview.withheld.map((item) => (
                                    <Badge key={item.id} title={item.text}>
                                      未用 · {item.facet}
                                    </Badge>
                                  ))}
                                </Row>
                              )}
                              {assistant &&
                                !turn.preview &&
                                turn.reply.abstain &&
                                turn.id === lastAnswer && (
                                  <Text size="xs" tone="secondary">
                                    <TextLink onClick={addNote}>
                                      补一句
                                    </TextLink>
                                  </Text>
                                )}
                              {capabilities?.available &&
                                audio.id === turn.id && (
                                  <progress
                                    aria-label="语音播放进度"
                                    max={1}
                                    value={audio.progress}
                                    className="sr-only"
                                  />
                                )}
                              {capabilities?.available &&
                                audio.errors[turn.id] && (
                                  <Text role="alert" size="xs" tone="danger">
                                    {audio.errors[turn.id]}
                                  </Text>
                                )}
                            </>
                          )}
                          {capabilities?.video?.available &&
                            video.videos[turn.id]?.status === 'failed' && (
                              <Text role="alert" size="xs" tone="secondary">
                                真人版生成失败 ·{' '}
                                <TextLink onClick={() => video.retry(turn.id)}>
                                  重试生成视频
                                </TextLink>
                              </Text>
                            )}
                        </ChatMessage>
                      ),
                  }))}
                />
                {chat.busy && !chat.newest && (
                  <div className="py-3">
                    <TypingIndicator
                      text={chat.step ? STEP_TEXT[chat.step] : undefined}
                    />
                  </div>
                )}
              </div>
              {pace.reminder && (
                <Notice
                  actions={
                    <Button variant="secondary" size="sm" onClick={pace.goOn}>
                      继续聊
                    </Button>
                  }
                >
                  <p>{pace.reminder}</p>
                </Notice>
              )}
              {chat.error && (
                <Notice
                  tone="danger"
                  role="alert"
                  actions={
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => {
                        void refreshState();
                        chat.retry(lens?.id ?? null);
                      }}
                      disabled={chat.busy}
                    >
                      重试
                    </Button>
                  }
                >
                  <p>分身没能回复：{chat.error}</p>
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
        aria-label="消息输入"
        className="chat-composer chat-column-grid"
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
      >
        {chat.attachments.length > 0 && filesWait && (
          <div className="mx-auto mb-2 max-w-3xl">
            <Notice>
              {trying ? '试问' : '向赋能提问'}
              不带附件，已添加的 {chat.attachments.length}{' '}
              个附件留到发普通消息时一起发送。
            </Notice>
          </div>
        )}
        {chat.attachments.length > 0 && !filesWait && (
          <div
            className="mx-auto mb-2 flex max-w-3xl flex-wrap gap-2"
            role="list"
            aria-label="已添加附件"
          >
            {chat.attachments.map((file, index) => (
              <div
                key={`${file.name}-${file.size}-${index}`}
                className="max-w-full"
                role="listitem"
              >
                <Chip>
                  <Text
                    as="span"
                    size="inherit"
                    tone="primary"
                    truncate
                    className="max-w-56"
                  >
                    {file.name}
                  </Text>
                  <IconButton
                    shape="circle"
                    label={`移除附件 ${file.name}`}
                    disabled={chat.busy}
                    onClick={() => {
                      chat.setAttachments(
                        chat.attachments.filter((_, i) => i !== index),
                      );
                      setAttachmentError('');
                    }}
                  >
                    <X className="size-4" aria-hidden />
                  </IconButton>
                </Chip>
              </div>
            ))}
          </div>
        )}
        {attachmentError && (
          <Text
            role="alert"
            size="sm"
            tone="danger"
            className="mx-auto mb-2 max-w-3xl"
          >
            {attachmentError}
          </Text>
        )}
        {chat.attachments.length > 0 && !filesWait && (
          <Text size="xs" tone="tertiary" className="mx-auto mb-2 max-w-3xl">
            原文件仅在本次请求中处理，不进入长期资料；提取文字会发送给当前配置的聊天模型。后续追问需重新附加，回答和引用摘录会保存在聊天记录。
          </Text>
        )}
        <ChatSurface variant="composer">
          <FileInput
            ref={attachmentInput}
            label="选择附件"
            accept={CHAT_ATTACHMENT_ACCEPT}
            multiple
            disabled={
              chat.busy || chat.loading || chat.restoreFailed || filesWait
            }
            onFiles={addAttachments}
          />
          <ChatInput
            id="chat-input"
            aria-label="你说"
            maxRows={5}
            maxLength={4000}
            value={chat.draft}
            onChange={(event) => chat.setDraft(event.target.value)}
            onSend={send}
            placeholder={
              trying
                ? '问一句，看同事会得到什么…'
                : lens
                  ? `向${lens.owner_name}的赋能提问…`
                  : assistant
                    ? personaEdition
                      ? '问问我的分身，或说“记一下…”'
                      : '问问我的分身，或说“记一下…”“帮我问问…”'
                    : `和${name}聊点什么…`
            }
          />
          <Row gap={1} wrap>
            <Tooltip
              label={
                filesWait
                  ? '这类提问不带附件'
                  : 'TXT、PDF、Word、EPUB 等，最多 5 个，共 50 MiB'
              }
            >
              <IconButton
                shape="circle"
                label="添加附件（TXT、PDF、Word、EPUB 等，最多 5 个，共 50 MiB）"
                disabled={
                  chat.busy || chat.loading || chat.restoreFailed || filesWait
                }
                onClick={() => attachmentInput.current?.click()}
              >
                <Plus className="size-5" aria-hidden />
              </IconButton>
            </Tooltip>
            {target}
            {modeSwitch}
            {trial && (
              <Tooltip label="看同事问同一句会得到什么，不留记录">
                <Chip
                  pressed={trial.on}
                  onClick={() => trial.onChange(!trial.on)}
                >
                  试问
                </Chip>
              </Tooltip>
            )}
            {lenses.choices.length > MAX_LENS_CHIPS ? (
              // Many are published: one choice, not a chip for each.
              <Select
                aria-label="向赋能提问"
                value={lensId ?? ''}
                onChange={(event) => setLensId(event.target.value || null)}
              >
                <option value="">不用赋能</option>
                {lenses.choices.map((choice) => (
                  <option key={choice.id} value={choice.id}>
                    赋能 · {choice.name}
                  </option>
                ))}
              </Select>
            ) : (
              lenses.choices.map((choice) => (
                <Chip
                  key={choice.id}
                  pressed={choice.id === lensId}
                  onClick={() =>
                    setLensId(choice.id === lensId ? null : choice.id)
                  }
                >
                  赋能 · {choice.name}
                </Chip>
              ))
            )}
            <div className="flex-1" />
            <ChatAction
              type="submit"
              variant="send"
              aria-label="发送"
              loading={chat.busy}
              disabled={
                !chat.draft.trim() || chat.loading || chat.restoreFailed
              }
            >
              {!chat.busy && <ArrowUp className="size-5" aria-hidden />}
            </ChatAction>
          </Row>
        </ChatSurface>
        {seen && !assistant && (
          <Text
            size="xs"
            tone="tertiary"
            align="center"
            className="mx-auto mt-2 max-w-3xl"
          >
            本人看得到分身的回答
          </Text>
        )}
      </form>
    </div>
  );
}
