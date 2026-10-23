import { useCallback, useEffect } from 'react';
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

export interface Away {
  waiting: Handoff[];
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
  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        setData(await api<Away>('/api/persona/handoffs', { signal }));
        setError('');
      } catch (failure) {
        if (signal?.aborted) return;
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
  const reload = useCallback(async () => {
    await load();
    window.dispatchEvent(new Event(AWAY_CHANGED));
  }, [load]);
  return { data, error, reload };
}
