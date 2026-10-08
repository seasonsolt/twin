import * as THREE from 'three';
import type { MemoryNode } from './buildMemoryGraph';

export interface ScreenBounds {
  left: number;
  right: number;
  top: number;
  bottom: number;
}
const empty = (): ScreenBounds => ({
  left: Infinity,
  right: -Infinity,
  top: Infinity,
  bottom: -Infinity,
});
const include = (
  bounds: ScreenBounds,
  x: number,
  y: number,
  rx: number,
  ry: number,
) => {
  bounds.left = Math.min(bounds.left, x - rx);
  bounds.right = Math.max(bounds.right, x + rx);
  bounds.top = Math.min(bounds.top, y - ry);
  bounds.bottom = Math.max(bounds.bottom, y + ry);
};
const labelText = (node: MemoryNode) =>
  node.label.length > 32 ? `${node.label.slice(0, 32)}…` : node.label;
const measurements = new Map<string, number>();
function measure(text: string, font: number) {
  const key = `${font}:${text}`;
  const cached = measurements.get(key);
  if (cached !== undefined) return cached;
  const ctx = document.createElement('canvas').getContext('2d');
  if (!ctx) return text.length * font;
  ctx.font = `600 ${font}px sans-serif`;
  const measured = ctx.measureText(text).width;
  measurements.set(key, measured);
  return measured;
}
const labelled = (node: MemoryNode, label?: string | null) =>
  node.kind === 'dimension' || node.kind === 'twin' || node.id === label;
const span = (b: ScreenBounds) => Math.max(b.right - b.left, b.bottom - b.top);

export function projectedBounds2D(
  nodes: MemoryNode[],
  scale: number,
  width: number,
  label?: string | null,
): ScreenBounds {
  const bounds = empty();
  for (const node of nodes) {
    const x = (node.x ?? 0) * scale,
      y = (node.y ?? 0) * scale;
    const radius = node.size * scale;
    include(bounds, x, y, radius + 3, radius + 3);
    if (!labelled(node, label)) continue;
    const font =
      node.kind === 'dimension' || node.kind === 'twin'
        ? width < 500
          ? 14
          : 15
        : 13;
    const textWidth = measure(labelText(node), font);
    let lx = x,
      ly = y + radius + 16;
    if (node.kind === 'dimension') {
      const angle = node.layoutAngle ?? 0,
        cosine = Math.cos(angle);
      lx =
        x +
        cosine * (radius + 10) +
        (Math.abs(cosine) > 0.3 ? (Math.sign(cosine) * textWidth) / 2 : 0);
      ly = y + Math.sin(angle) * (radius + 10);
    }
    include(bounds, lx, ly, textWidth / 2 + 4, font / 2 + 4);
  }
  return bounds;
}

export function fit2D(
  nodes: MemoryNode[],
  width: number,
  height: number,
  label?: string | null,
) {
  if (!nodes.length) return null;
  const target = 0.85 * Math.min(width, height);
  let low = 0.0001,
    high = 1000;
  for (let i = 0; i < 50; i++) {
    const scale = (low + high) / 2;
    if (span(projectedBounds2D(nodes, scale, width, label)) > target)
      high = scale;
    else low = scale;
  }
  const bounds = projectedBounds2D(nodes, low, width, label);
  return {
    zoom: low,
    x: (bounds.left + bounds.right) / 2 / low,
    y: (bounds.top + bounds.bottom) / 2 / low,
  };
}

export function projectedBounds3D(
  nodes: MemoryNode[],
  camera: THREE.PerspectiveCamera,
  width: number,
  height: number,
  label?: string | null,
): ScreenBounds {
  camera.updateMatrixWorld(true);
  const bounds = empty();
  const project = (point: THREE.Vector3) => {
    const screen = point.clone().project(camera);
    return {
      x: ((screen.x + 1) * width) / 2,
      y: ((1 - screen.y) * height) / 2,
    };
  };
  for (const node of nodes) {
    const point = new THREE.Vector3(node.x ?? 0, node.y ?? 0, node.z ?? 0);
    const view = point.clone().applyMatrix4(camera.matrixWorldInverse);
    if (view.z >= -node.size)
      return {
        left: -Infinity,
        right: Infinity,
        top: -Infinity,
        bottom: Infinity,
      };
    const ppu = (height * camera.projectionMatrix.elements[5]) / (2 * -view.z);
    const screen = project(point);
    const radius =
      node.size *
      (node.kind === 'twin' || node.kind === 'dimension' ? 1.25 : 1.6) *
      ppu;
    include(bounds, screen.x, screen.y, radius + 3, radius + 3);
    if (!labelled(node, label)) continue;
    const fontHeight =
      node.kind === 'twin' || node.kind === 'dimension' ? 24 : 20;
    const textWidth = ((measure(labelText(node), 40) + 24) * fontHeight) / 64;
    if (node.kind === 'dimension') {
      const angle = node.layoutAngle ?? 0,
        cosine = Math.cos(angle);
      point.x +=
        cosine * (node.size + 10 / ppu) +
        (Math.abs(cosine) > 0.3
          ? (Math.sign(cosine) * textWidth) / 2 / ppu
          : 0);
      point.y += Math.sin(angle) * (node.size + 10 / ppu);
    } else point.y -= node.size + 16 / ppu;
    const position = project(point);
    include(
      bounds,
      position.x,
      position.y,
      textWidth / 2 + 4,
      fontHeight / 2 + 4,
    );
  }
  return bounds;
}

export function fit3D(
  nodes: MemoryNode[],
  camera: THREE.PerspectiveCamera,
  width: number,
  height: number,
  label?: string | null,
) {
  if (!nodes.length) return null;
  const probe = camera.clone();
  probe.aspect = width / height;
  probe.updateProjectionMatrix();
  const box = new THREE.Box3().setFromPoints(
    nodes.map(
      (node) => new THREE.Vector3(node.x ?? 0, node.y ?? 0, node.z ?? 0),
    ),
  );
  const target = box.getCenter(new THREE.Vector3());
  const direction = camera.getWorldDirection(new THREE.Vector3()).negate();
  const desired = Math.min(width, height) * 0.85;
  let distance = 1;
  for (let recenter = 0; recenter < 4; recenter++) {
    let low = 0.1,
      high = Math.max(1000, box.getSize(new THREE.Vector3()).length() * 100);
    for (let i = 0; i < 50; i++) {
      distance = (low + high) / 2;
      probe.position.copy(target).addScaledVector(direction, distance);
      probe.lookAt(target);
      if (span(projectedBounds3D(nodes, probe, width, height, label)) > desired)
        low = distance;
      else high = distance;
    }
    distance = high;
    probe.position.copy(target).addScaledVector(direction, distance);
    probe.lookAt(target);
    const bounds = projectedBounds3D(nodes, probe, width, height, label);
    const ppu = (height * probe.projectionMatrix.elements[5]) / (2 * distance);
    const right = new THREE.Vector3().setFromMatrixColumn(probe.matrixWorld, 0);
    const up = new THREE.Vector3().setFromMatrixColumn(probe.matrixWorld, 1);
    target.addScaledVector(
      right,
      ((bounds.left + bounds.right) / 2 - width / 2) / ppu,
    );
    target.addScaledVector(
      up,
      -((bounds.top + bounds.bottom) / 2 - height / 2) / ppu,
    );
  }
  return {
    position: target.clone().addScaledVector(direction, distance),
    target,
  };
}
