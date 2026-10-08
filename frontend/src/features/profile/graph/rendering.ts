import { useEffect, useState } from 'react';
import {
  endpointId,
  type MemoryGraph,
  type MemoryLink,
  type MemoryNode,
} from './buildMemoryGraph';

import { createRadialLayout } from './layout';

export interface GraphPalette {
  [token: string]: string;
}
export function useGraphPalette() {
  const read = () => {
    const style = getComputedStyle(document.documentElement);
    return Object.fromEntries(
      [
        'backdrop',
        'ink',
        'center',
        'source',
        'danger',
        ...Array.from({ length: 9 }, (_, i) => `d${i + 1}`),
      ].map((name) => [
        `--graph-${name}`,
        style.getPropertyValue(`--graph-${name}`).trim(),
      ]),
    );
  };
  const [palette, setPalette] = useState<GraphPalette>(read);
  useEffect(() => {
    const update = () => setPalette(read());
    const scheme = window.matchMedia('(prefers-color-scheme: dark)');
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class', 'data-theme', 'style'],
    });
    scheme.addEventListener('change', update);
    return () => {
      observer.disconnect();
      scheme.removeEventListener('change', update);
    };
  }, []);
  return palette;
}

// Force-graph mutates its input. Keep that input stable for non-topological updates,
// including optimistic reviews and rollbacks, so particles do not restart their layout.
export function useGraphLayout(graph: MemoryGraph, dimensions: 2 | 3) {
  const [layout, setLayout] = useState(() =>
    createRadialLayout(graph, dimensions),
  );
  useEffect(() => {
    const signature = (data: MemoryGraph) =>
      JSON.stringify([
        data.nodes.map((node) => node.id),
        data.links.map((link) => [
          endpointId(link.source),
          endpointId(link.target),
          link.kind,
        ]),
      ]);
    if (signature(graph) !== signature(layout)) {
      const next = createRadialLayout(graph, dimensions);
      const previous = new Map(layout.nodes.map((node) => [node.id, node]));
      for (const node of next.nodes) {
        const old = previous.get(node.id);
        if (old && node.kind === 'item')
          Object.assign(node, { x: old.x, y: old.y, z: old.z });
      }
      setLayout(next);
    } else {
      const latest = new Map(graph.nodes.map((node) => [node.id, node]));
      for (const node of layout.nodes) {
        const size = node.size;
        Object.assign(node, latest.get(node.id));
        if (node.kind === 'twin' || node.kind === 'dimension') node.size = size;
      }
      layout.links.forEach((link, index) => {
        link.weight = graph.links[index].weight;
      });
    }
  }, [graph, layout, dimensions]);
  return layout;
}
export interface GraphViewProps {
  graph: MemoryGraph;
  width: number;
  height: number;
  palette: GraphPalette;
  visible: Set<string>;
  highlighted: Set<string> | null;
  labelled: string | null;
  focus: { id: string; sequence: number } | null;
  reduced: boolean;
  onHover(node: MemoryNode | null): void;
  onClick(node: MemoryNode): void;
  onClear(): void;
  onFailure(): void;
}
export const nodeAlpha = (node: MemoryNode, props: GraphViewProps) =>
  node.kind === 'twin'
    ? 1
    : props.highlighted && !props.highlighted.has(node.id)
      ? 0.12
      : node.review === 'unreviewed'
        ? 0.5
        : 1;
export const linkVisible = (link: MemoryLink, visible: Set<string>) =>
  visible.has(endpointId(link.source)) && visible.has(endpointId(link.target));
export const linkHighlighted = (
  link: MemoryLink,
  highlighted: Set<string> | null,
) =>
  !!highlighted &&
  highlighted.has(endpointId(link.source)) &&
  highlighted.has(endpointId(link.target));
export function tooltip(node: MemoryNode) {
  const element = document.createElement('span');
  element.textContent = node.label;
  return element.outerHTML;
}
