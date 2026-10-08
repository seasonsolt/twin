import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ForceGraphProps } from 'react-force-graph-2d';
import * as THREE from 'three';
import { Graph3DBatch } from '../features/profile/graph/Graph3DBatch';
import Graph2D from '../features/profile/graph/Graph2D';
import type { GraphViewProps } from '../features/profile/graph/rendering';
import { paintTwinPortrait } from '../features/profile/graph/portrait';
import { projectedBounds2D } from '../features/profile/graph/fit';
import MemoryGraphPanel from '../features/profile/graph/MemoryGraphPanel';
import {
  buildMemoryGraph,
  dimensionColorToken,
  type MemoryLink,
  type MemoryNode,
} from '../features/profile/graph/buildMemoryGraph';
import type { ProfileItem } from '../features/profile/types';
import { setPersonaId } from '../lib/persona';
import { usePersonas } from '../stores/personas';
import { useStatus } from '../stores/status';

const renderer = vi.hoisted(() => ({
  current: null as ForceGraphProps<MemoryNode, MemoryLink> | null,
  pause: vi.fn(),
  fly: vi.fn(),
  fit: vi.fn(),
  zoom: vi.fn(),
}));
vi.mock('react-force-graph-2d', async () => {
  const { useImperativeHandle } = await import('react');
  return {
    default: function MockForceGraph(
      props: ForceGraphProps<MemoryNode, MemoryLink> & {
        ref?: React.Ref<unknown>;
      },
    ) {
      renderer.current = props;
      useImperativeHandle(props.ref, () => ({
        d3Force: () => ({ distance: vi.fn(), strength: vi.fn() }),
        d3ReheatSimulation: vi.fn(),
        pauseAnimation: renderer.pause,
        resumeAnimation: vi.fn(),
        centerAt: renderer.fly,
        zoom: renderer.zoom,
        zoomToFit: renderer.fit,
      }));
      return (
        <div aria-label="模拟力导向图">
          {props.graphData?.nodes
            .filter(
              (node) =>
                typeof props.nodeVisibility !== 'function' ||
                props.nodeVisibility(node),
            )
            .map((node) => (
              <button
                key={node.id}
                aria-label={`节点 ${node.label}`}
                onMouseOver={() => props.onNodeHover?.(node, null)}
                onClick={(event) =>
                  props.onNodeClick?.(node, event.nativeEvent)
                }
              >
                {node.label}
              </button>
            ))}
          <button
            onClick={(event) => props.onBackgroundClick?.(event.nativeEvent)}
          >
            图谱背景
          </button>
        </div>
      );
    },
  };
});
vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
const twin = {
  id: 'default',
  name: '阿林',
  portrait: '/api/media/avatar-image?persona=default',
};
const evidence = (
  source = 's1',
  quote = '在山间走走',
  date = '2026-01-02',
) => ({
  expression_id: `${source}:${quote}`,
  source_id: source,
  source_kind: 'document' as const,
  quote,
  date,
  own_words: true,
});
const item = (
  id: string,
  overrides: Partial<ProfileItem> = {},
): ProfileItem => ({
  item_id: id,
  statement: `记忆 ${id}`,
  dimension_id: 'D1',
  dimension_name: '经历与身份',
  facet_id: '1.1',
  facet_name: '经历',
  extracted_statement: '',
  applies_when: '',
  conflict: '',
  occasions: 1,
  review: 'unreviewed',
  evidence: [evidence()],
  ...overrides,
});
const sources = [
  {
    source_id: 's1',
    title: '旅行日记',
    kind: 'document',
    first_date: '2026-01-02',
  },
  { source_id: 'unused', title: '不用的资料' },
];

