import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../lib/api';
import { toast } from '../../components/ui';
import { useStatus } from '../../stores/status';
import type { ImportResult, Source, SourceKind } from './types';

export function useSources(active: boolean) {
  const [sources, setSources] = useState<Source[]>([]);
  const [stale, setStale] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [importError, setImportError] = useState('');
  const [result, setResult] = useState<ImportResult | null>(null);
  const alive = useRef(false);
  const reloadRequest = useRef<AbortController | null>(null);
  const mutations = useRef(new Set<AbortController>());
  const removing = useRef(new Set<string>());
  const reload = useCallback(async () => {
    if (!alive.current) return;
    reloadRequest.current?.abort();
    const request = new AbortController();
    reloadRequest.current = request;
    try {
      const [rows, memory] = await Promise.all([
        api<Source[]>('/api/persona/sources', { signal: request.signal }),
        api<{ stale: boolean }>('/api/persona/state', {
          signal: request.signal,
        }),
      ]);
      if (!request.signal.aborted && alive.current) {
        setSources(rows.filter((row) => !removing.current.has(row.source_id)));
        setStale(memory.stale);
        setError('');
      }
    } catch (failure) {
      if (!request.signal.aborted && alive.current)
        setError(failure instanceof Error ? failure.message : '资料加载失败');
    } finally {
      if (!request.signal.aborted && alive.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    alive.current = active;
    if (active) void reload();
    const requests = mutations.current;
    return () => {
      alive.current = false;
      reloadRequest.current?.abort();
      requests.forEach((request) => request.abort());
    };
  }, [active, reload]);
  const refreshStatus = (signal: AbortSignal) =>
    useStatus.getState().refresh(signal);
  const upload = async (files: File[], kind: SourceKind, date: string) => {
    if (!alive.current || uploading) return false;
    const request = new AbortController();
    mutations.current.add(request);
    const form = new FormData();
    files.forEach((file) => form.append('files', file, file.name));
    setUploading(true);
    setImportError('');
    setResult(null);
    try {
      const imported = await api<ImportResult>(
        `/api/persona/import?${new URLSearchParams({ kind, date })}`,
        {
          method: 'POST',
          form,
          signal: request.signal,
        },
      );
      if (request.signal.aborted || !alive.current) return false;
      setResult(imported);
      toast(
        `已导入或更新 ${imported.imported.length} 份资料${imported.skipped.length ? `，跳过 ${imported.skipped.length} 份` : ''}`,
        imported.skipped.length ? 'warning' : 'success',
      );
      void reload();
      await refreshStatus(request.signal);
      return !request.signal.aborted && alive.current;
    } catch (failure) {
      if (!request.signal.aborted && alive.current) {
        const message = failure instanceof Error ? failure.message : '导入失败';
        setImportError(message);
        toast(message, 'danger');
      }
      return false;
    } finally {
      mutations.current.delete(request);
      if (!request.signal.aborted && alive.current) setUploading(false);
    }
  };
  const remove = async (source: Source) => {
    if (!alive.current || removing.current.has(source.source_id)) return;
    const request = new AbortController();
    mutations.current.add(request);
    removing.current.add(source.source_id);
    reloadRequest.current?.abort();
    const index = sources.findIndex(
      (row) => row.source_id === source.source_id,
    );
    setSources((rows) =>
      rows.filter((row) => row.source_id !== source.source_id),
    );
    try {
      await api(
        `/api/persona/sources/${encodeURIComponent(source.source_id)}`,
        { method: 'DELETE', signal: request.signal },
      );
      if (request.signal.aborted || !alive.current) return;
      toast('资料已删除，下次构建时生效', 'success');
      await refreshStatus(request.signal);
    } catch (failure) {
      if (!request.signal.aborted && alive.current) {
        setSources((rows) =>
          rows.some((row) => row.source_id === source.source_id)
            ? rows
            : [...rows.slice(0, index), source, ...rows.slice(index)],
        );
        toast(
          failure instanceof Error ? failure.message : '删除失败，资料已恢复',
          'danger',
        );
      }
    } finally {
      mutations.current.delete(request);
      removing.current.delete(source.source_id);
      if (!request.signal.aborted && alive.current) void reload();
    }
  };
  return {
    sources,
    stale,
    loading,
    error,
    uploading,
    importError,
    result,
    reload,
    upload,
    remove,
  };
}
