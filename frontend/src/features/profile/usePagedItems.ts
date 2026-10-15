import { useCallback, useEffect, useRef } from 'react';
import {
  usePersonaId,
  usePersonaState as useState,
} from '../../lib/usePersonaState';
import { api } from '../../lib/api';
import type { ItemPage, ItemQuery, ItemSource, ProfileItem } from './types';

export const ITEM_PAGE_SIZE = 20;
// The server's largest page; a reload of a long list re-reads at most this many rows.
export const MAX_ITEM_PAGE = 500;

export function itemsUrl(query: ItemQuery, limit: number, offset = 0) {
  const params = new URLSearchParams();
  query.dimension?.forEach((id) => params.append('dimension', id));
  if (query.review) params.set('review', query.review);
  if (query.q?.trim()) params.set('q', query.q.trim());
  if (query.source_id) params.set('source_id', query.source_id);
  if (query.sort) params.set('sort', query.sort);
  if (query.with_sources) params.set('with_sources', 'true');
  params.set('limit', String(limit));
  if (offset) params.set('offset', String(offset));
  return `/api/persona/items?${params}`;
}

/** Profile items matching `query`, read a page at a time; `null` reads nothing. */
export function usePagedItems(
  query: ItemQuery | null,
  pageSize = ITEM_PAGE_SIZE,
) {
  const personaId = usePersonaId();
  const key = query ? JSON.stringify(query) : null;
  const [items, setItems] = useState<ProfileItem[]>([]);
  const [sources, setSources] = useState<Record<string, ItemSource>>({});
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(query !== null);
  const [error, setError] = useState('');
  const request = useRef<AbortController | null>(null);
  const loaded = useRef(0);
  const read = useCallback(
    async (offset: number, limit: number) => {
      if (key === null) return;
      request.current?.abort();
      const controller = new AbortController();
      request.current = controller;
      setLoading(true);
      try {
        const page = await api<ItemPage>(
          itemsUrl(JSON.parse(key) as ItemQuery, limit, offset),
          {
            signal: controller.signal,
            headers: { 'X-Twin-Persona': personaId },
          },
        );
        if (controller.signal.aborted) return;
        setItems((rows) => {
          const kept = offset ? rows.slice(0, offset) : [];
          const seen = new Set(kept.map((row) => row.item_id));
          return [
            ...kept,
            ...page.items.filter((row) => !seen.has(row.item_id)),
          ];
        });
        setSources((known) =>
          offset ? { ...known, ...page.sources } : (page.sources ?? {}),
        );
        setTotal(page.total);
        setError('');
      } catch (failure) {
        if (!controller.signal.aborted)
          setError(failure instanceof Error ? failure.message : '条目加载失败');
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    },
    [key, personaId, setItems, setSources, setTotal, setLoading, setError],
  );
  useEffect(() => {
    loaded.current = items.length;
  }, [items]);
  useEffect(() => {
    loaded.current = 0;
    setItems([]);
    setSources({});
    setTotal(0);
    setError('');
    if (key === null) setLoading(false);
    else void read(0, pageSize);
    return () => request.current?.abort();
  }, [
    key,
    pageSize,
    read,
    setItems,
    setSources,
    setTotal,
    setError,
    setLoading,
  ]);
  const loadMore = useCallback(() => {
    if (!loading) void read(loaded.current, pageSize);
  }, [read, pageSize, loading]);
  /** Re-read the rows already shown (at least one page), after a change elsewhere. */
  const reload = useCallback(
    () => read(0, Math.min(MAX_ITEM_PAGE, Math.max(pageSize, loaded.current))),
    [read, pageSize],
  );
  /** Show a reviewed item of this list in place; a rejected one leaves it. */
  const replace = useCallback(
    (item: ProfileItem) => {
      if (item.review === 'rejected') {
        setItems((rows) => rows.filter((row) => row.item_id !== item.item_id));
        setTotal((count) => Math.max(0, count - 1));
        return;
      }
      setItems((rows) =>
        rows.map((row) => (row.item_id === item.item_id ? item : row)),
      );
    },
    [setItems, setTotal],
  );
  return {
    items,
    sources,
    total,
    loading,
    error,
    hasMore: items.length < total,
    loadMore,
    reload,
    replace,
  };
}
