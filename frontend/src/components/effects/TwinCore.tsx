import { animate } from 'motion/react';
import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { useMotionPreset } from '../../design/motion';
import { cn } from '../../lib/utils';

/*
 * The twin's core: a wire shell (the machine), a breathing translucent body inside it (the living part) and a warm
 * point at its heart (the memory). It takes its colours from the theme (--accent, --core, --text-primary) and eases
 * to the new ones when the palette changes. With reduced motion it is drawn once and holds still; where WebGL is
 * missing (old hardware, tests) a soft glow of the same colours stands in.
 */

const VERTEX = `
uniform float uTime;
uniform float uPulse;
varying float vRim;
varying float vLift;
void main() {
  vec3 p = position;
  float t = uTime * 0.6;
  float lift = 0.09 * sin(3.1 * p.x + t) * sin(2.7 * p.y + t * 1.3) * sin(3.3 * p.z + t * 0.8)
    + 0.035 * sin(7.0 * p.y + t * 2.0) + 0.06 * uPulse * sin(9.0 * p.x + t * 3.0);
  vec4 view = modelViewMatrix * vec4(p * (1.0 + lift), 1.0);
  vec3 normalView = normalize(normalMatrix * normal);
  vRim = pow(1.0 - abs(dot(normalView, normalize(-view.xyz))), 2.4);
  vLift = lift;
  gl_Position = projectionMatrix * view;
}`;

const FRAGMENT = `
uniform vec3 uWarm;
uniform vec3 uDeep;
uniform float uPulse;
uniform float uLight;
varying float vRim;
varying float vLift;
void main() {
  vec3 color = mix(uDeep, uWarm, vRim) + uWarm * max(vLift, 0.0) * 1.4;
  if (uLight < 0.5) {
    color += vec3(1.0, 0.94, 0.88) * pow(vRim, 6.0) * 0.6;
    float alpha = 0.16 + vRim * 0.7 + uPulse * 0.25;
    gl_FragColor = vec4(color * alpha, alpha);
  } else {
    gl_FragColor = vec4(color, 0.1 + vRim * 0.75 + uPulse * 0.15);
  }
}`;

const BREATH = 4.5;

interface Palette {
  warm: THREE.Color;
  core: THREE.Color;
  ink: THREE.Color;
  light: boolean;
}

function readPalette(): Palette {
  const style = getComputedStyle(document.documentElement);
  const color = (name: string, fallback: string) =>
    new THREE.Color(style.getPropertyValue(name).trim() || fallback);
  const canvas = color('--canvas', '#07090b');
  return {
    warm: color('--accent', '#ff8a5b'),
    core: color('--core', '#ffe2cc'),
    ink: color('--text-primary', '#edeae4'),
    light: canvas.r * 0.2126 + canvas.g * 0.7152 + canvas.b * 0.0722 > 0.5,
  };
}

// The same scatter of dust on every load, so a still frame (reduced motion, screenshots) does not change.
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
  canvas.width = canvas.height = 128;
  const context = canvas.getContext('2d');
  if (context) {
    const gradient = context.createRadialGradient(64, 64, 0, 64, 64, 64);
    gradient.addColorStop(0, 'rgba(255,255,255,1)');
    gradient.addColorStop(0.25, 'rgba(255,255,255,0.45)');
    gradient.addColorStop(1, 'rgba(255,255,255,0)');
    context.fillStyle = gradient;
    context.fillRect(0, 0, 128, 128);
  }
  return new THREE.CanvasTexture(canvas);
}

