import { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import * as TabsPrimitive from '@radix-ui/react-tabs';
import { useNavigate, useSearchParams } from 'react-router';
import { Button, Card, Dialog, Skeleton, useConfirm } from '../components/ui';
import { StageHeader } from '../components/layout/StageHeader';
import { AvatarPreview } from '../features/avatar/AvatarPreview';
import { AvatarPicker } from '../features/avatar/AvatarPicker';
import { presetId, presets } from '../features/avatar/presets';
import { IdentityForm } from '../features/identity/IdentityForm';
import { useIdentity } from '../features/identity/useIdentity';
import { SelfAssets } from '../features/assets/SelfAssets';
import { RecordingShortcut } from '../features/sources/MediaClaim';
import { Overview } from '../features/profile/Overview';
import { Channels } from '../features/profile/Channels';
import { usePersonaId, usePersonaState } from '../lib/usePersonaState';
import { api } from '../lib/api';
import { forgetPersona, personaUrl } from '../lib/persona';
import { usePersonas } from '../stores/personas';
import { Memories } from './Memories';

const MemoryGraphPanel = lazy(
  () => import('../features/profile/graph/MemoryGraphPanel'),
);

const sections = [
  { id: 'overview', title: '概览' },
  { id: 'graph', title: '图谱' },
  { id: 'memories', title: '记忆' },
  { id: 'assets', title: '形象和声音' },
  { id: 'channels', title: '接入' },
] as const;
type Section = (typeof sections)[number]['id'];

export function Profile() {
  const personaId = usePersonaId();
  const identity = useIdentity(true);
  const current = usePersonas((state) =>
    state.items.find((item) => item.id === state.id),
  );
  const navigate = useNavigate();
  const confirm = useConfirm();
  const [params, setParams] = useSearchParams();
  const requested = params.get('section');
  const section: Section =
    sections.find((item) => item.id === requested)?.id ?? 'overview';
  const [editing, setEditing] = usePersonaState(false);
  const [speakerCount, setSpeakerCount] = usePersonaState(0);
  const [busy, setBusy] = usePersonaState(false);
  const [error, setError] = usePersonaState('');
  const modelUrl = identity.capabilities?.avatar_model?.url;
  const [model, setModel] = useState<{ url?: string; name: string | null }>({
    name: null,
  });
  const onModelNameChange = useCallback(
    (name: string | null) => setModel({ url: modelUrl, name }),
    [modelUrl],
  );
  const modelName = modelUrl && model.url === modelUrl ? model.name : null;
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [section]);
  useEffect(() => {
    if (section !== 'overview') return;
    const controller = new AbortController();
    void api<{ status: string }[]>('/api/persona/sources', {
      signal: controller.signal,
      headers: { 'X-Twin-Persona': personaId },
    })
      .then((rows) => {
        if (!controller.signal.aborted)
          setSpeakerCount(
            rows.filter((row) => row.status === 'needs_speaker').length,
          );
      })
      .catch(() => {});
    return () => controller.abort();
  }, [section, personaId, setSpeakerCount]);
  const remove = async () => {
    if (!current || current.is_default || busy) return;
    const deleting = current;
    if (
      !(await confirm({
        title: `删除「${deleting.name}」？`,
        body: '删除后 7 天内可以在「最近删除」里恢复',
        confirmLabel: '删除分身',
        tone: 'danger',
      })) ||
      usePersonas.getState().id !== deleting.id
    )
      return;
    setBusy(true);
    setError('');
    try {
      await api(`/api/personas/${deleting.id}`, { method: 'DELETE' });
      forgetPersona(deleting.id);
      await usePersonas.getState().refresh();
      navigate('/twins');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '操作失败，请重试');
    } finally {
      setBusy(false);
    }
  };
  return (
    <TabsPrimitive.Root
      className="profile-page"
      value={section}
      onValueChange={(value) =>
        setParams({ section: value }, { replace: true })
      }
    >
      <StageHeader
        variant="expanded"
        name={identity.data?.name}
        right={
          <Button variant="secondary" onClick={() => setEditing(true)}>
            编辑
          </Button>
        }
        portrait={
          identity.capabilities &&
          (identity.capabilities.avatar_image ||
            identity.capabilities.avatar_model ||
            identity.capabilities.avatar) ? (
            <div
              className="stage-circle stage-portrait about-portrait"
              aria-label="你的形象"
            >
              <AvatarPreview
                capabilities={identity.capabilities}
                onModelNameChange={onModelNameChange}
              />
            </div>
          ) : undefined
        }
        intro={
          <p className="stage-caption profile-intro">
            {identity.data?.about || '在这里，慢慢认识他。'}
          </p>
        }
      />
      <TabsPrimitive.List asChild>
        <nav aria-label="档案章节" className="profile-section-nav">
          {sections.map((item) => (
            <TabsPrimitive.Trigger
              key={item.id}
              value={item.id}
              aria-controls={`profile-${item.id}`}
              asChild
            >
              <a
                href={`#/profile?section=${item.id}`}
                onClick={(event) => {
                  event.preventDefault();
                  if (section !== item.id)
                    setParams({ section: item.id }, { replace: true });
                }}
              >
                {item.title}
              </a>
            </TabsPrimitive.Trigger>
          ))}
        </nav>
      </TabsPrimitive.List>
      <div className="page-content space-y-6">
        {section === 'overview' && (
          <TabsPrimitive.Content value="overview" asChild>
            <section
              id="profile-overview"
              className="profile-section space-y-4"
              aria-label="概览"
            >
              <h2 className="text-xl font-semibold">概览</h2>
              {speakerCount > 0 && (
                <a
                  className="speaker-banner block rounded-xl bg-note p-4 text-primary"
                  href="#/profile?section=memories"
                >
                  有 {speakerCount} 段录音需要确认哪位是你
                </a>
              )}
              <Overview />
              <Card className="border border-danger/20 p-4 md:p-6">
                <h2 className="mb-3 text-lg font-semibold">删除这个分身</h2>
                {current?.is_default ? (
                  <p className="text-secondary">默认分身不能删除</p>
                ) : (
                  current && (
                    <Button
                      variant="danger"
                      loading={busy}
                      onClick={() => void remove()}
                    >
                      删除这个分身
                    </Button>
                  )
                )}
                {error && (
                  <p role="alert" className="mt-3 text-danger">
                    {error}
                  </p>
                )}
              </Card>
            </section>
          </TabsPrimitive.Content>
        )}
        {section === 'graph' && (
          <TabsPrimitive.Content value="graph" asChild>
            <section
              id="profile-graph"
              className="profile-section min-w-0"
              aria-label="图谱"
            >
              <Suspense fallback={<Skeleton className="h-[70vh]" />}>
                <MemoryGraphPanel
                  key={personaId}
                  twin={{
                    id: personaId,
                    name: identity.data?.name || current?.name || '分身',
                    avatarPreset:
                      identity.data?.avatar_preset ??
                      identity.data?.avatar ??
                      current?.avatar_preset,
                    portrait: identity.capabilities?.avatar_image
                      ? personaUrl(
                          identity.capabilities.avatar_image.url ||
                            '/api/media/avatar-image',
                          personaId,
                        )
                      : undefined,
                  }}
                />
              </Suspense>
            </section>
          </TabsPrimitive.Content>
        )}
        {section === 'memories' && (
          <TabsPrimitive.Content value="memories" asChild>
            <section
              id="profile-memories"
              className="profile-section space-y-4"
              aria-label="记忆"
            >
              <h2 className="text-xl font-semibold">记忆</h2>
              <Memories profile onSpeakerCount={setSpeakerCount} />
            </section>
          </TabsPrimitive.Content>
        )}
        {section === 'assets' && (
          <TabsPrimitive.Content value="assets" asChild>
            <section
              id="profile-assets"
              className="profile-section space-y-4"
              aria-label="形象和声音"
            >
              <h2 className="text-xl font-semibold">形象和声音</h2>
              <p className="text-sm text-secondary">
                形象：
                {modelName
                  ? `${modelName}（3D 模型）`
                  : identity.capabilities?.avatar_image
                    ? '肖像照片'
                    : `${presets[presetId(identity.data?.avatar)].name}（插画形象）`}
              </p>
              {identity.avatarError && (
                <p role="alert" className="text-danger">
                  形象预览：{identity.avatarError}{' '}
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={identity.reload}
                  >
                    重试预览
                  </Button>
                </p>
              )}
              <AvatarPicker
                key={`avatar-${personaId}`}
                selected={identity.data?.avatar_preset ?? identity.data?.avatar}
                collapsed={
                  !!(
                    identity.capabilities?.avatar_image ||
                    identity.capabilities?.avatar_model
                  )
                }
                onSave={identity.savePreset}
              />
              <RecordingShortcut key={personaId} />
              <SelfAssets />
            </section>
          </TabsPrimitive.Content>
        )}
        {section === 'channels' && (
          <TabsPrimitive.Content value="channels" asChild>
            <section
              id="profile-channels"
              className="profile-section space-y-4"
              aria-label="接入"
            >
              <h2 className="text-xl font-semibold">接入</h2>
              <Channels />
            </section>
          </TabsPrimitive.Content>
        )}
      </div>
      <Dialog
        open={editing}
        onOpenChange={setEditing}
        title="名字与介绍"
        body="修改这个分身的名字和一句话介绍。"
      >
        {identity.loading && <Skeleton className="h-40" />}
        {identity.error && (
          <p role="alert" className="text-danger">
            {identity.error}{' '}
            <Button variant="secondary" onClick={identity.reload}>
              重试加载
            </Button>
          </p>
        )}
        {identity.data && (
          <IdentityForm
            key={`${personaId}-${identity.data.name}-${identity.data.about}`}
            identity={identity.data}
            onSaved={() => {
              identity.reload();
              setEditing(false);
            }}
          />
        )}
      </Dialog>
    </TabsPrimitive.Root>
  );
}