describe('buildMemoryGraph', () => {
  it('builds only represented dimensions, skips rejected items, and deduplicates referenced sources and weighted evidence', () => {
    const items = [
      item('a', {
        evidence: [evidence(), evidence('s1', '第二条原话'), evidence('s2')],
      }),
      item('b', {
        review: 'confirmed',
        dimension_id: 'D9',
        dimension_name: '生活与喜好',
      }),
      item('rejected', { review: 'rejected', dimension_id: 'D8' }),
    ];
    const graph = buildMemoryGraph(items, sources, twin);
    expect(graph.nodes).toHaveLength(7);
    expect(graph.links).toHaveLength(7);
    expect(graph.nodes.filter((node) => node.kind === 'source')).toHaveLength(
      2,
    );
    expect(
      graph.nodes.some(
        (node) => node.id.includes('rejected') || node.sourceId === 'unused',
      ),
    ).toBe(false);
    expect(
      graph.links.find(
        (link) => link.source === 'item:a' && link.target === 'source:s1',
      ),
    ).toMatchObject({ weight: 2, kind: 'evidence' });
    expect(graph.nodes.find((node) => node.id === 'source:s2')).toMatchObject({
      label: '未命名资料',
      date: '2026-01-02',
    });
    expect(
      graph.nodes.find((node) => node.id === 'twin:default'),
    ).toMatchObject({ portrait: twin.portrait });
    expect(
      graph.nodes.find((node) => node.id === 'item:a')!.size,
    ).toBeGreaterThan(graph.nodes.find((node) => node.id === 'item:b')!.size);
    expect(items[0].evidence).toHaveLength(3);
  });
  it('pairs flagged conflicts only in the same nonempty facet and dimension, with singletons still flagged', () => {
    const graph = buildMemoryGraph(
      [
        item('a', { conflict: '冲突' }),
        item('b', { conflict: '冲突' }),
        item('c', { conflict: '冲突' }),
        item('d', { conflict: '另一个', facet_id: '1.2' }),
        item('e'),
        item('f', { conflict: '跨维度', dimension_id: 'D2' }),
        item('g', { conflict: '无小面', facet_id: '' }),
        item('rejected', { conflict: '冲突', review: 'rejected' }),
      ],
      sources,
      twin,
    );
    expect(graph.links.filter((link) => link.kind === 'conflict')).toEqual([
      { source: 'item:a', target: 'item:b', kind: 'conflict', weight: 1 },
      { source: 'item:a', target: 'item:c', kind: 'conflict', weight: 1 },
      { source: 'item:b', target: 'item:c', kind: 'conflict', weight: 1 },
    ]);
    expect(graph.nodes.find((node) => node.id === 'item:d')!.conflict).toBe(
      true,
    );
    expect(graph.nodes.find((node) => node.id === 'item:e')!.conflict).toBe(
      false,
    );
  });
  it('assigns all nine warm colour tokens by dimension ID independent of ordering', () => {
    const graph = buildMemoryGraph(
      Array.from({ length: 9 }, (_, i) =>
        item(String(i), { dimension_id: `D${9 - i}` }),
      ),
      [],
      twin,
    );
    expect(
      new Set(
        graph.nodes
          .filter((node) => node.kind === 'dimension')
          .map((node) => node.colorToken),
      ).size,
    ).toBe(9);
    expect(dimensionColorToken('D9')).toBe('--graph-d9');
    expect(graph.nodes.find((node) => node.id === 'item:8')!.colorToken).toBe(
      '--graph-d1',
    );
    expect(buildMemoryGraph([], sources, twin)).toEqual({
      nodes: [expect.objectContaining({ kind: 'twin' })],
      links: [],
    });
  });
  it('handles the target workload without duplicating shared sources', () => {
    const items = Array.from({ length: 2000 }, (_, i) =>
      item(String(i), {
        dimension_id: `D${(i % 9) + 1}`,
        evidence: [evidence(`s${i % 300}`)],
      }),
    );
    const graph = buildMemoryGraph(items, [], twin);
    expect(graph.nodes).toHaveLength(2310);
    expect(graph.links).toHaveLength(4009);
  });
});

