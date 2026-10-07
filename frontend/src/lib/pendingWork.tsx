import {
  createContext,
  useCallback,
  useContext,
  useId,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

interface Work {
  id: string;
  step: string;
  label: string;
  background: boolean;
  released: boolean;
}
const PendingContext = createContext<{
  work: Work[];
  update: (
    id: string,
    step: string,
    label: string,
    background: boolean,
  ) => void;
  remove: (id: string) => void;
  release: (id: string) => void;
} | null>(null);
const StepContext = createContext('');

export function PendingWorkProvider({ children }: { children: ReactNode }) {
  const [work, setWork] = useState<Work[]>([]);
  const update = useCallback(
    (id: string, step: string, label: string, background: boolean) => {
      setWork((items) => {
        const previous = items.find((item) => item.id === id);
        if (
          previous?.step === step &&
          previous.label === label &&
          previous.background === background
        )
          return items;
        const next = {
          id,
          step,
          label,
          background,
          released:
            background && previous?.background && previous.step === step
              ? previous.released
              : false,
        };
        return previous
          ? items.map((item) => (item.id === id ? next : item))
          : [...items, next];
      });
    },
    [],
  );
  const remove = useCallback((id: string) => {
    setWork((items) =>
      items.some((item) => item.id === id)
        ? items.filter((item) => item.id !== id)
        : items,
    );
  }, []);
  const release = useCallback((id: string) => {
    setWork((items) =>
      items.map((item) =>
        item.id === id && item.background ? { ...item, released: true } : item,
      ),
    );
  }, []);
  const value = useMemo(
    () => ({ work, update, remove, release }),
    [work, update, remove, release],
  );
  return (
    <PendingContext.Provider value={value}>{children}</PendingContext.Provider>
  );
}

export function PendingStep({
  step,
  children,
}: {
  step: string;
  children: ReactNode;
}) {
  return <StepContext.Provider value={step}>{children}</StepContext.Provider>;
}

export function usePendingWork(
  busy: boolean,
  label: string,
  background = false,
) {
  const id = useId();
  const step = useContext(StepContext);
  const context = useContext(PendingContext);
  const update = context?.update;
  const remove = context?.remove;
  useLayoutEffect(() => {
    if (busy) update?.(id, step, label, background);
    else remove?.(id);
  }, [busy, id, step, label, background, update, remove]);
  useLayoutEffect(() => () => remove?.(id), [id, remove]);
}

export function useFlowPending(currentStep?: string) {
  const scope = useContext(StepContext);
  const context = useContext(PendingContext);
  const pending =
    context?.work.filter(
      (item) => item.step === (currentStep ?? scope) && !item.released,
    ) ?? [];
  const foreground = pending.find((item) => !item.background);
  const job = pending.find((item) => item.background);
  return {
    locked: pending.length > 0,
    label: (foreground ?? job)?.label ?? '',
    // Never offer an escape while bytes or a save request are still in flight.
    backgroundJob: foreground ? undefined : job,
    release: () => {
      if (!foreground && job) context?.release(job.id);
    },
  };
}
