import { useEffect, useRef, useState } from 'react';
import { animate } from 'motion/react';
import * as THREE from 'three';
import { useMotionPreset } from '../../design/motion';
import { cn } from '../../lib/utils';

/*
 * The ten aspects of a person as a constellation around the twin's heart: one cluster of light for each, in its own
 * graph colour (--graph-d1 … --graph-d10), fuller and brighter the better it is known. The chosen one turns to face
 * the viewer; a drag turns the whole of it, and a click on a cluster chooses it. With reduced motion it turns at once
 * and draws only when something changes; where WebGL is missing a soft glow stands in, and the list beside it still
 * chooses.
 */

export interface ConstellationAspect {
  id: string;
  /** 0 not known yet … 3 known well. */
  level: number;
  /** How many memories it holds. */
  total: number;
}

// The same scatter on every load, so a still frame (reduced motion, screenshots) does not change.
function seeded(seed: number) {
  let state = seed;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function glowTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 64;
  const context = canvas.getContext('2d');
  if (context) {
    const gradient = context.createRadialGradient(32, 32, 0, 32, 32, 32);
    gradient.addColorStop(0, 'rgba(255,255,255,1)');
    gradient.addColorStop(0.3, 'rgba(255,255,255,0.4)');
    gradient.addColorStop(1, 'rgba(255,255,255,0)');
    context.fillStyle = gradient;
    context.fillRect(0, 0, 64, 64);
  }
  return new THREE.CanvasTexture(canvas);
}

function readColor(name: string, fallback: string) {
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return new THREE.Color(value || fallback);
}

const aspectColor = (id: string) =>
  readColor(`--graph-${id.toLowerCase()}`, '#d6b36e');

/** Where each of n clusters sits: spread evenly over a sphere (a Fibonacci lattice). */
function placements(n: number, radius: number) {
  const golden = Math.PI * (3 - Math.sqrt(5));
  return Array.from({ length: n }, (_, i) => {
    const y = 1 - ((i + 0.5) / n) * 2;
    const ring = Math.sqrt(1 - y * y);
    const angle = golden * i;
    return new THREE.Vector3(
      Math.cos(angle) * ring * radius,
      y * radius * 0.8,
      Math.sin(angle) * ring * radius,
    );
  });
}

// The chosen aspect comes forward a little above and to the right of the heart, so it never hides it.
const FORWARD = new THREE.Vector3(0.5, 0.3, 0.8).normalize();

