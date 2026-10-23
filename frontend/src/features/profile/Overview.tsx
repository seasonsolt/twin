import { useEffect, useRef, useState } from 'react';
import {
  AspectRing,
  Badge,
  Button,
  Card,
  EmptyState,
  Heading,
  Input,
  LevelDots,
  Row,
  SideTabs,
  Skeleton,
  Stack,
  Text,
  TextLink,
  Toolbar,
  type AspectLayer,
} from '../../components/ui';
import { usePersonaId, usePersonaState } from '../../lib/usePersonaState';
import type { ItemQuery } from './types';
import { ItemRow } from './ItemRow';
import { useItemSearch } from './useItemSearch';
import { useProfile } from './useProfile';
import { MemoryUpdating } from '../memories/BuildProgress';
import { FillDialog, type FillScope } from '../fill/FillDialog';
import { useStatus } from '../../stores/status';
import { ITEM_PAGE_SIZE, usePagedItems } from './usePagedItems';

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

/** What each aspect covers, in a line, so an empty one still says what it is waiting to learn. */
const blurbs: Record<string, string> = {
  D1: '现在的身份、重要的经历，和常讲给别人听的故事',
  D2: '做事时实际看重什么，不愿放弃的底线和原则',
  D3: '面对选择时怎么权衡、靠什么拿主意、什么时候拍板',
  D4: '面对复杂问题怎么拆、先问什么、常用什么类比',
  D5: '有把握的本领，对熟悉领域的看法，和自认不懂的地方',
  D6: '用词和口头禅、句式结构，对不同的人怎么说话',
  D7: '怎么和人相处、帮助别人、一起做事和处理分歧',
  D8: '这段时间的重点、正在做的事和还没想清楚的问题',
  D9: '兴趣爱好、作息习惯、家庭和各种偏好',
};
/** The nine aspects in reading order: who they are inside, how that shows, and the life around them. */
const layers: { label: string; layer: AspectLayer; ids: string[] }[] = [
  { label: '内核', layer: 'core', ids: ['D2', 'D4', 'D3'] },
  { label: '外显', layer: 'outer', ids: ['D6', 'D7', 'D5'] },
  { label: '处境', layer: 'context', ids: ['D1', 'D8', 'D9'] },
];
const order = layers.flatMap((group) => group.ids);
const layerOf = (id: string) =>
  layers.find((group) => group.ids.includes(id))?.layer ?? 'core';
// How well something is known, in words: the four levels the server counts, each more than the last. A facet whose
// answers also held up when checked carries a tick after the last (``checked``).
const levelNames = ['还不了解', '提到过', '了解一些', '了解较多'];
const CHECKED_MARK = ' ✓';

