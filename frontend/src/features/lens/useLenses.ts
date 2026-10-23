import { useCallback, useEffect } from 'react';
import { api } from '../../lib/api';
import { usePersonaId, usePersonaState } from '../../lib/usePersonaState';
import type { LensList } from './types';

/** The person's lenses and the facets they could open, for the twin in view, loaded again when it is switched. */
export function useLenses(enabled = true) {
  const personaId = usePersonaId();
  const [data, setData] = usePersonaState<LensList | null>(null);
  const [error, setError] = usePersonaState('');
  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        setData(await api<LensList>('/api/persona/lenses', { signal }));
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
  const reload = useCallback(() => load(), [load]);
  return { data, error, reload };
}
