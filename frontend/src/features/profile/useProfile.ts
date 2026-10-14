import { useCallback, useEffect, useRef } from 'react';
import {
  usePersonaId,
  usePersonaState as useState,
} from '../../lib/usePersonaState';
import { api } from '../../lib/api';
import { getPersonaId } from '../../lib/persona';
import { toast } from '../../components/ui';
import { useStatus } from '../../stores/status';
import type { Coverage, ItemSummary, ProfileItem, ReviewStatus } from './types';

/** The list showing a reviewed item: it shows the change at once and re-reads itself if saving fails. */
export interface ReviewedList {
  replace: (item: ProfileItem) => void;
  reload: () => Promise<void>;
}

/** Profile counts and suggestions, and the reviews that change them. Items themselves are read a page at a
 * time with `usePagedItems`, so a profile with tens of thousands of items never loads them all. */
export function useProfile(active: boolean) {
  const personaId = usePersonaId();
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [summary, setSummary] = useState<ItemSummary | null>(null);
  const [coverageError, setCoverageError] = useState('');
  const [summaryError, setSummaryError] = useState('');
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [batchBusy, setBatchBusy] = useState(false);
  const batchRequest = useRef<AbortController | null>(null);
  const alive = useRef(false);
  const coverageRequest = useRef<AbortController | null>(null);
  const summaryRequest = useRef<AbortController | null>(null);
  const mutations = useRef(new Set<AbortController>());
  const reviewing = useRef(new Set<string>());
  const refreshCoverage = useCallback(async () => {
    if (!alive.current) return;
    coverageRequest.current?.abort();
    const request = new AbortController();
    coverageRequest.current = request;
    try {
      const report = await api<Coverage>('/api/persona/coverage', {
        signal: request.signal,
        headers: { 'X-Twin-Persona': personaId },
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
  }, [personaId, setCoverage, setCoverageError]);
  const refreshSummary = useCallback(async () => {
    if (!alive.current) return;
    summaryRequest.current?.abort();
    const request = new AbortController();
    summaryRequest.current = request;
    try {
      const counts = await api<ItemSummary>('/api/persona/items/summary', {
        signal: request.signal,
        headers: { 'X-Twin-Persona': personaId },
      });
      if (!request.signal.aborted && alive.current) {
        setSummary(counts);
        setSummaryError('');
      }
    } catch (failure) {
      if (!request.signal.aborted && alive.current)
        setSummaryError(
          failure instanceof Error ? failure.message : '条目加载失败',
        );
    }
  }, [personaId, setSummary, setSummaryError]);
  const latest = useRef({ refreshCoverage, refreshSummary });
  useEffect(() => {
    latest.current = { refreshCoverage, refreshSummary };
  }, [refreshCoverage, refreshSummary]);
  useEffect(() => {
    alive.current = active;
    reviewing.current = new Set();
    const requests = mutations.current;
    return () => {
      alive.current = false;
      coverageRequest.current?.abort();
      summaryRequest.current?.abort();
      requests.forEach((request) => request.abort());
    };
  }, [active, personaId]);
  useEffect(() => {
    if (active) {
      void refreshCoverage();
      void refreshSummary();
    }
  }, [active, refreshCoverage, refreshSummary]);
  const afterChange = async (signal: AbortSignal) => {
    void latest.current.refreshSummary();
    void latest.current.refreshCoverage();
    await useStatus.getState().refresh(signal);
  };
  const review = async (
    item: ProfileItem,
    status: ReviewStatus,
    statement: string | undefined,
    list: ReviewedList,
  ) => {
    if (
      !alive.current ||
      reviewing.current.has(item.item_id) ||
      (batchRequest.current && !batchRequest.current.signal.aborted)
    )
      return false;
    const request = new AbortController();
    const started = reviewing.current;
    mutations.current.add(request);
    started.add(item.item_id);
    setPending(new Set(started));
    const extracted = item.extracted_statement || item.statement;
    // A rejected item leaves the list only once the rejection is saved.
    if (status !== 'rejected')
      list.replace({
        ...item,
        review: status,
        statement: status === 'edited' ? statement! : extracted,
        extracted_statement: status === 'edited' ? extracted : '',
      });
    try {
      const saved = await api<ProfileItem>(
        `/api/persona/items/${encodeURIComponent(item.item_id)}/review`,
        {
          method: 'POST',
          json: { status, statement: statement ?? null, note: '' },
          signal: request.signal,
          headers: { 'X-Twin-Persona': personaId },
        },
      );
      if (request.signal.aborted || !alive.current) return false;
      list.replace(saved);
      toast('审核已保存', 'success');
      await afterChange(request.signal);
      return !request.signal.aborted && alive.current;
    } catch (failure) {
      if (!request.signal.aborted && alive.current) {
        list.replace(item);
        void list.reload();
        toast(
          failure instanceof Error ? failure.message : '审核失败，已恢复原条目',
          'danger',
        );
      }
      return false;
    } finally {
      mutations.current.delete(request);
      started.delete(item.item_id);
      if (!request.signal.aborted && alive.current)
        setPending(new Set(started));
    }
  };
  /** Confirm every unreviewed item of a dimension on the server, however many there are. */
  const confirmDimension = async (dimensionId: string) => {
    if (
      !alive.current ||
      getPersonaId() !== personaId ||
      reviewing.current.size > 0 ||
      (batchRequest.current && !batchRequest.current.signal.aborted)
    )
      return false;
    const request = new AbortController();
    batchRequest.current = request;
    mutations.current.add(request);
    setBatchBusy(true);
    try {
      const saved = await api<{ updated: number }>(
        '/api/persona/items/review-batch',
        {
          method: 'POST',
          json: { dimension_id: dimensionId, status: 'confirmed' },
          signal: request.signal,
          headers: { 'X-Twin-Persona': personaId },
        },
      );
      if (request.signal.aborted || !alive.current) return false;
      toast(`已确认 ${saved.updated} 条`, 'success');
      await afterChange(request.signal);
      return !request.signal.aborted && alive.current;
    } catch (failure) {
      if (!request.signal.aborted && alive.current)
        toast(
          failure instanceof Error ? failure.message : '审核失败，请重试',
          'danger',
        );
      return false;
    } finally {
      mutations.current.delete(request);
      if (batchRequest.current === request) batchRequest.current = null;
      if (!request.signal.aborted && alive.current) setBatchBusy(false);
    }
  };
  return {
    coverage,
    summary,
    coverageError,
    summaryError,
    loading: summary === null && !summaryError,
    pending,
    batchBusy,
    confirmDimension,
    refreshCoverage,
    refreshSummary,
    review,
  };
}
