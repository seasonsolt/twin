import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import {
  VRMLoaderPlugin,
  VRMUtils,
  type VRM,
  type VRMMeta,
} from '@pixiv/three-vrm';
import { useMotionPreset } from '../../design/motion';
import { AvatarMotion } from './motion';
import { visibleRenderLoop } from './renderLoop';
import { applyRelaxedPose, fitPortrait, portraitBounds } from './rig';

export interface Avatar3DProps {
  url: string;
  mouth: number;
  speaking: boolean;
  label: string;
  onFallback(): void;
  onModelNameChange?(name: string | null): void;
  still?: boolean;
}

export function modelCredit(meta: VRMMeta) {
  const name = meta.metaVersion === '1' ? meta.name : meta.title;
  const authors =
    meta.metaVersion === '1' ? meta.authors.join('、') : meta.author;
  const license =
    meta.metaVersion === '1' ? meta.licenseUrl : meta.otherLicenseUrl;
  return {
    name: name || null,
    text: `模型：${name || '未命名'} · ${authors || '作者未注明'}`,
    license,
    required: meta.metaVersion === '1' && meta.creditNotation === 'required',
  };
}

export default function Avatar3D(props: Avatar3DProps) {
  const { reduced } = useMotionPreset();
  const host = useRef<HTMLDivElement>(null);
  const latest = useRef({ ...props, reduced });
  const [credit, setCredit] = useState<ReturnType<typeof modelCredit> | null>(
    null,
  );
  useEffect(() => {
    latest.current = { ...props, reduced };
  });
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    setCredit(null);
    latest.current.onModelNameChange?.(null);
    let alive = true;
    let failed = false;
    let renderer: THREE.WebGLRenderer | undefined;
    let vrm: VRM | undefined;
    let stopLoop: (() => void) | undefined;
    let resize: ResizeObserver | undefined;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(32, 1, 0.01, 100);
    const gaze = new THREE.Object3D();
    scene.add(gaze);
    const key = new THREE.DirectionalLight(0xffffff, 2.4);
    const fill = new THREE.DirectionalLight(0xffffff, 1.2);
    const rim = new THREE.DirectionalLight(0xffffff, 1.8);
    const ambient = new THREE.HemisphereLight(0xffffff, 0x625c54, 1.4);
    key.position.set(-1, 2, 3);
    fill.position.set(2, 1, 2);
    rim.position.set(0, 2, -2);
    scene.add(key, fill, rim, ambient);
    const scheme = window.matchMedia('(prefers-color-scheme: dark)');
    const lighting = () => {
      const tokens = getComputedStyle(document.documentElement);
      key.color.set(
        tokens.getPropertyValue('--surface-raised').trim() || '#ffffff',
      );
      fill.color.set(tokens.getPropertyValue('--canvas').trim() || '#fbf8f4');
      rim.color.set(tokens.getPropertyValue('--accent').trim() || '#2563eb');
      ambient.color.set(
        tokens.getPropertyValue('--text-primary').trim() || '#292622',
      );
    };
    scheme.addEventListener('change', lighting);
    lighting();
    const dispose = () => {
      stopLoop?.();
      resize?.disconnect();
      scheme.removeEventListener('change', lighting);
      if (vrm) {
        if (vrm.meta.metaVersion === '0') vrm.meta.texture?.dispose();
        VRMUtils.deepDispose(vrm.scene);
        vrm = undefined;
      }
      renderer?.dispose();
      renderer?.forceContextLoss();
      renderer?.domElement.remove();
      renderer = undefined;
    };
    const fallback = () => {
      if (!alive || failed) return;
      failed = true;
      dispose();
      latest.current.onModelNameChange?.(null);
      latest.current.onFallback();
    };
    try {
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setClearColor(0x000000, 0);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.domElement.setAttribute('aria-label', '风格化 3D 形象');
      renderer.domElement.setAttribute('role', 'img');
      renderer.domElement.style.width = '100%';
      renderer.domElement.style.height = '100%';
      renderer.domElement.addEventListener('webglcontextlost', fallback, {
        once: true,
      });
      element.appendChild(renderer.domElement);
      const loader = new GLTFLoader();
      loader.register((parser) => {
        // Keep embedded blob textures under img-src, not ImageBitmapLoader's fetch/connect-src.
        parser.textureLoader = new THREE.TextureLoader(parser.options.manager)
          .setCrossOrigin(parser.options.crossOrigin)
          .setRequestHeader(parser.options.requestHeader);
        return new VRMLoaderPlugin(parser);
      });
      void loader
        .loadAsync(props.url)
        .then((gltf) => {
          const loaded = gltf.userData.vrm as VRM | undefined;
          if (!alive || !renderer) {
            if (loaded?.meta.metaVersion === '0')
              loaded.meta.texture?.dispose();
            VRMUtils.deepDispose(gltf.scene);
            return;
          }
          if (!loaded) {
            VRMUtils.deepDispose(gltf.scene);
            fallback();
            return;
          }
          vrm = loaded;
          VRMUtils.removeUnnecessaryVertices(vrm.scene);
          VRMUtils.combineSkeletons(vrm.scene);
          VRMUtils.rotateVRM0(vrm);
          scene.add(vrm.scene);
          const bones = vrm.humanoid;
          const head = bones.getNormalizedBoneNode('head');
          if (!head) throw new Error('Missing head');
          const chest =
            bones.getNormalizedBoneNode('chest') ||
            bones.getNormalizedBoneNode('spine');
          applyRelaxedPose(bones);
          vrm.update(0);
          vrm.scene.updateMatrixWorld(true);
          const size = new THREE.Box3()
            .setFromObject(vrm.scene)
            .getSize(new THREE.Vector3());
          const height = Math.max(size.y, 0.5);
          const portrait = portraitBounds(
            vrm.scene,
            head,
            bones.getRawBoneNode('head'),
          );
          const fit = () => {
            if (!renderer) return;
            const width = Math.max(element.clientWidth, 1);
            const canvasHeight = Math.max(element.clientHeight, 1);
            fitPortrait(
              camera,
              portrait.target,
              portrait.headHeight,
              width / canvasHeight,
            );
            renderer.setSize(width, canvasHeight, false);
            if (props.still) renderer.render(scene, camera);
          };
          resize = new ResizeObserver(fit);
          resize.observe(element);
          fit();
          if (vrm.lookAt) vrm.lookAt.target = gaze;
          const headRest = head.rotation.clone();
          const chestRest = chest?.rotation.clone();
          const motion = new AvatarMotion();
          const metadata = modelCredit(vrm.meta);
          setCredit(metadata);
          latest.current.onModelNameChange?.(metadata.name);
          if (props.still) return;
          stopLoop = visibleRenderLoop(element, (delta) => {
            if (!vrm || !renderer) return;
            const state = latest.current;
            const pose = motion.step(
              delta,
              state.mouth,
              state.speaking,
              state.reduced,
            );
            for (const expression of ['aa', 'oh', 'ih', 'blink'] as const) {
              vrm.expressionManager?.setValue(expression, pose[expression]);
            }
            head.rotation.copy(headRest);
            head.rotation.x += pose.pitch;
            head.rotation.y += pose.yaw;
            if (chest && chestRest) {
              chest.rotation.copy(chestRest);
              chest.rotation.x += pose.breath;
            }
            gaze.position
              .copy(camera.position)
              .add(
                new THREE.Vector3(
                  pose.gaze.x * height,
                  pose.gaze.y * height,
                  0,
                ),
              );
            try {
              vrm.update(delta);
              renderer.render(scene, camera);
            } catch {
              fallback();
            }
          });
        })
        .catch(fallback);
    } catch {
      fallback();
    }
    return () => {
      alive = false;
      dispose();
    };
  }, [props.url, props.still]);
  const licenseUrl =
    credit?.license && /^https?:\/\//i.test(credit.license)
      ? credit.license
      : undefined;
  if (props.still)
    return (
      <div
        ref={host}
        className="size-full"
        title={credit?.text}
        aria-label="VRM 静态头像"
      />
    );
  return (
    <div className="mx-auto w-full max-w-64 shrink-0">
      <div className="relative aspect-[4/5]">
        <div ref={host} className="absolute inset-0" />
        <p
          role="note"
          className="absolute bottom-2 left-2 whitespace-nowrap rounded-sm border border-border/50 bg-surface/80 px-1.5 py-0.5 text-[10px] leading-tight text-secondary"
        >
          {props.label}
        </p>
      </div>
      {credit && (
        <p className="mt-1 text-center text-xs text-tertiary">
          {credit.text}
          {licenseUrl && (
            <>
              {' '}
              ·{' '}
              <a
                href={licenseUrl}
                target="_blank"
                rel="noreferrer"
                className="underline"
              >
                许可
              </a>
            </>
          )}
        </p>
      )}
    </div>
  );
}