let rows: ProfileItem[];
let fetcher: ReturnType<typeof vi.fn>;
beforeEach(() => {
  rows = [
    item('a', { statement: '喜欢徒步' }),
    item('b', {
      statement: '习惯读书',
      review: 'confirmed',
      dimension_id: 'D9',
      dimension_name: '生活与喜好',
      evidence: [evidence('s1', '每天翻开书页')],
    }),
  ];
  setPersonaId('default');
  usePersonas.setState({ id: 'default', items: [], pendingId: null });
  useStatus.setState({ data: null, error: null });
  fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    let value: unknown = {};
    if (url.endsWith('/review')) {
      const body = JSON.parse(String(init?.body));
      rows = rows.map((row) =>
        row.item_id === 'a'
          ? {
              ...row,
              review: body.status,
              statement: body.statement || row.statement,
            }
          : row,
      );
      value = rows[0];
    } else if (url.startsWith('/api/persona/items')) value = rows;
    else if (url === '/api/persona/sources') value = sources;
    else if (url === '/api/persona/coverage')
      value = {
        facets: [],
        suggestions: [],
        kind_labels: { document: '文档' },
      };
    else if (url === '/api/status') value = { counts: {}, egress: [] };
    return new Response(JSON.stringify(value), { status: 200 });
  });
  vi.stubGlobal('fetch', fetcher);
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(900);
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(500);
  renderer.current = null;
  renderer.pause.mockClear();
  renderer.fly.mockClear();
  renderer.fit.mockClear();
  renderer.zoom.mockClear();
});
afterEach(() => {
  vi.restoreAllMocks();
});

