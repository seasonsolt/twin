import { forceCollide, forceRadial, forceX, forceY, forceZ } from 'd3-force-3d';
import {
  endpointId,
  type MemoryGraph,
  type MemoryLink,
  type MemoryNode,
} from './buildMemoryGraph';

const TAU = Math.PI * 2;
const TILT = Math.PI / 12;
export function graphRadii(
  itemCount: number,
  sourceCount: number,
  dimensionCount = 9,
) {
  const cloud =
    18 + Math.sqrt(Math.max(0, itemCount) / Math.max(1, dimensionCount)) * 4;
  const inner = 130 + cloud * 1.4;
  const items = inner + cloud + 20;
  const sources = Math.max(
    items + cloud + 35,
    (Math.max(0, sourceCount) * 12) / TAU,
  );
  return { inner, items, sources, cloud };
}
export function ringPosition(angle: number, radius: number, tilted = false) {
  return {
    x: Math.cos(angle) * radius,
    y: Math.sin(angle) * radius * (tilted ? Math.cos(TILT) : 1),
    z: tilted ? Math.sin(angle) * radius * Math.sin(TILT) : 0,
  };
}
export function dimensionAngles(ids: readonly string[]) {
  const sorted = [...ids].sort((a, b) =>
    a.localeCompare(b, undefined, { numeric: true }),
  );
  return new Map(
    sorted.map((id, index) => [
      id,
      -Math.PI / 2 + (index * TAU) / sorted.length,
    ]),
  );
}
export function circularMean(angles: readonly number[]) {
  if (!angles.length) return 0;
  const x = angles.reduce((sum, angle) => sum + Math.cos(angle), 0);
  const y = angles.reduce((sum, angle) => sum + Math.sin(angle), 0);
  return Math.hypot(x, y) < 1e-8 ? angles[0] : Math.atan2(y, x);
}
export function sourceAngles(
  graph: MemoryGraph,
  angles: ReadonlyMap<string, number>,
) {
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  const supported = new Map<string, Set<string>>();
  for (const link of graph.links) {
    if (link.kind !== 'evidence') continue;
    const item = nodes.get(endpointId(link.source));
    if (!item?.dimensionId) continue;
    const source = endpointId(link.target);
    if (!supported.has(source)) supported.set(source, new Set());
    supported.get(source)!.add(item.dimensionId);
  }
  return new Map(
    graph.nodes
      .filter((node) => node.kind === 'source')
      .map((node) => [
        node.id,
        circularMean(
          [...(supported.get(node.id) ?? [])]
            .sort()
            .map((id) => angles.get(id) ?? 0),
        ),
      ]),
  );
}
export function createRadialLayout(
  graph: MemoryGraph,
  dimensions: 2 | 3,
): MemoryGraph {
  const dimensionNodes = graph.nodes.filter(
    (node) => node.kind === 'dimension',
  );
  const itemNodes = graph.nodes.filter((node) => node.kind === 'item');
  const sourceNodes = graph.nodes.filter((node) => node.kind === 'source');
  const radii = graphRadii(
    itemNodes.length,
    sourceNodes.length,
    dimensionNodes.length,
  );
  const angles = dimensionAngles(
    dimensionNodes.map((node) => node.dimensionId!),
  );
  const materialAngles = sourceAngles(graph, angles);
  const counts = new Map<string, number>();
  itemNodes.forEach((node) =>
    counts.set(node.dimensionId!, (counts.get(node.dimensionId!) ?? 0) + 1),
  );
  const indices = new Map<string, number>();
  const sourceIndices = new Map<string, number>();
  const scale = radii.sources / 300;
  const nodes = graph.nodes.map((node) => {
    if (node.kind === 'twin')
      return {
        ...node,
        size: 26 * scale,
        x: 0,
        y: 0,
        z: 0,
        fx: 0,
        fy: 0,
        fz: 0,
      };
    const angle =
      node.kind === 'source'
        ? materialAngles.get(node.id)!
        : angles.get(node.dimensionId!)!;
    const radius =
      node.kind === 'dimension'
        ? radii.inner
        : node.kind === 'source'
          ? radii.sources
          : radii.items;
    const target = ringPosition(angle, radius, dimensions === 3);
    if (node.kind === 'dimension')
      return {
        ...node,
        size: 14 * scale,
        ...target,
        fx: target.x,
        fy: target.y,
        fz: target.z,
        layoutAngle: angle,
        layoutRadius: radius,
      };
    if (node.kind === 'source') {
      const sector = angle.toFixed(3);
      const index = sourceIndices.get(sector) ?? 0;
      sourceIndices.set(sector, index + 1);
      // Deterministic alternating seeds break exact ties; collision resolves the
      // remaining crowding while angular attraction keeps materials near their topics.
      const spread =
        (Math.ceil(index / 2) * (index % 2 ? 1 : -1) * 12) / radius;
      return {
        ...node,
        ...ringPosition(angle + spread, radius, dimensions === 3),
        layoutAngle: angle,
        layoutRadius: radius,
      };
    }
    const index = indices.get(node.dimensionId!) ?? 0;
    indices.set(node.dimensionId!, index + 1);
    const offset =
      Math.sqrt((index + 0.5) / counts.get(node.dimensionId!)!) * radii.cloud;
    const spiral = index * 2.39996;
    const tangent = Math.sin(spiral) * offset;
    const radial = Math.cos(spiral) * offset;
    const position = ringPosition(
      angle + tangent / radius,
      radius + radial,
      dimensions === 3,
    );
    return { ...node, ...position, layoutAngle: angle, layoutRadius: radius };
  });
  return {
    nodes,
    links: graph.links.map((link) => ({
      ...link,
      source: endpointId(link.source),
      target: endpointId(link.target),
    })),
  };
}

