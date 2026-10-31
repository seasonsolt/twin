import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import type { PaceState } from '../settings/Pace';

/**
 * 节奏提醒 (P3.6): the line to show above the person's own conversation once the pace they set is reached, read
 * again each time an answer is done; ``goOn`` keeps it away for the rest of the day.
 */
export function usePace(on: boolean, busy: boolean) {
  const [reminder, setReminder] = useState<string | null>(null);
  useEffect(() => {
    if (!on || busy) return;
    const controller = new AbortController();
    void api<PaceState>('/api/persona/pace', { signal: controller.signal })
      .then((state) => setReminder(state.reminder))
      .catch(() => {});
    return () => controller.abort();
  }, [on, busy]);
  const goOn = () => {
    setReminder(null);
    void api<PaceState>('/api/persona/pace/go-on', { method: 'POST' }).catch(
      () => {},
    );
  };
  return { reminder: on ? reminder : null, goOn };
}
