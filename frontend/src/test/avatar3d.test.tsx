import {
  act,
  fireEvent,
  render as renderView,
  screen,
} from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { MemoryRouter } from 'react-router';
import { About } from '../pages/About';
import { AvatarComparison } from '../features/avatar/AvatarComparison';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import * as THREE from 'three';
import { VRMUtils, type VRM, type VRMMeta } from '@pixiv/three-vrm';
import Avatar3D, { modelCredit } from '../features/avatar/Avatar3D';
import { AvatarPreview } from '../features/avatar/AvatarPreview';
import {
  AvatarMotion,
  BlinkScheduler,
  DampedSpring,
  mouthWeight,
} from '../features/avatar/motion';
import { visibleRenderLoop } from '../features/avatar/renderLoop';

const mocks = vi.hoisted(() => ({
  render: vi.fn(),
  dispose: vi.fn(),
  loss: vi.fn(),
  pixelRatio: vi.fn(),
  load: vi.fn(),
  update: vi.fn(),
  expression: vi.fn(),
  parser: {
    options: {
      manager: undefined,
      crossOrigin: 'anonymous',
      requestHeader: {},
    },
    textureLoader: null as unknown,
  },
  reduced: false,
  unavailable: false,
}));
vi.mock('three', async (original) => {
  const actual = await original<typeof import('three')>();
  return {
    ...actual,
    WebGLRenderer: class {
      domElement = document.createElement('canvas');
      constructor() {
        if (mocks.unavailable) throw new Error('No WebGL');
      }
      setPixelRatio = mocks.pixelRatio;
      setClearColor() {}
      setSize() {}
      render = mocks.render;
      dispose = mocks.dispose;
      forceContextLoss = mocks.loss;
    },
  };
});
vi.mock('three/addons/loaders/GLTFLoader.js', () => ({
  GLTFLoader: class {
    register(plugin: (parser: unknown) => unknown) {
      plugin(mocks.parser);
      return this;
    }
    loadAsync = mocks.load;
  },
}));
vi.mock('@pixiv/three-vrm', async (original) => {
  const actual = await original<typeof import('@pixiv/three-vrm')>();
  return {
    ...actual,
    VRMLoaderPlugin: class {},
    VRMUtils: {
      removeUnnecessaryVertices: vi.fn(),
      combineSkeletons: vi.fn(),
      rotateVRM0: vi.fn(),
      deepDispose: vi.fn(actual.VRMUtils.deepDispose),
    },
  };
});
vi.mock('../design/motion', async (original) => ({
  ...(await original<typeof import('../design/motion')>()),
  useMotionPreset: () => ({ reduced: mocks.reduced }),
}));

let intersection: (entries: { isIntersecting: boolean }[]) => void;
let hidden = false;
let model: VRM;
let geometry: THREE.BoxGeometry;
let material: THREE.MeshBasicMaterial;
let texture: THREE.Texture;
const props = {
  url: '/api/media/avatar.vrm',
  mouth: 3,
  speaking: true,
  onFallback: vi.fn(),
};

beforeEach(() => {
  vi.useFakeTimers();
  hidden = false;
  mocks.reduced = false;
  mocks.unavailable = false;
  Object.defineProperty(document, 'hidden', {
    configurable: true,
    get: () => hidden,
  });
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      constructor(callback: typeof intersection) {
        intersection = callback;
      }
      observe() {}
      disconnect() {}
    },
  );
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) =>
    setTimeout(() => callback(performance.now()), 1000 / 60),
  );
  vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id));
  geometry = new THREE.BoxGeometry(0.4, 1.8, 0.2);
  texture = new THREE.Texture();
  material = new THREE.MeshBasicMaterial({ map: texture });
  const scene = new THREE.Group();
  scene.add(new THREE.Mesh(geometry, material));
  const head = new THREE.Group();
  head.position.y = 1.6;
  const chest = new THREE.Group();
  scene.add(head, chest);
  model = {
    scene,
    meta: {
      metaVersion: '1',
      name: '配置模型',
      authors: ['作者甲', '作者乙'],
      creditNotation: 'required',
      licenseUrl: 'https://example.org/license',
    },
    humanoid: {
      autoUpdateHumanBones: true,
      getRawBoneNode: (name: string) => (name === 'head' ? head : null),
      getNormalizedBoneNode: (name: string) =>
        name === 'head' ? head : name === 'chest' ? chest : null,
    },
    expressionManager: { setValue: mocks.expression },
    lookAt: {},
    update: mocks.update,
  } as unknown as VRM;
  mocks.load.mockResolvedValue({ scene, userData: { vrm: model } });
});
afterEach(() => {
  vi.useRealTimers();
});
const load = async () => {
  await act(async () => {
    await Promise.resolve();
  });
};

