import { useCallback, useEffect, useRef } from 'react';
import {
  usePersonaId,
  usePersonaState as useState,
} from '../../lib/usePersonaState';
import { loadEssential, peekEssential } from '../../lib/personaPrefetch';
import { api, ApiError } from '../../lib/api';
import { getPersonaId, personaKey } from '../../lib/persona';
import { usePolling } from '../../lib/usePolling';
import { readSSE } from '../../lib/sse';
import {
  settling,
  spoken,
  waiting,
  withHandoffs,
  type ChatReply,
  type HandoffLine,
  type NoteTier,
  type Turn,
} from './types';

export const CHAT_KEY = 'twin.next.chat';
export const CURRENT_CHAT_KEY = 'twin.current.conversation';
/** Which tier of memory a conversation answers from: ``self`` is the person's own, with their assistant. */
export type Audience = 'self' | 'colleague';
interface Conversation {
  id: string;
  title: string;
  turns: Turn[];
  audience?: Audience;
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
// The server keeps at most this many turns of an imported conversation; older ones are left out.
const MAX_IMPORTED_TURNS = 500;
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
    json: {
      turns: turns.slice(-MAX_IMPORTED_TURNS),
      migration_id: migrationId,
    },
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

/** What a streamed answer is doing before its first words: looking things up, working them out, writing. */
export type ChatStep = 'search' | 'think' | 'write';

export function useConversation(active: boolean) {
  const legacyKey = personaKey(CHAT_KEY);
  const currentKey = personaKey(CURRENT_CHAT_KEY);
  const personaId = usePersonaId();
  const headers = useCallback(
    () => ({ 'X-Twin-Persona': personaId }),
    [personaId],
  );
  const savedPath = stored(currentKey);
  const prefetched = savedPath
    ? peekEssential<Conversation>(
        `/api/conversations/${encodeURIComponent(savedPath)}`,
        personaId,
      )
    : undefined;
  const [turns, setTurns] = useState(
    () => prefetched?.turns ?? loadLegacy(legacyKey),
  );
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [audience, setAudience] = useState<Audience | null>(null);
  // What the conversation open is called, as it was read or renamed here: the list may not hold it (another page of
  // it, or another list than the conversation's own).
  const [conversationTitle, setConversationTitle] = useState<string | null>(
    null,
  );
  const id = useRef<string | null>(null);
  const [draft, setDraft] = useState('');
  const [attachments, setAttachments] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [restoreFailed, setRestoreFailed] = useState(false);
  const [restoreVersion, setRestoreVersion] = useState(0);
  const [error, setError] = useState('');
  // Why a conversation of the list could not be opened.
  const [openError, setOpenError] = useState('');
  // Counts what was written to the person's conversations (made, answered, renamed, deleted), for the list to ask again.
  const [written, setWritten] = useState(0);
  const [newest, setNewest] = useState<string | null>(null);
  // What the twin is doing before its first words, as the server says (``step`` events).
  const [step, setStep] = useState<ChatStep | null>(null);
  const mounted = useRef(false);
  const request = useRef<AbortController | null>(null);
  const failed = useRef<string | null>(null);
  const failedTrial = useRef(false);
  const failedLens = useRef<string | null>(null);
  const selectId = useCallback(
    (value: string | null) => {
      id.current = value;
      setConversationId(value);
      remember(currentKey, value);
    },
    [currentKey],
  );
  const markWritten = useCallback(
    () => setWritten((count) => count + 1),
    [setWritten],
  );
  useEffect(() => {
    mounted.current = active;
    if (!active) {
      setAttachments([]);
      return;
    }
    const controller = new AbortController();
    request.current = controller;
    const stop = () => {
      mounted.current = false;
      controller.abort();
      request.current?.abort();
    };
    window.addEventListener('twin-persona-switch', stop);
    const legacy = loadLegacy(legacyKey);
    const saved = stored(currentKey);
    id.current = null;
    setConversationId(null);
    setAudience(null);
    setConversationTitle(null);
    const cached = saved
      ? peekEssential<Conversation>(
          `/api/conversations/${encodeURIComponent(saved)}`,
          personaId,
        )
      : undefined;
    setTurns(cached?.turns ?? legacy);
    setDraft('');
    setAttachments([]);
    failed.current = null;
    setBusy(false);
    setError('');
    setRestoreFailed(false);
    setNewest(null);
    if (saved || legacy.length) {
      setLoading(!cached);
      void (async () => {
        try {
          const imported = legacy.length
            ? await migrate(legacyKey, legacy, headers())
            : null;
          if (controller.signal.aborted) return;
          const nextId = saved || imported;
          if (!nextId) return;
          const conversation = await loadEssential<Conversation>(
            `/api/conversations/${encodeURIComponent(nextId)}`,
            personaId,
            controller.signal,
          );
          if (!controller.signal.aborted) {
            selectId(conversation.id);
            setAudience(conversation.audience ?? null);
            setConversationTitle(conversation.title ?? null);
            setTurns(conversation.turns);
            if (imported) markWritten();
          }
        } catch (error) {
          if (!controller.signal.aborted) {
            if (error instanceof ApiError && error.status === 404) {
              selectId(null);
              setAudience(null);
              setConversationTitle(null);
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
      setAudience(null);
      setConversationTitle(null);
      setTurns([]);
      setLoading(false);
    }
    return () => {
      window.removeEventListener('twin-persona-switch', stop);
      stop();
    };
  }, [
    active,
    legacyKey,
    currentKey,
    headers,
    selectId,
    restoreVersion,
    markWritten,
    personaId,
  ]);

  /** ``trial``: ask as a colleague would be answered (看同事会得到什么), and keep nothing of it. ``lens``: put the
   * question to that lens of the person (a colleague's, not a streamed answer of the twin). */
  const send = async (
    text = draft,
    trial = false,
    lens: string | null = null,
  ) => {
    text = text.trim();
    if (
      !text ||
      !mounted.current ||
      personaId !== getPersonaId() ||
      busy ||
      loading ||
      restoreFailed
    )
      return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const user: Turn = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
      ...(trial ? { preview: true } : {}),
    };
    const pending = [...turns, user];
    setTurns(pending);
    setDraft('');
    setBusy(true);
    setError('');
    setNewest(null);
    setStep(null);
    try {
      if (!id.current && !trial) {
        const created = await api<{ id: string; audience?: Audience }>(
          '/api/conversations',
          {
            method: 'POST',
            json: {},
            headers: headers(),
            signal: controller.signal,
          },
        );
        if (controller.signal.aborted || !mounted.current) return;
        selectId(created.id);
        setAudience(created.audience ?? null);
      }
      if (lens && !trial) {
        const reply = await api<ChatReply>(
          `/api/persona/lenses/${encodeURIComponent(lens)}/ask`,
          {
            method: 'POST',
            json: { question: text, conversation_id: id.current },
            headers: headers(),
            signal: controller.signal,
          },
        );
        if (controller.signal.aborted || !mounted.current) return;
        const answer: Turn = {
          id: crypto.randomUUID(),
          role: 'twin',
          content: reply.reply,
          timestamp: new Date().toISOString(),
          reply,
        };
        setTurns([...pending, answer]);
        setNewest(answer.id);
        failed.current = null;
        markWritten();
        return;
      }
      const payload = trial
        ? {
            conversation_id: id.current,
            messages: [{ role: 'user', content: text }],
            preview: true,
          }
        : {
            conversation_id: id.current,
            messages: pending
              .filter(spoken)
              .slice(-40)
              .map(({ role, content }) => ({ role, content })),
          };
      const response =
        attachments.length && !trial
          ? await (() => {
              const form = new FormData();
              form.append('payload', JSON.stringify(payload));
              attachments.forEach((file) =>
                form.append('files', file, file.name),
              );
              return api<Response>('/api/persona/chat/stream-with-files', {
                method: 'POST',
                form,
                headers: headers(),
                signal: controller.signal,
                responseType: 'stream',
              });
            })()
          : await api<Response>('/api/persona/chat/stream', {
              method: 'POST',
              json: payload,
              headers: headers(),
              signal: controller.signal,
              responseType: 'stream',
            });
      const twin: Turn = {
        id: crypto.randomUUID(),
        role: 'twin',
        content: '',
        timestamp: new Date().toISOString(),
        ...(trial ? { preview: true } : {}),
      };
      let finished = false;
      for await (const { event, data } of readSSE(
        response,
        controller.signal,
      )) {
        if (controller.signal.aborted || !mounted.current) return;
        if (event === 'step') {
          setStep((data as { step: ChatStep }).step);
        } else if (event === 'delta') {
          twin.content += (data as { text: string }).text;
          setTurns([...pending, { ...twin }]);
          setNewest(twin.id);
        } else if (event === 'final') {
          twin.reply = data as ChatReply;
          twin.content = twin.reply.reply;
          twin.handoff = twin.reply.handoff;
          finished = true;
          setTurns([...pending, { ...twin }]);
          setNewest(twin.id);
          failed.current = null;
          if (!trial) {
            setAttachments([]);
            markWritten();
          }
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
        failedTrial.current = trial;
        failedLens.current = lens;
        setError(message(error));
        // A lens that is no longer there is also a 404, and says nothing of the conversation.
        if (error instanceof ApiError && error.status === 404 && !lens)
          selectId(null);
      }
    } finally {
      if (request.current === controller) request.current = null;
      if (!controller.signal.aborted && mounted.current) {
        setBusy(false);
        setStep(null);
      }
    }
  };
  // What an answer left to the person is theirs to settle, when they can: until then the conversation is asked again
  // for where it stands, and for their reply, which then appears under the answer.
  const waitingFor = conversationId && !busy && turns.some(waiting);
  // Once they have, it may still change (a late reply, a promise taken on): looked at now and then.
  const settlingFor = conversationId && !busy && turns.some(settling);
  const follow = useCallback(async () => {
    const current = id.current;
    if (!current || !mounted.current || personaId !== getPersonaId()) return;
    try {
      const conversation = await api<Conversation>(
        `/api/conversations/${encodeURIComponent(current)}`,
        { headers: headers() },
      );
      if (id.current === current && mounted.current)
        setTurns((now) => withHandoffs(now, conversation.turns));
    } catch {
      // The next look will do.
    }
  }, [headers, personaId, setTurns]);
  usePolling(follow, waitingFor ? 20000 : settlingFor ? 60000 : 0);
  const clear = () => {
    request.current?.abort();
    request.current = null;
    selectId(null);
    setAudience(null);
    setConversationTitle(null);
    setTurns([]);
    setDraft('');
    setAttachments([]);
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
    setOpenError('');
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
      setAudience(conversation.audience ?? null);
      setConversationTitle(conversation.title ?? null);
      setTurns(conversation.turns);
      setRestoreFailed(false);
      setDraft('');
      setAttachments([]);
      setNewest(null);
      failed.current = null;
      return true;
    } catch (error) {
      if (!controller.signal.aborted && mounted.current)
        setOpenError(message(error));
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
    if (!mounted.current || personaId !== getPersonaId()) return;
    if (id.current === nextId) setConversationTitle(title);
    markWritten();
  };
  const remove = async (nextId: string) => {
    await api(`/api/conversations/${encodeURIComponent(nextId)}`, {
      method: 'DELETE',
      headers: headers(),
    });
    if (!mounted.current || personaId !== getPersonaId()) return;
    if (id.current === nextId) clear();
    markWritten();
  };
  /** Say who may use a note the assistant took down: ``none`` is not keeping it. Rejects when it could not be changed. */
  const setNoteTier = async (turnId: string, tier: NoteTier) => {
    const note = turns.find((turn) => turn.id === turnId)?.reply?.note;
    if (!note) return;
    await api(`/api/persona/notes/${encodeURIComponent(note.id)}/tier`, {
      method: 'PUT',
      json: { tier },
      headers: headers(),
    });
    if (!mounted.current || personaId !== getPersonaId()) return;
    setTurns((rows) =>
      rows.map((turn) =>
        turn.id === turnId && turn.reply?.note
          ? {
              ...turn,
              reply: { ...turn.reply, note: { ...turn.reply.note, tier } },
            }
          : turn,
      ),
    );
  };
  /** After a lens could not settle it: hand the question to the person, in the asker's name. The line under the
   * answer then says where it stands. Rejects with why it could not. */
  const askLensOwner = async (turnId: string) => {
    const current = id.current;
    if (!current) return;
    const { handoff } = await api<{ handoff: HandoffLine }>(
      '/api/persona/lenses/ask-owner',
      {
        method: 'POST',
        json: { conversation_id: current },
        headers: headers(),
      },
    );
    if (!mounted.current || personaId !== getPersonaId()) return;
    setTurns((rows) =>
      rows.map((turn) => (turn.id === turnId ? { ...turn, handoff } : turn)),
    );
  };
  /** Take back a promise the assistant wrote into the commitments from what the person said. */
  const undoPromise = async (turnId: string) => {
    const promise = turns.find((turn) => turn.id === turnId)?.reply?.commitment;
    if (!promise) return;
    await api(
      `/api/persona/ledger/${encodeURIComponent(promise.entry_id)}/review`,
      { method: 'POST', json: { action: 'reject' }, headers: headers() },
    );
    if (!mounted.current || personaId !== getPersonaId()) return;
    setTurns((rows) =>
      rows.map((turn) =>
        turn.id === turnId && turn.reply
          ? { ...turn, reply: { ...turn.reply, commitment: undefined } }
          : turn,
      ),
    );
  };
  return {
    turns,
    conversationId,
    audience,
    conversationTitle,
    setNoteTier,
    undoPromise,
    askLensOwner,
    draft,
    setDraft,
    attachments,
    setAttachments,
    busy,
    loading,
    restoreFailed,
    error,
    newest,
    step,
    send,
    clear,
    openError,
    clearOpenError: () => setOpenError(''),
    written,
    resume,
    rename,
    remove,
    /** ``lens``: the one the composer has chosen now, which the retry goes to (not the one that failed). */
    retry: (lens: string | null = failedLens.current) => {
      if (failed.current) void send(failed.current, failedTrial.current, lens);
      else if (restoreFailed) setRestoreVersion((value) => value + 1);
    },
  };
}
