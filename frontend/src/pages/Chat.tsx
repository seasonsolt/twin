import { useCallback, useEffect, useRef, type CSSProperties } from 'react';
import { useLocation } from 'react-router';
import { ArrowUp, Paperclip, Play, X } from 'lucide-react';
import { MessageList } from '../components/effects/MessageList';
import { ThinkingLabel } from '../components/effects/ThinkingLabel';
import { Badge, Button, EmptyState, Textarea } from '../components/ui';
import { Citations } from '../features/chat/Citations';
import { MessageText } from '../features/chat/MessageText';
import { ReplyDetails } from '../features/chat/ReplyDetails';
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
  const { end, composer, composerHeight } = useComposerLayout(active);
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
      className="chat-page"
      data-empty={!chat.turns.length && !chat.loading}
      style={{ '--composer-height': `${composerHeight}px` } as CSSProperties}
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
                  <p role="status" className="text-sm text-secondary">
                    记忆更新中：录音的说话人归属刚有变化，整理完成后就能回答。
                  </p>
                )}
                {stale && canManage && (
                  <p role="status" className="text-xs text-secondary">
                    新添加的记忆正在处理中，聊天暂时使用已记住的内容。{' '}
                    <a
                      className="inline-flex min-h-11 items-center text-accent underline"
                      href="#/profile?section=memories"
                    >
                      查看记忆
                    </a>
                  </p>
                )}
                {stateError && (
                  <div role="alert" className="text-sm text-danger">
                    无法检查档案状态：{stateError}{' '}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => void refreshState()}
                    >
                      重新检查
                    </Button>
                  </div>
                )}
                <div
                  aria-live="polite"
                  aria-relevant="additions text"
                  data-testid="chat-messages"
                >
                  {chat.loading && (
                    <p role="status" className="text-sm text-secondary">
                      正在加载对话…
                    </p>
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
                          <button
                            key={starter}
                            type="button"
                            className="starter-chip min-h-11 rounded-full border border-primary px-4 text-primary"
                            onClick={() => {
                              chat.setDraft(starter);
                              document.getElementById('chat-input')?.focus();
                            }}
                          >
                            {starter}
                          </button>
                        ))}
                      </div>
                      {canManage && (
                        <a
                          className="inline-flex min-h-11 items-center text-accent underline"
                          href="#/profile?section=memories"
                        >
                          添加记忆
                        </a>
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
                                ? 'user-bubble ml-auto w-fit max-w-[85%] px-4 py-3'
                                : 'mr-auto w-fit max-w-[90%] min-w-0 text-primary'
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
                            {turn.role === 'twin' && turn.reply && (
                              <ReplyDetails reply={turn.reply} />
                            )}
                            {turn.reply && (
                              <>
                                <div
                                  role="group"
                                  aria-label="回复媒体"
                                  className="reply-actions mt-1 flex min-w-0 flex-wrap items-center justify-end gap-x-2"
                                >
                                  {capabilities?.available && (
                                    <button
                                      type="button"
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
                                    </button>
                                  )}
                                  {turn.reply.mode === 'inferred' && (
                                    <Badge>推测 · 非本人表达</Badge>
                                  )}
                                  <Citations cited={turn.reply.cited} />
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
                                    <p
                                      role="alert"
                                      className="text-xs text-danger"
                                    >
                                      {audio.errors[turn.id]}
                                    </p>
                                  )}
                              </>
                            )}
                            {capabilities?.video?.available &&
                              video.videos[turn.id]?.status === 'failed' && (
                                <p
                                  role="alert"
                                  className="text-xs text-secondary"
                                >
                                  真人版生成失败 ·{' '}
                                  <button
                                    type="button"
                                    className="min-h-11 underline"
                                    onClick={() => video.retry(turn.id)}
                                  >
                                    重试生成视频
                                  </button>
                                </p>
                              )}
                          </article>
                        ),
                      };
                    })}
                  />
                  {chat.busy && !chat.newest && (
                    <div className="py-3">
                      <ThinkingLabel />
                    </div>
                  )}
                </div>
                {chat.error && (
                  <div
                    role="alert"
                    className="rounded-md border border-danger/20 bg-danger/5 px-3 py-2 text-danger"
                  >
                    <p>分身没能回复：{chat.error}</p>
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
          aria-label="消息输入"
          className="chat-composer chat-column-grid fixed inset-x-0 z-20 border-t border-border bg-canvas/95 px-3 pt-2 backdrop-blur-xl md:left-[var(--sidebar-width,0px)]"
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
                  className="flex min-h-10 max-w-full items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-sm"
                  role="listitem"
                >
                  <span className="max-w-56 truncate">{file.name}</span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="size-8 min-h-8 min-w-8 rounded-full p-0"
                    aria-label={`移除附件 ${file.name}`}
                    disabled={chat.busy}
                    onClick={() => {
                      chat.setAttachments(
                        chat.attachments.filter((_, i) => i !== index),
                      );
                      setAttachmentError('');
                    }}
                  >
                    <X className="size-4" aria-hidden />
                  </Button>
                </div>
              ))}
            </div>
          )}
          {attachmentError && (
            <p
              role="alert"
              className="mx-auto mb-2 max-w-3xl text-sm text-danger"
            >
              {attachmentError}
            </p>
          )}
          {chat.attachments.length > 0 && (
            <p className="mx-auto mb-2 max-w-3xl text-xs text-tertiary">
              原文件仅在本次请求中处理，不进入长期资料；提取文字会发送给当前配置的聊天模型。后续追问需重新附加，回答和引用摘录会保存在聊天记录。
            </p>
          )}
          <div className="composer-field mx-auto flex max-w-3xl items-end gap-1 bg-surface py-1 pr-1 pl-2">
            <input
              ref={attachmentInput}
              type="file"
              aria-label="选择附件"
              accept={CHAT_ATTACHMENT_ACCEPT}
              multiple
              className="sr-only"
              disabled={chat.busy || chat.loading || chat.restoreFailed}
              onChange={(event) => {
                addAttachments(Array.from(event.currentTarget.files ?? []));
                event.currentTarget.value = '';
              }}
            />
            <Button
              type="button"
              variant="ghost"
              className="size-11 min-h-11 min-w-11 rounded-full p-0"
              aria-label="添加附件"
              title="添加文件（PDF 仅支持文字层，不支持扫描件 OCR）"
              disabled={chat.busy || chat.loading || chat.restoreFailed}
              onClick={() => attachmentInput.current?.click()}
            >
              <Paperclip className="size-5" aria-hidden />
            </Button>
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
            <Button
              type="submit"
              aria-label="发送"
              className="send-button size-11 min-h-11 rounded-full p-0"
              loading={chat.busy}
              disabled={
                !chat.draft.trim() || chat.loading || chat.restoreFailed
              }
            >
              {!chat.busy && <ArrowUp className="size-5" aria-hidden />}
            </Button>
          </div>
          <p className="mx-auto mt-1 max-w-3xl text-xs text-tertiary">
            支持 TXT / MD / PDF / Word / EPUB / HTML / CSV / JSON / SRT /
            VTT；最多 5 个，合计不超过 50 MiB。
          </p>
        </form>
      </div>
    </div>
  );
}
