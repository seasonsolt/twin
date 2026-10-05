import * as THREE from 'three';
import type { VRMHumanoid, VRMHumanBoneName } from '@pixiv/three-vrm';

export function applyRelaxedPose(
  humanoid: Pick<VRMHumanoid, 'getNormalizedBoneNode' | 'autoUpdateHumanBones'>,
) {
  humanoid.autoUpdateHumanBones = true;
  for (const side of ['left', 'right'] as const) {
    const upper = humanoid.getNormalizedBoneNode(`${side}UpperArm`);
    const lower = humanoid.getNormalizedBoneNode(`${side}LowerArm`);
    const hand = humanoid.getNormalizedBoneNode(`${side}Hand`);
    // Normalized rotations are bind-relative; use the rig's arm direction, not raw VRM-version axes.
    const outward = Math.sign(
      lower?.position.x || upper?.position.x || (side === 'left' ? 1 : -1),
    );
    const mirror = side === 'left' ? -1 : 1;
    if (upper)
      upper.rotation.set(0, 0, -outward * THREE.MathUtils.degToRad(70));
    if (lower) lower.rotation.set(0, mirror * THREE.MathUtils.degToRad(12), 0);
    if (hand)
      hand.rotation.set(
        0,
        mirror * THREE.MathUtils.degToRad(5),
        -outward * THREE.MathUtils.degToRad(3),
      );
    for (const finger of ['Index', 'Middle', 'Ring', 'Little'] as const) {
      const joint = humanoid.getNormalizedBoneNode(
        `${side}${finger}Proximal` as VRMHumanBoneName,
      );
      if (joint)
        joint.rotation.set(0, mirror * THREE.MathUtils.degToRad(10), 0);
    }
  }
}

export function portraitBounds(
  scene: THREE.Object3D,
  head: THREE.Object3D,
  rawHead: THREE.Object3D | null,
) {
  const headPosition = head.getWorldPosition(new THREE.Vector3());
  const headBones = new Set<THREE.Object3D>();
  // Exclude descendant spring bones so long hair does not inflate the face framing.
  if (rawHead) headBones.add(rawHead);
  const bounds = new THREE.Box3();
  const vertex = new THREE.Vector3();
  scene.traverse((node) => {
    const mesh = node as THREE.SkinnedMesh;
    if (!mesh.isSkinnedMesh) return;
    const indices = mesh.geometry.getAttribute('skinIndex');
    const weights = mesh.geometry.getAttribute('skinWeight');
    if (!indices || !weights) return;
    const headIndices = new Set(
      mesh.skeleton.bones.flatMap((bone, index) =>
        headBones.has(bone) ? [index] : [],
      ),
    );
    for (let i = 0; i < indices.count; i++) {
      let influence = 0;
      for (let j = 0; j < 4; j++) {
        if (headIndices.has(indices.getComponent(i, j)))
          influence += weights.getComponent(i, j);
      }
      if (influence < 0.5) continue;
      mesh.getVertexPosition(i, vertex).applyMatrix4(mesh.matrixWorld);
      bounds.expandByPoint(vertex);
    }
  });
  if (bounds.isEmpty()) {
    const height =
      Math.max(new THREE.Box3().setFromObject(scene).getSize(vertex).y, 0.5) *
      0.2;
    bounds.setFromCenterAndSize(
      headPosition.clone().add(new THREE.Vector3(0, height * 0.25, 0)),
      new THREE.Vector3(height, height, height),
    );
  }
  const headHeight = Math.max(bounds.max.y - bounds.min.y, 0.05);
  // Keep the face above center, leaving the lower portrait for the shoulders.
  const target = headPosition.clone();
  target.y = bounds.min.y + headHeight * 0.25;
  return { target, headHeight };
}

export function fitPortrait(
  camera: THREE.PerspectiveCamera,
  target: THREE.Vector3,
  headHeight: number,
  aspect: number,
) {
  camera.aspect = aspect;
  const distance =
    headHeight / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
  const tilt = THREE.MathUtils.degToRad(5);
  camera.position
    .copy(target)
    .add(
      new THREE.Vector3(
        0,
        Math.sin(tilt) * distance,
        Math.cos(tilt) * distance,
      ),
    );
  camera.lookAt(target);
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld(true);
}
