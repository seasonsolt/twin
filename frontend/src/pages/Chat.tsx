import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import { useLocation } from 'react-router';
import { ArrowUp, Pause, Play, Trash2 } from 'lucide-react';
import { MessageList } from '../components/effects/MessageList';
import { ReplyReveal } from '../components/effects/ReplyReveal';
import { ThinkingLabel } from '../components/effects/ThinkingLabel';
import { Button, EmptyState, IconButton, Textarea } from '../components/ui';
import { Citations } from '../features/chat/Citations';
import { useConversation } from '../features/chat/useConversation';
import { ChatAvatar } from '../features/chat/ChatAvatar';
import { ReplyVideo } from '../features/chat/ReplyVideo';
import { useReplyAudio } from '../features/chat/useReplyAudio';
import { useReplyVideos } from '../features/chat/useReplyVideos';
import type { Capabilities } from '../features/avatar/types';
import { api } from '../lib/api';
import { useStatus } from '../stores/status';

export function Chat() {
  const { pathname } = useLocation();
  const active = pathname === '/chat';
  const chat = useConversation(active);
  const status = useStatus((state) => state.data);
  const name = status?.target_name || '本人';
  const [stale, setStale] = useState(false);
  const [stateError, setStateError] = useState('');
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [assetVersion, setAssetVersion] = useState(0);
  useEffect(() => {
    const changed = () => {
      setCapabilities(null);
      setAssetVersion((value) => value + 1);
    };
    window.addEventListener('twin-assets-changed', changed);
    return () => window.removeEventListener('twin-assets-changed', changed);
  }, []);
  const audio = useReplyAudio(active);
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
  }, [active, chat.turns.length, chat.busy, composerHeight]);
  const send = () => {
    if (chat.busy || !chat.draft.trim()) return;
    void refreshState();
    void chat.send();
  };
  return (
    <div
      className="chat-page mx-auto max-w-3xl space-y-4"
      style={{
        paddingBottom: `calc(${composerHeight + 12}px + var(--keyboard-inset, 0px))`,
      }}
    >
      <audio ref={audio.audioRef} preload="auto" className="hidden" />
      <header className="flex items-center gap-2 border-b border-border pb-3">
        <ChatAvatar name={name} capabilities={capabilities} />
        <h1 className="text-md font-semibold">{name}</h1>
        <IconButton
          label="清空对话"
          className="ml-auto hidden min-h-11 min-w-11 md:inline-flex"
          onClick={() => {
            chat.clear();
            audio.stop();
          }}
        >
          <Trash2 className="size-4" aria-hidden />
        </IconButton>
      </header>
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
          <Button variant="ghost" size="sm" onClick={() => void refreshState()}>
            重新检查
          </Button>
        </div>
      )}
      <div
        aria-live="polite"
        aria-relevant="additions text"
        data-testid="chat-messages"
      >
        {!chat.turns.length && (
          <EmptyState
            title={status?.counts.sources === 0 ? '还没有记忆' : '还没有对话'}
            body={
              status?.counts.sources === 0
                ? '先添加一些关于你的记忆，再来聊聊。'
                : '在下面输入一句话开始，也可以先添加记忆。'
            }
          >
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
              text: abstain
                ? turn.reply?.abstain_reason || turn.content
                : turn.content,
              content: (
                <article
                  aria-label={turn.role === 'user' ? '你说' : '分身回复'}
                  className={
                    turn.role === 'user'
                      ? 'ml-auto w-fit max-w-[85%] rounded-2xl bg-accent/10 px-3 py-2'
                      : abstain
                        ? 'mr-auto text-sm text-secondary'
                        : 'mr-auto flex w-full min-w-0 gap-2 text-primary'
                  }
                >
                  {abstain ? (
                    <p>{turn.reply?.abstain_reason || turn.content}</p>
                  ) : (
                    <>
                      {turn.role === 'twin' && (
                        <ChatAvatar
                          name={name}
                          capabilities={capabilities}
                          level={audio.id === turn.id ? audio.level : 0}
                          speaking={audio.id === turn.id && audio.speaking}
                        />
                      )}
                      <div className="min-w-0 flex-1 break-words">
                        {turn.role === 'twin' && turn.id === chat.newest ? (
                          <ReplyReveal text={turn.content} />
                        ) : (
                          <p className="whitespace-pre-wrap">{turn.content}</p>
                        )}
                        {turn.reply && (
                          <div className="mt-1">
                            <div
                              role="group"
                              aria-label="回复媒体"
                              className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1"
                            >
                              {capabilities?.available && (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="min-h-11 min-w-11 px-2"
                                  aria-label={
                                    audio.id === turn.id && audio.playing
                                      ? '暂停语音'
                                      : '播放语音'
                                  }
                                  aria-busy={
                                    audio.id === turn.id && audio.loading
                                  }
                                  onClick={() =>
                                    audio.toggle(turn.id, turn.reply!, name)
                                  }
                                >
                                  {audio.id === turn.id && audio.playing ? (
                                    <Pause size={14} aria-hidden />
                                  ) : (
                                    <Play size={14} aria-hidden />
                                  )}
                                  {audio.id === turn.id && audio.playing
                                    ? '暂停'
                                    : '播放'}
                                </Button>
                              )}
                              <Citations cited={turn.reply.cited} />
                              {capabilities?.video?.available && (
                                <ReplyVideo
                                  id={turn.id}
                                  answer={turn.reply}
                                  portrait={capabilities.avatar_image?.url}
                                  state={video.videos[turn.id]}
                                  speaking={
                                    audio.id === turn.id && audio.playing
                                  }
                                  onRetry={() => video.retry(turn.id)}
                                  onError={() => video.invalidate(turn.id)}
                                />
                              )}
                            </div>
                            {audio.id === turn.id && (
                              <progress
                                aria-label="语音播放进度"
                                max={1}
                                value={audio.progress}
                                className="block h-1 w-full accent-accent"
                              />
                            )}
                            {audio.errors[turn.id] && (
                              <p role="alert" className="text-xs text-danger">
                                {audio.errors[turn.id]}
                              </p>
                            )}
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </article>
              ),
            };
          })}
        />
        {chat.busy && (
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
      <form
        ref={composer}
        aria-label="消息输入"
        className="chat-composer fixed inset-x-0 z-20 border-t border-border bg-canvas/95 px-3 pt-2 backdrop-blur-xl md:left-[var(--sidebar-width,0px)]"
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
      >
        <div className="mx-auto flex max-w-3xl items-end gap-1 rounded-3xl border border-border bg-surface py-1 pr-1 pl-2">
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
            className="size-11 min-h-11 rounded-full p-0"
            loading={chat.busy}
            disabled={!chat.draft.trim()}
          >
            {!chat.busy && <ArrowUp className="size-5" aria-hidden />}
          </Button>
        </div>
      </form>
    </div>
  );
}
