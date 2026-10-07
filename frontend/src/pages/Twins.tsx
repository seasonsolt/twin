import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { Check, Globe, MoreHorizontal, Plus } from 'lucide-react';
import { Button, Dialog, Skeleton, useConfirm } from '../components/ui';
import { StageHeader } from '../components/layout/StageHeader';
import { PersonaPortrait } from '../components/layout/PersonaSwitcher';
import { NewTwin } from '../components/layout/NewTwin';
import { CHAT_KEY } from '../features/chat/useConversation';
import { api } from '../lib/api';
import { forgetPersona, personaKey } from '../lib/persona';
import { useMobile } from '../lib/useMobile';
import { useAuth } from '../stores/auth';
import { usePersonas, type Persona } from '../stores/personas';
import { useStatus } from '../stores/status';

function lastMessage(id: string) {
  try {
    const turns: unknown = JSON.parse(
      sessionStorage.getItem(personaKey(CHAT_KEY, id)) ?? '[]',
    );
    if (!Array.isArray(turns)) return '';
    const last = turns.at(-1) as { content?: unknown } | undefined;
    return typeof last?.content === 'string'
      ? last.content.replace(/\s+/gu, ' ').slice(0, 160)
      : '';
  } catch {
    return '';
  }
}

export function Twins() {
  const { id, items, refresh, switchTo } = usePersonas();
  const identity = useAuth((state) => state.identity);
  const mobile = useMobile();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<Record<string, number>>({});
  const [editing, setEditing] = useState<Persona | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const confirm = useConfirm();
  useEffect(() => {
    let alive = true;
    void refresh()
      .catch((failure: unknown) => {
        if (alive)
          setError(failure instanceof Error ? failure.message : '无法加载分身');
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [refresh]);
  useEffect(() => {
    const controller = new AbortController();
    void Promise.all(
      items
        .filter((persona) => persona.can_manage !== false)
        .map(async (persona) => {
          try {
            const sources = await api<{ status: string }[]>(
              '/api/persona/sources',
              {
                headers: { 'X-Twin-Persona': persona.id },
                signal: controller.signal,
              },
            );
            return [
              persona.id,
              sources.filter((source) => source.status === 'needs_speaker')
                .length,
            ] as const;
          } catch {
            return [persona.id, 0] as const;
          }
        }),
    ).then((counts) => {
      if (!controller.signal.aborted) setPending(Object.fromEntries(counts));
    });
    return () => controller.abort();
  }, [items]);
  const work = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError('');
    try {
      await fn();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '操作失败，请重试');
    } finally {
      setBusy(false);
    }
  };
  const rename = () =>
    work(async () => {
      if (!editing || !draft.trim()) return;
      const headers = { 'X-Twin-Persona': editing.id };
      const data = await api<{ about: string }>('/api/identity', { headers });
      await api('/api/identity', {
        method: 'PUT',
        headers,
        json: { name: draft.trim(), about: data.about },
      });
      await refresh();
      if (id === editing.id) await useStatus.getState().refresh();
      setEditing(null);
    });
  const setPublic = (persona: Persona, value: boolean) =>
    work(async () => {
      await api(`/api/personas/${persona.id}`, {
        method: 'PATCH',
        json: { public: value },
      });
      await refresh();
    });
  const remove = async (persona: Persona) => {
    if (
      !(await confirm({
        title: `删除「${persona.name}」？`,
        body: '记忆、聊天、形象、声音和媒体将永久删除，无法恢复。',
        confirmLabel: '删除分身',
        tone: 'danger',
      }))
    )
      return;
    await work(async () => {
      await api(`/api/personas/${persona.id}`, { method: 'DELETE' });
      forgetPersona(persona.id);
      await refresh();
    });
  };
  const mine = items.filter((persona) => persona.can_manage !== false);
  const others = items.filter((persona) => persona.can_manage === false);
  const card = (persona: Persona) => (
    <article
      key={persona.id}
      className="twin-card relative rounded-xl bg-surface shadow-card"
      data-current={persona.id === id}
    >
      <button
        type="button"
        className="twin-card-select flex h-full w-full min-w-0 flex-col items-center gap-3 rounded-xl p-6 text-center"
        aria-label={`和${persona.name}聊天`}
        onClick={() => {
          navigate('/chat');
          switchTo(persona.id);
        }}
      >
        <PersonaPortrait persona={persona} />
        <span className="persona-name max-w-full truncate text-2xl">
          {persona.name}
        </span>
        <span className="text-sm text-secondary">{persona.sources} 条记忆</span>
        {lastMessage(persona.id) && (
          <span className="w-full truncate text-sm text-secondary">
            {lastMessage(persona.id)}
          </span>
        )}
        {!!pending[persona.id] && (
          <span className="rounded-full bg-note px-3 py-1 text-xs text-primary">
            有 {pending[persona.id]} 段待确认
          </span>
        )}
        {persona.owner && persona.owner !== identity?.email && (
          <span
            className="max-w-full truncate text-xs text-tertiary"
            title={persona.owner}
          >
            {persona.owner}
          </span>
        )}
        {persona.public && persona.can_manage !== false && (
          <span className="flex items-center gap-1 rounded-full bg-soft px-3 py-1 text-xs text-primary">
            <Globe size={14} aria-hidden />
            公开
          </span>
        )}
        {persona.id === id && (
          <span className="flex items-center gap-1 rounded-full bg-primary px-3 py-1 text-xs text-canvas">
            <Check size={14} aria-hidden />
            当前分身
          </span>
        )}
      </button>
      {persona.can_manage !== false && (
        <details className="twin-card-menu absolute top-2 right-2">
          <summary
            aria-label={`管理${persona.name}`}
            className="grid size-11 cursor-pointer list-none place-items-center rounded-full text-secondary hover:bg-soft [&::-webkit-details-marker]:hidden"
          >
            <MoreHorizontal size={20} aria-hidden />
          </summary>
          <div className="absolute right-0 z-10 grid min-w-28 rounded-lg border border-border bg-canvas p-1 shadow-elevation-2">
            <Button
              variant="ghost"
              disabled={busy}
              onClick={(event) => {
                event.currentTarget.closest('details')?.removeAttribute('open');
                setDraft(persona.name);
                setEditing(persona);
              }}
            >
              重命名
            </Button>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={(event) => {
                event.currentTarget.closest('details')?.removeAttribute('open');
                void setPublic(persona, !persona.public);
              }}
            >
              {persona.public ? '设为私有' : '设为公开'}
            </Button>
            {!persona.is_default && (
              <Button
                variant="ghost"
                disabled={busy}
                onClick={(event) => {
                  event.currentTarget
                    .closest('details')
                    ?.removeAttribute('open');
                  void remove(persona);
                }}
              >
                删除
              </Button>
            )}
          </div>
        </details>
      )}
    </article>
  );
  return (
    <div className="twins-page">
      <StageHeader
        variant="brand"
        intro={<p className="stage-caption">每个分身，都是一段独立的记忆。</p>}
      />
      <div className="page-content space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <h2 className="text-2xl font-semibold">我的分身</h2>
          {mobile && identity?.auth_enabled && (
            <div className="min-w-0 text-sm">
              <p
                className="max-w-64 truncate text-secondary"
                title={identity.email ?? undefined}
              >
                {identity.email}
              </p>
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => void work(() => useAuth.getState().logout())}
              >
                退出登录
              </Button>
            </div>
          )}
        </header>
        {loading && <Skeleton className="h-32" />}
        {error && (
          <p role="alert" className="text-danger">
            {error}{' '}
            <Button variant="ghost" onClick={() => void work(refresh)}>
              重试
            </Button>
          </p>
        )}
        <div className="twins-grid" aria-label="分身列表">
          {mine.map(card)}
          <NewTwin
            initialOpen={params.get('create') === '1'}
            className="twin-card twin-card-create flex min-h-60 flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed border-primary bg-transparent p-6 text-primary"
            onOpenChange={(open) => {
              if (!open && params.has('create'))
                setParams({}, { replace: true });
            }}
          >
            <span className="grid size-20 place-items-center rounded-full bg-soft">
              <Plus size={32} aria-hidden />
            </span>
            <span className="persona-name text-2xl">新建分身</span>
          </NewTwin>
        </div>
        {others.length > 0 && (
          <>
            <h2 className="text-2xl font-semibold">公开分身</h2>
            <div className="twins-grid" aria-label="公开分身列表">
              {others.map(card)}
            </div>
          </>
        )}
        <Dialog
          open={editing !== null}
          onOpenChange={(open) => {
            if (!open) setEditing(null);
          }}
          title="重命名分身"
          body="记忆、形象、声音和聊天不会改变。"
        >
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              void rename();
            }}
          >
            <label className="block space-y-2">
              分身名字
              <input
                autoFocus
                required
                maxLength={20}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                className="block min-h-11 w-full rounded-lg border-2 border-primary bg-surface px-3"
              />
            </label>
            <Button type="submit" loading={busy} disabled={!draft.trim()}>
              保存名字
            </Button>
            {error && (
              <p role="alert" className="text-danger">
                {error}
              </p>
            )}
          </form>
        </Dialog>
      </div>
    </div>
  );
}
