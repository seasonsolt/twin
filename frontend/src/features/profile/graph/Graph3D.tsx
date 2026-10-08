import { useCallback, useEffect, useMemo, useRef } from 'react';
import ForceGraph3D, { type ForceGraphMethods } from 'react-force-graph-3d';
import * as THREE from 'three';
import type { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Graph3DBatch } from './Graph3DBatch';
import type { MemoryLink, MemoryNode } from './buildMemoryGraph';
import { configureRadialForces } from './layout';
import { paintTwinPortrait, usePortrait } from './portrait';
import {
  nodeAlpha,
  tooltip,
  useGraphLayout,
  type GraphViewProps,
} from './rendering';

function bodyTexture(
  node: MemoryNode,
  props: GraphViewProps,
  portrait: HTMLImageElement | null,
) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 128;
  const ctx = canvas.getContext('2d')!;
  const color = props.palette[node.colorToken];
  if (node.kind === 'twin') {
    paintTwinPortrait(
      ctx,
      64,
      64,
      50,
      node.label,
      color,
      props.palette['--graph-backdrop'],
      portrait,
    );
  } else {
    const glow = ctx.createRadialGradient(64, 64, 24, 64, 64, 64);
    glow.addColorStop(0, color);
    glow.addColorStop(1, `${color}00`);
    ctx.globalAlpha = 0.4;
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, 128, 128);
    ctx.globalAlpha = 1;
    ctx.beginPath();
    ctx.arc(64, 64, 40, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}
function textSprite(node: MemoryNode, props: GraphViewProps) {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d')!;
  const text =
    node.label.length > 32 ? `${node.label.slice(0, 32)}…` : node.label;
  ctx.font = '600 40px sans-serif';
  canvas.width = Math.ceil(ctx.measureText(text).width) + 24;
  canvas.height = 64;
  ctx.font = '600 40px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.lineWidth = 8;
  ctx.strokeStyle = props.palette['--graph-backdrop'];
  ctx.shadowColor = props.palette['--graph-backdrop'];
  ctx.shadowBlur = 8;
  ctx.strokeText(text, canvas.width / 2, 32);
  ctx.fillStyle = props.palette['--graph-ink'];
  ctx.fillText(text, canvas.width / 2, 32);
  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: new THREE.CanvasTexture(canvas),
      depthWrite: false,
      depthTest: false,
    }),
  );
  sprite.name = 'label';
  sprite.userData.key = `${node.label}:${props.palette['--graph-ink']}:${props.palette['--graph-backdrop']}`;
  sprite.userData.node = node;
  const size = new THREE.Vector2();
  const view = new THREE.Vector3();
  sprite.onBeforeRender = (renderer, _scene, camera) => {
    view
      .set(node.x ?? 0, node.y ?? 0, node.z ?? 0)
      .applyMatrix4(camera.matrixWorldInverse);
    const pixelsPerUnit =
      (renderer.getSize(size).y * camera.projectionMatrix.elements[5]) /
      (2 * Math.max(1, -view.z));
    const height =
      (node.kind === 'dimension' || node.kind === 'twin' ? 24 : 20) /
      pixelsPerUnit;
    const width = (height * canvas.width) / canvas.height;
    sprite.scale.set(width, height, 1);
    if (node.kind === 'dimension') {
      const angle = node.layoutAngle ?? 0;
      const margin = node.size + 10 / pixelsPerUnit;
      sprite.position.set(
        (node.x ?? 0) +
          Math.cos(angle) * margin +
          (Math.abs(Math.cos(angle)) > 0.3
            ? (Math.sign(Math.cos(angle)) * width) / 2
            : 0),
        (node.y ?? 0) + Math.sin(angle) * margin,
        node.z ?? 0,
      );
    } else
      sprite.position.set(
        node.x ?? 0,
        (node.y ?? 0) - node.size - 16 / pixelsPerUnit,
        node.z ?? 0,
      );
    sprite.updateMatrixWorld(true);
  };
  return sprite;
}

function startRotation(controls: OrbitControls) {
  const angle = controls.getAzimuthalAngle();
  controls.minAzimuthAngle = angle - 0.15;
  controls.maxAzimuthAngle = angle + 0.15;
  controls.autoRotateSpeed = 0.25;
  controls.autoRotate = true;
}

