import { useEffect, useRef, useState } from 'react';
import { api } from '../../lib/api';
import { personaKey } from '../../lib/persona';
import { readSSE } from '../../lib/sse';
import type { ChatReply, Turn } from './types';

export const CHAT_KEY = 'twin.next.chat';
function loadHistory(): Turn[] {
  try {
    const saved: unknown = JSON.parse(
      sessionStorage.getItem(personaKey(CHAT_KEY)) ?? '[]',
    );
    return Array.isArray(saved)
      ? saved.filter(
          (turn): turn is Turn =>
            turn &&
            typeof turn.id === 'string' &&
            (turn.role === 'user' || turn.role === 'twin') &&
            typeof turn.content === 'string' &&
            typeof turn.timestamp === 'string',
        )
      : [];
  } catch {
    return [];
  }
}
function saveHistory(turns: Turn[], key: string) {
  try {
    if (turns.length) sessionStorage.setItem(key, JSON.stringify(turns));
    else sessionStorage.removeItem(key);
  } catch {
    /* A disabled/full store must not block chat. */
  }
}

export function useConversation(active: boolean) {
  const historyKey = personaKey(CHAT_KEY);
  const [turns, setTurns] = useState(loadHistory);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [newest, setNewest] = useState<string | null>(null);
  const mounted = useRef(false);
  const request = useRef<AbortController | null>(null);
  const failed = useRef<string | null>(null);
  useEffect(() => {
    mounted.current = active;
    return () => {
      mounted.current = false;
      request.current?.abort();
      request.current = null;
    };
  }, [active, historyKey]);
  const send = async (text = draft) => {
    text = text.trim();
    if (!text || !mounted.current) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const user: Turn = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    };
    const pending = [...turns, user];
    setTurns(pending);
    setDraft('');
    setBusy(true);
    setError('');
    setNewest(null);
    try {
      const response = await api<Response>('/api/persona/chat/stream', {
        method: 'POST',
        json: {
          messages: pending.map(({ role, content }) => ({ role, content })),
        },
        signal: controller.signal,
        responseType: 'stream',
      });
      const twin: Turn = {
        id: crypto.randomUUID(),
        role: 'twin',
        content: '',
        timestamp: new Date().toISOString(),
      };
      let finished = false;
      const finish = (reply: ChatReply) => {
        if (controller.signal.aborted || !mounted.current) return;
        twin.content = reply.reply;
        twin.reply = reply;
        finished = true;
        const complete = [...pending, { ...twin }];
        setTurns(complete);
        setNewest(twin.id);
        saveHistory(complete, historyKey);
        failed.current = null;
      };
      for await (const { event, data } of readSSE(
        response,
        controller.signal,
      )) {
        if (controller.signal.aborted || !mounted.current) return;
        if (event === 'delta') {
          const { text } = data as { text: string };
          twin.content += text;
          setTurns([...pending, { ...twin }]);
          setNewest(twin.id);
        } else if (event === 'final') {
          finish(data as ChatReply);
          break;
        } else if (event === 'error') {
          throw new Error(
            (data as { detail: string }).detail || '分身没能回复，请重试',
          );
        }
      }
      if (!finished) throw new Error('回复中断，请重试');
    } catch (error) {
      if (!controller.signal.aborted && mounted.current) {
        setTurns(turns);
        setNewest(null);
        setDraft(text);
        failed.current = text;
        setError(
          error instanceof Error ? error.message : '分身没能回复，请重试',
        );
      }
    } finally {
      if (request.current === controller) request.current = null;
      if (!controller.signal.aborted && mounted.current) setBusy(false);
    }
  };
  const clear = () => {
    request.current?.abort();
    request.current = null;
    setTurns([]);
    setBusy(false);
    setError('');
    setNewest(null);
    failed.current = null;
    saveHistory([], historyKey);
  };
  return {
    turns,
    draft,
    setDraft,
    busy,
    error,
    newest,
    send,
    retry: () => {
      if (failed.current) void send(failed.current);
    },
    clear,
  };
}
