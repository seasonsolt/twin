import { useEffect, useId, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { Check, Globe, Plus } from 'lucide-react';
import {
  ActionMenu,
  AvatarFrame,
  Badge,
  Button,
  Card,
  Chip,
  Dialog,
  Field,
  Heading,
  Input,
  Row,
  Skeleton,
  Stack,
  Text,
  TextLink,
  Toolbar,
  useConfirm,
  ThemePicker,
} from '../components/ui';
import { StageHeader } from '../components/layout/StageHeader';
import { PersonaPortrait } from '../components/layout/PersonaSwitcher';
import { NewTwin } from '../components/layout/NewTwin';
import { CHAT_KEY } from '../features/chat/useConversation';
import { api } from '../lib/api';
import { forgetPersona, personaKey } from '../lib/persona';
import { useMobile } from '../lib/useMobile';
import { accountLabel, useAuth } from '../stores/auth';
import { usePersonas, type Persona } from '../stores/personas';
import { useStatus } from '../stores/status';
import { THEMES, useTheme } from '../stores/theme';

interface TrashedPersona {
  id: string;
  name: string;
  deleted_at: string;
  expires_at: string;
}

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
  const { theme, setTheme } = useTheme();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<Record<string, number>>({});
  const [editing, setEditing] = useState<Persona | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [trashOpen, setTrashOpen] = useState(false);
  const [trash, setTrash] = useState<TrashedPersona[]>([]);
  const [trashLoading, setTrashLoading] = useState(false);
  const confirm = useConfirm();
  const nameId = useId();
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
            const page = await api<{ summary: { needs_speaker: number } }>(
              '/api/persona/sources?limit=0',
              {
                headers: { 'X-Twin-Persona': persona.id },
                signal: controller.signal,
              },
            );
            return [persona.id, page.summary.needs_speaker] as const;
          } catch {
            return [persona.id, 0] as const;
          }
        }),
    ).then((counts) => {
      if (!controller.signal.aborted) setPending(Object.fromEntries(counts));
    });
    return () => controller.abort();
  }, [items]);
  useEffect(() => {
    if (!trashOpen) return;
    const controller = new AbortController();
    setTrashLoading(true);
    void api<TrashedPersona[]>('/api/personas/trash', {
      signal: controller.signal,
    })
      .then((entries) => {
        if (!controller.signal.aborted) {
          if (!Array.isArray(entries)) throw new Error('无法加载最近删除');
          setTrash(entries);
        }
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setError(
            failure instanceof Error ? failure.message : '无法加载最近删除',
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setTrashLoading(false);
      });
    return () => controller.abort();
  }, [trashOpen, items]);
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
        body: '删除后 7 天内可以在「最近删除」里恢复',
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
    <Card
      key={persona.id}
      as="article"
      padding="none"
      className="twin-card relative overflow-hidden"
      data-current={persona.id === id}
    >
      <Button
        variant="ghost"
        className="twin-card-select h-full w-full min-w-0 flex-col justify-start gap-3 p-6 text-center text-primary hover:bg-transparent"
        aria-label={`和${persona.name}聊天`}
        onClick={() => {
          navigate('/chat');
          switchTo(persona.id);
        }}
      >
        <PersonaPortrait persona={persona} />
        <Text
          as="span"
          size="2xl"
          tone="inherit"
          weight="inherit"
          truncate
          className="persona-name max-w-full"
        >
          {persona.name}
        </Text>
        <Text as="span" size="sm" tone="secondary" weight="regular">
          {persona.sources} 条记忆
        </Text>
        {lastMessage(persona.id) && (
          <Text
            as="span"
            size="sm"
            tone="secondary"
            weight="regular"
            truncate
            className="w-full"
          >
            {lastMessage(persona.id)}
          </Text>
        )}
        {!!pending[persona.id] && (
          <Badge tone="warning">有 {pending[persona.id]} 段待确认</Badge>
        )}
        {persona.owner && persona.owner !== identity?.email && (
          <Text
            as="span"
            size="xs"
            tone="tertiary"
            weight="regular"
            truncate
            className="max-w-full"
            title={persona.owner}
          >
            {persona.owner}
          </Text>
        )}
        {persona.public && persona.can_manage !== false && (
          <Badge>
            <Globe size={14} aria-hidden />
            公开
          </Badge>
        )}
        {persona.id === id && (
          <Chip pressed>
            <Check size={14} aria-hidden />
            当前分身
          </Chip>
        )}
      </Button>
      {persona.can_manage !== false && (
        <ActionMenu
          label={`管理${persona.name}`}
          className="twin-card-menu absolute top-2 right-2"
          items={[
            {
              label: '重命名',
              disabled: busy,
              onSelect: () => {
                setDraft(persona.name);
                setEditing(persona);
              },
            },
            {
              label: persona.public ? '设为私有' : '设为公开',
              disabled: busy,
              onSelect: () => void setPublic(persona, !persona.public),
            },
            ...(persona.is_default
              ? []
              : [
                  {
                    label: '删除',
                    disabled: busy,
                    onSelect: () => void remove(persona),
                  },
                ]),
          ]}
        />
      )}
    </Card>
  );
  return (
    <div className="twins-page">
      <StageHeader
        variant="brand"
        intro={<p className="stage-caption">每个分身，都是一段独立的记忆。</p>}
      />
      <div className="page-content space-y-6">
        <Toolbar as="header" gap={4}>
          <Heading level={2}>我的分身</Heading>
          <TextLink to="/team" size="sm">
            团队
          </TextLink>
          {mobile && (
            <ThemePicker value={theme} options={THEMES} onChange={setTheme} />
          )}
          {mobile && identity?.auth_enabled && (
            <div className="min-w-0">
              <Text
                size="sm"
                tone="secondary"
                truncate
                className="max-w-64"
                title={accountLabel(identity) || undefined}
              >
                {accountLabel(identity)}
              </Text>
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => void work(() => useAuth.getState().logout())}
              >
                退出登录
              </Button>
            </div>
          )}
        </Toolbar>
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
            variant="card"
            onOpenChange={(open) => {
              if (!open && params.has('create'))
                setParams({}, { replace: true });
            }}
          >
            <AvatarFrame size="xl">
              <Plus size={32} aria-hidden />
            </AvatarFrame>
            <Text
              as="span"
              size="2xl"
              tone="inherit"
              weight="inherit"
              className="persona-name"
            >
              新建分身
            </Text>
          </NewTwin>
        </div>
        {others.length > 0 && (
          <>
            <Heading level={2}>公开分身</Heading>
            <div className="twins-grid" aria-label="公开分身列表">
              {others.map(card)}
            </div>
          </>
        )}
        <Card as="div" variant="outline" padding="md">
          <details onToggle={(event) => setTrashOpen(event.currentTarget.open)}>
            <summary className="min-h-11 cursor-pointer">
              <Text as="span" size="lg" weight="semibold">
                最近删除
              </Text>
            </summary>
            <Text size="sm" tone="secondary" className="mb-3">
              删除后保留 7 天，到期后永久删除。
            </Text>
            {trashLoading ? (
              <Skeleton className="h-16" />
            ) : trash.length === 0 ? (
              <Text size="sm" tone="secondary">
                暂无最近删除的分身
              </Text>
            ) : (
              <Stack as="ul" gap={3}>
                {trash.map((persona) => (
                  <Row as="li" key={persona.id} gap={3} justify="between">
                    <div className="min-w-0">
                      <Text truncate>{persona.name}</Text>
                      <Text size="xs" tone="secondary">
                        删除于{' '}
                        {new Date(persona.deleted_at).toLocaleDateString(
                          'zh-CN',
                        )}
                        ，
                        {new Date(persona.expires_at).toLocaleDateString(
                          'zh-CN',
                        )}{' '}
                        到期
                      </Text>
                    </div>
                    <Button
                      variant="secondary"
                      disabled={busy}
                      aria-label={`恢复${persona.name}`}
                      onClick={() =>
                        void work(async () => {
                          await api(`/api/personas/${persona.id}/restore`, {
                            method: 'POST',
                          });
                          await refresh();
                        })
                      }
                    >
                      恢复
                    </Button>
                  </Row>
                ))}
              </Stack>
            )}
          </details>
        </Card>
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
            <Field id={nameId} label="分身名字">
              <Input
                id={nameId}
                autoFocus
                required
                maxLength={20}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
              />
            </Field>
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
