import { useCallback, useEffect, useRef } from 'react';
import { usePolling } from '../../lib/usePolling';
import { api } from '../../lib/api';
import { usePersonaId, usePersonaState } from '../../lib/usePersonaState';

export type HandoffKind =
  'decide' | 'commit' | 'evaluate' | 'missing' | 'inferred';
export type HandoffStatus =
  | 'delivered'
  | 'writing'
  | 'replied'
  | 'accepted'
  | 'declined'
  | 'dismissed'
  | 'expired'
  | 'withdrawn';

/** What a colleague's question left to the person: a decision, a promise, a judgement, or an answer the twin lacks. */
export interface Handoff {
  id: string;
  kind: HandoffKind;
  kind_label: string;
  status: HandoffStatus;
  status_label: string;
  asker_name: string;
  question: string;
  context: string;
  ask: string;
  /** What the twin said, when the conversation is known. */
  answer: string | null;
  /** How the twin met it: it answered (grounded, general, inferred) or had nothing to say (abstain). */
  twin_mode?: 'grounded' | 'general' | 'inferred' | 'abstain' | null;
  /** False for a question from before handoffs: it can be kept as a memory, not written back. */
  source_known: boolean;
  created_at: string;
  expires_at: string;
  days_left: number | null;
  /** The promise asked for, with whether the person has taken it yet. */
  commit: {
    entry_id: string | null;
    what: string;
    due: string | null;
    pending: boolean;
  } | null;
  reply: string | null;
  replied_at: string | null;
}

/** An answer the twin gave from the profile or by guessing, to a colleague. */
export interface AnsweredQuestion {
  conversation_id: string;
  turn: number;
  asker_name: string;
  question: string;
  answer: string;
  at: string;
}

/** A reply the twin has given again and again, which the person may make a team answer. */
export interface OftenReply {
  handoff_id: string;
  title: string;
  reply: string;
  askers: string[];
  uses: number;
  days: number;
}

export interface Away {
  waiting: Handoff[];
  /** Waiting questions that ask the same thing, as lists of their ids (a way of showing them; each stays its own). */
  groups: string[][];
  often: OftenReply[];
  /** The team answers the person has set, and how many of them may be out of date. */
  answers: { total: number; stale: number };
  guessed: AnsweredQuestion[];
  sourced: AnsweredQuestion[];
  sourced_count: number;
  answered: number;
  shelved: Handoff[];
  settled: Handoff[];
  pending: number;
  days: number;
}

/** Said whenever what waits for the person changes, for the number the side bar shows on the account. */
export const AWAY_CHANGED = 'twin-away-changed';

/** What happened while the person was away, for the twin in view, loaded again whenever it is switched. `reload` is
 * for after a reply or a change of mind: it also tells the rest of the page. */
export function useAway(enabled = true) {
  const personaId = usePersonaId();
  const [data, setData] = usePersonaState<Away | null>(null);
  const [error, setError] = usePersonaState('');
  const latest = useRef(data);
  latest.current = data;
  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        setData(await api<Away>('/api/persona/handoffs', { signal }));
        setError('');
      } catch (failure) {
        if (signal?.aborted || latest.current) return;
        setError(failure instanceof Error ? failure.message : '加载失败');
      }
    },
    [setData, setError],
  );
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [enabled, load, personaId]);
  usePolling(() => load(), enabled ? 15000 : 0);
  const reload = useCallback(async () => {
    await load();
    window.dispatchEvent(new Event(AWAY_CHANGED));
  }, [load]);
  return { data, error, reload };
}
