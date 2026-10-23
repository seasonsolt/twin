import { useCallback, useEffect, useRef } from 'react';
import {
  usePersonaId,
  usePersonaState as useState,
} from '../../lib/usePersonaState';
import { api } from '../../lib/api';
import { toast } from '../../components/ui';
import { useSeesWhole } from '../../stores/access';
import { usePersonas } from '../../stores/personas';
import { useStatus } from '../../stores/status';
import type {
  Coverage,
  ItemSummary,
  ProfileItem,
  ReviewStatus,
  Tier,
} from './types';

/** The list showing a reviewed item: it shows the change at once and re-reads itself if saving fails. */
export interface ReviewedList {
  replace: (item: ProfileItem) => void;
  reload: () => Promise<void>;
}

const savedMessages: Record<ReviewStatus, string> = {
  edited: '改好了，之后按这条回答',
  rejected: '删掉了，之后不会再用它',
  unreviewed: '恢复成原来的说法',
  confirmed: '已保存',
};

/** Profile counts and suggestions, and the reviews that change them. Items themselves are read a page at a
 * time with `usePagedItems`, so a profile with tens of thousands of items never loads them all. */
export function useProfile(active: boolean) {
  const personaId = usePersonaId();
  // Only the person behind the twin, who sees all its memories, says who may use each one.
  const canTier = useSeesWhole(
    usePersonas((state) => state.items.find((item) => item.id === personaId)),
  );
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [summary, setSummary] = useState<ItemSummary | null>(null);
  const [coverageError, setCoverageError] = useState('');
  const [summaryError, setSummaryError] = useState('');
  const [pending, setPending] = useState<Set<string>>(new Set());
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
    if (!alive.current || reviewing.current.has(item.item_id)) return false;
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
      toast(savedMessages[status], 'success');
      await afterChange(request.signal);
      return !request.signal.aborted && alive.current;
    } catch (failure) {
      if (!request.signal.aborted && alive.current) {
        list.replace(item);
        void list.reload();
        toast(
          failure instanceof Error ? failure.message : '没有保存，已恢复原条目',
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
  /** Say who may use a memory; the list shows it at once and goes back if saving fails. */
  const tier = async (item: ProfileItem, next: Tier, list: ReviewedList) => {
    if (!alive.current || reviewing.current.has(item.item_id)) return false;
    const request = new AbortController();
    const started = reviewing.current;
    mutations.current.add(request);
    started.add(item.item_id);
    setPending(new Set(started));
    list.replace({ ...item, tier: next, tier_changed: true });
    try {
      const saved = await api<ProfileItem>(
        `/api/persona/items/${encodeURIComponent(item.item_id)}/tier`,
        {
          method: 'PUT',
          json: { tier: next },
          signal: request.signal,
          headers: { 'X-Twin-Persona': personaId },
        },
      );
      if (request.signal.aborted || !alive.current) return false;
      list.replace(saved);
      toast(
        next === 'self'
          ? '之后只有你自己的对话会用它'
          : '之后同事问到时也会用它',
        'success',
      );
      return true;
    } catch (failure) {
      if (!request.signal.aborted && alive.current) {
        list.replace(item);
        void list.reload();
        toast(
          failure instanceof Error ? failure.message : '没有保存，已恢复原条目',
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
  return {
    coverage,
    summary,
    coverageError,
    summaryError,
    loading: summary === null && !summaryError,
    pending,
    refreshCoverage,
    refreshSummary,
    review,
    tier,
    canTier,
  };
}
