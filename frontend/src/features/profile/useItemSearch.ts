import { useCallback, useEffect, useRef } from 'react';
import {
  usePersonaId,
  usePersonaState as useState,
} from '../../lib/usePersonaState';
import { api } from '../../lib/api';
import type { ItemPage, ProfileItem } from './types';

const DEBOUNCE_MS = 300;

/** The items closest to `text` by meaning and keywords, best first, as the twin's own retrieval finds them: the way
 * to find what the twin remembers about something and correct it. An empty `text` reads nothing. */
export function useItemSearch(text: string) {
  const personaId = usePersonaId();
  const query = text.trim();
  const [items, setItems] = useState<ProfileItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const request = useRef<AbortController | null>(null);
  const read = useCallback(async () => {
    request.current?.abort();
    if (!query) return;
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    try {
      const page = await api<ItemPage>(
        `/api/persona/items/search?${new URLSearchParams({ q: query })}`,
        {
          signal: controller.signal,
          headers: { 'X-Twin-Persona': personaId },
        },
      );
      if (controller.signal.aborted) return;
      setItems(page.items);
      setError('');
    } catch (failure) {
      if (!controller.signal.aborted)
        setError(failure instanceof Error ? failure.message : '搜索失败');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [query, personaId, setItems, setLoading, setError]);
  useEffect(() => {
    request.current?.abort();
    setError('');
    if (!query) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const timer = setTimeout(() => void read(), DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      request.current?.abort();
    };
  }, [query, read, setItems, setLoading, setError]);
  /** Show a reviewed item in place; a rejected one leaves the results. */
  const replace = useCallback(
    (item: ProfileItem) =>
      setItems((rows) =>
        item.review === 'rejected'
          ? rows.filter((row) => row.item_id !== item.item_id)
          : rows.map((row) => (row.item_id === item.item_id ? item : row)),
      ),
    [setItems],
  );
  return { query, items, loading, error, reload: read, replace };
}
