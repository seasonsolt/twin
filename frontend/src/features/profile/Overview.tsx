import { useState } from 'react';
import {
  Button,
  Card,
  EmptyState,
  Input,
  Skeleton,
  Tabs,
} from '../../components/ui';
import { usePersonaId } from '../../lib/usePersonaState';
import type { ItemQuery } from './types';
import { ItemCard } from './ItemCard';
import { useItemSearch } from './useItemSearch';
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

type Profile = ReturnType<typeof useProfile>;

/** Items matching a fixed query: the first few, then more a page at a time. */
function ItemList({ query, profile }: { query: ItemQuery; profile: Profile }) {
  const page = usePagedItems(query);
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? page.items : page.items.slice(0, COLLAPSED);
  const remaining = page.total - shown.length;
  return (
    <div className="space-y-2 md:space-y-3">
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

/** What the twin would draw on for a search, best first, each ready to correct or remove. */
function SearchResults({
  search,
  profile,
}: {
  search: ReturnType<typeof useItemSearch>;
  profile: Profile;
}) {
  return (
    <section aria-label="搜索结果" className="space-y-2 md:space-y-3">
      {search.error && (
        <p role="alert" className="text-danger">
          {search.error}{' '}
          <Button variant="ghost" onClick={() => void search.reload()}>
            重试
          </Button>
        </p>
      )}
      {search.loading && !search.items.length && <Skeleton className="h-24" />}
      {!search.loading && !search.error && !search.items.length && (
        <p className="text-sm text-secondary">没找到相关的记忆</p>
      )}
      {search.items.map((item) => (
        <ItemCard
          key={item.item_id}
          item={item}
          pending={profile.pending.has(item.item_id)}
          onReview={(reviewed, status, statement) =>
            profile.review(reviewed, status, statement, search)
          }
          kindLabels={profile.coverage?.kind_labels ?? {}}
        />
      ))}
    </section>
  );
}

const conflictQuery: ItemQuery = { conflict: true };

function DimensionItems({
  dimensionId,
  profile,
}: {
  dimensionId: string;
  profile: Profile;
}) {
  const [query] = useState<ItemQuery>(() => ({ dimension: [dimensionId] }));
  return <ItemList query={query} profile={profile} />;
}

export function Overview() {
  const personaId = usePersonaId();
  const profile = useProfile(true);
  const dimensions = (profile.summary?.dimensions ?? []).map((row) => ({
    id: row.dimension_id,
    title: topics[row.dimension_id] ?? row.name,
    total: row.total,
  }));
  const total = profile.summary?.total ?? 0;
  const conflicts = profile.summary?.conflicts ?? 0;
  const [text, setText] = useState('');
  const [showConflicts, setShowConflicts] = useState(false);
  const search = useItemSearch(text);
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
          <div className="min-w-0 space-y-3">
            <p className="text-sm text-secondary">
              共 {total} 条，回答时都会用到。哪条不对，搜一下改掉或删掉。
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <Input
                type="search"
                aria-label="搜索记忆"
                placeholder="搜一件事，比如：怎么看加班"
                value={text}
                maxLength={200}
                onChange={(event) => setText(event.target.value)}
                className="min-w-0 flex-1 basis-56"
              />
              {conflicts > 0 && !search.query && (
                <Button
                  variant="ghost"
                  size="sm"
                  aria-pressed={showConflicts}
                  onClick={() => setShowConflicts(!showConflicts)}
                >
                  有矛盾的 {conflicts} 条
                </Button>
              )}
            </div>
            {search.query ? (
              <SearchResults search={search} profile={profile} />
            ) : showConflicts && conflicts > 0 ? (
              <section aria-label="有矛盾的记忆">
                <ItemList
                  key={`${personaId}-conflicts`}
                  query={conflictQuery}
                  profile={profile}
                />
              </section>
            ) : (
              <Tabs
                key={personaId}
                scrollable
                defaultValue={dimensions[0].id}
                items={dimensions.map((dimension) => ({
                  value: dimension.id,
                  label: `${dimension.title} ${dimension.total}`,
                  content: (
                    <DimensionItems
                      key={`${personaId}-${dimension.id}`}
                      dimensionId={dimension.id}
                      profile={profile}
                    />
                  ),
                }))}
              />
            )}
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
