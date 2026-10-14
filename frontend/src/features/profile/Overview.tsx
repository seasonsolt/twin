import { useState } from 'react';
import {
  Button,
  Card,
  EmptyState,
  Skeleton,
  Tabs,
  useConfirm,
} from '../../components/ui';
import { usePersonaId } from '../../lib/usePersonaState';
import type { ItemQuery } from './types';
import { ItemCard } from './ItemCard';
import { useProfile } from './useProfile';
import { ITEM_PAGE_SIZE, usePagedItems } from './usePagedItems';
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

const COLLAPSED = 5;

function DimensionItems({
  dimension,
  profile,
}: {
  dimension: { id: string; total: number; unreviewed: number };
  profile: ReturnType<typeof useProfile>;
}) {
  const [query] = useState<ItemQuery>(() => ({ dimension: [dimension.id] }));
  const page = usePagedItems(query);
  const [expanded, setExpanded] = useState(false);
  const confirm = useConfirm();
  const confirmAll = async () => {
    if (
      (await confirm({
        title: `确认这 ${dimension.unreviewed} 条？`,
        body: '确认后，分身回答时会优先依据它们。可以随时逐条撤销。',
        confirmLabel: '全部确认',
      })) &&
      (await profile.confirmDimension(dimension.id))
    )
      await page.reload();
  };
  const shown = expanded ? page.items : page.items.slice(0, COLLAPSED);
  const remaining = page.total - shown.length;
  return (
    <div className="space-y-2 md:space-y-3">
      {dimension.unreviewed > 0 && (
        <div className="flex justify-end">
          <Button
            variant="secondary"
            size="sm"
            loading={profile.batchBusy}
            disabled={profile.pending.size > 0}
            onClick={() => void confirmAll()}
          >
            全部确认（{dimension.unreviewed}）
          </Button>
        </div>
      )}
      {page.error && (
        <p role="alert" className="text-danger">
          {page.error}{' '}
          <Button variant="ghost" onClick={() => void page.reload()}>
            重试
          </Button>
        </p>
      )}
      {shown.map((item) => (
        <ItemCard
          key={item.item_id}
          item={item}
          pending={profile.pending.has(item.item_id)}
          onReview={(reviewed, status, statement) =>
            profile.review(reviewed, status, statement, page)
          }
          kindLabels={profile.coverage?.kind_labels ?? {}}
        />
      ))}
      {page.loading && <Skeleton className="h-24" />}
      <div className="flex flex-wrap gap-2">
        {!page.loading && remaining > 0 && (
          <Button
            variant="ghost"
            aria-expanded={expanded}
            onClick={() => {
              if (expanded) page.loadMore();
              else setExpanded(true);
            }}
          >
            {expanded
              ? `再看 ${Math.min(remaining, ITEM_PAGE_SIZE)} 条（还有 ${remaining} 条）`
              : `展开其余 ${remaining} 条`}
          </Button>
        )}
        {expanded && (
          <Button
            variant="ghost"
            aria-expanded
            onClick={() => setExpanded(false)}
          >
            收起
          </Button>
        )}
      </div>
    </div>
  );
}

export function Overview() {
  const personaId = usePersonaId();
  const profile = useProfile(true);
  const dimensions = (profile.summary?.dimensions ?? []).map((row) => ({
    id: row.dimension_id,
    title: topics[row.dimension_id] ?? row.name,
    total: row.total,
    unreviewed: row.unreviewed,
  }));
  const total = profile.summary?.total ?? 0;
  const unreviewed = profile.summary?.unreviewed ?? 0;
  const defaultDimension =
    dimensions.find((dimension) => dimension.unreviewed > 0) ?? dimensions[0];
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
        {profile.summaryError && (
          <p role="alert" className="text-danger">
            {profile.summaryError}{' '}
            <Button
              variant="ghost"
              onClick={() => void profile.refreshSummary()}
            >
              重试
            </Button>
          </p>
        )}
        {profile.summary && !dimensions.length && (
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
        {dimensions.length > 0 && (
          <div className="min-w-0">
            <p className="mb-3 text-sm text-secondary">
              共 {total} 条，其中 {unreviewed} 条待你确认
            </p>
            <Tabs
              key={personaId}
              scrollable
              defaultValue={defaultDimension.id}
              items={dimensions.map((dimension) => ({
                value: dimension.id,
                label: (
                  <>
                    {dimension.title} {dimension.total}
                    {dimension.unreviewed > 0 && (
                      <span className="ml-1 text-xs opacity-70">
                        {' · '}
                        {dimension.unreviewed} 待确认
                      </span>
                    )}
                  </>
                ),
                content: (
                  <DimensionItems
                    key={`${personaId}-${dimension.id}`}
                    dimension={dimension}
                    profile={profile}
                  />
                ),
              }))}
            />
          </div>
        )}
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
