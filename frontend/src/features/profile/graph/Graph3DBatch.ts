import * as THREE from 'three';
import { endpointId, type MemoryGraph } from './buildMemoryGraph';
import { ambientParticle } from './layout';
import {
  linkHighlighted,
  linkVisible,
  nodeAlpha,
  type GraphViewProps,
} from './rendering';

// Batch thousands of particles and edges into three draw calls. The force graph
// still owns layout, picking anchors and camera controls, but not per-item meshes.
export class Graph3DBatch {
  readonly group = new THREE.Group();
  private nodes;
  private nodeMap;
  private evidence;
  private positions;
  private edges;
  private flows;
  private geometry = new THREE.BufferGeometry();
  private edgeGeometry = new THREE.BufferGeometry();
  private flowGeometry = new THREE.BufferGeometry();
  private material = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    uniforms: {
      viewport: { value: 600 },
      danger: { value: new THREE.Color() },
    },
    vertexShader: `
      attribute float size;
      attribute float alpha;
      attribute float hollow;
      attribute float conflict;
      attribute float square;
      attribute vec3 color;
      uniform float viewport;
      varying vec3 ink;
      varying float opacity;
      varying float openRing;
      varying float dangerRing;
      varying float squareNode;
      void main() {
        vec4 view = modelViewMatrix * vec4(position, 1.0);
        gl_Position = projectionMatrix * view;
        gl_PointSize = clamp(size * viewport / max(1.0, -view.z), 2.0, 150.0);
        ink = color; opacity = alpha; openRing = hollow;
        dangerRing = conflict; squareNode = square;
      }
    `,
    fragmentShader: `
      uniform vec3 danger;
      varying vec3 ink;
      varying float opacity;
      varying float openRing;
      varying float dangerRing;
      varying float squareNode;
      void main() {
        vec2 uv = abs(gl_PointCoord * 2.0 - 1.0);
        float r = squareNode > 0.5 ? max(max(uv.x, uv.y), (uv.x + uv.y) / 1.65) : length(uv);
        float solid = 1.0 - smoothstep(0.38, 0.48, r);
        float ring = smoothstep(0.32, 0.39, r) * (1.0 - smoothstep(0.44, 0.51, r));
        float glow = exp(-r * r * 5.0) * 0.35;
        float warning = dangerRing * smoothstep(0.60, 0.65, r) * (1.0 - smoothstep(0.71, 0.76, r));
        float body = mix(max(solid, glow), ring, openRing);
        float a = max(body, warning) * opacity;
        if (a < 0.005) discard;
        gl_FragColor = vec4(mix(ink, danger, warning), a);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }
    `,
  });
  private edgeMaterial = new THREE.LineBasicMaterial({
    vertexColors: true,
    transparent: true,
    opacity: 1,
    depthWrite: false,
  });
  private flowMaterial = new THREE.PointsMaterial({
    size: 1.6,
    transparent: true,
    opacity: 0.7,
    depthWrite: false,
  });
  private visibleFlows = new Set<number>();
  private visibleEdges = new Set<number>();
  private viewport = new THREE.Vector2();

  constructor(
    private graph: MemoryGraph,
    private onFrame?: () => void,
  ) {
    this.nodes = graph.nodes.filter(
      (node) => node.kind === 'item' || node.kind === 'source',
    );
    this.nodeMap = new Map(graph.nodes.map((node) => [node.id, node]));
    this.evidence = graph.links.filter((link) => link.kind === 'evidence');
    this.positions = new Float32Array(this.nodes.length * 3);
    this.edges = new Float32Array(graph.links.length * 6);
    this.flows = new Float32Array(this.evidence.length * 3);
    this.geometry.setAttribute(
      'position',
      new THREE.BufferAttribute(this.positions, 3),
    );
    for (const name of ['size', 'alpha', 'hollow', 'conflict', 'square'])
      this.geometry.setAttribute(
        name,
        new THREE.BufferAttribute(new Float32Array(this.nodes.length), 1),
      );
    this.geometry.setAttribute(
      'color',
      new THREE.BufferAttribute(new Float32Array(this.nodes.length * 3), 3),
    );
    this.edgeGeometry.setAttribute(
      'position',
      new THREE.BufferAttribute(this.edges, 3),
    );
    this.edgeGeometry.setAttribute(
      'color',
      new THREE.BufferAttribute(new Float32Array(graph.links.length * 8), 4),
    );
    this.flowGeometry.setAttribute(
      'position',
      new THREE.BufferAttribute(this.flows, 3),
    );
    const particles = new THREE.Points(this.geometry, this.material);
    const edges = new THREE.LineSegments(this.edgeGeometry, this.edgeMaterial);
    const flow = new THREE.Points(this.flowGeometry, this.flowMaterial);
    for (const object of [particles, edges, flow]) object.frustumCulled = false;
    particles.onBeforeRender = (renderer) => {
      this.material.uniforms.viewport.value =
        renderer.getSize(this.viewport).y * renderer.getPixelRatio();
      this.move();
      this.onFrame?.();
    };
    this.group.add(particles, edges, flow);
  }
  update(props: GraphViewProps) {
    const color = new THREE.Color();
    this.nodes.forEach((node, index) => {
      color.set(props.palette[node.colorToken]);
      this.geometry
        .getAttribute('color')
        .setXYZ(index, color.r, color.g, color.b);
      this.geometry
        .getAttribute('alpha')
        .setX(index, props.visible.has(node.id) ? nodeAlpha(node, props) : 0);
      const highlighted = props.highlighted?.has(node.id);
      this.geometry
        .getAttribute('size')
        .setX(index, node.size * (highlighted ? 5 : 4));
      this.geometry
        .getAttribute('hollow')
        .setX(index, node.review === 'unreviewed' ? 1 : 0);
      this.geometry.getAttribute('conflict').setX(index, node.conflict ? 1 : 0);
      this.geometry
        .getAttribute('square')
        .setX(index, node.kind === 'source' ? 1 : 0);
    });
    this.visibleEdges.clear();
    this.graph.links.forEach((link, index) => {
      if (linkVisible(link, props.visible)) this.visibleEdges.add(index);
      color.set(
        props.palette[
          link.kind === 'conflict' ? '--graph-danger' : '--graph-source'
        ],
      );
      const opacity = !linkVisible(link, props.visible)
        ? 0
        : linkHighlighted(link, props.highlighted)
          ? 0.7
          : link.kind === 'evidence'
            ? 0.06
            : 0.15;
      this.edgeGeometry
        .getAttribute('color')
        .setXYZW(index * 2, color.r, color.g, color.b, opacity);
      this.edgeGeometry
        .getAttribute('color')
        .setXYZW(index * 2 + 1, color.r, color.g, color.b, opacity);
    });
    this.visibleFlows.clear();
    this.evidence.forEach((link, index) => {
      if (
        linkVisible(link, props.visible) &&
        (linkHighlighted(link, props.highlighted) || ambientParticle(link))
      )
        this.visibleFlows.add(index);
    });
    for (const attribute of Object.values(this.geometry.attributes))
      attribute.needsUpdate = true;
    this.edgeGeometry.getAttribute('color').needsUpdate = true;
    this.material.uniforms.danger.value.set(props.palette['--graph-danger']);
    this.flowMaterial.color.set(props.palette['--graph-center']);
    this.move();
  }
  private move() {
    this.nodes.forEach((node, i) => {
      this.positions[i * 3] = node.x ?? 0;
      this.positions[i * 3 + 1] = node.y ?? 0;
      this.positions[i * 3 + 2] = node.z ?? 0;
    });
    this.graph.links.forEach((link, i) => {
      const a = this.nodeMap.get(endpointId(link.source))!;
      const b = this.nodeMap.get(endpointId(link.target))!;
      const visible = this.visibleEdges.has(i);
      this.edges[i * 6] = visible ? (a.x ?? 0) : 1e8;
      this.edges[i * 6 + 1] = visible ? (a.y ?? 0) : 1e8;
      this.edges[i * 6 + 2] = visible ? (a.z ?? 0) : 1e8;
      this.edges[i * 6 + 3] = visible ? (b.x ?? 0) : 1e8;
      this.edges[i * 6 + 4] = visible ? (b.y ?? 0) : 1e8;
      this.edges[i * 6 + 5] = visible ? (b.z ?? 0) : 1e8;
    });
    const time = performance.now() * 0.00005;
    this.evidence.forEach((link, i) => {
      if (!this.visibleFlows.has(i)) {
        this.flows[i * 3] = this.flows[i * 3 + 1] = this.flows[i * 3 + 2] = 1e8;
        return;
      }
      const a = this.nodeMap.get(endpointId(link.source))!;
      const b = this.nodeMap.get(endpointId(link.target))!;
      const t = (time + i * 0.618) % 1;
      this.flows[i * 3] = (a.x ?? 0) + ((b.x ?? 0) - (a.x ?? 0)) * t;
      this.flows[i * 3 + 1] = (a.y ?? 0) + ((b.y ?? 0) - (a.y ?? 0)) * t;
      this.flows[i * 3 + 2] = (a.z ?? 0) + ((b.z ?? 0) - (a.z ?? 0)) * t;
    });
    this.geometry.getAttribute('position').needsUpdate = true;
    this.edgeGeometry.getAttribute('position').needsUpdate = true;
    this.flowGeometry.getAttribute('position').needsUpdate = true;
  }
  dispose() {
    this.group.removeFromParent();
    this.geometry.dispose();
    this.edgeGeometry.dispose();
    this.flowGeometry.dispose();
    this.material.dispose();
    this.edgeMaterial.dispose();
    this.flowMaterial.dispose();
  }
}
