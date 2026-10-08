import { describe, expect, it } from 'vitest';
import type {
  MemoryGraph,
  MemoryNode,
} from '../features/profile/graph/buildMemoryGraph';
import {
  ambientParticle,
  circularMean,
  createRadialLayout,
  dimensionAngles,
  graphRadii,
  ringPosition,
  sourceAngles,
} from '../features/profile/graph/layout';
import { linkHighlighted } from '../features/profile/graph/rendering';

const node = (
  id: string,
  kind: MemoryNode['kind'],
  dimensionId?: string,
): MemoryNode => ({
  id,
  kind,
  dimensionId,
  label: id,
  colorToken: '--graph-d1',
  size: kind === 'item' ? 3 : 11,
});
const graph: MemoryGraph = {
  nodes: [
    node('twin:t', 'twin'),
    node('dimension:D1', 'dimension', 'D1'),
    node('dimension:D2', 'dimension', 'D2'),
    node('item:a', 'item', 'D1'),
    node('item:b', 'item', 'D2'),
    node('item:c', 'item', 'D1'),
    node('source:s', 'source'),
  ],
  links: [
    { source: 'item:a', target: 'source:s', kind: 'evidence', weight: 5 },
    { source: 'item:b', target: 'source:s', kind: 'evidence', weight: 1 },
    { source: 'item:c', target: 'source:s', kind: 'evidence', weight: 1 },
  ],
};

