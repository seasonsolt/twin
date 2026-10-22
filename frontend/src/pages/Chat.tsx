import { useCallback, useEffect, useRef } from 'react';
import { useLocation } from 'react-router';
import {
  ArrowUp,
  Plus,
  Play,
  X,
  PanelLeft,
  SquarePen,
  UserRound,
  ChevronDown,
  Copy,
  Mic,
} from 'lucide-react';
import { MessageList } from '../components/effects/MessageList';
import {
  Chip,
  ChatSurface,
  ChatMessage,
  ChatAction,
  ChatInput,
  ChatIdentity,
  Heading,
  Row,
  Tooltip,
  toast,
  FileInput,
  IconButton,
  Notice,
  Text,
  TextLink,
  Button,
  PlainButton,
  ResizeHandle,
  Spacer,
  TypingIndicator,
} from '../components/ui';
import { MessageText } from '../features/chat/MessageText';
import {
  ReplyBasis,
  ReplyDetails,
  ReplyTime,
} from '../features/chat/ReplyDetails';
import { useConversation } from '../features/chat/useConversation';
import { ChatStage } from '../features/chat/ChatStage';
import {
  useComposerLayout,
  usePinnedMessage,
} from '../features/chat/useComposerLayout';
import { ConversationHistory } from '../features/chat/ConversationHistory';
import { videoUrl } from '../features/chat/useReplyVideos';
import type { Turn } from '../features/chat/types';
import { useReplyAudio } from '../features/chat/useReplyAudio';
import { useReplyVideos } from '../features/chat/useReplyVideos';
import type { Capabilities } from '../features/avatar/types';
import { api } from '../lib/api';
import {
  usePersonaId,
  usePersonaState as useState,
} from '../lib/usePersonaState';
import { loadEssential, peekEssential } from '../lib/personaPrefetch';
import { useStatus } from '../stores/status';
import { usePersonas } from '../stores/personas';
import { useMediaQuery, useMobile } from '../lib/useMobile';
import { SHEET_WIDTH, useChatLayout } from '../stores/chatLayout';
import {
  PersonaSwitcher,
  PersonaPortrait,
} from '../components/layout/PersonaSwitcher';
import { useIdentity } from '../features/identity/useIdentity';
import { SetupCard } from '../features/setup/SetupCard';
import { MemoryUpdating } from '../features/memories/BuildProgress';
import { PersonaFade } from '../components/motion/PersonaFade';

const CHAT_ATTACHMENT_ACCEPT =
  '.txt,.md,.pdf,.docx,.epub,.html,.htm,.csv,.json,.srt,.vtt';
const CHAT_ATTACHMENT_SUFFIXES = new Set(
  'txt md pdf docx epub html htm csv json srt vtt'.split(' '),
);
const MAX_CHAT_ATTACHMENT_COUNT = 5;
const MAX_CHAT_ATTACHMENT_BYTES = 50 * 1024 * 1024;

