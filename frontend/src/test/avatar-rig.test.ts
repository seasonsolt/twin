import { expect, it, vi } from 'vitest';
import * as THREE from 'three';
import {
  applyRelaxedPose,
  fitPortrait,
  portraitBounds,
} from '../features/avatar/rig';

it.each([1, -1])(
  'lowers normalized arms for either bind-axis convention (%s), bends elbows and relaxes hands',
  (axis) => {
    const root = new THREE.Group();
    const nodes = new Map<string, THREE.Object3D>();
    if (axis === -1) root.rotation.y = Math.PI;
    for (const side of ['left', 'right'] as const) {
      const outward = (side === 'left' ? 1 : -1) * axis;
      const upper = new THREE.Group();
      const lower = new THREE.Group();
      const hand = new THREE.Group();
      lower.position.x = outward * 0.3;
      hand.position.x = outward * 0.25;
      root.add(upper);
      upper.add(lower);
      lower.add(hand);
      nodes.set(`${side}UpperArm`, upper);
      nodes.set(`${side}LowerArm`, lower);
      nodes.set(`${side}Hand`, hand);
      const finger = new THREE.Group();
      hand.add(finger);
      nodes.set(`${side}IndexProximal`, finger);
    }
    const humanoid = {
      autoUpdateHumanBones: false,
      getNormalizedBoneNode: vi.fn((name: string) => nodes.get(name) || null),
    };
    applyRelaxedPose(humanoid);
    expect(humanoid.autoUpdateHumanBones).toBe(true);
    for (const side of ['left', 'right'] as const) {
      const upper = nodes.get(`${side}UpperArm`)!;
      const lower = nodes.get(`${side}LowerArm`)!;
      const hand = nodes.get(`${side}Hand`)!;
      const mirror = side === 'left' ? -1 : 1;
      expect(Math.abs(upper.rotation.z)).toBeCloseTo(
        THREE.MathUtils.degToRad(70),
      );
      expect(lower.rotation.y).toBeCloseTo(
        mirror * THREE.MathUtils.degToRad(12),
      );
      expect(hand.rotation.y).toBeCloseTo(mirror * THREE.MathUtils.degToRad(5));
      expect(nodes.get(`${side}IndexProximal`)!.rotation.y).toBeCloseTo(
        mirror * THREE.MathUtils.degToRad(10),
      );
      const direction = lower
        .getWorldPosition(new THREE.Vector3())
        .sub(upper.getWorldPosition(new THREE.Vector3()))
        .normalize();
      expect(direction.y).toBeCloseTo(-Math.sin(THREE.MathUtils.degToRad(70)));
      const rest = upper.quaternion.clone();
      applyRelaxedPose(humanoid);
      expect(upper.quaternion.equals(rest)).toBe(true);
    }
  },
);

it('allows optional arm, hand and finger bones to be absent', () => {
  expect(() =>
    applyRelaxedPose({
      autoUpdateHumanBones: true,
      getNormalizedBoneNode: () => null,
    }),
  ).not.toThrow();
});

it('fits head-weighted vertices, not the body or long hair, to half a 4:5 portrait with a 5-degree downward view', () => {
  const scene = new THREE.Group();
  const head = new THREE.Bone();
  head.position.y = 1.5;
  const hair = new THREE.Bone();
  head.add(hair);
  const body = new THREE.Bone();
  scene.add(head, body);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    'position',
    new THREE.Float32BufferAttribute(
      [0, 1.5, 0, 0, 1.9, 0, 0, 0.1, 0, 0, 0.5, 0],
      3,
    ),
  );
  geometry.setAttribute(
    'skinIndex',
    new THREE.Uint16BufferAttribute(
      [0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 2, 0, 0, 0],
      4,
    ),
  );
  geometry.setAttribute(
    'skinWeight',
    new THREE.Float32BufferAttribute(
      [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
      4,
    ),
  );
  const material = new THREE.MeshBasicMaterial();
  const mesh = new THREE.SkinnedMesh(geometry, material);
  scene.add(mesh);
  scene.updateMatrixWorld(true);
  const skeleton = new THREE.Skeleton([head, body, hair]);
  mesh.bind(skeleton);
  const portrait = portraitBounds(scene, head, head);
  expect(portrait.headHeight).toBeCloseTo(0.4);
  expect(portrait.target.y).toBeCloseTo(1.6);
  const camera = new THREE.PerspectiveCamera(32, 1, 0.01, 100);
  fitPortrait(camera, portrait.target, portrait.headHeight, 4 / 5);
  expect(camera.aspect).toBe(0.8);
  const bottom = new THREE.Vector3(0, 1.5, 0).project(camera);
  const top = new THREE.Vector3(0, 1.9, 0).project(camera);
  const fraction = (top.y - bottom.y) / 2;
  expect(fraction).toBeGreaterThan(0.45);
  expect(fraction).toBeLessThan(0.55);
  expect(top.y).toBeLessThan(1);
  const shoulder = new THREE.Vector3(0.2, 1.3, 0).project(camera);
  expect(Math.abs(shoulder.x)).toBeLessThan(1);
  expect(Math.abs(shoulder.y)).toBeLessThan(1);
  const direction = camera.getWorldDirection(new THREE.Vector3());
  expect(Math.asin(-direction.y)).toBeCloseTo(THREE.MathUtils.degToRad(5));
  geometry.dispose();
  material.dispose();
  skeleton.dispose();
});