export function AspectConstellation({
  aspects,
  selected,
  onSelect,
  label,
  className,
}: {
  aspects: ConstellationAspect[];
  selected: string;
  onSelect: (id: string) => void;
  label: string;
  /** Layout only (its box: size and placement). */
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { reduced } = useMotionPreset('gentle');
  const [failed, setFailed] = useState(false);
  const chooseRef = useRef(onSelect);
  chooseRef.current = onSelect;
  const selectedRef = useRef(selected);
  const aspectsRef = useRef(aspects);
  aspectsRef.current = aspects;
  const turnRef = useRef<((id: string) => void) | null>(null);
  // The scene is built again only when what it shows changes, not on every render of the page.
  const shape = aspects.map((a) => `${a.id}:${a.level}:${a.total}`).join(',');

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const aspects = aspectsRef.current;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        canvas,
        antialias: true,
        alpha: true,
      });
    } catch {
      setFailed(true);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
    camera.position.set(0, 0, 8.8);
    const rig = new THREE.Group();
    scene.add(rig);
    const texture = glowTexture();
    const additive = THREE.AdditiveBlending;
    const disposables: { dispose(): void }[] = [texture];
    const keep = <T extends { dispose(): void }>(item: T) => {
      disposables.push(item);
      return item;
    };

    // The heart: the twin the aspects are of.
    const heartGlow = keep(
      new THREE.SpriteMaterial({
        map: texture,
        color: readColor('--accent', '#ff8a5b'),
        transparent: true,
        opacity: 0.7,
        depthWrite: false,
        blending: additive,
      }),
    );
    const heartSprite = new THREE.Sprite(heartGlow);
    heartSprite.scale.setScalar(1.1);
    rig.add(heartSprite);
    const heartMaterial = keep(
      new THREE.MeshBasicMaterial({ color: readColor('--core', '#ffe2cc') }),
    );
    rig.add(
      new THREE.Mesh(
        keep(new THREE.SphereGeometry(0.07, 20, 20)),
        heartMaterial,
      ),
    );
    const shellMaterial = keep(
      new THREE.LineBasicMaterial({
        color: readColor('--text-primary', '#edeae4'),
        transparent: true,
        opacity: 0.1,
      }),
    );
    rig.add(
      new THREE.LineSegments(
        keep(
          new THREE.WireframeGeometry(
            keep(new THREE.IcosahedronGeometry(0.55, 1)),
          ),
        ),
        shellMaterial,
      ),
    );

    const spots = placements(aspects.length, 2.3);
    const random = seeded(11);
    const clusters = aspects.map((aspect, index) => {
      const centre = spots[index];
      const known = aspect.level / 3;
      const count = 10 + aspect.level * 14 + Math.min(aspect.total, 40);
      const positions = new Float32Array(count * 3);
      for (let i = 0; i < count; i++) {
        // A soft ball: most points near the middle, a few further out.
        const spread = 0.12 + 0.22 * random() ** 1.6;
        const u = random() * 2 - 1;
        const angle = random() * Math.PI * 2;
        const ring = Math.sqrt(1 - u * u);
        positions[i * 3] = centre.x + spread * ring * Math.cos(angle);
        positions[i * 3 + 1] = centre.y + spread * u;
        positions[i * 3 + 2] = centre.z + spread * ring * Math.sin(angle);
      }
      const geometry = keep(new THREE.BufferGeometry());
      geometry.setAttribute(
        'position',
        new THREE.BufferAttribute(positions, 3),
      );
      const color = aspectColor(aspect.id);
      const pointMaterial = keep(
        new THREE.PointsMaterial({
          map: texture,
          color,
          size: 0.09,
          transparent: true,
          opacity: 0.35 + 0.65 * known,
          depthWrite: false,
          blending: additive,
        }),
      );
      rig.add(new THREE.Points(geometry, pointMaterial));
      const glowMaterial = keep(
        new THREE.SpriteMaterial({
          map: texture,
          color,
          transparent: true,
          opacity: 0.15 + 0.4 * known,
          depthWrite: false,
          blending: additive,
        }),
      );
      const glow = new THREE.Sprite(glowMaterial);
      glow.position.copy(centre);
      glow.scale.setScalar(0.7 + 0.5 * known);
      rig.add(glow);
      const threadMaterial = keep(
        new THREE.LineBasicMaterial({
          color,
          transparent: true,
          opacity: 0.06 + 0.12 * known,
        }),
      );
      rig.add(
        new THREE.Line(
          keep(
            new THREE.BufferGeometry().setFromPoints([
              new THREE.Vector3(),
              centre,
            ]),
          ),
          threadMaterial,
        ),
      );
      return {
        id: aspect.id,
        centre,
        known,
        glow,
        pointMaterial,
        glowMaterial,
        threadMaterial,
      };
    });

    // The ring that marks the chosen aspect, drawn facing the viewer.
    const markMaterial = keep(
      new THREE.LineBasicMaterial({
        color: readColor('--text-primary', '#edeae4'),
        transparent: true,
        opacity: 0.55,
      }),
    );
    const mark = new THREE.LineLoop(
      keep(
        new THREE.BufferGeometry().setFromPoints(
          new THREE.EllipseCurve(0, 0, 0.46, 0.46)
            .getPoints(64)
            .map((point) => new THREE.Vector3(point.x, point.y, 0)),
        ),
      ),
      markMaterial,
    );
    scene.add(mark);

    const draw = () => {
      const chosen = clusters.find((c) => c.id === selectedRef.current);
      mark.visible = !!chosen;
      if (chosen) {
        mark.position.copy(chosen.centre).applyMatrix4(rig.matrixWorld);
      }
      renderer.render(scene, camera);
    };
    const target = new THREE.Quaternion();
    const facing = (id: string) => {
      const chosen = clusters.find((c) => c.id === id);
      return chosen
        ? new THREE.Quaternion().setFromUnitVectors(
            chosen.centre.clone().normalize(),
            FORWARD,
          )
        : new THREE.Quaternion();
    };
    const emphasise = (id: string) => {
      for (const cluster of clusters) {
        const on = cluster.id === id;
        cluster.glow.scale.setScalar(
          (0.7 + 0.5 * cluster.known) * (on ? 1.5 : 1),
        );
        cluster.glowMaterial.opacity =
          (0.15 + 0.4 * cluster.known) * (on ? 1.6 : 1);
        cluster.threadMaterial.opacity =
          (0.06 + 0.12 * cluster.known) * (on ? 2.5 : 1);
      }
    };
    target.copy(facing(selectedRef.current));
    rig.quaternion.copy(target);
    emphasise(selectedRef.current);
    rig.updateMatrixWorld();
    turnRef.current = (id) => {
      emphasise(id);
      target.copy(facing(id));
      if (reduced) {
        rig.quaternion.copy(target);
        rig.updateMatrixWorld();
        draw();
      }
    };

    const resize = () => {
      const width = canvas.clientWidth || 1;
      const height = canvas.clientHeight || 1;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      draw();
    };
    const resizer = new ResizeObserver(resize);
    resizer.observe(canvas);
    resize();

    // A drag turns it; a press that hardly moves chooses the cluster nearest to it.
    let pressed: { x: number; y: number; moved: number } | null = null;
    const down = (event: PointerEvent) => {
      pressed = { x: event.clientX, y: event.clientY, moved: 0 };
      canvas.setPointerCapture?.(event.pointerId);
    };
    const move = (event: PointerEvent) => {
      if (!pressed) return;
      const dx = event.clientX - pressed.x;
      const dy = event.clientY - pressed.y;
      pressed = {
        x: event.clientX,
        y: event.clientY,
        moved: pressed.moved + Math.abs(dx) + Math.abs(dy),
      };
      const spin = new THREE.Quaternion().setFromEuler(
        new THREE.Euler(dy * 0.006, dx * 0.006, 0),
      );
      rig.quaternion.premultiply(spin);
      target.copy(rig.quaternion);
      rig.updateMatrixWorld();
      if (reduced) draw();
    };
    const up = (event: PointerEvent) => {
      const press = pressed;
      pressed = null;
      if (!press || press.moved > 6) return;
      const box = canvas.getBoundingClientRect();
      let best: { id: string; distance: number } | null = null;
      for (const cluster of clusters) {
        const at = cluster.centre
          .clone()
          .applyMatrix4(rig.matrixWorld)
          .project(camera);
        const x = ((at.x + 1) / 2) * box.width + box.left;
        const y = ((1 - at.y) / 2) * box.height + box.top;
        const distance = Math.hypot(x - event.clientX, y - event.clientY);
        if (distance < 48 && (!best || distance < best.distance))
          best = { id: cluster.id, distance };
      }
      if (best) chooseRef.current(best.id);
    };
    canvas.addEventListener('pointerdown', down);
    canvas.addEventListener('pointermove', move);
    canvas.addEventListener('pointerup', up);
    canvas.addEventListener('pointercancel', up);

    let frame = 0;
    let last = performance.now();
    let time = 0;
    const tick = (now: number) => {
      const delta = Math.min((now - last) / 1000, 0.05);
      last = now;
      time += delta;
      if (!pressed) rig.quaternion.slerp(target, 0.05);
      rig.updateMatrixWorld();
      heartGlow.opacity = 0.6 + 0.15 * Math.sin(time * 1.6);
      draw();
      frame = requestAnimationFrame(tick);
    };
    if (!reduced) frame = requestAnimationFrame(tick);

    // A new palette: each cluster takes its new colour, eased across unless motion is reduced.
    const recolour = () => {
      const from = clusters.map((c) => c.pointMaterial.color.clone());
      const to = clusters.map((c) => aspectColor(c.id));
      const accent = {
        from: heartGlow.color.clone(),
        to: readColor('--accent', '#ff8a5b'),
      };
      const core = {
        from: heartMaterial.color.clone(),
        to: readColor('--core', '#ffe2cc'),
      };
      const ink = {
        from: markMaterial.color.clone(),
        to: readColor('--text-primary', '#edeae4'),
      };
      const apply = (k: number) => {
        clusters.forEach((cluster, index) => {
          const color = cluster.pointMaterial.color.lerpColors(
            from[index],
            to[index],
            k,
          );
          cluster.glowMaterial.color.copy(color);
          cluster.threadMaterial.color.copy(color);
        });
        heartGlow.color.lerpColors(accent.from, accent.to, k);
        heartMaterial.color.lerpColors(core.from, core.to, k);
        markMaterial.color.lerpColors(ink.from, ink.to, k);
        shellMaterial.color.copy(markMaterial.color);
      };
      if (reduced) {
        apply(1);
        draw();
      } else {
        void animate(0, 1, {
          duration: 0.9,
          ease: [0.2, 0.7, 0.2, 1],
          onUpdate: apply,
        });
      }
    };
    const themeWatch = new MutationObserver(recolour);
    themeWatch.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    });

    return () => {
      turnRef.current = null;
      cancelAnimationFrame(frame);
      canvas.removeEventListener('pointerdown', down);
      canvas.removeEventListener('pointermove', move);
      canvas.removeEventListener('pointerup', up);
      canvas.removeEventListener('pointercancel', up);
      resizer.disconnect();
      themeWatch.disconnect();
      for (const item of disposables) item.dispose();
      renderer.dispose();
    };
    // The aspects are read from the ref: the scene is built again when their shape changes.
  }, [shape, reduced]);

  useEffect(() => {
    selectedRef.current = selected;
    turnRef.current?.(selected);
  }, [selected]);

  return failed ? (
    <div
      role="img"
      aria-label={label}
      className={cn('twin-core-fallback', className)}
    />
  ) : (
    <canvas
      ref={canvasRef}
      role="img"
      aria-label={label}
      className={cn('block cursor-grab touch-none', className)}
    />
  );
}
