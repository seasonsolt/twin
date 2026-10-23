import { useCallback, useEffect, useRef, useState } from 'react';

/** How long a settled row waits for 撤销 before the server is told. */
export const UNDO_MS = 5000;

interface Entry {
  label: string;
  run: () => Promise<unknown>;
  timer?: ReturnType<typeof setTimeout>;
  /** waiting: can still be taken back; sent: told to the server (or on its way), gone from the list. */
  state: 'waiting' | 'sent';
}

/**
 * Answers the server hears a few seconds after they are given, so a wrong click costs nothing: until then the row
 * shows what was done with 撤销, and taking it back sends no request. Whatever is still waiting when the page is
 * left (or closed) is sent at once. The answers go one after another, and ``settle`` (loading the page again) runs
 * once the last one is told, not between them, so a run of many answers does not load the heaviest view each time.
 */
export function useDeferred({
  settle,
  delay = UNDO_MS,
}: {
  settle: () => Promise<unknown>;
  delay?: number;
}) {
  const entries = useRef(new Map<string, Entry>());
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const settling = useRef(settle);
  const [, setTick] = useState(0);
  const changed = () => setTick((tick) => tick + 1);
  useEffect(() => {
    settling.current = settle;
  }, [settle]);

  // How many answers are on their way: loading again waits for them all.
  const inflight = useRef(0);
  const finish = useCallback(async () => {
    if (inflight.current > 0) return;
    const left = [...entries.current.entries()];
    if (left.some(([, entry]) => entry.state === 'waiting')) return;
    const sent = left.map(([id]) => id);
    if (!sent.length) return;
    try {
      await settling.current();
    } finally {
      for (const id of sent) entries.current.delete(id);
      changed();
    }
  }, []);

  const send = useCallback(
    (id: string) => {
      const entry = entries.current.get(id);
      if (!entry || entry.state !== 'waiting') return;
      clearTimeout(entry.timer);
      entry.state = 'sent';
      inflight.current += 1;
      changed();
      chain.current = chain.current
        .then(() => entry.run())
        .catch(() => {})
        .then(() => {
          inflight.current -= 1;
          return finish();
        })
        // A failed reload must not hold back the answers still to come.
        .catch(() => {});
    },
    [finish],
  );

  /** Settle ``id`` as ``label`` and tell the server in a few seconds, unless taken back. */
  const defer = useCallback(
    (id: string, label: string, run: () => Promise<unknown>) => {
      if (entries.current.has(id)) return;
      entries.current.set(id, {
        label,
        run,
        state: 'waiting',
        timer: setTimeout(() => send(id), delay),
      });
      changed();
    },
    [delay, send],
  );

  const undo = useCallback((id: string) => {
    const entry = entries.current.get(id);
    if (!entry || entry.state !== 'waiting') return;
    clearTimeout(entry.timer);
    entries.current.delete(id);
    changed();
  }, []);

  /** Tell the server everything still waiting, now. */
  const flush = useCallback(() => {
    for (const [id, entry] of [...entries.current])
      if (entry.state === 'waiting') send(id);
  }, [send]);

  useEffect(() => {
    window.addEventListener('pagehide', flush);
    return () => {
      window.removeEventListener('pagehide', flush);
      flush();
    };
  }, [flush]);

  const all = [...entries.current.entries()];
  return {
    defer,
    undo,
    flush,
    /** Rows settled and not yet told, newest last, each with what was done. */
    waiting: all
      .filter(([, entry]) => entry.state === 'waiting')
      .map(([id, entry]) => ({ id, label: entry.label })),
    /** Everything settled this way and not yet gone from what the server lists. */
    has: (id: string) => entries.current.has(id),
    held: (id: string) => entries.current.get(id)?.state === 'waiting',
    labelOf: (id: string) => entries.current.get(id)?.label ?? '',
    count: entries.current.size,
  };
}
