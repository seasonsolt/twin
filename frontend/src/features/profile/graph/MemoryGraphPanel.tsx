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
import { useProfile } from '../useProfile';
import {
  buildMemoryGraph,
  endpointId,
  type GraphSource,
  type GraphTwin,
  type MemoryNode,
} from './buildMemoryGraph';
import { useGraphPalette } from './rendering';

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
  const personaId = usePersonaId();
  const profile = useProfile(true);
  const mobile = useMobile();
  const { reduced } = useMotionPreset();
  const palette = useGraphPalette();
  const [webgl] = useState(supportsWebGL);
  const [failed, setFailed] = useState(false);
  const [sources, setSources] = useState<GraphSource[]>([]);
  const [sourceError, setSourceError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState('');
  const [hiddenDimensions, setHiddenDimensions] = useState(new Set<string>());
  const [unreviewed, setUnreviewed] = useState(false);
  const [hovered, setHovered] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [focus, setFocus] = useState<{ id: string; sequence: number } | null>(
    null,
  );
  const host = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const controller = new AbortController();
    void api<GraphSource[]>('/api/persona/sources', {
      signal: controller.signal,
      headers: { 'X-Twin-Persona': personaId },
    })
      .then((rows) => {
        if (!controller.signal.aborted) {
          setSources(rows);
          setSourceError('');
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setSourceError(
            error instanceof Error ? error.message : '资料加载失败',
          );
      });
    return () => controller.abort();
  }, [personaId, attempt]);
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
  const graph = useMemo(
    () => buildMemoryGraph(profile.items, sources, twin),
    [profile.items, sources, twin],
  );
  const nodes = useMemo(
    () => new Map(graph.nodes.map((node) => [node.id, node])),
    [graph],
  );
  const dimensions = graph.nodes.filter((node) => node.kind === 'dimension');
  const eligibleItems = useMemo(
    () =>
      profile.items.filter(
        (item) =>
          item.review !== 'rejected' &&
          !hiddenDimensions.has(item.dimension_id) &&
          (!unreviewed || item.review === 'unreviewed'),
      ),
    [profile.items, hiddenDimensions, unreviewed],
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
  const needle = query.trim().toLocaleLowerCase();
  const matches = useMemo(
    () =>
      needle
        ? eligibleItems.filter(
            (item) =>
              item.statement.toLocaleLowerCase().includes(needle) ||
              item.evidence.some((evidence) =>
                evidence.quote.toLocaleLowerCase().includes(needle),
              ),
          )
        : [],
    [eligibleItems, needle],
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
  const selection =
    selected && visible.has(selected) ? nodes.get(selected) : undefined;
  const item = selection?.itemId
    ? profile.items.find((item) => item.item_id === selection.itemId)
    : undefined;
  const supported =
    selection?.kind === 'source'
      ? eligibleItems.filter((item) =>
          item.evidence.some(
            (evidence) => evidence.source_id === selection.sourceId,
          ),
        )
      : [];
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
  return (
    <div className="memory-graph-panel">
      <div className="memory-graph-controls" aria-label="图谱筛选">
        <form
          className="memory-graph-search"
          onSubmit={(event) => {
            event.preventDefault();
            if (matches[0]) click(nodes.get(`item:${matches[0].item_id}`)!);
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
              ? `${matches.length} 条匹配`
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
            aria-pressed={unreviewed}
            onClick={() => setUnreviewed(!unreviewed)}
          >
            只看待确认
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
                onClick={() => click(nodes.get(`item:${item.item_id}`)!)}
              >
                {item.statement}
              </button>
            ))}
          </div>
        )}
        {profile.itemsError ? (
          <div className="memory-graph-notice" role="alert">
            {profile.itemsError}
            <Button onClick={() => void profile.refreshItems()}>重试</Button>
          </div>
        ) : !hasItems ? (
          <div className="memory-graph-notice">
            {profile.loading ? (
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
            <li>○ 待确认 · 较暗空心</li>
            <li>● 已确认 / 已修改 · 实心发光</li>
            <li style={{ color: palette['--graph-danger'] }}>◎ 存在矛盾</li>
            <li>□ 资料来源</li>
          </ul>
        </details>
        <p className="memory-graph-hint">
          {mobile ? '双指缩放 · 拖动浏览' : '拖动探索 · 滚轮缩放'} ·
          点击节点查看
        </p>
      </div>
      {sourceError && (
        <p role="alert" className="text-danger">
          {sourceError}{' '}
          <Button
            variant="ghost"
            onClick={() => setAttempt((value) => value + 1)}
          >
            重试资料
          </Button>
        </p>
      )}
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
        className={mobile ? 'memory-graph-sheet' : 'memory-graph-drawer'}
      >
        {item && (
          <ItemCard
            key={item.item_id}
            item={item}
            pending={profile.pending.has(item.item_id)}
            onReview={profile.review}
            kindLabels={profile.coverage?.kind_labels ?? {}}
          />
        )}
        {selection?.kind === 'source' && (
          <>
            <p className="mb-3 text-sm text-secondary">
              {selection.date} · 支持 {supported.length} 条记忆
            </p>
            <ul className="space-y-3" aria-label="资料支持的记忆">
              {supported.map((item) => (
                <li key={item.item_id}>
                  <button
                    type="button"
                    className="w-full rounded-lg bg-surface p-3 text-left"
                    onClick={() => click(nodes.get(`item:${item.item_id}`)!)}
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
          </>
        )}
      </Dialog>
    </div>
  );
}