export default function Graph3D(props: GraphViewProps) {
  const layout = useGraphLayout(props.graph, 3);
  const portrait = usePortrait(
    props.graph.nodes.find((node) => node.kind === 'twin')?.portrait,
  );
  const fg = useRef<ForceGraphMethods<MemoryNode, MemoryLink> | undefined>(
    undefined,
  );
  const textures = useRef(new Map<string, THREE.Texture>());
  const objects = useRef(new Map<string, THREE.Group>());
  const labels = useRef(new Map<string, THREE.Sprite>());
  const bounds = useMemo(
    () => ({
      geometry: new THREE.BoxGeometry(2, 2, 2),
      material: new THREE.MeshBasicMaterial(),
    }),
    [],
  );
  const labelLayer = useMemo(() => new THREE.Group(), []);
  const idle = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const batch = useRef<Graph3DBatch | null>(null);
  const generation = useRef({ value: 0 });
  const latest = useRef({ props, portrait });
  useEffect(() => {
    latest.current = { props, portrait };
  });
  const interact = useCallback(() => {
    const controls = fg.current?.controls() as OrbitControls | undefined;
    if (controls) {
      controls.autoRotate = false;
      controls.minAzimuthAngle = -Infinity;
      controls.maxAzimuthAngle = Infinity;
    }
    clearTimeout(idle.current);
    idle.current = setTimeout(() => {
      if (controls && !document.hidden) startRotation(controls);
    }, 10000);
  }, []);
  const styleObject = useCallback(
    (
      node: MemoryNode,
      group: THREE.Group,
      state: GraphViewProps,
      image: HTMLImageElement | null,
    ) => {
      const body = group.getObjectByName('body') as THREE.Sprite | undefined;
      if (body) {
        const key = `${node.kind}:${state.palette[node.colorToken]}:${state.palette['--graph-backdrop']}:${node.kind === 'twin' ? `${node.label}:${image?.src}` : ''}`;
        let texture = textures.current.get(key);
        if (!texture) {
          texture = bodyTexture(node, state, image);
          textures.current.set(key, texture);
        }
        body.material.map = texture;
        body.material.opacity = nodeAlpha(node, state);
        body.material.needsUpdate = true;
        body.scale.setScalar(node.size * (node.kind === 'twin' ? 2.5 : 3.2));
      }
      const key = `${node.label}:${state.palette['--graph-ink']}:${state.palette['--graph-backdrop']}`;
      const old = labels.current.get(node.id);
      const show =
        state.visible.has(node.id) &&
        (node.kind === 'dimension' ||
          node.kind === 'twin' ||
          state.labelled === node.id);
      if (
        old &&
        (!show || old.userData.key !== key || old.userData.node !== node)
      ) {
        old.removeFromParent();
        old.material.map?.dispose();
        old.material.dispose();
        labels.current.delete(node.id);
      }
      if (show && !labels.current.has(node.id)) {
        const label = textSprite(node, state);
        labels.current.set(node.id, label);
        labelLayer.add(label);
      }
    },
    [labelLayer],
  );
  const makeObject = useCallback(
    (node: MemoryNode) => {
      const group = new THREE.Group();
      // Invisible bounds include batched particles in zoomToFit without adding
      // draw calls. Screen-sized labels live outside these bounds to avoid a fit feedback loop.
      const proxy = new THREE.Mesh(bounds.geometry, bounds.material);
      proxy.visible = false;
      proxy.raycast = () => {};
      proxy.scale.setScalar(node.size);
      group.add(proxy);
      if (node.kind === 'dimension' || node.kind === 'twin') {
        const sprite = new THREE.Sprite(
          new THREE.SpriteMaterial({ transparent: true, depthWrite: false }),
        );
        sprite.name = 'body';
        group.add(sprite);
      } else {
        const sphere = new THREE.Sphere(new THREE.Vector3(), node.size * 1.6);
        const point = new THREE.Vector3();
        group.raycast = (raycaster, intersections) => {
          group.getWorldPosition(sphere.center);
          const hit = raycaster.ray.intersectSphere(sphere, point);
          if (!hit) return;
          const distance = raycaster.ray.origin.distanceTo(hit);
          if (distance >= raycaster.near && distance <= raycaster.far)
            intersections.push({ distance, point: hit.clone(), object: group });
        };
      }
      styleObject(node, group, latest.current.props, latest.current.portrait);
      objects.current.set(node.id, group);
      return group;
    },
    [styleObject, bounds],
  );

  useEffect(() => {
    const graph = fg.current;
    if (!graph) return;
    const lifecycle = generation.current;
    const mountedGeneration = ++lifecycle.value;
    graph.resumeAnimation();
    const controls = graph.controls() as OrbitControls;
    // A gentle bounded orbit keeps radial labels readable instead of eventually
    // turning the entire constellation edge-on. Manual orbit remains unrestricted.
    startRotation(controls);
    controls.addEventListener('start', interact);
    controls.addEventListener('end', interact);
    const radius = Math.max(
      ...latest.current.props.graph.nodes.map((node) => node.size),
      100,
    );
    graph.cameraPosition(
      { x: 0, y: radius * 1.5, z: radius * 6 },
      { x: 0, y: 0, z: 0 },
      0,
    );
    const renderer = graph.renderer();
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    const canvas = renderer.domElement;
    const failure = (event: Event) => {
      event.preventDefault();
      latest.current.props.onFailure();
    };
    canvas.addEventListener('webglcontextlost', failure);
    const visibility = () => {
      if (document.hidden) graph.pauseAnimation();
      else graph.resumeAnimation();
    };
    document.addEventListener('visibilitychange', visibility);
    graph.scene().add(labelLayer);
    const cache = textures.current,
      groups = objects.current,
      textLabels = labels.current;
    return () => {
      clearTimeout(idle.current);
      document.removeEventListener('visibilitychange', visibility);
      canvas.removeEventListener('webglcontextlost', failure);
      controls.removeEventListener('start', interact);
      controls.removeEventListener('end', interact);
      graph.pauseAnimation();
      // StrictMode replays effects without recreating the Kapsule renderer.
      queueMicrotask(() => {
        if (lifecycle.value !== mountedGeneration) return;
        groups.forEach((group) =>
          group.traverse((object) => {
            if (object instanceof THREE.Sprite) {
              if (object.name === 'label') object.material.map?.dispose();
              object.material.dispose();
            }
          }),
        );
        groups.clear();
        textLabels.forEach((label) => {
          label.material.map?.dispose();
          label.material.dispose();
        });
        textLabels.clear();
        labelLayer.removeFromParent();
        bounds.geometry.dispose();
        bounds.material.dispose();
        cache.forEach((texture) => texture.dispose());
        cache.clear();
        renderer.dispose();
        renderer.forceContextLoss();
      });
    };
  }, [interact, labelLayer, bounds]);
  useEffect(() => {
    if (!fg.current) return;
    configureRadialForces(fg.current, 3);
    fg.current.d3ReheatSimulation();
    const controls = fg.current.controls() as OrbitControls;
    const layer = new Graph3DBatch(layout, () => {
      if (!controls.autoRotate) return;
      const angle = controls.getAzimuthalAngle();
      if (angle <= controls.minAzimuthAngle + 0.01)
        controls.autoRotateSpeed = -0.25;
      if (angle >= controls.maxAzimuthAngle - 0.01)
        controls.autoRotateSpeed = 0.25;
    });
    batch.current = layer;
    fg.current.scene().add(layer.group);
    return () => {
      layer.dispose();
      batch.current = null;
    };
  }, [layout]);
  useEffect(() => {
    batch.current?.update(props);
    for (const node of layout.nodes) {
      const group = objects.current.get(node.id);
      if (group) styleObject(node, group, props, portrait);
    }
  }, [layout, props, portrait, styleObject]);
  const fit = useCallback(() => {
    const state = latest.current.props;
    fg.current?.zoomToFit(
      500,
      Math.min(state.width, state.height) * 0.1,
      (node) => state.visible.has(node.id),
    );
  }, []);
  const visibleKey = [...props.visible].sort().join('\0');
  useEffect(() => {
    const timer = setTimeout(fit, 100);
    return () => clearTimeout(timer);
  }, [fit, visibleKey, props.width, props.height, layout]);
  useEffect(() => {
    if (!props.focus) return;
    interact();
    const node = layout.nodes.find((node) => node.id === props.focus!.id);
    if (!node || !fg.current) return;
    if (node.kind === 'dimension')
      fg.current.zoomToFit(
        700,
        65,
        (candidate) => candidate.dimensionId === node.dimensionId,
      );
    else {
      const target = { x: node.x ?? 0, y: node.y ?? 0, z: node.z ?? 0 };
      fg.current.cameraPosition(
        {
          x: target.x,
          y: target.y + 25,
          z: target.z + Math.max(120, node.size * 5),
        },
        target,
        700,
      );
    }
  }, [props.focus, layout, interact]);
  return (
    <div onPointerDownCapture={interact} onWheelCapture={interact}>
      <ForceGraph3D<MemoryNode, MemoryLink>
        ref={fg}
        graphData={layout}
        width={props.width}
        height={props.height}
        backgroundColor={props.palette['--graph-backdrop']}
        controlType="orbit"
        showNavInfo={false}
        nodeThreeObject={makeObject}
        nodeVisibility={(node) => props.visible.has(node.id)}
        nodeLabel={tooltip}
        linkVisibility={false}
        linkDirectionalParticles={0}
        warmupTicks={0}
        cooldownTicks={140}
        d3AlphaDecay={0.035}
        onEngineStop={fit}
        onNodeClick={props.onClick}
        onNodeHover={props.onHover}
        onBackgroundClick={props.onClear}
      />
    </div>
  );
}
