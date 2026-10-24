import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import type { ItemSummary } from '../profile/types';
import { useStatus } from '../../stores/status';

/**
 * How many memories of a twin the viewer may use, as the profile counts them (by the viewer's tier). The server-wide
 * ``/api/status`` count is not it: it also counts what only the twin's person may use, which nobody else is told
 * exists. Asked only for those who may open the memory, and again whenever the twin's memory changes (the status
 * the app polls says so).
 */
export function useMemoryCount(twinId: string, enabled = true) {
  const [total, setTotal] = useState<number | null>(null);
  const changed = useStatus((state) => state.data?.counts?.items);
  const updating = useStatus((state) => state.data?.memory_updating);
  useEffect(() => {
    // A visitor to someone else's twin is told nothing of its memory.
    if (!enabled) return;
    const controller = new AbortController();
    api<ItemSummary>('/api/persona/items/summary', {
      signal: controller.signal,
      headers: { 'X-Twin-Persona': twinId },
    })
      .then((found) => {
        if (!controller.signal.aborted) setTotal(found.total);
      })
      .catch(() => {});
    return () => controller.abort();
  }, [twinId, enabled, changed, updating]);
  return total;
}
