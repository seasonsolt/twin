import { useCallback, useState } from 'react';
import { useLocation } from 'react-router';
import { Button, Card, EmptyState, Skeleton } from '../components/ui';
import { AvatarPreview } from '../features/avatar/AvatarPreview';
import { IdentityForm } from '../features/identity/IdentityForm';
import { SelfAssets } from '../features/assets/SelfAssets';
import { useIdentity } from '../features/identity/useIdentity';
import { ItemCard } from '../features/profile/ItemCard';
import { useProfile } from '../features/profile/useProfile';
import { useStatus } from '../stores/status';
import { useMobile } from '../lib/useMobile';

export const topics: Record<string, string> = {
  D1: '经历与身份',
  D2: '看重什么',
  D3: '怎么做决定',
  D4: '怎么思考',
  D5: '擅长什么',
  D6: '说话方式',
  D7: '和人相处',
  D8: '最近在关注',
  D9: '生活与喜好',
};
const suggestions: Record<string, string> = {
  D1: '多写写你的经历与身份',
  D2: '多写写你看重什么',
  D3: '多写写你怎么做决定',
  D4: '多写写你怎么思考',
  D5: '多写写你擅长什么',
  D6: '多写写你平时怎么说话',
  D7: '多写写你怎样和人相处',
  D8: '多写写你最近在关注什么',
  D9: '多写写你的生活与喜好',
};
const backendNames: Record<string, string> = {
  llm: '大模型',
  embed: '向量',
  tts: '朗读',
  asr: '语音识别',
  video: '视频生成',
  vision: '形象提取',
  judge: '回答检查',
};