export function Chat() {
  const personaId = usePersonaId();
  const { pathname, state, key } = useLocation();
  const active = pathname === '/chat';
  const chat = useConversation(active);
  // A question picked elsewhere (such as trying out a twin before saying it is all right) waits in the composer.
  const ask = (state as { ask?: unknown } | null)?.ask;
  const { setDraft } = chat;
  useEffect(() => {
    if (typeof ask === 'string') setDraft(ask);
  }, [ask, key, setDraft]);
  const mobile = useMobile();
  const wide = useMediaQuery('(min-width: 1280px)');
  const layout = useChatLayout();
  const sheetOpen = !mobile && (layout.sheet ?? wide);
  const stageOpen = layout.stage ?? false;
  const identity = useIdentity(active);
  const setStageOpen = (value: boolean) => layout.setChoice('stage', value);
  const [historyOpen, setHistoryOpen] = useState(false);
  const { refreshHistory } = chat;
  useEffect(() => {
    if (active) void refreshHistory();
  }, [active, refreshHistory]);
  useEffect(() => {
    if (!mobile) setHistoryOpen(false);
  }, [mobile]);
  const historyTrigger = useRef<HTMLElement | null>(null);
  const attachmentInput = useRef<HTMLInputElement>(null);
  const [attachmentError, setAttachmentError] = useState('');
  const openHistory = () => {
    historyTrigger.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    setHistoryOpen(true);
    void chat.refreshHistory();
  };
  const status = useStatus((state) => state.data);
  const persona = usePersonas((state) =>
    state.items.find((item) => item.id === state.id),
  );
  const name = status?.target_name || persona?.name || '本人';
  const canManage = persona?.can_manage ?? true;
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
  const [capabilities, setCapabilities] = useState<Capabilities | null>(
    () =>
      peekEssential<Capabilities>('/api/media/capabilities', personaId) ?? null,
  );
  const [assetVersion, setAssetVersion] = useState(0);
  useEffect(() => {
    const changed = () => {
      setCapabilities(null);
      setVideoId('');
      setVideoPlaying(false);
      setAssetVersion((value) => value + 1);
    };
    window.addEventListener('twin-assets-changed', changed);
    return () => window.removeEventListener('twin-assets-changed', changed);
  }, []);
  const audio = useReplyAudio(active);
  const setChoice = layout.setChoice;
  useEffect(() => {
    if (audio.speaking) setChoice('stage', true);
  }, [audio.speaking, setChoice]);
  const autoSpoken = useRef<string | null>(null);
  useEffect(() => {
    const turn = chat.turns.find((entry) => entry.id === chat.newest);
    if (
      !active ||
      !capabilities?.available ||
      !turn?.reply ||
      !turn.reply.reply.trim() ||
      autoSpoken.current === turn.id
    )
      return;
    autoSpoken.current = turn.id;
    audio.toggle(turn.id, turn.reply, name);
  }, [active, capabilities, chat.turns, chat.newest, audio, name]);
  const [videoId, setVideoId] = useState('');
  const [videoPlaying, setVideoPlaying] = useState(false);
  const video = useReplyVideos(
    active && !!capabilities?.video?.available,
    chat.turns,
    name,
    capabilities?.video?.asset_key ?? '',
  );
  useEffect(() => {
    if (!active) return;
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
  }, [active, assetVersion, personaId]);
  const stateRequest = useRef<AbortController | null>(null);
  const alive = useRef(false);
  const { page, end, composer, composerHeight } = useComposerLayout(active);
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
  }, [personaId]);
  useEffect(() => {
    alive.current = active;
    if (active) void refreshState();
    return () => {
      alive.current = false;
      stateRequest.current?.abort();
    };
  }, [active, refreshState]);
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
  const currentTurn = chat.turns.find(
    (turn) => turn.id === (videoId || audio.id || chat.newest),
  );
  const toggleReply = (turn?: Turn, preferVideo = false) => {
    if (!turn?.reply) return;
    setStageOpen(true);
    if (videoId === turn.id && videoPlaying) {
      setVideoPlaying(false);
      return;
    }
    const state = video.videos[turn.id];
    const ready = state?.status === 'done' && videoUrl(state.result);
    if (audio.id === turn.id && audio.playing && !(preferVideo && ready)) {
      audio.toggle(turn.id, turn.reply, name);
      return;
    }
    if (ready) {
      audio.stop();
      setVideoId(turn.id);
      setVideoPlaying(true);
    } else {
      setVideoId('');
      setVideoPlaying(false);
      audio.toggle(turn.id, turn.reply, name);
    }
  };
  const stopPlayback = () => {
    audio.stop();
    setVideoId('');
    setVideoPlaying(false);
  };
  const newConversation = () => {
    chat.clear();
    setPinned(null);
    setAttachmentError('');
    stopPlayback();
  };
  const presence =
    audio.speaking || videoPlaying
      ? '正在说话'
      : chat.busy && !chat.newest
        ? '正在思考'
        : ''; // Source counts also include documents; no recording-only count is available here.
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
  const lastAnswer = [...chat.turns]
    .reverse()
    .find((turn) => turn.role === 'twin')?.id;
  const conversationTitle =
    chat.history.find((entry) => entry.id === chat.conversationId)?.title ??
    '新对话';
  const history = (
    <ConversationHistory
      open={active && historyOpen}
      onOpenChange={(open) =>
        mobile ? setHistoryOpen(open) : layout.setChoice('sheet', open)
      }
      chat={chat}
      onResume={stopPlayback}
      onNew={newConversation}
      name={name}
      inline={!mobile}
      heading={switcher}
      presence={presence}
      returnFocus={historyTrigger}
    />
  );
  const send = () => {
    if (chat.busy || chat.loading || chat.restoreFailed || !chat.draft.trim())
      return;
    audio.stop();
    audio.unlock();
    setAttachmentError('');
    void refreshState();
    pinNext.current = true;
    void chat.send();
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
    <div
      ref={page}
      className="chat-page chat-redesign"
      data-sheet={sheetOpen}
      data-empty={!chat.turns.length && !chat.loading}
    >
      <audio ref={audio.audioRef} preload="auto" className="hidden" />
      {sheetOpen && (
        <ChatSurface variant="sheet" width={layout.sheetWidth}>
          {history}
          <ResizeHandle
            label="调整对话列表宽度"
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
        <header className="chat-topbar" aria-label={`${name}的聊天`}>
          {mobile ? (
            <>
              <IconButton label="对话列表" onClick={openHistory}>
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
                {presence && (
                  <Text size="xs" tone="tertiary">
                    {presence}
                  </Text>
                )}
              </div>
              <ChatAction
                aria-label={stageOpen ? '收起形象' : '打开形象'}
                selected={stageOpen}
                aria-pressed={stageOpen}
                onClick={() => setStageOpen(!stageOpen)}
              >
                <UserRound size={20} aria-hidden />
              </ChatAction>
              <IconButton label="新对话" onClick={newConversation}>
                <SquarePen size={20} aria-hidden />
              </IconButton>
            </>
          ) : (
            <>
              {!sheetOpen && (
                <>
                  <IconButton
                    label="展开对话列表"
                    onClick={() => layout.setChoice('sheet', true)}
                  >
                    <PanelLeft size={18} aria-hidden />
                  </IconButton>
                  {/* With the list folded away, the twin's portrait is where it is switched. */}
                  <PersonaSwitcher
                    label={`切换分身（当前：${name}）`}
                    className="flex shrink-0 items-center"
                    trigger={
                      <ChatIdentity size="mobile">
                        <PersonaPortrait persona={persona} />
                      </ChatIdentity>
                    }
                  />
                </>
              )}
              <Heading
                level={1}
                weight="medium"
                size="item"
                truncate
                className="min-w-0 flex-1"
              >
                {!sheetOpen ? `${name} / ` : ''}
                {conversationTitle}
              </Heading>
              <ChatAction
                disabled={
                  !capabilities?.available ||
                  !chat.turns.some((turn) => turn.reply?.reply.trim())
                }
                onClick={() => {
                  setStageOpen(true);
                  toggleReply(
                    [...chat.turns]
                      .reverse()
                      .find((turn) => turn.reply?.reply.trim()),
                  );
                }}
              >
                <Mic size={16} aria-hidden />
                语音
              </ChatAction>
              <ChatAction
                selected={stageOpen}
                aria-pressed={stageOpen}
                onClick={() => setStageOpen(!stageOpen)}
              >
                形象
              </ChatAction>
            </>
          )}
        </header>
        <div className="chat-body flex min-h-0 flex-1">
          <div className="chat-thread">
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
                              <ChatIdentity size="empty">
                                <PersonaPortrait persona={persona} />
                              </ChatIdentity>
                              <Heading
                                level={2}
                                size="display"
                                weight="bold"
                                align="center"
                              >
                                和{name}聊聊
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
                        items={chat.turns.map((turn) => {
                          return {
                            id: turn.id,
                            text: turn.content,
                            content: (
                              <ChatMessage
                                speaker={turn.role}
                                last={turn.id === lastAnswer}
                                aria-label={
                                  turn.role === 'user' ? '你说' : '分身回复'
                                }
                                data-pin={
                                  turn.role === 'user' ? turn.id : undefined
                                }
                              >
                                <div
                                  className={
                                    turn.role === 'twin'
                                      ? 'twin-bubble min-w-0'
                                      : 'min-w-0'
                                  }
                                  data-speaking={
                                    (audio.id === turn.id && audio.playing) ||
                                    (videoId === turn.id && videoPlaying)
                                  }
                                >
                                  <MessageText
                                    text={turn.content}
                                    plain={turn.role === 'user'}
                                    streaming={
                                      turn.role === 'twin' &&
                                      !turn.reply &&
                                      chat.busy
                                    }
                                  />
                                </div>
                                {turn.reply && (
                                  <>
                                    <div className="reply-actions mt-1 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                                      {turn.role === 'twin' && (
                                        <>
                                          <ReplyBasis reply={turn.reply} />
                                          <ReplyTime reply={turn.reply} />
                                        </>
                                      )}
                                      <div
                                        role="group"
                                        aria-label="回复媒体"
                                        className="answer-controls ml-auto flex items-center"
                                      >
                                        {capabilities?.available && (
                                          <PlainButton
                                            shape="circle"
                                            className="reply-play min-h-11 min-w-11"
                                            aria-label={
                                              (audio.id === turn.id &&
                                                audio.playing) ||
                                              (videoId === turn.id &&
                                                videoPlaying)
                                                ? '正在说这句，点击暂停'
                                                : `让${name}说这句`
                                            }
                                            aria-busy={
                                              audio.id === turn.id &&
                                              audio.loading
                                            }
                                            data-speaking={
                                              (audio.id === turn.id &&
                                                audio.playing) ||
                                              (videoId === turn.id &&
                                                videoPlaying)
                                            }
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
                                              {(audio.id === turn.id &&
                                                audio.playing) ||
                                              (videoId === turn.id &&
                                                videoPlaying) ? (
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
                                        {turn.role === 'twin' && (
                                          <ReplyDetails
                                            reply={turn.reply}
                                            compact
                                          />
                                        )}
                                      </div>
                                    </div>
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
                                        <Text
                                          role="alert"
                                          size="xs"
                                          tone="danger"
                                        >
                                          {audio.errors[turn.id]}
                                        </Text>
                                      )}
                                  </>
                                )}
                                {capabilities?.video?.available &&
                                  video.videos[turn.id]?.status ===
                                    'failed' && (
                                    <Text
                                      role="alert"
                                      size="xs"
                                      tone="secondary"
                                    >
                                      真人版生成失败 ·{' '}
                                      <TextLink
                                        onClick={() => video.retry(turn.id)}
                                      >
                                        重试生成视频
                                      </TextLink>
                                    </Text>
                                  )}
                              </ChatMessage>
                            ),
                          };
                        })}
                      />
                      {chat.busy && !chat.newest && (
                        <div className="py-3">
                          <TypingIndicator />
                        </div>
                      )}
                    </div>
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
                              chat.retry();
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
              {chat.attachments.length > 0 && (
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
              {chat.attachments.length > 0 && (
                <Text
                  size="xs"
                  tone="tertiary"
                  className="mx-auto mb-2 max-w-3xl"
                >
                  原文件仅在本次请求中处理，不进入长期资料；提取文字会发送给当前配置的聊天模型。后续追问需重新附加，回答和引用摘录会保存在聊天记录。
                </Text>
              )}
              <ChatSurface variant="composer">
                <FileInput
                  ref={attachmentInput}
                  label="选择附件"
                  accept={CHAT_ATTACHMENT_ACCEPT}
                  multiple
                  disabled={chat.busy || chat.loading || chat.restoreFailed}
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
                  placeholder={`和${name}聊点什么…`}
                />
                <Row gap={1}>
                  <Tooltip label="TXT、PDF、Word、EPUB 等，最多 5 个，共 50 MiB">
                    <IconButton
                      shape="circle"
                      label="添加附件（TXT、PDF、Word、EPUB 等，最多 5 个，共 50 MiB）"
                      disabled={chat.busy || chat.loading || chat.restoreFailed}
                      onClick={() => attachmentInput.current?.click()}
                    >
                      <Plus className="size-5" aria-hidden />
                    </IconButton>
                  </Tooltip>
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
            </form>
          </div>
          {stageOpen && (
            <ChatSurface
              variant="stage"
              role="complementary"
              aria-label={`${name}的形象`}
            >
              <IconButton
                label="关闭形象"
                className="stage-close"
                onClick={() => setStageOpen(false)}
              >
                <X size={18} aria-hidden />
              </IconButton>
              <ChatStage
                name={name}
                capabilities={capabilities}
                turn={currentTurn}
                videoState={
                  currentTurn ? video.videos[currentTurn.id] : undefined
                }
                videoPlaying={active && videoPlaying}
                voiceCaption={audio.caption}
                level={audio.level}
                speaking={audio.speaking}
                thinking={chat.busy && !chat.newest}
                onToggle={() =>
                  toggleReply(
                    currentTurn ??
                      [...chat.turns]
                        .reverse()
                        .find((turn) => turn.reply?.reply.trim()),
                    true,
                  )
                }
                onVideoPlaying={setVideoPlaying}
                onVideoError={() => {
                  if (!videoId) return;
                  video.invalidate(videoId);
                  setVideoId('');
                  setVideoPlaying(false);
                  if (currentTurn?.reply)
                    audio.toggle(currentTurn.id, currentTurn.reply, name);
                }}
                onClear={newConversation}
                onHistory={openHistory}
                panel
              />
            </ChatSurface>
          )}
        </div>
      </ChatSurface>
    </div>
  );
}
