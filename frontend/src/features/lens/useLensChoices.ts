import { useCallback, useEffect } from 'react';
import { api } from '../../lib/api';
import { usePersonaId, usePersonaState } from '../../lib/usePersonaState';
import type { LensChoice } from './types';

/** The lenses the person behind the twin in view has published for the viewer to ask in this conversation. None when
 * the viewer is that person, or there is nothing to ask; a failure to ask leaves it at none. `reload` is for after a
 * lens turned out not to be there any more. */
export function useLensChoices(enabled: boolean) {
  const personaId = usePersonaId();
  const [choices, setChoices] = usePersonaState<LensChoice[]>([]);
  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const found = await api<{ lenses: LensChoice[] }>(
          '/api/persona/lenses/available',
          { signal },
        );
        setChoices(Array.isArray(found.lenses) ? found.lenses : []);
      } catch {
        if (!signal?.aborted) setChoices([]);
      }
    },
    [setChoices],
  );
  useEffect(() => {
    if (!enabled) {
      setChoices([]);
      return;
    }
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [enabled, load, personaId, setChoices]);
  const reload = useCallback(() => load(), [load]);
  return { choices, reload };
}