it('renders the chat VRM preview once without a motion loop and disposes it', async () => {
  const view = renderView(
    <Avatar3D {...props} mouth={0} speaking={false} still />,
  );
  await load();
  expect(mocks.render).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText('VRM 静态头像')).toHaveAttribute(
    'title',
    '模型：配置模型 · 作者甲、作者乙',
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });
  expect(mocks.render).toHaveBeenCalledTimes(1);
  expect(mocks.expression).not.toHaveBeenCalled();
  view.unmount();
  expect(mocks.dispose).toHaveBeenCalledTimes(1);
  expect(mocks.loss).toHaveBeenCalledTimes(1);
});

it('maps the four mouth levels and uses frame-rate-independent critical damping', () => {
  expect([0, 1, 2, 3].map((level) => mouthWeight(level, true, false))).toEqual([
    0, 0.35, 0.65, 1,
  ]);
  expect(mouthWeight(3, false, false)).toBe(0);
  expect(mouthWeight(NaN, true, false)).toBe(0);
  expect(mouthWeight(3, true, true)).toBe(0.35);
  const spring = new DampedSpring();
  const first = spring.step(1, 1 / 60);
  expect(first).toBeGreaterThan(0);
  expect(first).toBeLessThan(0.1);
  for (let i = 0; i < 120; i++)
    expect(spring.step(1, 1 / 60)).toBeLessThanOrEqual(1);
  expect(spring.value).toBeCloseTo(1);
  const whole = new DampedSpring();
  const halves = new DampedSpring();
  whole.step(1, 1 / 30);
  halves.step(1, 1 / 60);
  halves.step(1, 1 / 60);
  expect(whole.value).toBeCloseTo(halves.value, 10);
  for (let i = 0; i < 120; i++) spring.step(0, 1 / 60);
  expect(spring.value).toBeCloseTo(0);
});

it('schedules natural blinks, double blinks and rare reduced-motion blinks with fake time', () => {
  const blink = new BlinkScheduler(() => 0);
  const start = Date.now();
  const sample = () => blink.step((Date.now() - start) / 1000, false);
  vi.advanceTimersByTime(2499);
  expect(sample()).toBe(0);
  vi.advanceTimersByTime(1);
  expect(sample()).toBe(0);
  vi.advanceTimersByTime(80);
  expect(sample()).toBeCloseTo(1);
  vi.advanceTimersByTime(160);
  expect(sample()).toBeCloseTo(0);
  vi.advanceTimersByTime(80);
  expect(sample()).toBeCloseTo(1);
  vi.advanceTimersByTime(81);
  expect(sample()).toBe(0);
  const rare = new BlinkScheduler(() => 0, true);
  expect(rare.step(6, true)).toBe(0);
  expect(rare.step(8, true)).toBe(0);
  expect(rare.step(8.08, true)).toBeCloseTo(1);
  expect(rare.step(8.32, true)).toBe(0);
  const latest = new BlinkScheduler(() => 1);
  expect(latest.step(5.99, false)).toBe(0);
  expect(latest.step(6, false)).toBe(0);
  expect(latest.step(6.08, false)).toBeCloseTo(1);
});

it('removes breathing, head motion, saccades and vowel variety in reduced motion', () => {
  const motion = new AvatarMotion();
  let pose = motion.step(1 / 60, 3, true, false);
  expect(pose.breath).not.toBe(0);
  for (let i = 0; i < 120; i++) pose = motion.step(1 / 60, 3, true, false);
  expect(pose.aa).toBeCloseTo(1);
  expect(motion.step(1 / 60, 3, true, true).aa).toBeLessThanOrEqual(0.35);
  for (let i = 0; i < 120; i++) pose = motion.step(1 / 60, 3, true, true);
  expect(pose).toMatchObject({
    pitch: 0,
    yaw: 0,
    breath: 0,
    oh: 0,
    ih: 0,
    gaze: { x: 0, y: 0 },
  });
  expect(pose.aa).toBeCloseTo(0.35);
  for (let i = 0; i < 120; i++) pose = motion.step(1 / 60, 3, false, true);
  expect(pose.aa).toBeCloseTo(0);
});

it('starts and stops rendering with intersection and document visibility and cleans up', () => {
  const draw = vi.fn();
  const stop = visibleRenderLoop(document.createElement('div'), draw);
  vi.advanceTimersByTime(100);
  expect(draw).not.toHaveBeenCalled();
  intersection([{ isIntersecting: true }]);
  vi.advanceTimersByTime(1000);
  expect(draw.mock.calls.length).toBeLessThanOrEqual(60);
  expect(draw).toHaveBeenCalled();
  let count = draw.mock.calls.length;
  hidden = true;
  document.dispatchEvent(new Event('visibilitychange'));
  vi.advanceTimersByTime(1000);
  expect(draw).toHaveBeenCalledTimes(count);
  hidden = false;
  document.dispatchEvent(new Event('visibilitychange'));
  vi.advanceTimersByTime(100);
  expect(draw.mock.calls.length).toBeGreaterThan(count);
  count = draw.mock.calls.length;
  intersection([{ isIntersecting: false }]);
  vi.advanceTimersByTime(100);
  expect(draw).toHaveBeenCalledTimes(count);
  intersection([{ isIntersecting: true }]);
  stop();
  vi.advanceTimersByTime(100);
  expect(draw).toHaveBeenCalledTimes(count);
  expect(vi.getTimerCount()).toBe(0);
});

