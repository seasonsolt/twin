import { useCallback, useEffect, useState } from 'react';
import { usePersonaId, usePersonaState } from '../../lib/usePersonaState';
import { api } from '../../lib/api';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Skeleton,
  Textarea,
  toast,
} from '../../components/ui';

export interface Followup {
  followup_id: string;
  question: string;
  previous: string;
  reason: string;
  asked: number;
  first_at: string;
  last_at: string;
  status: 'pending' | 'answered' | 'dismissed';
  handled_at: string | null;
  asked_since: number;
  source_id: string | null;
  unresolved: boolean;
}

interface FollowupList {
  items: Followup[];
  pending: number;
}

function when(iso: string) {
  const match = /^\d{4}-(\d{2})-(\d{2})T(\d{2}:\d{2})/.exec(iso);
  return match ? `${Number(match[1])}月${Number(match[2])}日 ${match[3]}` : '';
}

function Question({
  item,
  onDone,
}: {
  item: Followup;
  onDone: () => Promise<void>;
}) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const id = `followup-${item.followup_id}`;
  const run = async (request: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setError('');
    try {
      await request();
      toast(done, 'success');
      await onDone();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '保存失败');
    } finally {
      setBusy(false);
    }
  };
  const base = `/api/persona/followups/${encodeURIComponent(item.followup_id)}`;
  return (
    <Card>
      <article aria-labelledby={`${id}-question`} className="space-y-3">
        {item.previous && (
          <p className="text-sm text-secondary">接着「{item.previous}」问：</p>
        )}
        <h3 id={`${id}-question`} className="font-medium">
          {item.question}
        </h3>
        <div className="flex flex-wrap items-center gap-2 text-sm text-secondary">
          <span>
            {item.asked > 1 ? `被问了 ${item.asked} 次，最近` : '问于'}{' '}
            {when(item.last_at)}
          </span>
          {item.unresolved && (
            <Badge tone="warning">回答过，分身还是答不上，可以再补充</Badge>
          )}
        </div>
        {item.reason && (
          <p className="text-sm text-tertiary">
            分身没回答的原因：{item.reason}
          </p>
        )}
        <label htmlFor={id} className="sr-only">
          你的回答
        </label>
        <Textarea
          id={id}
          value={text}
          placeholder="用你自己的话回答，会作为你的原话记下来"
          onChange={(event) => setText(event.target.value)}
        />
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            loading={busy}
            disabled={!text.trim()}
            onClick={() =>
              void run(
                () =>
                  api(`${base}/answer`, {
                    method: 'POST',
                    json: { text: text.trim() },
                  }),
                '已记下，正在整理成记忆',
              )
            }
          >
            记为我的回答
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() =>
              void run(
                () =>
                  api(`${base}/status`, {
                    method: 'POST',
                    json: { status: 'dismissed' },
                  }),
                '已放到一边，分身遇到这个问题仍会说要问你本人',
              )
            }
          >
            不用回答
          </Button>
        </div>
      </article>
    </Card>
  );
}

export function Followups() {
  const personaId = usePersonaId();
  const [data, setData] = usePersonaState<FollowupList | null>(null);
  const [error, setError] = usePersonaState('');
  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        setData(await api<FollowupList>('/api/persona/followups', { signal }));
        setError('');
      } catch (failure) {
        if (signal?.aborted) return;
        setError(failure instanceof Error ? failure.message : '加载失败');
      }
    },
    [setData, setError],
  );
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, personaId]);
  if (error)
    return (
      <div role="alert" className="space-y-2 text-danger">
        <p>{error}</p>
        <Button variant="secondary" onClick={() => void load()}>
          重试加载
        </Button>
      </div>
    );
  if (!data) return <Skeleton className="h-40" />;
  const pending = data.items.filter((item) => item.status === 'pending');
  const answered = data.items.filter((item) => item.status === 'answered');
  const dismissed = data.items.filter((item) => item.status === 'dismissed');
  return (
    <div className="space-y-4">
      <p className="text-sm text-secondary">
        别人问分身、分身答不上来的问题会出现在这里。你回答一次，分身以后就能用你的原话回答。
      </p>
      {!pending.length && (
        <EmptyState
          title="没有待回答的问题"
          body="分身答不上来时，问题会自动出现在这里。"
        />
      )}
      {pending.map((item) => (
        <Question key={item.followup_id} item={item} onDone={() => load()} />
      ))}
      {answered.length > 0 && (
        <details className="space-y-2">
          <summary className="cursor-pointer text-secondary">
            已回答 {answered.length} 个
          </summary>
          <ul className="space-y-1 pt-2 text-sm">
            {answered.map((item) => (
              <li key={item.followup_id}>
                {item.question}
                {item.handled_at && (
                  <span className="text-tertiary">
                    （{when(item.handled_at)} 回答，可以在「记忆」里查看或删除）
                  </span>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
      {dismissed.length > 0 && (
        <details className="space-y-2">
          <summary className="cursor-pointer text-secondary">
            不用回答 {dismissed.length} 个
          </summary>
          <ul className="space-y-2 pt-2 text-sm">
            {dismissed.map((item) => (
              <li
                key={item.followup_id}
                className="flex flex-wrap items-center gap-2"
              >
                <span>{item.question}</span>
                {item.asked_since > 0 && (
                  <span className="text-tertiary">
                    之后又被问了 {item.asked_since} 次
                  </span>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    void api(
                      `/api/persona/followups/${encodeURIComponent(item.followup_id)}/status`,
                      { method: 'POST', json: { status: 'pending' } },
                    )
                      .then(() => load())
                      .catch((failure: unknown) =>
                        toast(
                          failure instanceof Error
                            ? failure.message
                            : '操作失败',
                          'danger',
                        ),
                      )
                  }
                >
                  放回待回答
                </Button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