export function About() {
  const active = useLocation().pathname === '/about';
  const identity = useIdentity(active);
  const mobile = useMobile();
  const profile = useProfile(active);
  const status = useStatus((state) => state.data);
  const modelUrl = identity.capabilities?.avatar_model?.url;
  const [model, setModel] = useState<{ url?: string; name: string | null }>({
    name: null,
  });
  const onModelNameChange = useCallback(
    (name: string | null) => setModel({ url: modelUrl, name }),
    [modelUrl],
  );
  const modelName = modelUrl && model.url === modelUrl ? model.name : null;
  const wanted = [
    ...new Set(
      (profile.coverage?.suggestions ?? [])
        .map((suggestion) => {
          const dimension =
            profile.coverage?.facets.find(
              (facet) => facet.facet_id === suggestion.facet_id,
            )?.dimension_id ?? `D${suggestion.facet_id.split('.')[0]}`;
          return suggestions[dimension];
        })
        .filter(Boolean),
    ),
  ].slice(0, 5);
  return (
    <div className="about-page space-y-4 md:space-y-6">
      <header className="flex items-center gap-4">
        {mobile && identity.capabilities && (
          <div
            className="size-24 shrink-0 overflow-hidden rounded-xl"
            aria-label="你的形象"
          >
            {identity.capabilities.avatar_image ? (
              <img
                src={identity.capabilities.avatar_image.url}
                alt={`${identity.data?.name || '你'}的肖像`}
                className="size-full object-cover object-[50%_30%]"
              />
            ) : (
              <AvatarPreview
                capabilities={identity.capabilities}
                onModelNameChange={onModelNameChange}
              />
            )}
          </div>
        )}
        <div>
          <h1 className="text-lg font-semibold md:text-2xl">关于你</h1>
          {mobile && identity.data && (
            <p className="mt-1 text-md font-medium">{identity.data.name}</p>
          )}
        </div>
      </header>
      <Card className="p-4 md:p-6">
        <h2 className="mb-3 text-md font-semibold md:mb-4 md:text-lg">
          名字与介绍
        </h2>
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
          <div className="flex flex-wrap items-start gap-3 md:gap-6">
            <div className="min-w-0 flex-1 md:min-w-64">
              <IdentityForm
                key={`${identity.data.name}-${identity.data.about}`}
                identity={identity.data}
                onSaved={identity.reload}
              />
              <p className="mt-4 text-sm text-secondary">
                形象：
                {modelName
                  ? `${modelName}（3D 模型）`
                  : identity.capabilities?.avatar_image
                    ? '肖像照片'
                    : `${identity.data.avatar || '未设置'}（风格化形象）`}
              </p>
            </div>
            {!mobile &&
              identity.capabilities &&
              (identity.capabilities.avatar ||
                identity.capabilities.avatar_model ||
                identity.capabilities.avatar_image) && (
                <div className="w-48">
                  <AvatarPreview
                    capabilities={identity.capabilities}
                    onModelNameChange={onModelNameChange}
                  />
                </div>
              )}
          </div>
        )}
        {identity.avatarError && (
          <p role="alert" className="mt-3 text-danger">
            形象预览：{identity.avatarError}{' '}
            <Button variant="secondary" size="sm" onClick={identity.reload}>
              重试预览
            </Button>
          </p>
        )}
        <div className="mt-5 border-t border-border pt-4">
          <SelfAssets active={active} />
        </div>
      </Card>
      <Card className="p-4 md:p-6">
        <h2 className="mb-3 text-md font-semibold md:mb-4 md:text-lg">
          我了解到的你
        </h2>
        {profile.loading && <Skeleton className="h-24" />}
        {profile.itemsError && (
          <p role="alert" className="text-danger">
            {profile.itemsError}{' '}
            <Button variant="ghost" onClick={() => void profile.refreshItems()}>
              重试
            </Button>
          </p>
        )}
        {!profile.loading && !profile.itemsError && !profile.items.length && (
          <EmptyState
            title="还不够了解你"
            body="添加一些记忆，让我慢慢认识你。"
          >
            <a href="#/memories" className="text-accent underline">
              添加记忆
            </a>
          </EmptyState>
        )}
        {Object.entries(topics).map(([id, title]) => {
          const items = profile.items.filter(
            (item) => item.dimension_id === id && item.review !== 'rejected',
          );
          return (
            items.length > 0 && (
              <section
                key={id}
                className="mt-3 space-y-2 md:mt-5 md:space-y-3"
                aria-label={title}
              >
                <h3 className="font-semibold">{title}</h3>
                {items.map((item) => (
                  <ItemCard
                    key={item.item_id}
                    item={item}
                    pending={profile.pending.has(item.item_id)}
                    onReview={profile.review}
                    kindLabels={profile.coverage?.kind_labels ?? {}}
                  />
                ))}
              </section>
            )
          );
        })}
      </Card>
      <Card className="p-4 md:p-6">
        <h2 className="mb-3 text-md font-semibold md:text-lg">还想多了解</h2>
        {profile.coverageError && (
          <p role="alert">
            {profile.coverageError}{' '}
            <Button
              variant="ghost"
              onClick={() => void profile.refreshCoverage()}
            >
              重试
            </Button>
          </p>
        )}
        <ul className="space-y-2">
          {wanted.map((text) => (
            <li key={text}>
              <a className="text-accent underline" href="#/memories">
                {text}
              </a>
            </li>
          ))}
        </ul>
        <a
          className="mt-4 inline-block text-accent underline"
          href="#/questionnaire"
        >
          回答几个问题
        </a>
      </Card>
      <section className="text-sm text-secondary" aria-label="外部服务">
        <h2 className="font-medium">外部服务</h2>
        {status &&
          (status.egress.some((row) => row.external) ? (
            <ul>
              {status.egress
                .filter((row) => row.external)
                .map((row, i) => (
                  <li key={`${row.kind}-${i}`}>
                    {backendNames[row.kind] ??
                      (row.kind.startsWith('judge') ? '回答检查' : '数据处理')}
                    ：{row.host || '地址未提供'}
                  </li>
                ))}
            </ul>
          ) : (
            <p>目前没有使用外部服务。</p>
          ))}
      </section>
    </div>
  );
}