it('reads credit and releases GPU resources on unmount', async () => {
  const geometryDispose = vi.spyOn(geometry, 'dispose');
  const materialDispose = vi.spyOn(material, 'dispose');
  const textureDispose = vi.spyOn(texture, 'dispose');
  const view = renderView(<Avatar3D {...props} />);
  expect(screen.queryByRole('note')).not.toBeInTheDocument();
  await load();
  expect(mocks.parser.textureLoader).toBeInstanceOf(THREE.TextureLoader);
  expect(
    screen.getByText('模型：配置模型 · 作者甲、作者乙', { exact: false }),
  ).toBeVisible();
  expect(screen.getByRole('link', { name: '许可' })).toHaveAttribute(
    'href',
    'https://example.org/license',
  );
  expect(VRMUtils.combineSkeletons).toHaveBeenCalledWith(model.scene);
  expect(VRMUtils.removeUnnecessaryVertices).toHaveBeenCalledWith(model.scene);
  intersection([{ isIntersecting: true }]);
  act(() => vi.advanceTimersByTime(500));
  expect(mocks.render).toHaveBeenCalled();
  expect(mocks.expression).toHaveBeenCalledWith('aa', expect.any(Number));
  expect(model.lookAt?.target).toBeDefined();
  view.unmount();
  expect(geometryDispose).toHaveBeenCalledOnce();
  expect(materialDispose).toHaveBeenCalledOnce();
  expect(textureDispose).toHaveBeenCalledOnce();
  expect(mocks.dispose).toHaveBeenCalledOnce();
  expect(mocks.loss).toHaveBeenCalledOnce();
  expect(vi.getTimerCount()).toBe(0);
});

it('supports legacy VRM credits and rejects unsafe license links', async () => {
  Object.defineProperty(model, 'meta', {
    value: {
      metaVersion: '0',
      title: '旧模型',
      author: '旧作者',
      otherLicenseUrl: 'javascript:alert(1)',
    } as VRMMeta,
  });
  expect(modelCredit(model.meta).text).toBe('模型：旧模型 · 旧作者');
  renderView(<Avatar3D {...props} />);
  await load();
  expect(screen.getByText('模型：旧模型 · 旧作者')).toBeVisible();
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
});

it('falls back on unavailable WebGL, loading errors and context loss', async () => {
  mocks.unavailable = true;
  const first = renderView(<Avatar3D {...props} />);
  expect(props.onFallback).toHaveBeenCalledOnce();
  first.unmount();
  props.onFallback.mockClear();
  mocks.unavailable = false;
  mocks.load.mockRejectedValueOnce(new Error('bad model'));
  const second = renderView(<Avatar3D {...props} />);
  await load();
  expect(props.onFallback).toHaveBeenCalledOnce();
  second.unmount();
  props.onFallback.mockClear();
  renderView(<Avatar3D {...props} />);
  await load();
  act(() =>
    screen.getByRole('img').dispatchEvent(new Event('webglcontextlost')),
  );
  expect(props.onFallback).toHaveBeenCalledOnce();
});

it('disposes a model that finishes loading after unmount', async () => {
  let resolve!: (value: unknown) => void;
  mocks.load.mockReturnValueOnce(
    new Promise((done) => {
      resolve = done;
    }),
  );
  const view = renderView(<Avatar3D {...props} />);
  view.unmount();
  resolve({ scene: model.scene, userData: { vrm: model } });
  await load();
  expect(VRMUtils.deepDispose).toHaveBeenCalledWith(model.scene);
  expect(props.onFallback).not.toHaveBeenCalled();
});

const capabilities = {
  available: false,
  backend: null,
  avatar: {
    schema_version: 1 as const,
    avatar_id: 'default',
    palette: {},
    mouth_states: 4 as const,
    stylized: true as const,
  },
};
it('renders 2D without loading three when the model is unset, and after a 3D failure', async () => {
  const view = renderView(<AvatarPreview capabilities={capabilities} />);
  expect(screen.getByRole('img', { name: '风格化插画' })).toBeVisible();
  expect(mocks.load).not.toHaveBeenCalled();
  mocks.unavailable = true;
  view.rerender(
    <AvatarPreview
      capabilities={{
        ...capabilities,
        avatar_model: { format: 'vrm', url: props.url },
      }}
    />,
  );
  await load();
  expect(screen.getByRole('img', { name: '风格化插画' })).toBeVisible();
});

