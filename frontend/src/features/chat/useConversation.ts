import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../../lib/api';
import { getPersonaId, personaKey } from '../../lib/persona';
import { readSSE } from '../../lib/sse';
import type { ChatReply, Turn } from './types';

export const CHAT_KEY = 'twin.next.chat';
export const CURRENT_CHAT_KEY = 'twin.current.conversation';
export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
  turns: number;
  preview: string;
}
interface Conversation {
  id: string;
  title: string;
  turns: Turn[];
}
function stored(key: string) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function remember(key: string, id: string | null) {
  try {
    if (id) localStorage.setItem(key, id);
    else localStorage.removeItem(key);
  } catch {
    // Storage is optional.
  }
}
function loadLegacy(key: string): Turn[] {
  try {
    const saved: unknown = JSON.parse(sessionStorage.getItem(key) ?? '[]');
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
const migrations = new Map<string, Promise<string>>();
function migrate(key: string, turns: Turn[], headers: HeadersInit) {
  const existing = migrations.get(key);
  if (existing) return existing;
  let migrationId: string = crypto.randomUUID();
  try {
    migrationId = sessionStorage.getItem(`${key}.migration`) || migrationId;
    sessionStorage.setItem(`${key}.migration`, migrationId);
  } catch {
    // The in-flight promise still avoids duplicate imports in StrictMode.
  }
  const pending = api<{ id: string }>('/api/conversations', {
    method: 'POST',
    json: { turns, migration_id: migrationId },
    headers,
  })
    .then(({ id }) => {
      try {
        sessionStorage.removeItem(key);
        sessionStorage.removeItem(`${key}.migration`);
      } catch {
        // Import is idempotent if the old copy cannot be cleared.
      }
      return id;
    })
    .finally(() => migrations.delete(key));
  migrations.set(key, pending);
  return pending;
}
const message = (error: unknown) =>
  error instanceof Error ? error.message : '无法加载对话记录';

export function useConversation(active: boolean) {
  const legacyKey = personaKey(CHAT_KEY);
  const currentKey = personaKey(CURRENT_CHAT_KEY);
  const personaId = getPersonaId();
  const headers = useCallback(
    () => ({ 'X-Twin-Persona': personaId }),
    [personaId],
  );
  const [turns, setTurns] = useState(() => loadLegacy(legacyKey));
  const [conversationId, setConversationId] = useState<string | null>(null);
  const id = useRef<string | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [restoreFailed, setRestoreFailed] = useState(false);
  const [restoreVersion, setRestoreVersion] = useState(0);
  const [error, setError] = useState('');
  const [historyError, setHistoryError] = useState('');
  const [history, setHistory] = useState<ConversationSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [newest, setNewest] = useState<string | null>(null);
  const mounted = useRef(false);
  const request = useRef<AbortController | null>(null);
  const historyRequest = useRef<AbortController | null>(null);
  const failed = useRef<string | null>(null);
  const selectId = useCallback(
    (value: string | null) => {
      id.current = value;
      setConversationId(value);
      remember(currentKey, value);
    },
    [currentKey],
  );
  const refreshHistory = useCallback(
    async (offset = 0) => {
      historyRequest.current?.abort();
      const controller = new AbortController();
      historyRequest.current = controller;
      setHistoryLoading(true);
      setHistoryError('');
      try {
        const rows = await api<ConversationSummary[]>(
          `/api/conversations?offset=${offset}`,
          {
            headers: headers(),
            signal: controller.signal,
          },
        );
        if (controller.signal.aborted || !mounted.current) return;
        setHistory((previous) => (offset ? [...previous, ...rows] : rows));
        setHasMore(rows.length === 50);
      } catch (error) {
        if (!controller.signal.aborted && mounted.current)
          setHistoryError(message(error));
      } finally {
        if (!controller.signal.aborted && mounted.current)
          setHistoryLoading(false);
      }
    },
    [headers],
  );
  useEffect(() => {
    mounted.current = active;
    if (!active) return;
    const controller = new AbortController();
    request.current = controller;
    const legacy = loadLegacy(legacyKey);
    const saved = stored(currentKey);
    id.current = null;
    setConversationId(null);
    setTurns(legacy);
    failed.current = null;
    setBusy(false);
    setError('');
    setRestoreFailed(false);
    setNewest(null);
    setHistory([]);
    if (saved || legacy.length) {
      setLoading(true);
      void (async () => {
        try {
          const imported = legacy.length
            ? await migrate(legacyKey, legacy, headers())
            : null;
          if (controller.signal.aborted) return;
          const nextId = saved || imported;
          if (!nextId) return;
          const conversation = await api<Conversation>(
            `/api/conversations/${encodeURIComponent(nextId)}`,
            {
              headers: headers(),
              signal: controller.signal,
            },
          );
          if (!controller.signal.aborted) {
            selectId(conversation.id);
            setTurns(conversation.turns);
          }
        } catch (error) {
          if (!controller.signal.aborted) {
            if (error instanceof ApiError && error.status === 404) {
              selectId(null);
              setTurns([]);
            } else {
              setRestoreFailed(true);
              setError(message(error));
            }
          }
        } finally {
          if (!controller.signal.aborted) setLoading(false);
        }
      })();
    } else {
      id.current = null;
      setConversationId(null);
      setTurns([]);
      setLoading(false);
    }
    return () => {
      mounted.current = false;
      controller.abort();
      request.current?.abort();
      historyRequest.current?.abort();
    };
  }, [active, legacyKey, currentKey, headers, selectId, restoreVersion]);

  const send = async (text = draft) => {
    text = text.trim();
    if (!text || !mounted.current || busy || loading || restoreFailed) return;
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
      if (!id.current) {
        const created = await api<{ id: string }>('/api/conversations', {
          method: 'POST',
          json: {},
          headers: headers(),
          signal: controller.signal,
        });
        if (controller.signal.aborted || !mounted.current) return;
        selectId(created.id);
      }
      const response = await api<Response>('/api/persona/chat/stream', {
        method: 'POST',
        json: {
          conversation_id: id.current,
          messages: pending
            .slice(-40)
            .map(({ role, content }) => ({ role, content })),
        },
        headers: headers(),
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
      for await (const { event, data } of readSSE(
        response,
        controller.signal,
      )) {
        if (controller.signal.aborted || !mounted.current) return;
        if (event === 'delta') {
          twin.content += (data as { text: string }).text;
          setTurns([...pending, { ...twin }]);
          setNewest(twin.id);
        } else if (event === 'final') {
          twin.reply = data as ChatReply;
          twin.content = twin.reply.reply;
          finished = true;
          setTurns([...pending, { ...twin }]);
          setNewest(twin.id);
          failed.current = null;
          void refreshHistory();
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
        setError(message(error));
        if (error instanceof ApiError && error.status === 404) selectId(null);
      }
    } finally {
      if (request.current === controller) request.current = null;
      if (!controller.signal.aborted && mounted.current) setBusy(false);
    }
  };
  const clear = () => {
    request.current?.abort();
    request.current = null;
    selectId(null);
    setTurns([]);
    setDraft('');
    setBusy(false);
    setLoading(false);
    setRestoreFailed(false);
    setError('');
    setNewest(null);
    failed.current = null;
  };
  const resume = async (nextId: string) => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setBusy(false);
    setLoading(true);
    setError('');
    try {
      const conversation = await api<Conversation>(
        `/api/conversations/${encodeURIComponent(nextId)}`,
        {
          headers: headers(),
          signal: controller.signal,
        },
      );
      if (controller.signal.aborted || !mounted.current) return false;
      selectId(conversation.id);
      setTurns(conversation.turns);
      setRestoreFailed(false);
      setDraft('');
      setNewest(null);
      failed.current = null;
      return true;
    } catch (error) {
      if (!controller.signal.aborted && mounted.current)
        setHistoryError(message(error));
      return false;
    } finally {
      if (!controller.signal.aborted && mounted.current) setLoading(false);
    }
  };
  const rename = async (nextId: string, title: string) => {
    await api(`/api/conversations/${encodeURIComponent(nextId)}`, {
      method: 'PATCH',
      json: { title },
      headers: headers(),
    });
    if (mounted.current)
      setHistory((rows) =>
        rows.map((row) => (row.id === nextId ? { ...row, title } : row)),
      );
  };
  const remove = async (nextId: string) => {
    await api(`/api/conversations/${encodeURIComponent(nextId)}`, {
      method: 'DELETE',
      headers: headers(),
    });
    if (!mounted.current) return;
    if (id.current === nextId) clear();
    void refreshHistory();
  };
  return {
    turns,
    conversationId,
    draft,
    setDraft,
    busy,
    loading,
    restoreFailed,
    error,
    newest,
    send,
    clear,
    history,
    historyError,
    historyLoading,
    hasMore,
    refreshHistory,
    resume,
    rename,
    remove,
    retry: () => {
      if (failed.current) void send(failed.current);
      else if (restoreFailed) setRestoreVersion((value) => value + 1);
    },
  };
}