interface ForceHost {
  d3Force(
    name: string,
    force?: ReturnType<typeof forceRadial<MemoryNode>> | null,
  ): unknown;
}
export function configureRadialForces(host: ForceHost, dimensions: 2 | 3) {
  const link = host.d3Force('link') as {
    distance(value: (link: MemoryLink) => number): void;
    strength(value: (link: MemoryLink) => number): void;
  };
  link.distance((link) => (link.kind === 'item' ? 45 : 0));
  link.strength((link) => (link.kind === 'item' ? 0.08 : 0));
  host.d3Force('charge', null);
  host.d3Force('center', null);
  host.d3Force(
    'radial',
    forceRadial<MemoryNode>((node) => node.layoutRadius ?? 0).strength(
      (node) =>
        node.kind === 'source' ? 0.9 : node.kind === 'item' ? 0.12 : 0,
    ),
  );
  host.d3Force(
    'collision',
    forceCollide<MemoryNode>((node) => node.size * 1.35 + 2)
      .strength(0.85)
      .iterations(2),
  );
  const target = (node: MemoryNode) =>
    ringPosition(
      node.layoutAngle ?? 0,
      node.layoutRadius ?? 0,
      dimensions === 3,
    );
  const strength = (node: MemoryNode) =>
    node.kind === 'item' ? 0.12 : node.kind === 'source' ? 0.035 : 0;
  host.d3Force(
    'cluster-x',
    forceX<MemoryNode>((node) => target(node).x).strength(strength),
  );
  host.d3Force(
    'cluster-y',
    forceY<MemoryNode>((node) => target(node).y).strength(strength),
  );
  if (dimensions === 3)
    host.d3Force(
      'cluster-z',
      forceZ<MemoryNode>((node) => target(node).z).strength(0.2),
    );
}
export function ambientParticle(link: MemoryLink) {
  let hash = 2166136261;
  for (const char of `${endpointId(link.source)}:${endpointId(link.target)}`)
    hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
  return (hash >>> 0) / 4294967296 < 0.1;
}
