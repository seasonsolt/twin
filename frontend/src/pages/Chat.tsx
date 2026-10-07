import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
} from 'react';
import { useLocation } from 'react-router';
import { ArrowUp, History, Play } from 'lucide-react';
import { MessageList } from '../components/effects/MessageList';
import { ThinkingLabel } from '../components/effects/ThinkingLabel';
import { Button, EmptyState, Textarea } from '../components/ui';
import { Citations } from '../features/chat/Citations';
import { MessageText } from '../features/chat/MessageText';
import { useConversation } from '../features/chat/useConversation';
import { ChatStage } from '../features/chat/ChatStage';
import { ConversationHistory } from '../features/chat/ConversationHistory';
import { videoUrl } from '../features/chat/useReplyVideos';
import type { Turn } from '../features/chat/types';
import { useReplyAudio } from '../features/chat/useReplyAudio';
import { useReplyVideos } from '../features/chat/useReplyVideos';
import type { Capabilities } from '../features/avatar/types';
import { api } from '../lib/api';
import { useStatus } from '../stores/status';
import { usePersonas } from '../stores/personas';

export function Chat() {
  const { pathname } = useLocation();
  const active = pathname === '/chat';
  const chat = useConversation(active);
  const [historyOpen, setHistoryOpen] = useState(false);
  const openHistory = () => {
    setHistoryOpen(true);
    void chat.refreshHistory();
  };
  const status = useStatus((state) => state.data);
  const persona = usePersonas((state) =>
    state.items.find((item) => item.id === state.id),
  );
  const name = status?.target_name || persona?.name || '本人';
  const [stale, setStale] = useState(false);
  const [stateError, setStateError] = useState('');
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
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
      turn.reply.abstain ||
      turn.reply.mode === 'abstain' ||
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
    void api<Capabilities>('/api/media/capabilities', {
      signal: controller.signal,
    })
      .then((data) => {
        if (!controller.signal.aborted) setCapabilities(data);
      })
      .catch(() => {});
    return () => controller.abort();
  }, [active, assetVersion]);
  const stateRequest = useRef<AbortController | null>(null);
  const alive = useRef(false);
  const end = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLFormElement>(null);
  const [composerHeight, setComposerHeight] = useState(76);
  const refreshState = useCallback(async () => {
    stateRequest.current?.abort();
    const controller = new AbortController();
    stateRequest.current = controller;
    try {
      const memory = await api<{ stale: boolean }>('/api/persona/state', {
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
  }, []);
  useEffect(() => {
    alive.current = active;
    if (active) void refreshState();
    return () => {
      alive.current = false;
      stateRequest.current?.abort();
    };
  }, [active, refreshState]);
  useLayoutEffect(() => {
    const form = composer.current;
    if (!form) return;
    const resize = () =>
      setComposerHeight(form.getBoundingClientRect().height || 76);
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(form);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!active) return;
    const viewport = window.visualViewport;
    const root = document.documentElement;
    let frame = 0;
    const update = () => {
      const inset = viewport
        ? Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop)
        : 0;
      const mobile = window.matchMedia('(max-width: 767px)').matches;
      const focused = document.activeElement?.matches(
        'input, textarea, select',
      );
      const keyboard = mobile && !!focused && inset > 120;
      root.dataset.keyboard = String(keyboard);
      root.style.setProperty(
        '--keyboard-inset',
        keyboard ? `${inset}px` : '0px',
      );
      cancelAnimationFrame(frame);
      if (focused)
        frame = requestAnimationFrame(() =>
          end.current?.scrollIntoView?.({ block: 'end' }),
        );
    };
    update();
    viewport?.addEventListener('resize', update);
    viewport?.addEventListener('scroll', update);
    window.addEventListener('resize', update);
    document.addEventListener('focusin', update);
    document.addEventListener('focusout', update);
    return () => {
      cancelAnimationFrame(frame);
      viewport?.removeEventListener('resize', update);
      viewport?.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
      document.removeEventListener('focusin', update);
      document.removeEventListener('focusout', update);
      delete root.dataset.keyboard;
      root.style.removeProperty('--keyboard-inset');
    };
  }, [active]);
  useEffect(() => {
    if (active) end.current?.scrollIntoView?.({ block: 'end' });
  }, [active, chat.turns, chat.busy, composerHeight]);
  const currentTurn = chat.turns.find(
    (turn) => turn.id === (videoId || audio.id),
  );
  const toggleReply = (turn?: Turn) => {
    if (!turn?.reply) return;
    if (videoId === turn.id && videoPlaying) {
      setVideoPlaying(false);
      return;
    }
    if (audio.id === turn.id && audio.playing) {
      audio.toggle(turn.id, turn.reply, name);
      return;
    }
    const state = video.videos[turn.id];
    if (state?.status === 'done' && videoUrl(state.result)) {
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
  const send = () => {
    if (chat.busy || chat.loading || chat.restoreFailed || !chat.draft.trim())
      return;
    void refreshState();
    void chat.send();
  };
  return (
    <div
      className="chat-page"
      style={{ '--composer-height': `${composerHeight}px` } as CSSProperties}
    >
      <audio ref={audio.audioRef} preload="auto" className="hidden" />
      <ChatStage
        name={name}
        capabilities={capabilities}
        turn={currentTurn}
        videoState={videoId ? video.videos[videoId] : undefined}
        videoPlaying={active && videoPlaying}
        voiceCaption={audio.caption}
        level={audio.level}
        speaking={audio.speaking}
        onToggle={() =>
          toggleReply(
            currentTurn ??
              [...chat.turns]
                .reverse()
                .find(
                  (turn) =>
                    turn.reply &&
                    !turn.reply.abstain &&
                    turn.reply.mode !== 'abstain',
                ),
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
        onClear={() => {
          chat.clear();
          stopPlayback();
        }}
        onHistory={openHistory}
      />
      <ConversationHistory
        open={active && historyOpen}
        onOpenChange={setHistoryOpen}
        chat={chat}
        onResume={stopPlayback}
      />
      <div className="chat-thread">
        <header className="chat-history-header">
          <button type="button" onClick={openHistory}>
            <History size={18} aria-hidden /> 对话记录
          </button>
        </header>
        <div className="chat-scroll">
          <div className="chat-conversation flex flex-col justify-end space-y-4">
            {stale && (
              <p role="status" className="text-xs text-secondary">
                新添加的记忆正在处理中，聊天暂时使用已记住的内容。{' '}
                <a
                  className="inline-flex min-h-11 items-center text-accent underline"
                  href="#/memories"
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
                    status?.counts.sources === 0
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
                  <a
                    className="inline-flex min-h-11 items-center text-accent underline"
                    href="#/memories"
                  >
                    添加记忆
                  </a>
                </EmptyState>
              )}
              <MessageList
                label="对话记录"
                className="space-y-4"
                items={chat.turns.map((turn) => {
                  const abstain =
                    turn.role === 'twin' &&
                    (turn.reply?.abstain || turn.reply?.mode === 'abstain');
                  return {
                    id: turn.id,
                    text: turn.content,
                    content: (
                      <article
                        aria-label={turn.role === 'user' ? '你说' : '分身回复'}
                        className={
                          turn.role === 'user'
                            ? 'user-bubble ml-auto w-fit max-w-[85%] px-4 py-3'
                            : abstain
                              ? 'mr-auto text-sm text-secondary'
                              : 'mr-auto w-fit max-w-[90%] min-w-0 text-primary'
                        }
                      >
                        {abstain ? (
                          <MessageText text={turn.content} />
                        ) : (
                          <>
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
                                <div
                                  role="group"
                                  aria-label="回复媒体"
                                  className="reply-actions mt-1 flex min-w-0 flex-wrap items-center justify-end gap-x-2"
                                >
                                  <button
                                    type="button"
                                    className="reply-play min-h-11 min-w-11"
                                    aria-label={
                                      (audio.id === turn.id && audio.playing) ||
                                      (videoId === turn.id && videoPlaying)
                                        ? '正在说这句，点击暂停'
                                        : `让${name}说这句`
                                    }
                                    aria-busy={
                                      audio.id === turn.id && audio.loading
                                    }
                                    data-speaking={
                                      (audio.id === turn.id && audio.playing) ||
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
                                      (videoId === turn.id && videoPlaying) ? (
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
                                  <Citations cited={turn.reply.cited} />
                                </div>
                                {audio.id === turn.id && (
                                  <progress
                                    aria-label="语音播放进度"
                                    max={1}
                                    value={audio.progress}
                                    className="sr-only"
                                  />
                                )}
                                {audio.errors[turn.id] && (
                                  <p
                                    role="alert"
                                    className="text-xs text-danger"
                                  >
                                    {audio.errors[turn.id]}
                                  </p>
                                )}
                              </>
                            )}
                            {video.videos[turn.id]?.status === 'failed' && (
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
                          </>
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
          </div>
        </div>
        <form
          ref={composer}
          aria-label="消息输入"
          className="chat-composer fixed inset-x-0 z-20 border-t border-border bg-canvas/95 px-3 pt-2 backdrop-blur-xl md:left-[var(--sidebar-width,0px)]"
          onSubmit={(event) => {
            event.preventDefault();
            send();
          }}
        >
          <div className="composer-field mx-auto flex max-w-3xl items-end gap-1 bg-surface py-1 pr-1 pl-2">
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
        </form>
      </div>
    </div>
  );
}
