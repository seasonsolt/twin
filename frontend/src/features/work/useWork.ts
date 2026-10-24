import { useCallback, useEffect } from 'react';
import { api, ApiError } from '../../lib/api';
import {
  usePersonaId,
  usePersonaState as useState,
} from '../../lib/usePersonaState';
import { toast, useConfirm } from '../../components/ui';
import type { WorkStarted, WorkSummary, WorkTask } from './types';

const POLL_MS = 1500;

/**
 * The tasks given to the twin in view: the list, the one open, and what sending, stopping and deleting do. Nothing is
 * asked of the server until ``enabled`` (work switched on for the person).
 */
export function useWork(enabled: boolean) {
  const personaId = usePersonaId();
  const confirm = useConfirm();
  const [tasks, setTasks] = useState<WorkSummary[] | null>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [task, setTask] = useState<WorkTask | null>(null);
  // Why the task opened could not be read (shown where it should be), and a count that asks for it again.
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);

  const loadTasks = useCallback(async () => {
    try {
      const data = await api<{ tasks: WorkSummary[] }>('/api/persona/work');
      setTasks(data.tasks);
    } catch {
      // The list of the page asks the index and says if it cannot; this one only tells it when to ask again.
    }
  }, [setTasks]);

  const loadTask = useCallback(
    async (taskId: string) => {
      const data = await api<WorkTask>(
        `/api/persona/work/${encodeURIComponent(taskId)}`,
      );
      setTask(data);
      return data;
    },
    [setTask],
  );

  useEffect(() => {
    if (enabled) void loadTasks();
  }, [enabled, loadTasks, personaId]);

  useEffect(() => {
    setError('');
    if (current === null) {
      setTask(null);
      return;
    }
    // Another task than the one on screen: not shown while this one is read.
    setTask((shown) => (shown?.task_id === current ? shown : null));
    void loadTask(current).catch((failure: unknown) => {
      if (failure instanceof ApiError && failure.status === 404) {
        // Deleted meanwhile (from another page or another device): back to a new task, not an endless wait.
        setCurrent(null);
        toast('找不到这个任务，可能已被删除', 'danger');
        void loadTasks();
        return;
      }
      setError(failure instanceof Error ? failure.message : '加载失败');
    });
  }, [current, attempt, loadTask, loadTasks, setCurrent, setTask, setError]);

  const running = task?.status === 'running';
  const taskId = task?.task_id;
  useEffect(() => {
    if (!enabled || !running || !taskId) return;
    const timer = window.setInterval(() => {
      void loadTask(taskId)
        .then((next) => {
          if (next.status !== 'running') void loadTasks();
        })
        .catch(() => undefined);
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [enabled, running, taskId, loadTask, loadTasks]);

  /** Whether the message went: a new task, a follow-up, or a word to the turn in flight. */
  const send = async () => {
    const text = draft.trim();
    if (!text || sending) return false;
    setSending(true);
    try {
      const started = await api<WorkStarted>('/api/persona/work', {
        method: 'POST',
        json: { text, ...(current ? { task_id: current } : {}) },
      });
      setDraft('');
      setCurrent(started.task.task_id);
      await loadTask(started.task.task_id);
      await loadTasks();
      return true;
    } catch (failure) {
      toast(failure instanceof Error ? failure.message : '发送失败', 'danger');
      return false;
    } finally {
      setSending(false);
    }
  };

  const stop = async () => {
    if (!taskId) return;
    try {
      await api(`/api/persona/work/${encodeURIComponent(taskId)}/stop`, {
        method: 'POST',
      });
      await loadTask(taskId);
    } catch (failure) {
      toast(failure instanceof Error ? failure.message : '没能停下', 'danger');
    }
  };

  const remove = async (row: Pick<WorkSummary, 'task_id' | 'title'>) => {
    const ok = await confirm({
      title: '删除任务？',
      body: `“${row.title}”和做出来的文件都会删掉，不能恢复。`,
      confirmLabel: '删除',
      tone: 'danger',
    });
    if (!ok) return;
    try {
      await api(`/api/persona/work/${encodeURIComponent(row.task_id)}`, {
        method: 'DELETE',
      });
      if (row.task_id === current) setCurrent(null);
      await loadTasks();
    } catch (failure) {
      toast(failure instanceof Error ? failure.message : '删除失败', 'danger');
    }
  };

  return {
    tasks,
    current,
    setCurrent,
    task,
    error,
    draft,
    setDraft,
    sending,
    running,
    send,
    stop,
    remove,
    reload: loadTasks,
    /** Read the open task again after it could not be. */
    retry: () => setAttempt((count) => count + 1),
  };
}

export type Work = ReturnType<typeof useWork>;
