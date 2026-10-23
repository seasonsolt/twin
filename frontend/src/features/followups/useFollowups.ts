import { useCallback, useEffect } from 'react';
import { api } from '../../lib/api';
import { usePersonaId, usePersonaState } from '../../lib/usePersonaState';

/** A question someone asked the twin that it could not answer. */
export interface Followup {
  followup_id: string;
  question: string;
  previous: string;
  reason: string;
  asked: number;
  first_at: string;
  last_at: string;
  status: 'pending' | 'answered' | 'dismissed';
  handled_at: string | null;
  asked_since: number;
  source_id: string | null;
  unresolved: boolean;
}

export interface FollowupList {
  items: Followup[];
  pending: number;
}

/** Said whenever the questions waiting change, for the count the side bar shows on the account. */
export const FOLLOWUPS_CHANGED = 'twin-followups-changed';

/** The questions the twin in view could not answer, loaded again whenever it is switched. `reload` is for after an
 * answer or a change of mind: it also tells the rest of the page. */
export function useFollowups(enabled = true) {
  const personaId = usePersonaId();
  const [data, setData] = usePersonaState<FollowupList | null>(null);
  const [error, setError] = usePersonaState('');
  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        setData(await api<FollowupList>('/api/persona/followups', { signal }));
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
    window.dispatchEvent(new Event(FOLLOWUPS_CHANGED));
  }, [load]);
  return { data, error, reload };
}
