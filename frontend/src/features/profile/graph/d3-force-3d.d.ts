declare module 'd3-force-3d' {
  interface Force<Node> {
    (alpha: number): void;
    initialize(nodes: Node[], dimensions?: number): void;
    strength(value: number | ((node: Node) => number)): this;
  }
  interface CollisionForce<Node> extends Force<Node> {
    iterations(value: number): this;
  }
  export function forceRadial<Node>(
    radius: (node: Node) => number,
    x?: number,
    y?: number,
    z?: number,
  ): Force<Node>;
  export function forceCollide<Node>(
    radius: (node: Node) => number,
  ): CollisionForce<Node>;
  export function forceX<Node>(position: (node: Node) => number): Force<Node>;
  export function forceY<Node>(position: (node: Node) => number): Force<Node>;
  export function forceZ<Node>(position: (node: Node) => number): Force<Node>;
}
