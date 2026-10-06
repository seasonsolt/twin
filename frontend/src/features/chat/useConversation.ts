import { useEffect, useRef, useState } from 'react';
import { api } from '../../lib/api';
import { personaKey } from '../../lib/persona';
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
function wait(signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', abort);
      resolve();
    }, 1000);
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) {
      signal.removeEventListener('abort', abort);
      abort();
    }
  });
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
  }, [active]);
  const send = async (text = draft) => {
    text = text.trim();
    if (!text || request.current || !mounted.current) return;
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
      const response = await api<{ job_id: string } | ChatReply>(
        '/api/persona/chat',
        {
          method: 'POST',
          json: {
            messages: pending.map(({ role, content }) => ({ role, content })),
          },
          signal: controller.signal,
        },
      );
      const finish = (reply: ChatReply) => {
        if (controller.signal.aborted || !mounted.current) return;
        const twin: Turn = {
          id: crypto.randomUUID(),
          role: 'twin',
          content: reply.reply,
          reply,
          timestamp: new Date().toISOString(),
        };
        const complete = [...pending, twin];
        setTurns(complete);
        setNewest(twin.id);
        saveHistory(complete, historyKey);
        failed.current = null;
      };
      if ('reply' in response) {
        finish(response);
        return;
      }
      const { job_id } = response;
      if (!job_id) throw new Error('服务没有返回任务编号');
      for (;;) {
        await wait(controller.signal);
        const job = await api<{
          status: 'queued' | 'running' | 'done' | 'failed';
          result: ChatReply;
          error?: string;
        }>(`/api/jobs/${encodeURIComponent(job_id)}`, {
          signal: controller.signal,
        });
        if (controller.signal.aborted || !mounted.current) return;
        if (job.status === 'failed') throw new Error(job.error || '任务失败');
        if (job.status !== 'done') continue;
        finish(job.result);
        break;
      }
    } catch (error) {
      if (!controller.signal.aborted && mounted.current) {
        setTurns(turns);
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
