import { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import * as TabsPrimitive from '@radix-ui/react-tabs';
import { useNavigate, useSearchParams } from 'react-router';
import {
  Button,
  Dialog,
  Heading,
  Row,
  SettingsDialog,
  Skeleton,
  Stack,
  Tabs,
  Text,
  useConfirm,
} from '../components/ui';
import { StageHeader } from '../components/layout/StageHeader';
import { AvatarPreview } from '../features/avatar/AvatarPreview';
import { AvatarPicker } from '../features/avatar/AvatarPicker';
import { presetId, presets } from '../features/avatar/presets';
import { AliasList } from '../features/identity/AliasList';
import { IdentityForm } from '../features/identity/IdentityForm';
import { useIdentity } from '../features/identity/useIdentity';
import { SelfAssets } from '../features/assets/SelfAssets';
import { RecordingShortcut } from '../features/sources/MediaClaim';
import { Overview } from '../features/profile/Overview';
import { Channels } from '../features/profile/Channels';
import { Followups } from '../features/followups/Followups';
import { usePersonaId, usePersonaState } from '../lib/usePersonaState';
import { api } from '../lib/api';
import { forgetPersona, personaUrl } from '../lib/persona';
import { usePersonas } from '../stores/personas';
import { useStatus } from '../stores/status';
import { Memories, type SourcePage } from './Memories';

const MemoryGraphPanel = lazy(
  () => import('../features/profile/graph/MemoryGraphPanel'),
);

const sections = [
  { id: 'overview', title: '人格' },
  { id: 'memories', title: '记忆' },
  { id: 'assets', title: '形象和声音' },
] as const;
type Section = (typeof sections)[number]['id'];
// Older links name sections that now live inside another one: the graph is a view of the memories, and channels
// and the questions the twin asked are settings of the twin (waiting questions also show under the persona).
const moved: Record<string, Section> = {
  graph: 'memories',
  questions: 'overview',
  channels: 'overview',
};
const settingsSections = [
  { key: 'channels', label: '接入' },
  { key: 'questions', label: '问过的问题' },
  { key: 'services', label: '外部服务' },
  { key: 'delete', label: '删除分身' },
];
const backendNames: Record<string, string> = {
  llm: '大模型',
  embed: '向量',
  tts: '朗读',
  asr: '语音识别',
  video: '视频生成',
  vision: '形象提取',
  judge: '回答检查',
  search: '网页搜索',
};

/** Where the twin's data leaves this machine, so the person can tell at a glance. */
function ExternalServices() {
  const status = useStatus((state) => state.data);
  if (!status) return <Skeleton className="h-16" />;
  const external = status.egress.filter((row) => row.external);
  return external.length ? (
    <Stack as="ul" gap={2}>
      {external.map((row, i) => (
        <Text as="li" key={`${row.kind}-${i}`} size="sm">
          {backendNames[row.kind] ??
            (row.kind.startsWith('judge') ? '回答检查' : '数据处理')}
          ：{row.host || '地址未提供'}
        </Text>
      ))}
    </Stack>
  ) : (
    <Text size="sm" tone="secondary">
      目前没有使用外部服务。
    </Text>
  );
}

export function Profile() {
  const personaId = usePersonaId();
  const identity = useIdentity(true);
  const current = usePersonas((state) =>
    state.items.find((item) => item.id === state.id),
  );
  const navigate = useNavigate();
  const confirm = useConfirm();
  const [params, setParams] = useSearchParams();
  const requested = params.get('section') ?? '';
  const section: Section =
    sections.find((item) => item.id === requested)?.id ??
    moved[requested] ??
    'overview';
  const view =
    requested === 'graph' || params.get('view') === 'graph' ? 'graph' : 'list';
  const [settings, setSettings] = useState<string | null>(null);
  // An old channels or questions link opens that setting over the persona, then reads as the persona's link, so
  // closing the dialog and going back and forward behave like any other dialog.
  useEffect(() => {
    if (requested !== 'channels' && requested !== 'questions') return;
    setSettings(requested);
    setParams({ section: 'overview' }, { replace: true });
  }, [requested, setParams]);
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
    void api<SourcePage>('/api/persona/sources?limit=0', {
      signal: controller.signal,
      headers: { 'X-Twin-Persona': personaId },
    })
      .then((page) => {
        if (!controller.signal.aborted)
          setSpeakerCount(page.summary.needs_speaker);
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
          <Row gap={2}>
            <Button variant="secondary" onClick={() => setEditing(true)}>
              编辑
            </Button>
            <Button
              variant="secondary"
              aria-haspopup="dialog"
              onClick={() => setSettings('channels')}
            >
              设置
            </Button>
          </Row>
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
              aria-label="人格"
            >
              <Heading level={2} size="title">
                人格
              </Heading>
              {speakerCount > 0 && (
                <a
                  className="speaker-banner block"
                  href="#/profile?section=memories"
                >
                  有 {speakerCount} 段录音需要确认哪位是你
                </a>
              )}
              <Overview />
              <Followups quiet />
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
              <Row gap={3} wrap justify="between">
                <Heading level={2} size="title">
                  记忆
                </Heading>
                <Tabs
                  variant="filters"
                  label="记忆的看法"
                  value={view}
                  onValueChange={(next) =>
                    setParams(
                      next === 'graph'
                        ? { section: 'memories', view: 'graph' }
                        : { section: 'memories' },
                      { replace: true },
                    )
                  }
                  items={[
                    { value: 'list', label: '列表' },
                    { value: 'graph', label: '图谱' },
                  ]}
                />
              </Row>
              {view === 'graph' ? (
                <Suspense fallback={<Skeleton panel />}>
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
              ) : (
                <Memories profile onSpeakerCount={setSpeakerCount} />
              )}
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
              <Heading level={2} size="title">
                形象和声音
              </Heading>
              <Text size="sm" tone="secondary">
                形象：
                {modelName
                  ? `${modelName}（3D 模型）`
                  : identity.capabilities?.avatar_image
                    ? '肖像照片'
                    : `${presets[presetId(identity.data?.avatar)].name}（插画形象）`}
              </Text>
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
      </div>
      <SettingsDialog
        open={settings !== null}
        onOpenChange={(open) => setSettings(open ? 'channels' : null)}
        title="分身设置"
        note={identity.data?.name || current?.name}
        sections={settingsSections}
        active={settings ?? 'channels'}
        onSelect={setSettings}
      >
        {settings === 'channels' && <Channels />}
        {settings === 'questions' && <Followups />}
        {settings === 'services' && <ExternalServices />}
        {settings === 'delete' && (
          <Stack gap={3} align="start">
            <Text size="sm" tone="secondary">
              删除后 7 天内可以在「最近删除」里恢复。
            </Text>
            {current?.is_default ? (
              <Text tone="secondary">默认分身不能删除</Text>
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
              <Text role="alert" tone="danger">
                {error}
              </Text>
            )}
          </Stack>
        )}
      </SettingsDialog>
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
        {editing && <AliasList />}
      </Dialog>
    </TabsPrimitive.Root>
  );
}
