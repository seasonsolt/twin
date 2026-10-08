import type { ProfileItem, ReviewStatus } from '../types';

export interface GraphSource {
  source_id: string;
  title?: string;
  name?: string;
  kind?: string;
  first_date?: string | null;
}
export interface GraphTwin {
  id: string;
  name: string;
  portrait?: string;
}
export interface MemoryNode {
  id: string;
  kind: 'twin' | 'dimension' | 'item' | 'source';
  label: string;
  dimensionId?: string;
  colorToken: string;
  size: number;
  review?: ReviewStatus;
  conflict?: boolean;
  itemId?: string;
  sourceId?: string;
  portrait?: string;
  date?: string | null;
  x?: number;
  y?: number;
  z?: number;
  layoutAngle?: number;
  layoutRadius?: number;
  fx?: number;
  fy?: number;
  fz?: number;
}
export interface MemoryLink {
  source: string | MemoryNode;
  target: string | MemoryNode;
  kind: 'dimension' | 'item' | 'evidence' | 'conflict';
  weight: number;
}
export interface MemoryGraph {
  nodes: MemoryNode[];
  links: MemoryLink[];
}
export const endpointId = (endpoint: string | MemoryNode) =>
  typeof endpoint === 'string' ? endpoint : endpoint.id;
export const dimensionColorToken = (id: string) => {
  const number = Number(id.replace(/^D/, ''));
  return `--graph-d${number >= 1 && number <= 9 ? number : 1}`;
};

export function buildMemoryGraph(
  items: readonly ProfileItem[],
  sources: readonly GraphSource[],
  twin: GraphTwin,
): MemoryGraph {
  const nodes: MemoryNode[] = [
    {
      id: `twin:${twin.id}`,
      kind: 'twin',
      label: twin.name,
      portrait: twin.portrait,
      colorToken: '--graph-center',
      size: 16,
    },
  ];
  const links: MemoryLink[] = [];
  const dimensions = new Set<string>();
  const sourceNodes = new Set<string>();
  const sourceMap = new Map(
    sources.map((source) => [source.source_id, source]),
  );
  const facets = new Map<string, string[]>();
  for (const item of items) {
    if (item.review === 'rejected') continue;
    const dimension = `dimension:${item.dimension_id}`;
    const id = `item:${item.item_id}`;
    const colorToken = dimensionColorToken(item.dimension_id);
    if (!dimensions.has(dimension)) {
      dimensions.add(dimension);
      nodes.push({
        id: dimension,
        kind: 'dimension',
        label: item.dimension_name,
        dimensionId: item.dimension_id,
        colorToken,
        size: 11,
      });
      links.push({
        source: nodes[0].id,
        target: dimension,
        kind: 'dimension',
        weight: 1,
      });
    }
    nodes.push({
      id,
      kind: 'item',
      itemId: item.item_id,
      label: item.statement,
      dimensionId: item.dimension_id,
      colorToken,
      size: 2 + Math.min(4, Math.sqrt(item.evidence.length)),
      review: item.review,
      conflict: !!item.conflict.trim(),
    });
    links.push({ source: dimension, target: id, kind: 'item', weight: 1 });
    const evidenceCounts = new Map<string, number>();
    for (const evidence of item.evidence) {
      if (!evidence.source_id) continue;
      evidenceCounts.set(
        evidence.source_id,
        (evidenceCounts.get(evidence.source_id) ?? 0) + 1,
      );
      if (!sourceNodes.has(evidence.source_id)) {
        sourceNodes.add(evidence.source_id);
        const source = sourceMap.get(evidence.source_id);
        nodes.push({
          id: `source:${evidence.source_id}`,
          kind: 'source',
          sourceId: evidence.source_id,
          label: source?.title || source?.name || '未命名资料',
          date: source?.first_date ?? evidence.date,
          colorToken: '--graph-source',
          size: 4,
        });
      }
    }
    for (const [source, weight] of evidenceCounts)
      links.push({
        source: id,
        target: `source:${source}`,
        kind: 'evidence',
        weight,
      });
    if (item.conflict.trim()) {
      const facetKey = `${item.dimension_id}:${item.facet_id}`;
      const paired = facets.get(facetKey) ?? [];
      if (item.facet_id) {
        for (const other of paired)
          links.push({
            source: other,
            target: id,
            kind: 'conflict',
            weight: 1,
          });
        paired.push(id);
        facets.set(facetKey, paired);
      }
    }
  }
  return { nodes, links };
}
