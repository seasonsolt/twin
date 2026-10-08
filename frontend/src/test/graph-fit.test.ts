import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import * as THREE from 'three';
import {
  fit2D,
  fit3D,
  projectedBounds2D,
  projectedBounds3D,
} from '../features/profile/graph/fit';
import type { MemoryNode } from '../features/profile/graph/buildMemoryGraph';

const nodes: MemoryNode[] = [
  {
    id: 'twin',
    kind: 'twin',
    label: '阿林',
    size: 26,
    colorToken: '',
    x: 0,
    y: 0,
    z: 0,
  },
  ...Array.from({ length: 9 }, (_, i): MemoryNode => {
    const angle = (i * Math.PI * 2) / 9;
    return {
      id: `d${i}`,
      kind: 'dimension',
      label: '经历与身份',
      size: 12,
      colorToken: '',
      x: Math.cos(angle) * 120,
      y: Math.sin(angle) * 120,
      z: Math.sin(angle) * 20,
      layoutAngle: angle,
    };
  }),
  {
    id: 'outer',
    kind: 'source',
    label: '最远的资料',
    size: 4,
    colorToken: '',
    x: 205,
    y: -150,
    z: 90,
  },
];
beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(
    () =>
      ({
        font: '',
        measureText(this: { font: string }, text: string) {
          return {
            width: text.length * Number(/(\d+)px/.exec(this.font)?.[1] ?? 14),
          };
        },
      }) as unknown as CanvasRenderingContext2D,
  );
});
afterEach(() => vi.restoreAllMocks());
const extent = (bounds: {
  left: number;
  right: number;
  top: number;
  bottom: number;
}) => Math.max(bounds.right - bounds.left, bounds.bottom - bounds.top);

it.each([
  [1200, 700],
  [360, 520],
])(
  'fits the 2D nodes plus constant-pixel labels to 0.85 of the shorter %sx%s canvas',
  (width, height) => {
    for (const visible of [
      nodes,
      nodes.filter((node) => node.id !== 'outer'),
    ]) {
      const fit = fit2D(visible, width, height)!;
      const bounds = projectedBounds2D(visible, fit.zoom, width);
      expect(extent(bounds)).toBeCloseTo(Math.min(width, height) * 0.85, 2);
      const left = bounds.left - fit.x * fit.zoom + width / 2;
      const right = bounds.right - fit.x * fit.zoom + width / 2;
      const top = bounds.top - fit.y * fit.zoom + height / 2;
      const bottom = bounds.bottom - fit.y * fit.zoom + height / 2;
      expect(left).toBeGreaterThanOrEqual(0);
      expect(top).toBeGreaterThanOrEqual(0);
      expect(right).toBeLessThanOrEqual(width);
      expect(bottom).toBeLessThanOrEqual(height);
    }
  },
);

it.each([
  [1200, 700],
  [360, 520],
])(
  'fits projected 3D bodies and labels after settling/filtering/resizing on %sx%s',
  (width, height) => {
    const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 10000);
    camera.position.set(80, 150, 1200);
    camera.lookAt(0, 0, 0);
    // Mock the force-graph camera adapter, while using real perspective projection.
    const graph = {
      camera: () => camera,
      cameraPosition: vi.fn(
        (position: THREE.Vector3, target: THREE.Vector3) => {
          camera.position.copy(position);
          camera.lookAt(target);
          camera.updateMatrixWorld(true);
        },
      ),
    };
    for (const visible of [
      nodes,
      nodes.filter((node) => node.id !== 'outer'),
    ]) {
      const view = fit3D(visible, graph.camera(), width, height)!;
      graph.cameraPosition(view.position, view.target);
      const bounds = projectedBounds3D(visible, camera, width, height);
      expect(extent(bounds) / Math.min(width, height)).toBeCloseTo(0.85, 2);
      expect(bounds.left).toBeGreaterThan(0);
      expect(bounds.top).toBeGreaterThan(0);
      expect(bounds.right).toBeLessThan(width);
      expect(bounds.bottom).toBeLessThan(height);
    }
    expect(graph.cameraPosition).toHaveBeenCalledTimes(2);
  },
);
