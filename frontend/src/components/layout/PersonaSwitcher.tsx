import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { Check, ChevronDown } from 'lucide-react';
import { Button, Dialog, useConfirm } from '../ui';
import { api } from '../../lib/api';
import { forgetPersona, personaUrl } from '../../lib/persona';
import { usePersonas, type Persona } from '../../stores/personas';
import { useStatus } from '../../stores/status';
import { useAuth } from '../../stores/auth';

function Portrait({ persona }: { persona?: Persona }) {
  return persona?.avatar_url ? (
    <img
      src={personaUrl(persona.avatar_url, persona.id)}
      alt=""
      className="size-8 rounded-full object-cover"
    />
  ) : (
    <span
      className="grid size-8 shrink-0 place-items-center rounded-full bg-accent/10"
      aria-hidden
    >
      {Array.from(persona?.name || '本人')[0]}
    </span>
  );
}

export function PersonaSwitcher({
  createOnly = false,
}: {
  createOnly?: boolean;
}) {
  const identity = useAuth((state) => state.identity);
  const { id, items, refresh, switchTo } = usePersonas();
  const current = items.find((item) => item.id === id);
  const name = useStatus((state) => state.data?.target_name);
  const [mode, setMode] = useState<'list' | 'create' | 'manage' | null>(
    createOnly ? 'create' : null,
  );
  const [draft, setDraft] = useState('');
  const [editing, setEditing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const confirm = useConfirm();
  const navigate = useNavigate();
  useEffect(() => {
    const load = () => void refresh().catch(() => {});
    load();
    window.addEventListener('twin-assets-changed', load);
    window.addEventListener('twin-identity-changed', load);
    return () => {
      window.removeEventListener('twin-assets-changed', load);
      window.removeEventListener('twin-identity-changed', load);
    };
  }, [refresh]);
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
      await api(`/api/personas/${persona.id}`, {
        method: 'DELETE',
      });
      forgetPersona(persona.id);
      if (id === persona.id)
        switchTo(
          items.find((item) => item.is_default)?.id ??
            items.find((item) => item.id !== persona.id)?.id ??
            '',
        );
      await refresh();
    });
  };
  const submit = () =>
    work(async () => {
      if (mode === 'create') {
        const created = await api<Persona>('/api/personas', {
          method: 'POST',
          json: { name: draft },
        });
        await refresh();
        navigate('/chat');
        switchTo(created.id);
        setMode(null);
      } else if (editing) {
        const headers = { 'X-Twin-Persona': editing };
        const identity = await api<{ about: string }>('/api/identity', {
          headers,
        });
        await api('/api/identity', {
          method: 'PUT',
          headers,
          json: { name: draft, about: identity.about },
        });
        await refresh();
        await useStatus.getState().refresh();
        setEditing(null);
      }
    });
  return (
    <>
      <button
        type="button"
        aria-label={createOnly ? '新建分身' : '切换分身'}
        aria-expanded={mode !== null}
        className="flex min-h-11 items-center gap-2 rounded-md px-2 text-base hover:bg-accent/10"
        onClick={() => {
          setMode(createOnly ? 'create' : 'list');
          setError('');
          void work(refresh);
        }}
      >
        <Portrait persona={current} />
        <span className="max-w-52 truncate">
          {createOnly ? '新建分身' : name || current?.name || '本人'}
        </span>
        <ChevronDown className="size-4" aria-hidden />
      </button>
      <Dialog
        open={mode !== null}
        onOpenChange={(open) => {
          if (!open) setMode(null);
        }}
        title={
          mode === 'create'
            ? '新建分身'
            : mode === 'manage'
              ? '管理分身'
              : '切换分身'
        }
        body="每个分身都有独立的记忆、形象、声音和聊天。"
        className="[&_button]:min-h-11 [&_button]:min-w-11"
      >
        <div className="space-y-3 [&_button]:min-h-11 [&_input]:text-base">
          {mode !== 'create' &&
            items.map((persona) => (
              <div
                key={persona.id}
                className="space-y-2 rounded-md border border-border p-2"
              >
                <button
                  type="button"
                  className="flex w-full items-center gap-3 text-left"
                  disabled={busy}
                  onClick={() => {
                    setMode(null);
                    switchTo(persona.id);
                  }}
                >
                  <Portrait persona={persona} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{persona.name}</span>
                    <span className="text-sm text-secondary">
                      {persona.sources} 条记忆
                    </span>
                    {identity?.admin &&
                      persona.owner &&
                      persona.owner !== identity.email && (
                        <span className="block truncate text-xs text-secondary">
                          {persona.owner}
                        </span>
                      )}
                  </span>
                  {persona.id === id && (
                    <Check
                      aria-label="当前分身"
                      className="size-5 text-accent"
                    />
                  )}
                </button>
                {mode === 'manage' && (
                  <div className="flex gap-2">
                    <Button
                      variant="secondary"
                      disabled={busy}
                      onClick={() => {
                        setEditing(persona.id);
                        setDraft(persona.name);
                      }}
                    >
                      重命名
                    </Button>
                    {!persona.is_default && (
                      <Button
                        variant="danger"
                        disabled={busy}
                        onClick={() => void remove(persona)}
                      >
                        删除
                      </Button>
                    )}
                  </div>
                )}
              </div>
            ))}
          {(mode === 'create' || (mode === 'manage' && editing)) && (
            <form
              className="space-y-3"
              onSubmit={(event) => {
                event.preventDefault();
                void submit();
              }}
            >
              <label className="block space-y-1">
                分身名字
                <input
                  autoFocus
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  maxLength={20}
                  required
                  className="block min-h-11 w-full rounded-md border border-border bg-background px-3"
                />
              </label>
              <Button type="submit" loading={busy} disabled={!draft.trim()}>
                {mode === 'create' ? '创建并开始' : '保存名字'}
              </Button>
            </form>
          )}
          {mode === 'list' && (
            <div className="flex gap-2">
              <Button
                disabled={busy}
                onClick={() => {
                  setDraft('');
                  setMode('create');
                }}
              >
                新建分身
              </Button>
              <Button
                variant="secondary"
                onClick={() => {
                  setEditing(null);
                  setMode('manage');
                }}
              >
                管理
              </Button>
            </div>
          )}
          {mode !== 'list' && (
            <Button
              variant="ghost"
              onClick={() => {
                setEditing(null);
                setMode('list');
              }}
            >
              返回列表
            </Button>
          )}
          {identity?.auth_enabled && (
            <div className="border-t border-border pt-3">
              <p className="break-all text-sm text-secondary">
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
          {error && (
            <p role="alert" className="text-danger">
              {error}
            </p>
          )}
        </div>
      </Dialog>
    </>
  );
}
