import { Button, Card, EmptyState, Skeleton } from '../../components/ui';
import { ItemCard } from './ItemCard';
import { useProfile } from './useProfile';
import { useStatus } from '../../stores/status';

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

export function Overview() {
  const profile = useProfile(true);
  const status = useStatus((state) => state.data);
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
    <div className="about-knowledge space-y-4 md:space-y-6">
      <Card className="p-4 md:p-6">
        <h3 className="mb-3 text-md font-semibold md:mb-4 md:text-lg">
          我了解到的他
        </h3>
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
            <a
              href="#/profile?section=memories"
              className="text-accent underline"
            >
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
                <h4 className="text-sm font-semibold text-secondary">
                  {title}
                </h4>
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
        <h3 className="mb-3 text-md font-semibold md:text-lg">还想多了解</h3>
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
              <a
                className="text-accent underline"
                href="#/profile?section=memories"
              >
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
        <h3 className="font-medium">外部服务</h3>
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
