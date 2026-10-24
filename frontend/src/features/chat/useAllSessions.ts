import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../lib/api';

/** A conversation of the signed-in person with some twin, as the team's index lists it. */
export interface AllConversation {
  id: string;
  persona_id: string;
  title: string;
  /** What was last said, for finding it. */
  preview?: string;
  updated_at: string;
  via: 'direct' | 'delegate';
  /** Where what it handed to the person stands, such as 等本人回复; nothing when it handed nothing. */
  handoff: string | null;
  /** In the person's own conversation with their assistant: how many colleagues' twins it asked (代问). */
  delegated?: number;
}

export interface AllTask {
  task_id: string;
  persona_id: string;
  title: string;
  status: 'idle' | 'running' | 'failed';
  updated_at: string;
}

/** The person's own twin, and how many of what colleagues asked it wait for them to decide. */
export interface OwnTwin {
  persona_id: string | null;
  pending: number;
}

interface Everyone {
  mine: OwnTwin | null;
  conversations: AllConversation[];
  tasks: AllTask[];
  more: boolean;
  /** Where the next page of conversations begins (what the first page adds apart is not counted). */
  next: number;
  moreTasks: boolean;
}

/** What the server sends: the same, with the tasks' own "more" under its wire name. */
type Reply = Partial<Omit<Everyone, 'moreTasks'>> & { more_tasks?: boolean };

/** Which of them the list is of: everyone's, one twin's (``with``), or the person's own with their own twin. */
export interface SessionScope {
  mine?: boolean;
  with?: string;
}

const query = (scope: SessionScope, offset: number, taskOffset: number) => {
  const params = new URLSearchParams();
  if (offset) params.set('offset', String(offset));
  if (taskOffset) params.set('task_offset', String(taskOffset));
  if (scope.mine) params.set('mine', 'true');
  if (scope.with) params.set('with', scope.with);
  const text = params.toString();
  return `/api/personas/conversations${text ? `?${text}` : ''}`;
};

/**
 * Every conversation and task of the signed-in person across the twins, from the team's index: one request, not one per
 * twin. Asked again when ``scope`` or ``revision`` changes (a conversation was written, renamed or deleted).
 */
export function useAllSessions(
  enabled: boolean,
  scope: SessionScope,
  revision: unknown,
) {
  const [data, setData] = useState<Everyone | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const request = useRef<AbortController | null>(null);
  const { mine, with: only } = scope;
  // ``offset``: the next conversations; ``taskOffset``: the next tasks, which come without conversations.
  const load = useCallback(
    async (offset = 0, taskOffset = 0) => {
      request.current?.abort();
      const controller = new AbortController();
      request.current = controller;
      setLoading(true);
      setError('');
      try {
        const reply = await api<Reply | null>(
          query({ mine, with: only }, offset, taskOffset),
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        if (!reply || !Array.isArray(reply.conversations))
          throw new Error('无法加载对话');
        const page: Everyone = {
          mine: reply.mine ?? null,
          conversations: reply.conversations,
          tasks: Array.isArray(reply.tasks) ? reply.tasks : [],
          more: !!reply.more,
          next: reply.next ?? reply.conversations.length,
          moreTasks: !!reply.more_tasks,
        };
        setData((previous) => {
          if (!previous || (!offset && !taskOffset)) return page;
          if (taskOffset)
            return {
              ...previous,
              tasks: [...previous.tasks, ...page.tasks],
              moreTasks: page.moreTasks,
            };
          return {
            ...page,
            conversations: [...previous.conversations, ...page.conversations],
            tasks: previous.tasks,
            moreTasks: previous.moreTasks,
          };
        });
      } catch (failure) {
        if (controller.signal.aborted) return;
        setError(failure instanceof Error ? failure.message : '无法加载对话');
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    },
    [mine, only],
  );
  useEffect(() => {
    if (!enabled) return;
    void load();
    return () => request.current?.abort();
    // ``revision`` is only a reason to ask again.
  }, [enabled, load, revision]);
  const next = data?.next ?? 0;
  const taskCount = data?.tasks.length ?? 0;
  return {
    data,
    loading,
    error,
    reload: () => load(),
    more: () => load(next),
    moreTasks: () => load(0, taskCount),
  };
}
