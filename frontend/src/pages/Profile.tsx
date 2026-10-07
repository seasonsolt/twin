import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { Button, Card, Dialog, Skeleton, useConfirm } from '../components/ui';
import { StageHeader } from '../components/layout/StageHeader';
import { AvatarPreview } from '../features/avatar/AvatarPreview';
import { IdentityForm } from '../features/identity/IdentityForm';
import { useIdentity } from '../features/identity/useIdentity';
import { SelfAssets } from '../features/assets/SelfAssets';
import { RecordingShortcut } from '../features/sources/MediaClaim';
import { Overview } from '../features/profile/Overview';
import { usePersonaId, usePersonaState } from '../lib/usePersonaState';
import { api } from '../lib/api';
import { forgetPersona } from '../lib/persona';
import { usePersonas } from '../stores/personas';
import { Memories } from './Memories';

const sections = [
  { id: 'overview', title: '概览' },
  { id: 'memories', title: '记忆' },
  { id: 'assets', title: '形象和声音' },
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
  const [active, setActive] = useState<Section>(section);
  const [editing, setEditing] = usePersonaState(false);
  const [speakerCount, setSpeakerCount] = usePersonaState(0);
  const [busy, setBusy] = usePersonaState(false);
  const [error, setError] = usePersonaState('');
  const fromScroll = useRef(false);
  const nav = useRef<HTMLElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const modelUrl = identity.capabilities?.avatar_model?.url;
  const [model, setModel] = useState<{ url?: string; name: string | null }>({
    name: null,
  });
  const onModelNameChange = useCallback(
    (name: string | null) => setModel({ url: modelUrl, name }),
    [modelUrl],
  );
  const modelName = modelUrl && model.url === modelUrl ? model.name : null;
  const jump = useCallback((id: Section) => {
    content.current
      ?.querySelector<HTMLElement>(`#profile-${id}`)
      ?.scrollIntoView?.({ block: 'start', behavior: 'instant' });
    setActive(id);
  }, []);
  useEffect(() => {
    if (fromScroll.current) {
      fromScroll.current = false;
      return;
    }
    if (!requested) {
      setActive('overview');
      return;
    }
    jump(section);
    const observer = new ResizeObserver(() => jump(section));
    if (content.current) observer.observe(content.current);
    const unpin = () => observer.disconnect();
    window.addEventListener('wheel', unpin, { passive: true });
    window.addEventListener('pointerdown', unpin, { passive: true });
    window.addEventListener('keydown', unpin);
    return () => {
      observer.disconnect();
      window.removeEventListener('wheel', unpin);
      window.removeEventListener('pointerdown', unpin);
      window.removeEventListener('keydown', unpin);
    };
  }, [requested, section, jump]);
  useEffect(() => {
    const spy = () => {
      const threshold =
        (nav.current?.getBoundingClientRect().bottom ?? 64) + 16;
      let next: Section = 'overview';
      let nearest = -Infinity;
      for (const item of sections) {
        const top = content.current
          ?.querySelector(`#profile-${item.id}`)
          ?.getBoundingClientRect().top;
        if (
          top !== undefined &&
          top <= threshold &&
          (top > nearest || (top === nearest && item.id === requested))
        ) {
          next = item.id;
          nearest = top;
        }
      }
      setActive(next);
      if (requested !== next) {
        fromScroll.current = true;
        setParams(
          { section: next },
          { replace: true, preventScrollReset: true },
        );
      }
    };
    window.addEventListener('scroll', spy, { passive: true });
    return () => window.removeEventListener('scroll', spy);
  }, [requested, setParams]);
  const remove = async () => {
    if (!current || current.is_default || busy) return;
    const deleting = current;
    if (
      !(await confirm({
        title: `删除「${deleting.name}」？`,
        body: '记忆、聊天、形象、声音和媒体将永久删除，无法恢复。',
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
    <div className="profile-page">
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
      <nav ref={nav} aria-label="档案章节" className="profile-section-nav">
        {sections.map((item) => (
          <a
            key={item.id}
            href={`#/profile?section=${item.id}`}
            aria-current={active === item.id ? 'location' : undefined}
            onClick={(event) => {
              event.preventDefault();
              fromScroll.current = false;
              setParams({ section: item.id });
              jump(item.id);
            }}
          >
            {item.title}
          </a>
        ))}
      </nav>
      <div ref={content} className="profile-content page-content space-y-6">
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
        </section>
        <section
          id="profile-memories"
          className="profile-section space-y-4"
          aria-label="记忆"
        >
          <h2 className="text-xl font-semibold">记忆</h2>
          <Memories profile onSpeakerCount={setSpeakerCount} />
        </section>
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
                : `${identity.data?.avatar || '未设置'}（风格化形象）`}
          </p>
          {identity.avatarError && (
            <p role="alert" className="text-danger">
              形象预览：{identity.avatarError}{' '}
              <Button variant="secondary" size="sm" onClick={identity.reload}>
                重试预览
              </Button>
            </p>
          )}
          <RecordingShortcut key={personaId} />
          <SelfAssets />
        </section>
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
    </div>
  );
}
