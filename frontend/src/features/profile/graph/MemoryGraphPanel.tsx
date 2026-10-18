import {
  Component,
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { Button, Dialog, EmptyState, Skeleton } from '../../../components/ui';
import { useMotionPreset } from '../../../design/motion';
import { api } from '../../../lib/api';
import { useMobile } from '../../../lib/useMobile';
import { usePersonaId } from '../../../lib/usePersonaState';
import { ItemCard } from '../ItemCard';
import type { ItemPage, ItemQuery, ItemSource, ProfileItem } from '../types';
import { useProfile, type ReviewedList } from '../useProfile';
import { itemsUrl, usePagedItems } from '../usePagedItems';
import {
  buildMemoryGraph,
  dimensionColorToken,
  endpointId,
  type GraphTwin,
  type MemoryNode,
} from './buildMemoryGraph';
import { useGraphPalette } from './rendering';

// The graph draws at most this many items, shared out between the dimensions so each one shows its
// best-supported items; search and the source drawer reach the rest and add what is opened.
const GRAPH_ITEMS = 360;
const MIN_PER_DIMENSION = 20;
const SEARCH_LIMIT = 20;
const SOURCE_PAGE = 50;

function useGraphItems(dimensionIds: string[] | null) {
  const personaId = usePersonaId();
  const [items, setItems] = useState<ProfileItem[]>([]);
  const [sources, setSources] = useState<Record<string, ItemSource>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const key = dimensionIds?.join(',') ?? null;
  useEffect(() => {
    if (key === null) return;
    const ids = key ? key.split(',') : [];
    const controller = new AbortController();
    const each = Math.max(
      MIN_PER_DIMENSION,
      Math.floor(GRAPH_ITEMS / Math.max(1, ids.length)),
    );
    setLoading(true);
    void Promise.all(
      ids.map((id) =>
        api<ItemPage>(
          itemsUrl(
            { dimension: [id], sort: 'evidence', with_sources: true },
            each,
          ),
          {
            signal: controller.signal,
            headers: { 'X-Twin-Persona': personaId },
          },
        ),
      ),
    )
      .then((pages) => {
        if (controller.signal.aborted) return;
        setItems(pages.flatMap((page) => page.items));
        setSources(Object.assign({}, ...pages.map((page) => page.sources)));
        setError('');
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setError(failure instanceof Error ? failure.message : '条目加载失败');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [key, personaId, attempt]);
  const replace = useCallback((item: ProfileItem) => {
    setItems((rows) =>
      item.review === 'rejected'
        ? rows.filter((row) => row.item_id !== item.item_id)
        : rows.map((row) => (row.item_id === item.item_id ? item : row)),
    );
  }, []);
  const reload = useCallback(async () => setAttempt((n) => n + 1), []);
  return { items, sources, loading, error, replace, reload };
}

const Graph3D = lazy(() => import('./Graph3D'));
const Graph2D = lazy(() => import('./Graph2D'));
class WebGLBoundary extends Component<
  { children: ReactNode; fallback: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
function supportsWebGL() {
  if (!window.WebGL2RenderingContext) return false;
  try {
    const gl = document.createElement('canvas').getContext('webgl2');
    if (!gl) return false;
    gl.getExtension('WEBGL_lose_context')?.loseContext();
    return true;
  } catch {
    return false;
  }
}

export default function MemoryGraphPanel({ twin }: { twin: GraphTwin }) {
  const profile = useProfile(true);
  const mobile = useMobile();
  const { reduced } = useMotionPreset();
  const palette = useGraphPalette();
  const [webgl] = useState(supportsWebGL);
  const [failed, setFailed] = useState(false);
  const [query, setQuery] = useState('');
  const [needle, setNeedle] = useState('');
  const [hiddenDimensions, setHiddenDimensions] = useState(new Set<string>());
  const [conflicted, setConflicted] = useState(false);
  const [hovered, setHovered] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [focus, setFocus] = useState<{ id: string; sequence: number } | null>(
    null,
  );
  // Items opened from search or a source that the graph did not draw yet.
  const [opened, setOpened] = useState<ProfileItem[]>([]);
  const host = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const summary = profile.summary;
  const dimensionIds = useMemo(
    () => summary?.dimensions.map((row) => row.dimension_id) ?? null,
    [summary],
  );
  const drawn = useGraphItems(dimensionIds);
  useEffect(() => {
    const timer = setTimeout(
      () => setNeedle(query.trim().toLocaleLowerCase()),
      250,
    );
    return () => clearTimeout(timer);
  }, [query]);
  const shownDimensions = dimensionIds?.filter(
    (id) => !hiddenDimensions.has(id),
  );
  // The chips and "only conflicts" narrow search and the source drawer on the server as well.
  const filters: ItemQuery = {
    ...(shownDimensions && shownDimensions.length < (dimensionIds?.length ?? 0)
      ? { dimension: shownDimensions }
      : {}),
    ...(conflicted ? { conflict: true } : {}),
  };
  const nothingShown = shownDimensions?.length === 0;
  const searchQuery =
    needle && !nothingShown
      ? { ...filters, q: needle, with_sources: true }
      : null;
  // usePagedItems compares queries by value, so a fresh object each render does not re-read.
  const search = usePagedItems(searchQuery, SEARCH_LIMIT);
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const resize = () =>
      setSize({ width: element.clientWidth, height: element.clientHeight });
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    resize();
    return () => observer.disconnect();
  }, []);
  const clear = useCallback(() => {
    setSelected(null);
    setHovered(null);
  }, []);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') clear();
    };
    window.addEventListener('keydown', escape);
    return () => window.removeEventListener('keydown', escape);
  }, [clear]);
  const items = useMemo(() => {
    const drawnIds = new Set(drawn.items.map((item) => item.item_id));
    return [
      ...drawn.items,
      ...opened.filter((item) => !drawnIds.has(item.item_id)),
    ];
  }, [drawn.items, opened]);
  const sources = useMemo(
    () =>
      Object.entries({ ...search.sources, ...drawn.sources }).map(
        ([source_id, source]) => ({ source_id, ...source }),
      ),
    [drawn.sources, search.sources],
  );
  const graph = useMemo(
    () => buildMemoryGraph(items, sources, twin),
    [items, sources, twin],
  );
  const nodes = useMemo(
    () => new Map(graph.nodes.map((node) => [node.id, node])),
    [graph],
  );
  const dimensions = (summary?.dimensions ?? []).map((row) => ({
    id: `dimension:${row.dimension_id}`,
    dimensionId: row.dimension_id,
    label: row.name,
    colorToken: dimensionColorToken(row.dimension_id),
  }));
  const eligibleItems = useMemo(
    () =>
      items.filter(
        (item) =>
          item.review !== 'rejected' &&
          !hiddenDimensions.has(item.dimension_id) &&
          (!conflicted || !!item.conflict.trim()),
      ),
    [items, hiddenDimensions, conflicted],
  );
  const visible = useMemo(() => {
    const ids = new Set([`twin:${twin.id}`]);
    for (const item of eligibleItems) {
      ids.add(`item:${item.item_id}`);
      ids.add(`dimension:${item.dimension_id}`);
      item.evidence.forEach((evidence) =>
        ids.add(`source:${evidence.source_id}`),
      );
    }
    return ids;
  }, [eligibleItems, twin.id]);
  const searching = !!searchQuery;
  const matches = useMemo(
    () => (searching ? search.items : []),
    [searching, search.items],
  );
  const adjacency = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const link of graph.links) {
      const a = endpointId(link.source),
        b = endpointId(link.target);
      if (!map.has(a)) map.set(a, new Set());
      if (!map.has(b)) map.set(b, new Set());
      map.get(a)!.add(b);
      map.get(b)!.add(a);
    }
    return map;
  }, [graph]);
  const activeId = hovered ?? selected;
  const highlighted = useMemo(() => {
    const matchIds = new Set<string>();
    for (const item of matches) {
      const id = `item:${item.item_id}`;
      matchIds.add(id);
      adjacency.get(id)?.forEach((neighbour) => matchIds.add(neighbour));
    }
    if (activeId && visible.has(activeId))
      return new Set([
        activeId,
        ...(adjacency.get(activeId) ?? []),
        ...matchIds,
      ]);
    return needle ? matchIds : null;
  }, [needle, matches, activeId, adjacency, visible]);
  const fly = (id: string) =>
    setFocus((previous) => ({ id, sequence: (previous?.sequence ?? 0) + 1 }));
  const click = (node: MemoryNode) => {
    setHovered(null);
    setSelected(node.id);
    fly(node.id);
  };
  const open = (item: ProfileItem) => {
    if (!items.some((row) => row.item_id === item.item_id))
      setOpened((rows) => [...rows, item]);
    const id = `item:${item.item_id}`;
    setHovered(null);
    setSelected(id);
    fly(id);
  };
  const selection =
    selected && visible.has(selected) ? nodes.get(selected) : undefined;
  const item = selection?.itemId
    ? items.find((item) => item.item_id === selection.itemId)
    : undefined;
  const sourceId = selection?.kind === 'source' ? selection.sourceId : null;
  const supported = usePagedItems(
    sourceId && !nothingShown ? { ...filters, source_id: sourceId } : null,
    SOURCE_PAGE,
  );
  const reviewed: ReviewedList = {
    replace: (row) => {
      drawn.replace(row);
      search.replace(row);
      supported.replace(row);
      setOpened((rows) =>
        row.review === 'rejected'
          ? rows.filter((other) => other.item_id !== row.item_id)
          : rows.map((other) => (other.item_id === row.item_id ? row : other)),
      );
    },
    reload: drawn.reload,
  };
  const graphProps = {
    graph,
    ...size,
    palette,
    visible,
    highlighted,
    labelled: activeId,
    focus,
    reduced,
    onHover: (node: MemoryNode | null) => setHovered(node?.id ?? null),
    onClick: click,
    onClear: clear,
    onFailure: () => setFailed(true),
  };
  const twoD = <Graph2D {...graphProps} />;
  const hasItems = graph.nodes.some((node) => node.kind === 'item');
  const total = (conflicted ? summary?.conflicts : summary?.total) ?? 0;
  const itemsError = profile.summaryError || drawn.error;
  const loadingItems = profile.loading || (drawn.loading && !hasItems);
  return (
    <div className="memory-graph-panel">
      <div className="memory-graph-controls" aria-label="图谱筛选">
        <form
          className="memory-graph-search"
          onSubmit={(event) => {
            event.preventDefault();
            if (matches[0]) open(matches[0]);
          }}
        >
          <input
            aria-label="搜索记忆和原话"
            placeholder="搜索记忆和原话…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <output aria-live="polite">
            {needle
              ? search.loading
                ? '搜索中…'
                : `${search.total} 条匹配`
              : eligibleItems.length < total
                ? `显示 ${eligibleItems.length} / ${total} 条记忆`
                : `${eligibleItems.length} 条记忆`}
          </output>
        </form>
        <div className="memory-graph-chips">
          {dimensions.map((node) => (
            <button
              key={node.id}
              type="button"
              aria-pressed={!hiddenDimensions.has(node.dimensionId!)}
              onClick={() =>
                setHiddenDimensions((previous) => {
                  const next = new Set(previous);
                  if (next.has(node.dimensionId!))
                    next.delete(node.dimensionId!);
                  else next.add(node.dimensionId!);
                  return next;
                })
              }
            >
              <i style={{ background: palette[node.colorToken] }} />
              {node.label}
            </button>
          ))}
          <button
            type="button"
            aria-pressed={conflicted}
            onClick={() => setConflicted(!conflicted)}
          >
            只看有矛盾
          </button>
        </div>
      </div>
      <div ref={host} className="memory-graph-viewport" aria-label="记忆图谱">
        {needle && matches.length > 0 && (
          <div className="memory-graph-results" aria-label="匹配的记忆">
            {matches.slice(0, 5).map((item) => (
              <button
                key={item.item_id}
                type="button"
                onClick={() => open(item)}
              >
                {item.statement}
              </button>
            ))}
          </div>
        )}
        {itemsError ? (
          <div className="memory-graph-notice" role="alert">
            {itemsError}
            <Button
              onClick={() => {
                void profile.refreshSummary();
                void drawn.reload();
              }}
            >
              重试
            </Button>
          </div>
        ) : !hasItems ? (
          <div className="memory-graph-notice">
            {loadingItems ? (
              <Skeleton className="h-24 w-64" />
            ) : (
              <EmptyState
                title="还不够了解你"
                body="添加一些记忆，让我慢慢认识你。"
              >
                <a href="#/profile?section=memories">添加记忆</a>
              </EmptyState>
            )}
          </div>
        ) : (
          size.width > 0 &&
          size.height > 0 && (
            <Suspense
              fallback={
                <div className="memory-graph-notice" role="status">
                  正在展开图谱…
                </div>
              }
            >
              {mobile || reduced || failed || !webgl ? (
                twoD
              ) : (
                <WebGLBoundary fallback={twoD}>
                  <Graph3D {...graphProps} />
                </WebGLBoundary>
              )}
            </Suspense>
          )
        )}
        {hasItems && !eligibleItems.length && (
          <p className="memory-graph-no-matches">当前筛选下没有记忆</p>
        )}
        <details className="memory-graph-legend">
          <summary role="button">图例</summary>
          <ul>
            {dimensions.map((node) => (
              <li key={node.id}>
                <i style={{ background: palette[node.colorToken] }} />
                {node.label}
              </li>
            ))}
            <li>● 本人说过或改过 · 实心发光</li>
            <li>○ 只有别人的说法 · 较暗空心</li>
            <li style={{ color: palette['--graph-danger'] }}>◎ 存在矛盾</li>
            <li>□ 资料来源</li>
          </ul>
        </details>
        <p className="memory-graph-hint">
          {mobile ? '双指缩放 · 拖动浏览' : '拖动探索 · 滚轮缩放'} ·
          点击节点查看
        </p>
      </div>
      <Dialog
        open={!!item || selection?.kind === 'source'}
        popover={!mobile}
        onOpenChange={(open) => {
          if (!open) clear();
        }}
        title={item ? '这条记忆' : (selection?.label ?? '资料')}
        onInteractOutside={(event) => {
          if (
            event.target instanceof Node &&
            host.current?.contains(event.target)
          )
            event.preventDefault();
        }}
        variant={mobile ? 'sheet' : 'drawer'}
        className={mobile ? 'memory-graph-sheet' : 'memory-graph-drawer'}
      >
        {item && (
          <ItemCard
            key={item.item_id}
            item={item}
            pending={profile.pending.has(item.item_id)}
            onReview={(row, status, statement) =>
              profile.review(row, status, statement, reviewed)
            }
            kindLabels={profile.coverage?.kind_labels ?? {}}
          />
        )}
        {selection?.kind === 'source' && (
          <>
            <p className="mb-3 text-sm text-secondary">
              {selection.date} · 支持 {supported.total} 条记忆
            </p>
            <ul className="space-y-3" aria-label="资料支持的记忆">
              {supported.items.map((item) => (
                <li key={item.item_id}>
                  <button
                    type="button"
                    className="w-full rounded-lg bg-surface p-3 text-left"
                    onClick={() => open(item)}
                  >
                    <span className="block break-words">{item.statement}</span>
                    <span className="text-xs text-secondary">
                      {item.evidence.find(
                        (evidence) => evidence.source_id === selection.sourceId,
                      )?.date ?? selection.date}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            {supported.error && (
              <p role="alert" className="mt-3 text-danger">
                {supported.error}{' '}
                <Button variant="ghost" onClick={() => void supported.reload()}>
                  重试
                </Button>
              </p>
            )}
            {supported.hasMore && (
              <Button
                variant="ghost"
                className="mt-3"
                loading={supported.loading}
                onClick={supported.loadMore}
              >
                再看{' '}
                {Math.min(
                  SOURCE_PAGE,
                  supported.total - supported.items.length,
                )}{' '}
                条
              </Button>
            )}
          </>
        )}
      </Dialog>
    </div>
  );
}
