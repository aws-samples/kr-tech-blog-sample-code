import React, { useRef, useEffect, useCallback } from "react";
import * as d3 from "d3";
import {
  STATUS_COLORS,
  PHASE_COLORS,
  type ModuleConfig,
  type Phase,
} from "../data/pipeline-config";

interface PipelineMapProps {
  modules: ModuleConfig[];
  onModuleSelect: (module: ModuleConfig) => void;
  selectedModuleId: string | null;
}

interface NodeLayout {
  module: ModuleConfig;
  x: number;
  y: number;
}

const NODE_WIDTH = 160;
const NODE_HEIGHT = 92;
const NODE_RADIUS = 12;
const H_GAP = 72;
const V_GAP = 34;
const PADDING_LEFT = 60;
const PADDING_TOP = 80;

const PHASE_ORDER: Phase[] = ["ingest", "curate", "augment", "train", "validate"];

function computeLayout(modules: ModuleConfig[]): NodeLayout[] {
  const phaseOrder = PHASE_ORDER;
  const phaseGroups = new Map<Phase, ModuleConfig[]>();

  for (const phase of phaseOrder) {
    phaseGroups.set(phase, []);
  }
  for (const mod of modules) {
    phaseGroups.get(mod.phase)?.push(mod);
  }

  const layouts: NodeLayout[] = [];
  let xOffset = PADDING_LEFT;

  // Center every column against the tallest column so a fan-out (e.g. the
  // curate column holding 3 modules) never overflows the SVG viewBox.
  const maxRows = Math.max(
    1,
    ...phaseOrder.map((p) => phaseGroups.get(p)?.length ?? 0)
  );

  for (const phase of phaseOrder) {
    const group = phaseGroups.get(phase) ?? [];
    const colHeight = group.length * (NODE_HEIGHT + V_GAP) - V_GAP;
    const yStart = PADDING_TOP + (maxRows * (NODE_HEIGHT + V_GAP) - colHeight) / 2;

    for (let i = 0; i < group.length; i++) {
      layouts.push({
        module: group[i],
        x: xOffset,
        y: yStart + i * (NODE_HEIGHT + V_GAP),
      });
    }

    xOffset += NODE_WIDTH + H_GAP;
  }

  return layouts;
}

/** "m02-cosmos-reason" -> "M2" (module id badge shown on each node). */
function moduleLabel(id: string): string {
  const m = id.match(/^m0*(\d+)/i);
  return m ? `M${m[1]}` : id.toUpperCase();
}

function getStatusIcon(status: ModuleConfig["status"]): string {
  switch (status) {
    case "completed":
      return "✓";
    case "in-progress":
      return "●";
    case "locked":
      return "■";
  }
}

