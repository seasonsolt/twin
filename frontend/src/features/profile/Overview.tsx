import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';
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
  toast,
  type AspectLayer,
} from '../../components/ui';
import { AspectConstellation } from '../../components/effects';
import { api } from '../../lib/api';
import { basePath } from '../../lib/base';
import { usePersonaId, usePersonaState } from '../../lib/usePersonaState';
import { usePolling } from '../../lib/usePolling';
import type { ItemQuery } from './types';
import { ItemRow } from './ItemRow';
import { useItemSearch } from './useItemSearch';
import { useProfile } from './useProfile';
import { MemoryUpdating } from '../memories/BuildProgress';
import { FillDialog, type FillScope } from '../fill/FillDialog';
import { LifeStory } from './LifeStory';
import { Observations } from './Observations';
import { usePersonaEdition } from '../../stores/auth';
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
  D10: '存在与意义',
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
  D10: '想留下什么，怎样面对失去，价值和意义寄托在哪里',
};
/** The ten aspects in reading order: who they are inside (and what it means to them), how that shows, and the life
 * around them. */
const layers: { label: string; layer: AspectLayer; ids: string[] }[] = [
  { label: '内核', layer: 'core', ids: ['D2', 'D10', 'D4', 'D3'] },
  { label: '外显', layer: 'outer', ids: ['D6', 'D7', 'D5'] },
  { label: '处境', layer: 'context', ids: ['D1', 'D8', 'D9'] },
];
const order = layers.flatMap((group) => group.ids);
const ASPECTS = '十个方面';
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
            aria-label={
              expanded
                ? `再看 ${Math.min(remaining, ITEM_PAGE_SIZE)} 条，还有 ${remaining} 条`
                : undefined
            }
            onClick={() => {
              if (expanded) page.loadMore();
              else setExpanded(true);
            }}
          >
            {expanded
              ? `再看 ${Math.min(remaining, ITEM_PAGE_SIZE)} 条`
              : `再看 ${remaining} 条`}
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
      <Stack as="ol" gap={2} aria-label="最有把握的几点">
        {top.map((item) => (
          <Row as="li" key={item.item_id} gap={2} align="baseline">
            <LevelDots level={3} max={1} layer={layerOf(item.dimension_id)} />
            <Text size="sm" twoLines className="min-w-0 break-words">
              {item.statement}
            </Text>
          </Row>
        ))}
      </Stack>
    </Stack>
  );
}

/** Who can be asked to fill in the aspects: the person behind the twin, seen by someone who is not them, and the
 * address of their page, where the link leads. */
export interface AskPerson {
  name: string;
  path: string;
}

/** The words to send the person, with the link that opens 补一补 on the aspect. */
function askText(person: AskPerson, aspect: string) {
  const link = `${window.location.origin}${basePath()}/#${person.path}${person.path.includes('?') ? '&' : '?'}fill=${aspect}`;
  return `${person.name}，团队里关于你的「${topics[aspect]}」还了解得不够。方便时点这里补几句：${link}`;
}

/** One aspect: what it covers, how well each of its facets is known, and the memories behind it. */
function Aspect({
  id,
  total,
  facets,
  levelLabels,
  profile,
  onFill,
  ask,
}: {
  id: string;
  total: number;
  facets: Facet[];
  levelLabels: string[];
  profile: Profile;
  /** Opens 补一补 for this aspect; absent where the viewer is not the person. */
  onFill?: (scope: FillScope) => void;
  /** Where the viewer is not the person: the one to ask to fill this aspect in. */
  ask?: AskPerson;
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
        {/* An empty aspect says what it waits to learn; one with memories shows them instead. */}
        {total === 0 && (
          <Text size="sm" tone="secondary">
            {blurbs[id]}
          </Text>
        )}
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
        <Card variant="soft" padding="md">
          <Text size="sm">还不了解这一面。</Text>
        </Card>
      )}
      {ask && (
        <TextLink
          size="sm"
          onClick={() => {
            const text = askText(ask, id);
            void navigator.clipboard.writeText(text).then(
              () => toast(`已复制，发给${ask.name}`, 'success'),
              () => toast(text, 'info', 15000),
            );
          }}
        >
          请{ask.name}补充 ›
        </TextLink>
      )}
    </Stack>
  );
}