export function TwinCore({
  pulse = 0,
  scale = 1,
  label = '分身的心核',
  className,
}: {
  /** Raise it each time the twin speaks: the core swells and brightens once. */
  pulse?: number;
  /** How large the core is drawn in its box (1 fills about two thirds of the height). */
  scale?: number;
  label?: string;
  /** Layout only (its box: size and placement). */
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pulseRef = useRef<(() => void) | null>(null);
  const { reduced } = useMotionPreset('gentle');
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
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
    const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100);
    camera.position.set(0, 0, 7.5);
    const rig = new THREE.Group();
    rig.scale.setScalar(scale);
    scene.add(rig);

    const palette = readPalette();
    const warm = palette.warm.clone();
    const ink = palette.ink.clone();
    const uniforms = {
      uTime: { value: 0 },
      uPulse: { value: 0 },
      uWarm: { value: warm },
      uDeep: { value: new THREE.Color(palette.light ? '#f3e6dc' : '#140a06') },
      uLight: { value: palette.light ? 1 : 0 },
    };
    const blending = () =>
      uniforms.uLight.value ? THREE.NormalBlending : THREE.AdditiveBlending;
    const bodyMaterial = new THREE.ShaderMaterial({
      uniforms,
      vertexShader: VERTEX,
      fragmentShader: FRAGMENT,
      transparent: true,
      depthWrite: false,
      blending: blending(),
    });
    const body = new THREE.Mesh(
      new THREE.IcosahedronGeometry(1, 40),
      bodyMaterial,
    );
    rig.add(body);
    const shellMaterial = new THREE.LineBasicMaterial({
      color: ink,
      transparent: true,
      opacity: 0.14,
    });
    const shell = new THREE.LineSegments(
      new THREE.WireframeGeometry(new THREE.IcosahedronGeometry(1.5, 1)),
      shellMaterial,
    );
    rig.add(shell);
    const rings = new THREE.Group();
    const ringMaterial = new THREE.LineBasicMaterial({
      color: ink,
      transparent: true,
      opacity: 0.08,
    });
    for (let i = -2; i <= 2; i++) {
      const y = i * 0.5;
      const radius = Math.sqrt(Math.max(0, 1.75 * 1.75 - y * y));
      const points = new THREE.EllipseCurve(0, 0, radius, radius)
        .getPoints(120)
        .map((point) => new THREE.Vector3(point.x, y, point.y));
      rings.add(
        new THREE.LineLoop(
          new THREE.BufferGeometry().setFromPoints(points),
          ringMaterial,
        ),
      );
    }
    rings.rotation.z = 0.35;
    rig.add(rings);
    const texture = glowTexture();
    const glowMaterial = new THREE.SpriteMaterial({
      map: texture,
      color: warm,
      transparent: true,
      depthWrite: false,
      blending: blending(),
    });
    const glow = new THREE.Sprite(glowMaterial);
    glow.scale.setScalar(1.7);
    rig.add(glow);
    const heartMaterial = new THREE.MeshBasicMaterial({
      color: palette.core.clone(),
    });
    rig.add(
      new THREE.Mesh(new THREE.SphereGeometry(0.08, 24, 24), heartMaterial),
    );
    const random = seeded(7);
    const count = 420;
    const positions = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const u = random() * 2 - 1;
      const angle = random() * Math.PI * 2;
      const radius = 2 + random() * 1.6;
      const ring = Math.sqrt(1 - u * u);
      positions[i * 3] = radius * ring * Math.cos(angle);
      positions[i * 3 + 1] = radius * u * 0.8;
      positions[i * 3 + 2] = radius * ring * Math.sin(angle);
    }
    const dustGeometry = new THREE.BufferGeometry();
    dustGeometry.setAttribute(
      'position',
      new THREE.BufferAttribute(positions, 3),
    );
    const dustMaterial = new THREE.PointsMaterial({
      map: texture,
      color: ink,
      size: 0.05,
      transparent: true,
      opacity: 0.5,
      depthWrite: false,
      blending: blending(),
    });
    const dust = new THREE.Points(dustGeometry, dustMaterial);
    rig.add(dust);

    const draw = () => renderer.render(scene, camera);
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

    const tilt = { x: 0, y: 0 };
    const lean = (event: PointerEvent) => {
      tilt.x = (event.clientY / window.innerHeight - 0.5) * 0.3;
      tilt.y = (event.clientX / window.innerWidth - 0.5) * 0.5;
    };
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const delta = Math.min((now - last) / 1000, 0.05);
      last = now;
      const time = (uniforms.uTime.value += delta);
      const breath = Math.sin((time * Math.PI * 2) / BREATH);
      body.scale.setScalar(1 + 0.025 * breath + uniforms.uPulse.value * 0.08);
      shell.rotation.y += delta * 0.08;
      shell.rotation.x += delta * 0.02;
      rings.rotation.y -= delta * 0.05;
      dust.rotation.y += delta * 0.015;
      glowMaterial.opacity =
        (uniforms.uLight.value ? 0.3 : 0.55) +
        0.2 * breath +
        uniforms.uPulse.value * 0.45;
      rig.rotation.x += (tilt.x - rig.rotation.x) * 0.04;
      rig.rotation.y += (tilt.y - rig.rotation.y) * 0.04;
      draw();
      frame = requestAnimationFrame(tick);
    };
    if (!reduced) {
      window.addEventListener('pointermove', lean);
      frame = requestAnimationFrame(tick);
    }

    // A new palette: ease every colour across, and switch how light is mixed when it turns light or dark.
    const recolour = () => {
      const next = readPalette();
      const from = {
        warm: warm.clone(),
        core: heartMaterial.color.clone(),
        ink: ink.clone(),
      };
      uniforms.uLight.value = next.light ? 1 : 0;
      uniforms.uDeep.value.set(next.light ? '#f3e6dc' : '#140a06');
      for (const material of [bodyMaterial, glowMaterial, dustMaterial]) {
        material.blending = blending();
        material.needsUpdate = true;
      }
      const apply = (k: number) => {
        warm.lerpColors(from.warm, next.warm, k);
        heartMaterial.color.lerpColors(from.core, next.core, k);
        ink.lerpColors(from.ink, next.ink, k);
        glowMaterial.color.copy(warm);
        shellMaterial.color.copy(ink);
        ringMaterial.color.copy(ink);
        dustMaterial.color.copy(ink);
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

    pulseRef.current = reduced
      ? null
      : () =>
          void animate(0, 1, {
            duration: 1.4,
            ease: [0.2, 0.7, 0.2, 1],
            onUpdate: (k) => {
              uniforms.uPulse.value = Math.sin(k * Math.PI);
            },
          });

    return () => {
      pulseRef.current = null;
      cancelAnimationFrame(frame);
      window.removeEventListener('pointermove', lean);
      resizer.disconnect();
      themeWatch.disconnect();
      scene.traverse((object) => {
        if (
          object instanceof THREE.Mesh ||
          object instanceof THREE.LineSegments ||
          object instanceof THREE.LineLoop ||
          object instanceof THREE.Points
        )
          object.geometry.dispose();
      });
      for (const material of [
        bodyMaterial,
        shellMaterial,
        ringMaterial,
        glowMaterial,
        heartMaterial,
        dustMaterial,
      ])
        material.dispose();
      texture.dispose();
      renderer.dispose();
    };
  }, [reduced, scale]);

  useEffect(() => {
    if (pulse > 0) pulseRef.current?.();
  }, [pulse]);

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
      className={cn('block', className)}
    />
  );
}