export function PipelineMap({ modules, onModuleSelect, selectedModuleId }: PipelineMapProps): React.JSX.Element {
  const svgRef = useRef<SVGSVGElement>(null);
  const layouts = computeLayout(modules);

  const handleNodeClick = useCallback(
    (module: ModuleConfig) => {
      onModuleSelect(module);
    },
    [onModuleSelect]
  );

  useEffect(() => {
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const width = layouts.length > 0
      ? Math.max(...layouts.map((l) => l.x)) + NODE_WIDTH + PADDING_LEFT + 40
      : 1200;
    // Height must fit the tallest column (bottom of the lowest node + padding).
    const maxNodeBottom = layouts.length > 0
      ? Math.max(...layouts.map((l) => l.y)) + NODE_HEIGHT
      : 400;
    const height = maxNodeBottom + 40;

    svg.attr("viewBox", `0 0 ${width} ${height}`).attr("width", "100%").attr("height", height);

    // Draw phase labels
    const phaseOrder = PHASE_ORDER;
    const phaseLabels: Record<Phase, string> = {
      ingest: "INGEST",
      curate: "CURATE",
      augment: "AUGMENT",
      train: "TRAIN",
      validate: "VALIDATE",
    };

    let labelX = PADDING_LEFT;
    for (const phase of phaseOrder) {
      const group = modules.filter((m) => m.phase === phase);
      if (group.length === 0) continue;

      svg
        .append("text")
        .attr("x", labelX + NODE_WIDTH / 2)
        .attr("y", 30)
        .attr("text-anchor", "middle")
        .attr("font-size", "11px")
        .attr("font-weight", "700")
        .attr("letter-spacing", "1px")
        .attr("fill", PHASE_COLORS[phase])
        .text(phaseLabels[phase]);

      svg
        .append("line")
        .attr("x1", labelX)
        .attr("y1", 42)
        .attr("x2", labelX + NODE_WIDTH)
        .attr("y2", 42)
        .attr("stroke", PHASE_COLORS[phase])
        .attr("stroke-width", 2)
        .attr("opacity", 0.4);

      labelX += NODE_WIDTH + H_GAP;
    }

    // Draw arrows between connected modules
    const layoutMap = new Map<string, NodeLayout>();
    for (const layout of layouts) {
      layoutMap.set(layout.module.id, layout);
    }

    const arrowGroup = svg.append("g").attr("class", "arrows");

    // One arrowhead marker per phase color, so an edge's head matches its line.
    const defs = svg.append("defs");
    const markerColors: Record<string, string> = {
      same: "#7d56c2",
      fwd: "#adb5bd",
    };
    for (const [key, color] of Object.entries(markerColors)) {
      defs
        .append("marker")
        .attr("id", `arrowhead-${key}`)
        .attr("viewBox", "0 0 10 10")
        .attr("refX", 9)
        .attr("refY", 5)
        .attr("markerWidth", 7)
        .attr("markerHeight", 7)
        .attr("orient", "auto")
        .append("path")
        .attr("d", "M 0 0 L 10 5 L 0 10 Z")
        .attr("fill", color);
    }

    // Count fan-out per source and fan-in per target so we can spread the
    // connection points along each node's edge instead of stacking them at the
    // center (which made M2->M3/M4 and M3->M5/5/6/9 overlap into one blob).
    const inCount = new Map<string, number>();
    const inIndex = new Map<string, number>();
    for (const layout of layouts) {
      for (const targetId of layout.module.feedsModules) {
        if (!layoutMap.has(targetId)) continue;
        inCount.set(targetId, (inCount.get(targetId) ?? 0) + 1);
      }
    }

    // Spread N points across a node edge of the given height (padded).
    const spread = (i: number, n: number, top: number, h: number): number => {
      if (n <= 1) return top + h / 2;
      const pad = 16;
      return top + pad + ((h - 2 * pad) * i) / (n - 1);
    };

    for (const layout of layouts) {
      const feeds = layout.module.feedsModules.filter((t) => layoutMap.has(t));
      const nOut = feeds.length;
      feeds.forEach((targetId, k) => {
        const target = layoutMap.get(targetId)!;
        const oi = k; // exit slot index on the source's right edge

        const nIn = inCount.get(targetId) ?? 1;
        const ii = inIndex.get(targetId) ?? 0;
        inIndex.set(targetId, ii + 1);

        const sameColumn = Math.abs(target.x - layout.x) < 1;
        const locked = target.module.status === "locked";
        const color = sameColumn ? markerColors.same : markerColors.fwd;
        const marker = sameColumn ? "arrowhead-same" : "arrowhead-fwd";

        let d: string;
        if (sameColumn) {
          // Same-column feed (e.g. M2 -> M3 / M4): route out to the right, curve
          // down/up, and come back into the target's LEFT edge — avoids the
          // near-vertical overlap of edge-to-edge lines.
          const y1 = spread(oi, nOut, layout.y, NODE_HEIGHT);
          const y2 = spread(ii, nIn, target.y, NODE_HEIGHT);
          const x1 = layout.x + NODE_WIDTH;
          const x2 = target.x;
          const bulge = 34;
          d = `M ${x1} ${y1} C ${x1 + bulge} ${y1}, ${x2 - bulge} ${y2}, ${x2} ${y2}`;
        } else {
          // Forward feed to a later column: spread exit points down the source's
          // right edge and entry points down the target's left edge.
          const y1 = spread(oi, nOut, layout.y, NODE_HEIGHT);
          const y2 = spread(ii, nIn, target.y, NODE_HEIGHT);
          const x1 = layout.x + NODE_WIDTH;
          const x2 = target.x;
          const midX = (x1 + x2) / 2;
          d = `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`;
        }

        arrowGroup
          .append("path")
          .attr("d", d)
          .attr("fill", "none")
          .attr("stroke", color)
          .attr("stroke-width", 2)
          .attr("opacity", sameColumn ? 0.85 : 0.7)
          .attr("stroke-dasharray", locked ? "4,4" : "none")
          .attr("marker-end", `url(#${marker})`);
      });
    }

    // (legacy single arrowhead kept for any other callers)
    svg
      .append("defs")
      .append("marker")
      .attr("id", "arrowhead")
      .attr("viewBox", "0 0 10 10")
      .attr("refX", 9)
      .attr("refY", 5)
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M 0 0 L 10 5 L 0 10 Z")
      .attr("fill", "#adb5bd");

    // Draw nodes
    const nodeGroup = svg.append("g").attr("class", "nodes");

    for (const layout of layouts) {
      const { module, x, y } = layout;
      const isSelected = module.id === selectedModuleId;
      const statusColor = STATUS_COLORS[module.status];

      const g = nodeGroup
        .append("g")
        .attr("class", "pipeline-node")
        .attr("cursor", "pointer")
        .on("click", () => handleNodeClick(module));

      // Node background
      g.append("rect")
        .attr("x", x)
        .attr("y", y)
        .attr("width", NODE_WIDTH)
        .attr("height", NODE_HEIGHT)
        .attr("rx", NODE_RADIUS)
        .attr("ry", NODE_RADIUS)
        .attr("fill", "#ffffff")
        .attr("stroke", isSelected ? "#0972d3" : statusColor)
        .attr("stroke-width", isSelected ? 3 : 2)
        .attr("filter", isSelected ? "drop-shadow(0 2px 8px rgba(9,114,211,0.3))" : "drop-shadow(0 1px 3px rgba(0,0,0,0.1))");

      // Status indicator bar (top)
      g.append("rect")
        .attr("x", x + 1)
        .attr("y", y + 1)
        .attr("width", NODE_WIDTH - 2)
        .attr("height", 4)
        .attr("rx", NODE_RADIUS)
        .attr("ry", NODE_RADIUS)
        .attr("fill", statusColor);

      // Clip the bottom of the top bar
      g.append("rect")
        .attr("x", x + 1)
        .attr("y", y + 3)
        .attr("width", NODE_WIDTH - 2)
        .attr("height", 3)
        .attr("fill", statusColor);

      // Module ID badge (top-left, e.g. "M2") — pill filled with the phase color
      const idText = moduleLabel(module.id);
      const idW = 16 + idText.length * 7;
      g.append("rect")
        .attr("x", x + 10)
        .attr("y", y + 12)
        .attr("width", idW)
        .attr("height", 18)
        .attr("rx", 9)
        .attr("ry", 9)
        .attr("fill", PHASE_COLORS[module.phase]);
      g.append("text")
        .attr("x", x + 10 + idW / 2)
        .attr("y", y + 24)
        .attr("text-anchor", "middle")
        .attr("font-size", "11px")
        .attr("font-weight", "700")
        .attr("fill", "#ffffff")
        .text(idText);

      // Module title (nudged down to sit below the ID badge)
      g.append("text")
        .attr("x", x + NODE_WIDTH / 2)
        .attr("y", y + 46)
        .attr("text-anchor", "middle")
        .attr("font-size", "12px")
        .attr("font-weight", "600")
        .attr("fill", "#16191f")
        .text(module.title.length > 18 ? module.title.slice(0, 16) + "…" : module.title);

      // Tool name
      g.append("text")
        .attr("x", x + NODE_WIDTH / 2)
        .attr("y", y + 61)
        .attr("text-anchor", "middle")
        .attr("font-size", "10px")
        .attr("fill", "#5f6b7a")
        .text(module.tool.length > 22 ? module.tool.slice(0, 20) + "…" : module.tool);

      // Status badge
      const badgeWidth = 20;
      const badgeX = x + NODE_WIDTH - badgeWidth - 8;
      const badgeY = y + NODE_HEIGHT - 22;

      g.append("circle")
        .attr("cx", badgeX + badgeWidth / 2)
        .attr("cy", badgeY + 6)
        .attr("r", 9)
        .attr("fill", statusColor)
        .attr("opacity", 0.15);

      g.append("text")
        .attr("x", badgeX + badgeWidth / 2)
        .attr("y", badgeY + 10)
        .attr("text-anchor", "middle")
        .attr("font-size", "11px")
        .attr("font-weight", "700")
        .attr("fill", statusColor)
        .text(getStatusIcon(module.status));

      // Estimated time
      g.append("text")
        .attr("x", x + 12)
        .attr("y", y + NODE_HEIGHT - 10)
        .attr("font-size", "9px")
        .attr("fill", "#687078")
        .text(`${module.estimatedMinutes}min`);
    }
  }, [layouts, selectedModuleId, handleNodeClick]);

  return (
    <div style={{ width: "100%", overflowX: "auto", padding: "16px 0" }}>
      <svg ref={svgRef} style={{ display: "block", margin: "0 auto" }} />
    </div>
  );
}