export function Overview({ ask }: { ask?: AskPerson }) {
  const personaId = usePersonaId();
  // The persona edition shows the ten aspects as a constellation around the twin, on glass over the page's glow.
  const sutai = usePersonaEdition();
  const surface = sutai ? 'glass' : undefined;
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
  // What 补一补 stored becomes memories only when the build that follows is done: until then the page waits, and
  // reads the counts and levels again once the build is idle.
  const [building, setBuilding] = usePersonaState(false);
  const settle = useCallback(async () => {
    try {
      const view = await api<{ state: string }>('/api/persona/processing', {
        headers: { 'X-Twin-Persona': personaId },
      });
      if (view.state !== 'idle') return;
      setBuilding(false);
      void refreshSummary();
      void refreshCoverage();
      void useStatus.getState().refresh();
    } catch {
      // The next poll tries again.
    }
  }, [personaId, setBuilding, refreshSummary, refreshCoverage]);
  usePolling(settle, building ? 3000 : 0);
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
  // 补一补 is open: for what the twin knows least, or for one aspect; in the persona edition the person is asked
  // about their life instead, stage by stage (人生回顾).
  const [filling, setFilling] = useState<FillScope | null>(null);
  const reviewing = sutai && profile.canTier;
  // What was told, laid out by year (生命叙事), beside the page.
  const [story, setStory] = useState(false);
  // A few observations held up to the person (剖析观察), beside the page.
  const [observing, setObserving] = useState(false);
  // A link from a colleague asking for more of one aspect opens 补一补 on it, for the person it is meant for.
  const [params, setParams] = useSearchParams();
  const requested = params.get('fill');
  useEffect(() => {
    if (!requested || !profile.canTier) return;
    if (requested in topics) setFilling({ dimension: requested });
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.delete('fill');
        return next;
      },
      { replace: true },
    );
  }, [requested, profile.canTier, setParams]);
  const search = useItemSearch(text);
  const selected =
    chosen ?? aspects.find((aspect) => aspect.total > 0)?.id ?? order[0];
  // The aspects the twin most wants to know more of, in the order it would collect them.
  const wantedIds = [
    ...new Set(
      (profile.coverage?.suggestions ?? [])
        .map(
          (suggestion) =>
            profile.coverage?.facets.find(
              (facet) => facet.facet_id === suggestion.facet_id,
            )?.dimension_id ?? `D${suggestion.facet_id.split('.')[0]}`,
        )
        .filter((id) => id in topics),
    ),
  ].slice(0, 5);
  const wanted = wantedIds.map((id) => topics[id]);
  const empty = !!profile.summary && total === 0;
  return (
    <div className="about-knowledge space-y-4 md:space-y-6">
      <Card padding="roomy" variant={surface} className="space-y-6">
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
            {sutai ? (
              <div className="relative size-64 shrink-0">
                <AspectConstellation
                  aspects={aspects}
                  selected={selected}
                  onSelect={setChosen}
                  label={`${ASPECTS}的星图，已了解 ${known} 个`}
                  className="size-full"
                />
                <Text
                  as="span"
                  size="xs"
                  tone="secondary"
                  align="center"
                  className="pointer-events-none absolute inset-x-0 bottom-1"
                >
                  {known}/{aspects.length} 个方面
                </Text>
              </div>
            ) : (
              <AspectRing
                label={`${ASPECTS}里已了解 ${known} 个`}
                segments={aspects.map((aspect) => ({
                  layer: layerOf(aspect.id),
                  level: aspect.level,
                }))}
              >
                <Text size="xl" weight="semibold">
                  {known}/{aspects.length}
                </Text>
                <Text size="xs" tone="secondary">
                  个方面
                </Text>
              </AspectRing>
            )}
            <Stack gap={4} grow>
              <Stack gap={1}>
                <Heading level={3}>
                  {profile.canTier ? '我了解到的你' : '我了解到的他'}
                </Heading>
                {empty && (
                  <EmptyState
                    title={profile.canTier ? '还不够了解你' : '还不够了解他'}
                    body={
                      profile.canTier
                        ? '回答几个问题，或添加一些记忆，让我慢慢认识你。'
                        : '添加一些记忆，让我慢慢认识他。'
                    }
                  >
                    {/* The person is offered 补一补 just below; anyone else adds the memories. */}
                    {!profile.canTier && (
                      <TextLink to="?section=memories">添加记忆</TextLink>
                    )}
                  </EmptyState>
                )}
              </Stack>
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
        {((wanted.length > 0 && (!empty || profile.canTier)) || reviewing) && (
          <Row gap={3} wrap>
            {wanted.length > 0 && (
              <Text as="span" size="sm" tone="secondary">
                了解得还少：{wanted.join('、')}
              </Text>
            )}
            {reviewing ? (
              <>
                <Button size="sm" onClick={() => setFilling({ life: true })}>
                  回顾人生
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-haspopup="dialog"
                  onClick={() => setStory(true)}
                >
                  看生命线
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-haspopup="dialog"
                  onClick={() => setObserving(true)}
                >
                  看剖析
                </Button>
              </>
            ) : profile.canTier ? (
              <Button
                size="sm"
                onClick={() => setFilling({ otherwise: wantedIds[0] })}
              >
                补一补
              </Button>
            ) : (
              // Where someone can be asked, each aspect below says so; otherwise the memories are added here.
              !ask && (
                <TextLink to="?section=memories" size="sm">
                  添加记忆
                </TextLink>
              )
            )}
          </Row>
        )}
      </Card>
      {profile.summary && !empty && (
        <Card
          padding="roomy"
          variant={surface}
          aria-label={ASPECTS}
          className="space-y-4"
        >
          <Toolbar stackOnMobile>
            <Heading level={3}>{ASPECTS}</Heading>
            <Row gap={2}>
              <Input
                type="search"
                aria-label="搜索记忆"
                placeholder="搜记忆"
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
                  看矛盾 {conflicts} 条
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
              label={ASPECTS}
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
                        <LevelDots
                          level={aspect.level}
                          layer={group.layer}
                          label={levelNames[aspect.level]}
                        />
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
                ask={profile.canTier ? undefined : ask}
              />
            </SideTabs>
          )}
        </Card>
      )}
      <FillDialog
        open={filling !== null}
        onOpenChange={(open) => !open && setFilling(null)}
        scope={filling ?? undefined}
        onKept={() => setBuilding(true)}
      />
      {reviewing && <LifeStory open={story} onOpenChange={setStory} />}
      {reviewing && (
        <Observations open={observing} onOpenChange={setObserving} />
      )}
    </div>
  );
}
