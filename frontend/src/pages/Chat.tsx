import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router';
import { MessageList } from '../components/effects/MessageList';
import { ReplyReveal } from '../components/effects/ReplyReveal';
import { ThinkingLabel } from '../components/effects/ThinkingLabel';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  Textarea,
  useConfirm,
} from '../components/ui';
import { Citations } from '../features/chat/Citations';
import { useConversation } from '../features/chat/useConversation';
import type { ChatReply } from '../features/chat/types';
import { PlaybackDialog } from '../features/playback/PlaybackDialog';
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
  const [playback, setPlayback] = useState<{
    answer: ChatReply;
    trigger: HTMLElement;
  } | null>(null);
  const [playbackOpen, setPlaybackOpen] = useState(false);
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
    else setPlaybackOpen(false);
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
      setPlaybackOpen(false);
    }
  };
  return (
    <div className="mx-auto max-w-3xl space-y-6">
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
          资料有变化，尚未重新构建；档案和聊天仍基于上次构建。{' '}
          <a className="text-accent underline" href="/#/sources">
            去重新构建
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
          <EmptyState
            title="还没有对话"
            body="在下面输入一句话开始。分身只依据已构建的人格档案作答。"
          />
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
                    : `mr-auto max-w-[95%] rounded-lg bg-surface px-4 py-3 ${turn.reply?.abstain ? 'text-secondary' : 'text-primary'}`
                }
              >
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
                      <Badge tone={turn.reply.abstain ? 'warning' : 'neutral'}>
                        置信度 {Math.round((turn.reply.confidence ?? 0) * 100)}%
                      </Badge>
                      {turn.reply.abstain && (
                        <>
                          <Badge tone="warning">需要本人确认</Badge>
                          <span className="text-sm text-secondary">
                            {turn.reply.abstain_reason}
                          </span>
                        </>
                      )}
                      {turn.reply.as_of && (
                        <span className="text-xs text-tertiary">
                          资料截至 {turn.reply.as_of}
                        </span>
                      )}
                    </div>
                    <Citations cited={turn.reply.cited} />
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(event) => {
                        setPlayback({
                          answer: turn.reply!,
                          trigger: event.currentTarget,
                        });
                        setPlaybackOpen(true);
                      }}
                    >
                      回放
                    </Button>
                  </div>
                )}
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
          <Field id="chat-asof" label="只用这一天及以前的资料" help="可选">
            <Input
              id="chat-asof"
              type="date"
              className="max-w-64"
              value={chat.asOf}
              onChange={(event) => chat.setAsOf(event.target.value)}
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
      {playback && (
        <PlaybackDialog
          open={playbackOpen && active}
          onOpenChange={setPlaybackOpen}
          answer={playback.answer}
          personaName={name}
          trigger={playback.trigger}
        />
      )}
    </div>
  );
}
