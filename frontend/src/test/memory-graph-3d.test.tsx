import { act, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import * as THREE from 'three';
import Graph3D from '../features/profile/graph/Graph3D';
import type { GraphViewProps } from '../features/profile/graph/rendering';
import type { ForceGraphProps } from 'react-force-graph-3d';
import type {
  MemoryLink,
  MemoryNode,
} from '../features/profile/graph/buildMemoryGraph';

const mock = vi.hoisted(() => ({
  scene: null as THREE.Scene | null,
  nodes: null as THREE.Group | null,
  renderer: null as unknown as THREE.WebGLRenderer,
  fit: vi.fn(),
  pause: vi.fn(),
  dispose: vi.fn(),
  lost: vi.fn(),
  current: null as ForceGraphProps<MemoryNode, MemoryLink> | null,
  controls: {
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    getAzimuthalAngle: () => 0,
    minAzimuthAngle: -Infinity,
    maxAzimuthAngle: Infinity,
  },
}));
vi.mock('react-force-graph-3d', async () => {
  const { useMemo, useImperativeHandle } = await import('react');
  const { Group } = await import('three');
  return {
    default: function MockForceGraph(
      props: ForceGraphProps<MemoryNode, MemoryLink> & {
        ref?: React.Ref<unknown>;
      },
    ) {
      mock.current = props;
      useMemo(() => {
        mock.nodes?.removeFromParent();
        const group = new Group();
        props.graphData!.nodes.forEach((node) => {
          const object = (
            props.nodeThreeObject as (node: MemoryNode) => THREE.Object3D
          )(node);
          object.position.set(node.x ?? 0, node.y ?? 0, node.z ?? 0);
          object.userData.node = node;
          group.add(object);
        });
        mock.nodes = group;
        mock.scene!.add(group);
      }, [props.graphData, props.nodeThreeObject]);
      useImperativeHandle(props.ref, () => ({
        scene: () => mock.scene,
        renderer: () => mock.renderer,
        controls: () => mock.controls,
        d3Force: () => ({ distance: vi.fn(), strength: vi.fn() }),
        d3ReheatSimulation: vi.fn(),
        resumeAnimation: vi.fn(),
        pauseAnimation: mock.pause,
        cameraPosition: vi.fn(),
        zoomToFit: mock.fit,
      }));
      return <div aria-label="模拟三维图" />;
    },
  };
});
function props(): GraphViewProps {
  const nodes: MemoryNode[] = [
    {
      id: 'twin:t',
      kind: 'twin',
      label: '阿林',
      colorToken: '--graph-center',
      size: 16,
    },
    {
      id: 'dimension:D1',
      kind: 'dimension',
      dimensionId: 'D1',
      label: '经历与身份',
      colorToken: '--graph-d1',
      size: 11,
    },
    {
      id: 'dimension:D2',
      kind: 'dimension',
      dimensionId: 'D2',
      label: '看重什么',
      colorToken: '--graph-d2',
      size: 11,
    },
    {
      id: 'item:a',
      kind: 'item',
      dimensionId: 'D1',
      label: '记忆',
      colorToken: '--graph-d1',
      size: 3,
    },
    {
      id: 'source:s',
      kind: 'source',
      label: '资料',
      colorToken: '--graph-source',
      size: 4,
    },
  ];
  return {
    graph: {
      nodes,
      links: [
        { source: 'item:a', target: 'source:s', kind: 'evidence', weight: 1 },
      ],
    },
    width: 900,
    height: 500,
    palette: Object.fromEntries(
      [
        '--graph-center',
        '--graph-source',
        '--graph-d1',
        '--graph-d2',
        '--graph-backdrop',
        '--graph-ink',
        '--graph-danger',
      ].map((key) => [key, '#ffc16e']),
    ),
    visible: new Set(nodes.map((node) => node.id)),
    highlighted: null,
    labelled: null,
    focus: null,
    reduced: false,
    onHover: vi.fn(),
    onClick: vi.fn(),
    onClear: vi.fn(),
    onFailure: vi.fn(),
  };
}
beforeEach(() => {
  mock.scene = new THREE.Scene();
  mock.nodes = null;
  const ctx = {
    measureText: (text: string) => ({ width: text.length * 40 }),
    createRadialGradient: () => ({ addColorStop: vi.fn() }),
    fillRect: vi.fn(),
    beginPath: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    stroke: vi.fn(),
    clip: vi.fn(),
    strokeText: vi.fn(),
    fillText: vi.fn(),
    drawImage: vi.fn(),
  };
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(
    () => ctx as unknown as CanvasRenderingContext2D,
  );
  mock.renderer = {
    domElement: document.createElement('canvas'),
    setPixelRatio: vi.fn(),
    getSize: (target: THREE.Vector2) => target.set(900, 500),
    getPixelRatio: () => 1,
    dispose: mock.dispose,
    forceContextLoss: mock.lost,
  } as unknown as THREE.WebGLRenderer;
  mock.fit.mockClear();
  mock.pause.mockClear();
  mock.dispose.mockClear();
  mock.lost.mockClear();
});
afterEach(() => vi.restoreAllMocks());

it('includes batched source/item bounds in fitting but keeps screen-sized labels outside the fit bounds', () => {
  render(<Graph3D {...props()} />);
  expect(
    mock.controls.maxAzimuthAngle - mock.controls.minAzimuthAngle,
  ).toBeCloseTo(0.3);
  mock.scene!.updateMatrixWorld(true);
  const before = new THREE.Box3().setFromObject(mock.nodes!);
  const labels: THREE.Sprite[] = [];
  mock.scene!.traverse((object) => {
    if (object.name === 'label') labels.push(object as THREE.Sprite);
  });
  expect(labels).toHaveLength(3);
  expect(
    labels.every((label) => !mock.nodes!.children.includes(label.parent!)),
  ).toBe(true);
  const source = mock.nodes!.children.find(
    (object) => object.userData.node.kind === 'source',
  )!;
  const sourceBounds = new THREE.Box3().setFromObject(source);
  expect(sourceBounds.isEmpty()).toBe(false);
  expect(source.children[0].visible).toBe(false);
  const camera = new THREE.PerspectiveCamera(50, 900 / 500, 0.1, 10000);
  camera.position.set(0, -80, 600);
  camera.lookAt(0, 0, 0);
  camera.updateMatrixWorld(true);
  for (let frame = 0; frame < 5; frame++)
    labels.forEach((label) =>
      label.onBeforeRender(
        mock.renderer,
        mock.scene!,
        camera,
        label.geometry,
        label.material,
        new THREE.Group(),
      ),
    );
  mock.scene!.updateMatrixWorld(true);
  expect(new THREE.Box3().setFromObject(mock.nodes!).equals(before)).toBe(true);
  act(() => mock.current!.onEngineStop?.());
  expect(mock.fit).toHaveBeenCalledWith(500, 50, expect.any(Function));
});

it('does not dispose the WebGL renderer during StrictMode replay, but does dispose on real unmount', async () => {
  const { StrictMode } = await import('react');
  const view = render(
    <StrictMode>
      <Graph3D {...props()} />
    </StrictMode>,
  );
  await act(async () => {});
  expect(mock.lost).not.toHaveBeenCalled();
  view.unmount();
  await waitFor(() => expect(mock.lost).toHaveBeenCalledOnce());
  expect(mock.pause).toHaveBeenCalled();
});
