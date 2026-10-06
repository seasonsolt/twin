import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router';
import { Pause, Volume2 } from 'lucide-react';
import { MessageList } from '../components/effects/MessageList';
import { ReplyReveal } from '../components/effects/ReplyReveal';
import { ThinkingLabel } from '../components/effects/ThinkingLabel';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  Textarea,
  useConfirm,
} from '../components/ui';
import { Citations } from '../features/chat/Citations';
import { useConversation } from '../features/chat/useConversation';
import { ChatAvatar } from '../features/chat/ChatAvatar';
import { ReplyVideo } from '../features/chat/ReplyVideo';
import { useReplyAudio } from '../features/chat/useReplyAudio';
import type { Capabilities } from '../features/avatar/types';
import { api } from '../lib/api';
import { useStatus } from '../stores/status';

export function Chat() {
  const { pathname } = useLocation();
  const active = pathname === '/chat';
  const chat = useConversation(active);
  const confirm = useConfirm();
  const status = useStatus((state) => state.data);
  const name = status?.target_name || '本人';
  const [stale, setStale] = useState(false);
  const [stateError, setStateError] = useState('');
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const audio = useReplyAudio(active);
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
  }, [active]);
  const stateRequest = useRef<AbortController | null>(null);
  const alive = useRef(false);
  const end = useRef<HTMLDivElement>(null);
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
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'nearest' });
  }, [chat.turns.length, chat.busy]);
  const send = () => {
    if (chat.busy || !chat.draft.trim()) return;
    void refreshState();
    void chat.send();
  };
  const clear = async () => {
    if (
      (await confirm({
        title: '清空对话？',
        body: '此标签页中的对话将被清除，无法恢复。',
        confirmLabel: '确认清空',
        tone: 'danger',
      })) &&
      alive.current
    ) {
      chat.clear();
      audio.stop();
    }
  };
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <audio ref={audio.audioRef} preload="auto" className="hidden" />
      <header>
        <h1 className="text-2xl font-semibold">和{name}的分身聊天</h1>
        <p className="mt-2 text-sm text-secondary">
          {status?.labels.chat_notice}
        </p>
      </header>
      {stale && (
        <p
          role="status"
          className="rounded-md border border-warning/20 bg-warning/5 px-4 py-2 text-sm text-secondary"
        >
          新添加的记忆正在处理中，聊天暂时使用已记住的内容。{' '}
          <a className="text-accent underline" href="#/memories">
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
        className="max-h-[55dvh] min-h-48 overflow-y-auto px-1 py-2"
        aria-live="polite"
        aria-relevant="additions text"
      >
        {!chat.turns.length && (
          <>
            <EmptyState
              title={status?.counts.sources === 0 ? '还没有记忆' : '还没有对话'}
              body={
                status?.counts.sources === 0
                  ? '先添加一些关于你的记忆，再来聊聊。'
                  : '在下面输入一句话开始，也可以先添加记忆。'
              }
            />
            <a className="text-accent underline" href="#/memories">
              添加记忆
            </a>
          </>
        )}
        <MessageList
          label="对话记录"
          className="space-y-6"
          items={chat.turns.map((turn) => ({
            id: turn.id,
            text: turn.content,
            content: (
              <article
                aria-label={turn.role === 'user' ? '你说' : '分身回复'}
                className={
                  turn.role === 'user'
                    ? 'ml-auto w-fit max-w-[85%] rounded-lg bg-accent/5 px-4 py-3'
                    : `mr-auto flex w-full min-w-0 gap-3 rounded-lg bg-surface px-3 py-3 ${turn.reply?.abstain ? 'text-secondary' : 'text-primary'}`
                }
              >
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
                    <ReplyReveal
                      text={turn.content}
                      className={
                        turn.reply?.abstain ? 'text-secondary' : undefined
                      }
                    />
                  ) : (
                    <p className="whitespace-pre-wrap">{turn.content}</p>
                  )}
                  <time
                    dateTime={turn.timestamp}
                    className="mt-1 block text-xs text-tertiary"
                  >
                    {new Date(turn.timestamp).toLocaleTimeString(undefined, {
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </time>
                  {turn.reply && (
                    <div className="mt-3 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge
                          tone={turn.reply.abstain ? 'warning' : 'neutral'}
                        >
                          置信度{' '}
                          {Math.round((turn.reply.confidence ?? 0) * 100)}%
                        </Badge>
                        {turn.reply.mode === 'general' && (
                          <Badge tone="neutral">通用回答 · 非本人观点</Badge>
                        )}
                        {turn.reply.abstain && (
                          <>
                            <Badge tone="warning">需要本人确认</Badge>
                            <span className="text-sm text-secondary">
                              {turn.reply.abstain_reason}
                            </span>
                          </>
                        )}
                      </div>
                      <Citations cited={turn.reply.cited} />
                      {!turn.reply.abstain && turn.reply.mode !== 'abstain' && (
                        <>
                          <div
                            role="group"
                            aria-label="回复媒体"
                            className="flex min-w-0 flex-wrap items-center gap-2"
                          >
                            <Button
                              variant="ghost"
                              size="sm"
                              className="min-h-11 min-w-11"
                              aria-label={
                                audio.id === turn.id && audio.playing
                                  ? '暂停语音'
                                  : '播放语音'
                              }
                              aria-busy={audio.id === turn.id && audio.loading}
                              onClick={() =>
                                audio.toggle(turn.id, turn.reply!, name)
                              }
                            >
                              {audio.id === turn.id && audio.playing ? (
                                <Pause size={16} aria-hidden />
                              ) : (
                                <Volume2 size={16} aria-hidden />
                              )}
                              {audio.id === turn.id && audio.playing
                                ? '暂停'
                                : '听'}
                            </Button>
                            {capabilities?.video?.available && (
                              <ReplyVideo
                                id={turn.id}
                                answer={turn.reply}
                                name={name}
                                portrait={capabilities.avatar_image?.url}
                                label={
                                  capabilities.label || status?.labels.explicit
                                }
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
                        </>
                      )}
                    </div>
                  )}
                </div>
              </article>
            ),
          }))}
        />
        {chat.busy && (
          <div className="px-4 py-4">
            <ThinkingLabel />
          </div>
        )}
        <div ref={end} />
      </div>
      {chat.error && (
        <div
          role="alert"
          className="rounded-md border border-danger/20 bg-danger/5 px-4 py-3 text-danger"
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
      <Card>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            send();
          }}
        >
          <Field
            id="chat-input"
            label="你说"
            help="Enter 发送，Shift + Enter 换行"
          >
            <Textarea
              id="chat-input"
              autoFocus
              maxLength={4000}
              value={chat.draft}
              onChange={(event) => chat.setDraft(event.target.value)}
              onSend={send}
              aria-describedby="chat-input-description"
              placeholder={`和${name}的分身聊点什么…`}
            />
          </Field>
          <div className="flex flex-wrap justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => void clear()}>
              清空对话
            </Button>
            <Button
              type="submit"
              loading={chat.busy}
              disabled={!chat.draft.trim()}
            >
              发送
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
