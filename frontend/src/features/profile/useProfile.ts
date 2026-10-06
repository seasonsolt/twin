import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../lib/api';
import { toast } from '../../components/ui';
import { useStatus } from '../../stores/status';
import type { Coverage, ProfileItem, ReviewStatus } from './types';

export function useProfile(active: boolean) {
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [items, setItems] = useState<ProfileItem[]>([]);
  const [coverageError, setCoverageError] = useState('');
  const [itemsError, setItemsError] = useState('');
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<Set<string>>(new Set());
  const alive = useRef(false);
  const coverageRequest = useRef<AbortController | null>(null);
  const itemsRequest = useRef<AbortController | null>(null);
  const mutations = useRef(new Set<AbortController>());
  const optimistic = useRef(new Map<string, ProfileItem>());
  const refreshCoverage = useCallback(async () => {
    if (!alive.current) return;
    coverageRequest.current?.abort();
    const request = new AbortController();
    coverageRequest.current = request;
    try {
      const report = await api<Coverage>('/api/persona/coverage', {
        signal: request.signal,
      });
      if (!request.signal.aborted && alive.current) {
        setCoverage(report);
        setCoverageError('');
      }
    } catch (failure) {
      if (!request.signal.aborted && alive.current)
        setCoverageError(
          failure instanceof Error ? failure.message : '建议加载失败',
        );
    }
  }, []);
  const latestCoverageRefresh = useRef(refreshCoverage);
  useEffect(() => {
    latestCoverageRefresh.current = refreshCoverage;
  }, [refreshCoverage]);
  const refreshItems = useCallback(async () => {
    if (!alive.current) return;
    itemsRequest.current?.abort();
    const request = new AbortController();
    itemsRequest.current = request;
    setLoading(true);
    try {
      const rows = await api<ProfileItem[]>(
        '/api/persona/items?include_rejected=false',
        { signal: request.signal },
      );
      if (!request.signal.aborted && alive.current) {
        const merged = rows.map(
          (item) => optimistic.current.get(item.item_id) ?? item,
        );
        for (const [id, item] of optimistic.current)
          if (!merged.some((row) => row.item_id === id)) merged.push(item);
        setItems(merged);
        setItemsError('');
      }
    } catch (failure) {
      if (!request.signal.aborted && alive.current)
        setItemsError(
          failure instanceof Error ? failure.message : '条目加载失败',
        );
    } finally {
      if (!request.signal.aborted && alive.current) setLoading(false);
    }
  }, []);
  const latestItemsRefresh = useRef(refreshItems);
  useEffect(() => {
    latestItemsRefresh.current = refreshItems;
  }, [refreshItems]);
  useEffect(() => {
    alive.current = active;
    const requests = mutations.current;
    return () => {
      alive.current = false;
      coverageRequest.current?.abort();
      itemsRequest.current?.abort();
      requests.forEach((request) => request.abort());
    };
  }, [active]);
  useEffect(() => {
    if (active) void refreshCoverage();
    return () => coverageRequest.current?.abort();
  }, [active, refreshCoverage]);
  useEffect(() => {
    if (active) void refreshItems();
    return () => itemsRequest.current?.abort();
  }, [active, refreshItems]);
  const review = async (
    item: ProfileItem,
    status: ReviewStatus,
    statement?: string,
  ) => {
    if (!alive.current || optimistic.current.has(item.item_id)) return false;
    const request = new AbortController();
    mutations.current.add(request);
    const extracted = item.extracted_statement || item.statement;
    const updated: ProfileItem = {
      ...item,
      review: status,
      statement: status === 'edited' ? statement! : extracted,
      extracted_statement: status === 'edited' ? extracted : '',
    };
    optimistic.current.set(item.item_id, updated);
    setPending(new Set(optimistic.current.keys()));
    setItems((rows) =>
      rows.map((row) => (row.item_id === item.item_id ? updated : row)),
    );
    try {
      const saved = await api<ProfileItem>(
        `/api/persona/items/${encodeURIComponent(item.item_id)}/review`,
        {
          method: 'POST',
          json: { status, statement: statement ?? null, note: '' },
          signal: request.signal,
        },
      );
      if (request.signal.aborted || !alive.current) return false;
      optimistic.current.set(item.item_id, saved);
      setItems((rows) =>
        rows.map((row) => (row.item_id === item.item_id ? saved : row)),
      );
      void latestItemsRefresh.current();
      toast('审核已保存', 'success');
      void latestCoverageRefresh.current();
      await useStatus.getState().refresh(request.signal);
      return !request.signal.aborted && alive.current;
    } catch (failure) {
      if (!request.signal.aborted && alive.current) {
        itemsRequest.current?.abort();
        setLoading(false);
        setItems((rows) =>
          rows.some((row) => row.item_id === item.item_id)
            ? rows.map((row) => (row.item_id === item.item_id ? item : row))
            : [...rows, item],
        );
        void latestItemsRefresh.current();
        toast(
          failure instanceof Error ? failure.message : '审核失败，已恢复原条目',
          'danger',
        );
      }
      return false;
    } finally {
      mutations.current.delete(request);
      optimistic.current.delete(item.item_id);
      if (!request.signal.aborted && alive.current)
        setPending(new Set(optimistic.current.keys()));
    }
  };
  return {
    coverage,
    items,
    coverageError,
    itemsError,
    loading,
    pending,
    refreshCoverage,
    refreshItems,
    review,
  };
}