describe('radial layout helpers', () => {
  it.each([false, true])(
    'preserves ring radius and uses a subtle 3D tilt (%s)',
    (tilted) => {
      const p = ringPosition(Math.PI / 2, 200, tilted);
      expect(Math.hypot(p.x, p.y, p.z)).toBeCloseTo(200);
      expect(p.x).toBeCloseTo(0);
      expect(p.z).toBe(tilted ? 200 * Math.sin(Math.PI / 12) : 0);
      expect(p.y).toBeCloseTo(tilted ? 200 * Math.cos(Math.PI / 12) : 200);
    },
  );
  it('spaces fixed dimensions evenly, sorted by ID rather than API order', () => {
    const ids = Array.from({ length: 9 }, (_, i) => `D${i + 1}`);
    const a = dimensionAngles(ids),
      b = dimensionAngles([...ids].reverse());
    for (let i = 0; i < ids.length; i++) {
      expect(a.get(ids[i])).toBe(b.get(ids[i]));
      if (i)
        expect(a.get(ids[i])! - a.get(ids[i - 1])!).toBeCloseTo(
          (2 * Math.PI) / 9,
        );
    }
  });
  it('scales separated layers for 20, 96, and 2000 items and reserves circumference for crowded sources', () => {
    const sizes = [
      graphRadii(20, 5),
      graphRadii(96, 14),
      graphRadii(2000, 300),
    ];
    sizes.forEach((r) => {
      expect(r.inner).toBeLessThan(r.items);
      expect(r.items + r.cloud).toBeLessThan(r.sources);
    });
    for (let i = 1; i < sizes.length; i++) {
      expect(sizes[i].inner).toBeGreaterThan(sizes[i - 1].inner);
      expect(sizes[i].items).toBeGreaterThan(sizes[i - 1].items);
      expect(sizes[i].sources).toBeGreaterThan(sizes[i - 1].sources);
    }
    expect(graphRadii(2000, 1000).sources * Math.PI * 2).toBeGreaterThanOrEqual(
      12000,
    );
    expect(Number.isFinite(graphRadii(0, 0, 0).sources)).toBe(true);
  });
  it('takes circular means across the 0/360 seam with a deterministic fallback for opposing directions', () => {
    expect(
      circularMean([(350 * Math.PI) / 180, (10 * Math.PI) / 180]),
    ).toBeCloseTo(0);
    expect(circularMean([Math.PI / 4, (Math.PI * 3) / 4])).toBeCloseTo(
      Math.PI / 2,
    );
    expect(circularMean([0, Math.PI])).toBe(0);
    expect(circularMean([])).toBe(0);
  });
  it('places sources at the mean of distinct supported dimensions, not evidence or item frequency', () => {
    const angles = new Map([
      ['D1', (350 * Math.PI) / 180],
      ['D2', (10 * Math.PI) / 180],
    ]);
    expect(sourceAngles(graph, angles).get('source:s')).toBeCloseTo(0);
    const mutatedLinks = {
      ...graph,
      links: graph.links.map((link) => ({
        ...link,
        source: graph.nodes.find((node) => node.id === link.source)!,
      })),
    };
    expect(sourceAngles(mutatedLinks, angles)).toEqual(
      sourceAngles(graph, angles),
    );
  });
  it.each([2, 3] as const)(
    'fixes the twin and inner ring, seeds item clouds and leaves sources collision-enabled in %sD',
    (dimensions) => {
      const layout = createRadialLayout(graph, dimensions);
      const radii = graphRadii(3, 1, 2);
      expect(layout.nodes[0]).toMatchObject({
        x: 0,
        y: 0,
        z: 0,
        fx: 0,
        fy: 0,
        fz: 0,
      });
      for (const n of layout.nodes.filter(
        (node) => node.kind === 'dimension',
      )) {
        expect(Math.hypot(n.x!, n.y!, n.z!)).toBeCloseTo(radii.inner);
        expect([n.fx, n.fy, n.fz]).toEqual([n.x, n.y, n.z]);
      }
      for (const n of layout.nodes.filter((node) => node.kind === 'item')) {
        const centre = ringPosition(
          n.layoutAngle!,
          radii.items,
          dimensions === 3,
        );
        expect(
          Math.hypot(n.x! - centre.x, n.y! - centre.y, n.z! - centre.z),
        ).toBeLessThanOrEqual(radii.cloud + 1);
        expect(n.fx).toBeUndefined();
      }
      const source = layout.nodes.find((node) => node.kind === 'source')!;
      expect(Math.hypot(source.x!, source.y!, source.z!)).toBeCloseTo(
        radii.sources,
      );
      expect(source.layoutAngle).toBe(
        sourceAngles(graph, dimensionAngles(['D1', 'D2'])).get(source.id),
      );
      expect(source.fx).toBeUndefined();
      expect(graph.nodes[0].x).toBeUndefined();
      expect(layout.links[0]).not.toBe(graph.links[0]);
    },
  );
  it('gives same-angle sources distinct seeds on the outer ring', () => {
    const materials = Array.from({ length: 14 }, (_, i) =>
      node(`source:${i}`, 'source'),
    );
    const layout = createRadialLayout(
      {
        nodes: [
          ...graph.nodes.filter((n) => n.kind !== 'source'),
          ...materials,
        ],
        links: materials.map((n) => ({
          source: 'item:a',
          target: n.id,
          kind: 'evidence',
          weight: 1,
        })),
      },
      2,
    );
    const sources = layout.nodes.filter((n) => n.kind === 'source');
    expect(new Set(sources.map((n) => `${n.x}:${n.y}`)).size).toBe(14);
    expect(new Set(sources.map((n) => n.layoutAngle)).size).toBe(1);
  });
  it('keeps ambient particles at a deterministic ~10% rather than animating every evidence link', () => {
    const links = Array.from({ length: 2000 }, (_, i) => ({
      source: `item:${i}`,
      target: `source:${i % 300}`,
      kind: 'evidence' as const,
      weight: 1,
    }));
    const selected = links.filter(ambientParticle);
    expect(selected.length).toBeGreaterThan(150);
    expect(selected.length).toBeLessThan(250);
    expect(links.filter(ambientParticle)).toEqual(selected);
    expect(linkHighlighted(links[0], null)).toBe(false);
    expect(linkHighlighted(links[0], new Set(['item:0', 'source:0']))).toBe(
      true,
    );
  });
});
