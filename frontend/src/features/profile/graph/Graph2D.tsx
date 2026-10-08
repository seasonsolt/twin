import { useCallback, useEffect, useRef } from 'react';
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d';
import type { MemoryLink, MemoryNode } from './buildMemoryGraph';
import { ambientParticle, configureRadialForces } from './layout';
import { paintTwinPortrait, usePortrait } from './portrait';
import {
  linkHighlighted,
  linkVisible,
  nodeAlpha,
  tooltip,
  useGraphLayout,
  type GraphViewProps,
} from './rendering';

function path(
  ctx: CanvasRenderingContext2D,
  node: MemoryNode,
  radius = node.size,
) {
  ctx.beginPath();
  if (node.kind === 'source')
    ctx.rect(
      (node.x ?? 0) - radius,
      (node.y ?? 0) - radius,
      radius * 2,
      radius * 2,
    );
  else ctx.arc(node.x ?? 0, node.y ?? 0, radius, 0, Math.PI * 2);
}
export default function Graph2D(props: GraphViewProps) {
  const layout = useGraphLayout(props.graph, 2);
  const fg = useRef<ForceGraphMethods<MemoryNode, MemoryLink> | undefined>(
    undefined,
  );
  const portrait = usePortrait(
    props.graph.nodes.find((node) => node.kind === 'twin')?.portrait,
  );
  const latest = useRef(props);
  useEffect(() => {
    latest.current = props;
  });
  useEffect(() => {
    const graph = fg.current;
    graph?.resumeAnimation();
    const visibility = () => {
      if (document.hidden) graph?.pauseAnimation();
      else graph?.resumeAnimation();
    };
    document.addEventListener('visibilitychange', visibility);
    return () => {
      document.removeEventListener('visibilitychange', visibility);
      graph?.pauseAnimation();
    };
  }, []);
  useEffect(() => {
    if (!fg.current) return;
    configureRadialForces(fg.current, 2);
    fg.current.d3ReheatSimulation();
  }, [layout]);
  const fit = useCallback(() => {
    const state = latest.current;
    const fontSize = state.width < 500 ? 14 : 15;
    const labelPadding = Math.max(
      0,
      ...state.graph.nodes
        .filter(
          (node) => node.kind === 'dimension' && state.visible.has(node.id),
        )
        .map((node) => Math.min(node.label.length, 33) * fontSize * 0.85 + 10),
    );
    fg.current?.zoomToFit(
      state.reduced ? 0 : 500,
      Math.max(Math.min(state.width, state.height) * 0.1, labelPadding),
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
    const node = layout.nodes.find((node) => node.id === props.focus!.id);
    if (!node) return;
    const duration = props.reduced ? 0 : 500;
    if (node.kind === 'dimension')
      fg.current?.zoomToFit(
        duration,
        65,
        (candidate) => candidate.dimensionId === node.dimensionId,
      );
    else {
      fg.current?.centerAt(node.x, node.y, duration);
      fg.current?.zoom(3, duration);
    }
  }, [props.focus, props.reduced, layout]);
  return (
    <ForceGraph2D<MemoryNode, MemoryLink>
      ref={fg}
      graphData={layout}
      width={props.width}
      height={props.height}
      backgroundColor={props.palette['--graph-backdrop']}
      nodeVisibility={(node) => props.visible.has(node.id)}
      nodeLabel={tooltip}
      nodeCanvasObject={(node, ctx, scale) => {
        ctx.save();
        ctx.globalAlpha = nodeAlpha(node, props);
        const color = props.palette[node.colorToken];
        const x = node.x ?? 0,
          y = node.y ?? 0;
        if (node.kind === 'twin')
          paintTwinPortrait(
            ctx,
            x,
            y,
            node.size,
            node.label,
            color,
            props.palette['--graph-backdrop'],
            portrait,
          );
        else {
          ctx.fillStyle = color;
          ctx.strokeStyle = color;
          ctx.lineWidth = 1.5 / scale;
          const solid = node.review !== 'unreviewed';
          ctx.shadowColor = color;
          ctx.shadowBlur =
            props.highlighted?.has(node.id) || node.kind === 'dimension'
              ? 16
              : solid
                ? 4
                : 0;
          path(ctx, node);
          if (solid) ctx.fill();
          else ctx.stroke();
          ctx.shadowBlur = 0;
          if (node.conflict) {
            path(ctx, node, node.size + 2);
            ctx.strokeStyle = props.palette['--graph-danger'];
            ctx.stroke();
          }
        }
        if (
          node.kind === 'dimension' ||
          node.kind === 'twin' ||
          node.id === props.labelled
        ) {
          ctx.globalAlpha = 1;
          ctx.font = `${node.kind === 'dimension' || node.kind === 'twin' ? '600 ' : ''}${(node.kind === 'dimension' || node.kind === 'twin' ? (props.width < 500 ? 14 : 15) : 13) / scale}px sans-serif`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          let labelX = x,
            labelY = y + node.size + 16 / scale;
          if (node.kind === 'dimension') {
            const angle = node.layoutAngle ?? 0;
            labelX = x + Math.cos(angle) * (node.size + 10 / scale);
            labelY = y + Math.sin(angle) * (node.size + 10 / scale);
            ctx.textAlign =
              Math.cos(angle) > 0.3
                ? 'left'
                : Math.cos(angle) < -0.3
                  ? 'right'
                  : 'center';
          }
          const label =
            node.label.length > 32 ? `${node.label.slice(0, 32)}…` : node.label;
          ctx.strokeStyle = props.palette['--graph-backdrop'];
          ctx.lineWidth = 4 / scale;
          ctx.lineJoin = 'round';
          ctx.shadowColor = props.palette['--graph-backdrop'];
          ctx.shadowBlur = 4;
          ctx.strokeText(label, labelX, labelY);
          ctx.fillStyle = props.palette['--graph-ink'];
          ctx.fillText(label, labelX, labelY);
        }
        ctx.restore();
      }}
      nodePointerAreaPaint={(node, color, ctx) => {
        ctx.fillStyle = color;
        path(ctx, node, Math.max(node.size, 6));
        ctx.fill();
      }}
      linkVisibility={(link) => linkVisible(link, props.visible)}
      linkColor={(link) =>
        `${props.palette[link.kind === 'conflict' ? '--graph-danger' : '--graph-source']}${linkHighlighted(link, props.highlighted) ? 'b3' : link.kind === 'evidence' ? '0f' : '26'}`
      }
      linkWidth={(link) =>
        linkHighlighted(link, props.highlighted) ? 1.5 : 0.4
      }
      linkLineDash={(link) => (link.kind === 'conflict' ? [3, 3] : null)}
      linkDirectionalParticles={(link) =>
        !props.reduced &&
        link.kind === 'evidence' &&
        (linkHighlighted(link, props.highlighted) || ambientParticle(link))
          ? 1
          : 0
      }
      linkDirectionalParticleColor={(link) =>
        `${props.palette['--graph-source']}${linkHighlighted(link, props.highlighted) ? 'cc' : '66'}`
      }
      linkDirectionalParticleWidth={1.5}
      linkDirectionalParticleSpeed={0.0025}
      warmupTicks={0}
      cooldownTicks={140}
      d3AlphaDecay={0.035}
      onEngineStop={fit}
      onNodeClick={props.onClick}
      onNodeHover={props.onHover}
      onBackgroundClick={props.onClear}
    />
  );
}