it('searches statements and quotes, counts matches, filters dimensions and review, and flies on Enter', async () => {
  render(<MemoryGraphPanel twin={twin} />);
  await screen.findByRole('button', { name: '节点 喜欢徒步' });
  const user = userEvent.setup();
  const search = screen.getByRole('textbox', { name: '搜索记忆和原话' });
  await user.type(search, '书页');
  expect(screen.getByRole('status')).toHaveTextContent('1 条匹配');
  const searchEdge = {
    source: 'item:b',
    target: 'source:s1',
    kind: 'evidence' as const,
    weight: 1,
  };
  expect(
    (renderer.current!.linkWidth as (link: MemoryLink) => number)(searchEdge),
  ).toBe(1.5);
  expect(screen.getByLabelText('记忆图谱')).toContainElement(
    screen.getByLabelText('匹配的记忆'),
  );
  expect(screen.getByLabelText('图谱筛选')).not.toContainElement(
    screen.getByLabelText('匹配的记忆'),
  );
  await user.keyboard('{Enter}');
  expect(renderer.fly).toHaveBeenCalled();
  expect(await screen.findByRole('dialog')).toHaveTextContent('习惯读书');
  await user.click(screen.getByRole('button', { name: '关闭' }));
  await user.clear(search);
  await user.type(search, '喜欢');
  expect(screen.getByRole('status')).toHaveTextContent('1 条匹配');
  await user.click(screen.getByRole('button', { name: '经历与身份' }));
  expect(screen.getByRole('status')).toHaveTextContent('0 条匹配');
  expect(screen.queryByRole('button', { name: '节点 喜欢徒步' })).toBeNull();
  await user.click(screen.getByRole('button', { name: '经历与身份' }));
  await user.clear(search);
  await user.click(screen.getByRole('button', { name: '只看待确认' }));
  expect(screen.queryByRole('button', { name: '节点 习惯读书' })).toBeNull();
  expect(screen.getByRole('button', { name: '只看待确认' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
});

it('opens the real ItemCard, saves reviews in place without restarting the graph layout, and removes rejected items', async () => {
  render(<MemoryGraphPanel twin={twin} />);
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole('button', { name: '节点 喜欢徒步' }),
  );
  const layout = renderer.current!.graphData;
  const dialog = screen.getByRole('dialog', { name: '这条记忆' });
  await waitFor(() => expect(within(dialog).getByText('待确认')).toBeVisible());
  await user.click(within(dialog).getByRole('button', { name: '对' }));
  await waitFor(() => expect(within(dialog).getByText('已确认')).toBeVisible());
  expect(
    fetcher.mock.calls.some(
      ([url, init]) =>
        url === '/api/persona/items/a/review' && init?.method === 'POST',
    ),
  ).toBe(true);
  expect(renderer.current!.graphData).toBe(layout);
  expect(layout!.nodes.find((node) => node.id === 'item:a')!.review).toBe(
    'confirmed',
  );
  await waitFor(() =>
    expect(within(dialog).getByRole('button', { name: '不对' })).toBeEnabled(),
  );
  await user.click(within(dialog).getByRole('button', { name: '不对' }));
  await waitFor(() =>
    expect(screen.queryByRole('button', { name: '节点 喜欢徒步' })).toBeNull(),
  );
});

it('lists all supported items with dates on source click, navigates to an item, and clears on Esc or background', async () => {
  render(<MemoryGraphPanel twin={twin} />);
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole('button', { name: '节点 旅行日记' }),
  );
  const dialog = screen.getByRole('dialog', { name: '旅行日记' });
  expect(dialog).toHaveTextContent('支持 2 条记忆');
  const list = within(dialog).getByRole('list', { name: '资料支持的记忆' });
  expect(within(list).getAllByRole('listitem')).toHaveLength(2);
  expect(list).toHaveTextContent('2026-01-02');
  await user.click(within(list).getByRole('button', { name: /喜欢徒步/ }));
  expect(await screen.findByRole('dialog', { name: '这条记忆' })).toBeVisible();
  await user.keyboard('{Escape}');
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  await user.click(screen.getByRole('button', { name: '节点 喜欢徒步' }));
  await user.click(screen.getByRole('button', { name: '图谱背景' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
});

it('highlights a hovered neighbourhood, focuses a dimension and stops animation/requests on unmount', async () => {
  const view = render(<MemoryGraphPanel twin={twin} />);
  fireEvent.mouseOver(
    await screen.findByRole('button', { name: '节点 喜欢徒步' }),
  );
  const highlighted = renderer.current!.linkWidth;
  expect(typeof highlighted).toBe('function');
  if (typeof highlighted === 'function') {
    expect(
      highlighted({
        source: 'item:a',
        target: 'source:s1',
        kind: 'evidence',
        weight: 1,
      }),
    ).toBe(1.5);
    expect(
      highlighted({
        source: 'dimension:D9',
        target: 'item:b',
        kind: 'item',
        weight: 1,
      }),
    ).toBe(0.4);
  }
  await userEvent
    .setup()
    .click(screen.getByRole('button', { name: '节点 经历与身份' }));
  expect(renderer.fit).toHaveBeenCalled();
  const request = fetcher.mock.calls.find(
    ([url]) => url === '/api/persona/sources',
  )![1];
  act(() => view.unmount());
  expect(request?.signal?.aborted).toBe(true);
  expect(renderer.pause).toHaveBeenCalled();
});

it('uses a bottom sheet on mobile and reuses the empty-state wording', async () => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: query === '(max-width: 767px)',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  const view = render(<MemoryGraphPanel twin={twin} />);
  await userEvent
    .setup()
    .click(await screen.findByRole('button', { name: '节点 喜欢徒步' }));
  expect(screen.getByRole('dialog')).toHaveClass('memory-graph-sheet');
  view.unmount();
  rows = [item('rejected', { review: 'rejected' })];
  render(<MemoryGraphPanel twin={twin} />);
  expect(await screen.findByText('还不够了解你')).toBeVisible();
  expect(screen.getByText('添加一些记忆，让我慢慢认识你。')).toBeVisible();
});

it('rolls a failed review back without replacing the layout', async () => {
  const original = fetcher.getMockImplementation()! as (
    url: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation((url: string, init?: RequestInit) =>
    url.endsWith('/review')
      ? Promise.resolve(
          new Response(JSON.stringify({ detail: '审核失败' }), { status: 500 }),
        )
      : original(url, init),
  );
  render(<MemoryGraphPanel twin={twin} />);
  await userEvent
    .setup()
    .click(await screen.findByRole('button', { name: '节点 喜欢徒步' }));
  const layout = renderer.current!.graphData;
  await userEvent
    .setup()
    .click(
      within(screen.getByRole('dialog')).getByRole('button', { name: '对' }),
    );
  await waitFor(() =>
    expect(
      within(screen.getByRole('dialog')).getByRole('button', { name: '对' }),
    ).toBeEnabled(),
  );
  expect(layout!.nodes.find((node) => node.id === 'item:a')!.review).toBe(
    'unreviewed',
  );
  expect(renderer.current!.graphData).toBe(layout);
});

it('batches the target 3D workload, updates review and highlight attributes, and disposes its GPU resources', () => {
  const graph = buildMemoryGraph(
    Array.from({ length: 2000 }, (_, i) =>
      item(String(i), {
        dimension_id: `D${(i % 9) + 1}`,
        evidence: [evidence(`s${i % 300}`)],
        conflict: i === 0 ? '冲突' : '',
      }),
    ),
    [],
    twin,
  );
  graph.nodes.forEach((node, i) =>
    Object.assign(node, { x: i, y: i / 2, z: 0 }),
  );
  const props: GraphViewProps = {
    graph,
    width: 900,
    height: 500,
    palette: Object.fromEntries(
      [
        '--graph-backdrop',
        '--graph-ink',
        '--graph-center',
        '--graph-source',
        '--graph-danger',
        ...graph.nodes.map((node) => node.colorToken),
      ].map((key) => [key, '#ffc16e']),
    ),
    visible: new Set(graph.nodes.map((node) => node.id)),
    highlighted: null,
    labelled: null,
    focus: null,
    reduced: false,
    onHover: vi.fn(),
    onClick: vi.fn(),
    onClear: vi.fn(),
    onFailure: vi.fn(),
  };
  const batch = new Graph3DBatch(graph);
  expect(batch.group.children).toHaveLength(3);
  batch.update(props);
  const particles = batch.group.children[0] as THREE.Points;
  const edges = batch.group.children[1] as THREE.LineSegments;
  const evidenceIndex = graph.links.findIndex(
    (link) => link.kind === 'evidence',
  );
  expect(
    edges.geometry.getAttribute('color').getW(evidenceIndex * 2),
  ).toBeCloseTo(0.06);
  props.highlighted = new Set(['item:0', 'source:s0']);
  batch.update(props);
  expect(
    edges.geometry.getAttribute('color').getW(evidenceIndex * 2),
  ).toBeCloseTo(0.7);
  const geometry = particles.geometry;
  expect(geometry.getAttribute('position').count).toBe(2300);
  expect(geometry.getAttribute('hollow').getX(0)).toBe(1);
  expect(geometry.getAttribute('conflict').getX(0)).toBe(1);
  graph.nodes.find((node) => node.id === 'item:0')!.review = 'confirmed';
  props.highlighted = new Set(['item:0']);
  batch.update(props);
  expect(particles.geometry).toBe(geometry);
  expect(geometry.getAttribute('hollow').getX(0)).toBe(0);
  expect(geometry.getAttribute('alpha').getX(0)).toBe(1);
  expect(geometry.getAttribute('alpha').getX(1)).toBeCloseTo(0.12);
  const disposals = batch.group.children.map((child) =>
    vi.spyOn((child as THREE.Points).geometry, 'dispose'),
  );
  const scene = new THREE.Scene();
  scene.add(batch.group);
  batch.dispose();
  expect(scene.children).toHaveLength(0);
  disposals.forEach((dispose) => expect(dispose).toHaveBeenCalledOnce());
});

it('fits visible nodes after settling and changing filters without replacing the layout', async () => {
  render(<MemoryGraphPanel twin={twin} />);
  await screen.findByRole('button', { name: '节点 喜欢徒步' });
  const layout = renderer.current!.graphData;
  act(() => renderer.current!.onEngineStop?.());
  expect(renderer.zoom).toHaveBeenCalledWith(expect.any(Number), 0);
  const bounds = projectedBounds2D(
    layout!.nodes,
    renderer.zoom.mock.lastCall![0],
    900,
  );
  expect(
    Math.max(bounds.right - bounds.left, bounds.bottom - bounds.top),
  ).toBeCloseTo(500 * 0.85, 1);
  renderer.zoom.mockClear();
  await userEvent
    .setup()
    .click(screen.getByRole('button', { name: '经历与身份' }));
  await waitFor(() => expect(renderer.zoom).toHaveBeenCalled());
  const visible = renderer.current!.nodeVisibility as (
    node: MemoryNode,
  ) => boolean;
  expect(visible(layout!.nodes.find((node) => node.id === 'item:a')!)).toBe(
    false,
  );
  expect(visible(layout!.nodes.find((node) => node.id === 'item:b')!)).toBe(
    true,
  );
  const filtered = projectedBounds2D(
    layout!.nodes.filter(visible),
    renderer.zoom.mock.lastCall![0],
    900,
  );
  expect(
    Math.max(filtered.right - filtered.left, filtered.bottom - filtered.top),
  ).toBeCloseTo(500 * 0.85, 1);
  expect(renderer.current!.graphData).toBe(layout);
});

it('reserves screen space for dimension labels on a narrow 2D canvas', () => {
  const graph = buildMemoryGraph([item('a')], sources, twin);
  render(
    <Graph2D
      graph={graph}
      width={320}
      height={440}
      palette={{ '--graph-d1': '#ffc16e' }}
      visible={new Set(graph.nodes.map((node) => node.id))}
      highlighted={null}
      labelled={null}
      focus={null}
      reduced={true}
      onHover={vi.fn()}
      onClick={vi.fn()}
      onClear={vi.fn()}
      onFailure={vi.fn()}
    />,
  );
  act(() => renderer.current!.onEngineStop?.());
  const bounds = projectedBounds2D(
    renderer.current!.graphData!.nodes,
    renderer.zoom.mock.lastCall![0],
    320,
  );
  expect(
    Math.max(bounds.right - bounds.left, bounds.bottom - bounds.top),
  ).toBeCloseTo(320 * 0.85, 1);
  const ctx = {
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    strokeText: vi.fn(),
    fillText: vi.fn(),
  } as unknown as CanvasRenderingContext2D;
  const draw = renderer.current!.nodeCanvasObject as (
    node: MemoryNode,
    ctx: CanvasRenderingContext2D,
    scale: number,
  ) => void;
  draw(
    renderer.current!.graphData!.nodes.find(
      (node) => node.kind === 'dimension',
    )!,
    ctx,
    1,
  );
  expect(ctx.font).toBe('600 14px sans-serif');
  const particles = renderer.current!.linkDirectionalParticles as (
    link: MemoryLink,
  ) => number;
  expect(graph.links.every((link) => particles(link) === 0)).toBe(true);
});

it('paints a ringed initial fallback or a circular centre-cropped portrait with the shared 2D/3D painter', () => {
  const ctx = {
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    clip: vi.fn(),
    stroke: vi.fn(),
    fillText: vi.fn(),
    drawImage: vi.fn(),
  } as unknown as CanvasRenderingContext2D;
  paintTwinPortrait(ctx, 0, 0, 26, '阿林', '#ffe0a1', '#1c121b', null);
  expect(ctx.fillText).toHaveBeenCalledWith('阿', 0, 26 * 0.06);
  expect(ctx.stroke).toHaveBeenCalledOnce();
  const image = Object.assign(new Image(), { width: 400, height: 300 });
  paintTwinPortrait(ctx, 0, 0, 26, '阿林', '#ffe0a1', '#1c121b', image);
  expect(ctx.drawImage).toHaveBeenCalledWith(
    image,
    50,
    0,
    300,
    300,
    -26,
    -26,
    52,
    52,
  );
  expect(ctx.clip).toHaveBeenCalledTimes(2);
});
