import {
  useCallback,
  useState,
  useSyncExternalStore,
  type Dispatch,
  type SetStateAction,
} from 'react';
import { usePersonas } from '../stores/personas';
import { getPersonaId } from './persona';

export function usePersonaId() {
  return useSyncExternalStore(
    usePersonas.subscribe,
    getPersonaId,
    getPersonaId,
  );
}

// Reset only persona-owned state, never the page or its layout. Setters from
// an old render cannot publish into a different persona's view.
export function usePersonaState<T>(
  initial: T | (() => T),
): [T, Dispatch<SetStateAction<T>>] {
  const persona = usePersonaId();
  const initialize = () =>
    typeof initial === 'function' ? (initial as () => T)() : initial;
  const [scoped, setScoped] = useState(() => ({
    persona,
    value: initialize(),
  }));
  let value = scoped.value;
  if (scoped.persona !== persona) {
    value = initialize();
    setScoped({ persona, value });
  }
  const update = useCallback<Dispatch<SetStateAction<T>>>(
    (next) => {
      if (getPersonaId() !== persona) return;
      setScoped((previous) => {
        if (previous.persona !== persona) return previous;
        return {
          persona,
          value:
            typeof next === 'function'
              ? (next as (value: T) => T)(previous.value)
              : next,
        };
      });
    },
    [persona],
  );
  return [value, update];
}