it('prefers VRM over a portrait and falls back to the portrait after context loss', async () => {
  renderView(
    <AvatarPreview
      capabilities={{
        ...capabilities,
        avatar_image: { url: '/api/media/avatar-image' },
        avatar_model: { format: 'vrm', url: props.url },
      }}
    />,
  );
  await load();
  expect(screen.getByRole('img', { name: '风格化 3D 形象' })).toBeVisible();
  expect(
    screen.queryByRole('img', { name: '肖像形象' }),
  ).not.toBeInTheDocument();
  act(() =>
    screen.getByRole('img').dispatchEvent(new Event('webglcontextlost')),
  );
  expect(screen.getByRole('img', { name: '肖像形象' })).toBeVisible();
});

it('prefers a newly uploaded, cache-busted portrait over the configured VRM', async () => {
  renderView(
    <AvatarPreview
      capabilities={{
        ...capabilities,
        avatar_image: { url: '/api/media/avatar-image?v=portrait-sha' },
        avatar_model: { format: 'vrm', url: props.url },
      }}
    />,
  );
  await load();
  expect(screen.getByRole('img', { name: '肖像形象' })).toBeVisible();
  expect(mocks.load).not.toHaveBeenCalled();
});

it('shares the demo lip track between both previews, replays and releases its timer', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(capabilities), {
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  );
  const view = renderView(<AvatarComparison />);
  await load();
  const mouths = () =>
    screen
      .getAllByRole('img')
      .map((image) => image.getAttribute('data-mouth-level'));
  expect(mouths()).toEqual(['0', '0']);
  act(() => vi.advanceTimersByTime(480));
  expect(mouths()).toEqual(['3', '3']);
  fireEvent.click(screen.getByRole('button', { name: '重播口型演示' }));
  expect(mouths()).toEqual(['0', '0']);
  view.unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it('allows blob textures and local recording playback without relaxing script/connect CSP', () => {
  const source = readFileSync('../src/twin/web/app.py', 'utf8');
  const block = source.match(
    /"Content-Security-Policy": \(([\s\S]*?)\n    \)/,
  )?.[1];
  const csp = [...(block || '').matchAll(/"([^"\n]*)"/g)]
    .map((match) => match[1])
    .join('');
  expect(csp).toBe(
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
  );
  expect(
    csp.split(';').filter((directive) => directive.includes('blob:')),
  ).toEqual([" img-src 'self' data: blob:", " media-src 'self' blob:"]);
});

it.each([
  ['0', false],
  ['1', false],
  ['1', true],
] as const)(
  'shows VRM %s metadata in About and restores the fallback (portrait=%s)',
  async (metaVersion, portrait) => {
    const fallbackName = portrait
      ? '形象：肖像照片'
      : '形象：default（风格化形象）';
    if (metaVersion === '0') {
      Object.defineProperty(model, 'meta', {
        value: { metaVersion: '0', title: '配置模型', author: '配置作者' },
      });
    }
    vi.stubGlobal(
      'fetch',
      vi.fn((path: string) =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              path.startsWith('/api/persona/items')
                ? []
                : path.startsWith('/api/persona/coverage')
                  ? { facets: [], suggestions: [], kind_labels: {} }
                  : path === '/api/identity'
                    ? {
                        name: '配置身份',
                        aliases: [],
                        avatar: 'default',
                        voice: null,
                        egress: [],
                      }
                    : {
                        ...capabilities,
                        avatar_image: portrait
                          ? { url: '/api/media/avatar-image' }
                          : null,
                        avatar_model: { format: 'vrm', url: props.url },
                      },
            ),
            { headers: { 'Content-Type': 'application/json' } },
          ),
        ),
      ),
    );
    let resolve!: (value: unknown) => void;
    mocks.load.mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    );
    renderView(
      <MemoryRouter initialEntries={['/about']}>
        <About />
      </MemoryRouter>,
    );
    await load();
    expect(screen.getByText(fallbackName)).toBeVisible();
    resolve({ scene: model.scene, userData: { vrm: model } });
    await load();
    expect(screen.getByText('形象：配置模型（3D 模型）')).toBeVisible();
    expect(screen.queryByText(fallbackName)).not.toBeInTheDocument();
    act(() =>
      screen
        .getByRole('img', { name: '风格化 3D 形象' })
        .dispatchEvent(new Event('webglcontextlost')),
    );
    expect(screen.getByText(fallbackName)).toBeVisible();
    if (portrait)
      expect(screen.getByRole('img', { name: '肖像形象' })).toBeVisible();
    expect(
      screen.queryByText('形象：配置模型（3D 模型）'),
    ).not.toBeInTheDocument();
  },
);
