import { useCallback, useEffect, useRef } from 'react';
import { useLocation } from 'react-router';
import { ArrowUp, Paperclip, Play, X } from 'lucide-react';
import { MessageList } from '../components/effects/MessageList';
import {
  Chip,
  EmptyState,
  FileInput,
  IconButton,
  Notice,
  Text,
  TextLink,
  Textarea,
  Button,
  PlainButton,
  Spacer,
  TypingIndicator,
} from '../components/ui';
import { MessageText } from '../features/chat/MessageText';
import { ReplyBasis, ReplyDetails } from '../features/chat/ReplyDetails';
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
import { useDesktop } from '../lib/useMobile';
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
  const { pathname } = useLocation();
  const active = pathname === '/chat';
  const chat = useConversation(active);
  const desktop = useDesktop();
  const [historyOpen, setHistoryOpen] = useState(false);
  const { refreshHistory } = chat;
  useEffect(() => {
    if (active) void refreshHistory();
  }, [active, refreshHistory]);
  useEffect(() => {
    if (desktop) setHistoryOpen(false);
  }, [desktop]);
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
  const history = (
    <ConversationHistory
      open={active && historyOpen}
      onOpenChange={setHistoryOpen}
      chat={chat}
      onResume={stopPlayback}
      onNew={newConversation}
      name={name}
      inline={desktop}
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
      className="chat-page"
      data-empty={!chat.turns.length && !chat.loading}
    >
      <audio ref={audio.audioRef} preload="auto" className="hidden" />
      <ChatStage
        name={name}
        capabilities={capabilities}
        turn={currentTurn}
        videoState={currentTurn ? video.videos[currentTurn.id] : undefined}
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
        history={desktop ? history : undefined}
      />
      {!desktop && history}
      <div className="chat-thread">
        <div className="chat-scroll">
          <div className="chat-column-grid">
            <PersonaFade>
              <div className="chat-conversation flex flex-col space-y-4">
                {status?.memory_updating && (
                  <Text role="status" size="sm" tone="secondary">
                    记忆更新中：录音的说话人归属刚有变化，整理完成后就能回答。
                  </Text>
                )}
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
                    <EmptyState
                      title={`和${name}聊聊`}
                      body={
                        !canManage
                          ? '在下面输入一句话开始。'
                          : status?.counts.sources === 0
                            ? '先添加一些关于你的记忆，再来聊聊。'
                            : '在下面输入一句话开始，也可以先添加记忆。'
                      }
                    >
                      <div
                        className="starter-chips flex flex-wrap justify-center gap-3"
                        aria-label="聊天开场白"
                      >
                        {[
                          '你最近在忙什么？',
                          '你周末一般怎么过？',
                          '遇到难事你会怎么做？',
                        ].map((starter) => (
                          <Chip
                            key={starter}
                            onClick={() => {
                              chat.setDraft(starter);
                              document.getElementById('chat-input')?.focus();
                            }}
                          >
                            {starter}
                          </Chip>
                        ))}
                      </div>
                      {canManage && (
                        <TextLink href="#/profile?section=memories">
                          添加记忆
                        </TextLink>
                      )}
                    </EmptyState>
                  )}
                  <MessageList
                    label="对话记录"
                    className="space-y-4"
                    items={chat.turns.map((turn) => {
                      return {
                        id: turn.id,
                        text: turn.content,
                        content: (
                          <article
                            aria-label={
                              turn.role === 'user' ? '你说' : '分身回复'
                            }
                            data-pin={
                              turn.role === 'user' ? turn.id : undefined
                            }
                            className={
                              turn.role === 'user'
                                ? 'user-bubble ml-auto w-fit max-w-17/20 px-4 py-3'
                                : 'mr-auto w-fit max-w-9/10 min-w-0 text-primary'
                            }
                          >
                            <div
                              className={`min-w-0 ${turn.role === 'twin' ? 'twin-bubble' : ''}`}
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
                                    <ReplyBasis reply={turn.reply} />
                                  )}
                                  <div
                                    role="group"
                                    aria-label="回复媒体"
                                    className="ml-auto flex items-center"
                                  >
                                    {capabilities?.available && (
                                      <PlainButton
                                        shape="circle"
                                        className="reply-play min-h-11 min-w-11"
                                        aria-label={
                                          (audio.id === turn.id &&
                                            audio.playing) ||
                                          (videoId === turn.id && videoPlaying)
                                            ? '正在说这句，点击暂停'
                                            : `让${name}说这句`
                                        }
                                        aria-busy={
                                          audio.id === turn.id && audio.loading
                                        }
                                        data-speaking={
                                          (audio.id === turn.id &&
                                            audio.playing) ||
                                          (videoId === turn.id && videoPlaying)
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
                                    <Text role="alert" size="xs" tone="danger">
                                      {audio.errors[turn.id]}
                                    </Text>
                                  )}
                                {turn.role === 'twin' && (
                                  <ReplyDetails reply={turn.reply} />
                                )}
                              </>
                            )}
                            {capabilities?.video?.available &&
                              video.videos[turn.id]?.status === 'failed' && (
                                <Text role="alert" size="xs" tone="secondary">
                                  真人版生成失败 ·{' '}
                                  <TextLink
                                    onClick={() => video.retry(turn.id)}
                                  >
                                    重试生成视频
                                  </TextLink>
                                </Text>
                              )}
                          </article>
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
          className="chat-composer chat-column-grid fixed inset-x-0 z-20 border-t border-border bg-canvas/95 px-3 pt-2 backdrop-blur-xl"
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
            <Text size="xs" tone="tertiary" className="mx-auto mb-2 max-w-3xl">
              原文件仅在本次请求中处理，不进入长期资料；提取文字会发送给当前配置的聊天模型。后续追问需重新附加，回答和引用摘录会保存在聊天记录。
            </Text>
          )}
          <div className="composer-field mx-auto flex max-w-3xl items-end gap-1 bg-surface py-1 pr-1 pl-2">
            <FileInput
              ref={attachmentInput}
              label="选择附件"
              accept={CHAT_ATTACHMENT_ACCEPT}
              multiple
              disabled={chat.busy || chat.loading || chat.restoreFailed}
              onFiles={addAttachments}
            />
            <IconButton
              shape="circle"
              size="lg"
              label="添加附件"
              title="添加文件（PDF 仅支持文字层，不支持扫描件 OCR）"
              disabled={chat.busy || chat.loading || chat.restoreFailed}
              onClick={() => attachmentInput.current?.click()}
            >
              <Paperclip className="size-5" aria-hidden />
            </IconButton>
            <Textarea
              id="chat-input"
              aria-label="你说"
              rows={1}
              maxRows={5}
              maxLength={4000}
              value={chat.draft}
              onChange={(event) => chat.setDraft(event.target.value)}
              onSend={send}
              className="min-h-11 border-0 bg-transparent px-2 py-2.5 shadow-none focus-visible:outline-none"
              placeholder={`和${name}聊点什么…`}
            />
            <IconButton
              type="submit"
              variant="primary"
              shape="circle"
              size="lg"
              label="发送"
              className="send-button"
              loading={chat.busy}
              disabled={
                !chat.draft.trim() || chat.loading || chat.restoreFailed
              }
            >
              {!chat.busy && <ArrowUp className="size-5" aria-hidden />}
            </IconButton>
          </div>
          <Text size="xs" tone="tertiary" className="mx-auto mt-1 max-w-3xl">
            支持 TXT / MD / PDF / Word / EPUB / HTML / CSV / JSON / SRT /
            VTT；最多 5 个，合计不超过 50 MiB。
          </Text>
        </form>
      </div>
    </div>
  );
}