const COLLAPSED = 5;
const TOP = 3;

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
        <ItemRow
          key={item.item_id}
          item={item}
          pending={profile.pending.has(item.item_id)}
          onReview={(reviewed, status, statement) =>
            profile.review(reviewed, status, statement, page)
          }
          onTier={
            profile.canTier
              ? (changed, tier) => profile.tier(changed, tier, page)
              : undefined
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
        <Text size="sm" tone="secondary">
          没找到相关的记忆
        </Text>
      )}
      {search.items.map((item) => (
        <ItemRow
          key={item.item_id}
          item={item}
          pending={profile.pending.has(item.item_id)}
          onReview={(reviewed, status, statement) =>
            profile.review(reviewed, status, statement, search)
          }
          onTier={
            profile.canTier
              ? (changed, tier) => profile.tier(changed, tier, search)
              : undefined
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

type Facet = NonNullable<Profile['coverage']>['facets'][number];

/** How well an aspect is known: the rounded mean of its facets, at least "some" once anything is known. */
function aspectLevel(facets: Facet[], total: number) {
  if (!facets.length) return total > 0 ? 1 : 0;
  const levels = facets.map((facet) => facet.level ?? 0);
  if (!levels.some((level) => level > 0)) return total > 0 ? 1 : 0;
  const mean = levels.reduce((sum, level) => sum + level, 0) / levels.length;
  return Math.max(1, Math.min(3, Math.round(mean)));
}

/** The few memories resting on the most occasions: what the twin is surest of. */
function Surest({ revision }: { revision: unknown }) {
  const [query] = useState<ItemQuery>(() => ({ sort: 'evidence' }));
  const page = usePagedItems(query, TOP);
  const seen = useRef(revision);
  const { reload } = page;
  // Every saved correction or removal re-reads the summary; re-read these too so none shows old wording.
  useEffect(() => {
    if (seen.current === revision) return;
    seen.current = revision;
    void reload();
  }, [revision, reload]);
  const top = page.items.slice(0, TOP);
  if (!top.length) return null;
  return (
    <Stack gap={2}>
      <Text size="sm" weight="medium">
        最有把握的几点
      </Text>
      <Stack as="ol" gap={2} aria-label="最有把握的几点">
        {top.map((item) => (
          <Row as="li" key={item.item_id} gap={2} align="baseline">
            <LevelDots level={3} max={1} layer={layerOf(item.dimension_id)} />
            <Text size="sm" className="min-w-0 break-words">
              {item.statement}
              <Text as="span" size="xs" tone="tertiary">
                {' '}
                · {topics[item.dimension_id] ?? item.dimension_name}
              </Text>
            </Text>
          </Row>
        ))}
      </Stack>
    </Stack>
  );
}

/** One aspect: what it covers, how well each of its facets is known, and the memories behind it. */
function Aspect({
  id,
  total,
  facets,
  levelLabels,
  profile,
  onFill,
}: {
  id: string;
  total: number;
  facets: Facet[];
  levelLabels: string[];
  profile: Profile;
  /** Opens 补一补 for this aspect; absent where the viewer is not the person. */
  onFill?: (scope: FillScope) => void;
}) {
  const personaId = usePersonaId();
  const layer = layerOf(id);
  const level = aspectLevel(facets, total);
  const named = facets.filter((facet) => facet.name);
  return (
    <Stack gap={4}>
      <Stack gap={1}>
        <Row gap={3} wrap align="baseline">
          <Heading level={4} size="section">
            {topics[id]}
          </Heading>
          <Text as="span" size="sm" tone="secondary">
            {levelLabels[level]}
            {total > 0 && ` · ${total} 条`}
          </Text>
          {onFill && level <= 1 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onFill({ dimension: id })}
            >
              补一补
            </Button>
          )}
        </Row>
        <Text size="sm" tone="secondary">
          {blurbs[id]}
        </Text>
      </Stack>
      {named.length > 0 && (
        <Row as="ul" gap={2} wrap aria-label={`${topics[id]}包括`}>
          {named.map((facet) => (
            <li key={facet.facet_id}>
              <Badge>
                {facet.name}
                <LevelDots
                  level={facet.level ?? 0}
                  layer={layer}
                  label={`${levelLabels[facet.level ?? 0]}${facet.checked ? CHECKED_MARK : ''}`}
                />
              </Badge>
            </li>
          ))}
        </Row>
      )}
      {total > 0 ? (
        <DimensionItems
          key={`${personaId}-${id}`}
          dimensionId={id}
          profile={profile}
        />
      ) : (
        <Card variant="soft" padding="md" className="space-y-2">
          <Text size="sm">还不了解这一面。</Text>
          <TextLink to="?section=memories">{suggestions[id]}</TextLink>
        </Card>
      )}
    </Stack>
  );
}

export function Overview() {
  const personaId = usePersonaId();
  const profile = useProfile(true);
  // Made from the recording library and catching up with changed recordings: the profile waits for the update.
  const updating = !!useStatus((state) => state.data?.memory_updating);
  const { refreshSummary, refreshCoverage } = profile;
  const wasUpdating = useRef(updating);
  useEffect(() => {
    if (wasUpdating.current && !updating) {
      void refreshSummary();
      void refreshCoverage();
    }
    wasUpdating.current = updating;
  }, [updating, refreshSummary, refreshCoverage]);
  const counts = new Map(
    (profile.summary?.dimensions ?? []).map((row) => [
      row.dimension_id,
      row.total,
    ]),
  );
  const facetsOf = (id: string) =>
    (profile.coverage?.facets ?? []).filter(
      (facet) => facet.dimension_id === id,
    );
  const aspects = order.map((id) => {
    const total = counts.get(id) ?? 0;
    return { id, total, level: aspectLevel(facetsOf(id), total) };
  });
  const known = aspects.filter((aspect) => aspect.level > 0).length;
  const total = profile.summary?.total ?? 0;
  const conflicts = profile.summary?.conflicts ?? 0;
  const [text, setText] = useState('');
  const [showConflicts, setShowConflicts] = useState(false);
  const [chosen, setChosen] = usePersonaState<string | null>(null);
  // 补一补 is open: for what the twin knows least, or for one aspect.
  const [filling, setFilling] = useState<FillScope | null>(null);
  const search = useItemSearch(text);
  const selected =
    chosen ?? aspects.find((aspect) => aspect.total > 0)?.id ?? order[0];
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
  const empty = !!profile.summary && total === 0;
  return (
    <div className="about-knowledge space-y-4 md:space-y-6">
      <Card padding="roomy" className="space-y-6">
        {profile.loading && <Skeleton className="h-40" />}
        {updating && <MemoryUpdating />}
        {profile.summaryError && !updating && (
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
        {profile.summary && (
          <Toolbar stackOnMobile gap={6}>
            <AspectRing
              label={`九个方面里已了解 ${known} 个`}
              segments={aspects.map((aspect) => ({
                layer: layerOf(aspect.id),
                level: aspect.level,
              }))}
            >
              <Text size="xl" weight="semibold">
                {known}/9
              </Text>
              <Text size="xs" tone="secondary">
                个方面
              </Text>
            </AspectRing>
            <Stack gap={4} grow>
              <Stack gap={1}>
                <Heading level={3}>我了解到的他</Heading>
                {empty ? (
                  <EmptyState
                    title="还不够了解你"
                    body="添加一些记忆，让我慢慢认识你。"
                  >
                    <TextLink to="?section=memories">添加记忆</TextLink>
                  </EmptyState>
                ) : (
                  <Text size="sm" tone="secondary">
                    共 {total}{' '}
                    条记忆，回答时都会用到。哪条不对，在下面改掉或删掉。
                  </Text>
                )}
              </Stack>
              <Row gap={4} wrap aria-hidden>
                {layers.map((group) => (
                  <Row key={group.layer} gap={2}>
                    <LevelDots level={1} max={1} layer={group.layer} />
                    <Text as="span" size="xs" tone="secondary">
                      {group.label}
                    </Text>
                  </Row>
                ))}
              </Row>
              {!empty && <Surest key={personaId} revision={profile.summary} />}
            </Stack>
          </Toolbar>
        )}
        {profile.coverageError && !updating && (
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
        {(wanted.length > 0 || profile.summary) && (
          <Row gap={3} wrap>
            <Text as="span" size="sm" tone="secondary">
              这几个方面分身还不了解，或只提到过：
            </Text>
            {wanted.map((text) => (
              <TextLink key={text} to="?section=memories" size="sm">
                {text}
              </TextLink>
            ))}
            {profile.canTier && (
              <Button size="sm" onClick={() => setFilling({})}>
                补一补
              </Button>
            )}
          </Row>
        )}
      </Card>
      {profile.summary && !empty && (
        <Card padding="roomy" aria-label="九个方面" className="space-y-4">
          <Toolbar stackOnMobile>
            <Heading level={3}>九个方面</Heading>
            <Row gap={2}>
              <Input
                type="search"
                aria-label="搜索记忆"
                placeholder="搜一件事，比如：怎么看加班"
                value={text}
                maxLength={200}
                onChange={(event) => setText(event.target.value)}
                className="min-w-0 flex-1 md:w-64"
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
            </Row>
          </Toolbar>
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
            <SideTabs
              label="九个方面"
              value={selected}
              onValueChange={setChosen}
              groups={layers.map((group) => ({
                label: group.label,
                layer: group.layer,
                items: group.ids.map((id) => {
                  const aspect = aspects.find((row) => row.id === id)!;
                  return {
                    value: id,
                    label: topics[id],
                    trailing: (
                      <Row gap={2}>
                        {aspect.total > 0 && (
                          <Text as="span" size="xs" tone="tertiary">
                            {aspect.total}
                          </Text>
                        )}
                        <LevelDots level={aspect.level} layer={group.layer} />
                      </Row>
                    ),
                  };
                }),
              }))}
            >
              <Aspect
                key={`${personaId}-${selected}`}
                id={selected}
                total={counts.get(selected) ?? 0}
                facets={facetsOf(selected)}
                levelLabels={levelNames}
                profile={profile}
                onFill={profile.canTier ? setFilling : undefined}
              />
            </SideTabs>
          )}
        </Card>
      )}
      <FillDialog
        open={filling !== null}
        onOpenChange={(open) => !open && setFilling(null)}
        scope={filling ?? undefined}
        onKept={() => {
          void refreshSummary();
          void refreshCoverage();
        }}
      />
    </div>
  );
}
